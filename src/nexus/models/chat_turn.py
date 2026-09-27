"""Chat turn: one user prompt to an employee and the execution that answers it.

The database row is the source of truth for a turn, not the request that
created it. Any API worker may claim a queued turn, so a turn survives a
browser refresh, a dropped connection and a backend restart. The
``nexus.runtime.chat_turns`` service owns every status change.

Lifecycle::

    queued -> claimed -> running -> completed | failed | cancelled
    queued -> cancelled | expired
    claimed/running -> queued   (lease expired, attempts left: recovery)

- ``turn_seq`` is the prompt message's ``seq`` in its session, so turns of one
  session are ordered the same way as the transcript. A turn is claimed only
  when every earlier turn of its session is terminal.
- ``idempotency_key`` is unique per company and session. A retried request
  with the same key attaches to the existing turn.
- ``claimed_by`` and ``lease_expires_at`` say which worker runs the turn and
  until when. A worker that stops renewing loses the turn to recovery.
- ``execution_context`` is the server-built
  :class:`~nexus.tools.context.ExecutionContext` of the request that created
  the turn. It never holds credentials.
"""

import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import JSON, CheckConstraint, Column, Index, Text, UniqueConstraint
from sqlmodel import Field, SQLModel

TURN_STATUSES = ("queued", "claimed", "running", "completed", "failed", "cancelled", "expired")
TERMINAL_STATUSES = ("completed", "failed", "cancelled", "expired")
ACTIVE_STATUSES = ("claimed", "running")

_STATUS_LIST = ", ".join(f"'{s}'" for s in TURN_STATUSES)


def _utcnow() -> datetime:
    # Models share the timezone.utc spelling (tests/test_utcnow_removal.py).
    return datetime.now(timezone.utc).replace(tzinfo=None)  # noqa: UP017


class ChatTurn(SQLModel, table=True):
    """One durable employee chat turn."""

    __tablename__ = "chat_turns"
    __table_args__ = (
        CheckConstraint(f"status IN ({_STATUS_LIST})", name="ck_chat_turns_status"),
        UniqueConstraint(
            "company_id", "session_id", "idempotency_key", name="uq_chat_turns_idempotency"
        ),
        UniqueConstraint("session_id", "turn_seq", name="uq_chat_turns_session_seq"),
        Index("ix_chat_turns_status_queued", "status", "queued_at"),
        Index("ix_chat_turns_status_lease", "status", "lease_expires_at"),
        Index("ix_chat_turns_company_session_status", "company_id", "session_id", "status"),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    company_id: uuid.UUID = Field(foreign_key="companies.id", index=True)
    agent_id: uuid.UUID = Field(foreign_key="agents.id", index=True)
    session_id: uuid.UUID = Field(foreign_key="agent_sessions.id", ondelete="CASCADE")
    idempotency_key: str = Field(max_length=255)
    request_id: str | None = Field(default=None, max_length=255)
    turn_seq: int
    status: str = Field(default="queued", max_length=20)

    prompt_message_id: uuid.UUID | None = Field(
        default=None, foreign_key="chat_messages.id", ondelete="SET NULL"
    )
    response_message_id: uuid.UUID | None = Field(
        default=None, foreign_key="chat_messages.id", ondelete="SET NULL"
    )
    execution_id: str | None = Field(default=None, max_length=64)
    adapter_used: str | None = Field(default=None, max_length=100)
    backend_used: str | None = Field(default=None, max_length=100)
    model_used: str | None = Field(default=None, max_length=100)

    claimed_by: str | None = Field(default=None, max_length=255)
    lease_expires_at: datetime | None = None
    attempt_count: int = Field(default=0)
    max_attempts: int = Field(default=3)
    cancel_requested_at: datetime | None = None
    cancelled_by: str | None = Field(default=None, max_length=255)

    error_code: str | None = Field(default=None, max_length=64)
    error_message: str | None = Field(default=None, sa_column=Column(Text))

    queued_at: datetime = Field(default_factory=_utcnow)
    claimed_at: datetime | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    updated_at: datetime = Field(default_factory=_utcnow)

    execution_context: dict[str, Any] | None = Field(default=None, sa_column=Column(JSON))
    result: dict[str, Any] | None = Field(default=None, sa_column=Column(JSON))
