"""Task Service - CRUD and status management for tasks."""

import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import select, update, delete
from sqlalchemy.ext.asyncio import AsyncSession

from nexus.models.agent import Agent
from nexus.models.task import Task

# A parent in one of these cannot take new children.
CLOSED_TASK_STATUSES = ("completed", "failed", "cancelled")
# An agent in one of these cannot be given work (same set the attempt worker refuses).
UNASSIGNABLE_AGENT_STATUSES = ("terminated", "archived", "paused")


def _error(status_code: int, code: str, message: str) -> HTTPException:
    return HTTPException(status_code=status_code, detail={"code": code, "message": message})


def refuse_closed_parent(parent: Task) -> None:
    """A completed, failed or cancelled task takes no new children (409)."""
    if parent.status in CLOSED_TASK_STATUSES:
        raise _error(
            status.HTTP_409_CONFLICT, "PARENT_TASK_CLOSED", "The parent task is closed"
        )


async def require_parent(
    db: AsyncSession, company_id: uuid.UUID, parent_task_id: uuid.UUID
) -> Task:
    """The open parent in this company, loaded by (company, id).

    A foreign task and a missing one get the same 404 and the answer names no id. A
    foreign-key check is never enough here: it sees every tenant's rows, RLS or not.
    """
    parent = (
        await db.execute(
            select(Task).where(Task.id == parent_task_id, Task.company_id == company_id)
        )
    ).scalar_one_or_none()
    if parent is None:
        raise _error(status.HTTP_404_NOT_FOUND, "PARENT_TASK_NOT_FOUND", "Parent task not found")
    refuse_closed_parent(parent)
    return parent


async def refuse_if_agent_owns_work(
    db: AsyncSession, company_id: uuid.UUID, agent_id: uuid.UUID
) -> None:
    """An agent that owns open work, or runs an attempt, cannot be deleted (409).

    Open work is any task of this company assigned to the agent that is not completed,
    failed or cancelled: an ordinary task, a manager's work order, an employee's work child
    (including one waiting in review). A live attempt counts even if its task moved on.
    Ownership is never nulled for any of these. A terminal task only loses its owner (the
    caller clears it); a recorded attempt is history that pins the agent (AGENT_HAS_HISTORY).
    """
    from nexus.models.task_attempt import ACTIVE_ATTEMPT_STATUSES, TaskAttempt

    open_task = await db.scalar(
        select(Task.id)
        .where(
            Task.company_id == company_id,
            Task.assigned_agent_id == agent_id,
            Task.status.not_in(CLOSED_TASK_STATUSES),
        )
        .limit(1)
    )
    live_attempt = await db.scalar(
        select(TaskAttempt.id)
        .where(
            TaskAttempt.company_id == company_id,
            TaskAttempt.agent_id == agent_id,
            TaskAttempt.status.in_(ACTIVE_ATTEMPT_STATUSES),
        )
        .limit(1)
    )
    if open_task is not None or live_attempt is not None:
        raise _error(
            status.HTTP_409_CONFLICT,
            "AGENT_OWNS_ACTIVE_WORK",
            "The agent owns active work; reassign or cancel it first",
        )
    history = await db.scalar(
        select(TaskAttempt.id)
        .where(TaskAttempt.company_id == company_id, TaskAttempt.agent_id == agent_id)
        .limit(1)
    )
    if history is not None:
        raise agent_history_error()


def agent_history_error() -> HTTPException:
    return _error(
        status.HTTP_409_CONFLICT,
        "AGENT_HAS_HISTORY",
        "The agent has recorded work or activity and cannot be deleted; pause it instead",
    )


async def require_assignable_agent(
    db: AsyncSession, company_id: uuid.UUID, agent_id: uuid.UUID
) -> Agent:
    """The agent in this company that can take work, loaded by (company, id).

    A foreign agent and a missing one get the same 404 (nothing about the foreign agent
    is read, woken or changed); a paused, terminated or archived one gets 409.
    """
    agent = (
        await db.execute(
            select(Agent).where(Agent.id == agent_id, Agent.company_id == company_id)
        )
    ).scalar_one_or_none()
    if agent is None:
        raise _error(status.HTTP_404_NOT_FOUND, "AGENT_NOT_FOUND", "Agent not found")
    if agent.status in UNASSIGNABLE_AGENT_STATUSES:
        raise _error(
            status.HTTP_409_CONFLICT, "AGENT_NOT_ASSIGNABLE", "The agent cannot take work"
        )
    return agent


