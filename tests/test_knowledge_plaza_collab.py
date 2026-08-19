"""Tests for Knowledge Plaza real-time collaboration features.

Validates subscribe/notify, page locking with auto-expiry, and
the recent changes feed functionality.
"""

import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest

from nexus.knowledge.plaza import KnowledgePlaza, PageChangeEvent


@pytest.fixture
def company_id():
    """Provide a fixed company UUID for tests."""
    return uuid.UUID("12345678-1234-1234-1234-123456789abc")


@pytest.fixture
def agent_id():
    """Provide a fixed agent UUID for tests."""
    return uuid.UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")


@pytest.fixture
def other_agent_id():
    """Provide a second agent UUID for tests."""
    return uuid.UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")


@pytest.fixture
def page_id():
    """Provide a fixed page UUID for tests."""
    return uuid.UUID("cccccccc-cccc-cccc-cccc-cccccccccccc")


@pytest.fixture
def mock_db():
    """Create a mock async database session."""
    session = AsyncMock()
    session.add = MagicMock()
    session.commit = AsyncMock()
    session.refresh = AsyncMock()
    session.exec = AsyncMock()
    return session


@pytest.fixture
def plaza(mock_db):
    """Create a KnowledgePlaza instance with a mock database."""
    return KnowledgePlaza(mock_db)


class TestPageChangeEvent:
    """Tests for PageChangeEvent dataclass fields."""

    def test_page_change_event_fields(self, page_id, company_id, agent_id):
        """PageChangeEvent has correct fields and defaults."""
        now = datetime.now(UTC)
        event = PageChangeEvent(
            page_id=page_id,
            company_id=company_id,
            change_type="created",
            agent_id=agent_id,
            timestamp=now,
        )
        assert event.page_id == page_id
        assert event.company_id == company_id
        assert event.change_type == "created"
        assert event.agent_id == agent_id
        assert event.timestamp == now
        assert event.metadata == {}

    def test_page_change_event_with_metadata(self, page_id, company_id, agent_id):
        """PageChangeEvent can include custom metadata."""
        now = datetime.now(UTC)
        event = PageChangeEvent(
            page_id=page_id,
            company_id=company_id,
            change_type="updated",
            agent_id=agent_id,
            timestamp=now,
            metadata={"version": 2, "title": "Updated Page"},
        )
        assert event.metadata == {"version": 2, "title": "Updated Page"}


class TestSubscribeNotify:
    """Tests for subscribe/notify flow."""

    def test_subscribe_returns_subscription_id(self, plaza, company_id):
        """subscribe() returns a unique subscription ID string."""
        callback = MagicMock()
        sub_id = plaza.subscribe(company_id, callback)
        assert isinstance(sub_id, str)
        assert len(sub_id) > 0

    def test_subscribe_multiple_returns_unique_ids(self, plaza, company_id):
        """Multiple subscriptions return unique IDs."""
        cb1 = MagicMock()
        cb2 = MagicMock()
        sub_id1 = plaza.subscribe(company_id, cb1)
        sub_id2 = plaza.subscribe(company_id, cb2)
        assert sub_id1 != sub_id2

    @pytest.mark.asyncio
    async def test_notify_calls_sync_callback(
        self, plaza, page_id, company_id, agent_id
    ):
        """notify_subscribers calls registered sync callbacks with event."""
        callback = MagicMock()
        plaza.subscribe(company_id, callback)

        await plaza.notify_subscribers(page_id, company_id, "created", agent_id)

        callback.assert_called_once()
        event = callback.call_args[0][0]
        assert isinstance(event, PageChangeEvent)
        assert event.page_id == page_id
        assert event.company_id == company_id
        assert event.change_type == "created"
        assert event.agent_id == agent_id

    @pytest.mark.asyncio
    async def test_notify_calls_async_callback(
        self, plaza, page_id, company_id, agent_id
    ):
        """notify_subscribers calls registered async callbacks with event."""
        callback = AsyncMock()
        plaza.subscribe(company_id, callback)

        await plaza.notify_subscribers(page_id, company_id, "updated", agent_id)

        callback.assert_awaited_once()
        event = callback.call_args[0][0]
        assert isinstance(event, PageChangeEvent)
        assert event.change_type == "updated"

    @pytest.mark.asyncio
    async def test_multiple_subscribers_receive_events(
        self, plaza, page_id, company_id, agent_id
    ):
        """All subscribers for a company receive the event."""
        cb1 = MagicMock()
        cb2 = MagicMock()
        cb3 = AsyncMock()
        plaza.subscribe(company_id, cb1)
        plaza.subscribe(company_id, cb2)
        plaza.subscribe(company_id, cb3)

        await plaza.notify_subscribers(page_id, company_id, "created", agent_id)

        cb1.assert_called_once()
        cb2.assert_called_once()
        cb3.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_subscribers_only_receive_own_company_events(
        self, plaza, page_id, company_id, agent_id
    ):
        """Subscribers only receive events for their subscribed company."""
        other_company = uuid.uuid4()
        cb_company = MagicMock()
        cb_other = MagicMock()
        plaza.subscribe(company_id, cb_company)
        plaza.subscribe(other_company, cb_other)

        await plaza.notify_subscribers(page_id, company_id, "created", agent_id)

        cb_company.assert_called_once()
        cb_other.assert_not_called()


