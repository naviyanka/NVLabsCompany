"""Task attempt: one durable try by an employee at a work task.

The ``Task`` stays the business item. Each time an employee works on it, a
``task_attempts`` row records that try: which employee and session, which
isolated worktree, which execution, what it produced and whether the
deterministic verifier accepted it. The ``nexus.runtime.task_attempts``
service owns every status change.

Lifecycle::

    queued -> claimed -> running -> verifying -> completed | failed | blocked
    queued | claimed | running | verifying -> cancelled
    queued -> expired
    claimed | running | verifying -> queued   (lease expired: recovery)

- At most one attempt per task is active (queued, claimed, running or
  verifying); a partial unique index enforces it.
- ``attempt_number`` is unique per task. A retry is a new attempt with the
  next number; the earlier attempt and its evidence are never rewritten.
- ``idempotency_key`` is unique per company and task, so a repeated start
  request attaches to the attempt it already created.
- ``claimed_by`` and ``lease_expires_at`` follow the chat-turn pattern: short
  transactions, renewed leases, and a sweep that recovers expired ones. The
  employee CLI itself runs as the attempt's chat turn, which has its own lease.
- ``report`` is the latest structured employee report; ``report_seq`` only
  grows, so an older update cannot overwrite a newer one.
- ``artifacts`` and ``verification`` hold manifests: relative paths, sizes,
  hashes, exit codes and references to bounded log files. Never file contents,
  secrets or absolute paths.

``WorkEffect`` is the side-effect ledger. Every effect a retry could repeat (a
git commit, a batch of evidence files, a notification, a governed tool call)
is recorded under a deterministic key first, so a retry or a recovered worker
finds the recorded result instead of doing it again.
"""

import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import JSON, CheckConstraint, Column, Index, Text, UniqueConstraint, text
from sqlmodel import Field, SQLModel

ATTEMPT_STATUSES = (
    "queued",
    "claimed",
    "running",
    "verifying",
    "completed",
    "failed",
    "blocked",
    "cancelled",
    "expired",
)
ACTIVE_ATTEMPT_STATUSES = ("queued", "claimed", "running", "verifying")
TERMINAL_ATTEMPT_STATUSES = ("completed", "failed", "blocked", "cancelled", "expired")
# Statuses a worker holds under a lease.
LEASED_ATTEMPT_STATUSES = ("claimed", "running", "verifying")

EFFECT_KINDS = ("tool_invocation", "file_write_batch", "git_commit", "pr_create", "notification")
EFFECT_STATUSES = ("pending", "done", "failed")

_ATTEMPT_STATUS_LIST = ", ".join(f"'{s}'" for s in ATTEMPT_STATUSES)
_EFFECT_KIND_LIST = ", ".join(f"'{s}'" for s in EFFECT_KINDS)
_EFFECT_STATUS_LIST = ", ".join(f"'{s}'" for s in EFFECT_STATUSES)
_ACTIVE_WHERE = text(
    "status IN (" + ", ".join(f"'{s}'" for s in ACTIVE_ATTEMPT_STATUSES) + ")"
)


def _utcnow() -> datetime:
    # Models share the timezone.utc spelling (tests/test_utcnow_removal.py).
    return datetime.now(timezone.utc).replace(tzinfo=None)  # noqa: UP017