class TaskService:
    """Service layer for task CRUD operations and status management.

    Handles task creation, retrieval, assignment, status transitions,
    completion, and failure recording.
    """

    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def create_task(
        self,
        company_id: uuid.UUID,
        title: str,
        description: str | None = None,
        priority: int = 0,
        project_id: uuid.UUID | None = None,
        assigned_agent_id: uuid.UUID | None = None,
        parent_task_id: uuid.UUID | None = None,
        work_spec: dict[str, Any] | None = None,
    ) -> Task:
        """Create a new task.

        Args:
            company_id: The company this task belongs to.
            title: Task title.
            description: Optional task description.
            priority: Priority level (higher = more important).
            project_id: Optional project this task belongs to.
            assigned_agent_id: Optional agent to assign immediately.
            parent_task_id: Optional parent task for subtask hierarchy.
            work_spec: Optional, already validated, work spec.

        Returns:
            The newly created Task instance.

        Raises:
            HTTPException: 409 WORK_OWNED_BY_LIFECYCLE for a work order or work child
                parent; 404 / 409 for a foreign, missing or closed parent; 404 / 409 for
                a foreign, missing or unavailable agent. Nothing is inserted then.
            There is no re-parent operation, so a new child cannot close a cycle.
        """
        if parent_task_id is not None:
            from nexus.services import work_service

            work_service.refuse_if_work_owned(
                await work_service.is_work_owned(self._db, company_id, parent_task_id)
            )
            await require_parent(self._db, company_id, parent_task_id)
        if assigned_agent_id is not None:
            await require_assignable_agent(self._db, company_id, assigned_agent_id)
        task = Task(
            company_id=company_id,
            title=title,
            description=description,
            priority=priority,
            project_id=project_id,
            assigned_agent_id=assigned_agent_id,
            parent_task_id=parent_task_id,
            work_spec=work_spec,
        )
        self._db.add(task)
        await self._db.flush()
        return task

    async def get_task(self, task_id: uuid.UUID) -> Task | None:
        """Retrieve a single task by ID.

        Args:
            task_id: The task's unique identifier.

        Returns:
            The Task instance, or None if not found.
        """
        stmt = select(Task).where(Task.id == task_id)
        result = await self._db.execute(stmt)
        return result.scalar_one_or_none()

    async def list_tasks(
        self,
        company_id: uuid.UUID,
        status: str | None = None,
        assigned_agent_id: uuid.UUID | None = None,
        project_id: uuid.UUID | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[Task]:
        """List tasks for a company with optional filters.

        Args:
            company_id: The company to list tasks for.
            status: Optional filter by task status.
            assigned_agent_id: Optional filter by assigned agent.
            project_id: Optional filter by project.
            limit: Maximum number of results.
            offset: Pagination offset.

        Returns:
            List of matching Task instances.
        """
        stmt = select(Task).where(Task.company_id == company_id)

        if status:
            stmt = stmt.where(Task.status == status)
        if assigned_agent_id:
            stmt = stmt.where(Task.assigned_agent_id == assigned_agent_id)
        if project_id:
            stmt = stmt.where(Task.project_id == project_id)

        stmt = stmt.offset(offset).limit(limit).order_by(Task.priority.desc())
        result = await self._db.execute(stmt)
        return list(result.scalars().all())

    async def assign_task(
        self, task_id: uuid.UUID, agent_id: uuid.UUID
    ) -> Task | None:
        """Assign a task to an agent.

        Args:
            task_id: The task to assign.
            agent_id: The agent to assign the task to.

        Returns:
            The updated Task instance.
        """
        stmt = (
            update(Task)
            .where(Task.id == task_id)
            .values(
                assigned_agent_id=agent_id,
                updated_at=datetime.now(timezone.utc),
            )
        )
        await self._db.execute(stmt)
        return await self.get_task(task_id)

    async def update_status(
        self, task_id: uuid.UUID, status: str
    ) -> Task | None:
        """Update the status of a task.

        Args:
            task_id: The task to update.
            status: The new status value.

        Returns:
            The updated Task instance.
        """
        values: dict[str, Any] = {
            "status": status,
            "updated_at": datetime.now(timezone.utc),
        }
        if status == "running":
            values["started_at"] = datetime.now(timezone.utc)

        stmt = update(Task).where(Task.id == task_id).values(**values)
        await self._db.execute(stmt)
        return await self.get_task(task_id)

    async def complete_task(
        self, task_id: uuid.UUID, result: str | None = None
    ) -> Task | None:
        """Mark a task as completed.

        Args:
            task_id: The task to complete.
            result: Optional result text.

        Returns:
            The updated Task instance.
        """
        stmt = (
            update(Task)
            .where(Task.id == task_id)
            .values(
                status="completed",
                result=result,
                completed_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc),
            )
        )
        await self._db.execute(stmt)
        return await self.get_task(task_id)

    async def fail_task(
        self, task_id: uuid.UUID, error: str
    ) -> Task | None:
        """Mark a task as failed with an error message.

        Args:
            task_id: The task that failed.
            error: Error description.

        Returns:
            The updated Task instance.
        """
        stmt = (
            update(Task)
            .where(Task.id == task_id)
            .values(
                status="failed",
                error=error,
                completed_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc),
            )
        )
        await self._db.execute(stmt)
        return await self.get_task(task_id)
