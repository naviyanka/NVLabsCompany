"""Persistent Circuit Breaker - database-backed circuit breaker for agent safety.

Stores circuit breaker state in the database so it survives process restarts.
On startup, loads all open circuits from the database to restore state.
"""

import logging
import uuid
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.governance.kill_switch import CircuitBreakerState

logger = logging.getLogger(__name__)


class PersistentCircuitBreaker:
    """Database-backed circuit breaker that survives restarts.

    Stores circuit breaker state in the `circuit_breaker_records` table.
    Mirrors the in-memory CircuitBreaker pattern but persists state to DB.

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

        now = datetime.utcnow()

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

        return just_opened

    async def record_success(self, agent_id: uuid.UUID) -> None:
        """Record a success for an agent, resetting the failure counter.

        If the circuit was open, it closes on success.

        Args:
            agent_id: The agent that succeeded.
        """
        from nexus.governance.circuit_breaker_model import CircuitBreakerRecord

        now = datetime.utcnow()

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

        now = datetime.utcnow()

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

        now = datetime.utcnow()

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
