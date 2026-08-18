"""Skill API endpoints - skill registry and agent-skill assignments."""

import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select

from nexus.api.deps import DbSession
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
    agent_id: uuid.UUID, body: AgentSkillAssign, db: DbSession
) -> Any:
    """Assign a skill to an agent."""
    agent_skill = AgentSkill(
        agent_id=agent_id,
        skill_id=body.skill_id,
        proficiency=body.proficiency,
    )
    db.add(agent_skill)
    await db.flush()
    return agent_skill
