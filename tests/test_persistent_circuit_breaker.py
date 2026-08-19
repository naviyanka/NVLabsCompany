"""Tests for PersistentCircuitBreaker - database-backed circuit breaker.

Tests cover: recording failures, opening the circuit at threshold,
recording successes, checking open state, resetting, and loading state.
Uses AsyncMock for the session factory following the conftest.py pattern.
"""

import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from nexus.governance.circuit_breaker_model import CircuitBreakerRecord
from nexus.governance.persistent_circuit_breaker import PersistentCircuitBreaker


def _make_session_factory(session: AsyncMock):
    """Create a mock async_sessionmaker that yields the given session.

    Wraps the session mock in an async context manager so that
    `async with session_factory() as session:` works as expected.
    """

    @asynccontextmanager
    async def _context():
        yield session

    factory = MagicMock()
    factory.return_value = _context()
    # Make factory callable multiple times by using side_effect
    factory.side_effect = lambda: _context()
    return factory


def _make_record(
    agent_id: uuid.UUID,
    consecutive_failures: int = 0,
    is_open: bool = False,
    last_failure_at: datetime | None = None,
    opened_at: datetime | None = None,
    cooldown_seconds: int = 300,
) -> CircuitBreakerRecord:
    """Create a CircuitBreakerRecord instance for testing."""
    return CircuitBreakerRecord(
        id=uuid.uuid4(),
        agent_id=agent_id,
        consecutive_failures=consecutive_failures,
        is_open=is_open,
        last_failure_at=last_failure_at,
        opened_at=opened_at,
        cooldown_seconds=cooldown_seconds,
        updated_at=datetime.now(timezone.utc),
    )


class TestRecordFailure:
    """Tests for PersistentCircuitBreaker.record_failure."""

    async def test_record_failure_creates_new_record_if_none_exists(self):
        """First failure for an agent creates a new record with count=1."""
        session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        session.execute = AsyncMock(return_value=mock_result)
        session.add = MagicMock()
        session.commit = AsyncMock()

        factory = _make_session_factory(session)
        cb = PersistentCircuitBreaker(factory, failure_threshold=5)

        agent_id = uuid.uuid4()
        opened = await cb.record_failure(agent_id)

        assert opened is False
        session.add.assert_called_once()
        session.commit.assert_called_once()

        # Verify the record that was added
        added_record = session.add.call_args[0][0]
        assert added_record.agent_id == agent_id
        assert added_record.consecutive_failures == 1
        assert added_record.is_open is False

    async def test_record_failure_increments_count(self):
        """Recording a failure increments the consecutive failure count."""
        agent_id = uuid.uuid4()
        record = _make_record(agent_id, consecutive_failures=2)

        session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = record
        session.execute = AsyncMock(return_value=mock_result)
        session.commit = AsyncMock()

        factory = _make_session_factory(session)
        cb = PersistentCircuitBreaker(factory, failure_threshold=5)

        opened = await cb.record_failure(agent_id)

        assert opened is False
        assert record.consecutive_failures == 3
        assert record.is_open is False

    async def test_record_failure_opens_circuit_at_threshold(self):
        """Circuit opens when consecutive failures reach the threshold."""
        agent_id = uuid.uuid4()
        record = _make_record(agent_id, consecutive_failures=4, is_open=False)

        session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = record
        session.execute = AsyncMock(return_value=mock_result)
        session.commit = AsyncMock()

        factory = _make_session_factory(session)
        cb = PersistentCircuitBreaker(factory, failure_threshold=5)

        opened = await cb.record_failure(agent_id)

        assert opened is True
        assert record.consecutive_failures == 5
        assert record.is_open is True
        assert record.opened_at is not None

    async def test_record_failure_does_not_reopen_already_open_circuit(self):
        """If the circuit is already open, additional failures do not re-trigger."""
        agent_id = uuid.uuid4()
        record = _make_record(
            agent_id,
            consecutive_failures=7,
            is_open=True,
            opened_at=datetime.now(timezone.utc),
        )

        session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = record
        session.execute = AsyncMock(return_value=mock_result)
        session.commit = AsyncMock()

        factory = _make_session_factory(session)
        cb = PersistentCircuitBreaker(factory, failure_threshold=5)

        opened = await cb.record_failure(agent_id)

        assert opened is False
        assert record.consecutive_failures == 8
        assert record.is_open is True


