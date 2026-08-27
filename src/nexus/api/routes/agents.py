"""Agent API endpoints - CRUD and lifecycle operations."""

import uuid
from datetime import timezone, datetime
from typing import Any

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select, update

from nexus.api.deps import CurrentCompanyId, DbSession
from nexus.models.agent import Agent

router = APIRouter(tags=["agents"])


class AgentCreate(BaseModel):
    """Request body for creating an agent."""

    name: str
    role: str
    title: str | None = None
    department_id: uuid.UUID | None = None
    team_id: uuid.UUID | None = None
    adapter_type: str = "langchain"
    adapter_config: dict[str, Any] | None = None
    model: str | None = None
    capabilities: list[str] | None = None
    responsibilities: str | None = None
    objectives: str | None = None
    soul_description: str | None = None
    budget_monthly_cents: int = 0
    autonomy_policy: dict[str, Any] | None = None


class AgentUpdate(BaseModel):
    """Request body for updating an agent."""

    name: str | None = None
    title: str | None = None
    role: str | None = None
    status: str | None = None
    adapter_type: str | None = None
    model: str | None = None
    capabilities: list[str] | None = None
    responsibilities: str | None = None
    objectives: str | None = None
    soul_description: str | None = None
    budget_monthly_cents: int | None = None
    autonomy_policy: dict[str, Any] | None = None


class AgentResponse(BaseModel):
    """Response model for an agent."""

    id: uuid.UUID
    company_id: uuid.UUID
    name: str
    title: str | None = None
    role: str
    department_id: uuid.UUID | None = None
    team_id: uuid.UUID | None = None
    manager_id: uuid.UUID | None = None
    status: str
    adapter_type: str
    model: str | None = None
    capabilities: list[str] | None = None
    responsibilities: str | None = None
    objectives: str | None = None
    budget_monthly_cents: int
    spent_monthly_cents: int
    soul_description: str | None = None
    autonomy_policy: dict[str, Any] | None = None
    last_heartbeat_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


@router.post(
    "/api/v1/companies/{company_id}/agents",
    status_code=status.HTTP_201_CREATED,
    response_model=AgentResponse,
)
async def create_agent(
    company_id: uuid.UUID, body: AgentCreate, db: DbSession
) -> Any:
    """Create a new agent in a company."""
    agent = Agent(
        company_id=company_id,
        name=body.name,
        role=body.role,
        title=body.title,
        department_id=body.department_id,
        team_id=body.team_id,
        adapter_type=body.adapter_type,
        adapter_config=body.adapter_config,
        model=body.model,
        capabilities=body.capabilities,
        responsibilities=body.responsibilities,
        objectives=body.objectives,
        soul_description=body.soul_description,
        budget_monthly_cents=body.budget_monthly_cents,
        autonomy_policy=body.autonomy_policy,
    )
    db.add(agent)
    await db.flush()

    # Audit: agent created
    from nexus.governance.audit_service import record_audit
    await record_audit(
        company_id, "agent.created",
        actor_type="user", resource_type="agent", resource_id=str(agent.id),
        details={"name": agent.name, "role": agent.role, "adapter_type": agent.adapter_type},
        db=db,
    )

    return agent


@router.get(
    "/api/v1/companies/{company_id}/agents",
    response_model=list[AgentResponse],
)
async def list_agents(
    company_id: uuid.UUID,
    db: DbSession,
    status_filter: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> Any:
    """List agents for a company."""
    stmt = select(Agent).where(Agent.company_id == company_id)
    if status_filter:
        stmt = stmt.where(Agent.status == status_filter)
    stmt = stmt.offset(offset).limit(limit).order_by(Agent.created_at.desc())
    result = await db.execute(stmt)
    return list(result.scalars().all())


@router.get("/api/v1/agents/{agent_id}", response_model=AgentResponse)
async def get_agent(agent_id: uuid.UUID, db: DbSession, company_id: CurrentCompanyId) -> Any:
    """Get an agent by ID."""
    stmt = select(Agent).where(Agent.id == agent_id, Agent.company_id == company_id)
    result = await db.execute(stmt)
    agent = result.scalar_one_or_none()
    if agent is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Agent {agent_id} not found",
        )
    return agent


@router.get(
    "/api/v1/companies/{company_id}/agents/{agent_id}",
    response_model=AgentResponse,
)
async def get_agent_company_scoped(
    company_id: uuid.UUID, agent_id: uuid.UUID, db: DbSession
) -> Any:
    """Get an agent by ID (company-scoped path for dashboard compat)."""
    stmt = select(Agent).where(Agent.id == agent_id, Agent.company_id == company_id)
    result = await db.execute(stmt)
    agent = result.scalar_one_or_none()
    if agent is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Agent {agent_id} not found",
        )
    return agent


