"""Tool invocation audit model - records every tool execution for compliance and analytics."""

import uuid
from datetime import datetime, timezone

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
    # NULL when the principal has no agent (an API key or user calling a tool directly).
    agent_id: uuid.UUID | None = Field(default=None, foreign_key="agents.id", index=True)
    # NULL for tools that are not rows in ``tools`` (MCP catalog tools, adapter-native tools).
    tool_id: uuid.UUID | None = Field(default=None, foreign_key="tools.id", index=True)
    connection_id: uuid.UUID | None = Field(default=None)
    session_id: uuid.UUID | None = Field(default=None, foreign_key="agent_sessions.id", ondelete="SET NULL", index=True)
    tool_name: str = Field(max_length=255)
    arguments_scrubbed: dict | None = Field(default=None, sa_column=Column(JSON))
    result_summary: str | None = Field(default=None)
    # success, error, timeout, denied, rate_limited, guardrail_blocked, autonomy_blocked
    status: str = Field(max_length=50)
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
    # Outcome of nexus.tools.access.check_tool_access: allowed, would_deny (audit
    # mode let the call run) or denied. NULL on rows written before WP ws05.
    authorization: str | None = Field(default=None, max_length=20, index=True)
    authorization_detail: dict | None = Field(default=None, sa_column=Column(JSON))