class TestRecordSuccess:
    """Tests for PersistentCircuitBreaker.record_success."""

    async def test_record_success_resets_failure_count(self):
        """A success resets the consecutive failure counter to 0."""
        agent_id = uuid.uuid4()
        record = _make_record(agent_id, consecutive_failures=3, is_open=False)

        session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = record
        session.execute = AsyncMock(return_value=mock_result)
        session.commit = AsyncMock()

        factory = _make_session_factory(session)
        cb = PersistentCircuitBreaker(factory)

        await cb.record_success(agent_id)

        assert record.consecutive_failures == 0
        assert record.is_open is False

    async def test_record_success_closes_open_circuit(self):
        """A success closes an open circuit."""
        agent_id = uuid.uuid4()
        record = _make_record(
            agent_id,
            consecutive_failures=5,
            is_open=True,
            opened_at=datetime.now(timezone.utc),
        )

        session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = record
        session.execute = AsyncMock(return_value=mock_result)
        session.commit = AsyncMock()

        factory = _make_session_factory(session)
        cb = PersistentCircuitBreaker(factory)

        await cb.record_success(agent_id)

        assert record.consecutive_failures == 0
        assert record.is_open is False
        assert record.opened_at is None

    async def test_record_success_no_record_is_noop(self):
        """If no record exists for the agent, success is a no-op."""
        session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        session.execute = AsyncMock(return_value=mock_result)
        session.commit = AsyncMock()

        factory = _make_session_factory(session)
        cb = PersistentCircuitBreaker(factory)

        agent_id = uuid.uuid4()
        await cb.record_success(agent_id)

        # No commit should happen since there's nothing to update
        session.commit.assert_not_called()


class TestIsOpen:
    """Tests for PersistentCircuitBreaker.is_open."""

    async def test_is_open_returns_true_when_circuit_open(self):
        """Returns True when there is an open circuit record in DB."""
        agent_id = uuid.uuid4()
        record = _make_record(agent_id, is_open=True)

        session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = record
        session.execute = AsyncMock(return_value=mock_result)

        factory = _make_session_factory(session)
        cb = PersistentCircuitBreaker(factory)

        result = await cb.is_open(agent_id)
        assert result is True

    async def test_is_open_returns_false_when_circuit_closed(self):
        """Returns False when no open circuit record exists."""
        session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        session.execute = AsyncMock(return_value=mock_result)

        factory = _make_session_factory(session)
        cb = PersistentCircuitBreaker(factory)

        agent_id = uuid.uuid4()
        result = await cb.is_open(agent_id)
        assert result is False


class TestReset:
    """Tests for PersistentCircuitBreaker.reset."""

    async def test_reset_closes_circuit_and_clears_failures(self):
        """Resetting closes the circuit and zeros the failure count."""
        agent_id = uuid.uuid4()
        record = _make_record(
            agent_id,
            consecutive_failures=10,
            is_open=True,
            opened_at=datetime.now(timezone.utc),
        )

        session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = record
        session.execute = AsyncMock(return_value=mock_result)
        session.commit = AsyncMock()

        factory = _make_session_factory(session)
        cb = PersistentCircuitBreaker(factory)

        await cb.reset(agent_id)

        assert record.consecutive_failures == 0
        assert record.is_open is False
        assert record.opened_at is None

    async def test_reset_no_record_is_noop(self):
        """If no record exists, reset is a no-op."""
        session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        session.execute = AsyncMock(return_value=mock_result)
        session.commit = AsyncMock()

        factory = _make_session_factory(session)
        cb = PersistentCircuitBreaker(factory)

        agent_id = uuid.uuid4()
        await cb.reset(agent_id)

        session.commit.assert_not_called()


