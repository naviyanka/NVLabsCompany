"""Memory API endpoints - memory storage, search, and retrieval."""

import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from nexus.api.deps import CurrentCompanyId, CurrentPrincipal, DbSession
from nexus.memory.safety import MemoryRejected, sanitize_metadata, sanitize_text
from nexus.models.memory import MemoryRecord

router = APIRouter(tags=["memory"])

# Scopes a caller may write here. All belong to the agent in the URL, so scope_id
# must be that agent. Executive memory goes through the CEO route; l2_agent and
# l3_shared are written only by the layered store.
WRITABLE_SCOPES = frozenset(
    {"agent", "task_context", "long_term", "guidelines", "episodic_reflection", "system_rule"}
)
CONTENT_MAX = 4000


class MemoryCreate(BaseModel):
    """Request body for storing a memory."""

    scope: str = "agent"
    scope_id: uuid.UUID | None = None
    content: str
    metadata: dict[str, Any] | None = None
    importance: float = Field(default=0.5, ge=0.0, le=1.0)


class MemorySearchQuery(BaseModel):
    """Query parameters for memory search."""

    query: str
    top_k: int = 10


class MemoryResponse(BaseModel):
    """Response model for a memory record."""

    id: uuid.UUID
    company_id: uuid.UUID
    agent_id: uuid.UUID | None = None
    scope: str
    scope_id: uuid.UUID | None = None
    content: str
    metadata: dict[str, Any] | None = None
    importance: float
    access_count: int
    tier: str
    created_at: datetime
    updated_at: datetime


class MemorySearchResult(BaseModel):
    """Response model for a search result."""

    memory: MemoryResponse
    score: float


@router.post(
    "/api/v1/agents/{agent_id}/memory",
    status_code=status.HTTP_201_CREATED,
    response_model=MemoryResponse,
)
async def store_memory(
    agent_id: uuid.UUID,
    body: MemoryCreate,
    db: DbSession,
    company_id: CurrentCompanyId,
    principal: CurrentPrincipal,
) -> Any:
    """Store a memory for an agent.

    Company and actor come from the principal. The caller supplies scope, text,
    importance and free-form metadata; the metadata may not set identity,
    provenance, trust or lifecycle keys, which the server owns.
    """
    from nexus.models.agent import Agent
    from nexus.services import manager_service as ms
    from nexus.services.ceo_service import EXECUTIVE_SCOPE

    def refuse(code: str, message: str) -> HTTPException:
        return HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": code, "message": message},
        )

    if body.scope == EXECUTIVE_SCOPE:
        raise refuse(
            "MEMORY_SCOPE_NOT_WRITABLE",
            "Executive memory is recorded through /api/v1/organization/ceo/memory",
        )
    if body.scope not in WRITABLE_SCOPES:
        raise refuse("MEMORY_SCOPE_NOT_WRITABLE", "This memory scope cannot be written here")
    if body.scope_id is not None and body.scope_id != agent_id:
        raise refuse("MEMORY_SCOPE_MISMATCH", "scope_id must be the agent the memory belongs to")
    try:
        content, hit = sanitize_text(body.content, max_len=CONTENT_MAX)
        user_meta, meta_hit = sanitize_metadata(body.metadata)
    except MemoryRejected as exc:
        raise refuse(exc.code, str(exc)) from exc

    agent_stmt = select(Agent).where(Agent.id == agent_id, Agent.company_id == company_id)
    agent_result = await db.execute(agent_stmt)
    agent = agent_result.scalar_one_or_none()
    if agent is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Agent {agent_id} not found",
        )

    if principal.user_id:
        actor = f"user:{principal.user_id}"
    elif principal.run_id:
        actor = f"run:{principal.run_id}"
    else:
        actor = f"service:{principal.api_key_id or principal.label or 'unknown'}"
    redacted = hit or meta_hit
    record = MemoryRecord(
        company_id=company_id,
        agent_id=agent_id,
        scope=body.scope,
        scope_id=agent_id,
        content=content,
        record_metadata={
            **user_meta,
            "origin": "api",
            "recorded_by": actor,
            "trust": "operator_supplied",
            "redacted": redacted,
        },
        importance=body.importance,
        tier="warm",
    )
    db.add(record)
    await db.flush()
    await ms.audit(
        db, company_id, "memory.recorded", actor, "memory", record.id,
        agent_id=agent_id, scope=body.scope, redacted=redacted,
    )
    # Built by hand: a SQLModel row's `.metadata` is the table registry, not the JSON column.
    return MemoryResponse(
        id=record.id,
        company_id=record.company_id,
        agent_id=record.agent_id,
        scope=record.scope,
        scope_id=record.scope_id,
        content=record.content,
        metadata=record.record_metadata,
        importance=record.importance,
        access_count=record.access_count or 0,
        tier=record.tier,
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


@router.get(
    "/api/v1/agents/{agent_id}/memory/search",
    response_model=list[MemorySearchResult],
)
async def search_memory(
    agent_id: uuid.UUID,
    db: DbSession,
    company_id: CurrentCompanyId,
    query: str = "",
    top_k: int = 10,
) -> Any:
    """Search an agent's memories using BM25 retrieval."""
    from nexus.memory.retriever import search as bm25_search

    # Fetch agent's accessible memories
    stmt = (
        select(MemoryRecord)
        .where(MemoryRecord.agent_id == agent_id, MemoryRecord.company_id == company_id)
        .order_by(MemoryRecord.importance.desc())
        .limit(1000)
    )
    result = await db.execute(stmt)
    memories = list(result.scalars().all())

    if not memories or not query:
        return []

    # Run BM25 search
    content_list = [m.content for m in memories]
    results = bm25_search(query, content_list, top_k=top_k)

    search_results = []
    for idx, score in results:
        memory = memories[idx]
        search_results.append(
            MemorySearchResult(
                memory=MemoryResponse(
                    id=memory.id,
                    company_id=memory.company_id,
                    agent_id=memory.agent_id,
                    scope=memory.scope,
                    scope_id=memory.scope_id,
                    content=memory.content,
                    metadata=memory.record_metadata,
                    importance=memory.importance,
                    access_count=memory.access_count,
                    tier=memory.tier,
                    created_at=memory.created_at,
                    updated_at=memory.updated_at,
                ),
                score=score,
            )
        )

    return search_results


@router.get(
    "/api/v1/agents/{agent_id}/memory",
    response_model=list[MemoryResponse],
)
async def list_agent_memories(
    agent_id: uuid.UUID,
    db: DbSession,
    company_id: CurrentCompanyId,
    scope: str | None = None,
    tier: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> Any:
    """List memories for an agent."""
    stmt = select(MemoryRecord).where(MemoryRecord.agent_id == agent_id, MemoryRecord.company_id == company_id)
    if scope:
        stmt = stmt.where(MemoryRecord.scope == scope)
    if tier:
        stmt = stmt.where(MemoryRecord.tier == tier)
    stmt = stmt.offset(offset).limit(limit).order_by(MemoryRecord.created_at.desc())
    result = await db.execute(stmt)
    return list(result.scalars().all())
