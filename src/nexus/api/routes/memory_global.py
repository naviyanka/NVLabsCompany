"""Company-wide memory endpoints — list, stats, detail, update, delete, archive, health."""

import uuid
from datetime import timedelta
from typing import Any

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import func, select, update

from nexus.api.deps import CurrentCompanyId, CurrentPrincipal, DbSession, PathCompanyId
from nexus.api.routes.memory import (
    audit_memory_review,
    is_memory_reviewer,
    principal_actor,
    require_memory_reviewer,
)
from nexus.memory.ingest import (
    MemoryContext,
    MemoryInput,
    MemoryOpError,
    Origin,
    clean_user_metadata,
    http_error,
    normalize_content,
)
from nexus.memory.lifecycle import archive_memory, supersede_memory
from nexus.memory.safety import MemoryRejected, sanitize_text
from nexus.models._time import utcnow
from nexus.models.memory import LIVE_STATUSES, MEMORY_STATUSES, PROMPT_STATUSES, MemoryRecord

router = APIRouter(tags=["memory"])


class MemoryUpdate(BaseModel):
    content: str | None = None
    importance: float | None = None
    tier: str | None = None


@router.get("/api/v1/companies/{company_id}/memory")
async def list_all_memories(
    company_id: PathCompanyId, db: DbSession, principal: CurrentPrincipal,
    agent_id: uuid.UUID | None = None, scope: str | None = None,
    tier: str | None = None, importance_min: float | None = None,
    state: str | None = Query(default=None, alias="status"),
    limit: int = 50, offset: int = 0,
) -> list[dict[str, Any]]:
    """List memories across agents for a company: ``active`` unless ``status`` names one state.

    Candidates, archived, superseded and rejected rows appear only when requested with
    ``?status=<state>``, the human review path: a human administrator only (403 otherwise),
    audited with ids and status, never content. Before this, the default also listed
    candidates.
    """
    if state is not None and state not in MEMORY_STATUSES:
        raise HTTPException(
            status_code=422,
            detail={"code": "MEMORY_STATUS_INVALID", "message": "Unknown memory status"},
        )
    reviewing = state is not None and state not in PROMPT_STATUSES
    if reviewing:
        require_memory_reviewer(principal)
    stmt = select(MemoryRecord).where(MemoryRecord.company_id == company_id)
    stmt = stmt.where(
        MemoryRecord.status == (state or PROMPT_STATUSES[0])
    )
    if agent_id:
        stmt = stmt.where(MemoryRecord.agent_id == agent_id)
    if scope:
        stmt = stmt.where(MemoryRecord.scope == scope)
    if tier:
        stmt = stmt.where(MemoryRecord.tier == tier)
    if importance_min is not None:
        stmt = stmt.where(MemoryRecord.importance >= importance_min)
    stmt = stmt.order_by(MemoryRecord.created_at.desc()).offset(offset).limit(limit)
    result = await db.execute(stmt)
    memories = result.scalars().all()
    if reviewing:
        await audit_memory_review(
            db, principal, company_id, f"company_list:{state}", [m.id for m in memories]
        )
    return [
        {
            "id": str(m.id),
            "agent_id": str(m.agent_id) if m.agent_id else None,
            "scope": m.scope,
            "content": m.content,
            "importance": m.importance,
            "tier": m.tier,
            "access_count": m.access_count,
            "created_at": m.created_at.isoformat(),
            "status": m.status,
            "trust_state": m.trust_state,
            "memory_type": m.memory_type,
        }
        for m in memories
    ]