class TestLoadState:
    """Tests for PersistentCircuitBreaker.load_state."""

    async def test_load_state_returns_open_circuits(self):
        """load_state returns a dict of agent_id -> CircuitBreakerState for open circuits."""
        agent_1 = uuid.uuid4()
        agent_2 = uuid.uuid4()

        record_1 = _make_record(
            agent_1,
            consecutive_failures=5,
            is_open=True,
            opened_at=datetime(2024, 1, 1, 12, 0, 0),
            cooldown_seconds=300,
        )
        record_2 = _make_record(
            agent_2,
            consecutive_failures=10,
            is_open=True,
            opened_at=datetime(2024, 1, 2, 12, 0, 0),
            cooldown_seconds=600,
        )

        session = AsyncMock()
        mock_result = MagicMock()
        mock_scalars = MagicMock()
        mock_scalars.all.return_value = [record_1, record_2]
        mock_result.scalars.return_value = mock_scalars
        session.execute = AsyncMock(return_value=mock_result)

        factory = _make_session_factory(session)
        cb = PersistentCircuitBreaker(factory)

        states = await cb.load_state()

        assert len(states) == 2
        assert agent_1 in states
        assert agent_2 in states
        assert states[agent_1].consecutive_failures == 5
        assert states[agent_1].is_open is True
        assert states[agent_1].cooldown_seconds == 300
        assert states[agent_2].consecutive_failures == 10
        assert states[agent_2].cooldown_seconds == 600

    async def test_load_state_returns_empty_dict_when_no_open_circuits(self):
        """load_state returns empty dict when no circuits are open."""
        session = AsyncMock()
        mock_result = MagicMock()
        mock_scalars = MagicMock()
        mock_scalars.all.return_value = []
        mock_result.scalars.return_value = mock_scalars
        session.execute = AsyncMock(return_value=mock_result)

        factory = _make_session_factory(session)
        cb = PersistentCircuitBreaker(factory)

        states = await cb.load_state()

        assert states == {}


class TestCooldownAutoReset:
    """Tests for PersistentCircuitBreaker.is_open cooldown enforcement."""

    async def test_is_open_auto_resets_when_cooldown_elapsed(self):
        """Circuit auto-resets to closed when cooldown has elapsed."""
        from datetime import timedelta

        agent_id = uuid.uuid4()
        # Create a record that was opened 600 seconds ago with 300s cooldown
        opened_at = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        record = _make_record(
            agent_id,
            consecutive_failures=5,
            is_open=True,
            opened_at=opened_at,
            cooldown_seconds=300,
        )

        session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = record
        session.execute = AsyncMock(return_value=mock_result)
        session.commit = AsyncMock()

        factory = _make_session_factory(session)
        cb = PersistentCircuitBreaker(factory, cooldown_seconds=300)

        # Mock datetime.now to return a time well past the cooldown
        fake_now = datetime(2024, 1, 1, 12, 10, 0, tzinfo=timezone.utc)  # 600s after opened_at
        with patch(
            "nexus.governance.persistent_circuit_breaker.datetime"
        ) as mock_dt:
            mock_dt.now.return_value = fake_now
            mock_dt.side_effect = lambda *args, **kw: datetime(*args, **kw)
            result = await cb.is_open(agent_id)

        assert result is False
        # Verify the record was auto-reset
        assert record.is_open is False
        assert record.opened_at is None
        assert record.consecutive_failures == 0
        session.commit.assert_called_once()

    async def test_is_open_remains_open_within_cooldown(self):
        """Circuit remains open when cooldown has NOT elapsed."""
        agent_id = uuid.uuid4()
        # Opened 100 seconds ago with 300s cooldown - should still be open
        opened_at = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        record = _make_record(
            agent_id,
            consecutive_failures=5,
            is_open=True,
            opened_at=opened_at,
            cooldown_seconds=300,
        )

        session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = record
        session.execute = AsyncMock(return_value=mock_result)
        session.commit = AsyncMock()

        factory = _make_session_factory(session)
        cb = PersistentCircuitBreaker(factory, cooldown_seconds=300)

        # Mock datetime.now to return a time within the cooldown
        fake_now = datetime(2024, 1, 1, 12, 1, 40, tzinfo=timezone.utc)  # 100s after opened_at
        with patch(
            "nexus.governance.persistent_circuit_breaker.datetime"
        ) as mock_dt:
            mock_dt.now.return_value = fake_now
            mock_dt.side_effect = lambda *args, **kw: datetime(*args, **kw)
            result = await cb.is_open(agent_id)

        assert result is True
        # Record should NOT have been modified
        assert record.is_open is True
        assert record.consecutive_failures == 5
        session.commit.assert_not_called()
