"""Task API endpoints - CRUD, assignment, and status management."""

import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select, update

from nexus.api.deps import CurrentCompanyId, DbSession
from nexus.models.task import Task

router = APIRouter(tags=["tasks"])


class TaskCreate(BaseModel):
    """Request body for creating a task."""

    title: str
    description: str | None = None
    priority: int = 0
    project_id: uuid.UUID | None = None
    assigned_agent_id: uuid.UUID | None = None
    parent_task_id: uuid.UUID | None = None


class TaskAssign(BaseModel):
    """Request body for assigning a task."""

    agent_id: uuid.UUID


class TaskStatusUpdate(BaseModel):
    """Request body for updating task status."""

    status: str
    result: str | None = None
    error: str | None = None


class TaskResponse(BaseModel):
    """Response model for a task."""

    id: uuid.UUID
    company_id: uuid.UUID
    project_id: uuid.UUID | None = None
    title: str
    description: str | None = None
    status: str
    priority: int
    assigned_agent_id: uuid.UUID | None = None
    parent_task_id: uuid.UUID | None = None
    result: str | None = None
    error: str | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


@router.post(
    "/api/v1/companies/{company_id}/tasks",
    status_code=status.HTTP_201_CREATED,
    response_model=TaskResponse,
)
async def create_task(
    company_id: uuid.UUID, body: TaskCreate, db: DbSession
) -> Any:
    """Create a new task in a company."""
    task = Task(
        company_id=company_id,
        title=body.title,
        description=body.description,
        priority=body.priority,
        project_id=body.project_id,
        assigned_agent_id=body.assigned_agent_id,
        parent_task_id=body.parent_task_id,
    )
    db.add(task)
    await db.flush()
    return task


@router.get(
    "/api/v1/companies/{company_id}/tasks",
    response_model=list[TaskResponse],
)
async def list_tasks(
    company_id: uuid.UUID,
    db: DbSession,
    status_filter: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> Any:
    """List tasks for a company."""
    stmt = select(Task).where(Task.company_id == company_id)
    if status_filter:
        stmt = stmt.where(Task.status == status_filter)
    stmt = stmt.offset(offset).limit(limit).order_by(Task.priority.desc())
    result = await db.execute(stmt)
    return list(result.scalars().all())


@router.get("/api/v1/tasks/{task_id}", response_model=TaskResponse)
async def get_task(task_id: uuid.UUID, db: DbSession, company_id: CurrentCompanyId) -> Any:
    """Get a task by ID."""
    stmt = select(Task).where(Task.id == task_id, Task.company_id == company_id)
    result = await db.execute(stmt)
    task = result.scalar_one_or_none()
    if task is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Task {task_id} not found",
        )
    return task


@router.put("/api/v1/tasks/{task_id}/assign", response_model=TaskResponse)
async def assign_task(
    task_id: uuid.UUID, body: TaskAssign, db: DbSession, company_id: CurrentCompanyId
) -> Any:
    """Assign a task to an agent."""
    stmt = (
        update(Task)
        .where(Task.id == task_id, Task.company_id == company_id)
        .values(
            assigned_agent_id=body.agent_id,
            updated_at=datetime.now(timezone.utc),
        )
    )
    await db.execute(stmt)

    result = await db.execute(select(Task).where(Task.id == task_id, Task.company_id == company_id))
    task = result.scalar_one_or_none()
    if task is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Task {task_id} not found",
        )
    return task


@router.put("/api/v1/tasks/{task_id}/status", response_model=TaskResponse)
async def update_task_status(
    task_id: uuid.UUID, body: TaskStatusUpdate, db: DbSession, company_id: CurrentCompanyId
) -> Any:
    """Update the status of a task."""
    values: dict[str, Any] = {
        "status": body.status,
        "updated_at": datetime.now(timezone.utc),
    }
    if body.status == "running":
        values["started_at"] = datetime.now(timezone.utc)
    elif body.status == "completed":
        values["completed_at"] = datetime.now(timezone.utc)
        if body.result:
            values["result"] = body.result
    elif body.status == "failed":
        values["completed_at"] = datetime.now(timezone.utc)
        if body.error:
            values["error"] = body.error

    stmt = update(Task).where(Task.id == task_id, Task.company_id == company_id).values(**values)
    await db.execute(stmt)

    result = await db.execute(select(Task).where(Task.id == task_id, Task.company_id == company_id))
    task = result.scalar_one_or_none()
    if task is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Task {task_id} not found",
        )
    return task
