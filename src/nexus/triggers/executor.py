"""Trigger Executor - fires triggers and records execution results.

Execution records live in the ``trigger_executions`` table, so history is
queryable after a restart. :class:`TriggerExecutionRecord` is the DTO returned
to callers; the row is the record of truth.
"""

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Awaitable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


def _naive(value: datetime | None) -> datetime | None:
    """Drop tzinfo so the value matches the table's naive UTC columns."""
    if value is None:
        return None
    if value.tzinfo is None:
        return value
    return value.astimezone(timezone.utc).replace(tzinfo=None)


@dataclass
class TriggerExecutionRecord:
    """Record of a single trigger execution.

    Attributes:
        id: Unique execution identifier.
        trigger_id: The trigger that was fired.
        company_id: Company scope.
        status: Execution status (running, completed, failed).
        result: Output data from the execution.
        error: Error message if execution failed.
        started_at: When execution started.
        completed_at: When execution completed.
        duration_ms: Execution duration in milliseconds.
    """

    id: uuid.UUID = field(default_factory=uuid.uuid4)
    trigger_id: uuid.UUID = field(default_factory=uuid.uuid4)
    company_id: uuid.UUID | None = None
    status: str = "running"
    result: dict[str, Any] | None = None
    error: str | None = None
    started_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    completed_at: datetime | None = None
    duration_ms: int = 0


class TriggerExecutor:
    """Fires triggers and manages execution lifecycle.

    When a trigger fires, the executor:
    1. Creates a TriggerExecutionRecord
    2. Wakes the associated agent
    3. Executes the configured action
    4. Records the duration and result
    """

    def __init__(
        self, session_factory: async_sessionmaker[AsyncSession] | None = None
    ) -> None:
        """Initialize the trigger executor.

        Args:
            session_factory: Session factory used to write and read
                ``trigger_executions`` rows. Defaults to the app's factory.
        """
        self._session_factory = session_factory
        self._action_handlers: dict[str, Callable[..., Awaitable[Any]]] = {}

    def _factory(self) -> async_sessionmaker[AsyncSession]:
        """Resolve the session factory, importing the app default lazily."""
        if self._session_factory is None:
            from nexus.database import async_session_factory

            self._session_factory = async_session_factory
        return self._session_factory

    async def _persist(self, record: TriggerExecutionRecord) -> None:
        """Insert or update the row backing an execution record."""
        from nexus.models.trigger import TriggerExecution

        async with self._factory()() as db:
            row = await db.get(TriggerExecution, record.id)
            if row is None:
                row = TriggerExecution(
                    id=record.id,
                    trigger_id=record.trigger_id,
                    company_id=record.company_id,
                    started_at=_naive(record.started_at),
                )
                db.add(row)
            row.status = record.status
            row.result = record.result
            row.error = record.error
            row.completed_at = _naive(record.completed_at)
            await db.commit()

    def register_action(
        self, action_type: str, handler: Callable[..., Awaitable[Any]]
    ) -> None:
        """Register a handler for a specific action type.

        Args:
            action_type: The action type identifier.
            handler: Async callable that performs the action.
        """
        self._action_handlers[action_type] = handler

    async def fire_trigger(
        self,
        trigger_id: uuid.UUID,
        agent_id: uuid.UUID,
        action_type: str,
        action_config: dict[str, Any],
        company_id: uuid.UUID | None = None,
    ) -> TriggerExecutionRecord:
        """Fire a trigger and execute its configured action.

        Creates an execution record, invokes the action handler,
        and records the outcome including duration.

        Args:
            trigger_id: The trigger being fired.
            agent_id: The agent to wake/activate.
            action_type: The type of action to perform.
            action_config: Configuration for the action.
            company_id: Company scope.

        Returns:
            A TriggerExecutionRecord with the outcome.
        """
        record = TriggerExecutionRecord(
            trigger_id=trigger_id,
            company_id=company_id,
        )
        await self._persist(record)

        start_time = datetime.now(timezone.utc)

        handler = self._action_handlers.get(action_type)
        if not handler:
            record.status = "failed"
            record.error = f"No handler registered for action type: {action_type}"
            record.completed_at = datetime.now(timezone.utc)
            record.duration_ms = int(
                (record.completed_at - start_time).total_seconds() * 1000
            )
            await self._persist(record)
            return record

        try:
            result = await handler(
                agent_id=agent_id,
                trigger_id=trigger_id,
                config=action_config,
            )
            end_time = datetime.now(timezone.utc)

            record.status = "completed"
            record.result = result if isinstance(result, dict) else {"output": result}
            record.completed_at = end_time
            record.duration_ms = int(
                (end_time - start_time).total_seconds() * 1000
            )

        except Exception as exc:
            end_time = datetime.now(timezone.utc)
            record.status = "failed"
            record.error = str(exc)
            record.completed_at = end_time
            record.duration_ms = int(
                (end_time - start_time).total_seconds() * 1000
            )

        await self._persist(record)
        return record

    async def get_executions(
        self,
        trigger_id: uuid.UUID | None = None,
        company_id: uuid.UUID | None = None,
        status: str | None = None,
        limit: int = 100,
    ) -> list[TriggerExecutionRecord]:
        """Retrieve trigger execution records with optional filters.

        Args:
            trigger_id: Filter by specific trigger.
            company_id: Filter by company.
            status: Filter by execution status.
            limit: Maximum records to return.

        Returns:
            List of matching TriggerExecutionRecord objects, most recent first.
        """
        from nexus.models.trigger import TriggerExecution

        stmt = select(TriggerExecution)
        if trigger_id:
            stmt = stmt.where(TriggerExecution.trigger_id == trigger_id)
        if company_id:
            stmt = stmt.where(TriggerExecution.company_id == company_id)
        if status:
            stmt = stmt.where(TriggerExecution.status == status)
        stmt = stmt.order_by(TriggerExecution.started_at.desc()).limit(limit)

        async with self._factory()() as db:
            rows = list((await db.execute(stmt)).scalars().all())

        return [
            TriggerExecutionRecord(
                id=row.id,
                trigger_id=row.trigger_id,
                company_id=row.company_id,
                status=row.status,
                result=row.result,
                error=row.error,
                started_at=row.started_at,
                completed_at=row.completed_at,
                duration_ms=int(
                    (row.completed_at - row.started_at).total_seconds() * 1000
                )
                if row.completed_at and row.started_at
                else 0,
            )
            for row in rows
        ]
