"""HR persistence models - training curricula and performance reviews."""

import uuid
from datetime import timezone, datetime
from typing import Optional

from sqlmodel import Field, SQLModel


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class TrainingCurriculum(SQLModel, table=True):
    """A synthetic-benchmark fine-tuning track assigned to an agent."""

    __tablename__ = "hr_training_curricula"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    company_id: uuid.UUID = Field(foreign_key="companies.id", index=True)
    target_agent_id: uuid.UUID = Field(foreign_key="agents.id", index=True)
    title: str = Field(max_length=300)
    category: str = Field(default="", max_length=100)
    # in_training | graduated | scheduled
    status: str = Field(default="scheduled", max_length=50)
    progress: int = Field(default=0)  # 0-100
    benchmark_lift: str = Field(default="", max_length=200)
    created_at: datetime = Field(default_factory=_utcnow)
    updated_at: datetime = Field(default_factory=_utcnow)


class PerformanceReview(SQLModel, table=True):
    """An operator-recorded performance note about an agent.

    Covers kudos, constraints, and appraisal feedback that previously lived
    only in dashboard local state.
    """

    __tablename__ = "hr_performance_reviews"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    company_id: uuid.UUID = Field(foreign_key="companies.id", index=True)
    agent_id: uuid.UUID = Field(foreign_key="agents.id", index=True)
    # kudos | constraint | appraisal
    review_type: str = Field(max_length=50)
    feedback: str = Field(default="", max_length=4000)
    author: str = Field(default="operator", max_length=120)
    created_at: datetime = Field(default_factory=_utcnow, index=True)
