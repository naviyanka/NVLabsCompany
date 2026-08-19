"""Decision Queue/Triage System - production-grade queue management.

Provides named queues with source tracking, triage support (decide-by dates,
snooze, priority routing), retention policies, and notification tracking.
"""

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone


@dataclass
class DecisionQueueItem:
    """A single item in a decision queue.

    Attributes:
        id: Unique item identifier.
        queue_id: The queue this item belongs to.
        decision_id: Reference to the decision being queued.
        source_kind: Origin type (agent/system/workflow).
        source_id: Identifier of the originating entity.
        priority: Priority level (1=highest, higher numbers = lower priority).
        status: Current status (pending/decided/snoozed/archived).
        decide_by: Optional deadline for making a decision.
        snoozed_until: When a snoozed item should reappear.
        needs_notification: Whether this item requires notification delivery.
        notification_delivered: Whether the notification has been sent.
        created_at: When the item was added to the queue.
        updated_at: When the item was last modified.
    """

    id: uuid.UUID = field(default_factory=uuid.uuid4)
    queue_id: uuid.UUID = field(default_factory=uuid.uuid4)
    decision_id: uuid.UUID = field(default_factory=uuid.uuid4)
    source_kind: str = ""
    source_id: uuid.UUID = field(default_factory=uuid.uuid4)
    priority: int = 5
    status: str = "pending"
    decide_by: datetime | None = None
    snoozed_until: datetime | None = None
    needs_notification: bool = True
    notification_delivered: bool = False
    created_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    updated_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )


@dataclass
class RetentionPolicy:
    """Policy controlling automatic archival and deletion of queue items.

    Attributes:
        auto_archive_after_days: Days after which decided items are archived.
        auto_delete_after_days: Days after which archived items are deleted (None = never).
    """

    auto_archive_after_days: int = 30
    auto_delete_after_days: int | None = None