@router.get("/api/v1/companies/{company_id}/memory/stats")
async def memory_stats(company_id: PathCompanyId, db: DbSession) -> dict[str, Any]:
    """Memory statistics for active memory: totals, by tier, by scope, avg importance; plus counts by status (all states)."""
    live = (MemoryRecord.company_id == company_id, MemoryRecord.status.in_(PROMPT_STATUSES))
    total = await db.execute(select(func.count(MemoryRecord.id)).where(*live))
    by_tier = await db.execute(
        select(MemoryRecord.tier, func.count(MemoryRecord.id)).where(*live).group_by(MemoryRecord.tier)
    )
    by_scope = await db.execute(
        select(MemoryRecord.scope, func.count(MemoryRecord.id)).where(*live).group_by(MemoryRecord.scope)
    )
    by_status = await db.execute(
        select(MemoryRecord.status, func.count(MemoryRecord.id))
        .where(MemoryRecord.company_id == company_id)
        .group_by(MemoryRecord.status)
    )
    avg_imp = await db.execute(select(func.avg(MemoryRecord.importance)).where(*live))
    agents_with_mem = await db.execute(
        select(func.count(func.distinct(MemoryRecord.agent_id))).where(*live)
    )
    return {
        "total": total.scalar() or 0,
        "by_tier": dict(by_tier.all()),
        "by_scope": dict(by_scope.all()),
        "by_status": dict(by_status.all()),
        "avg_importance": round(avg_imp.scalar() or 0, 2),
        "agents_with_memory": agents_with_mem.scalar() or 0,
    }


@router.get("/api/v1/memory/{memory_id}")
async def get_memory(
    memory_id: uuid.UUID, db: DbSession, company_id: CurrentCompanyId, principal: CurrentPrincipal
) -> dict[str, Any]:
    """Get one memory by ID: active for any caller; a candidate or closed row only for a reviewer.

    For anyone else a non-active row is a 404, the same answer as an unknown or foreign id, so
    the route is no oracle for closed memory. A reviewer's read is audited without content.
    """
    stmt = select(MemoryRecord).where(MemoryRecord.id == memory_id, MemoryRecord.company_id == company_id)
    result = await db.execute(stmt)
    m = result.scalar_one_or_none()
    if not m or (m.status not in PROMPT_STATUSES and not is_memory_reviewer(principal)):
        raise HTTPException(status_code=404, detail="Memory not found")
    if m.status not in PROMPT_STATUSES:
        await audit_memory_review(db, principal, m.id, f"detail:{m.status}", [m.id])
    return {
        "id": str(m.id),
        "agent_id": str(m.agent_id) if m.agent_id else None,
        "scope": m.scope,
        "scope_id": str(m.scope_id) if m.scope_id else None,
        "content": m.content,
        "record_metadata": m.record_metadata,
        "importance": m.importance,
        "access_count": m.access_count,
        "tier": m.tier,
        "created_at": m.created_at.isoformat(),
        "updated_at": m.updated_at.isoformat(),
        "status": m.status,
        "trust_state": m.trust_state,
        "memory_type": m.memory_type,
        "supersedes_id": str(m.supersedes_id) if m.supersedes_id else None,
        "source_type": m.source_type,
        "source_id": m.source_id,
    }


async def _editable(db: Any, company_id: uuid.UUID, memory_id: uuid.UUID) -> MemoryRecord:
    """A non-executive memory of this company. Executive memory changes only through ceo_service."""
    record = (
        await db.execute(
            select(MemoryRecord).where(
                MemoryRecord.id == memory_id,
                MemoryRecord.company_id == company_id,
                MemoryRecord.scope != "executive",
            )
        )
    ).scalar_one_or_none()
    if record is None:
        raise HTTPException(status_code=404, detail="Memory not found")
    return record


