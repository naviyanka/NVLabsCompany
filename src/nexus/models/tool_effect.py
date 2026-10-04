"""Durable ledger of write-capable tool effects, so a recovered turn never repeats one.

One ``tool_effects`` row is one *logical* tool call: a durable slot (tenant, chat turn,
round index, invocation index) always maps to the same row (see ``nexus.tools.effects`` for
the key). The slot, not the call's content, is the identity, so two identical calls at
different positions are two rows, and a recovered turn that reaches the same position finds
the same row. The row records the tool name and the argument digest it was claimed for; a
recovery that arrives at an occupied slot with a different tool or digest is refused.
The row is inserted in state ``executing`` *before* the tool runs, so a crash at any later
point leaves evidence that the effect may have happened.

States::

    executing -> succeeded | failed | ambiguous
    executing (lease expired) -> ambiguous
    failed -> executing                      (the tool said it did nothing: safe to retry)
    ambiguous -> executing                   (idempotent write only: automatic retry)
    ambiguous -> manual_recovery_required    (non-idempotent write: never rerun automatically)
    manual_recovery_required -> succeeded | failed   (audited operator decision only)

``claim_token`` is the holder's proof of ownership: only the claim that wrote it can settle
the row, so a holder whose lease expired and whose row was taken over cannot overwrite the
newer outcome. ``attempt_count`` only grows and doubles as the optimistic version for every
transition. ``result`` and ``error`` are bounded, scrubbed data, never raw tool output.
"""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import JSON, CheckConstraint, Index, UniqueConstraint
from sqlmodel import Column, Field, SQLModel

from nexus.models._time import utcnow

# Read-only calls are never ledgered, so only the two write classes can be stored.
WRITE_EFFECT_CLASSES = ("idempotent_write", "non_idempotent_write")
EFFECT_STATUSES = ("executing", "succeeded", "failed", "ambiguous", "manual_recovery_required")


def _in(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(repr(v) for v in values)})"


class ToolEffect(SQLModel, table=True):
    """One logical write-capable tool call and what is known about its effect."""

    __tablename__ = "tool_effects"
    __table_args__ = (
        UniqueConstraint("company_id", "invocation_key", name="uq_tool_effects_key"),
        CheckConstraint(_in("status", EFFECT_STATUSES), name="ck_tool_effects_status"),
        CheckConstraint(_in("effect_class", WRITE_EFFECT_CLASSES), name="ck_tool_effects_class"),
        CheckConstraint("attempt_count >= 1", name="ck_tool_effects_attempts"),
        CheckConstraint("turn_attempt >= 1", name="ck_tool_effects_turn_attempt"),
        CheckConstraint("round_index >= -1", name="ck_tool_effects_round"),
        CheckConstraint("invocation_index >= 0", name="ck_tool_effects_position"),
        CheckConstraint(
            "status <> 'executing' OR (claim_token IS NOT NULL AND lease_expires_at IS NOT NULL)",
            name="ck_tool_effects_executing_claim",
        ),
        Index("ix_tool_effects_company_turn", "company_id", "turn_id"),
        Index("ix_tool_effects_company_status", "company_id", "status"),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    company_id: uuid.UUID = Field(foreign_key="companies.id", ondelete="RESTRICT")
    # The chat turn's stable id (unlike its per-claim execution id). Not a foreign key: a
    # turn is deleted with its session, and the ledger must outlive it.
    turn_id: uuid.UUID
    # The durable slot: the model round within the turn (-1 for a caller that has no rounds
    # and numbers its writes in order) and the call's position within that round.
    round_index: int
    invocation_index: int
    tool_name: str = Field(max_length=255)
    effect_class: str = Field(max_length=24)
    # sha256 hex of the versioned canonical (company, turn, round, position) tuple.
    invocation_key: str = Field(max_length=64)
    # sha256 hex of the canonical arguments alone. Recovery compares it with the occupied
    # slot's digest, and it lets an operator match a row to a call without the ledger
    # holding the arguments.
    arguments_digest: str = Field(max_length=64)
    # Which execution of the turn (``ChatTurn.attempt_count``) first claimed this slot. A
    # recovered execution may replay a slot an earlier one claimed, but it may not open a new
    # write beside them (see ``nexus.tools.effects.claim``). Read from the turn row by the
    # server, never from a caller.
    turn_attempt: int = Field(default=1)
    status: str = Field(default="executing", max_length=24)
    claim_token: str | None = Field(default=None, max_length=64)
    attempt_count: int = Field(default=1)
    lease_expires_at: datetime | None = None
    result: dict[str, Any] | None = Field(default=None, sa_column=Column(JSON))
    error: str | None = Field(default=None, max_length=500)
    resolved_by: str | None = Field(default=None, max_length=100)
    resolved_at: datetime | None = None
    resolution_reason: str | None = Field(default=None, max_length=500)
    # Naive UTC, stored without a timezone; see nexus.models._time for why.
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)
    completed_at: datetime | None = None


class ToolNotification(SQLModel, table=True):
    """Marks that the notification for one logical invocation was already sent.

    The autonomy gate's level-2 notice is an external effect of its own. Inserting this row
    (the unique key decides the winner) before sending means a replay, or a concurrent claim
    for the same slot, does not send it again. A crash between the insert and the send loses
    the notice rather than duplicating it.
    """

    __tablename__ = "tool_notifications"

    company_id: uuid.UUID = Field(foreign_key="companies.id", ondelete="RESTRICT", primary_key=True)
    invocation_key: str = Field(max_length=64, primary_key=True)
    # Naive UTC, stored without a timezone; see nexus.models._time for why.
    created_at: datetime = Field(default_factory=utcnow)


class ToolBridgeSlot(SQLModel, table=True):
    """Maps a bridge client's idempotency key to a durable ledger slot of one turn.

    The inbound MCP bridge has no model rounds, and its HTTP handler is rebuilt per request, so
    nothing in memory can name "the same write". The client's ``Idempotency-Key`` does: the
    first request with a key reserves the next free ordinal of the turn, and every retry of
    that key, from any process or after a restart, finds the same row and therefore the same
    ledger slot ``(-1, ordinal)``. The primary key makes one winner per key and the unique
    ordinal makes one winner per slot, so concurrent requests can never share a slot. Company
    and turn come from the authenticated bridge credential, so a key only ever names a slot of
    the caller's own turn. ``tool_name`` and ``arguments_digest`` let a reused key with
    different content fail before anything is dispatched.
    """

    __tablename__ = "tool_bridge_slots"
    __table_args__ = (
        UniqueConstraint("company_id", "turn_id", "ordinal", name="uq_tool_bridge_slots_ordinal"),
        CheckConstraint("ordinal >= 0", name="ck_tool_bridge_slots_ordinal"),
    )

    company_id: uuid.UUID = Field(foreign_key="companies.id", ondelete="RESTRICT", primary_key=True)
    turn_id: uuid.UUID = Field(primary_key=True)
    idempotency_key: str = Field(max_length=128, primary_key=True)
    ordinal: int
    tool_name: str = Field(max_length=255)
    arguments_digest: str = Field(max_length=64)
    # Naive UTC, stored without a timezone; see nexus.models._time for why.
    created_at: datetime = Field(default_factory=utcnow)
