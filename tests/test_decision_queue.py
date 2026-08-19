"""Tests for the Decision Queue/Triage System."""

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from nexus.governance.decision_queue import (
    DecisionQueueItem,
    DecisionQueueManager,
    RetentionPolicy,
)


class TestDecisionQueueItem:
    """Tests for the DecisionQueueItem dataclass."""

    def test_default_values(self) -> None:
        """Item has sensible defaults."""
        item = DecisionQueueItem()
        assert item.status == "pending"
        assert item.priority == 5
        assert item.needs_notification is True
        assert item.notification_delivered is False
        assert item.decide_by is None
        assert item.snoozed_until is None
        assert isinstance(item.id, uuid.UUID)
        assert isinstance(item.created_at, datetime)
        assert isinstance(item.updated_at, datetime)

    def test_custom_values(self) -> None:
        """Item accepts custom field values."""
        decision_id = uuid.uuid4()
        source_id = uuid.uuid4()
        deadline = datetime.now(timezone.utc) + timedelta(hours=2)

        item = DecisionQueueItem(
            decision_id=decision_id,
            source_kind="agent",
            source_id=source_id,
            priority=1,
            decide_by=deadline,
        )
        assert item.decision_id == decision_id
        assert item.source_kind == "agent"
        assert item.source_id == source_id
        assert item.priority == 1
        assert item.decide_by == deadline


class TestRetentionPolicy:
    """Tests for the RetentionPolicy dataclass."""

    def test_defaults(self) -> None:
        """RetentionPolicy has expected defaults."""
        policy = RetentionPolicy()
        assert policy.auto_archive_after_days == 30
        assert policy.auto_delete_after_days is None

    def test_custom_values(self) -> None:
        """RetentionPolicy accepts custom configuration."""
        policy = RetentionPolicy(auto_archive_after_days=7, auto_delete_after_days=90)
        assert policy.auto_archive_after_days == 7
        assert policy.auto_delete_after_days == 90


class TestQueueCreation:
    """Tests for queue creation and listing."""

    def test_create_queue_returns_uuid(self) -> None:
        """create_queue returns a UUID for the new queue."""
        mgr = DecisionQueueManager()
        company_id = uuid.uuid4()
        queue_id = mgr.create_queue("urgent", company_id)
        assert isinstance(queue_id, uuid.UUID)

    def test_create_duplicate_queue_raises(self) -> None:
        """Creating a queue with a duplicate name raises ValueError."""
        mgr = DecisionQueueManager()
        company_id = uuid.uuid4()
        mgr.create_queue("ops", company_id)
        with pytest.raises(ValueError, match="already exists"):
            mgr.create_queue("ops", company_id)

    def test_list_queues_empty(self) -> None:
        """list_queues returns empty list when no queues exist."""
        mgr = DecisionQueueManager()
        assert mgr.list_queues() == []

    def test_list_queues_returns_names(self) -> None:
        """list_queues returns all queue names."""
        mgr = DecisionQueueManager()
        company_id = uuid.uuid4()
        mgr.create_queue("alpha", company_id)
        mgr.create_queue("beta", company_id)
        names = mgr.list_queues()
        assert "alpha" in names
        assert "beta" in names
        assert len(names) == 2


