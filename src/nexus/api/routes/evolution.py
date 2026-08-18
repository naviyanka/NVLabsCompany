"""Evolution API endpoints - proposals, evaluations, skill versioning."""

import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select

from nexus.api.deps import CurrentCompanyId, DbSession
from nexus.models.evolution import (
    EvolutionEvaluation,
    EvolutionProposal,
    SkillVersion,
)

router = APIRouter(tags=["evolution"])


# ---------------------------------------------------------------------------
# Request / Response Models
# ---------------------------------------------------------------------------


class CreateProposalRequest(BaseModel):
    """Request body for creating an evolution proposal."""

    proposal_type: str
    title: str
    description: Optional[str] = None
    expected_impact: Optional[str] = None
    confidence: Optional[float] = None
    risk_level: str = "low"
    estimated_cost_cents: int = 0


class ProposalResponse(BaseModel):
    """Response model for an evolution proposal."""

    id: uuid.UUID
    company_id: uuid.UUID
    proposal_type: str
    title: str
    description: Optional[str] = None
    expected_impact: Optional[str] = None
    confidence: Optional[float] = None
    risk_level: str
    estimated_cost_cents: int
    status: str
    proposed_by_agent_id: Optional[uuid.UUID] = None
    approved_by: Optional[str] = None
    approval_id: Optional[uuid.UUID] = None
    created_at: datetime
    updated_at: Optional[datetime] = None


class EvaluationResponse(BaseModel):
    """Response model for an evaluation result."""

    id: uuid.UUID
    proposal_id: uuid.UUID
    company_id: uuid.UUID
    baseline_score: float
    candidate_score: float
    improvement_percent: float
    statistical_significance: float
    dimensions: Optional[dict[str, Any]] = None
    passed: bool
    evaluated_at: datetime


class PromoteRequest(BaseModel):
    """Request body for promoting a proposal (requires approval_id)."""

    approval_id: uuid.UUID


class RollbackRequest(BaseModel):
    """Request body for rolling back a proposal."""

    reason: Optional[str] = None


class PatternResponse(BaseModel):
    """Response model for a detected pattern."""

    pattern_type: str
    description: str
    confidence: float
    detected_at: datetime


class ChangeHistoryEntry(BaseModel):
    """A change history entry."""

    proposal_id: uuid.UUID
    title: str
    proposal_type: str
    status: str
    created_at: datetime
    updated_at: Optional[datetime] = None


class SkillVersionResponse(BaseModel):
    """Response model for a skill version."""

    id: uuid.UUID
    company_id: uuid.UUID
    skill_id: uuid.UUID
    version_number: int
    prompt_template: str
    performance_score: Optional[float] = None
    is_active: bool
    created_at: datetime


class CreateSkillVersionRequest(BaseModel):
    """Request body for creating a new skill version."""

    prompt_template: str
    performance_score: Optional[float] = None


# ---------------------------------------------------------------------------
# Pattern Routes
# ---------------------------------------------------------------------------


@router.get(
    "/api/v1/companies/{company_id}/evolution/patterns",
    response_model=list[PatternResponse],
)
async def get_detected_patterns(
    company_id: uuid.UUID, db: DbSession
) -> Any:
    """Get detected patterns for a company.

    In production, patterns would be detected by analyzing agent behavior,
    performance metrics, and recurring failures. Returns empty list as placeholder.
    """
    return []


# ---------------------------------------------------------------------------
# Proposal Routes
# ---------------------------------------------------------------------------


@router.post(
    "/api/v1/companies/{company_id}/evolution/proposals",
    status_code=status.HTTP_201_CREATED,
    response_model=ProposalResponse,
)
async def create_proposal(
    company_id: uuid.UUID, body: CreateProposalRequest, db: DbSession
) -> Any:
    """Create a new evolution proposal."""
    proposal = EvolutionProposal(
        company_id=company_id,
        proposal_type=body.proposal_type,
        title=body.title,
        description=body.description,
        expected_impact=body.expected_impact,
        confidence=body.confidence,
        risk_level=body.risk_level,
        estimated_cost_cents=body.estimated_cost_cents,
    )
    db.add(proposal)
    await db.flush()
    return proposal


@router.get(
    "/api/v1/companies/{company_id}/evolution/proposals",
    response_model=list[ProposalResponse],
)
async def list_proposals(
    company_id: uuid.UUID,
    db: DbSession,
    status_filter: Optional[str] = None,
    limit: int = 100,
    offset: int = 0,
) -> Any:
    """List evolution proposals for a company."""
    stmt = select(EvolutionProposal).where(EvolutionProposal.company_id == company_id)
    if status_filter:
        stmt = stmt.where(EvolutionProposal.status == status_filter)
    stmt = stmt.offset(offset).limit(limit).order_by(EvolutionProposal.created_at.desc())
    result = await db.execute(stmt)
    return list(result.scalars().all())


@router.get(
    "/api/v1/evolution/proposals/{proposal_id}",
    response_model=ProposalResponse,
)
async def get_proposal(proposal_id: uuid.UUID, db: DbSession, company_id: CurrentCompanyId) -> Any:
    """Get an evolution proposal by ID."""
    stmt = select(EvolutionProposal).where(EvolutionProposal.id == proposal_id, EvolutionProposal.company_id == company_id)
    result = await db.execute(stmt)
    proposal = result.scalar_one_or_none()
    if proposal is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Proposal {proposal_id} not found",
        )
    return proposal


