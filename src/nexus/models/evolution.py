"""Evolution models for continuous improvement and self-optimization.

The evolution system enables agents to propose improvements, evaluate them
through A/B testing, and track versioned configurations. All promotions
require explicit approval gates - auto-promotion is never allowed.
"""

import uuid
from datetime import datetime
from typing import Any, Optional

from sqlalchemy import JSON
from sqlmodel import Column, Field, SQLModel


class EvolutionProposal(SQLModel, table=True):
    """A proposal for improving skills, workflows, agent config, or org structure.

    Proposals go through a lifecycle: proposed -> evaluating -> approved/rejected ->
    promoted/rolled_back. Promotion always requires an explicit approval gate and
    is never automated.
    """

    __tablename__ = "evolution_proposals"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    company_id: uuid.UUID = Field(foreign_key="companies.id", index=True)
    proposal_type: str = Field(max_length=50)  # skill_improvement/workflow_change/agent_config/org_change
    title: str = Field(max_length=500)
    description: Optional[str] = Field(default=None)
    expected_impact: Optional[str] = Field(default=None)
    confidence: Optional[float] = Field(default=None)
    risk_level: str = Field(default="low", max_length=20)  # low/medium/high
    estimated_cost_cents: int = Field(default=0)
    status: str = Field(default="proposed", max_length=50)  # proposed/evaluating/approved/rejected/promoted/rolled_back
    proposed_by_agent_id: Optional[uuid.UUID] = Field(
        default=None, foreign_key="agents.id", index=True
    )
    approved_by: Optional[str] = Field(default=None, max_length=255)
    approval_id: Optional[uuid.UUID] = Field(
        default=None, foreign_key="approvals.id"
    )
    created_at: datetime = Field(default_factory=lambda: datetime.utcnow())
    updated_at: Optional[datetime] = Field(default=None)


class EvolutionEvaluation(SQLModel, table=True):
    """An A/B evaluation result for an evolution proposal.

    Evaluations compare baseline vs candidate performance across multiple
    dimensions, computing statistical significance to determine whether
    the proposed change is a genuine improvement.
    """

    __tablename__ = "evolution_evaluations"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    proposal_id: uuid.UUID = Field(foreign_key="evolution_proposals.id", index=True)
    company_id: uuid.UUID = Field(foreign_key="companies.id", index=True)
    baseline_score: float
    candidate_score: float
    improvement_percent: float
    statistical_significance: float
    dimensions: Optional[dict[str, Any]] = Field(default=None, sa_column=Column(JSON))
    passed: bool = Field(default=False)
    evaluated_at: datetime = Field(default_factory=lambda: datetime.utcnow())


class SkillVersion(SQLModel, table=True):
    """A versioned snapshot of a skill's prompt template and performance.

    Tracks the evolution of skills over time, enabling rollback to previous
    versions if a new version underperforms.
    """

    __tablename__ = "skill_versions"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    company_id: uuid.UUID = Field(foreign_key="companies.id", index=True)
    skill_id: uuid.UUID = Field(foreign_key="skills.id", index=True)
    version_number: int = Field(default=1)
    prompt_template: str
    performance_score: Optional[float] = Field(default=None)
    is_active: bool = Field(default=False)
    created_at: datetime = Field(default_factory=lambda: datetime.utcnow())


class AgentVersion(SQLModel, table=True):
    """A versioned snapshot of an agent's configuration and performance.

    Tracks the evolution of agent configurations over time, enabling rollback
    to previous versions if a new configuration underperforms.
    """

    __tablename__ = "agent_versions"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    company_id: uuid.UUID = Field(foreign_key="companies.id", index=True)
    agent_id: uuid.UUID = Field(foreign_key="agents.id", index=True)
    version_number: int = Field(default=1)
    config_snapshot: Optional[dict[str, Any]] = Field(
        default=None, sa_column=Column(JSON)
    )
    performance_score: Optional[float] = Field(default=None)
    is_active: bool = Field(default=False)
    created_at: datetime = Field(default_factory=lambda: datetime.utcnow())