class DecisionQueueManager:
    """Manages decision queues with priority routing, triage, and retention.

    Supports multiple named queues, each holding DecisionQueueItem instances
    sorted by priority and creation time. Provides snooze/decide lifecycle,
    overdue detection, notification tracking, and automatic retention policies.
    """

    def __init__(self, retention_policy: RetentionPolicy | None = None) -> None:
        """Initialize the decision queue manager.

        Args:
            retention_policy: Optional retention policy for automatic archival.
                Defaults to RetentionPolicy() if not provided.
        """
        self._retention_policy = retention_policy or RetentionPolicy()
        self._queues: dict[str, list[DecisionQueueItem]] = {}
        self._queue_ids: dict[str, uuid.UUID] = {}
        self._company_ids: dict[str, uuid.UUID] = {}

    def create_queue(self, name: str, company_id: uuid.UUID) -> uuid.UUID:
        """Create a new named decision queue.

        Args:
            name: Unique name for the queue.
            company_id: Company scope for the queue.

        Returns:
            The UUID assigned to the new queue.

        Raises:
            ValueError: If a queue with the given name already exists.
        """
        if name in self._queues:
            raise ValueError(f"Queue '{name}' already exists")
        queue_id = uuid.uuid4()
        self._queues[name] = []
        self._queue_ids[name] = queue_id
        self._company_ids[name] = company_id
        return queue_id

    def add_item(
        self,
        queue_name: str,
        decision_id: uuid.UUID,
        source_kind: str,
        source_id: uuid.UUID,
        priority: int = 5,
        decide_by: datetime | None = None,
    ) -> DecisionQueueItem:
        """Add an item to a named queue.

        Args:
            queue_name: Name of the target queue.
            decision_id: Reference to the decision being queued.
            source_kind: Origin type (agent/system/workflow).
            source_id: Identifier of the originating entity.
            priority: Priority level (1=highest). Defaults to 5.
            decide_by: Optional deadline for decision.

        Returns:
            The created DecisionQueueItem.

        Raises:
            KeyError: If the queue does not exist.
        """
        if queue_name not in self._queues:
            raise KeyError(f"Queue '{queue_name}' does not exist")

        item = DecisionQueueItem(
            queue_id=self._queue_ids[queue_name],
            decision_id=decision_id,
            source_kind=source_kind,
            source_id=source_id,
            priority=priority,
            decide_by=decide_by,
        )
        self._queues[queue_name].append(item)
        return item

    def get_pending(self, queue_name: str, limit: int = 50) -> list[DecisionQueueItem]:
        """Get pending items from a queue sorted by priority then created_at.

        Args:
            queue_name: Name of the queue to query.
            limit: Maximum number of items to return. Defaults to 50.

        Returns:
            List of pending items sorted by priority (ascending) then created_at.

        Raises:
            KeyError: If the queue does not exist.
        """
        if queue_name not in self._queues:
            raise KeyError(f"Queue '{queue_name}' does not exist")

        pending = [
            item for item in self._queues[queue_name] if item.status == "pending"
        ]
        pending.sort(key=lambda item: (item.priority, item.created_at))
        return pending[:limit]

    def snooze_item(self, item_id: uuid.UUID, until: datetime) -> None:
        """Snooze an item until a specified time.

        Args:
            item_id: The item to snooze.
            until: When the item should reappear.

        Raises:
            KeyError: If the item is not found.
        """
        item = self._find_item(item_id)
        item.status = "snoozed"
        item.snoozed_until = until
        item.updated_at = datetime.now(timezone.utc)

    def decide_item(self, item_id: uuid.UUID, decision: str) -> None:
        """Mark an item as decided.

        Args:
            item_id: The item to mark as decided.
            decision: The decision string (stored as a status transition marker).

        Raises:
            KeyError: If the item is not found.
        """
        item = self._find_item(item_id)
        item.status = "decided"
        item.updated_at = datetime.now(timezone.utc)

    def mark_notification_delivered(self, item_id: uuid.UUID) -> None:
        """Mark notification as delivered for an item.

        Args:
            item_id: The item whose notification was delivered.

        Raises:
            KeyError: If the item is not found.
        """
        item = self._find_item(item_id)
        item.notification_delivered = True
        item.updated_at = datetime.now(timezone.utc)

    def apply_retention(self) -> int:
        """Apply retention policy, archiving items older than the configured threshold.

        Items with status 'decided' that were last updated more than
        auto_archive_after_days ago are archived.

        Returns:
            Count of items that were archived.
        """
        now = datetime.now(timezone.utc)
        cutoff = now - timedelta(days=self._retention_policy.auto_archive_after_days)
        archived_count = 0

        for items in self._queues.values():
            for item in items:
                if item.status == "decided" and item.updated_at < cutoff:
                    item.status = "archived"
                    item.updated_at = now
                    archived_count += 1

        return archived_count

    def get_overdue(self, queue_name: str | None = None) -> list[DecisionQueueItem]:
        """Get items that are past their decide_by deadline and still pending.

        Args:
            queue_name: Optional filter by queue name. None means all queues.

        Returns:
            List of overdue DecisionQueueItem instances.

        Raises:
            KeyError: If queue_name is specified but does not exist.
        """
        now = datetime.now(timezone.utc)

        if queue_name is not None:
            if queue_name not in self._queues:
                raise KeyError(f"Queue '{queue_name}' does not exist")
            queues_to_check = [self._queues[queue_name]]
        else:
            queues_to_check = list(self._queues.values())

        overdue: list[DecisionQueueItem] = []
        for items in queues_to_check:
            for item in items:
                if (
                    item.status == "pending"
                    and item.decide_by is not None
                    and item.decide_by < now
                ):
                    overdue.append(item)

        return overdue

    def list_queues(self) -> list[str]:
        """List all queue names.

        Returns:
            List of queue name strings.
        """
        return list(self._queues.keys())

    def _find_item(self, item_id: uuid.UUID) -> DecisionQueueItem:
        """Find an item by ID across all queues.

        Args:
            item_id: The item identifier to search for.

        Returns:
            The found DecisionQueueItem.

        Raises:
            KeyError: If no item with the given ID exists.
        """
        for items in self._queues.values():
            for item in items:
                if item.id == item_id:
                    return item
        raise KeyError(f"Item '{item_id}' not found")
