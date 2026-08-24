"""Tool invocation audit model - records every tool execution for compliance and analytics."""

import uuid
from datetime import timezone, datetime

from sqlalchemy import JSON
from sqlmodel import Column, Field, SQLModel


class ToolInvocation(SQLModel, table=True):
    """Audit record for a single tool execution attempt.

    Captures the full lifecycle of a tool call including scrubbed arguments,
    execution outcome, duration, cost, and approval state for compliance tracking.
    """

    __tablename__ = "tool_invocations"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    company_id: uuid.UUID = Field(foreign_key="companies.id", index=True)
    agent_id: uuid.UUID = Field(foreign_key="agents.id", index=True)
    tool_id: uuid.UUID = Field(foreign_key="tools.id", index=True)
    connection_id: uuid.UUID | None = Field(default=None)
    tool_name: str = Field(max_length=255)
    arguments_scrubbed: dict | None = Field(default=None, sa_column=Column(JSON))
    result_summary: str | None = Field(default=None)
    status: str = Field(max_length=50)  # success, error, timeout, denied, rate_limited
    duration_ms: int = Field(default=0)
    cost_cents: int = Field(default=0)
    approval_state: str = Field(
        default="not_required", max_length=50
    )  # not_required, approved, denied
    error: str | None = Field(default=None)
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc).replace(tzinfo=None)
    )
    completed_at: datetime | None = Field(default=None)