@router.patch("/api/v1/memory/{memory_id}")
async def update_memory(
    memory_id: uuid.UUID, body: MemoryUpdate, db: DbSession, company_id: CurrentCompanyId,
    principal: CurrentPrincipal,
) -> dict:
    """Change importance or tier in place; a content change appends a superseding memory.

    Memory text is append-only, so an edit never rewrites the stored row: it creates a
    new record (redacted and bounded like any ingest) and marks the old one superseded.
    The response ``id`` is the current record; ``superseded_id`` names the replaced one.
    """
    updates = body.model_dump(exclude_unset=True)
    if not updates:
        raise HTTPException(status_code=400, detail="No fields to update")
    record = await _editable(db, company_id, memory_id)
    ctx = MemoryContext(company_id, principal_actor(principal))

    content = updates.pop("content", None)
    try:
        if content is not None:
            clean, _ = sanitize_text(content, max_len=4000)
            content = normalize_content(clean)
        if content is not None and content != record.content:
            new = MemoryInput(
                scope=record.scope,
                content=content,
                memory_type=record.memory_type,
                agent_id=record.agent_id,
                scope_id=record.scope_id,
                importance=updates.get("importance", record.importance),
                tier=updates.get("tier", record.tier),
                metadata=clean_user_metadata(record.record_metadata),
                content_max=4000,
            )
            result = await supersede_memory(db, ctx, memory_id, new, Origin.API)
            return {
                "id": str(result.record.id), "updated": True, "superseded_id": str(memory_id)
            }
    except (MemoryRejected, MemoryOpError) as exc:
        raise http_error(exc) from exc
    if updates:
        # Scoring fields only, and only on a live row: a closed row stays as it was closed.
        changed = await db.execute(
            update(MemoryRecord)
            .where(
                MemoryRecord.id == memory_id,
                MemoryRecord.company_id == company_id,
                MemoryRecord.status.in_(LIVE_STATUSES),
            )
            .values(
                importance=updates.get("importance", MemoryRecord.importance),
                tier=updates.get("tier", MemoryRecord.tier),
                updated_at=utcnow(),
            )
        )
        if changed.rowcount != 1:
            raise HTTPException(
                status_code=409,
                detail={"code": "MEMORY_INVALID_TRANSITION", "message": "Closed memory cannot be edited"},
            )
    return {"id": str(memory_id), "updated": True}


@router.delete("/api/v1/memory/{memory_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_memory(
    memory_id: uuid.UUID, db: DbSession, company_id: CurrentCompanyId, principal: CurrentPrincipal
) -> None:
    """Retire a memory. Nothing is deleted: the row is archived and keeps its content and history."""
    await _editable(db, company_id, memory_id)
    try:
        await archive_memory(
            db, MemoryContext(company_id, principal_actor(principal)), memory_id, reason="deleted"
        )
    except MemoryOpError as exc:
        raise http_error(exc) from exc


@router.post("/api/v1/memory/{memory_id}/archive")
async def archive_memory_route(
    memory_id: uuid.UUID, db: DbSession, company_id: CurrentCompanyId, principal: CurrentPrincipal
) -> dict:
    """Archive memory: retire it from recall and move it to the cold tier."""
    await _editable(db, company_id, memory_id)
    try:
        await archive_memory(
            db, MemoryContext(company_id, principal_actor(principal)), memory_id, tier="cold"
        )
    except MemoryOpError as exc:
        raise http_error(exc) from exc
    return {"id": str(memory_id), "tier": "cold"}


@router.get("/api/v1/companies/{company_id}/memory/health")
async def memory_health(company_id: PathCompanyId, db: DbSession) -> dict[str, Any]:
    """Memory health for active memory: stale count, low relevance count."""
    cutoff = utcnow() - timedelta(days=90)
    live = (MemoryRecord.company_id == company_id, MemoryRecord.status.in_(PROMPT_STATUSES))
    stale = await db.execute(
        select(func.count(MemoryRecord.id)).where(*live, MemoryRecord.created_at < cutoff)
    )
    low_rel = await db.execute(
        select(func.count(MemoryRecord.id)).where(*live, MemoryRecord.importance < 0.3)
    )
    return {
        "stale_count": stale.scalar() or 0,
        "low_relevance_count": low_rel.scalar() or 0,
        "duplicates_estimate": 0,
    }
