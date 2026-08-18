"""Agent API endpoints - CRUD and lifecycle operations."""

import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select, update

from nexus.api.deps import DbSession
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


class AgentUpdate(BaseModel):
    """Request body for updating an agent."""

    name: str | None = None
    title: str | None = None
    role: str | None = None
    status: str | None = None
    model: str | None = None
    capabilities: list[str] | None = None
    responsibilities: str | None = None
    objectives: str | None = None
    budget_monthly_cents: int | None = None


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
    )
    db.add(agent)
    await db.flush()
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
async def get_agent(agent_id: uuid.UUID, db: DbSession) -> Any:
    """Get an agent by ID."""
    stmt = select(Agent).where(Agent.id == agent_id)
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
    agent_id: uuid.UUID, body: AgentUpdate, db: DbSession
) -> Any:
    """Update an agent."""
    updates = body.model_dump(exclude_unset=True)
    if not updates:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No fields to update",
        )
    updates["updated_at"] = datetime.now(timezone.utc)
    stmt = update(Agent).where(Agent.id == agent_id).values(**updates)
    await db.execute(stmt)

    result = await db.execute(select(Agent).where(Agent.id == agent_id))
    agent = result.scalar_one_or_none()
    if agent is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Agent {agent_id} not found",
        )
    return agent


@router.post("/api/v1/agents/{agent_id}/wake", response_model=AgentResponse)
async def wake_agent(agent_id: uuid.UUID, db: DbSession) -> Any:
    """Wake an agent (transition to ready state)."""
    stmt = select(Agent).where(Agent.id == agent_id)
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
        .where(Agent.id == agent_id)
        .values(status="ready", updated_at=datetime.now(timezone.utc))
    )
    await db.execute(update_stmt)
    result = await db.execute(select(Agent).where(Agent.id == agent_id))
    return result.scalar_one()


@router.post("/api/v1/agents/{agent_id}/pause", response_model=AgentResponse)
async def pause_agent(agent_id: uuid.UUID, db: DbSession) -> Any:
    """Pause an agent."""
    stmt = select(Agent).where(Agent.id == agent_id)
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
        .where(Agent.id == agent_id)
        .values(
            status="paused",
            paused_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
    )
    await db.execute(update_stmt)
    result = await db.execute(select(Agent).where(Agent.id == agent_id))
    return result.scalar_one()


@router.post("/api/v1/agents/{agent_id}/heartbeat")
async def agent_heartbeat(agent_id: uuid.UUID, db: DbSession) -> dict[str, Any]:
    """Record a heartbeat from an agent."""
    now = datetime.now(timezone.utc)
    stmt = (
        update(Agent)
        .where(Agent.id == agent_id)
        .values(last_heartbeat_at=now)
    )
    result = await db.execute(stmt)
    if result.rowcount == 0:  # type: ignore[union-attr]
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Agent {agent_id} not found",
        )
    return {"agent_id": str(agent_id), "heartbeat_at": now.isoformat()}
