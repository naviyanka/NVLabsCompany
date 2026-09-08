"""Tests for cross-worker circuit breaker trip propagation.

A trip recorded on one worker has to contain the incident on every other worker.
The database already holds the state; these tests cover the Redis fast path that
carries the trip without a database round trip, and the invariant that matters
more than speed: losing Redis must never open a circuit that should be closed.
"""

import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from nexus.governance.circuit_breaker_model import CircuitBreakerRecord
from nexus.governance.persistent_circuit_breaker import (
    PersistentCircuitBreaker,
    _trip_key,
)


class FakeRedis:
    """The three Redis calls the breaker uses, backed by a dict."""

    def __init__(self) -> None:
        self.keys: dict[str, int] = {}

    async def set(self, key: str, value: str, ex: int | None = None) -> None:
        self.keys[key] = ex or 0

    async def delete(self, key: str) -> None:
        self.keys.pop(key, None)

    async def exists(self, key: str) -> int:
        return 1 if key in self.keys else 0


class BrokenRedis:
    """A Redis that fails every call, standing in for an outage."""

    async def set(self, *args, **kwargs):
        raise ConnectionError("redis down")

    async def delete(self, *args, **kwargs):
        raise ConnectionError("redis down")

    async def exists(self, *args, **kwargs):
        raise ConnectionError("redis down")


def _make_session_factory(session: AsyncMock):
    """A mock async_sessionmaker yielding the given session each call."""

    @asynccontextmanager
    async def _context():
        yield session

    factory = MagicMock()
    factory.side_effect = lambda: _context()
    return factory


def _session_returning(record: CircuitBreakerRecord | None) -> AsyncMock:
    """A session whose single query resolves to ``record``."""
    session = AsyncMock()
    session.add = MagicMock()
    result = MagicMock()
    result.scalar_one_or_none = MagicMock(return_value=record)
    session.execute = AsyncMock(return_value=result)
    return session


@pytest.fixture
def redis():
    """Patch the breaker's Redis lookup with an in-process fake."""
    fake = FakeRedis()
    with patch("nexus.runtime.redis_utils.get_redis", AsyncMock(return_value=fake)):
        yield fake


class TestTripPropagation:
    """Opening a circuit must publish it; closing must retract it."""

    async def test_open_sets_key_with_cooldown_ttl(self, redis):
        """The fast-path key expires exactly when the circuit would auto-close."""
        agent_id = uuid.uuid4()
        record = CircuitBreakerRecord(
            agent_id=agent_id, consecutive_failures=4, is_open=False, cooldown_seconds=120
        )
        breaker = PersistentCircuitBreaker(
            _make_session_factory(_session_returning(record)), failure_threshold=5
        )

        assert await breaker.record_failure(agent_id) is True
        assert redis.keys[_trip_key(agent_id)] == 120

    async def test_failure_below_threshold_publishes_nothing(self, redis):
        """A single failure is not an incident; nothing is broadcast."""
        agent_id = uuid.uuid4()
        record = CircuitBreakerRecord(
            agent_id=agent_id, consecutive_failures=1, is_open=False
        )
        breaker = PersistentCircuitBreaker(
            _make_session_factory(_session_returning(record)), failure_threshold=5
        )

        assert await breaker.record_failure(agent_id) is False
        assert redis.keys == {}

    async def test_success_clears_key(self, redis):
        """A recovered agent must not stay blocked for the rest of the TTL."""
        agent_id = uuid.uuid4()
        redis.keys[_trip_key(agent_id)] = 300
        record = CircuitBreakerRecord(
            agent_id=agent_id, consecutive_failures=5, is_open=True
        )
        breaker = PersistentCircuitBreaker(
            _make_session_factory(_session_returning(record))
        )

        await breaker.record_success(agent_id)
        assert redis.keys == {}

    async def test_manual_reset_clears_key(self, redis):
        """An operator reset has to take effect on every worker, not just this one."""
        agent_id = uuid.uuid4()
        redis.keys[_trip_key(agent_id)] = 300
        record = CircuitBreakerRecord(
            agent_id=agent_id, consecutive_failures=5, is_open=True
        )
        breaker = PersistentCircuitBreaker(
            _make_session_factory(_session_returning(record))
        )

        await breaker.reset(agent_id)
        assert redis.keys == {}

    async def test_cooldown_expiry_closes_and_leaves_no_key(self, redis):
        """The auto-close path retracts the broadcast too.

        The key's TTL is the cooldown, so by the time the cooldown has elapsed
        the key has expired on its own -- the fake starts empty to model that.
        The delete still runs, which is what keeps a lengthened cooldown from
        leaving a key behind.
        """
        agent_id = uuid.uuid4()
        record = CircuitBreakerRecord(
            agent_id=agent_id,
            consecutive_failures=5,
            is_open=True,
            opened_at=datetime.now(timezone.utc) - timedelta(seconds=400),
            cooldown_seconds=300,
        )
        breaker = PersistentCircuitBreaker(
            _make_session_factory(_session_returning(record))
        )

        assert await breaker.is_open(agent_id) is False
        assert redis.keys == {}