class TaskAttempt(SQLModel, table=True):
    """One durable attempt by an employee at a task."""

    __tablename__ = "task_attempts"
    __table_args__ = (
        CheckConstraint(f"status IN ({_ATTEMPT_STATUS_LIST})", name="ck_task_attempts_status"),
        UniqueConstraint("task_id", "attempt_number", name="uq_task_attempts_task_number"),
        UniqueConstraint(
            "company_id", "task_id", "idempotency_key", name="uq_task_attempts_idempotency"
        ),
        Index(
            "uq_task_attempts_one_active",
            "task_id",
            unique=True,
            sqlite_where=_ACTIVE_WHERE,
            postgresql_where=_ACTIVE_WHERE,
        ),
        Index("ix_task_attempts_status_lease", "status", "lease_expires_at"),
        Index("ix_task_attempts_company_task", "company_id", "task_id"),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    company_id: uuid.UUID = Field(foreign_key="companies.id", index=True)
    task_id: uuid.UUID = Field(foreign_key="tasks.id", ondelete="CASCADE")
    agent_id: uuid.UUID = Field(foreign_key="agents.id", index=True)
    session_id: uuid.UUID | None = Field(
        default=None, foreign_key="agent_sessions.id", ondelete="SET NULL"
    )
    chat_turn_id: uuid.UUID | None = Field(
        default=None, foreign_key="chat_turns.id", ondelete="SET NULL"
    )
    attempt_number: int
    idempotency_key: str = Field(max_length=255)
    status: str = Field(default="queued", max_length=20)
    execution_id: str | None = Field(default=None, max_length=64)

    workspace_id: uuid.UUID | None = Field(
        default=None, foreign_key="workspaces.id", ondelete="SET NULL"
    )
    repository_id: uuid.UUID | None = Field(
        default=None, foreign_key="repositories.id", ondelete="SET NULL"
    )
    worktree_id: uuid.UUID | None = Field(
        default=None, foreign_key="agent_worktrees.id", ondelete="SET NULL"
    )

    claimed_by: str | None = Field(default=None, max_length=255)
    lease_expires_at: datetime | None = None
    recoveries: int = Field(default=0)
    cancel_requested_at: datetime | None = None
    cancelled_by: str | None = Field(default=None, max_length=255)
    created_by: str | None = Field(default=None, max_length=255)

    queued_at: datetime = Field(default_factory=_utcnow)
    started_at: datetime | None = None
    completed_at: datetime | None = None
    updated_at: datetime = Field(default_factory=_utcnow)

    # The work spec and prompt inputs as they were when the attempt started.
    context_snapshot: dict[str, Any] | None = Field(default=None, sa_column=Column(JSON))
    output_summary: str | None = Field(default=None, sa_column=Column(Text))
    completion_reason: str | None = Field(default=None, max_length=32)
    error_code: str | None = Field(default=None, max_length=64)
    error: str | None = Field(default=None, sa_column=Column(Text))

    report: dict[str, Any] | None = Field(default=None, sa_column=Column(JSON))
    report_seq: int = Field(default=0)
    artifacts: list[dict[str, Any]] | None = Field(default=None, sa_column=Column(JSON))
    verification: dict[str, Any] | None = Field(default=None, sa_column=Column(JSON))
    # Tokens, cost, backend, model and duration of the execution.
    usage: dict[str, Any] | None = Field(default=None, sa_column=Column(JSON))


class WorkEffect(SQLModel, table=True):
    """One recorded side effect, keyed so that it happens at most once."""

    __tablename__ = "work_effects"
    __table_args__ = (
        CheckConstraint(f"kind IN ({_EFFECT_KIND_LIST})", name="ck_work_effects_kind"),
        CheckConstraint(f"status IN ({_EFFECT_STATUS_LIST})", name="ck_work_effects_status"),
        UniqueConstraint("company_id", "effect_key", name="uq_work_effects_key"),
        Index("ix_work_effects_company_task", "company_id", "task_id"),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    company_id: uuid.UUID = Field(foreign_key="companies.id", index=True)
    task_id: uuid.UUID | None = Field(default=None, foreign_key="tasks.id", ondelete="CASCADE")
    attempt_id: uuid.UUID | None = Field(
        default=None, foreign_key="task_attempts.id", ondelete="SET NULL"
    )
    kind: str = Field(max_length=32)
    effect_key: str = Field(max_length=255)
    status: str = Field(default="pending", max_length=16)
    result: dict[str, Any] | None = Field(default=None, sa_column=Column(JSON))
    created_at: datetime = Field(default_factory=_utcnow)
    updated_at: datetime = Field(default_factory=_utcnow)
