"""Knowledge API endpoints - knowledge base and experience tracking."""

import uuid
from datetime import datetime
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select

from nexus.api.deps import DbSession
from nexus.models.knowledge import ExperienceRecord, KnowledgeChunk, KnowledgePage

router = APIRouter(tags=["knowledge"])


# ---------------------------------------------------------------------------
# Request / Response Models
# ---------------------------------------------------------------------------


class PublishPageRequest(BaseModel):
    """Request body for publishing a knowledge page."""

    title: str
    content: str
    category: Optional[str] = None
    tags: Optional[list[str]] = None
    author_agent_id: Optional[uuid.UUID] = None


class UpdatePageRequest(BaseModel):
    """Request body for updating a knowledge page."""

    title: Optional[str] = None
    content: Optional[str] = None
    category: Optional[str] = None
    tags: Optional[list[str]] = None
    status: Optional[str] = None


class PageResponse(BaseModel):
    """Response model for a knowledge page."""

    id: uuid.UUID
    company_id: uuid.UUID
    title: str
    content: str
    category: Optional[str] = None
    tags: Optional[list[str]] = None
    version: int
    author_agent_id: Optional[uuid.UUID] = None
    status: str
    created_at: datetime
    updated_at: Optional[datetime] = None


class PageHistoryEntry(BaseModel):
    """A version history entry for a knowledge page."""

    id: uuid.UUID
    page_id: uuid.UUID
    content: str
    chunk_index: int
    created_at: datetime


class RAGSearchRequest(BaseModel):
    """Request body for RAG search."""

    query: str
    top_k: int = 5


class RAGSearchResult(BaseModel):
    """A single RAG search result."""

    chunk_id: uuid.UUID
    page_id: uuid.UUID
    content: str
    chunk_index: int
    metadata: Optional[dict[str, Any]] = None


class RecordExperienceRequest(BaseModel):
    """Request body for recording an experience."""

    agent_id: uuid.UUID
    task_id: Optional[uuid.UUID] = None
    outcome: str
    approach: Optional[str] = None
    result_quality: Optional[float] = None
    lessons_learned: Optional[str] = None
    tags: Optional[list[str]] = None


class ExperienceResponse(BaseModel):
    """Response model for an experience record."""

    id: uuid.UUID
    company_id: uuid.UUID
    agent_id: uuid.UUID
    task_id: Optional[uuid.UUID] = None
    outcome: str
    approach: Optional[str] = None
    result_quality: Optional[float] = None
    lessons_learned: Optional[str] = None
    tags: Optional[list[str]] = None
    created_at: datetime


# ---------------------------------------------------------------------------
# Knowledge Page Routes
# ---------------------------------------------------------------------------


@router.post(
    "/api/v1/companies/{company_id}/knowledge",
    status_code=status.HTTP_201_CREATED,
    response_model=PageResponse,
)
async def publish_page(
    company_id: uuid.UUID, body: PublishPageRequest, db: DbSession
) -> Any:
    """Publish a new knowledge page."""
    page = KnowledgePage(
        company_id=company_id,
        title=body.title,
        content=body.content,
        category=body.category,
        tags=body.tags,
        author_agent_id=body.author_agent_id,
        status="published",
    )
    db.add(page)
    await db.flush()
    return page


@router.get(
    "/api/v1/companies/{company_id}/knowledge",
    response_model=list[PageResponse],
)
async def list_pages(
    company_id: uuid.UUID,
    db: DbSession,
    query: Optional[str] = None,
    category: Optional[str] = None,
    tag: Optional[str] = None,
    limit: int = 100,
) -> Any:
    """List or search knowledge pages for a company."""
    stmt = select(KnowledgePage).where(KnowledgePage.company_id == company_id)
    if category:
        stmt = stmt.where(KnowledgePage.category == category)
    if query:
        stmt = stmt.where(KnowledgePage.title.ilike(f"%{query}%"))
    stmt = stmt.limit(limit).order_by(KnowledgePage.created_at.desc())
    result = await db.execute(stmt)
    return list(result.scalars().all())


@router.get(
    "/api/v1/knowledge/{page_id}",
    response_model=PageResponse,
)
async def get_page(page_id: uuid.UUID, db: DbSession) -> Any:
    """Get a knowledge page by ID."""
    stmt = select(KnowledgePage).where(KnowledgePage.id == page_id)
    result = await db.execute(stmt)
    page = result.scalar_one_or_none()
    if page is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Knowledge page {page_id} not found",
        )
    return page