class TestAddItem:
    """Tests for adding items to queues."""

    def test_add_item_returns_item(self) -> None:
        """add_item returns a DecisionQueueItem with correct fields."""
        mgr = DecisionQueueManager()
        company_id = uuid.uuid4()
        mgr.create_queue("main", company_id)

        decision_id = uuid.uuid4()
        source_id = uuid.uuid4()
        item = mgr.add_item("main", decision_id, "agent", source_id, priority=2)

        assert isinstance(item, DecisionQueueItem)
        assert item.decision_id == decision_id
        assert item.source_kind == "agent"
        assert item.source_id == source_id
        assert item.priority == 2
        assert item.status == "pending"

    def test_add_item_nonexistent_queue_raises(self) -> None:
        """add_item raises KeyError for nonexistent queue."""
        mgr = DecisionQueueManager()
        with pytest.raises(KeyError, match="does not exist"):
            mgr.add_item("missing", uuid.uuid4(), "system", uuid.uuid4())

    def test_add_item_with_decide_by(self) -> None:
        """add_item respects decide_by parameter."""
        mgr = DecisionQueueManager()
        mgr.create_queue("triage", uuid.uuid4())
        deadline = datetime.now(timezone.utc) + timedelta(hours=4)
        item = mgr.add_item(
            "triage", uuid.uuid4(), "workflow", uuid.uuid4(), decide_by=deadline
        )
        assert item.decide_by == deadline

    def test_add_item_default_priority(self) -> None:
        """add_item defaults to priority 5."""
        mgr = DecisionQueueManager()
        mgr.create_queue("default", uuid.uuid4())
        item = mgr.add_item("default", uuid.uuid4(), "agent", uuid.uuid4())
        assert item.priority == 5


class TestGetPending:
    """Tests for retrieving pending items with sorting."""

    def test_get_pending_empty_queue(self) -> None:
        """get_pending returns empty list for queue with no items."""
        mgr = DecisionQueueManager()
        mgr.create_queue("empty", uuid.uuid4())
        assert mgr.get_pending("empty") == []

    def test_get_pending_sorted_by_priority(self) -> None:
        """get_pending sorts by priority ascending (1 = highest)."""
        mgr = DecisionQueueManager()
        mgr.create_queue("sorted", uuid.uuid4())

        item_low = mgr.add_item("sorted", uuid.uuid4(), "agent", uuid.uuid4(), priority=10)
        item_high = mgr.add_item("sorted", uuid.uuid4(), "agent", uuid.uuid4(), priority=1)
        item_mid = mgr.add_item("sorted", uuid.uuid4(), "agent", uuid.uuid4(), priority=5)

        pending = mgr.get_pending("sorted")
        assert pending[0].id == item_high.id
        assert pending[1].id == item_mid.id
        assert pending[2].id == item_low.id

    def test_get_pending_sorted_by_created_at_within_priority(self) -> None:
        """Items with same priority are sorted by created_at (oldest first)."""
        mgr = DecisionQueueManager()
        mgr.create_queue("time", uuid.uuid4())

        # Create items with same priority but different timestamps
        item1 = mgr.add_item("time", uuid.uuid4(), "agent", uuid.uuid4(), priority=3)
        item1.created_at = datetime(2024, 1, 1, tzinfo=timezone.utc)

        item2 = mgr.add_item("time", uuid.uuid4(), "agent", uuid.uuid4(), priority=3)
        item2.created_at = datetime(2024, 1, 2, tzinfo=timezone.utc)

        item3 = mgr.add_item("time", uuid.uuid4(), "agent", uuid.uuid4(), priority=3)
        item3.created_at = datetime(2024, 1, 3, tzinfo=timezone.utc)

        pending = mgr.get_pending("time")
        assert pending[0].id == item1.id
        assert pending[1].id == item2.id
        assert pending[2].id == item3.id

    def test_get_pending_excludes_non_pending(self) -> None:
        """get_pending only returns items with status 'pending'."""
        mgr = DecisionQueueManager()
        mgr.create_queue("mixed", uuid.uuid4())

        item_pending = mgr.add_item("mixed", uuid.uuid4(), "agent", uuid.uuid4())
        item_decided = mgr.add_item("mixed", uuid.uuid4(), "agent", uuid.uuid4())
        mgr.decide_item(item_decided.id, "approved")

        pending = mgr.get_pending("mixed")
        assert len(pending) == 1
        assert pending[0].id == item_pending.id

    def test_get_pending_respects_limit(self) -> None:
        """get_pending respects the limit parameter."""
        mgr = DecisionQueueManager()
        mgr.create_queue("limited", uuid.uuid4())

        for _ in range(10):
            mgr.add_item("limited", uuid.uuid4(), "system", uuid.uuid4())

        pending = mgr.get_pending("limited", limit=3)
        assert len(pending) == 3

    def test_get_pending_nonexistent_queue_raises(self) -> None:
        """get_pending raises KeyError for nonexistent queue."""
        mgr = DecisionQueueManager()
        with pytest.raises(KeyError, match="does not exist"):
            mgr.get_pending("ghost")


