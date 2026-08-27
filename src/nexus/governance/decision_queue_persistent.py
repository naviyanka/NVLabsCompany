"""Persistent Decision Queue Manager - database-backed triage queues.

Same surface as the in-memory `DecisionQueueManager`, but every queue and item
lives in PostgreSQL (`decision_queues` / `decision_queue_items`), so pending
approvals and triage state survive a process restart. Lookups by queue name,
status, and decide_by go through indexed queries instead of scanning dicts.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.governance.decision_queue_model import DecisionQueueItemRecord
from nexus.models.governance import DecisionQueue


@dataclass
class RetentionPolicy:
    """Policy controlling automatic archival and deletion of queue items.

    Attributes:
        auto_archive_after_days: Days after which decided items are archived.
        auto_delete_after_days: Days after which archived items are deleted (None = never).
    """

    auto_archive_after_days: int = 30
    auto_delete_after_days: int | None = None


def _naive_utc(value: datetime | None) -> datetime | None:
    """Normalize an aware datetime to naive UTC for DB storage."""
    if value is None:
        return None
    if value.tzinfo is None:
        return value
    return value.astimezone(timezone.utc).replace(tzinfo=None)


def _now() -> datetime:
    """Current UTC time as a naive datetime (matches the model default)."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


class PersistentDecisionQueueManager:
    """Database-backed decision queue manager.

    Usage:
        manager = PersistentDecisionQueueManager(async_session_factory)
        queue_id = await manager.create_queue("exec-review", company_id)
        item = await manager.add_item("exec-review", decision_id, "agent", agent_id)
        pending = await manager.get_pending("exec-review")
    """

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        retention_policy: RetentionPolicy | None = None,
    ) -> None:
        """Initialize with a session factory.

        Args:
            session_factory: SQLAlchemy async session factory.
            retention_policy: Optional retention policy for automatic archival.
        """
        self._session_factory = session_factory
        self._retention_policy = retention_policy or RetentionPolicy()

    async def _resolve_queue(
        self, session: AsyncSession, queue_name: str
    ) -> DecisionQueue:
        """Look up a queue by name, raising KeyError when absent."""
        result = await session.execute(
            select(DecisionQueue).where(DecisionQueue.name == queue_name)
        )
        queue = result.scalars().first()
        if queue is None:
            raise KeyError(f"Queue '{queue_name}' does not exist")
        return queue

    async def create_queue(self, name: str, company_id: uuid.UUID) -> uuid.UUID:
        """Create a new named decision queue.

        Args:
            name: Unique name for the queue.
            company_id: Company scope for the queue.

        Returns:
            The UUID assigned to the new queue.

        Raises:
            ValueError: If a queue with the given name already exists.
        """
        async with self._session_factory() as session:
            existing = await session.execute(
                select(DecisionQueue.id).where(DecisionQueue.name == name)
            )
            if existing.scalars().first() is not None:
                raise ValueError(f"Queue '{name}' already exists")

            queue = DecisionQueue(name=name, company_id=company_id)
            session.add(queue)
            await session.commit()
            return queue.id

    async def add_item(
        self,
        queue_name: str,
        decision_id: uuid.UUID,
        source_kind: str,
        source_id: uuid.UUID,
        priority: int = 5,
        decide_by: datetime | None = None,
    ) -> DecisionQueueItemRecord:
        """Add an item to a named queue.

        Args:
            queue_name: Name of the target queue.
            decision_id: Reference to the decision being queued.
            source_kind: Origin type (agent/system/workflow).
            source_id: Identifier of the originating entity.
            priority: Priority level (1=highest). Defaults to 5.
            decide_by: Optional deadline for decision.

        Returns:
            The persisted DecisionQueueItemRecord.

        Raises:
            KeyError: If the queue does not exist.
        """
        async with self._session_factory() as session:
            queue = await self._resolve_queue(session, queue_name)
            item = DecisionQueueItemRecord(
                queue_id=queue.id,
                company_id=queue.company_id,
                decision_id=decision_id,
                source_kind=source_kind,
                source_id=source_id,
                priority=priority,
                decide_by=_naive_utc(decide_by),
            )
            session.add(item)
            await session.commit()
            await session.refresh(item)
            return item

    async def get_pending(
        self, queue_name: str, limit: int = 50
    ) -> list[DecisionQueueItemRecord]:
        """Get pending items from a queue sorted by priority then created_at.

        Args:
            queue_name: Name of the queue to query.
            limit: Maximum number of items to return. Defaults to 50.

        Returns:
            List of pending items sorted by priority (ascending) then created_at.

        Raises:
            KeyError: If the queue does not exist.
        """
        async with self._session_factory() as session:
            queue = await self._resolve_queue(session, queue_name)
            result = await session.execute(
                select(DecisionQueueItemRecord)
                .where(
                    DecisionQueueItemRecord.queue_id == queue.id,
                    DecisionQueueItemRecord.status == "pending",
                )
                .order_by(
                    DecisionQueueItemRecord.priority.asc(),
                    DecisionQueueItemRecord.created_at.asc(),
                )
                .limit(limit)
            )
            return list(result.scalars().all())

    async def _update_item(
        self, item_id: uuid.UUID, **values: object
    ) -> DecisionQueueItemRecord:
        """Apply field updates to one item, raising KeyError when absent."""
        async with self._session_factory() as session:
            result = await session.execute(
                select(DecisionQueueItemRecord).where(
                    DecisionQueueItemRecord.id == item_id
                )
            )
            item = result.scalar_one_or_none()
            if item is None:
                raise KeyError(f"Item '{item_id}' not found")

            values.setdefault("updated_at", _now())
            for field, value in values.items():
                setattr(item, field, value)
            await session.commit()
            await session.refresh(item)
            return item

    async def snooze_item(self, item_id: uuid.UUID, until: datetime) -> None:
        """Snooze an item until a specified time.

        Args:
            item_id: The item to snooze.
            until: When the item should reappear.

        Raises:
            KeyError: If the item is not found.
        """
        await self._update_item(
            item_id, status="snoozed", snoozed_until=_naive_utc(until)
        )

    async def decide_item(self, item_id: uuid.UUID, decision: str) -> None:
        """Mark an item as decided and store the decision outcome.

        Args:
            item_id: The item to mark as decided.
            decision: The decision outcome string (e.g., "approved").

        Raises:
            KeyError: If the item is not found.
        """
        await self._update_item(
            item_id, status="decided", decision_outcome=decision
        )

    async def mark_notification_delivered(self, item_id: uuid.UUID) -> None:
        """Mark notification as delivered for an item.

        Args:
            item_id: The item whose notification was delivered.

        Raises:
            KeyError: If the item is not found.
        """
        await self._update_item(item_id, notification_delivered=True)

    async def apply_retention(self) -> int:
        """Archive decided items older than the configured threshold.

        Returns:
            Count of items that were archived.
        """
        now = _now()
        cutoff = now - timedelta(
            days=self._retention_policy.auto_archive_after_days
        )

        async with self._session_factory() as session:
            result = await session.execute(
                select(DecisionQueueItemRecord).where(
                    DecisionQueueItemRecord.status == "decided",
                    DecisionQueueItemRecord.updated_at < cutoff,
                )
            )
            items = list(result.scalars().all())
            for item in items:
                item.status = "archived"
                item.updated_at = now
            await session.commit()
            return len(items)

    async def get_overdue(
        self, queue_name: str | None = None
    ) -> list[DecisionQueueItemRecord]:
        """Get items past their decide_by deadline and still pending.

        Args:
            queue_name: Optional filter by queue name. None means all queues.

        Returns:
            List of overdue items.

        Raises:
            KeyError: If queue_name is specified but does not exist.
        """
        now = _now()
        async with self._session_factory() as session:
            stmt = select(DecisionQueueItemRecord).where(
                DecisionQueueItemRecord.status == "pending",
                DecisionQueueItemRecord.decide_by.is_not(None),
                DecisionQueueItemRecord.decide_by < now,
            )
            if queue_name is not None:
                queue = await self._resolve_queue(session, queue_name)
                stmt = stmt.where(DecisionQueueItemRecord.queue_id == queue.id)

            result = await session.execute(stmt)
            return list(result.scalars().all())

    async def list_queues(self) -> list[str]:
        """List all queue names.

        Returns:
            List of queue name strings.
        """
        async with self._session_factory() as session:
            result = await session.execute(
                select(DecisionQueue.name).order_by(DecisionQueue.name.asc())
            )
            return list(result.scalars().all())