@router.put(
    "/api/v1/knowledge/{page_id}",
    response_model=PageResponse,
)
async def update_page(
    page_id: uuid.UUID, body: UpdatePageRequest, db: DbSession
) -> Any:
    """Update a knowledge page."""
    stmt = select(KnowledgePage).where(KnowledgePage.id == page_id)
    result = await db.execute(stmt)
    page = result.scalar_one_or_none()
    if page is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Knowledge page {page_id} not found",
        )
    updates = body.model_dump(exclude_unset=True)
    for key, value in updates.items():
        setattr(page, key, value)
    page.version += 1
    from datetime import timezone

    page.updated_at = datetime.now(timezone.utc)
    await db.flush()
    return page


@router.get(
    "/api/v1/knowledge/{page_id}/history",
    response_model=list[PageHistoryEntry],
)
async def get_page_history(page_id: uuid.UUID, db: DbSession) -> Any:
    """Get version history (chunks) for a knowledge page."""
    stmt = (
        select(KnowledgeChunk)
        .where(KnowledgeChunk.page_id == page_id)
        .order_by(KnowledgeChunk.chunk_index)
    )
    result = await db.execute(stmt)
    chunks = list(result.scalars().all())
    return [
        PageHistoryEntry(
            id=c.id,
            page_id=c.page_id,
            content=c.content,
            chunk_index=c.chunk_index,
            created_at=c.created_at,
        )
        for c in chunks
    ]


# ---------------------------------------------------------------------------
# RAG Search
# ---------------------------------------------------------------------------


@router.post(
    "/api/v1/companies/{company_id}/knowledge/search",
    response_model=list[RAGSearchResult],
)
async def rag_search(
    company_id: uuid.UUID, body: RAGSearchRequest, db: DbSession
) -> Any:
    """Perform a RAG search across knowledge chunks.

    In production this would use vector similarity search. Currently performs
    a text-based search as a placeholder.
    """
    stmt = (
        select(KnowledgeChunk)
        .where(KnowledgeChunk.company_id == company_id)
        .where(KnowledgeChunk.content.ilike(f"%{body.query}%"))
        .limit(body.top_k)
    )
    result = await db.execute(stmt)
    chunks = list(result.scalars().all())
    return [
        RAGSearchResult(
            chunk_id=c.id,
            page_id=c.page_id,
            content=c.content,
            chunk_index=c.chunk_index,
            metadata=c.metadata,
        )
        for c in chunks
    ]


# ---------------------------------------------------------------------------
# Experience Routes
# ---------------------------------------------------------------------------


@router.post(
    "/api/v1/companies/{company_id}/experiences",
    status_code=status.HTTP_201_CREATED,
    response_model=ExperienceResponse,
)
async def record_experience(
    company_id: uuid.UUID, body: RecordExperienceRequest, db: DbSession
) -> Any:
    """Record an agent's experience from task execution."""
    record = ExperienceRecord(
        company_id=company_id,
        agent_id=body.agent_id,
        task_id=body.task_id,
        outcome=body.outcome,
        approach=body.approach,
        result_quality=body.result_quality,
        lessons_learned=body.lessons_learned,
        tags=body.tags,
    )
    db.add(record)
    await db.flush()
    return record


@router.get(
    "/api/v1/companies/{company_id}/experiences",
    response_model=list[ExperienceResponse],
)
async def search_experiences(
    company_id: uuid.UUID,
    db: DbSession,
    query: Optional[str] = None,
    agent_id: Optional[uuid.UUID] = None,
    outcome: Optional[str] = None,
    limit: int = 100,
) -> Any:
    """Search experience records for a company."""
    stmt = select(ExperienceRecord).where(ExperienceRecord.company_id == company_id)
    if agent_id:
        stmt = stmt.where(ExperienceRecord.agent_id == agent_id)
    if outcome:
        stmt = stmt.where(ExperienceRecord.outcome == outcome)
    if query:
        stmt = stmt.where(ExperienceRecord.lessons_learned.ilike(f"%{query}%"))
    stmt = stmt.limit(limit).order_by(ExperienceRecord.created_at.desc())
    result = await db.execute(stmt)
    return list(result.scalars().all())
