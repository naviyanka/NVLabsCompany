"""HR Room endpoints — performance summary, training, enhancements, evaluations."""

import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sqlalchemy import select, func

from nexus.api.deps import CurrentCompanyId, DbSession
from nexus.models.agent import Agent
from nexus.models.evolution import EvolutionEvaluation

router = APIRouter(tags=["hr"])


@router.get("/api/v1/companies/{company_id}/agents/performance-summary")
async def performance_summary(company_id: uuid.UUID, db: DbSession) -> list[dict[str, Any]]:
    """All agents with performance data, sorted by score."""
    stmt = select(Agent).where(Agent.company_id == company_id).order_by(Agent.performance_score.desc().nulls_last())
    result = await db.execute(stmt)
    return [{"id": str(a.id), "name": a.name, "role": a.role, "title": a.title, "status": a.status, "model": a.model, "performance_score": a.performance_score, "budget_monthly_cents": a.budget_monthly_cents, "spent_monthly_cents": a.spent_monthly_cents, "capabilities": a.capabilities} for a in result.scalars().all()]


class TrainRequest(BaseModel):
    skill: str
    duration_minutes: int = 30


@router.post("/api/v1/agents/{agent_id}/train")
async def train_agent(agent_id: uuid.UUID, body: TrainRequest, db: DbSession, company_id: CurrentCompanyId) -> dict[str, Any]:
    """Start a training session for an agent."""
    stmt = select(Agent).where(Agent.id == agent_id, Agent.company_id == company_id)
    result = await db.execute(stmt)
    agent = result.scalar_one_or_none()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    return {"agent_id": str(agent_id), "agent_name": agent.name, "training_started": True, "skill": body.skill, "duration_minutes": body.duration_minutes, "estimated_completion": (datetime.utcnow()).isoformat()}


class EnhanceRequest(BaseModel):
    capabilities: list[str]


@router.post("/api/v1/agents/{agent_id}/enhance")
async def enhance_agent(agent_id: uuid.UUID, body: EnhanceRequest, db: DbSession, company_id: CurrentCompanyId) -> dict[str, Any]:
    """Add capabilities to an agent."""
    stmt = select(Agent).where(Agent.id == agent_id, Agent.company_id == company_id)
    result = await db.execute(stmt)
    agent = result.scalar_one_or_none()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    existing = agent.capabilities or []
    new_caps = list(set(existing + body.capabilities))
    agent.capabilities = new_caps
    await db.flush()
    return {"agent_id": str(agent_id), "capabilities": new_caps, "added": body.capabilities}


@router.get("/api/v1/companies/{company_id}/training-queue")
async def training_queue(company_id: uuid.UUID, db: DbSession) -> list[dict[str, Any]]:
    """Agents currently in training/configuring state."""
    stmt = select(Agent).where(Agent.company_id == company_id, Agent.status == "configuring")
    result = await db.execute(stmt)
    return [{"id": str(a.id), "name": a.name, "role": a.role, "status": a.status} for a in result.scalars().all()]


@router.get("/api/v1/companies/{company_id}/evaluations")
async def list_evaluations(company_id: uuid.UUID, db: DbSession, limit: int = 20) -> list[dict[str, Any]]:
    """Recent evolution evaluations."""
    stmt = select(EvolutionEvaluation).where(EvolutionEvaluation.company_id == company_id).order_by(EvolutionEvaluation.evaluated_at.desc()).limit(limit)
    result = await db.execute(stmt)
    return [{"id": str(e.id), "proposal_id": str(e.proposal_id), "baseline_score": e.baseline_score, "candidate_score": e.candidate_score, "improvement_percent": e.improvement_percent, "passed": e.passed, "evaluated_at": e.evaluated_at.isoformat()} for e in result.scalars().all()]
