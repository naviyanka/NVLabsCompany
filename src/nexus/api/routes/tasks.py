"""Task API endpoints - CRUD, assignment, and status management."""

import uuid
from datetime import datetime
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
    """Create a new task in a company.

    If assigned_agent_id is not specified, uses AgentRouter to evaluate available
    agents in the company and auto-assign the highest-scoring candidate.
    """
    assigned_id = body.assigned_agent_id

    if assigned_id is None:
        try:
            from nexus.models.agent import Agent
            from nexus.orchestration.router import AgentCandidate, AgentRouter

            stmt = select(Agent).where(
                Agent.company_id == company_id, Agent.status == "active"
            )
            res = await db.execute(stmt)
            agents = list(res.scalars().all())

            if agents:
                candidates = [
                    AgentCandidate(
                        agent_id=a.id,
                        name=a.name,
                        skills=a.capabilities or [],
                        current_workload=0,
                        max_concurrent=5,
                        budget_remaining_cents=(
                            a.budget_monthly_cents - a.spent_monthly_cents
                        ),
                        performance_score=(
                            (a.performance_score or 50) / 100.0
                        ),
                        status=a.status,
                    )
                    for a in agents
                ]

                router_engine = AgentRouter()
                decision = await router_engine.route_task(
                    task_description=f"{body.title}\n{body.description or ''}",
                    required_skills=[],
                    estimated_cost_cents=100,
                    available_agents=candidates,
                )
                if decision:
                    assigned_id = decision.agent_id
        except Exception:
            pass  # Fall back to unassigned if routing scoring fails

    task = Task(
        company_id=company_id,
        title=body.title,
        description=body.description,
        priority=body.priority,
        project_id=body.project_id,
        assigned_agent_id=assigned_id,
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
            updated_at=datetime.utcnow(),
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
        "updated_at": datetime.utcnow(),
    }
    if body.status == "running":
        values["started_at"] = datetime.utcnow()
    elif body.status == "completed":
        values["completed_at"] = datetime.utcnow()
        if body.result:
            values["result"] = body.result
    elif body.status == "failed":
        values["completed_at"] = datetime.utcnow()
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



class SubtaskCreate(BaseModel):
    """Request body for creating a subtask."""

    title: str
    description: str | None = None
    priority: int = 0
    assigned_agent_id: uuid.UUID | None = None


class ReassignBody(BaseModel):
    """Request body for reassigning a task."""

    agent_id: uuid.UUID


@router.get("/api/v1/companies/{company_id}/tasks/stats")
async def get_task_stats(company_id: uuid.UUID, db: DbSession) -> dict[str, Any]:
    """Aggregated task statistics for a company."""
    from sqlalchemy import func
    from nexus.models.agent import Agent

    # Total
    total_result = await db.execute(
        select(func.count(Task.id)).where(Task.company_id == company_id)
    )
    total = total_result.scalar() or 0

    # By status
    status_result = await db.execute(
        select(Task.status, func.count(Task.id))
        .where(Task.company_id == company_id)
        .group_by(Task.status)
    )
    by_status = dict(status_result.all())

    # By priority
    priority_result = await db.execute(
        select(Task.priority, func.count(Task.id))
        .where(Task.company_id == company_id)
        .group_by(Task.priority)
    )
    by_priority = {str(k): v for k, v in priority_result.all()}

    # Top agents by task count
    top_agents_result = await db.execute(
        select(Task.assigned_agent_id, func.count(Task.id).label("count"))
        .where(Task.company_id == company_id, Task.assigned_agent_id.isnot(None))
        .group_by(Task.assigned_agent_id)
        .order_by(func.count(Task.id).desc())
        .limit(5)
    )
    top_agents_rows = top_agents_result.all()

    top_agents = []
    for agent_id_val, count in top_agents_rows:
        agent_result = await db.execute(
            select(Agent.name).where(Agent.id == agent_id_val)
        )
        name = agent_result.scalar() or "Unknown"
        top_agents.append({"agent_id": str(agent_id_val), "name": name, "count": count})

    return {
        "total": total,
        "by_status": by_status,
        "by_priority": by_priority,
        "top_agents": top_agents,
    }


@router.get("/api/v1/tasks/{task_id}/subtasks", response_model=list[TaskResponse])
async def list_subtasks(task_id: uuid.UUID, db: DbSession, company_id: CurrentCompanyId) -> Any:
    """List subtasks for a given task."""
    stmt = (
        select(Task)
        .where(Task.parent_task_id == task_id, Task.company_id == company_id)
        .order_by(Task.priority.desc())
    )
    result = await db.execute(stmt)
    return list(result.scalars().all())


@router.post(
    "/api/v1/tasks/{task_id}/subtasks",
    status_code=status.HTTP_201_CREATED,
    response_model=TaskResponse,
)
async def create_subtask(
    task_id: uuid.UUID, body: SubtaskCreate, db: DbSession, company_id: CurrentCompanyId
) -> Any:
    """Create a subtask under an existing task."""
    # Verify parent task exists and belongs to company
    parent_stmt = select(Task).where(Task.id == task_id, Task.company_id == company_id)
    parent_result = await db.execute(parent_stmt)
    parent = parent_result.scalar_one_or_none()
    if parent is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Parent task {task_id} not found",
        )

    subtask = Task(
        company_id=parent.company_id,
        title=body.title,
        description=body.description,
        priority=body.priority,
        assigned_agent_id=body.assigned_agent_id,
        parent_task_id=task_id,
    )
    db.add(subtask)
    await db.flush()
    return subtask


