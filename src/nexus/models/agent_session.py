"""Agent session model — the canonical record of one agent conversation/run.

A session groups the transcript (``chat_messages``), tool calls
(``tool_invocations``), spend (``cost_events``), checkpoints and heartbeat runs
that belong to a single agent interaction. Those tables carry a nullable
``session_id`` pointing here; there is deliberately no separate event table.
"""

import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import JSON, BigInteger, Index
from sqlmodel import Column, Field, SQLModel

SESSION_STATUSES = ("active", "idle", "completed", "failed", "terminated")
ENDED_STATUSES = ("completed", "failed", "terminated")

# Lifecycle: a session is created active, then alternates between active and
# idle as it is used and parked (a new turn wakes an idle session). completed,
# failed and terminated are final: an ended session never resumes, so
# continuing the work means opening a new session.
#
#   active <-> idle
#   active | idle -> completed | failed | terminated
TRANSITIONS: dict[str, frozenset[str]] = {
    "active": frozenset({"idle", "completed", "failed", "terminated"}),
    "idle": frozenset({"active", "completed", "failed", "terminated"}),
}


def _utcnow() -> datetime:
    # Models share the timezone.utc spelling (tests/test_utcnow_removal.py).
    return datetime.now(timezone.utc).replace(tzinfo=None)  # noqa: UP017


class AgentSessionRecord(SQLModel, table=True):
    """One agent session, scoped to a company and pinned to an adapter/model.

    The pin (adapter_type, model, llm_connection_id) is copied from the agent
    when the session opens and only changes through an explicit repin; a
    session whose pin is no longer usable refuses to run rather than fall back
    to another model. ``adapter_type == "unknown"`` marks an unpinned session
    (ws03 legacy backfill), which adopts the agent's config on its first turn.
    """

    __tablename__ = "agent_sessions"
    __table_args__ = (
        Index(
            "ix_agent_sessions_company_agent_activity", "company_id", "agent_id", "last_activity_at"
        ),
        Index("ix_agent_sessions_company_workspace", "company_id", "workspace_id"),
        Index("ix_agent_sessions_company_status", "company_id", "status"),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    company_id: uuid.UUID = Field(foreign_key="companies.id", index=True)
    agent_id: uuid.UUID = Field(foreign_key="agents.id", ondelete="CASCADE")
    workspace_id: uuid.UUID | None = Field(
        default=None, foreign_key="workspaces.id", ondelete="SET NULL"
    )
    status: str = Field(default="active", max_length=20)
    title: str | None = Field(default=None, max_length=255)
    adapter_type: str = Field(default="unknown", max_length=100)
    model: str | None = Field(default=None, max_length=255)
    # No ON DELETE action: a pinned connection cannot be deleted out from under
    # a session, which would silently unpin it. Retire it with is_active.
    llm_connection_id: uuid.UUID | None = Field(default=None, foreign_key="llm_connections.id")
    external_session_id: str | None = Field(default=None, max_length=255)
    # Monotonic per-session counter; chat_messages.seq is allocated from it.
    event_seq: int = Field(default=0, sa_type=BigInteger)
    created_by: str | None = Field(default=None, max_length=255)
    session_metadata: dict[str, Any] | None = Field(
        default=None, sa_column=Column("metadata", JSON)
    )
    started_at: datetime = Field(default_factory=_utcnow)
    last_activity_at: datetime = Field(default_factory=_utcnow)
    ended_at: datetime | None = Field(default=None)