@router.put("/api/v1/agents/{agent_id}", response_model=AgentResponse)
async def update_agent(
    agent_id: uuid.UUID, body: AgentUpdate, db: DbSession, company_id: CurrentCompanyId
) -> Any:
    """Update an agent."""
    updates = body.model_dump(exclude_unset=True)
    if not updates:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No fields to update",
        )
    updates["updated_at"] = datetime.now(timezone.utc)
    stmt = update(Agent).where(Agent.id == agent_id, Agent.company_id == company_id).values(**updates)
    await db.execute(stmt)

    result = await db.execute(select(Agent).where(Agent.id == agent_id, Agent.company_id == company_id))
    agent = result.scalar_one_or_none()
    if agent is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Agent {agent_id} not found",
        )
    return agent


@router.patch("/api/v1/agents/{agent_id}", response_model=AgentResponse)
async def patch_agent(
    agent_id: uuid.UUID, body: AgentUpdate, db: DbSession, company_id: CurrentCompanyId
) -> Any:
    """Partial update an agent (PATCH semantics, same logic as PUT)."""
    return await update_agent(agent_id, body, db, company_id)


@router.patch(
    "/api/v1/companies/{company_id}/agents/{agent_id}",
    response_model=AgentResponse,
)
async def patch_agent_company_scoped(
    company_id: uuid.UUID, agent_id: uuid.UUID, body: AgentUpdate, db: DbSession
) -> Any:
    """Partial update via company-scoped path (dashboard compat)."""
    updates = body.model_dump(exclude_unset=True)
    if not updates:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No fields to update",
        )
    updates["updated_at"] = datetime.now(timezone.utc)
    stmt = update(Agent).where(Agent.id == agent_id, Agent.company_id == company_id).values(**updates)
    await db.execute(stmt)

    result = await db.execute(select(Agent).where(Agent.id == agent_id, Agent.company_id == company_id))
    agent = result.scalar_one_or_none()
    if agent is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Agent {agent_id} not found",
        )
    return agent


@router.post("/api/v1/agents/{agent_id}/wake", response_model=AgentResponse)
async def wake_agent(agent_id: uuid.UUID, db: DbSession, company_id: CurrentCompanyId) -> Any:
    """Wake an agent (transition to ready state)."""
    stmt = select(Agent).where(Agent.id == agent_id, Agent.company_id == company_id)
    result = await db.execute(stmt)
    agent = result.scalar_one_or_none()
    if agent is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Agent {agent_id} not found",
        )
    if agent.status not in ("idle", "paused"):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Agent cannot be woken from status '{agent.status}'",
        )
    update_stmt = (
        update(Agent)
        .where(Agent.id == agent_id, Agent.company_id == company_id)
        .values(status="ready", updated_at=datetime.now(timezone.utc))
    )
    await db.execute(update_stmt)
    result = await db.execute(select(Agent).where(Agent.id == agent_id, Agent.company_id == company_id))
    agent = result.scalar_one()

    # Audit: agent woken
    from nexus.governance.audit_service import record_audit
    await record_audit(
        company_id, "agent.woken",
        actor_type="user", resource_type="agent", resource_id=str(agent_id),
        details={"name": agent.name, "new_status": "ready"},
        db=db,
    )

    return agent


@router.post("/api/v1/agents/{agent_id}/pause", response_model=AgentResponse)
async def pause_agent(agent_id: uuid.UUID, db: DbSession, company_id: CurrentCompanyId) -> Any:
    """Pause an agent."""
    stmt = select(Agent).where(Agent.id == agent_id, Agent.company_id == company_id)
    result = await db.execute(stmt)
    agent = result.scalar_one_or_none()
    if agent is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Agent {agent_id} not found",
        )
    if agent.status == "terminated":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Cannot pause a terminated agent",
        )
    update_stmt = (
        update(Agent)
        .where(Agent.id == agent_id, Agent.company_id == company_id)
        .values(
            status="paused",
            paused_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
    )
    await db.execute(update_stmt)
    result = await db.execute(select(Agent).where(Agent.id == agent_id, Agent.company_id == company_id))
    return result.scalar_one()


@router.post("/api/v1/agents/{agent_id}/heartbeat")
async def agent_heartbeat(agent_id: uuid.UUID, db: DbSession, company_id: CurrentCompanyId) -> dict[str, Any]:
    """Record a heartbeat from an agent."""
    now = datetime.now(timezone.utc)
    stmt = (
        update(Agent)
        .where(Agent.id == agent_id, Agent.company_id == company_id)
        .values(last_heartbeat_at=now)
    )
    result = await db.execute(stmt)
    if result.rowcount == 0:  # type: ignore[union-attr]
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Agent {agent_id} not found",
        )
    return {"agent_id": str(agent_id), "heartbeat_at": now.isoformat()}



