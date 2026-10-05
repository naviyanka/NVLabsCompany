"""Execute-once protocol for write-capable tool calls.

A chat turn that expires or is interrupted is requeued and its model and tool rounds run
again. Without a stable identity for "the same tool call", the rerun would repeat an external
effect. This module gives every write-capable call a logical identity, records it durably
*before* the tool runs, and decides on a rerun from what the ledger says happened. The
operator-facing description (key derivation, state machine, recovery steps) is in
``docs/runbooks/tool-effect-recovery.md``.

Classification (:class:`EffectClass`), declared explicitly on each tool, never inferred from
a tool name or a risk label:

- ``read_only``: no ledger row; a rerun is harmless.
- ``idempotent_write``: repeating the call with the same arguments leaves the same state.
  An interrupted call is retried automatically.
- ``non_idempotent_write``: a second run would do the effect twice. An interrupted call is
  never rerun; it waits for an audited operator decision. A tool with no declared class is
  treated as this one, so a missing declaration fails closed.

Logical key: ``sha256(json([KEY_VERSION, company_id, turn_id, round_index, invocation_index]))``.
The identity is a durable *slot*: the model round within the turn and the call's position in
that round. It does not depend on the call's content, so two identical calls at different
positions are two logical calls, and a recovered turn that reaches the same position finds
the same row. The row stores the tool name and the digest of the canonical arguments (JSON
with sorted keys, ``(",", ":")`` separators, ASCII escapes and no NaN); a recovery that
arrives at an occupied slot with a different tool or digest is refused. Provider-generated
call ids are never part of the key (a rerun regenerates them), and nothing here is a
process-global counter.

A recovered execution of a turn (``ChatTurn.attempt_count > 1``, read from the turn row by the
server, never from a caller) may replay the slots an earlier execution claimed, but it may not
open a new write beside them: its model may have planned the same write at another position,
and nothing durable records which positions were planned. Such a call is ``blocked`` (the
model sees ``effect_recovery_required``), idempotent or not, because an idempotent write's
downstream key follows the slot. Reads are never ledgered and are unaffected.

Every execution of a turn carries an immutable epoch (:class:`Epoch`): the ``execution_id`` and
attempt the runtime copied from the turn row when it claimed the turn (the inbound bridge copies
them when it verifies its credential). Before any write effect is claimed it is compared, under
a share lock on the turn row, with the turn's current attempt. A worker a recovery replaced
(a zombie) is ``stale``: nothing is inserted, spent, approved, notified or run, idempotent or
not, and its epoch is never refreshed. Reads are not fenced. No model, argument, header or MCP
client can set the epoch.

The inbound MCP bridge has no rounds: a write names itself with the HTTP ``Idempotency-Key``
header or with the declared ``nexus_invocation_key`` tool argument (a tool's own
``idempotency_key`` when it has one), see :func:`resolve_bridge_identity`. Both must agree when
both are sent. :func:`reserve_bridge_slot` maps that key durably to the slot ``(-1, ordinal)``
of the turn; the client's value is never the downstream business key.

A write-capable call inside a turn with no slot is refused rather than run without a durable
identity. A call without a turn id (a plain REST request) is not ledgered: nothing requeues it.

Outcomes fail closed. Only an :class:`EffectNotStarted` raised for a failure proven to happen
before dispatch or mutation (or a result flagged ``effect_rejected``) is a retryable
``failed``. Everything else that is not a clean success, including a plain ``ValueError``, an
in-band tool error, a timeout, cancellation and any unexpected exception, is ``ambiguous``.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import logging
import re
import secrets
import uuid
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal
from enum import Enum, StrEnum
from pathlib import PurePath
from typing import Any, Literal

from sqlalchemy import and_ as sa_and
from sqlalchemy import func, literal_column, or_, select, update
from sqlalchemy.exc import IntegrityError

from nexus.models._time import utcnow
from nexus.models.chat_turn import ChatTurn
from nexus.models.tool_effect import ToolBridgeSlot, ToolEffect, ToolNotification

logger = logging.getLogger(__name__)

KEY_VERSION = "nexus.tool-effect.v2"
# A live holder must settle within this window. There is no heartbeat: a call that runs
# longer is treated as interrupted by a later claim (a non-idempotent one then needs an
# operator, an idempotent one is retried). Lease decisions use the database clock, never a
# worker's own.
LEASE_SECONDS = 900
MAX_RESULT_BYTES = 16_384
MAX_TEXT_CHARS = 500

Action = Literal["run", "replay", "busy", "blocked", "denied", "stale"]


class EffectClass(StrEnum):
    READ_ONLY = "read_only"
    IDEMPOTENT_WRITE = "idempotent_write"
    NON_IDEMPOTENT_WRITE = "non_idempotent_write"


class BridgeSlotError(ValueError):
    """A bridge write has no usable idempotency identity, so it must not be dispatched."""


class EffectKeyError(ValueError):
    """The arguments have no canonical form, so the call has no stable identity."""


class EffectStateError(RuntimeError):
    """A manual-recovery request does not match what the ledger holds."""


class EffectNotStarted(ValueError):  # noqa: N818 - a signal, not an error
    """The call failed before it was dispatched and before it changed anything.

    The only exception that lets a non-idempotent write become a retryable ``failed``. Raise
    it only where the code itself proves that nothing was sent and nothing was mutated (an
    argument or configuration check that runs ahead of the first side effect). A timeout, a
    malformed response, an HTTP error status or anything raised once the tool has begun to
    act does not qualify.
    """


class ResultNotRetainable(Exception):  # noqa: N818 - a signal, not an error
    """A tool result has no JSON form that can be stored safely."""


@dataclass(frozen=True)
class ToolSlot:
    """Where a call sits in a turn: its model round and its position within that round.

    ``round_index`` is ``-1`` for a caller that has no rounds and numbers its writes in
    order (the MCP bridge). Parallel provider calls in one round are numbered by the order the
    provider returned them, which a recovery reproduces.
    """

    round_index: int
    invocation_index: int

    def __post_init__(self) -> None:
        for value in (self.round_index, self.invocation_index):
            if not isinstance(value, int) or isinstance(value, bool):
                raise ValueError("a tool slot is two integers")
        if self.round_index < -1 or self.invocation_index < 0:
            raise ValueError("a tool slot has round >= -1 and position >= 0")


def resolve_effect(declared: str | EffectClass | None) -> EffectClass:
    """The class a call runs under; anything undeclared or unknown is non-idempotent."""
    try:
        return EffectClass(declared) if declared is not None else EffectClass.NON_IDEMPOTENT_WRITE
    except ValueError:
        return EffectClass.NON_IDEMPOTENT_WRITE


def canonical_arguments(arguments: Any) -> str:
    try:
        return json.dumps(
            arguments, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False
        )
    except (TypeError, ValueError) as exc:
        raise EffectKeyError("tool arguments are not canonical JSON") from exc


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def invocation_key(company_id: uuid.UUID, turn_id: uuid.UUID, slot: ToolSlot) -> str:
    """The logical identity of the call at ``slot`` in a turn."""
    parts = [KEY_VERSION, str(company_id), str(turn_id), slot.round_index, slot.invocation_index]
    return _sha256(json.dumps(parts, separators=(",", ":")))


def arguments_digest(arguments: Any) -> str:
    """sha256 of the canonical arguments; :class:`EffectKeyError` if there is none."""
    return _sha256(canonical_arguments(arguments))


# The ledger key of the call now running, so a tool can hand it downstream as its idempotency
# key instead of trusting a key the model regenerates on every recovery.
_current_key: ContextVar[str | None] = ContextVar("nexus_tool_effect_key", default=None)


@contextmanager
def bind_invocation(key: str | None) -> Iterator[None]:
    token = _current_key.set(key)
    try:
        yield
    finally:
        _current_key.reset(token)


def downstream_key(model_key: str | None) -> str | None:
    """The idempotency key to pass downstream: the ledger's when one is bound, else the model's.

    Inside a ledgered call the model's own key is ignored, because a recovered model
    regenerates it. With no ledger there is no recovery to protect, so the caller's key stands.
    """
    return _current_key.get() or model_key


@dataclass(frozen=True)
class Claim:
    """What the ledger decided for one call."""

    action: Action
    company_id: uuid.UUID
    effect_class: EffectClass
    effect_id: uuid.UUID | None = None
    token: str | None = None
    stored: dict[str, Any] | None = None
    reason: str = ""
    # The slot's invocation key, for the downstream idempotency binding and notice dedupe.
    key: str | None = None


# --- bounded, scrubbed result and error data ------------------------------------------------


# Token shapes the guardrail patterns do not cover. Free text cannot be proven clean, so this is
# a second net; raised exceptions are stored by type only (see ``guarded_call``).
_TOKEN_PATTERNS = (
    r"\bsk-[A-Za-z0-9_-]{8,}",
    r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]{8,}",
    r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]*",
    r"(?i)\b(api[_-]?key|token|secret|authorization)\b\s*[:=]\s*\S+",
)


def _mask(text: str) -> str:
    from nexus.tools.factory import BLOCKED_PATTERNS

    for pattern in (*BLOCKED_PATTERNS, *_TOKEN_PATTERNS):
        text = re.sub(pattern, "[redacted]", text)
    return text


def redact_text(text: Any, limit: int = MAX_TEXT_CHARS) -> str:
    """Mask secret-looking text (guardrail patterns plus token shapes), then cap the length."""
    return _mask(str(text))[:limit]


def _flatten(result: Any) -> tuple[str, Any]:
    from nexus.nodes.executor import ExecutorResult
    from nexus.tools.mcp_client import MCPResult

    if isinstance(result, ExecutorResult):
        return "executor_result", {
            "success": result.success,
            "outputs": result.outputs,
            "error": redact_text(result.error) if result.error else None,
        }
    if isinstance(result, MCPResult):
        return "mcp_result", {
            "content": result.content,
            "is_error": result.is_error,
            "metadata": result.metadata,
        }
    return "json", result


def _json_default(value: Any) -> Any:
    """Plain scalar forms for the few non-JSON types tools commonly return."""
    if isinstance(value, uuid.UUID | datetime | date | Decimal | PurePath):
        return str(value)
    if isinstance(value, Enum):
        return value.value
    raise TypeError(f"{type(value).__name__} is not JSON serializable")


# Tighter and tighter limits until the result fits: (string chars, list items, nesting depth).
_BOUND_TIERS = ((2000, 100, 8), (500, 20, 5), (120, 5, 3))
_SKELETON_KEYS = 50
_SKELETON_CHARS = 120


def _bound(value: Any, strings: int, items: int, depth: int, cut: list[bool]) -> Any:
    """Redact strings and cap sizes, leaving a visible marker wherever something was dropped."""
    if isinstance(value, str):
        text = _mask(value)
        if len(text) > strings:
            cut[0] = True
            return f"{text[:strings]}...[truncated {len(text) - strings} chars]"
        return text
    if isinstance(value, dict):
        if depth <= 0:
            cut[0] = True
            return "[truncated: nesting]"
        out = {
            str(k)[:100]: _bound(v, strings, items, depth - 1, cut)
            for k, v in list(value.items())[:items]
        }
        if len(value) > items:
            cut[0] = True
            out["_truncated_keys"] = len(value) - items
        return out
    if isinstance(value, list):
        if depth <= 0:
            cut[0] = True
            return "[truncated: nesting]"
        out_list = [_bound(v, strings, items, depth - 1, cut) for v in value[:items]]
        if len(value) > items:
            cut[0] = True
            out_list.append(f"[{len(value) - items} more items truncated]")
        return out_list
    return value


def _skeleton(value: Any, cut: list[bool]) -> Any:
    """Last resort: the top-level scalar fields only (identifiers, statuses, counts)."""
    cut[0] = True
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for k, v in list(value.items())[:_SKELETON_KEYS]:
            if isinstance(v, str):
                out[str(k)[:100]] = _bound(v, _SKELETON_CHARS, 0, 0, cut)
            elif v is None or isinstance(v, bool | int | float):
                out[str(k)[:100]] = v
        out["_truncated_fields"] = True
        return out
    return _bound(value, _SKELETON_CHARS, 0, 0, cut)


def _size(value: Any) -> int:
    return len(json.dumps(value, sort_keys=True, separators=(",", ":")).encode())


def seal_result(result: Any) -> dict[str, Any]:
    """The one durable, bounded, scrubbed form of a result, stored and returned to every caller.

    The first caller and every replay receive the output of :func:`decode_result` on this same
    envelope, so a recovery never sees less (or more) than the original run did. Secret-looking
    keys are masked (the rule the invocation audit row uses), strings are pattern-redacted,
    and a result over :data:`MAX_RESULT_BYTES` is cut down in steps that keep short scalar
    identifiers and say where data was dropped. Raises :class:`ResultNotRetainable` when the
    result has no JSON form (the effect already happened, so the caller must settle ambiguous
    rather than rerun).
    """
    from nexus.tools.executor import _scrub_value

    kind, value = _flatten(result)
    try:
        plain = json.loads(json.dumps(value, default=_json_default, allow_nan=False))
        plain = _scrub_value(plain)
        original_bytes = _size(plain)
        cut = [False]
        bounded = _bound(plain, *_BOUND_TIERS[0], cut)
        for tier in _BOUND_TIERS[1:]:
            if _size(bounded) <= MAX_RESULT_BYTES:
                break
            cut = [True]
            bounded = _bound(plain, *tier, cut)
        if _size(bounded) > MAX_RESULT_BYTES:
            bounded = _skeleton(plain, cut)
        digest = _sha256(json.dumps(plain, sort_keys=True, separators=(",", ":")))
    except (TypeError, ValueError, RecursionError, OverflowError) as exc:
        raise ResultNotRetainable(type(exc).__name__) from exc
    envelope: dict[str, Any] = {"kind": kind, "value": bounded}
    if cut[0]:
        envelope["truncated"] = {"original_bytes": original_bytes, "sha256": digest}
    return envelope


def decode_result(stored: dict[str, Any]) -> Any:
    """Rebuild the result object a caller expects from :func:`seal_result` output."""
    from nexus.nodes.executor import ExecutorResult
    from nexus.tools.mcp_client import MCPResult

    kind = stored["kind"]
    value = stored.get("value")
    if kind == "executor_result":
        return ExecutorResult(
            success=value["success"], outputs=value["outputs"] or {}, error=value["error"]
        )
    if kind == "mcp_result":
        return MCPResult(
            content=value["content"], is_error=value["is_error"], metadata=value["metadata"] or {}
        )
    if kind == "json":
        return value
    raise ValueError(f"unknown stored result kind {kind!r}")


def outcome_of(result: Any, tool_name: str | None = None) -> tuple[str, str | None]:
    """``(status, error)`` for a result the tool returned rather than raised.

    Fails closed: only a clean success is ``succeeded``, and only a result flagged
    ``effect_rejected`` (the tool proved it acted on nothing) is a retryable ``failed``. A
    result that reports an error without that proof, such as an in-band MCP error or a
    non-success executor result, may still have had an effect and is ``ambiguous``.
    """
    if getattr(result, "effect_unknown", False):
        return "ambiguous", getattr(result, "error", None) or "outcome unknown"
    if getattr(result, "effect_rejected", False):
        return "failed", str(getattr(result, "error", None) or getattr(result, "content", ""))
    if getattr(result, "is_error", False):
        return "ambiguous", str(getattr(result, "content", "")) or "in-band tool error"
    if getattr(result, "success", True) is False:
        return "ambiguous", getattr(result, "error", None) or "tool reported failure"
    if isinstance(result, dict):
        from nexus.tools.obsidian import (
            OBSIDIAN_NOTE_REPLACE_NAME,
            OBSIDIAN_REJECTED_STATUSES,
            OBSIDIAN_UNCERTAIN_STATUSES,
        )

        status = result.get("status")
        if tool_name == OBSIDIAN_NOTE_REPLACE_NAME and status in OBSIDIAN_REJECTED_STATUSES:
            return "failed", str(result.get("reason") or status)
        if tool_name == OBSIDIAN_NOTE_REPLACE_NAME and status in OBSIDIAN_UNCERTAIN_STATUSES:
            return "ambiguous", str(result.get("reason") or status)
    return "succeeded", None


def outcome_of_exception(exc: BaseException) -> str:
    """``failed`` only for an :class:`EffectNotStarted`; every other raise is ``ambiguous``.

    A plain ``ValueError``, a decoding error, a timeout, cancellation or an HTTP error may
    all surface after the effect began, so none of them proves that nothing happened.
    """
    if isinstance(exc, EffectNotStarted):
        return "failed"
    return "ambiguous"


# --- ledger transitions ---------------------------------------------------------------------


def _audit_details(row: ToolEffect, **extra: Any) -> dict[str, Any]:
    """Identifiers and states only: never arguments, results or error text."""
    return {
        "tool_name": row.tool_name,
        "effect_class": row.effect_class,
        "turn_id": str(row.turn_id),
        "invocation_key": row.invocation_key,
        "attempt_count": row.attempt_count,
        **extra,
    }


async def _audit(
    db: Any,
    row: ToolEffect,
    action: str,
    *,
    actor_type: str = "system",
    actor_id: str = "tool_effects",
    must: bool = False,
    **extra: Any,
) -> None:
    from nexus.governance.audit_service import record_audit

    await record_audit(
        row.company_id,
        f"tool_effect.{action}",
        actor_type=actor_type,
        actor_id=actor_id,
        resource_type="tool_effect",
        resource_id=str(row.id),
        details=_audit_details(row, **extra),
        db=db,
        raise_on_error=must,
    )


def _cas(row: ToolEffect, **values: Any) -> Any:
    """UPDATE guarded by the status and attempt count the decision was based on."""
    return (
        update(ToolEffect)
        .where(
            ToolEffect.id == row.id,
            ToolEffect.company_id == row.company_id,
            ToolEffect.status == row.status,
            ToolEffect.attempt_count == row.attempt_count,
        )
        .values(updated_at=utcnow(), **values)
    )


async def _db_now(db: Any) -> datetime:
    """The database's current time as naive UTC, the form every ledger timestamp is stored in.

    Lease expiry and takeover are decided against this clock, never a worker's: workers can
    disagree by seconds or minutes, and a skewed one would otherwise reclaim a live call early.
    PostgreSQL's ``clock_timestamp()`` advances inside a transaction (unlike ``now()``).
    """
    dialect = (await db.connection()).dialect.name
    if dialect == "postgresql":
        now = select(literal_column("timezone('UTC', clock_timestamp())"))
        return (await db.execute(now)).scalar_one()
    # SQLite has no server; its own clock is the equivalent, and is read in SQL so a test can
    # skew the Python clock without moving it.
    text = (
        await db.execute(select(func.strftime("%Y-%m-%d %H:%M:%f", "now")))
    ).scalar_one()
    return datetime.strptime(text, "%Y-%m-%d %H:%M:%S.%f")


async def claim(
    company_id: uuid.UUID,
    turn_id: uuid.UUID,
    slot: ToolSlot,
    tool_name: str,
    effect_class: EffectClass,
    arguments: Any,
    grant_id: uuid.UUID | None = None,
    *,
    epoch: Epoch | None = None,
) -> Claim:
    """Reserve the call at ``slot``, or say why it must not run now.

    ``epoch`` is the execution of the turn this caller was started as. It is compared, under a
    share lock on the turn row, with the execution the database currently holds; any
    difference (or no epoch at all) is ``stale`` and nothing is inserted, spent or run. The
    lock keeps a recovery from advancing the turn until this claim has committed.

    With ``grant_id`` the temporary allow the call relies on is spent in the same transaction,
    and only when the decision is ``run``: a replay, a busy or blocked slot and a slot mismatch
    never spend. The use is keyed by this slot, so a retake of the slot after a crash does not
    spend again. If the grant is no longer live nothing is committed, the result is ``denied``.

    Exactly one caller gets ``run`` for a given slot at a time: the first INSERT wins on the
    unique key, and every later takeover is one compare-and-set UPDATE. A recovery that
    reaches an occupied slot with a different tool or argument digest is ``blocked``. Raises
    :class:`EffectKeyError` for non-canonical arguments and propagates database errors; the
    caller must then refuse the call rather than run it unrecorded.
    """
    from nexus import database

    key = invocation_key(company_id, turn_id, slot)
    digest = arguments_digest(arguments)
    token = secrets.token_hex(16)
    async with database.tenant_session(company_id) as db:
        stale = await _stale_reason(db, company_id, turn_id, epoch)
        if stale:
            logger.warning("stale execution of turn %s refused a write: %s", turn_id, stale)
            await db.rollback()
            return Claim("stale", company_id, effect_class, key=key, reason=stale)
        assert epoch is not None  # a missing epoch was stale above
        attempt = epoch.attempt
        lease = (await _db_now(db)) + timedelta(seconds=LEASE_SECONDS)
        new = ToolEffect(
            company_id=company_id,
            turn_id=turn_id,
            round_index=slot.round_index,
            invocation_index=slot.invocation_index,
            tool_name=tool_name,
            effect_class=effect_class.value,
            invocation_key=key,
            arguments_digest=digest,
            turn_attempt=attempt,
            claim_token=token,
            lease_expires_at=lease,
        )
        try:
            async with db.begin_nested():
                db.add(new)
                await db.flush()
                if attempt > 1 and await _earlier_execution_wrote(db, new, attempt):
                    raise _NewSlotInRecovery
        except IntegrityError:
            pass
        except _NewSlotInRecovery:
            # The savepoint rolled the new row back: nothing was reserved or spent.
            logger.warning(
                "recovered turn %s attempt %d tried a new write %s at slot (%d, %d)",
                turn_id, attempt, tool_name, slot.round_index, slot.invocation_index,
            )
            return Claim(
                "blocked", company_id, effect_class, key=key,
                reason=(
                    "this turn was recovered and already made writes, so a new write at a "
                    "position no earlier run used needs an operator to decide"
                ),
            )
        else:
            first = Claim("run", company_id, effect_class, new.id, token, key=key)
            return await _commit_run(db, first, grant_id)
        row = (
            await db.execute(
                select(ToolEffect)
                .where(ToolEffect.company_id == company_id, ToolEffect.invocation_key == key)
                .with_for_update()
            )
        ).scalar_one()
        if row.tool_name != tool_name or row.arguments_digest != digest:
            # Recovery diverged from what ran here before. Whether the occupant ran is not
            # this call's to guess, so nothing runs and an operator looks at the turn.
            await _audit(
                db, row, "slot_mismatch", requested_tool=tool_name, requested_digest=digest
            )
            await db.commit()
            return Claim(
                "blocked", company_id, effect_class, row.id, key=key,
                reason="slot is occupied by a different call",
            )
        decision = await _decide(db, row, effect_class, token)
        if decision.action == "run":
            return await _commit_run(db, decision, grant_id)
        await db.commit()
        return decision


class _NewSlotInRecovery(Exception):  # noqa: N818 - rolls back the savepoint, never escapes
    """A recovered execution reached an empty slot while earlier writes exist."""


@dataclass(frozen=True)
class Epoch:
    """Which execution of a turn a caller is: fixed when the turn was claimed, never refreshed.

    ``execution_id`` and ``attempt`` come from the ``ChatTurn`` row the runtime claimed (or,
    for the MCP bridge, from the turn the bridge credential was minted for). A model, an
    argument, a header or a service key cannot supply either.
    """

    execution_id: str | None
    attempt: int


async def _stale_reason(
    db: Any, company_id: uuid.UUID, turn_id: uuid.UUID, epoch: Epoch | None
) -> str:
    """Why ``epoch`` is not the turn's current execution, or ``""`` when it is.

    Reads the turn row under a share lock, so a recovery (an UPDATE of the same row) waits for
    the caller's transaction. A turn with no row (a direct call that was never queued) has the
    single execution 1.
    """
    if epoch is None:
        return "this call carries no execution epoch, so it cannot be fenced"
    row = (
        await db.execute(
            select(ChatTurn.execution_id, ChatTurn.attempt_count)
            .where(ChatTurn.id == turn_id, ChatTurn.company_id == company_id)
            .with_for_update(read=True)
        )
    ).first()
    if row is None:
        return "" if epoch.attempt == 1 else "the turn no longer exists for this execution"
    current_id, current_attempt = row
    if max(current_attempt or 1, 1) != epoch.attempt or (
        epoch.execution_id is not None and str(current_id) != epoch.execution_id
    ):
        return (
            f"this execution (attempt {epoch.attempt}) was replaced by a recovery; "
            "only the current execution of a turn may write"
        )
    return ""


async def is_current_execution(
    company_id: uuid.UUID, turn_id: uuid.UUID, epoch: Epoch | None
) -> str:
    """Early, advisory form of the fence for callers that act before claiming (``""`` = current)."""
    from nexus import database

    async with database.tenant_session(company_id) as db:
        reason = await _stale_reason(db, company_id, turn_id, epoch)
        await db.rollback()
        return reason


async def _earlier_execution_wrote(db: Any, row: ToolEffect, attempt: int) -> bool:
    """Whether a previous execution of the turn claimed any write other than ``row``."""
    found = await db.execute(
        select(ToolEffect.id)
        .where(
            ToolEffect.company_id == row.company_id,
            ToolEffect.turn_id == row.turn_id,
            ToolEffect.turn_attempt < attempt,
            ToolEffect.id != row.id,
        )
        .limit(1)
    )
    return found.first() is not None


BRIDGE_KEY_PATTERN = re.compile(r"[A-Za-z0-9._:~-]{1,128}")
# Slot allocation retries when a concurrent request takes the key or the ordinal first. Each
# lost round means another request won, so the bound is the number of simultaneous writes
# in one turn.
_BRIDGE_ATTEMPTS = 50


def valid_bridge_key(key: Any) -> bool:
    """Whether ``key`` is an acceptable bridge ``Idempotency-Key`` (1-128 URL-safe characters)."""
    return isinstance(key, str) and BRIDGE_KEY_PATTERN.fullmatch(key) is not None


# The tool argument that carries a bridge write's identity for a client that cannot set a
# per-call header (stock Claude Code). A tool that already declares ``idempotency_key`` uses
# that argument instead; every other bridge write tool advertises this one as required.
BRIDGE_KEY_ARG = "nexus_invocation_key"
_OWN_KEY_ARG = "idempotency_key"
BRIDGE_KEY_HINT = (
    "Required: a fresh unique value (1-128 characters from A-Z a-z 0-9 . _ : ~ -) for each "
    "intentional call of this tool, even when every other argument is the same as an earlier "
    "call. Repeat the exact same value and arguments only to retry a call whose outcome you "
    "did not see."
)


def bridge_key_field(declared_fields: Iterable[str]) -> str:
    """The argument name a bridge write tool takes its identity from."""
    return _OWN_KEY_ARG if _OWN_KEY_ARG in set(declared_fields) else BRIDGE_KEY_ARG


def resolve_bridge_identity(
    header: str | None, arguments: dict[str, Any], field: str
) -> tuple[str, dict[str, Any]]:
    """The call's identity from the header and/or the declared argument, plus its arguments.

    Either source alone is enough; both must match exactly, because silently preferring one
    could attach a retry to the wrong slot. The returned arguments are the business arguments:
    the bridge-only argument is removed, and a header-only call to a tool that declares its own
    ``idempotency_key`` has the header value filled in so the tool's schema is satisfied.

    Raises:
        BridgeSlotError: ``IDEMPOTENCY_KEY_REQUIRED``, ``_INVALID`` or ``_CONFLICT``.
    """
    business = dict(arguments)
    from_arg = business.get(field)
    if header is not None and not valid_bridge_key(header):
        raise BridgeSlotError(
            f"IDEMPOTENCY_KEY_INVALID: the Idempotency-Key header is malformed. {BRIDGE_KEY_HINT}"
        )
    if field in business and not valid_bridge_key(from_arg):
        raise BridgeSlotError(
            f"IDEMPOTENCY_KEY_INVALID: `{field}` is malformed. {BRIDGE_KEY_HINT}"
        )
    if header is None and field not in business:
        raise BridgeSlotError(
            f"IDEMPOTENCY_KEY_REQUIRED: this write needs the `{field}` argument "
            f"(or an Idempotency-Key header). {BRIDGE_KEY_HINT}"
        )
    if header is not None and field in business and header != from_arg:
        raise BridgeSlotError(
            f"IDEMPOTENCY_KEY_CONFLICT: the Idempotency-Key header and `{field}` disagree; "
            "send one value, or the same value in both"
        )
    key = header if header is not None else from_arg
    if field == BRIDGE_KEY_ARG:
        business.pop(field, None)
    else:
        business[field] = key
    assert isinstance(key, str)
    return key, business


async def reserve_bridge_slot(
    company_id: uuid.UUID,
    turn_id: uuid.UUID,
    key: str | None,
    tool_name: str,
    arguments: Any,
) -> ToolSlot:
    """The durable slot of one inbound bridge write, allocated once per ``Idempotency-Key``.

    The first call with a key reserves the turn's next free ordinal; any retry, from another
    process or after a restart, returns the same slot. The primary key (one row per key) and
    the unique ordinal (one row per slot) are enforced by the database, so concurrent requests
    cannot share a slot whatever order they arrive in. A key reused for a different tool or
    different arguments is refused, and so is a missing or malformed key: a write with no
    identity is never dispatched. Company and turn come from the authenticated bridge
    credential, never from the client.

    Raises:
        BridgeSlotError: Missing or malformed key, or the key names a different call.
        EffectKeyError: The arguments have no canonical form.
    """
    from nexus import database

    if not valid_bridge_key(key):
        raise BridgeSlotError(
            "IDEMPOTENCY_KEY_REQUIRED: a write needs a bridge identity "
            "(1-128 characters from A-Z a-z 0-9 . _ : ~ -), unique per intended write"
        )
    digest = arguments_digest(arguments)
    async with database.tenant_session(company_id) as db:
        for _ in range(_BRIDGE_ATTEMPTS):
            row = (
                await db.execute(
                    select(ToolBridgeSlot).where(
                        ToolBridgeSlot.company_id == company_id,
                        ToolBridgeSlot.turn_id == turn_id,
                        ToolBridgeSlot.idempotency_key == key,
                    )
                )
            ).scalar_one_or_none()
            if row is not None:
                if row.tool_name != tool_name or row.arguments_digest != digest:
                    raise BridgeSlotError(
                        "IDEMPOTENCY_KEY_REUSED: this Idempotency-Key already names a "
                        "different call"
                    )
                return ToolSlot(-1, row.ordinal)
            ordinal = (
                await db.execute(
                    select(func.coalesce(func.max(ToolBridgeSlot.ordinal), -1) + 1).where(
                        ToolBridgeSlot.company_id == company_id,
                        ToolBridgeSlot.turn_id == turn_id,
                    )
                )
            ).scalar_one()
            try:
                async with db.begin_nested():
                    db.add(
                        ToolBridgeSlot(
                            company_id=company_id, turn_id=turn_id, idempotency_key=key,
                            ordinal=ordinal, tool_name=tool_name, arguments_digest=digest,
                        )
                    )
                    await db.flush()
            except IntegrityError:
                continue  # a concurrent request took this key or ordinal; look again
            await db.commit()
            return ToolSlot(-1, ordinal)
    raise BridgeSlotError("could not reserve a slot for this write; retry the request")


async def _commit_run(db: Any, run: Claim, grant_id: uuid.UUID | None) -> Claim:
    """Commit a ``run`` decision together with the grant use it depends on, or neither."""
    if grant_id is not None:
        from nexus.tools import governance_overlay

        if not await governance_overlay.consume_temp_grant(
            db, run.company_id, grant_id, run.key
        ):
            await db.rollback()
            return Claim(
                "denied", run.company_id, run.effect_class, key=run.key,
                reason="temporary access is no longer valid",
            )
    await db.commit()
    return run


async def _decide(db: Any, row: ToolEffect, requested: EffectClass, token: str) -> Claim:
    cid = row.company_id
    key = row.invocation_key
    strict = (
        EffectClass.NON_IDEMPOTENT_WRITE
        if EffectClass.NON_IDEMPOTENT_WRITE.value in (row.effect_class, requested.value)
        else EffectClass.IDEMPOTENT_WRITE
    )
    if row.status == "succeeded":
        await _audit(db, row, "replayed")
        return Claim("replay", cid, strict, row.id, stored=row.result, key=key)
    if row.status == "manual_recovery_required":
        return Claim(
            "blocked", cid, strict, row.id, key=key, reason="manual recovery required"
        )
    now = await _db_now(db)
    expired = row.lease_expires_at is None or row.lease_expires_at <= now
    if row.status == "executing" and not expired:
        return Claim(
            "busy", cid, strict, row.id, key=key, reason="another worker holds this call"
        )
    take = {
        "status": "executing",
        "claim_token": token,
        "lease_expires_at": now + timedelta(seconds=LEASE_SECONDS),
        "attempt_count": row.attempt_count + 1,
        "result": None,
        "error": None,
        "completed_at": None,
    }
    if row.status == "failed":
        # The tool proved it did nothing, so a retry cannot repeat an effect.
        won = (await db.execute(_cas(row, **take))).rowcount == 1
        return (
            Claim("run", cid, strict, row.id, token, key=key)
            if won
            else Claim("busy", cid, strict, row.id, key=key, reason="lost the claim race")
        )
    # ambiguous, or an executing claim whose lease ran out: the effect may have happened.
    came_from = row.status
    if strict is EffectClass.NON_IDEMPOTENT_WRITE:
        won = (
            await db.execute(_cas(row, status="manual_recovery_required", claim_token=None,
                                  lease_expires_at=None))
        ).rowcount == 1
        if won:
            await _audit(db, row, "manual_recovery_required", must=True, came_from=came_from)
        return Claim(
            "blocked", cid, strict, row.id, key=key, reason="manual recovery required"
        )
    won = (await db.execute(_cas(row, **take))).rowcount == 1
    if not won:
        return Claim("busy", cid, strict, row.id, key=key, reason="lost the claim race")
    await _audit(db, row, "retaken", must=True, came_from=came_from)
    return Claim("run", cid, strict, row.id, token, key=key)


async def settle(
    held: Claim, status: str, *, stored: dict[str, Any] | None = None, error: str | None = None
) -> bool:
    """Record the outcome of a call this claim started. Never raises.

    ``stored`` is the :func:`seal_result` envelope for a ``succeeded`` outcome. Only the claim
    holding the token can settle, so a holder whose row was taken over after its lease expired
    cannot overwrite the newer outcome. ``False`` means nothing changed; the row then stays
    ``executing`` and the next claim treats it as ambiguous.
    """
    from nexus import database

    if held.action != "run" or held.effect_id is None:
        return False
    if status == "succeeded" and stored is None:
        return False
    now = utcnow()
    values: dict[str, Any] = {
        "status": status,
        "claim_token": None,
        "lease_expires_at": None,
        "error": redact_text(error) if error else None,
        "updated_at": now,
        "completed_at": now,
    }
    if status == "succeeded":
        values["result"] = stored
    try:
        async with database.tenant_session(held.company_id) as db:
            done = await db.execute(
                update(ToolEffect)
                .where(
                    ToolEffect.id == held.effect_id,
                    ToolEffect.company_id == held.company_id,
                    ToolEffect.claim_token == held.token,
                    ToolEffect.status == "executing",
                )
                .values(**values)
            )
            if done.rowcount != 1:
                logger.warning("tool effect %s was not settled: claim lost", held.effect_id)
                return False
            if status == "ambiguous":
                row = await db.get(ToolEffect, held.effect_id)
                await _audit(db, row, "ambiguous")
            await db.commit()
            return True
    except Exception as exc:  # noqa: BLE001 - settling must never fail the tool call
        logger.error("could not settle tool effect %s: %s", held.effect_id, exc)
        return False


async def claim_notice(company_id: uuid.UUID, invocation_key: str) -> bool:
    """True exactly once per logical invocation: the caller that gets it may send the notice.

    The insert is the decision (the primary key has one winner), and it is made before the
    send, so a replay or a concurrent claim for the same slot never notifies again. If the
    database cannot be reached the answer is ``False``: a notice may be missed, never doubled.
    """
    from nexus import database

    try:
        async with database.tenant_session(company_id) as db:
            try:
                async with db.begin_nested():
                    db.add(ToolNotification(company_id=company_id, invocation_key=invocation_key))
                    await db.flush()
            except IntegrityError:
                return False
            await db.commit()
            return True
    except Exception as exc:  # noqa: BLE001 - a missed notice is safer than a repeated one
        logger.error("could not record tool notification %s: %s", invocation_key, exc)
        return False


async def resolve_manual_recovery(
    company_id: uuid.UUID,
    effect_id: uuid.UUID,
    outcome: Literal["applied", "not_applied"],
    *,
    actor: str,
    reason: str,
    note: str | None = None,
) -> dict[str, Any]:
    """Record an operator's decision about an ambiguous non-idempotent effect.

    ``applied`` settles the call as succeeded (a replay then returns the operator's note),
    ``not_applied`` as failed (the next call may run). The row, the actor and the reason are
    audited in the same transaction; if the audit cannot be written nothing changes.
    """
    from nexus import database

    if outcome not in ("applied", "not_applied"):
        raise ValueError("outcome must be 'applied' or 'not_applied'")
    if not actor.strip() or not reason.strip():
        raise ValueError("actor and reason are required")
    now = utcnow()
    async with database.tenant_session(company_id) as db:
        row = (
            await db.execute(
                select(ToolEffect)
                .where(ToolEffect.company_id == company_id, ToolEffect.id == effect_id)
                .with_for_update()
            )
        ).scalar_one_or_none()
        if row is None:
            raise LookupError("tool effect not found")
        if row.status not in ("ambiguous", "manual_recovery_required"):
            raise EffectStateError(f"tool effect is {row.status}, not awaiting recovery")
        applied = outcome == "applied"
        values: dict[str, Any] = {
            "status": "succeeded" if applied else "failed",
            "result": (
                {"kind": "json", "value": {"manual_recovery": "applied",
                                           "note": redact_text(note or "")}}
                if applied else None
            ),
            "error": None if applied else "manual recovery: effect confirmed not applied",
            "resolved_by": actor[:100],
            "resolved_at": now,
            "resolution_reason": redact_text(reason),
            "completed_at": now,
        }
        done = await db.execute(_cas(row, **values))
        if done.rowcount != 1:
            raise EffectStateError("tool effect changed while resolving")
        await _audit(
            db, row, "manual_recovery_resolved", actor_type="user", actor_id=actor[:100],
            must=True, outcome=outcome, from_status=row.status,
        )
        await db.commit()
        return {"id": str(row.id), "status": values["status"], "outcome": outcome}


def _encode_cursor(created_at: datetime, effect_id: uuid.UUID) -> str:
    raw = json.dumps([created_at.isoformat(), str(effect_id)], separators=(",", ":"))
    return base64.urlsafe_b64encode(raw.encode()).decode().rstrip("=")


def _decode_cursor(cursor: str) -> tuple[datetime, uuid.UUID]:
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        stamp, ident = json.loads(base64.urlsafe_b64decode(padded.encode()))
        return datetime.fromisoformat(stamp), uuid.UUID(ident)
    except (ValueError, TypeError, binascii.Error) as exc:
        raise ValueError("invalid cursor") from exc


async def list_open(
    company_id: uuid.UUID, limit: int = 100, after: str | None = None
) -> dict[str, Any]:
    """One page of effects awaiting an operator decision, oldest first.

    Identifiers and states only. ``next_cursor`` is ``None`` on the last page; pass it back as
    ``after`` for the next. The cursor is keyset based, so a row resolved between two pages
    never shifts what the next page contains.
    """
    from nexus import database

    limit = max(1, min(limit, 500))
    query = select(ToolEffect).where(
        ToolEffect.company_id == company_id,
        ToolEffect.status.in_(("ambiguous", "manual_recovery_required")),
    )
    if after is not None:
        seen_at, seen_id = _decode_cursor(after)
        query = query.where(
            or_(
                ToolEffect.created_at > seen_at,
                sa_and(ToolEffect.created_at == seen_at, ToolEffect.id > seen_id),
            )
        )
    async with database.tenant_session(company_id) as db:
        rows = list(
            (
                await db.execute(
                    query.order_by(ToolEffect.created_at, ToolEffect.id).limit(limit + 1)
                )
            ).scalars()
        )
    page, more = rows[:limit], len(rows) > limit
    return {
        "items": [
            {
                "id": str(r.id),
                "turn_id": str(r.turn_id),
                "round_index": r.round_index,
                "invocation_index": r.invocation_index,
                "tool_name": r.tool_name,
                "effect_class": r.effect_class,
                "status": r.status,
                "attempt_count": r.attempt_count,
                "arguments_digest": r.arguments_digest,
                "created_at": r.created_at.isoformat(),
            }
            for r in page
        ],
        "next_cursor": _encode_cursor(page[-1].created_at, page[-1].id) if more else None,
    }
