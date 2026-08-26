"""HR Room endpoints — performance summary, training, enhancements, evaluations."""

import uuid
from datetime import timezone, datetime
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
    return {"agent_id": str(agent_id), "agent_name": agent.name, "training_started": True, "skill": body.skill, "duration_minutes": body.duration_minutes, "estimated_completion": (datetime.now(timezone.utc)).isoformat()}


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


# ---------------------------------------------------------------------------
# Training curricula + performance reviews (persisted HR data)
# ---------------------------------------------------------------------------

from fastapi import status as _status  # noqa: E402

from nexus.models.hr import PerformanceReview, TrainingCurriculum  # noqa: E402


def _hr_now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class CurriculumCreate(BaseModel):
    target_agent_id: uuid.UUID
    title: str
    category: str = ""
    status: str = "scheduled"
    progress: int = 0
    benchmark_lift: str = ""


class CurriculumUpdate(BaseModel):
    status: str | None = None
    progress: int | None = None
    benchmark_lift: str | None = None


class ReviewCreate(BaseModel):
    agent_id: uuid.UUID
    review_type: str
    feedback: str = ""
    author: str = "operator"


_VALID_CURRICULUM_STATUSES = ("in_training", "graduated", "scheduled")
_VALID_REVIEW_TYPES = ("kudos", "constraint", "appraisal")


@router.get("/api/v1/companies/{company_id}/hr/curricula")
async def list_curricula(company_id: uuid.UUID, db: DbSession) -> list[dict[str, Any]]:
    """List training curricula for a company."""
    stmt = (
        select(TrainingCurriculum)
        .where(TrainingCurriculum.company_id == company_id)
        .order_by(TrainingCurriculum.created_at.desc())
        .limit(200)
    )
    result = await db.execute(stmt)
    return [
        {
            "id": str(c.id),
            "target_agent_id": str(c.target_agent_id),
            "title": c.title,
            "category": c.category,
            "status": c.status,
            "progress": c.progress,
            "benchmark_lift": c.benchmark_lift,
            "created_at": c.created_at.isoformat(),
            "updated_at": c.updated_at.isoformat(),
        }
        for c in result.scalars().all()
    ]


@router.post(
    "/api/v1/companies/{company_id}/hr/curricula",
    status_code=201,
)
async def create_curriculum(company_id: uuid.UUID, body: CurriculumCreate, db: DbSession) -> dict[str, Any]:
    """Enroll an agent in a training curriculum."""
    if not 0 <= body.progress <= 100:
        raise HTTPException(status_code=_status.HTTP_422_UNPROCESSABLE_ENTITY, detail="progress must be 0-100")
    if body.status not in _VALID_CURRICULUM_STATUSES:
        raise HTTPException(status_code=_status.HTTP_422_UNPROCESSABLE_ENTITY, detail="invalid status")
    item = TrainingCurriculum(
        company_id=company_id,
        target_agent_id=body.target_agent_id,
        title=body.title[:300],
        category=body.category[:100],
        status=body.status,
        progress=body.progress,
        benchmark_lift=body.benchmark_lift[:200],
    )
    db.add(item)
    await db.flush()
    return {
        "id": str(item.id),
        "target_agent_id": str(item.target_agent_id),
        "title": item.title,
        "category": item.category,
        "status": item.status,
        "progress": item.progress,
        "benchmark_lift": item.benchmark_lift,
    }


@router.patch("/api/v1/hr/curricula/{curriculum_id}")
async def update_curriculum(
    curriculum_id: uuid.UUID,
    body: CurriculumUpdate,
    db: DbSession,
    company_id: CurrentCompanyId,
) -> dict[str, Any]:
    """Update progress/status of a curriculum (tenant-scoped)."""
    stmt = select(TrainingCurriculum).where(
        TrainingCurriculum.id == curriculum_id,
        TrainingCurriculum.company_id == company_id,
    )
    result = await db.execute(stmt)
    item = result.scalar_one_or_none()
    if item is None:
        raise HTTPException(status_code=404, detail="Curriculum not found")

    updates = body.model_dump(exclude_unset=True)
    if "progress" in updates and not 0 <= updates["progress"] <= 100:
        raise HTTPException(status_code=_status.HTTP_422_UNPROCESSABLE_ENTITY, detail="progress must be 0-100")
    if "status" in updates and updates["status"] not in _VALID_CURRICULUM_STATUSES:
        raise HTTPException(status_code=_status.HTTP_422_UNPROCESSABLE_ENTITY, detail="invalid status")
    for key, value in updates.items():
        setattr(item, key, value)
    item.updated_at = _hr_now()
    await db.flush()
    return {"id": str(item.id), "status": item.status, "progress": item.progress}


@router.get("/api/v1/companies/{company_id}/hr/reviews")
async def list_hr_reviews(
    company_id: uuid.UUID,
    db: DbSession,
    agent_id: uuid.UUID | None = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    """List performance reviews (kudos/constraint/appraisal), newest first."""
    conditions = [PerformanceReview.company_id == company_id]
    if agent_id is not None:
        conditions.append(PerformanceReview.agent_id == agent_id)
    stmt = (
        select(PerformanceReview)
        .where(*conditions)
        .order_by(PerformanceReview.created_at.desc())
        .limit(limit)
    )
    result = await db.execute(stmt)
    return [
        {
            "id": str(r.id),
            "agent_id": str(r.agent_id),
            "review_type": r.review_type,
            "feedback": r.feedback,
            "author": r.author,
            "created_at": r.created_at.isoformat(),
        }
        for r in result.scalars().all()
    ]


@router.post("/api/v1/companies/{company_id}/hr/reviews", status_code=201)
async def create_hr_review(company_id: uuid.UUID, body: ReviewCreate, db: DbSession) -> dict[str, Any]:
    """Record a kudos, constraint, or appraisal note for an agent."""
    if body.review_type not in _VALID_REVIEW_TYPES:
        raise HTTPException(status_code=_status.HTTP_422_UNPROCESSABLE_ENTITY, detail="invalid review_type")
    review = PerformanceReview(
        company_id=company_id,
        agent_id=body.agent_id,
        review_type=body.review_type,
        feedback=body.feedback[:4000],
        author=(body.author or "operator")[:120],
    )
    db.add(review)
    await db.flush()
    return {
        "id": str(review.id),
        "agent_id": str(review.agent_id),
        "review_type": review.review_type,
        "feedback": review.feedback,
        "author": review.author,
        "created_at": review.created_at.isoformat(),
    }
