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

Logical key: ``sha256(json([KEY_VERSION, company_id, turn_id, tool_name, canonical_args]))``
with ``canonical_args`` the arguments as JSON with sorted keys, ``(",", ":")`` separators,
ASCII escapes and no NaN. Arguments that are not plain JSON have no canonical form and are
refused for a write. The model's own tool-call ids are not part of the key (a rerun
regenerates them), so two identical calls in one turn are one logical call and the second
replays the first.

A call without a turn id (a plain REST request) is not ledgered: nothing requeues it.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import secrets
import uuid
from dataclasses import dataclass
from datetime import timedelta
from enum import StrEnum
from typing import Any, Literal

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError

from nexus.models._time import utcnow
from nexus.models.tool_effect import ToolEffect

logger = logging.getLogger(__name__)

KEY_VERSION = "nexus.tool-effect.v1"
# A live holder must settle within this window. There is no heartbeat: a call that runs
# longer is treated as interrupted by a later claim (a non-idempotent one then needs an
# operator, an idempotent one is retried).
LEASE_SECONDS = 900
MAX_RESULT_BYTES = 16_384
MAX_TEXT_CHARS = 500

Action = Literal["run", "replay", "busy", "blocked"]


class EffectClass(StrEnum):
    READ_ONLY = "read_only"
    IDEMPOTENT_WRITE = "idempotent_write"
    NON_IDEMPOTENT_WRITE = "non_idempotent_write"


class EffectKeyError(ValueError):
    """The arguments have no canonical form, so the call has no stable identity."""


class EffectStateError(RuntimeError):
    """A manual-recovery request does not match what the ledger holds."""


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


def invocation_key(
    company_id: uuid.UUID, turn_id: uuid.UUID, tool_name: str, arguments: Any
) -> tuple[str, str]:
    """Return ``(invocation_key, arguments_digest)`` for one logical call."""
    canon = canonical_arguments(arguments)
    parts = [KEY_VERSION, str(company_id), str(turn_id), tool_name, canon]
    return _sha256(json.dumps(parts, separators=(",", ":"))), _sha256(canon)


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


# --- bounded, scrubbed result and error data ------------------------------------------------


# Token shapes the guardrail patterns do not cover. Free text cannot be proven clean, so this is
# a second net; raised exceptions are stored by type only (see ``guarded_call``).
_TOKEN_PATTERNS = (
    r"\bsk-[A-Za-z0-9_-]{8,}",
    r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]{8,}",
    r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]*",
    r"(?i)\b(api[_-]?key|token|secret|authorization)\b\s*[:=]\s*\S+",
)


def redact_text(text: Any, limit: int = MAX_TEXT_CHARS) -> str:
    """Mask secret-looking text (guardrail patterns plus token shapes), then cap the length."""
    from nexus.tools.factory import BLOCKED_PATTERNS

    out = str(text)
    for pattern in (*BLOCKED_PATTERNS, *_TOKEN_PATTERNS):
        out = re.sub(pattern, "[redacted]", out)
    return out[:limit]


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


def encode_result(result: Any) -> dict[str, Any]:
    """Bounded, scrubbed, JSON-safe form of a tool result.

    Keys that look secret are masked (the same rule as the invocation audit row). A result
    over :data:`MAX_RESULT_BYTES` is not stored; only its size and digest are, and a replay
    says so instead of returning the data.
    """
    from nexus.tools.executor import _scrub_value

    kind, value = _flatten(result)
    value = _scrub_value(json.loads(json.dumps(value, default=str)))
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"))
    size = len(raw.encode())
    if size > MAX_RESULT_BYTES:
        return {"kind": kind, "omitted": {"bytes": size, "sha256": _sha256(raw)}}
    return {"kind": kind, "value": value}


def decode_result(stored: dict[str, Any]) -> Any:
    """Rebuild the result object a caller expects from :func:`encode_result` output."""
    from nexus.nodes.executor import ExecutorResult
    from nexus.tools.mcp_client import MCPResult

    kind = stored["kind"]
    omitted = stored.get("omitted")
    note = {"replayed": True, "result_omitted": True, **omitted} if omitted else None
    value = stored.get("value") or {}
    if kind == "executor_result":
        if note is not None:
            return ExecutorResult(success=True, outputs=note)
        return ExecutorResult(
            success=value["success"], outputs=value["outputs"], error=value["error"]
        )
    if kind == "mcp_result":
        if note is not None:
            return MCPResult(content=note)
        return MCPResult(
            content=value["content"], is_error=value["is_error"], metadata=value["metadata"] or {}
        )
    if kind == "json":
        return note if note is not None else stored["value"]
    raise ValueError(f"unknown stored result kind {kind!r}")


def outcome_of(result: Any) -> tuple[str, str | None]:
    """``(status, error)`` for a result the tool returned rather than raised.

    ``ambiguous`` only when the tool says it cannot tell whether it acted (a timeout or an
    unexpected crash); a failure the tool reports itself is a definite no-effect ``failed``.
    """
    if getattr(result, "effect_unknown", False):
        return "ambiguous", getattr(result, "error", None) or "outcome unknown"
    if getattr(result, "is_error", False):
        return "failed", str(getattr(result, "content", ""))
    if getattr(result, "success", True) is False:
        return "failed", getattr(result, "error", None)
    return "succeeded", None


