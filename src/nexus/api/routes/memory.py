"""Memory API endpoints - memory storage, search, and retrieval."""

import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter, status
from pydantic import BaseModel
from sqlalchemy import select

from nexus.api.deps import DbSession
from nexus.models.memory import MemoryRecord

router = APIRouter(tags=["memory"])


class MemoryCreate(BaseModel):
    """Request body for storing a memory."""

    scope: str = "agent"
    scope_id: uuid.UUID | None = None
    content: str
    metadata: dict[str, Any] | None = None
    importance: float = 0.5


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
    agent_id: uuid.UUID, body: MemoryCreate, db: DbSession
) -> Any:
    """Store a memory for an agent."""
    # Get agent's company_id
    from nexus.models.agent import Agent

    agent_stmt = select(Agent).where(Agent.id == agent_id)
    agent_result = await db.execute(agent_stmt)
    agent = agent_result.scalar_one_or_none()
    company_id = agent.company_id if agent else uuid.UUID(int=0)

    record = MemoryRecord(
        company_id=company_id,
        agent_id=agent_id,
        scope=body.scope,
        scope_id=body.scope_id or agent_id,
        content=body.content,
        metadata=body.metadata,
        importance=body.importance,
        tier="warm",
    )
    db.add(record)
    await db.flush()
    return record


@router.get(
    "/api/v1/agents/{agent_id}/memory/search",
    response_model=list[MemorySearchResult],
)
async def search_memory(
    agent_id: uuid.UUID,
    db: DbSession,
    query: str = "",
    top_k: int = 10,
) -> Any:
    """Search an agent's memories using BM25 retrieval."""
    from nexus.memory.retriever import search as bm25_search

    # Fetch agent's accessible memories
    stmt = (
        select(MemoryRecord)
        .where(MemoryRecord.agent_id == agent_id)
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
                    metadata=memory.metadata,
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
    scope: str | None = None,
    tier: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> Any:
    """List memories for an agent."""
    stmt = select(MemoryRecord).where(MemoryRecord.agent_id == agent_id)
    if scope:
        stmt = stmt.where(MemoryRecord.scope == scope)
    if tier:
        stmt = stmt.where(MemoryRecord.tier == tier)
    stmt = stmt.offset(offset).limit(limit).order_by(MemoryRecord.created_at.desc())
    result = await db.execute(stmt)
    return list(result.scalars().all())
