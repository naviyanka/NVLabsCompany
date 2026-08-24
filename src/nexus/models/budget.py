"""Budget policies and cost tracking models."""

import uuid
from datetime import timezone, datetime
from typing import Optional

from sqlmodel import Field, SQLModel


class BudgetPolicy(SQLModel, table=True):
    """Defines budget limits for a scope (company, department, agent, project)."""

    __tablename__ = "budget_policies"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    company_id: uuid.UUID = Field(foreign_key="companies.id", index=True)
    scope_type: str = Field(max_length=50)  # company, department, agent, project
    scope_id: uuid.UUID = Field(index=True)
    metric: str = Field(max_length=100)  # cost_cents, tokens, api_calls
    window_kind: str = Field(max_length=50)  # monthly, weekly, daily, per_execution
    amount: int = Field(default=0)
    warn_percent: int = Field(default=80)
    hard_stop_enabled: bool = Field(default=True)
    is_active: bool = Field(default=True)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc).replace(tzinfo=None))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc).replace(tzinfo=None))


class CostEvent(SQLModel, table=True):
    """Records an individual cost event (LLM call, tool usage, etc.)."""

    __tablename__ = "cost_events"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    company_id: uuid.UUID = Field(foreign_key="companies.id", index=True)
    agent_id: Optional[uuid.UUID] = Field(
        default=None, foreign_key="agents.id", index=True
    )
    task_id: Optional[uuid.UUID] = Field(
        default=None, foreign_key="tasks.id"
    )
    project_id: Optional[uuid.UUID] = Field(
        default=None, foreign_key="projects.id"
    )
    provider: str = Field(max_length=100)
    model: Optional[str] = Field(default=None, max_length=255)
    input_tokens: int = Field(default=0)
    output_tokens: int = Field(default=0)
    cost_cents: int = Field(default=0)
    billing_type: str = Field(default="llm_inference", max_length=100)
    occurred_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc).replace(tzinfo=None))
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc).replace(tzinfo=None))