class TestUnsubscribe:
    """Tests for unsubscribe functionality."""

    def test_unsubscribe_returns_true_for_existing(self, plaza, company_id):
        """unsubscribe() returns True when subscription is found."""
        callback = MagicMock()
        sub_id = plaza.subscribe(company_id, callback)
        assert plaza.unsubscribe(sub_id) is True

    def test_unsubscribe_returns_false_for_nonexistent(self, plaza):
        """unsubscribe() returns False for unknown subscription ID."""
        assert plaza.unsubscribe("nonexistent-id") is False

    @pytest.mark.asyncio
    async def test_unsubscribed_callback_not_called(
        self, plaza, page_id, company_id, agent_id
    ):
        """After unsubscribe, callback no longer receives events."""
        callback = MagicMock()
        sub_id = plaza.subscribe(company_id, callback)
        plaza.unsubscribe(sub_id)

        await plaza.notify_subscribers(page_id, company_id, "created", agent_id)

        callback.assert_not_called()


class TestGetRecentChanges:
    """Tests for get_recent_changes functionality."""

    @pytest.mark.asyncio
    async def test_get_recent_changes_returns_events(
        self, plaza, page_id, company_id, agent_id
    ):
        """get_recent_changes returns events after the given timestamp."""
        before = datetime.now(UTC) - timedelta(seconds=1)

        await plaza.notify_subscribers(page_id, company_id, "created", agent_id)

        changes = plaza.get_recent_changes(company_id, before)
        assert len(changes) == 1
        assert changes[0].page_id == page_id
        assert changes[0].change_type == "created"

    @pytest.mark.asyncio
    async def test_get_recent_changes_filters_by_timestamp(
        self, plaza, page_id, company_id, agent_id
    ):
        """get_recent_changes excludes events before the timestamp."""
        await plaza.notify_subscribers(page_id, company_id, "created", agent_id)

        # Timestamp after the event
        after = datetime.now(UTC) + timedelta(seconds=1)
        changes = plaza.get_recent_changes(company_id, after)
        assert len(changes) == 0

    @pytest.mark.asyncio
    async def test_get_recent_changes_filters_by_company(
        self, plaza, page_id, company_id, agent_id
    ):
        """get_recent_changes only returns events for the specified company."""
        other_company = uuid.uuid4()
        before = datetime.now(UTC) - timedelta(seconds=1)

        await plaza.notify_subscribers(page_id, company_id, "created", agent_id)
        await plaza.notify_subscribers(page_id, other_company, "updated", agent_id)

        changes = plaza.get_recent_changes(company_id, before)
        assert len(changes) == 1
        assert changes[0].company_id == company_id

    @pytest.mark.asyncio
    async def test_get_recent_changes_respects_limit(
        self, plaza, company_id, agent_id
    ):
        """get_recent_changes limits results to the specified count."""
        before = datetime.now(UTC) - timedelta(seconds=1)

        # Create 10 events
        for _ in range(10):
            page = uuid.uuid4()
            await plaza.notify_subscribers(page, company_id, "created", agent_id)

        changes = plaza.get_recent_changes(company_id, before, limit=3)
        assert len(changes) == 3

    @pytest.mark.asyncio
    async def test_get_recent_changes_default_limit(
        self, plaza, company_id, agent_id
    ):
        """get_recent_changes default limit is 50."""
        before = datetime.now(UTC) - timedelta(seconds=1)

        # Create 60 events
        for _ in range(60):
            page = uuid.uuid4()
            await plaza.notify_subscribers(page, company_id, "created", agent_id)

        changes = plaza.get_recent_changes(company_id, before)
        assert len(changes) == 50


