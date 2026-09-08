"""Persistent Circuit Breaker - database-backed circuit breaker for agent safety.

Stores circuit breaker state in the database so it survives process restarts.
On startup, loads all open circuits from the database to restore state.
"""

import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

logger = logging.getLogger(__name__)


@dataclass
class CircuitBreakerState:
    """A snapshot of one agent's circuit, as loaded from the database.

    Attributes:
        agent_id: The agent being monitored.
        consecutive_failures: Number of consecutive failures.
        is_open: Whether the circuit is open (agent is blocked).
        last_failure_at: When the last failure occurred.
        opened_at: When the circuit was opened.
        cooldown_seconds: Time before the circuit resets.
    """

    agent_id: uuid.UUID
    consecutive_failures: int = 0
    is_open: bool = False
    last_failure_at: datetime | None = None
    opened_at: datetime | None = None
    cooldown_seconds: int = 300


def _trip_key(agent_id: uuid.UUID) -> str:
    """The Redis key naming one agent's open circuit."""
    return f"nexus:breaker:open:{agent_id}"


class PersistentCircuitBreaker:
    """Database-backed circuit breaker that survives restarts.

    Stores circuit breaker state in the `circuit_breaker_records` table, and
    mirrors an open circuit into Redis when Redis is configured. The database is
    the record of truth; the Redis key is a containment fast path, so a trip on
    one worker blocks the next call on every other replica without waiting for a
    database round trip. Without Redis the behaviour is unchanged -- every check
    reads the database.

    Usage:
        cb = PersistentCircuitBreaker(async_session_factory)
        opened = await cb.record_failure(agent_id)
        await cb.record_success(agent_id)
        is_blocked = await cb.is_open(agent_id)
        await cb.reset(agent_id)
        states = await cb.load_state()
    """

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        failure_threshold: int = 5,
        cooldown_seconds: int = 300,
    ) -> None:
        """Initialize with a session factory.

        Args:
            session_factory: SQLAlchemy async session factory.
            failure_threshold: Consecutive failures before circuit opens.
            cooldown_seconds: Default seconds before an open circuit resets.
        """
        self._session_factory = session_factory
        self._failure_threshold = failure_threshold
        self._cooldown_seconds = cooldown_seconds

    async def _propagate_trip(self, agent_id: uuid.UUID, cooldown_seconds: int) -> None:
        """Publish an open circuit to every replica via Redis.

        The key carries the cooldown as its TTL, so the fast path expires exactly
        when the circuit would auto-close anyway and cannot outlive the database
        state it mirrors.

        Args:
            agent_id: The agent whose circuit opened.
            cooldown_seconds: How long the circuit stays open.
        """
        try:
            from nexus.runtime.redis_utils import get_redis

            redis = await get_redis()
            if redis is None:
                return
            await redis.set(_trip_key(agent_id), "1", ex=max(1, cooldown_seconds))
        except Exception as exc:  # noqa: BLE001 - the DB state still holds
            logger.warning("Breaker trip propagation failed for %s: %s", agent_id, exc)

    async def _clear_trip(self, agent_id: uuid.UUID) -> None:
        """Drop the Redis fast-path key when a circuit closes.

        A stale key would block a healthy agent for the rest of its TTL, so this
        runs on success, manual reset, and cooldown expiry.

        Args:
            agent_id: The agent whose circuit closed.
        """
        try:
            from nexus.runtime.redis_utils import get_redis

            redis = await get_redis()
            if redis is None:
                return
            await redis.delete(_trip_key(agent_id))
        except Exception as exc:  # noqa: BLE001 - the DB state still holds
            logger.warning("Breaker trip clear failed for %s: %s", agent_id, exc)

    async def record_failure(self, agent_id: uuid.UUID) -> bool:
        """Record a failure for an agent and persist to DB.

        Increments the consecutive failure count. If the threshold is
        reached, the circuit opens (agent is blocked).

        Args:
            agent_id: The agent that failed.

        Returns:
            True if the circuit just opened due to this failure.
        """
        from nexus.governance.circuit_breaker_model import CircuitBreakerRecord

        now = datetime.now(timezone.utc)

        async with self._session_factory() as session:
            stmt = select(CircuitBreakerRecord).where(
                CircuitBreakerRecord.agent_id == agent_id
            )
            result = await session.execute(stmt)
            record = result.scalar_one_or_none()

            if record is None:
                # Create new record for this agent
                record = CircuitBreakerRecord(
                    agent_id=agent_id,
                    consecutive_failures=1,
                    is_open=False,
                    last_failure_at=now,
                    cooldown_seconds=self._cooldown_seconds,
                    updated_at=now,
                )
                session.add(record)
                just_opened = False

                # Check if single failure meets threshold
                if record.consecutive_failures >= self._failure_threshold:
                    record.is_open = True
                    record.opened_at = now
                    just_opened = True

                await session.commit()
                return just_opened

            # Update existing record
            record.consecutive_failures += 1
            record.last_failure_at = now
            record.updated_at = now

            just_opened = False
            if (
                record.consecutive_failures >= self._failure_threshold
                and not record.is_open
            ):
                record.is_open = True
                record.opened_at = now
                just_opened = True

            await session.commit()

        logger.debug(
            "Circuit breaker failure recorded for agent %s (count=%d, open=%s)",
            agent_id,
            record.consecutive_failures,
            record.is_open,
        )

        if just_opened:
            logger.warning(
                "Circuit breaker OPENED for agent %s after %d consecutive failures",
                agent_id,
                record.consecutive_failures,
            )
            try:
                from nexus.observability.metrics import record_circuit_breaker_trip
                record_circuit_breaker_trip(service=str(agent_id))
            except Exception:
                pass
            await self._propagate_trip(agent_id, record.cooldown_seconds)

        return just_opened

    async def record_success(self, agent_id: uuid.UUID) -> None:
        """Record a success for an agent, resetting the failure counter.

        If the circuit was open, it closes on success.

        Args:
            agent_id: The agent that succeeded.
        """
        from nexus.governance.circuit_breaker_model import CircuitBreakerRecord

        now = datetime.now(timezone.utc)

        async with self._session_factory() as session:
            stmt = select(CircuitBreakerRecord).where(
                CircuitBreakerRecord.agent_id == agent_id
            )
            result = await session.execute(stmt)
            record = result.scalar_one_or_none()

            if record is None:
                # No record exists; nothing to reset
                return

            record.consecutive_failures = 0
            record.is_open = False
            record.opened_at = None
            record.updated_at = now
            await session.commit()

        await self._clear_trip(agent_id)

        logger.debug(
            "Circuit breaker success recorded for agent %s (reset to closed)",
            agent_id,
        )

    async def is_open(self, agent_id: uuid.UUID) -> bool:
        """Check if the circuit breaker is open for an agent (from DB).

        If the cooldown period has elapsed since the circuit opened,
        the circuit auto-resets (transitions to closed), matching the
        in-memory CircuitBreaker behavior.

        Args:
            agent_id: The agent to check.

        Returns:
            True if the circuit is open (agent should be blocked).
        """
        from nexus.governance.circuit_breaker_model import CircuitBreakerRecord

        now = datetime.now(timezone.utc)

        # Containment fast path: a trip on any replica lands here first, so this
        # worker refuses the next call without a database round trip. Only a
        # positive answer short-circuits -- a missing key means "ask the database",
        # never "the circuit is closed", so losing Redis cannot open a circuit.
        try:
            from nexus.runtime.redis_utils import get_redis

            redis = await get_redis()
            if redis is not None and await redis.exists(_trip_key(agent_id)):
                return True
        except Exception as exc:  # noqa: BLE001 - fall through to the DB
            logger.warning("Breaker fast-path check failed for %s: %s", agent_id, exc)

        async with self._session_factory() as session:
            stmt = select(CircuitBreakerRecord).where(
                CircuitBreakerRecord.agent_id == agent_id,
                CircuitBreakerRecord.is_open == True,  # noqa: E712
            )
            result = await session.execute(stmt)
            record = result.scalar_one_or_none()

            if record is None:
                return False

            # Check if cooldown has elapsed - auto-reset if so
            if record.opened_at is not None:
                elapsed = now - record.opened_at
                if elapsed >= timedelta(seconds=record.cooldown_seconds):
                    # Cooldown expired: auto-close the circuit
                    record.is_open = False
                    record.opened_at = None
                    record.consecutive_failures = 0
                    record.updated_at = now
                    await session.commit()
                    await self._clear_trip(agent_id)
                    logger.info(
                        "Circuit breaker auto-reset for agent %s "
                        "(cooldown of %ds elapsed)",
                        agent_id,
                        record.cooldown_seconds,
                    )
                    return False

            return True

    async def reset(self, agent_id: uuid.UUID) -> None:
        """Manually reset the circuit breaker for an agent.

        Closes the circuit and resets the failure counter.

        Args:
            agent_id: The agent to reset.
        """
        from nexus.governance.circuit_breaker_model import CircuitBreakerRecord

        now = datetime.now(timezone.utc)

        async with self._session_factory() as session:
            stmt = select(CircuitBreakerRecord).where(
                CircuitBreakerRecord.agent_id == agent_id
            )
            result = await session.execute(stmt)
            record = result.scalar_one_or_none()

            if record is None:
                return

            record.consecutive_failures = 0
            record.is_open = False
            record.opened_at = None
            record.updated_at = now
            await session.commit()

        await self._clear_trip(agent_id)

        logger.info("Circuit breaker manually RESET for agent %s", agent_id)

    async def load_state(self) -> dict[uuid.UUID, CircuitBreakerState]:
        """Load all open circuit breakers from DB.

        Called during application startup to restore persisted state.

        Returns:
            Dictionary mapping agent_id to CircuitBreakerState for all
            agents with open circuits.
        """
        from nexus.governance.circuit_breaker_model import CircuitBreakerRecord

        async with self._session_factory() as session:
            stmt = select(CircuitBreakerRecord).where(
                CircuitBreakerRecord.is_open == True  # noqa: E712
            )
            result = await session.execute(stmt)
            records = list(result.scalars().all())

        states: dict[uuid.UUID, CircuitBreakerState] = {}
        for record in records:
            states[record.agent_id] = CircuitBreakerState(
                agent_id=record.agent_id,
                consecutive_failures=record.consecutive_failures,
                is_open=record.is_open,
                last_failure_at=record.last_failure_at,
                opened_at=record.opened_at,
                cooldown_seconds=record.cooldown_seconds,
            )

        if records:
            logger.info(
                "Loaded %d open circuit breaker(s) from database",
                len(records),
            )

        return states