@router.post(
    "/api/v1/evolution/proposals/{proposal_id}/evaluate",
    response_model=EvaluationResponse,
)
async def evaluate_proposal(proposal_id: uuid.UUID, db: DbSession, company_id: CurrentCompanyId) -> Any:
    """Trigger evaluation for a proposal."""
    stmt = select(EvolutionProposal).where(EvolutionProposal.id == proposal_id, EvolutionProposal.company_id == company_id)
    result = await db.execute(stmt)
    proposal = result.scalar_one_or_none()
    if proposal is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Proposal {proposal_id} not found",
        )

    # Update proposal status
    proposal.status = "evaluating"
    proposal.updated_at = datetime.now(timezone.utc)

    # Create evaluation record (placeholder scores)
    evaluation = EvolutionEvaluation(
        proposal_id=proposal_id,
        company_id=proposal.company_id,
        baseline_score=0.0,
        candidate_score=0.0,
        improvement_percent=0.0,
        statistical_significance=0.0,
        passed=False,
    )
    db.add(evaluation)
    await db.flush()
    return evaluation


@router.post(
    "/api/v1/evolution/proposals/{proposal_id}/promote",
    response_model=ProposalResponse,
)
async def promote_proposal(
    proposal_id: uuid.UUID, body: PromoteRequest, db: DbSession, company_id: CurrentCompanyId
) -> Any:
    """Promote a proposal (requires explicit approval_id).

    Promotion NEVER happens automatically - an approval gate is always required.
    The proposal must be in an appropriate lifecycle state (approved or evaluating).
    """
    stmt = select(EvolutionProposal).where(EvolutionProposal.id == proposal_id, EvolutionProposal.company_id == company_id)
    result = await db.execute(stmt)
    proposal = result.scalar_one_or_none()
    if proposal is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Proposal {proposal_id} not found",
        )

    # Pre-condition: only proposals in an appropriate state can be promoted.
    # Rejected, rolled_back, or already promoted proposals cannot be promoted.
    promotable_states = {"proposed", "evaluating", "approved"}
    if proposal.status not in promotable_states:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"Proposal cannot be promoted from status '{proposal.status}'. "
                f"Must be in one of: {sorted(promotable_states)}"
            ),
        )

    # Require approval_id for promotion gate
    proposal.status = "promoted"
    proposal.approval_id = body.approval_id
    proposal.updated_at = datetime.now(timezone.utc)
    await db.flush()
    return proposal


@router.post(
    "/api/v1/evolution/proposals/{proposal_id}/rollback",
    response_model=ProposalResponse,
)
async def rollback_proposal(
    proposal_id: uuid.UUID, body: RollbackRequest, db: DbSession, company_id: CurrentCompanyId
) -> Any:
    """Rollback a promoted proposal."""
    stmt = select(EvolutionProposal).where(EvolutionProposal.id == proposal_id, EvolutionProposal.company_id == company_id)
    result = await db.execute(stmt)
    proposal = result.scalar_one_or_none()
    if proposal is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Proposal {proposal_id} not found",
        )

    proposal.status = "rolled_back"
    proposal.updated_at = datetime.now(timezone.utc)
    await db.flush()
    return proposal


# ---------------------------------------------------------------------------
# History Routes
# ---------------------------------------------------------------------------


@router.get(
    "/api/v1/companies/{company_id}/evolution/history",
    response_model=list[ChangeHistoryEntry],
)
async def get_change_history(
    company_id: uuid.UUID,
    db: DbSession,
    limit: int = 100,
    offset: int = 0,
) -> Any:
    """Get evolution change history for a company."""
    stmt = (
        select(EvolutionProposal)
        .where(EvolutionProposal.company_id == company_id)
        .where(EvolutionProposal.status.in_(["promoted", "rolled_back"]))
        .offset(offset)
        .limit(limit)
        .order_by(EvolutionProposal.updated_at.desc())
    )
    result = await db.execute(stmt)
    proposals = list(result.scalars().all())
    return [
        ChangeHistoryEntry(
            proposal_id=p.id,
            title=p.title,
            proposal_type=p.proposal_type,
            status=p.status,
            created_at=p.created_at,
            updated_at=p.updated_at,
        )
        for p in proposals
    ]


# ---------------------------------------------------------------------------
# Skill Version Routes
# ---------------------------------------------------------------------------


@router.get(
    "/api/v1/companies/{company_id}/evolution/skills/{skill_id}/versions",
    response_model=list[SkillVersionResponse],
)
async def get_skill_versions(
    company_id: uuid.UUID, skill_id: uuid.UUID, db: DbSession
) -> Any:
    """Get version history for a skill."""
    stmt = (
        select(SkillVersion)
        .where(SkillVersion.company_id == company_id, SkillVersion.skill_id == skill_id)
        .order_by(SkillVersion.version_number.desc())
    )
    result = await db.execute(stmt)
    return list(result.scalars().all())


@router.post(
    "/api/v1/companies/{company_id}/evolution/skills/{skill_id}/versions",
    status_code=status.HTTP_201_CREATED,
    response_model=SkillVersionResponse,
)
async def create_skill_version(
    company_id: uuid.UUID,
    skill_id: uuid.UUID,
    body: CreateSkillVersionRequest,
    db: DbSession,
) -> Any:
    """Create a new version for a skill."""
    # Determine next version number
    stmt = (
        select(SkillVersion)
        .where(SkillVersion.company_id == company_id, SkillVersion.skill_id == skill_id)
        .order_by(SkillVersion.version_number.desc())
        .limit(1)
    )
    result = await db.execute(stmt)
    latest = result.scalar_one_or_none()
    next_version = (latest.version_number + 1) if latest else 1

    version = SkillVersion(
        company_id=company_id,
        skill_id=skill_id,
        version_number=next_version,
        prompt_template=body.prompt_template,
        performance_score=body.performance_score,
    )
    db.add(version)
    await db.flush()
    return version
