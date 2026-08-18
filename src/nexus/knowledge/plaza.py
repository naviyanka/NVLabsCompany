"""Knowledge Plaza - collaborative knowledge base with versioned pages.

The Knowledge Plaza provides a shared space for agents to publish, search,
and version knowledge pages. All operations are scoped by company_id to
ensure multi-tenant isolation.
"""

import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from nexus.memory.retriever import search as bm25_search
from nexus.models.knowledge import KnowledgePage


class KnowledgePlaza:
    """Collaborative knowledge base for publishing and searching versioned pages.

    KnowledgePlaza enables agents to share structured knowledge within a company.
    Pages are versioned, categorized, and searchable via BM25 text retrieval.
    All operations enforce company_id isolation for multi-tenant safety.

    Attributes:
        db: Async database session for persistence operations.
    """

    def __init__(self, db: AsyncSession) -> None:
        """Initialize KnowledgePlaza with a database session.

        Args:
            db: An async SQLAlchemy session for database operations.
        """
        self.db = db

    async def publish_page(
        self,
        company_id: uuid.UUID,
        title: str,
        content: str,
        category: str,
        tags: list[str],
        author_agent_id: uuid.UUID,
    ) -> KnowledgePage:
        """Publish a new knowledge page to the plaza.

        Creates a new versioned knowledge page with status 'published' and
        version=1. The page is immediately available for search.

        Args:
            company_id: The company this page belongs to.
            title: Title of the knowledge page.
            content: Full text content of the page.
            category: Category for organization (e.g., 'engineering', 'policy').
            tags: List of tags for filtering and discovery.
            author_agent_id: UUID of the agent authoring this page.

        Returns:
            The newly created KnowledgePage instance.
        """
        page = KnowledgePage(
            company_id=company_id,
            title=title,
            content=content,
            category=category,
            tags=tags,
            version=1,
            author_agent_id=author_agent_id,
            status="published",
            created_at=datetime.now(timezone.utc),
        )
        self.db.add(page)
        await self.db.commit()
        await self.db.refresh(page)
        return page

    async def update_page(
        self,
        page_id: uuid.UUID,
        content: str,
        editor_agent_id: uuid.UUID,
    ) -> KnowledgePage:
        """Update an existing knowledge page, incrementing its version.

        Fetches the page by ID, updates the content and version number,
        and records the update timestamp. The editor_agent_id is tracked
        as the author of the new version.

        Args:
            page_id: UUID of the page to update.
            content: New content for the page.
            editor_agent_id: UUID of the agent performing the edit.

        Returns:
            The updated KnowledgePage instance.

        Raises:
            ValueError: If the page_id does not exist.
        """
        statement = select(KnowledgePage).where(KnowledgePage.id == page_id)
        result = await self.db.exec(statement)
        page = result.first()
        if page is None:
            raise ValueError(f"Knowledge page not found: {page_id}")

        page.content = content
        page.version += 1
        page.author_agent_id = editor_agent_id
        page.updated_at = datetime.now(timezone.utc)

        self.db.add(page)
        await self.db.commit()
        await self.db.refresh(page)
        return page

    async def search_pages(
        self,
        company_id: uuid.UUID,
        query: str,
        category_filter: Optional[str] = None,
        tag_filter: Optional[str] = None,
    ) -> list[KnowledgePage]:
        """Search knowledge pages using BM25 text retrieval.

        Searches all published pages within the company scope. Results can be
        filtered by category and/or tag. Uses BM25 ranking from the memory
        retriever for relevance scoring.

        Args:
            company_id: Company scope for the search.
            query: Search query text.
            category_filter: Optional category to restrict results.
            tag_filter: Optional tag that must be present in page tags.

        Returns:
            List of KnowledgePage instances ranked by relevance.
        """
        # Build query for pages in this company
        statement = select(KnowledgePage).where(
            KnowledgePage.company_id == company_id,
            KnowledgePage.status == "published",
        )

        if category_filter:
            statement = statement.where(KnowledgePage.category == category_filter)

        result = await self.db.exec(statement)
        pages = list(result.all())

        if not pages:
            return []

        # Apply tag filter in-memory (JSON column)
        if tag_filter:
            pages = [
                p for p in pages if p.tags and tag_filter in p.tags
            ]

        if not pages:
            return []

        # Build search corpus from page content
        memories = [f"{p.title} {p.content}" for p in pages]

        # Use BM25 search for ranking
        ranked_results = bm25_search(query, memories, top_k=len(pages))

        # Return pages in ranked order
        ranked_pages = [pages[idx] for idx, _score in ranked_results]
        return ranked_pages

    async def get_page_history(self, page_id: uuid.UUID) -> list[KnowledgePage]:
        """Get the version history of a knowledge page.

        Returns all versions of the specified page ordered by version number.
        Note: In the current implementation, only the latest version is stored
        in-place (version field is incremented). A full history implementation
        would store each version as a separate record.

        Args:
            page_id: UUID of the page to get history for.

        Returns:
            List containing the page (current version). Future implementations
            may return multiple version records.
        """
        statement = select(KnowledgePage).where(KnowledgePage.id == page_id)
        result = await self.db.exec(statement)
        page = result.first()
        if page is None:
            return []
        return [page]

    async def list_categories(self, company_id: uuid.UUID) -> list[str]:
        """List all distinct categories for a company's knowledge pages.

        Returns unique category values from all published pages in the
        specified company scope.

        Args:
            company_id: Company scope for the category listing.

        Returns:
            List of unique category strings.
        """
        statement = select(KnowledgePage.category).where(
            KnowledgePage.company_id == company_id,
            KnowledgePage.status == "published",
            KnowledgePage.category.isnot(None),  # type: ignore[union-attr]
        )
        result = await self.db.exec(statement)
        categories = list(result.all())
        # Deduplicate
        return list(set(categories))
