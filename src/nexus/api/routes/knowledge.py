"""Knowledge API endpoints - knowledge base and experience tracking."""

import uuid
from datetime import timezone, datetime
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select

from nexus.api.deps import CurrentCompanyId, DbSession
from nexus.models.knowledge import ExperienceRecord, KnowledgeChunk, KnowledgePage

router = APIRouter(tags=["knowledge"])


def _escape_like(value: str) -> str:
    """Escape LIKE-special characters (% and _) in user input.

    This prevents user-supplied wildcards from altering search semantics
    or matching unintended rows.
    """
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


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
        escaped = _escape_like(query)
        stmt = stmt.where(KnowledgePage.title.ilike(f"%{escaped}%"))
    stmt = stmt.limit(limit).order_by(KnowledgePage.created_at.desc())
    result = await db.execute(stmt)
    return list(result.scalars().all())


@router.get(
    "/api/v1/knowledge/{page_id}",
    response_model=PageResponse,
)
async def get_page(page_id: uuid.UUID, db: DbSession, company_id: CurrentCompanyId) -> Any:
    """Get a knowledge page by ID."""
    stmt = select(KnowledgePage).where(KnowledgePage.id == page_id, KnowledgePage.company_id == company_id)
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
    page_id: uuid.UUID, body: UpdatePageRequest, db: DbSession, company_id: CurrentCompanyId
) -> Any:
    """Update a knowledge page."""
    stmt = select(KnowledgePage).where(KnowledgePage.id == page_id, KnowledgePage.company_id == company_id)
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
async def get_page_history(page_id: uuid.UUID, db: DbSession, company_id: CurrentCompanyId) -> Any:
    """Get version history (chunks) for a knowledge page."""
    stmt = (
        select(KnowledgeChunk)
        .where(KnowledgeChunk.page_id == page_id, KnowledgeChunk.company_id == company_id)
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
    """Perform a RAG search across knowledge chunks using RAGPipeline (BM25 + vector similarity)."""
    try:
        from nexus.knowledge.rag import RAGPipeline
        from nexus.knowledge.embeddings import get_embedding_provider

        embedding_provider = get_embedding_provider()
        pipeline = RAGPipeline(db=db, embedding_provider=embedding_provider)
        chunks = await pipeline.search(company_id=company_id, query=body.query, top_k=body.top_k)
        return [
            RAGSearchResult(
                chunk_id=c.id,
                page_id=c.page_id,
                content=c.content,
                chunk_index=c.chunk_index,
                metadata=c.chunk_metadata,
            )
            for c in chunks
        ]
    except Exception:
        stmt = (
            select(KnowledgeChunk)
            .where(KnowledgeChunk.company_id == company_id)
            .where(KnowledgeChunk.content.ilike(f"%{_escape_like(body.query)}%"))
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
                metadata=c.chunk_metadata,
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
        escaped = _escape_like(query)
        stmt = stmt.where(ExperienceRecord.lessons_learned.ilike(f"%{escaped}%"))
    stmt = stmt.limit(limit).order_by(ExperienceRecord.created_at.desc())
    result = await db.execute(stmt)
    return list(result.scalars().all())



# ---------------------------------------------------------------------------
# Knowledge Stats & Bulk Operations
# ---------------------------------------------------------------------------


@router.get("/api/v1/companies/{company_id}/knowledge/stats")
async def get_knowledge_stats(company_id: uuid.UUID, db: DbSession) -> dict[str, Any]:
    """Knowledge base statistics for a company."""
    from sqlalchemy import func

    # Total pages
    pages_result = await db.execute(
        select(func.count(KnowledgePage.id)).where(KnowledgePage.company_id == company_id)
    )
    total_pages = pages_result.scalar() or 0

    # Total chunks
    chunks_result = await db.execute(
        select(func.count(KnowledgeChunk.id)).where(KnowledgeChunk.company_id == company_id)
    )
    total_chunks = chunks_result.scalar() or 0

    # By status
    status_result = await db.execute(
        select(KnowledgePage.status, func.count(KnowledgePage.id))
        .where(KnowledgePage.company_id == company_id)
        .group_by(KnowledgePage.status)
    )
    by_status = dict(status_result.all())

    # By category
    cat_result = await db.execute(
        select(KnowledgePage.category, func.count(KnowledgePage.id))
        .where(KnowledgePage.company_id == company_id, KnowledgePage.category.isnot(None))
        .group_by(KnowledgePage.category)
    )
    by_category = dict(cat_result.all())

    return {
        "total_pages": total_pages,
        "total_chunks": total_chunks,
        "by_status": by_status,
        "by_category": by_category,
    }


@router.get("/api/v1/companies/{company_id}/knowledge/categories")
async def list_knowledge_categories(company_id: uuid.UUID, db: DbSession) -> list[dict[str, Any]]:
    """List unique categories with page count per category."""
    from sqlalchemy import func

    stmt = (
        select(KnowledgePage.category, func.count(KnowledgePage.id).label("count"))
        .where(KnowledgePage.company_id == company_id, KnowledgePage.category.isnot(None))
        .group_by(KnowledgePage.category)
        .order_by(func.count(KnowledgePage.id).desc())
    )
    result = await db.execute(stmt)
    rows = result.all()
    return [{"category": row[0], "count": row[1]} for row in rows]


@router.delete("/api/v1/knowledge/{page_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_knowledge_page(page_id: uuid.UUID, db: DbSession, company_id: CurrentCompanyId) -> None:
    """Delete a knowledge page with company_id check."""
    from sqlalchemy import delete as sa_delete

    stmt = sa_delete(KnowledgePage).where(KnowledgePage.id == page_id, KnowledgePage.company_id == company_id)
    await db.execute(stmt)


class BulkImportRequest(BaseModel):
    """Request body for bulk importing knowledge pages."""

    pages: list[PublishPageRequest]


@router.post("/api/v1/companies/{company_id}/knowledge/import")
async def import_knowledge_pages(
    company_id: uuid.UUID, body: BulkImportRequest, db: DbSession
) -> dict[str, Any]:
    """Bulk create knowledge pages. Returns count created."""
    created = 0
    for page_data in body.pages:
        page = KnowledgePage(
            company_id=company_id,
            title=page_data.title,
            content=page_data.content,
            category=page_data.category,
            tags=page_data.tags,
            author_agent_id=page_data.author_agent_id,
            status="published",
        )
        db.add(page)
        created += 1
    await db.flush()
    return {"created": created}



@router.get("/api/v1/companies/{company_id}/knowledge/stats")
async def knowledge_stats(company_id: uuid.UUID, db: DbSession) -> dict[str, Any]:
    """Knowledge base statistics."""
    from sqlalchemy import func
    total_pages = await db.execute(select(func.count(KnowledgePage.id)).where(KnowledgePage.company_id == company_id))
    total_chunks = await db.execute(select(func.count(KnowledgeChunk.id)).where(KnowledgeChunk.company_id == company_id))
    by_status = await db.execute(select(KnowledgePage.status, func.count(KnowledgePage.id)).where(KnowledgePage.company_id == company_id).group_by(KnowledgePage.status))
    by_category = await db.execute(select(KnowledgePage.category, func.count(KnowledgePage.id)).where(KnowledgePage.company_id == company_id, KnowledgePage.category != None).group_by(KnowledgePage.category))
    return {"total_pages": total_pages.scalar() or 0, "total_chunks": total_chunks.scalar() or 0, "by_status": dict(by_status.all()), "by_category": dict(by_category.all())}


@router.get("/api/v1/companies/{company_id}/knowledge/categories")
async def knowledge_categories(company_id: uuid.UUID, db: DbSession) -> list[dict[str, Any]]:
    """List knowledge base categories with counts."""
    from sqlalchemy import func
    stmt = select(KnowledgePage.category, func.count(KnowledgePage.id)).where(KnowledgePage.company_id == company_id, KnowledgePage.category != None).group_by(KnowledgePage.category)
    result = await db.execute(stmt)
    return [{"category": cat, "count": count} for cat, count in result.all()]


@router.delete("/api/v1/knowledge/{page_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_page(page_id: uuid.UUID, db: DbSession, company_id: CurrentCompanyId) -> None:
    """Delete a knowledge page."""
    from sqlalchemy import delete as sa_delete
    await db.execute(sa_delete(KnowledgeChunk).where(KnowledgeChunk.page_id == page_id, KnowledgeChunk.company_id == company_id))
    await db.execute(sa_delete(KnowledgePage).where(KnowledgePage.id == page_id, KnowledgePage.company_id == company_id))


@router.post("/api/v1/companies/{company_id}/knowledge/import")
async def import_knowledge(company_id: uuid.UUID, db: DbSession, body: dict[str, Any] = {}) -> dict[str, int]:
    """Bulk import knowledge pages."""
    pages = body.get("pages", [])
    created = 0
    for page_data in pages:
        page = KnowledgePage(company_id=company_id, title=page_data.get("title", "Untitled"), content=page_data.get("content", ""), category=page_data.get("category"), tags=page_data.get("tags"), status="published")
        db.add(page)
        created += 1
    await db.flush()
    return {"created": created}
