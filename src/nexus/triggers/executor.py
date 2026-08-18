"""Trigger Executor - fires triggers and records execution results."""

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Awaitable


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

    def __init__(self) -> None:
        """Initialize the trigger executor."""
        self._executions: list[TriggerExecutionRecord] = []
        self._action_handlers: dict[str, Callable[..., Awaitable[Any]]] = {}

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
        self._executions.append(record)

        start_time = datetime.now(timezone.utc)

        handler = self._action_handlers.get(action_type)
        if not handler:
            record.status = "failed"
            record.error = f"No handler registered for action type: {action_type}"
            record.completed_at = datetime.now(timezone.utc)
            record.duration_ms = int(
                (record.completed_at - start_time).total_seconds() * 1000
            )
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

        return record

    def get_executions(
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
            List of matching TriggerExecutionRecord objects.
        """
        results: list[TriggerExecutionRecord] = []
        for record in reversed(self._executions):
            if trigger_id and record.trigger_id != trigger_id:
                continue
            if company_id and record.company_id != company_id:
                continue
            if status and record.status != status:
                continue
            results.append(record)
            if len(results) >= limit:
                break
        return results
