"""Company simulation API endpoints - org chart, delegation, performance, hiring."""

import uuid
from datetime import datetime
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select

from nexus.api.deps import DbSession
from nexus.models.agent import Agent
from nexus.models.company import Department, Team

router = APIRouter(tags=["company"])


# ---------------------------------------------------------------------------
# Request / Response Models
# ---------------------------------------------------------------------------


class OrgNodeResponse(BaseModel):
    """A node in the organizational chart."""

    agent_id: uuid.UUID
    name: str
    title: Optional[str] = None
    role: str
    department_id: Optional[uuid.UUID] = None
    team_id: Optional[uuid.UUID] = None
    manager_id: Optional[uuid.UUID] = None
    status: str


class ReportingChainResponse(BaseModel):
    """The reporting chain for an agent."""

    agent_id: uuid.UUID
    chain: list[OrgNodeResponse]


class DelegateTaskRequest(BaseModel):
    """Request body for delegating a task."""

    task_id: uuid.UUID
    from_agent_id: uuid.UUID
    to_agent_id: uuid.UUID
    reason: Optional[str] = None


class DelegationResponse(BaseModel):
    """Response model for a delegation."""

    id: uuid.UUID
    task_id: uuid.UUID
    from_agent_id: uuid.UUID
    to_agent_id: uuid.UUID
    reason: Optional[str] = None
    created_at: datetime


class PerformanceOverview(BaseModel):
    """Company performance overview."""

    company_id: uuid.UUID
    total_agents: int
    active_agents: int
    departments: int
    teams: int


class AgentPerformanceResponse(BaseModel):
    """Performance detail for a single agent."""

    agent_id: uuid.UUID
    name: str
    role: str
    status: str
    budget_monthly_cents: int
    spent_monthly_cents: int


class PeerReviewRequest(BaseModel):
    """Request body for submitting a peer review."""

    reviewer_agent_id: uuid.UUID
    rating: int
    feedback: Optional[str] = None


class PeerReviewResponse(BaseModel):
    """Response model for a peer review."""

    agent_id: uuid.UUID
    reviewer_agent_id: uuid.UUID
    rating: int
    feedback: Optional[str] = None
    created_at: datetime


class GenerateJDRequest(BaseModel):
    """Request body for generating a job description."""

    role: str
    department: Optional[str] = None
    responsibilities: list[str] = []
    skills: list[str] = []


class JobDescriptionResponse(BaseModel):
    """Response model for a generated job description."""

    role: str
    department: Optional[str] = None
    responsibilities: list[str]
    skills: list[str]
    description: str


class CreateAgentFromTemplateRequest(BaseModel):
    """Request body for hiring an agent from a template."""

    role_template: str


class OnboardingPlanResponse(BaseModel):
    """Response model for an onboarding plan."""

    agent_id: uuid.UUID
    steps: list[str]
    estimated_days: int


# ---------------------------------------------------------------------------
# Org Chart Routes
# ---------------------------------------------------------------------------


@router.get(
    "/api/v1/companies/{company_id}/org-chart",
    response_model=list[OrgNodeResponse],
)
async def get_org_chart(company_id: uuid.UUID, db: DbSession) -> Any:
    """Get organizational hierarchy for a company."""
    stmt = (
        select(Agent)
        .where(Agent.company_id == company_id)
        .order_by(Agent.name)
    )
    result = await db.execute(stmt)
    agents = list(result.scalars().all())
    return [
        OrgNodeResponse(
            agent_id=a.id,
            name=a.name,
            title=a.title,
            role=a.role,
            department_id=a.department_id,
            team_id=a.team_id,
            manager_id=a.manager_id,
            status=a.status,
        )
        for a in agents
    ]


@router.get(
    "/api/v1/companies/{company_id}/org-chart/reporting-chain/{agent_id}",
    response_model=ReportingChainResponse,
)
async def get_reporting_chain(
    company_id: uuid.UUID, agent_id: uuid.UUID, db: DbSession
) -> Any:
    """Get the reporting chain for an agent up to the top."""
    chain: list[OrgNodeResponse] = []
    current_id: Optional[uuid.UUID] = agent_id

    while current_id is not None:
        stmt = select(Agent).where(Agent.id == current_id, Agent.company_id == company_id)
        result = await db.execute(stmt)
        agent = result.scalar_one_or_none()
        if agent is None:
            break
        chain.append(
            OrgNodeResponse(
                agent_id=agent.id,
                name=agent.name,
                title=agent.title,
                role=agent.role,
                department_id=agent.department_id,
                team_id=agent.team_id,
                manager_id=agent.manager_id,
                status=agent.status,
            )
        )
        current_id = agent.manager_id

    return ReportingChainResponse(agent_id=agent_id, chain=chain)


# ---------------------------------------------------------------------------
# Delegation Routes
# ---------------------------------------------------------------------------


@router.post(
    "/api/v1/companies/{company_id}/delegations",
    status_code=status.HTTP_201_CREATED,
    response_model=DelegationResponse,
)
async def delegate_task(
    company_id: uuid.UUID, body: DelegateTaskRequest, db: DbSession
) -> Any:
    """Delegate a task from one agent to another."""
    from datetime import timezone

    delegation_id = uuid.uuid4()
    now = datetime.now(timezone.utc)
    return DelegationResponse(
        id=delegation_id,
        task_id=body.task_id,
        from_agent_id=body.from_agent_id,
        to_agent_id=body.to_agent_id,
        reason=body.reason,
        created_at=now,
    )


