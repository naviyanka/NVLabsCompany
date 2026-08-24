"""Skill API endpoints - skill registry and agent-skill assignments."""

import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select

from nexus.api.deps import CurrentCompanyId, DbSession
from nexus.models.skill import AgentSkill, Skill

router = APIRouter(tags=["skills"])


class SkillCreate(BaseModel):
    """Request body for registering a skill."""

    name: str
    description: str | None = None
    category: str | None = None
    version: str = "1.0.0"
    schema_def: dict[str, Any] | None = None


class AgentSkillAssign(BaseModel):
    """Request body for assigning a skill to an agent."""

    skill_id: uuid.UUID
    proficiency: float = 0.5


class SkillResponse(BaseModel):
    """Response model for a skill."""

    id: uuid.UUID
    company_id: uuid.UUID
    name: str
    description: str | None = None
    category: str | None = None
    version: str
    schema_def: dict[str, Any] | None = None
    created_at: datetime


class AgentSkillResponse(BaseModel):
    """Response model for an agent-skill assignment."""

    id: uuid.UUID
    agent_id: uuid.UUID
    skill_id: uuid.UUID
    proficiency: float
    acquired_at: datetime


@router.post(
    "/api/v1/companies/{company_id}/skills",
    status_code=status.HTTP_201_CREATED,
    response_model=SkillResponse,
)
async def create_skill(
    company_id: uuid.UUID, body: SkillCreate, db: DbSession
) -> Any:
    """Register a new skill in the company."""
    skill = Skill(
        company_id=company_id,
        name=body.name,
        description=body.description,
        category=body.category,
        version=body.version,
        schema_def=body.schema_def,
    )
    db.add(skill)
    await db.flush()
    return skill


@router.get(
    "/api/v1/companies/{company_id}/skills",
    response_model=list[SkillResponse],
)
async def list_skills(
    company_id: uuid.UUID,
    db: DbSession,
    category: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> Any:
    """List skills for a company."""
    stmt = select(Skill).where(Skill.company_id == company_id)
    if category:
        stmt = stmt.where(Skill.category == category)
    stmt = stmt.offset(offset).limit(limit).order_by(Skill.name)
    result = await db.execute(stmt)
    return list(result.scalars().all())


@router.post(
    "/api/v1/agents/{agent_id}/skills",
    status_code=status.HTTP_201_CREATED,
    response_model=AgentSkillResponse,
)
async def assign_skill_to_agent(
    agent_id: uuid.UUID, body: AgentSkillAssign, db: DbSession, company_id: CurrentCompanyId
) -> Any:
    """Assign a skill to an agent."""
    # Verify agent belongs to company
    from nexus.models.agent import Agent

    agent_stmt = select(Agent).where(Agent.id == agent_id, Agent.company_id == company_id)
    agent_result = await db.execute(agent_stmt)
    agent = agent_result.scalar_one_or_none()
    if agent is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Agent {agent_id} not found",
        )

    agent_skill = AgentSkill(
        agent_id=agent_id,
        skill_id=body.skill_id,
        proficiency=body.proficiency,
    )
    db.add(agent_skill)
    await db.flush()
    return agent_skill



class SkillUpdate(BaseModel):
    """Request body for updating a skill."""

    name: str | None = None
    description: str | None = None
    category: str | None = None
    version: str | None = None
    schema_def: dict[str, Any] | None = None



@router.get("/api/v1/skills/{skill_id}", response_model=SkillResponse)
async def get_skill(skill_id: uuid.UUID, db: DbSession, company_id: CurrentCompanyId) -> Any:
    """Get a skill by ID."""
    stmt = select(Skill).where(Skill.id == skill_id, Skill.company_id == company_id)
    result = await db.execute(stmt)
    skill = result.scalar_one_or_none()
    if not skill:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Skill not found")
    return skill


@router.patch("/api/v1/skills/{skill_id}", response_model=SkillResponse)
async def update_skill(skill_id: uuid.UUID, body: SkillCreate, db: DbSession, company_id: CurrentCompanyId) -> Any:
    """Update a skill."""
    stmt = select(Skill).where(Skill.id == skill_id, Skill.company_id == company_id)
    result = await db.execute(stmt)
    skill = result.scalar_one_or_none()
    if not skill:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Skill not found")
    updates = body.model_dump(exclude_unset=True)
    for k, v in updates.items():
        setattr(skill, k, v)
    await db.flush()
    return skill


@router.delete("/api/v1/skills/{skill_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_skill(skill_id: uuid.UUID, db: DbSession, company_id: CurrentCompanyId) -> None:
    """Delete a skill."""
    from sqlalchemy import delete as sa_delete
    stmt = sa_delete(Skill).where(Skill.id == skill_id, Skill.company_id == company_id)
    await db.execute(stmt)