class TestSnoozeItem:
    """Tests for snoozing queue items."""

    def test_snooze_sets_status_and_until(self) -> None:
        """snooze_item sets status to 'snoozed' and snoozed_until."""
        mgr = DecisionQueueManager()
        mgr.create_queue("snooze_q", uuid.uuid4())
        item = mgr.add_item("snooze_q", uuid.uuid4(), "agent", uuid.uuid4())

        until = datetime.now(timezone.utc) + timedelta(hours=2)
        mgr.snooze_item(item.id, until)

        assert item.status == "snoozed"
        assert item.snoozed_until == until

    def test_snooze_updates_timestamp(self) -> None:
        """snooze_item updates the updated_at timestamp."""
        mgr = DecisionQueueManager()
        mgr.create_queue("ts_q", uuid.uuid4())
        item = mgr.add_item("ts_q", uuid.uuid4(), "agent", uuid.uuid4())
        original_updated = item.updated_at

        until = datetime.now(timezone.utc) + timedelta(hours=1)
        mgr.snooze_item(item.id, until)

        assert item.updated_at >= original_updated

    def test_snooze_nonexistent_raises(self) -> None:
        """snooze_item raises KeyError for nonexistent item."""
        mgr = DecisionQueueManager()
        with pytest.raises(KeyError, match="not found"):
            mgr.snooze_item(uuid.uuid4(), datetime.now(timezone.utc))


class TestDecideItem:
    """Tests for deciding queue items."""

    def test_decide_sets_status(self) -> None:
        """decide_item sets status to 'decided'."""
        mgr = DecisionQueueManager()
        mgr.create_queue("decide_q", uuid.uuid4())
        item = mgr.add_item("decide_q", uuid.uuid4(), "workflow", uuid.uuid4())

        mgr.decide_item(item.id, "approved")
        assert item.status == "decided"

    def test_decide_updates_timestamp(self) -> None:
        """decide_item updates the updated_at timestamp."""
        mgr = DecisionQueueManager()
        mgr.create_queue("ts2_q", uuid.uuid4())
        item = mgr.add_item("ts2_q", uuid.uuid4(), "agent", uuid.uuid4())
        original_updated = item.updated_at

        mgr.decide_item(item.id, "rejected")
        assert item.updated_at >= original_updated

    def test_decide_nonexistent_raises(self) -> None:
        """decide_item raises KeyError for nonexistent item."""
        mgr = DecisionQueueManager()
        with pytest.raises(KeyError, match="not found"):
            mgr.decide_item(uuid.uuid4(), "approved")

    def test_decide_stores_decision_outcome(self) -> None:
        """decide_item stores the decision string on the item."""
        mgr = DecisionQueueManager()
        mgr.create_queue("outcome_q", uuid.uuid4())
        item = mgr.add_item("outcome_q", uuid.uuid4(), "agent", uuid.uuid4())

        mgr.decide_item(item.id, "rejected - insufficient budget")
        assert item.decision_outcome == "rejected - insufficient budget"

    def test_decision_outcome_initially_none(self) -> None:
        """New items have decision_outcome set to None."""
        item = DecisionQueueItem()
        assert item.decision_outcome is None


