"""Memory API endpoints - memory storage, search, and retrieval."""

import hashlib
import json
import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Header, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from nexus.api.deps import CurrentCompanyId, CurrentPrincipal, DbSession
from nexus.memory.ingest import (
    MemoryContext,
    MemoryInput,
    MemoryOpError,
    Origin,
    http_error,
    ingest_memory,
)
from nexus.memory.safety import MemoryRejected
from nexus.models.memory import LIVE_STATUSES, MEMORY_STATUSES, MemoryRecord

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
    status: str | None = None
    trust_state: str | None = None
    memory_type: str | None = None
    supersedes_id: uuid.UUID | None = None


def principal_actor(principal: Any) -> str:
    """The audit actor for an authenticated principal."""
    if principal.user_id:
        return f"user:{principal.user_id}"
    if principal.run_id:
        return f"run:{principal.run_id}"
    return f"service:{principal.api_key_id or principal.label or 'unknown'}"


def memory_response(record: MemoryRecord) -> MemoryResponse:
    """Built by hand: a SQLModel row's `.metadata` is the table registry, not the JSON column."""
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
        status=record.status,
        trust_state=record.trust_state,
        memory_type=record.memory_type,
        supersedes_id=record.supersedes_id,
    )


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
    idempotency_key: str | None = Header(default=None, max_length=200),
) -> Any:
    """Store a memory for an agent.

    Company and actor come from the principal. The caller supplies scope, text,
    importance and free-form metadata; the metadata may not set identity,
    provenance, trust or lifecycle keys, which the server owns. An optional
    ``Idempotency-Key`` header makes a retry return the first result; reusing the
    key with a different body is a 409.
    """
    from nexus.models.agent import Agent
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

    agent_stmt = select(Agent).where(Agent.id == agent_id, Agent.company_id == company_id)
    agent_result = await db.execute(agent_stmt)
    agent = agent_result.scalar_one_or_none()
    if agent is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Agent {agent_id} not found",
        )

    actor = principal_actor(principal)

    item = MemoryInput(
        scope=body.scope,
        content=body.content,
        agent_id=agent_id,
        scope_id=agent_id,
        importance=body.importance,
        metadata=body.metadata,
        content_max=CONTENT_MAX,
        source_type="api_request",
        extractor_version="api-v1",
    )
    if idempotency_key:
        # Bound to the authenticated company and actor, so no one else's key can collide.
        bound = json.dumps([str(company_id), actor, idempotency_key])
        item.source_id = "idem:" + hashlib.sha256(bound.encode()).hexdigest()[:40]
        item.item_key = hashlib.sha256(
            json.dumps([body.metadata, body.importance], sort_keys=True, default=str).encode()
        ).hexdigest()[:32]
    try:
        result = await ingest_memory(
            db, MemoryContext(company_id, actor), item, Origin.API,
            payload_conflict_409=bool(idempotency_key),
        )
    except (MemoryRejected, MemoryOpError) as exc:
        raise http_error(exc) from exc
    return memory_response(result.record)


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
        .where(
            MemoryRecord.agent_id == agent_id,
            MemoryRecord.company_id == company_id,
            MemoryRecord.status.in_(LIVE_STATUSES),
        )
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
                memory=memory_response(memory),
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
    state: str | None = Query(default=None, alias="status"),
    limit: int = 100,
    offset: int = 0,
) -> Any:
    """List memories for an agent. Live (candidate + active) unless ``status`` names one state."""
    if state is not None and state not in MEMORY_STATUSES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": "MEMORY_STATUS_INVALID", "message": "Unknown memory status"},
        )
    stmt = select(MemoryRecord).where(
        MemoryRecord.agent_id == agent_id, MemoryRecord.company_id == company_id
    )
    stmt = stmt.where(
        MemoryRecord.status == state if state else MemoryRecord.status.in_(LIVE_STATUSES)
    )
    if scope:
        stmt = stmt.where(MemoryRecord.scope == scope)
    if tier:
        stmt = stmt.where(MemoryRecord.tier == tier)
    stmt = stmt.offset(offset).limit(limit).order_by(MemoryRecord.created_at.desc())
    result = await db.execute(stmt)
    return [memory_response(m) for m in result.scalars().all()]
