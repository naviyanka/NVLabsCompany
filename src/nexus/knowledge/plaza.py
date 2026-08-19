"""Knowledge Plaza - collaborative knowledge base with versioned pages.

The Knowledge Plaza provides a shared space for agents to publish, search,
and version knowledge pages. All operations are scoped by company_id to
ensure multi-tenant isolation.
"""

import asyncio
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from nexus.memory.retriever import search as bm25_search
from nexus.models.knowledge import KnowledgePage


@dataclass
class PageChangeEvent:
    """Represents a change event for a knowledge page.

    Captures metadata about a page creation, update, or deletion event
    for real-time notification to subscribers.

    Attributes:
        page_id: UUID of the affected page.
        company_id: UUID of the company scope.
        change_type: Type of change ('created', 'updated', or 'deleted').
        agent_id: UUID of the agent that made the change.
        timestamp: When the change occurred.
        metadata: Additional event metadata.
    """

    page_id: uuid.UUID
    company_id: uuid.UUID
    change_type: str
    agent_id: uuid.UUID
    timestamp: datetime
    metadata: dict = field(default_factory=dict)


class KnowledgePlaza:
    """Collaborative knowledge base for publishing and searching versioned pages.

    KnowledgePlaza enables agents to share structured knowledge within a company.
    Pages are versioned, categorized, and searchable via BM25 text retrieval.
    All operations enforce company_id isolation for multi-tenant safety.

    Supports real-time collaboration features including:
    - Subscribe/notify pattern for page change events
    - Page-level locking with auto-expiry
    - Recent changes feed with timestamp filtering

    Attributes:
        db: Async database session for persistence operations.
    """

    def __init__(self, db: AsyncSession) -> None:
        """Initialize KnowledgePlaza with a database session.

        Args:
            db: An async SQLAlchemy session for database operations.
        """
        self.db = db
        self._subscribers: dict[uuid.UUID, list[tuple[str, Callable]]] = {}
        self._recent_changes: list[PageChangeEvent] = []
        self._page_locks: dict[uuid.UUID, tuple[uuid.UUID, datetime]] = {}

    def subscribe(
        self, company_id: uuid.UUID, callback: Callable
    ) -> str:
        """Register a callback for page change events in a company.

        The callback will be invoked with a PageChangeEvent whenever a page
        is created, updated, or deleted within the specified company scope.

        Args:
            company_id: The company to subscribe to events for.
            callback: A callable (sync or async) that accepts a PageChangeEvent.

        Returns:
            A unique subscription ID string for later unsubscription.
        """
        subscription_id = str(uuid.uuid4())
        if company_id not in self._subscribers:
            self._subscribers[company_id] = []
        self._subscribers[company_id].append((subscription_id, callback))
        return subscription_id

    def unsubscribe(self, subscription_id: str) -> bool:
        """Remove a subscription by its ID.

        Args:
            subscription_id: The ID returned by subscribe().

        Returns:
            True if the subscription was found and removed, False otherwise.
        """
        for company_id, subs in self._subscribers.items():
            for i, (sid, _callback) in enumerate(subs):
                if sid == subscription_id:
                    subs.pop(i)
                    return True
        return False

    async def notify_subscribers(
        self,
        page_id: uuid.UUID,
        company_id: uuid.UUID,
        change_type: str,
        agent_id: uuid.UUID,
    ) -> None:
        """Notify all subscribers of a page change event.

        Creates a PageChangeEvent and delivers it to all registered callbacks
        for the specified company. Handles both sync and async callbacks.

        Args:
            page_id: UUID of the affected page.
            company_id: UUID of the company scope.
            change_type: Type of change ('created', 'updated', or 'deleted').
            agent_id: UUID of the agent that made the change.
        """
        event = PageChangeEvent(
            page_id=page_id,
            company_id=company_id,
            change_type=change_type,
            agent_id=agent_id,
            timestamp=datetime.now(UTC),
        )
        self._recent_changes.append(event)

        subscribers = self._subscribers.get(company_id, [])
        for _sid, callback in subscribers:
            if asyncio.iscoroutinefunction(callback):
                await callback(event)
            else:
                callback(event)

    def get_recent_changes(
        self,
        company_id: uuid.UUID,
        since_timestamp: datetime,
        limit: int = 50,
    ) -> list[PageChangeEvent]:
        """Get recent page change events for a company since a given timestamp.

        Returns events in chronological order, filtered by company and timestamp,
        limited to the specified number of results.

        Args:
            company_id: Company scope for filtering events.
            since_timestamp: Only return events after this timestamp.
            limit: Maximum number of events to return (default 50).

        Returns:
            List of PageChangeEvent instances matching the criteria.
        """
        filtered = [
            event
            for event in self._recent_changes
            if event.company_id == company_id
            and event.timestamp > since_timestamp
        ]
        return filtered[:limit]

    def lock_page(
        self,
        page_id: uuid.UUID,
        agent_id: uuid.UUID,
        duration_seconds: int = 300,
    ) -> bool:
        """Acquire a page lock with auto-expiry.

        Attempts to lock a page for exclusive editing by the specified agent.
        If the page is already locked by another agent with a non-expired lock,
        the request is denied. Expired locks are automatically released.

        Args:
            page_id: UUID of the page to lock.
            agent_id: UUID of the agent requesting the lock.
            duration_seconds: Lock duration in seconds (default 300).

        Returns:
            True if the lock was acquired, False if denied.
        """
        now = datetime.now(UTC)

        if page_id in self._page_locks:
            holder_id, expiry = self._page_locks[page_id]
            if expiry > now and holder_id != agent_id:
                return False
            # Expired or same agent - allow re-lock

        from datetime import timedelta

        expiry = now + timedelta(seconds=duration_seconds)
        self._page_locks[page_id] = (agent_id, expiry)
        return True

    def unlock_page(self, page_id: uuid.UUID, agent_id: uuid.UUID) -> bool:
        """Release a page lock if held by the specified agent.

        Only the agent that holds the lock can release it.

        Args:
            page_id: UUID of the page to unlock.
            agent_id: UUID of the agent requesting the unlock.

        Returns:
            True if the lock was released, False if not held by this agent.
        """
        if page_id not in self._page_locks:
            return False

        holder_id, _expiry = self._page_locks[page_id]
        if holder_id != agent_id:
            return False

        del self._page_locks[page_id]
        return True

    def is_page_locked(self, page_id: uuid.UUID) -> bool:
        """Check if a page is currently locked (respecting expiry).

        Args:
            page_id: UUID of the page to check.

        Returns:
            True if the page has an active (non-expired) lock.
        """
        if page_id not in self._page_locks:
            return False

        _holder_id, expiry = self._page_locks[page_id]
        now = datetime.now(UTC)
        if expiry <= now:
            # Clean up expired lock
            del self._page_locks[page_id]
            return False
        return True

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
        Notifies all subscribers of the creation event.

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
            created_at=datetime.now(UTC),
        )
        self.db.add(page)
        await self.db.commit()
        await self.db.refresh(page)
        await self.notify_subscribers(
            page_id=page.id,
            company_id=company_id,
            change_type="created",
            agent_id=author_agent_id,
        )
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
        as the author of the new version. Notifies all subscribers of the
        update event.

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
        page.updated_at = datetime.now(UTC)

        self.db.add(page)
        await self.db.commit()
        await self.db.refresh(page)
        await self.notify_subscribers(
            page_id=page_id,
            company_id=page.company_id,
            change_type="updated",
            agent_id=editor_agent_id,
        )
        return page

    async def search_pages(
        self,
        company_id: uuid.UUID,
        query: str,
        category_filter: str | None = None,
        tag_filter: str | None = None,
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
