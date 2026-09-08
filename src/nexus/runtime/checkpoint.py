"""Durable Execution Checkpoints - crash recovery for long-running tasks.

Provides a database-backed checkpointing system that allows tasks to save their progress
at intermediate steps and resume execution after failures or restarts.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Any

from sqlalchemy import Column, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.types import JSON
from sqlmodel import Field, SQLModel

from nexus.models._time import utcnow

logger = logging.getLogger(__name__)


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
    state_json: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    status: str = Field(default=CheckpointStatus.active)
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime | None = Field(default=None)


def build_checkpoint_state(
    agent_context: dict[str, Any],
    completed_steps: list[int],
    intermediate_results: list[dict[str, Any]],
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
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


class DurableCheckpointService:
    """Database-backed checkpoint service for task execution recovery.

    Provides transactional persistence of execution checkpoints to the
    execution_checkpoints table using async SQLAlchemy sessions.
    """

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession] | None = None,
        max_checkpoint_age_hours: int = 24,
    ) -> None:
        """Initialize the durable checkpoint service.

        Args:
            session_factory: Optional async session maker for auto-managing sessions.
            max_checkpoint_age_hours: Default TTL for stale checkpoints.
        """
        self._session_factory = session_factory
        self._max_checkpoint_age_hours = max_checkpoint_age_hours

    @classmethod
    async def save_checkpoint(
        cls,
        task_id: uuid.UUID,
        step_index: int,
        state: dict[str, Any],
        session: AsyncSession,
    ) -> ExecutionCheckpoint:
        """Upserts/saves checkpoint atomically to execution_checkpoints table.

        Args:
            task_id: The task this checkpoint belongs to.
            step_index: The current step index being checkpointed.
            state: The execution state to persist.
            session: The active AsyncSession.

        Returns:
            The created or updated ExecutionCheckpoint instance.
        """
        now = utcnow()

        stmt = (
            select(ExecutionCheckpoint)
            .where(
                ExecutionCheckpoint.task_id == task_id,
                ExecutionCheckpoint.step_index == step_index,
                ExecutionCheckpoint.status == CheckpointStatus.active,
            )
            .limit(1)
        )
        result = await session.execute(stmt)
        checkpoint = result.scalar_one_or_none()

        if checkpoint is not None:
            checkpoint.state_json = state
            checkpoint.updated_at = now
            session.add(checkpoint)
        else:
            checkpoint = ExecutionCheckpoint(
                task_id=task_id,
                step_index=step_index,
                state_json=state,
                status=CheckpointStatus.active,
                created_at=now,
                updated_at=now,
            )
            session.add(checkpoint)

        await session.flush()
        return checkpoint

    @classmethod
    async def load_latest(
        cls,
        task_id: uuid.UUID,
        session: AsyncSession,
    ) -> ExecutionCheckpoint | None:
        """Returns the most recent active checkpoint for the task.

        Args:
            task_id: The task identifier to query.
            session: The active AsyncSession.

        Returns:
            The latest active checkpoint or None.
        """
        stmt = (
            select(ExecutionCheckpoint)
            .where(
                ExecutionCheckpoint.task_id == task_id,
                ExecutionCheckpoint.status == CheckpointStatus.active,
            )
            .order_by(
                ExecutionCheckpoint.step_index.desc(),
                ExecutionCheckpoint.created_at.desc(),
            )
            .limit(1)
        )
        result = await session.execute(stmt)
        cp = result.scalar_one_or_none()
        if cp is not None and not isinstance(cp, ExecutionCheckpoint):
            return None
        return cp

    @classmethod
    async def abandon_stale(
        cls,
        max_age_hours: int,
        session: AsyncSession,
    ) -> int:
        """Marks checkpoints older than TTL as abandoned.

        Args:
            max_age_hours: Age threshold in hours.
            session: The active AsyncSession.

        Returns:
            Number of checkpoints marked abandoned.
        """
        now = utcnow()
        cutoff = now - timedelta(hours=max_age_hours)

        stmt = select(ExecutionCheckpoint).where(
            ExecutionCheckpoint.status == CheckpointStatus.active,
            ExecutionCheckpoint.created_at < cutoff,
        )
        result = await session.execute(stmt)
        stale_checkpoints = list(result.scalars().all())

        for cp in stale_checkpoints:
            cp.status = CheckpointStatus.abandoned
            cp.updated_at = now
            session.add(cp)

        if stale_checkpoints:
            await session.flush()

        return len(stale_checkpoints)

    @classmethod
    async def mark_completed(
        cls,
        task_id: uuid.UUID,
        session: AsyncSession,
    ) -> None:
        """Transitions active checkpoints to completed upon task success.

        Args:
            task_id: The task whose checkpoints to mark completed.
            session: The active AsyncSession.
        """
        now = utcnow()
        stmt = select(ExecutionCheckpoint).where(
            ExecutionCheckpoint.task_id == task_id,
            ExecutionCheckpoint.status == CheckpointStatus.active,
        )
        result = await session.execute(stmt)
        active_checkpoints = list(result.scalars().all())

        for cp in active_checkpoints:
            cp.status = CheckpointStatus.completed
            cp.updated_at = now
            session.add(cp)

        if active_checkpoints:
            await session.flush()

    @classmethod
    async def list_active(
        cls,
        session: AsyncSession,
    ) -> list[ExecutionCheckpoint]:
        """Get all active checkpoints across all tasks.

        Args:
            session: The active AsyncSession.

        Returns:
            List of active checkpoints ordered by creation time descending.
        """
        stmt = (
            select(ExecutionCheckpoint)
            .where(ExecutionCheckpoint.status == CheckpointStatus.active)
            .order_by(ExecutionCheckpoint.created_at.desc())
        )
        result = await session.execute(stmt)
        return list(result.scalars().all())

    @classmethod
    async def recover_interrupted(
        cls,
        session: AsyncSession,
    ) -> list[tuple[uuid.UUID, dict[str, Any]]]:
        """Find all active checkpoints for startup recovery.

        Returns:
            List of (task_id, state_json) tuples for distinct tasks.
        """
        active = await cls.list_active(session)
        seen: set[uuid.UUID] = set()
        results: list[tuple[uuid.UUID, dict[str, Any]]] = []
        for cp in active:
            if cp.task_id not in seen:
                seen.add(cp.task_id)
                results.append((cp.task_id, cp.state_json))
        return results

    @classmethod
    async def resume_from_checkpoint(
        cls,
        task_id: uuid.UUID,
        session: AsyncSession,
    ) -> dict[str, Any] | None:
        """Load the latest active checkpoint state for resumption.

        Args:
            task_id: Task to resume.
            session: The active AsyncSession.

        Returns:
            The state_json dictionary or None.
        """
        cp = await cls.load_latest(task_id, session)
        if cp is None:
            return None
        return cp.state_json

    @classmethod
    async def cleanup(
        cls,
        task_id: uuid.UUID,
        session: AsyncSession,
    ) -> None:
        """Alias for mark_completed."""
        await cls.mark_completed(task_id, session)


async def save_checkpoint(
    task_id: uuid.UUID,
    step_index: int,
    state: dict[str, Any],
    session: AsyncSession,
) -> ExecutionCheckpoint:
    """Save/upsert a checkpoint to the database atomically."""
    return await DurableCheckpointService.save_checkpoint(
        task_id=task_id,
        step_index=step_index,
        state=state,
        session=session,
    )


async def load_latest(
    task_id: uuid.UUID,
    session: AsyncSession,
) -> ExecutionCheckpoint | None:
    """Load the latest active checkpoint for a task from the database."""
    return await DurableCheckpointService.load_latest(
        task_id=task_id,
        session=session,
    )


async def abandon_stale(
    max_age_hours: int,
    session: AsyncSession,
) -> int:
    """Mark active checkpoints older than TTL as abandoned."""
    return await DurableCheckpointService.abandon_stale(
        max_age_hours=max_age_hours,
        session=session,
    )


async def mark_completed(
    task_id: uuid.UUID,
    session: AsyncSession,
) -> None:
    """Mark all active checkpoints for a task as completed."""
    await DurableCheckpointService.mark_completed(
        task_id=task_id,
        session=session,
    )


async def resume_from_checkpoint(
    task_id: uuid.UUID,
    session: AsyncSession,
) -> dict[str, Any] | None:
    """Load latest active checkpoint state for resumption."""
    return await DurableCheckpointService.resume_from_checkpoint(
        task_id=task_id,
        session=session,
    )


async def save_checkpoint_nonblocking(
    task_id: uuid.UUID,
    step_index: int,
    state: dict[str, Any],
    session: AsyncSession | None = None,
) -> ExecutionCheckpoint | None:
    """Save checkpoint transactionally and non-blockingly.

    If session is provided, flushes on it.
    If session is not provided, opens a new session with async_session_factory,
    saves, commits, and suppresses errors to avoid blocking execution.
    """
    if session is not None:
        try:
            return await save_checkpoint(task_id, step_index, state, session)
        except Exception as exc:
            logger.warning("Checkpoint save on active session failed for task %s: %s", task_id, exc)
            return None

    try:
        from nexus.database import async_session_factory

        async with async_session_factory() as new_session:
            cp = await save_checkpoint(task_id, step_index, state, new_session)
            await new_session.commit()
            return cp
    except Exception as exc:
        logger.warning("Background checkpoint save failed for task %s: %s", task_id, exc)
        return None


def _normalize_dt(dt: datetime | None) -> datetime:
    """Normalize datetime to naive UTC for consistent comparison."""
    if dt is None:
        return utcnow()
    if dt.tzinfo is not None:
        return dt.replace(tzinfo=None)
    return dt


class CheckpointManager:
    """In-memory checkpoint manager for task execution recovery.

    Maintains full backward compatibility for in-memory and synchronous testing.
    Can also delegate to database session when provided.
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
        self, task_id: uuid.UUID, step_index: int, state: dict[str, Any]
    ) -> ExecutionCheckpoint:
        """Save a new checkpoint in-memory for a task."""
        now = utcnow()
        checkpoint = ExecutionCheckpoint(
            task_id=task_id,
            step_index=step_index,
            state_json=state,
            status=CheckpointStatus.active,
            created_at=now,
            updated_at=now,
        )
        self._checkpoints.append(checkpoint)
        return checkpoint

    def load_latest(self, task_id: uuid.UUID) -> ExecutionCheckpoint | None:
        """Load the most recent active checkpoint for a task."""
        active = [
            cp
            for cp in self._checkpoints
            if cp.task_id == task_id and cp.status == CheckpointStatus.active
        ]
        if not active:
            return None
        return max(active, key=lambda cp: (cp.step_index, _normalize_dt(cp.created_at)))

    def cleanup(self, task_id: uuid.UUID) -> None:
        """Mark all checkpoints for a task as completed."""
        now = utcnow()
        for cp in self._checkpoints:
            if cp.task_id == task_id and cp.status == CheckpointStatus.active:
                cp.status = CheckpointStatus.completed
                cp.updated_at = now

    def mark_completed(self, task_id: uuid.UUID) -> None:
        """Alias for cleanup."""
        self.cleanup(task_id)

    def abandon_stale(self) -> list[ExecutionCheckpoint]:
        """Mark checkpoints older than max_checkpoint_age_hours as abandoned."""
        now = utcnow()
        cutoff = now - timedelta(hours=self._max_checkpoint_age_hours)
        abandoned: list[ExecutionCheckpoint] = []

        for cp in self._checkpoints:
            if cp.status == CheckpointStatus.active and _normalize_dt(cp.created_at) < cutoff:
                cp.status = CheckpointStatus.abandoned
                cp.updated_at = now
                abandoned.append(cp)

        return abandoned

    def list_active(self) -> list[ExecutionCheckpoint]:
        """Get all active checkpoints."""
        return [
            cp for cp in self._checkpoints if cp.status == CheckpointStatus.active
        ]

    def resume_from_checkpoint(self, task_id: uuid.UUID) -> dict[str, Any] | None:
        """Load the latest active checkpoint state for resumption."""
        latest = self.load_latest(task_id)
        if latest is None:
            return None
        return latest.state_json

    def recover_interrupted(self) -> list[tuple[uuid.UUID, dict[str, Any]]]:
        """Find all active checkpoints for startup recovery."""
        seen_tasks: set[uuid.UUID] = set()
        results: list[tuple[uuid.UUID, dict[str, Any]]] = []

        for cp in sorted(
            self._checkpoints, key=lambda c: (c.step_index, _normalize_dt(c.created_at)), reverse=True
        ):
            if cp.status == CheckpointStatus.active and cp.task_id not in seen_tasks:
                seen_tasks.add(cp.task_id)
                results.append((cp.task_id, cp.state_json))

        return results