class TestRetention:
    """Tests for retention policy application."""

    def test_apply_retention_archives_old_decided_items(self) -> None:
        """apply_retention archives decided items older than threshold."""
        policy = RetentionPolicy(auto_archive_after_days=7)
        mgr = DecisionQueueManager(retention_policy=policy)
        mgr.create_queue("retention_q", uuid.uuid4())

        item = mgr.add_item("retention_q", uuid.uuid4(), "agent", uuid.uuid4())
        mgr.decide_item(item.id, "done")

        # Simulate age by backdating updated_at
        item.updated_at = datetime.now(timezone.utc) - timedelta(days=10)

        count = mgr.apply_retention()
        assert count == 1
        assert item.status == "archived"

    def test_apply_retention_does_not_archive_recent(self) -> None:
        """apply_retention does not archive recently decided items."""
        policy = RetentionPolicy(auto_archive_after_days=30)
        mgr = DecisionQueueManager(retention_policy=policy)
        mgr.create_queue("recent_q", uuid.uuid4())

        item = mgr.add_item("recent_q", uuid.uuid4(), "agent", uuid.uuid4())
        mgr.decide_item(item.id, "accepted")

        count = mgr.apply_retention()
        assert count == 0
        assert item.status == "decided"

    def test_apply_retention_does_not_archive_pending(self) -> None:
        """apply_retention does not archive pending items even if old."""
        policy = RetentionPolicy(auto_archive_after_days=1)
        mgr = DecisionQueueManager(retention_policy=policy)
        mgr.create_queue("pending_q", uuid.uuid4())

        item = mgr.add_item("pending_q", uuid.uuid4(), "agent", uuid.uuid4())
        item.updated_at = datetime.now(timezone.utc) - timedelta(days=10)

        count = mgr.apply_retention()
        assert count == 0
        assert item.status == "pending"

    def test_apply_retention_across_multiple_queues(self) -> None:
        """apply_retention works across all queues."""
        policy = RetentionPolicy(auto_archive_after_days=5)
        mgr = DecisionQueueManager(retention_policy=policy)
        mgr.create_queue("q1", uuid.uuid4())
        mgr.create_queue("q2", uuid.uuid4())

        item1 = mgr.add_item("q1", uuid.uuid4(), "agent", uuid.uuid4())
        mgr.decide_item(item1.id, "done")
        item1.updated_at = datetime.now(timezone.utc) - timedelta(days=10)

        item2 = mgr.add_item("q2", uuid.uuid4(), "system", uuid.uuid4())
        mgr.decide_item(item2.id, "done")
        item2.updated_at = datetime.now(timezone.utc) - timedelta(days=10)

        count = mgr.apply_retention()
        assert count == 2
        assert item1.status == "archived"
        assert item2.status == "archived"


class TestGetOverdue:
    """Tests for overdue item detection."""

    def test_get_overdue_returns_past_deadline_items(self) -> None:
        """get_overdue returns pending items past their decide_by date."""
        mgr = DecisionQueueManager()
        mgr.create_queue("overdue_q", uuid.uuid4())

        past = datetime.now(timezone.utc) - timedelta(hours=1)
        item = mgr.add_item(
            "overdue_q", uuid.uuid4(), "agent", uuid.uuid4(), decide_by=past
        )

        overdue = mgr.get_overdue("overdue_q")
        assert len(overdue) == 1
        assert overdue[0].id == item.id

    def test_get_overdue_excludes_future_deadline(self) -> None:
        """get_overdue excludes items with future decide_by."""
        mgr = DecisionQueueManager()
        mgr.create_queue("future_q", uuid.uuid4())

        future = datetime.now(timezone.utc) + timedelta(hours=1)
        mgr.add_item("future_q", uuid.uuid4(), "agent", uuid.uuid4(), decide_by=future)

        overdue = mgr.get_overdue("future_q")
        assert len(overdue) == 0

    def test_get_overdue_excludes_decided_items(self) -> None:
        """get_overdue excludes items that are no longer pending."""
        mgr = DecisionQueueManager()
        mgr.create_queue("decided_q", uuid.uuid4())

        past = datetime.now(timezone.utc) - timedelta(hours=1)
        item = mgr.add_item(
            "decided_q", uuid.uuid4(), "agent", uuid.uuid4(), decide_by=past
        )
        mgr.decide_item(item.id, "approved")

        overdue = mgr.get_overdue("decided_q")
        assert len(overdue) == 0

    def test_get_overdue_excludes_no_deadline(self) -> None:
        """get_overdue excludes items without a decide_by deadline."""
        mgr = DecisionQueueManager()
        mgr.create_queue("no_deadline_q", uuid.uuid4())
        mgr.add_item("no_deadline_q", uuid.uuid4(), "agent", uuid.uuid4())

        overdue = mgr.get_overdue("no_deadline_q")
        assert len(overdue) == 0

    def test_get_overdue_all_queues(self) -> None:
        """get_overdue with queue_name=None checks all queues."""
        mgr = DecisionQueueManager()
        mgr.create_queue("qa", uuid.uuid4())
        mgr.create_queue("qb", uuid.uuid4())

        past = datetime.now(timezone.utc) - timedelta(hours=1)
        mgr.add_item("qa", uuid.uuid4(), "agent", uuid.uuid4(), decide_by=past)
        mgr.add_item("qb", uuid.uuid4(), "system", uuid.uuid4(), decide_by=past)

        overdue = mgr.get_overdue()
        assert len(overdue) == 2

    def test_get_overdue_nonexistent_queue_raises(self) -> None:
        """get_overdue raises KeyError for nonexistent queue."""
        mgr = DecisionQueueManager()
        with pytest.raises(KeyError, match="does not exist"):
            mgr.get_overdue("nope")


