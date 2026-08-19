"""Durable Execution Checkpoints - crash recovery for long-running tasks.

Provides a checkpointing system that allows tasks to save their progress
at intermediate steps and resume execution after failures or restarts.
"""

import uuid
from datetime import datetime, timedelta, timezone
from enum import StrEnum

from sqlalchemy import Column
from sqlalchemy.types import JSON
from sqlmodel import Field, SQLModel


class CheckpointStatus(StrEnum):
    """Status of an execution checkpoint."""

    active = "active"
    completed = "completed"
    abandoned = "abandoned"


class ExecutionCheckpoint(SQLModel, table=True):
    """Records a checkpoint of task execution state for crash recovery.

    Each checkpoint captures the full state needed to resume a task
    from a specific step, including agent context, completed steps,
    and any intermediate results produced so far.
    """

    __tablename__ = "execution_checkpoints"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    task_id: uuid.UUID = Field(index=True)
    step_index: int = Field(default=0)
    state_json: dict = Field(default_factory=dict, sa_column=Column(JSON))
    status: str = Field(default=CheckpointStatus.active)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime | None = Field(default=None)


def build_checkpoint_state(
    agent_context: dict,
    completed_steps: list[int],
    intermediate_results: list[dict],
    metadata: dict | None = None,
) -> dict:
    """Build a structured checkpoint state dictionary.

    Args:
        agent_context: Current agent execution context.
        completed_steps: Indices of steps that have been completed.
        intermediate_results: Results produced by completed steps.
        metadata: Optional additional metadata to store.

    Returns:
        A dictionary suitable for storing in ExecutionCheckpoint.state_json.
    """
    return {
        "agent_context": agent_context,
        "completed_steps": completed_steps,
        "intermediate_results": intermediate_results,
        "metadata": metadata or {},
    }


class CheckpointManager:
    """In-memory checkpoint manager for task execution recovery.

    Manages the lifecycle of execution checkpoints: creation, retrieval,
    cleanup, and staleness detection. Designed for testability without
    requiring a real database connection.
    """

    def __init__(self, max_checkpoint_age_hours: int = 24) -> None:
        """Initialize the checkpoint manager.

        Args:
            max_checkpoint_age_hours: Number of hours after which an active
                checkpoint is considered stale and eligible for abandonment.
        """
        self._checkpoints: list[ExecutionCheckpoint] = []
        self._max_checkpoint_age_hours = max_checkpoint_age_hours

    def save_checkpoint(
        self, task_id: uuid.UUID, step_index: int, state: dict
    ) -> ExecutionCheckpoint:
        """Save a new checkpoint for a task.

        Args:
            task_id: The task this checkpoint belongs to.
            step_index: The current step index being checkpointed.
            state: The execution state to persist.

        Returns:
            The created ExecutionCheckpoint instance.
        """
        checkpoint = ExecutionCheckpoint(
            task_id=task_id,
            step_index=step_index,
            state_json=state,
            status=CheckpointStatus.active,
        )
        self._checkpoints.append(checkpoint)
        return checkpoint

    def load_latest(self, task_id: uuid.UUID) -> ExecutionCheckpoint | None:
        """Load the most recent active checkpoint for a task.

        Args:
            task_id: The task to find checkpoints for.

        Returns:
            The most recent active checkpoint, or None if no active
            checkpoint exists for this task.
        """
        active = [
            cp
            for cp in self._checkpoints
            if cp.task_id == task_id and cp.status == CheckpointStatus.active
        ]
        if not active:
            return None
        return max(active, key=lambda cp: cp.created_at)

    def cleanup(self, task_id: uuid.UUID) -> None:
        """Mark all checkpoints for a task as completed.

        Called when a task finishes successfully and its checkpoints
        are no longer needed for recovery.

        Args:
            task_id: The task whose checkpoints should be marked completed.
        """
        now = datetime.now(timezone.utc)
        for cp in self._checkpoints:
            if cp.task_id == task_id and cp.status == CheckpointStatus.active:
                cp.status = CheckpointStatus.completed
                cp.updated_at = now

    def abandon_stale(self) -> list[ExecutionCheckpoint]:
        """Mark checkpoints older than max_checkpoint_age_hours as abandoned.

        Returns:
            List of checkpoints that were marked as abandoned.
        """
        now = datetime.now(timezone.utc)
        cutoff = now - timedelta(hours=self._max_checkpoint_age_hours)
        abandoned: list[ExecutionCheckpoint] = []

        for cp in self._checkpoints:
            if cp.status == CheckpointStatus.active and cp.created_at < cutoff:
                cp.status = CheckpointStatus.abandoned
                cp.updated_at = now
                abandoned.append(cp)

        return abandoned

    def list_active(self) -> list[ExecutionCheckpoint]:
        """Get all active checkpoints.

        Returns:
            List of checkpoints with active status.
        """
        return [
            cp for cp in self._checkpoints if cp.status == CheckpointStatus.active
        ]

    def resume_from_checkpoint(self, task_id: uuid.UUID) -> dict | None:
        """Load the latest active checkpoint state for resumption.

        Convenience method that returns just the state dictionary
        from the most recent active checkpoint.

        Args:
            task_id: The task to resume.

        Returns:
            The state_json dict from the latest active checkpoint,
            or None if no active checkpoint exists.
        """
        latest = self.load_latest(task_id)
        if latest is None:
            return None
        return latest.state_json

    def recover_interrupted(self) -> list[tuple[uuid.UUID, dict]]:
        """Find all active checkpoints for startup recovery.

        Used during system startup to identify tasks that were
        interrupted and need to be resumed.

        Returns:
            List of (task_id, state_json) tuples for all active checkpoints.
        """
        seen_tasks: set[uuid.UUID] = set()
        results: list[tuple[uuid.UUID, dict]] = []

        for cp in sorted(
            self._checkpoints, key=lambda c: c.created_at, reverse=True
        ):
            if cp.status == CheckpointStatus.active and cp.task_id not in seen_tasks:
                seen_tasks.add(cp.task_id)
                results.append((cp.task_id, cp.state_json))

        return results