@router.post("/api/v1/tasks/{task_id}/reassign", response_model=TaskResponse)
async def reassign_task(
    task_id: uuid.UUID, body: ReassignBody, db: DbSession, company_id: CurrentCompanyId
) -> Any:
    """Reassign a task to a different agent."""
    stmt = (
        update(Task)
        .where(Task.id == task_id, Task.company_id == company_id)
        .values(assigned_agent_id=body.agent_id, updated_at=datetime.utcnow())
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


@router.post("/api/v1/tasks/{task_id}/cancel", response_model=TaskResponse)
async def cancel_task(
    task_id: uuid.UUID, db: DbSession, company_id: CurrentCompanyId
) -> Any:
    """Cancel a task."""
    stmt = (
        update(Task)
        .where(Task.id == task_id, Task.company_id == company_id)
        .values(status="cancelled", completed_at=datetime.utcnow(), updated_at=datetime.utcnow())
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



@router.get("/api/v1/companies/{company_id}/tasks/stats")
async def get_task_stats(company_id: uuid.UUID, db: DbSession) -> dict[str, Any]:
    """Task statistics: counts by status, priority, top agents."""
    from sqlalchemy import func
    total = await db.execute(select(func.count(Task.id)).where(Task.company_id == company_id))
    by_status = await db.execute(select(Task.status, func.count(Task.id)).where(Task.company_id == company_id).group_by(Task.status))
    by_priority = await db.execute(select(Task.priority, func.count(Task.id)).where(Task.company_id == company_id).group_by(Task.priority))
    top_agents = await db.execute(
        select(Task.assigned_agent_id, func.count(Task.id)).where(Task.company_id == company_id, Task.assigned_agent_id != None)
        .group_by(Task.assigned_agent_id).order_by(func.count(Task.id).desc()).limit(5)
    )
    return {"total": total.scalar() or 0, "by_status": dict(by_status.all()), "by_priority": dict(by_priority.all()), "top_agents": [{"agent_id": str(a), "count": c} for a, c in top_agents.all()]}


@router.get("/api/v1/tasks/{task_id}/subtasks", response_model=list[TaskResponse])
async def get_subtasks(task_id: uuid.UUID, db: DbSession, company_id: CurrentCompanyId) -> Any:
    """List subtasks of a task."""
    stmt = select(Task).where(Task.parent_task_id == task_id, Task.company_id == company_id)
    result = await db.execute(stmt)
    return list(result.scalars().all())


@router.post("/api/v1/tasks/{task_id}/subtasks", status_code=status.HTTP_201_CREATED, response_model=TaskResponse)
async def create_subtask(task_id: uuid.UUID, body: TaskCreate, db: DbSession, company_id: CurrentCompanyId) -> Any:
    """Create a subtask under a parent task."""
    subtask = Task(company_id=company_id, parent_task_id=task_id, title=body.title, description=body.description, priority=body.priority or 0, assigned_agent_id=body.assigned_agent_id)
    db.add(subtask)
    await db.flush()
    return subtask


@router.post("/api/v1/tasks/{task_id}/reassign", response_model=TaskResponse)
async def reassign_task(task_id: uuid.UUID, body: TaskAssign, db: DbSession, company_id: CurrentCompanyId) -> Any:
    """Reassign task to a different agent."""
    stmt = update(Task).where(Task.id == task_id, Task.company_id == company_id).values(assigned_agent_id=body.agent_id, updated_at=datetime.utcnow())
    await db.execute(stmt)
    result = await db.execute(select(Task).where(Task.id == task_id, Task.company_id == company_id))
    task = result.scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    return task


@router.post("/api/v1/tasks/{task_id}/cancel", response_model=TaskResponse)
async def cancel_task(task_id: uuid.UUID, db: DbSession, company_id: CurrentCompanyId) -> Any:
    """Cancel a task."""
    stmt = update(Task).where(Task.id == task_id, Task.company_id == company_id).values(status="cancelled", completed_at=datetime.utcnow(), updated_at=datetime.utcnow())
    await db.execute(stmt)
    result = await db.execute(select(Task).where(Task.id == task_id, Task.company_id == company_id))
    task = result.scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    return task


@router.post("/api/v1/tasks/{task_id}/decompose")
async def decompose_task(
    task_id: uuid.UUID, db: DbSession, company_id: CurrentCompanyId
) -> dict[str, Any]:
    """Decompose a task into subtasks using the TaskPlanner orchestration module.

    Uses the orchestration layer to analyze the task description and generate
    a set of ordered subtasks with dependencies. Creates subtask records in DB.
    """
    from nexus.orchestration.planner import TaskPlanner

    stmt = select(Task).where(Task.id == task_id, Task.company_id == company_id)
    result = await db.execute(stmt)
    task = result.scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    planner = TaskPlanner(max_subtasks=10)
    subtasks = await planner.decompose_task(
        task_id=task.id,
        description=f"{task.title}\n{task.description or ''}",
        context={"priority": task.priority, "status": task.status},
    )

    # Create subtask records in DB
    created = []
    for st in subtasks:
        subtask_record = Task(
            company_id=company_id,
            title=st.description[:500],
            description=f"Subtask of {task.title}",
            priority=task.priority,
            parent_id=task.id,
            status="pending",
        )
        db.add(subtask_record)
        await db.flush()
        created.append({
            "id": str(subtask_record.id),
            "title": subtask_record.title,
            "status": subtask_record.status,
            "dependencies": [str(d) for d in st.dependencies],
        })

    await db.commit()

    return {
        "task_id": str(task_id),
        "subtasks_created": len(created),
        "subtasks": created,
    }