def outcome_of_exception(exc: BaseException) -> str:
    """A validation refusal (``ValueError``, HTTP 4xx) did nothing; everything else is unknown.

    Cancellation, timeouts, connection errors and server errors all leave the effect unknown.
    """
    if isinstance(exc, ValueError):
        return "failed"
    code = getattr(exc, "status_code", None)
    if isinstance(exc, Exception) and isinstance(code, int) and 400 <= code < 500:
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


async def claim(
    company_id: uuid.UUID,
    turn_id: uuid.UUID,
    tool_name: str,
    effect_class: EffectClass,
    arguments: Any,
) -> Claim:
    """Reserve one logical call, or say why it must not run now.

    Exactly one caller gets ``run`` for a given key at a time: the first INSERT wins on the
    unique key, and every later takeover is one compare-and-set UPDATE. Raises
    :class:`EffectKeyError` for non-canonical arguments and propagates database errors; the
    caller must then refuse the call rather than run it unrecorded.
    """
    from nexus import database

    key, digest = invocation_key(company_id, turn_id, tool_name, arguments)
    token = secrets.token_hex(16)
    lease = utcnow() + timedelta(seconds=LEASE_SECONDS)
    new = ToolEffect(
        company_id=company_id,
        turn_id=turn_id,
        tool_name=tool_name,
        effect_class=effect_class.value,
        invocation_key=key,
        arguments_digest=digest,
        claim_token=token,
        lease_expires_at=lease,
    )
    async with database.tenant_session(company_id) as db:
        try:
            async with db.begin_nested():
                db.add(new)
                await db.flush()
        except IntegrityError:
            pass
        else:
            await db.commit()
            return Claim("run", company_id, effect_class, new.id, token)
        row = (
            await db.execute(
                select(ToolEffect)
                .where(ToolEffect.company_id == company_id, ToolEffect.invocation_key == key)
                .with_for_update()
            )
        ).scalar_one()
        decision = await _decide(db, row, effect_class, token, lease)
        await db.commit()
        return decision


async def _decide(
    db: Any, row: ToolEffect, requested: EffectClass, token: str, lease: Any
) -> Claim:
    cid = row.company_id
    strict = (
        EffectClass.NON_IDEMPOTENT_WRITE
        if EffectClass.NON_IDEMPOTENT_WRITE.value in (row.effect_class, requested.value)
        else EffectClass.IDEMPOTENT_WRITE
    )
    if row.status == "succeeded":
        await _audit(db, row, "replayed")
        return Claim("replay", cid, strict, row.id, stored=row.result)
    if row.status == "manual_recovery_required":
        return Claim("blocked", cid, strict, row.id, reason="manual recovery required")
    expired = row.lease_expires_at is None or row.lease_expires_at <= utcnow()
    if row.status == "executing" and not expired:
        return Claim("busy", cid, strict, row.id, reason="another worker holds this call")
    take = {
        "status": "executing",
        "claim_token": token,
        "lease_expires_at": lease,
        "attempt_count": row.attempt_count + 1,
        "result": None,
        "error": None,
        "completed_at": None,
    }
    if row.status == "failed":
        # The tool reported that it did nothing, so a retry cannot repeat an effect.
        won = (await db.execute(_cas(row, **take))).rowcount == 1
        return (
            Claim("run", cid, strict, row.id, token)
            if won
            else Claim("busy", cid, strict, row.id, reason="lost the claim race")
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
        return Claim("blocked", cid, strict, row.id, reason="manual recovery required")
    won = (await db.execute(_cas(row, **take))).rowcount == 1
    if not won:
        return Claim("busy", cid, strict, row.id, reason="lost the claim race")
    await _audit(db, row, "retaken", must=True, came_from=came_from)
    return Claim("run", cid, strict, row.id, token)


async def settle(
    held: Claim, status: str, *, result: Any = None, error: str | None = None
) -> bool:
    """Record the outcome of a call this claim started. Never raises.

    Only the claim holding the token can settle, so a holder whose row was taken over after
    its lease expired cannot overwrite the newer outcome. ``False`` means nothing changed;
    the row then stays ``executing`` and the next claim treats it as ambiguous.
    """
    from nexus import database

    if held.action != "run" or held.effect_id is None:
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
    try:
        if status == "succeeded":
            values["result"] = encode_result(result)
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


async def list_open(company_id: uuid.UUID, limit: int = 100) -> list[dict[str, Any]]:
    """Effects awaiting an operator decision, oldest first. Identifiers and states only."""
    from nexus import database

    async with database.tenant_session(company_id) as db:
        rows = (
            await db.execute(
                select(ToolEffect)
                .where(
                    ToolEffect.company_id == company_id,
                    ToolEffect.status.in_(("ambiguous", "manual_recovery_required")),
                )
                .order_by(ToolEffect.created_at, ToolEffect.id)
                .limit(limit)
            )
        ).scalars()
        return [
            {
                "id": str(r.id),
                "turn_id": str(r.turn_id),
                "tool_name": r.tool_name,
                "effect_class": r.effect_class,
                "status": r.status,
                "attempt_count": r.attempt_count,
                "arguments_digest": r.arguments_digest,
                "created_at": r.created_at.isoformat(),
            }
            for r in rows
        ]
