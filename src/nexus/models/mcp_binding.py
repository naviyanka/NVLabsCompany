"""MCP binding: grants an agent or one session access to a tool connection.

A binding is a grant, not a policy. It says "this agent (or this session) may
use this MCP server", minus any tools listed in ``disabled_tools``. It never
overrides a denial from RBAC, ``ToolPolicy``/``ToolProfile``, the autonomy gate
or the guardrails; ``nexus.tools.access.check_tool_access`` requires every one
of those to pass.

Scoping, as resolved by ``check_tool_access``:

- A session inherits its agent's bindings; a session binding adds to them.
- ``disabled_tools`` is the union across every binding in scope, so the more
  restrictive setting always wins.
- A binding with status ``disabled`` in scope revokes access to its connection,
  even when another binding in scope is active (explicit "off" wins).
- ``pending_approval`` grants nothing and revokes nothing.
"""

import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import JSON, CheckConstraint, Index, UniqueConstraint
from sqlmodel import Column, Field, SQLModel

BINDING_STATUSES = ("active", "disabled", "pending_approval")


def _utcnow() -> datetime:
    # Models share the timezone.utc spelling (tests/test_utcnow_removal.py).
    return datetime.now(timezone.utc).replace(tzinfo=None)  # noqa: UP017


class McpBinding(SQLModel, table=True):
    """One agent- or session-scoped grant of a ``ToolConnection``."""

    __tablename__ = "mcp_bindings"
    __table_args__ = (
        CheckConstraint(
            "(target_type = 'agent' AND agent_id IS NOT NULL AND session_id IS NULL)"
            " OR (target_type = 'session' AND session_id IS NOT NULL AND agent_id IS NULL)",
            name="ck_mcp_bindings_target",
        ),
        # NULLs are distinct in both dialects, so these only bite within a scope.
        UniqueConstraint("agent_id", "connection_id", name="uq_mcp_bindings_agent_connection"),
        UniqueConstraint(
            "session_id", "connection_id", name="uq_mcp_bindings_session_connection"
        ),
        Index("ix_mcp_bindings_company_agent", "company_id", "agent_id"),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    company_id: uuid.UUID = Field(foreign_key="companies.id", index=True)
    connection_id: uuid.UUID = Field(foreign_key="tool_connections.id", ondelete="CASCADE")
    target_type: str = Field(max_length=10)  # agent, session
    agent_id: uuid.UUID | None = Field(default=None, foreign_key="agents.id", ondelete="CASCADE")
    session_id: uuid.UUID | None = Field(
        default=None, foreign_key="agent_sessions.id", ondelete="CASCADE", index=True
    )
    disabled_tools: list[Any] = Field(default_factory=list, sa_column=Column(JSON, nullable=False))
    instructions: str | None = Field(default=None)
    status: str = Field(default="active", max_length=20)
    approval_id: uuid.UUID | None = Field(
        default=None, foreign_key="approvals.id", ondelete="SET NULL"
    )
    version: int = Field(default=1)
    created_by: str | None = Field(default=None, max_length=255)
    updated_by: str | None = Field(default=None, max_length=255)
    created_at: datetime = Field(default_factory=_utcnow)
    updated_at: datetime = Field(default_factory=_utcnow)
