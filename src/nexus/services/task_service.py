"""Task Service - CRUD and status management for tasks."""

import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select, update, delete
from sqlalchemy.ext.asyncio import AsyncSession

from nexus.models.task import Task


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

        Returns:
            The newly created Task instance.
        """
        task = Task(
            company_id=company_id,
            title=title,
            description=description,
            priority=priority,
            project_id=project_id,
            assigned_agent_id=assigned_agent_id,
            parent_task_id=parent_task_id,
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