class TestPageLocking:
    """Tests for page lock/unlock/is_locked functionality."""

    def test_lock_page_acquires_lock(self, plaza, page_id, agent_id):
        """lock_page returns True when page is unlocked."""
        assert plaza.lock_page(page_id, agent_id) is True

    def test_lock_page_same_agent_re_locks(self, plaza, page_id, agent_id):
        """Same agent can re-acquire their own lock."""
        plaza.lock_page(page_id, agent_id)
        assert plaza.lock_page(page_id, agent_id) is True

    def test_lock_page_different_agent_rejected(
        self, plaza, page_id, agent_id, other_agent_id
    ):
        """Another agent cannot lock a page already locked."""
        plaza.lock_page(page_id, agent_id)
        assert plaza.lock_page(page_id, other_agent_id) is False

    def test_lock_page_expired_lock_overridden(
        self, plaza, page_id, agent_id, other_agent_id
    ):
        """Expired locks can be overridden by another agent."""
        # Lock with 0 duration to immediately expire
        plaza.lock_page(page_id, agent_id, duration_seconds=0)
        # Other agent should be able to lock now
        assert plaza.lock_page(page_id, other_agent_id) is True

    def test_unlock_page_by_owner(self, plaza, page_id, agent_id):
        """unlock_page returns True when released by the lock holder."""
        plaza.lock_page(page_id, agent_id)
        assert plaza.unlock_page(page_id, agent_id) is True

    def test_unlock_page_by_wrong_agent(
        self, plaza, page_id, agent_id, other_agent_id
    ):
        """unlock_page returns False when attempted by non-holder."""
        plaza.lock_page(page_id, agent_id)
        assert plaza.unlock_page(page_id, other_agent_id) is False

    def test_unlock_page_not_locked(self, plaza, page_id, agent_id):
        """unlock_page returns False when page is not locked."""
        assert plaza.unlock_page(page_id, agent_id) is False

    def test_is_page_locked_true(self, plaza, page_id, agent_id):
        """is_page_locked returns True for active locks."""
        plaza.lock_page(page_id, agent_id)
        assert plaza.is_page_locked(page_id) is True

    def test_is_page_locked_false_no_lock(self, plaza, page_id):
        """is_page_locked returns False when no lock exists."""
        assert plaza.is_page_locked(page_id) is False

    def test_is_page_locked_false_expired(self, plaza, page_id, agent_id):
        """is_page_locked returns False when lock has expired."""
        plaza.lock_page(page_id, agent_id, duration_seconds=0)
        assert plaza.is_page_locked(page_id) is False

    def test_lock_with_custom_duration(self, plaza, page_id, agent_id):
        """lock_page respects custom duration_seconds."""
        plaza.lock_page(page_id, agent_id, duration_seconds=600)
        assert plaza.is_page_locked(page_id) is True


class TestNotifyIntegration:
    """Tests for notify_subscribers wired into publish_page and update_page."""

    @pytest.mark.asyncio
    async def test_publish_page_triggers_notify(
        self, plaza, mock_db, company_id, agent_id
    ):
        """publish_page triggers notify_subscribers with 'created' type."""
        callback = MagicMock()
        plaza.subscribe(company_id, callback)

        await plaza.publish_page(
            company_id=company_id,
            title="New Page",
            content="Content here",
            category="engineering",
            tags=["test"],
            author_agent_id=agent_id,
        )

        callback.assert_called_once()
        event = callback.call_args[0][0]
        assert event.change_type == "created"
        assert event.company_id == company_id
        assert event.agent_id == agent_id

    @pytest.mark.asyncio
    async def test_update_page_triggers_notify(
        self, plaza, mock_db, page_id, company_id, agent_id
    ):
        """update_page triggers notify_subscribers with 'updated' type."""
        # Mock the existing page
        existing_page = MagicMock()
        existing_page.id = page_id
        existing_page.company_id = company_id
        existing_page.content = "Old content"
        existing_page.version = 1
        existing_page.author_agent_id = agent_id

        mock_result = MagicMock()
        mock_result.first.return_value = existing_page
        mock_db.exec.return_value = mock_result

        callback = MagicMock()
        plaza.subscribe(company_id, callback)

        await plaza.update_page(
            page_id=page_id,
            content="Updated content",
            editor_agent_id=agent_id,
        )

        callback.assert_called_once()
        event = callback.call_args[0][0]
        assert event.change_type == "updated"
        assert event.page_id == page_id
        assert event.company_id == company_id
        assert event.agent_id == agent_id
