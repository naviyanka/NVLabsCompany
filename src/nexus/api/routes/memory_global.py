"""Company-wide memory endpoints — list, stats, detail, update, delete, archive, health."""

import uuid
from datetime import datetime, timedelta
from typing import Any

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select, update, delete, func

from nexus.api.deps import CurrentCompanyId, DbSession
from nexus.models.memory import MemoryRecord

router = APIRouter(tags=["memory"])


class MemoryUpdate(BaseModel):
    content: str | None = None
    importance: float | None = None
    tier: str | None = None


@router.get("/api/v1/companies/{company_id}/memory")
async def list_all_memories(
    company_id: uuid.UUID, db: DbSession,
    agent_id: uuid.UUID | None = None, scope: str | None = None,
    tier: str | None = None, importance_min: float | None = None,
    limit: int = 50, offset: int = 0,
) -> list[dict[str, Any]]:
    """List all memories across agents for a company."""
    stmt = select(MemoryRecord).where(MemoryRecord.company_id == company_id)
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
    return [{"id": str(m.id), "agent_id": str(m.agent_id) if m.agent_id else None, "scope": m.scope, "content": m.content, "importance": m.importance, "tier": m.tier, "access_count": m.access_count, "created_at": m.created_at.isoformat()} for m in memories]


@router.get("/api/v1/companies/{company_id}/memory/stats")
async def memory_stats(company_id: uuid.UUID, db: DbSession) -> dict[str, Any]:
    """Memory statistics: totals, by tier, by scope, avg importance."""
    total = await db.execute(select(func.count(MemoryRecord.id)).where(MemoryRecord.company_id == company_id))
    by_tier = await db.execute(select(MemoryRecord.tier, func.count(MemoryRecord.id)).where(MemoryRecord.company_id == company_id).group_by(MemoryRecord.tier))
    by_scope = await db.execute(select(MemoryRecord.scope, func.count(MemoryRecord.id)).where(MemoryRecord.company_id == company_id).group_by(MemoryRecord.scope))
    avg_imp = await db.execute(select(func.avg(MemoryRecord.importance)).where(MemoryRecord.company_id == company_id))
    agents_with_mem = await db.execute(select(func.count(func.distinct(MemoryRecord.agent_id))).where(MemoryRecord.company_id == company_id))
    return {"total": total.scalar() or 0, "by_tier": dict(by_tier.all()), "by_scope": dict(by_scope.all()), "avg_importance": round(avg_imp.scalar() or 0, 2), "agents_with_memory": agents_with_mem.scalar() or 0}


@router.get("/api/v1/memory/{memory_id}")
async def get_memory(memory_id: uuid.UUID, db: DbSession, company_id: CurrentCompanyId) -> dict[str, Any]:
    """Get single memory by ID."""
    stmt = select(MemoryRecord).where(MemoryRecord.id == memory_id, MemoryRecord.company_id == company_id)
    result = await db.execute(stmt)
    m = result.scalar_one_or_none()
    if not m:
        raise HTTPException(status_code=404, detail="Memory not found")
    return {"id": str(m.id), "agent_id": str(m.agent_id) if m.agent_id else None, "scope": m.scope, "scope_id": str(m.scope_id) if m.scope_id else None, "content": m.content, "record_metadata": m.record_metadata, "importance": m.importance, "access_count": m.access_count, "tier": m.tier, "created_at": m.created_at.isoformat(), "updated_at": m.updated_at.isoformat()}


@router.patch("/api/v1/memory/{memory_id}")
async def update_memory(memory_id: uuid.UUID, body: MemoryUpdate, db: DbSession, company_id: CurrentCompanyId) -> dict:
    """Update a memory record."""
    updates = body.model_dump(exclude_unset=True)
    if not updates:
        raise HTTPException(status_code=400, detail="No fields to update")
    updates["updated_at"] = datetime.utcnow()
    stmt = update(MemoryRecord).where(MemoryRecord.id == memory_id, MemoryRecord.company_id == company_id).values(**updates)
    result = await db.execute(stmt)
    if result.rowcount == 0:
        raise HTTPException(status_code=404, detail="Memory not found")
    return {"id": str(memory_id), "updated": True}


@router.delete("/api/v1/memory/{memory_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_memory(memory_id: uuid.UUID, db: DbSession, company_id: CurrentCompanyId) -> None:
    """Delete a memory record."""
    stmt = delete(MemoryRecord).where(MemoryRecord.id == memory_id, MemoryRecord.company_id == company_id)
    await db.execute(stmt)


@router.post("/api/v1/memory/{memory_id}/archive")
async def archive_memory(memory_id: uuid.UUID, db: DbSession, company_id: CurrentCompanyId) -> dict:
    """Archive memory (move to cold tier)."""
    stmt = update(MemoryRecord).where(MemoryRecord.id == memory_id, MemoryRecord.company_id == company_id).values(tier="cold", updated_at=datetime.utcnow())
    result = await db.execute(stmt)
    if result.rowcount == 0:
        raise HTTPException(status_code=404, detail="Memory not found")
    return {"id": str(memory_id), "tier": "cold"}


@router.get("/api/v1/companies/{company_id}/memory/health")
async def memory_health(company_id: uuid.UUID, db: DbSession) -> dict[str, Any]:
    """Memory health: stale count, low relevance count."""
    cutoff = datetime.utcnow() - timedelta(days=90)
    stale = await db.execute(select(func.count(MemoryRecord.id)).where(MemoryRecord.company_id == company_id, MemoryRecord.created_at < cutoff))
    low_rel = await db.execute(select(func.count(MemoryRecord.id)).where(MemoryRecord.company_id == company_id, MemoryRecord.importance < 0.3))
    return {"stale_count": stale.scalar() or 0, "low_relevance_count": low_rel.scalar() or 0, "duplicates_estimate": 0}