class TestNotificationTracking:
    """Tests for notification delivery tracking."""

    def test_new_item_needs_notification(self) -> None:
        """New items default to needs_notification=True."""
        mgr = DecisionQueueManager()
        mgr.create_queue("notify_q", uuid.uuid4())
        item = mgr.add_item("notify_q", uuid.uuid4(), "agent", uuid.uuid4())
        assert item.needs_notification is True
        assert item.notification_delivered is False

    def test_mark_notification_delivered(self) -> None:
        """mark_notification_delivered sets flag to True."""
        mgr = DecisionQueueManager()
        mgr.create_queue("deliver_q", uuid.uuid4())
        item = mgr.add_item("deliver_q", uuid.uuid4(), "agent", uuid.uuid4())

        mgr.mark_notification_delivered(item.id)
        assert item.notification_delivered is True

    def test_mark_notification_updates_timestamp(self) -> None:
        """mark_notification_delivered updates updated_at."""
        mgr = DecisionQueueManager()
        mgr.create_queue("ts_notify_q", uuid.uuid4())
        item = mgr.add_item("ts_notify_q", uuid.uuid4(), "agent", uuid.uuid4())
        original_updated = item.updated_at

        mgr.mark_notification_delivered(item.id)
        assert item.updated_at >= original_updated

    def test_mark_notification_nonexistent_raises(self) -> None:
        """mark_notification_delivered raises KeyError for nonexistent item."""
        mgr = DecisionQueueManager()
        with pytest.raises(KeyError, match="not found"):
            mgr.mark_notification_delivered(uuid.uuid4())


class TestLifecycle:
    """Tests for complete item lifecycle: pending -> snoozed -> pending -> decided -> archived."""

    def test_full_lifecycle(self) -> None:
        """Item goes through complete lifecycle."""
        policy = RetentionPolicy(auto_archive_after_days=1)
        mgr = DecisionQueueManager(retention_policy=policy)
        mgr.create_queue("lifecycle_q", uuid.uuid4())

        # Add item
        item = mgr.add_item("lifecycle_q", uuid.uuid4(), "workflow", uuid.uuid4())
        assert item.status == "pending"

        # Snooze
        until = datetime.now(timezone.utc) + timedelta(hours=1)
        mgr.snooze_item(item.id, until)
        assert item.status == "snoozed"

        # Not in pending anymore
        pending = mgr.get_pending("lifecycle_q")
        assert len(pending) == 0

        # Unsnooze by re-setting to pending (manual triage)
        item.status = "pending"

        # Decide
        mgr.decide_item(item.id, "approved")
        assert item.status == "decided"

        # Apply retention (backdate to trigger archival)
        item.updated_at = datetime.now(timezone.utc) - timedelta(days=5)
        count = mgr.apply_retention()
        assert count == 1
        assert item.status == "archived"
