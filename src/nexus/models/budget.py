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
    spent_cents: int = Field(default=0)
    reserved_cents: int = Field(default=0)
    warn_percent: int = Field(default=80)
    hard_stop_enabled: bool = Field(default=True)
    is_active: bool = Field(default=True)
    window_started_at: Optional[datetime] = Field(default=None)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc).replace(tzinfo=None))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc).replace(tzinfo=None))


class CostEvent(SQLModel, table=True):
    """Records an individual cost event (LLM call, tool usage, etc.).

    Doubles as the two-phase budget ledger. A row written before a provider
    call carries ``status="reserved"`` and an ``expires_at``: it holds the
    estimated spend so concurrent workers see it in the same window sum that
    committed rows land in. After the call the row is reconciled to the exact
    cost (``status="committed"``) or released (``status="released"``, excluded
    from the sum). Reusing this table rather than a separate reservations one
    means the existing window aggregation needs no second query to stay
    correct.
    """

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
    policy_id: Optional[uuid.UUID] = Field(
        default=None, foreign_key="budget_policies.id", index=True
    )
    provider: str = Field(max_length=100)
    model: Optional[str] = Field(default=None, max_length=255)
    input_tokens: int = Field(default=0)
    output_tokens: int = Field(default=0)
    cost_cents: int = Field(default=0)
    billing_type: str = Field(default="llm_inference", max_length=100)
    # Two-phase ledger state: reserved (hold), committed (settled), released
    # (hold returned). Existing rows predate reservations and are committed.
    status: str = Field(default="committed", max_length=20, index=True)
    # When a reservation stops counting against the budget. A worker that dies
    # mid-call would otherwise hold spend forever; the window sum ignores
    # reserved rows past this instant, so a crash self-heals without a sweeper.
    expires_at: Optional[datetime] = Field(default=None)
    occurred_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc).replace(tzinfo=None))
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc).replace(tzinfo=None))