class TestFastPathReads:
    """The fast path may only ever add blocking, never remove it."""

    async def test_key_blocks_without_touching_the_database(self, redis):
        """Another worker's trip blocks this one with no query."""
        agent_id = uuid.uuid4()
        redis.keys[_trip_key(agent_id)] = 300
        session = _session_returning(None)
        breaker = PersistentCircuitBreaker(_make_session_factory(session))

        assert await breaker.is_open(agent_id) is True
        session.execute.assert_not_called()

    async def test_missing_key_falls_through_to_the_database(self, redis):
        """No key means "ask the database", not "the circuit is closed"."""
        agent_id = uuid.uuid4()
        record = CircuitBreakerRecord(
            agent_id=agent_id, consecutive_failures=5, is_open=True
        )
        breaker = PersistentCircuitBreaker(
            _make_session_factory(_session_returning(record))
        )

        assert await breaker.is_open(agent_id) is True


class TestRedisOutage:
    """A Redis outage degrades to the previous behaviour, it does not fail open."""

    async def test_open_circuit_still_blocks_when_redis_is_down(self):
        """The database is the record of truth, so containment survives."""
        agent_id = uuid.uuid4()
        record = CircuitBreakerRecord(
            agent_id=agent_id, consecutive_failures=5, is_open=True
        )
        breaker = PersistentCircuitBreaker(
            _make_session_factory(_session_returning(record))
        )

        with patch(
            "nexus.runtime.redis_utils.get_redis",
            AsyncMock(return_value=BrokenRedis()),
        ):
            assert await breaker.is_open(agent_id) is True

    async def test_trip_still_recorded_when_redis_is_down(self):
        """A failed broadcast must not swallow the trip itself."""
        agent_id = uuid.uuid4()
        record = CircuitBreakerRecord(
            agent_id=agent_id, consecutive_failures=4, is_open=False
        )
        breaker = PersistentCircuitBreaker(
            _make_session_factory(_session_returning(record)), failure_threshold=5
        )

        with patch(
            "nexus.runtime.redis_utils.get_redis",
            AsyncMock(return_value=BrokenRedis()),
        ):
            assert await breaker.record_failure(agent_id) is True

    async def test_no_redis_configured_is_unchanged_behaviour(self):
        """Without Redis every check reads the database, as before."""
        agent_id = uuid.uuid4()
        record = CircuitBreakerRecord(
            agent_id=agent_id, consecutive_failures=5, is_open=True
        )
        session = _session_returning(record)
        breaker = PersistentCircuitBreaker(_make_session_factory(session))

        with patch("nexus.runtime.redis_utils.get_redis", AsyncMock(return_value=None)):
            assert await breaker.is_open(agent_id) is True
        session.execute.assert_called_once()