@router.get(
    "/api/v1/companies/{company_id}/delegations",
    response_model=list[DelegationResponse],
)
async def list_delegations(
    company_id: uuid.UUID, db: DbSession
) -> Any:
    """List delegations for a company.

    Note: Full delegation tracking would require a dedicated table.
    This endpoint returns an empty list as a placeholder.
    """
    return []


# ---------------------------------------------------------------------------
# Performance Routes
# ---------------------------------------------------------------------------


@router.get(
    "/api/v1/companies/{company_id}/performance",
    response_model=PerformanceOverview,
)
async def get_performance_overview(
    company_id: uuid.UUID, db: DbSession
) -> Any:
    """Get company performance overview."""
    agents_stmt = select(Agent).where(Agent.company_id == company_id)
    agents_result = await db.execute(agents_stmt)
    agents = list(agents_result.scalars().all())

    dept_stmt = select(Department).where(Department.company_id == company_id)
    dept_result = await db.execute(dept_stmt)
    departments = list(dept_result.scalars().all())

    team_stmt = select(Team).where(Team.company_id == company_id)
    team_result = await db.execute(team_stmt)
    teams = list(team_result.scalars().all())

    active_count = sum(1 for a in agents if a.status in ("ready", "busy"))

    return PerformanceOverview(
        company_id=company_id,
        total_agents=len(agents),
        active_agents=active_count,
        departments=len(departments),
        teams=len(teams),
    )


@router.get(
    "/api/v1/companies/{company_id}/performance/{agent_id}",
    response_model=AgentPerformanceResponse,
)
async def get_agent_performance(
    company_id: uuid.UUID, agent_id: uuid.UUID, db: DbSession
) -> Any:
    """Get performance detail for a specific agent."""
    stmt = select(Agent).where(Agent.id == agent_id, Agent.company_id == company_id)
    result = await db.execute(stmt)
    agent = result.scalar_one_or_none()
    if agent is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Agent {agent_id} not found in company {company_id}",
        )
    return AgentPerformanceResponse(
        agent_id=agent.id,
        name=agent.name,
        role=agent.role,
        status=agent.status,
        budget_monthly_cents=agent.budget_monthly_cents,
        spent_monthly_cents=agent.spent_monthly_cents,
    )


@router.post(
    "/api/v1/companies/{company_id}/performance/{agent_id}/review",
    status_code=status.HTTP_201_CREATED,
    response_model=PeerReviewResponse,
)
async def submit_peer_review(
    company_id: uuid.UUID,
    agent_id: uuid.UUID,
    body: PeerReviewRequest,
    db: DbSession,
) -> Any:
    """Submit a peer review for an agent."""
    from datetime import timezone

    # Verify agent exists
    stmt = select(Agent).where(Agent.id == agent_id, Agent.company_id == company_id)
    result = await db.execute(stmt)
    agent = result.scalar_one_or_none()
    if agent is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Agent {agent_id} not found in company {company_id}",
        )

    return PeerReviewResponse(
        agent_id=agent_id,
        reviewer_agent_id=body.reviewer_agent_id,
        rating=body.rating,
        feedback=body.feedback,
        created_at=datetime.now(timezone.utc),
    )


# ---------------------------------------------------------------------------
# Hiring Routes
# ---------------------------------------------------------------------------


@router.post(
    "/api/v1/companies/{company_id}/hiring/job-description",
    status_code=status.HTTP_201_CREATED,
    response_model=JobDescriptionResponse,
)
async def generate_job_description(
    company_id: uuid.UUID, body: GenerateJDRequest, db: DbSession
) -> Any:
    """Generate a job description for a new agent role."""
    description = (
        f"We are looking for a {body.role} agent"
        f"{' in the ' + body.department + ' department' if body.department else ''}. "
        f"Responsibilities include: {', '.join(body.responsibilities) if body.responsibilities else 'TBD'}. "
        f"Required skills: {', '.join(body.skills) if body.skills else 'TBD'}."
    )
    return JobDescriptionResponse(
        role=body.role,
        department=body.department,
        responsibilities=body.responsibilities,
        skills=body.skills,
        description=description,
    )


@router.post(
    "/api/v1/companies/{company_id}/hiring/create-agent",
    status_code=status.HTTP_201_CREATED,
)
async def create_agent_from_template(
    company_id: uuid.UUID, body: CreateAgentFromTemplateRequest, db: DbSession
) -> dict[str, Any]:
    """Hire a new agent from a role template."""
    agent = Agent(
        company_id=company_id,
        name=f"{body.role_template} Agent",
        role=body.role_template,
        status="idle",
    )
    db.add(agent)
    await db.flush()
    return {
        "agent_id": str(agent.id),
        "role_template": body.role_template,
        "status": "created",
    }


@router.get(
    "/api/v1/companies/{company_id}/hiring/{agent_id}/onboarding",
    response_model=OnboardingPlanResponse,
)
async def get_onboarding_plan(
    company_id: uuid.UUID, agent_id: uuid.UUID, db: DbSession
) -> Any:
    """Get onboarding plan for a newly hired agent."""
    stmt = select(Agent).where(Agent.id == agent_id, Agent.company_id == company_id)
    result = await db.execute(stmt)
    agent = result.scalar_one_or_none()
    if agent is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Agent {agent_id} not found in company {company_id}",
        )
    return OnboardingPlanResponse(
        agent_id=agent_id,
        steps=[
            "Configure runtime adapter",
            "Assign to department and team",
            "Set up communication channels",
            "Review company knowledge base",
            "Complete initial skill assessment",
        ],
        estimated_days=3,
    )