@router.delete("/api/v1/agents/{agent_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_agent(agent_id: uuid.UUID, db: DbSession, company_id: CurrentCompanyId) -> None:
    """Delete an agent permanently. Nullifies all foreign key references first."""
    from sqlalchemy import delete as sa_delete, update as sa_update
    from nexus.models.task import Task, Goal

    # Nullify references from other tables
    await db.execute(sa_update(Agent).where(Agent.manager_id == agent_id).values(manager_id=None))
    await db.execute(sa_update(Task).where(Task.assigned_agent_id == agent_id).values(assigned_agent_id=None))
    await db.execute(sa_update(Goal).where(Goal.owner_agent_id == agent_id).values(owner_agent_id=None))

    # Delete the agent
    stmt = sa_delete(Agent).where(Agent.id == agent_id, Agent.company_id == company_id)
    result = await db.execute(stmt)
    if result.rowcount == 0:  # type: ignore[union-attr]
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Agent {agent_id} not found",
        )


@router.post("/api/v1/agents/{agent_id}/clone", status_code=status.HTTP_201_CREATED, response_model=AgentResponse)
async def clone_agent(agent_id: uuid.UUID, db: DbSession, company_id: CurrentCompanyId) -> Any:
    """Clone an agent — creates a copy with all config, soul, and capabilities.

    The new agent gets a "-clone" suffix on its name and starts in "idle" status.
    """
    stmt = select(Agent).where(Agent.id == agent_id, Agent.company_id == company_id)
    result = await db.execute(stmt)
    source = result.scalar_one_or_none()
    if source is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Agent {agent_id} not found")

    clone = Agent(
        company_id=company_id,
        name=f"{source.name}-clone",
        role=source.role,
        title=source.title,
        department_id=source.department_id,
        team_id=source.team_id,
        adapter_type=source.adapter_type,
        adapter_config=source.adapter_config,
        model=source.model,
        capabilities=list(source.capabilities) if source.capabilities else None,
        responsibilities=source.responsibilities,
        objectives=source.objectives,
        soul_description=source.soul_description,
        budget_monthly_cents=source.budget_monthly_cents,
    )
    db.add(clone)
    await db.flush()
    return clone


class DelegateTaskRequest(BaseModel):
    """Request body for delegating a task to another agent."""

    target_agent_id: uuid.UUID
    title: str
    description: str | None = None
    priority: int = 1


@router.post("/api/v1/agents/{agent_id}/delegate", status_code=status.HTTP_201_CREATED)
async def delegate_task(
    agent_id: uuid.UUID, body: DelegateTaskRequest, db: DbSession, company_id: CurrentCompanyId
) -> dict[str, Any]:
    """Delegate a task from one agent to another.

    Creates a task assigned to the target agent and sends a notification
    via the communication inbox. The source agent is recorded as the requestor.
    """
    from nexus.models.task import Task
    from nexus.models.communication import Message

    # Verify both agents exist
    source = await db.execute(select(Agent).where(Agent.id == agent_id, Agent.company_id == company_id))
    source_agent = source.scalar_one_or_none()
    if not source_agent:
        raise HTTPException(status_code=404, detail="Source agent not found")

    target = await db.execute(select(Agent).where(Agent.id == body.target_agent_id, Agent.company_id == company_id))
    target_agent = target.scalar_one_or_none()
    if not target_agent:
        raise HTTPException(status_code=404, detail="Target agent not found")

    # Create the delegated task
    task = Task(
        company_id=company_id,
        title=body.title,
        description=body.description or f"Delegated from {source_agent.name}",
        priority=body.priority,
        assigned_agent_id=body.target_agent_id,
        status="pending",
    )
    db.add(task)
    await db.flush()

    # Send delegation message to target agent's inbox
    msg = Message(
        company_id=company_id,
        sender_agent_id=agent_id,
        recipient_agent_id=body.target_agent_id,
        message_type="delegation",
        content=f"Task delegated: {body.title}",
        priority="normal",
        delivery_route="direct",
    )
    db.add(msg)
    await db.flush()

    return {
        "task_id": str(task.id),
        "delegated_by": str(agent_id),
        "delegated_to": str(body.target_agent_id),
        "title": body.title,
        "status": "pending",
    }
