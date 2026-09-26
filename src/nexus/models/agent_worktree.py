"""Agent worktree: a git worktree and branch owned by one agent in one repository.

This module only defines the persisted record. Creating, merging and removing
worktrees, and moving a row between statuses, belong to the worktree service.

Ownership:

- ``agent_id`` is the permanent owner and never changes.
- ``session_id`` is the session currently holding the worktree. It is cleared
  when that session ends; rework after review attaches a new session. A session
  holds at most one ``created`` or ``active`` worktree at a time.
- ``company_id`` must match the company of the repository, agent, session,
  task and approval. The database does not check that across tables (there is
  no composite tenant key in this schema); the service does, and PostgreSQL
  row-level security keeps every read and write inside the current company.

``relative_path`` is relative to the company's worktree root and is resolved
and root-checked again on every use; an absolute path is never stored.

A worktree is not a sandbox: an agent process running in it can still reach
the rest of the filesystem.
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import CheckConstraint, Index, UniqueConstraint, text
from sqlmodel import Field, SQLModel

# Lifecycle, in order. Failure and abandonment end in archived; there are no
# separate failed or abandoned states.
#
#   created -> active -> review -> approved -> merged -> archived
WORKTREE_STATUSES = ("created", "active", "review", "approved", "merged", "archived")

# Statuses in which a worktree occupies its session.
SESSION_HOLDING_STATUSES = ("created", "active")

_STATUS_LIST = ", ".join(f"'{s}'" for s in WORKTREE_STATUSES)
_HOLDING_WHERE = text(
    "session_id IS NOT NULL AND status IN ("
    + ", ".join(f"'{s}'" for s in SESSION_HOLDING_STATUSES)
    + ")"
)


def _utcnow() -> datetime:
    # Models share the timezone.utc spelling (tests/test_utcnow_removal.py).
    return datetime.now(timezone.utc).replace(tzinfo=None)  # noqa: UP017


class AgentWorktree(SQLModel, table=True):
    """One agent's worktree and branch in a connected repository."""

    __tablename__ = "agent_worktrees"
    __table_args__ = (
        CheckConstraint(f"status IN ({_STATUS_LIST})", name="ck_agent_worktrees_status"),
        # Covers archived rows too: an unmerged branch is never deleted, so its
        # name stays taken in git after the row is archived.
        UniqueConstraint("repository_id", "branch", name="uq_agent_worktrees_repository_branch"),
        Index(
            "uq_agent_worktrees_session_holding",
            "session_id",
            unique=True,
            sqlite_where=_HOLDING_WHERE,
            postgresql_where=_HOLDING_WHERE,
        ),
        Index("ix_agent_worktrees_company_status", "company_id", "status"),
        Index("ix_agent_worktrees_company_agent", "company_id", "agent_id"),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    company_id: uuid.UUID = Field(foreign_key="companies.id", index=True)
    # RESTRICT: a repository or agent cannot be deleted while it owns worktrees.
    repository_id: uuid.UUID = Field(foreign_key="repositories.id", ondelete="RESTRICT")
    agent_id: uuid.UUID = Field(foreign_key="agents.id", ondelete="RESTRICT")
    session_id: uuid.UUID | None = Field(
        default=None, foreign_key="agent_sessions.id", ondelete="SET NULL", index=True
    )
    task_id: uuid.UUID | None = Field(default=None, foreign_key="tasks.id", ondelete="SET NULL")
    branch: str = Field(max_length=255)
    base_ref: str = Field(max_length=255)
    # Full object ids: 40 hex characters for SHA-1 repositories, 64 for SHA-256.
    base_commit: str = Field(max_length=64)
    head_commit: str | None = Field(default=None, max_length=64)
    merged_commit: str | None = Field(default=None, max_length=64)
    approval_id: uuid.UUID | None = Field(
        default=None, foreign_key="approvals.id", ondelete="SET NULL"
    )
    relative_path: str = Field(max_length=500)
    status: str = Field(default="created", max_length=20)
    created_by: str = Field(max_length=255)
    created_at: datetime = Field(default_factory=_utcnow)
    updated_at: datetime = Field(default_factory=_utcnow)
