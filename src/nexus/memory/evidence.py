"""The one path that creates ``memory_evidence`` rows, and the idempotent runner for them.

Evidence says why a human administrator may promote a memory's trust. It is never a
claim the caller makes: the caller names a *source* (a chat turn, a tool invocation, a
task attempt) or attests as themselves, and the server finds the source in the caller's
company, derives the grade and a digest of the source's qualifying state, and stamps the
actor. Nothing the caller sends can set trust, grade, digest, company or actor.

Grades (policy ``memory-evidence-v1``): ``none`` records provenance and qualifies for
nothing; ``assert`` supports untrusted -> asserted; ``verify`` supports asserted ->
verified. Anything ambiguous is ``none``:

- chat_turn: provenance only. A turn proves who said what, never that it is true.
- tool_invocation: ``assert`` only when the run succeeded, a person approved it and
  access control allowed it. A tool running proves the tool ran, not that its output
  is true, so it never verifies.
- task_attempt: ``verify`` only when the deterministic verifier recorded a passed
  completion for the attempt (status completed, reason ``goal``, every check passed).
- human_attestation: the attesting administrator, with a reason code from a fixed list.

Evidence is re-derived and re-compared at transition time (``requalify``), with the
source row locked on PostgreSQL, so a source that changed after attachment is stale.
The caller owns the transaction; nothing here commits.
"""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from nexus.memory.ingest import MemoryContext, MemoryOpError, begin_write, get_in_company
from nexus.models.chat_turn import ChatTurn
from nexus.models.memory import LIVE_STATUSES
from nexus.models.memory_evidence import (
    POLICY_VERSION,
    MemoryEvidence,
    MemoryOperation,
)
from nexus.models.task_attempt import TaskAttempt
from nexus.models.tool_invocation import ToolInvocation

# reason code -> grade. A person vouching; only the second may verify.
ATTESTATION_REASONS = {
    "reviewed_by_admin": "assert",
    "independently_verified_by_admin": "verify",
}
GRADE_RANK = {"none": 0, "assert": 1, "verify": 2}
_SOURCE_TYPE = {
    "human_attestation": "user",
    "chat_turn": "chat_turn",
    "tool_invocation": "tool_invocation",
    "task_attempt": "task_attempt",
}
_KEY = re.compile(r"^[A-Za-z0-9._:-]{8,128}$")


@dataclass(frozen=True)
class Qualification:
    grade: str
    digest: str


def digest_of(parts: dict[str, Any]) -> str:
    """sha256 of canonical JSON. Inputs are ids and state flags, never content."""
    raw = json.dumps(parts, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(raw.encode()).hexdigest()


def _error(code: str, message: str, status: int) -> MemoryOpError:
    return MemoryOpError(code, message, status)


def _not_found() -> MemoryOpError:
    return _error("MEMORY_NOT_FOUND", "Memory not found", 404)


def _source_not_found() -> MemoryOpError:
    return _error("MEMORY_EVIDENCE_SOURCE_NOT_FOUND", "Evidence source not found", 404)


def validate_key(key: str | None) -> str:
    if not key:
        raise _error("IDEMPOTENCY_KEY_REQUIRED", "Idempotency-Key header is required", 422)
    if not _KEY.match(key):
        raise _error(
            "IDEMPOTENCY_KEY_INVALID",
            "Idempotency-Key must be 8-128 characters of letters, digits, . _ : -",
            422,
        )
    return key


def request_digest(
    operation: str, memory_id: uuid.UUID, actor: str, body: dict[str, Any]
) -> str:
    return digest_of({"op": operation, "memory": str(memory_id), "actor": actor, "body": body})


def _actor_user_id(actor: str) -> uuid.UUID | None:
    prefix, _, rest = actor.partition(":")
    if prefix != "user":
        return None
    try:
        return uuid.UUID(rest)
    except ValueError:
        return None


async def _is_active_admin(db: Any, company_id: uuid.UUID, user_id: uuid.UUID) -> bool:
    from nexus.auth.users import get_membership
    from nexus.models.auth import normalize_role
    from nexus.models.user_profile import UserProfile

    user = await db.get(UserProfile, user_id)
    if user is None or not user.is_active:
        return False
    membership = await get_membership(db, user_id, company_id)
    return membership is not None and normalize_role(membership.role) == "admin"


async def require_human_admin(db: Any, ctx: MemoryContext) -> uuid.UUID:
    """The acting user, re-read from the database as an active administrator of the company.

    The route already applied ``can_write`` to the request's principal; this checks the
    same facts again where the write happens, so a service caller cannot skip them and an
    actor that is not a person (agent, run, API key, development fallback) is refused.
    """
    user_id = _actor_user_id(ctx.actor)
    if user_id is None or not await _is_active_admin(db, ctx.company_id, user_id):
        raise _error(
            "MEMORY_EVIDENCE_FORBIDDEN",
            "Only a human company administrator may manage memory evidence",
            403,
        )
    return user_id


async def _one(db: Any, model: Any, company_id: uuid.UUID, ref: str, lock: bool) -> Any | None:
    try:
        row_id = uuid.UUID(ref)
    except ValueError:
        return None
    stmt = select(model).where(model.id == row_id, model.company_id == company_id)
    if lock:
        stmt = stmt.with_for_update()
    return (await db.execute(stmt.execution_options(populate_existing=True))).scalar_one_or_none()


def _verification_passed(attempt: TaskAttempt) -> bool:
    v = attempt.verification
    if not isinstance(v, dict) or v.get("passed") is not True or v.get("outcome") != "completed":
        return False
    checks = v.get("checks")
    return (
        attempt.status == "completed"
        and attempt.completion_reason == "goal"
        and not attempt.error_code
        and isinstance(checks, list)
        and bool(checks)
        and all(isinstance(c, dict) and c.get("passed") is True for c in checks)
    )


async def qualify(
    db: Any,
    company_id: uuid.UUID,
    source_type: str,
    source_id: str,
    reason_code: str = "",
    *,
    lock: bool = False,
) -> Qualification | None:
    """Grade and digest of one source in ``company_id``; None when it is not there."""
    cid = str(company_id)
    if source_type == "user":
        try:
            user_id = uuid.UUID(source_id)
        except ValueError:
            return None
        if reason_code not in ATTESTATION_REASONS or not await _is_active_admin(
            db, company_id, user_id
        ):
            return None
        grade = ATTESTATION_REASONS[reason_code]
        return Qualification(
            grade, digest_of({"user": source_id, "company": cid, "reason": reason_code})
        )
    if source_type == "chat_turn":
        turn = await _one(db, ChatTurn, company_id, source_id, lock)
        if turn is None:
            return None
        return Qualification(
            "none",
            digest_of({"id": str(turn.id), "company": cid, "session": str(turn.session_id)}),
        )
    if source_type == "tool_invocation":
        run = await _one(db, ToolInvocation, company_id, source_id, lock)
        if run is None:
            return None
        ok = (
            run.status == "success"
            and run.approval_state == "approved"
            and run.authorization == "allowed"
            and run.completed_at is not None
        )
        return Qualification(
            "assert" if ok else "none",
            digest_of(
                {
                    "id": str(run.id), "company": cid, "tool": run.tool_name,
                    "status": run.status, "approval": run.approval_state,
                    "authorization": run.authorization,
                    "completed_at": run.completed_at,
                }
            ),
        )
    if source_type == "task_attempt":
        attempt = await _one(db, TaskAttempt, company_id, source_id, lock)
        if attempt is None:
            return None
        return Qualification(
            "verify" if _verification_passed(attempt) else "none",
            digest_of(
                {
                    "id": str(attempt.id), "company": cid, "task": str(attempt.task_id),
                    "status": attempt.status, "reason": attempt.completion_reason,
                    "error_code": attempt.error_code,
                    "verification": digest_of(attempt.verification or {}),
                }
            ),
        )
    return None


async def requalify(db: Any, company_id: uuid.UUID, evidence: MemoryEvidence) -> str:
    """The evidence's grade *now*; refuses evidence whose source changed or went away."""
    now = await qualify(
        db, company_id, evidence.source_type, evidence.source_id, evidence.reason_code, lock=True
    )
    if now is None or now.digest != evidence.source_digest:
        raise _error(
            "MEMORY_EVIDENCE_STALE", "The evidence source changed since it was attached", 409
        )
    return now.grade


async def load_evidence(
    db: Any, company_id: uuid.UUID, memory_id: uuid.UUID, evidence_id: uuid.UUID
) -> MemoryEvidence:
    row = (
        await db.execute(
            select(MemoryEvidence).where(
                MemoryEvidence.id == evidence_id,
                MemoryEvidence.company_id == company_id,
                MemoryEvidence.memory_id == memory_id,
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise _error("MEMORY_EVIDENCE_NOT_FOUND", "Evidence not found", 404)
    return row


def evidence_view(row: MemoryEvidence) -> dict[str, Any]:
    """The stable, content-free shape of a row; also what the ledger stores for an attach."""
    return {
        "evidence_id": str(row.id),
        "memory_id": str(row.memory_id),
        "evidence_kind": row.evidence_kind,
        "source_type": row.source_type,
        "source_id": row.source_id,
        "reason_code": row.reason_code or None,
        "grade": row.grade,
        "policy_version": row.policy_version,
        "created_by": row.created_by,
        "created_at": row.created_at.isoformat(),
    }


async def attach_evidence(
    db: Any,
    ctx: MemoryContext,
    memory_id: uuid.UUID,
    *,
    evidence_kind: str,
    source_id: str | None,
    reason_code: str | None,
    idempotency_key: str,
) -> dict[str, Any]:
    """Record one piece of evidence for an open memory; returns its view."""
    user_id = await require_human_admin(db, ctx)
    if evidence_kind not in _SOURCE_TYPE:
        raise _error("MEMORY_EVIDENCE_INVALID", "Unknown evidence kind", 422)
    source_type = _SOURCE_TYPE[evidence_kind]
    if evidence_kind == "human_attestation":
        # The attester is the caller, never a name the caller supplies.
        if source_id is not None or reason_code not in ATTESTATION_REASONS:
            raise _error(
                "MEMORY_EVIDENCE_INVALID",
                "An attestation takes a reason_code from the allowed list and no source_id",
                422,
            )
        source_id, reason = str(user_id), reason_code
    else:
        if not source_id or reason_code:
            raise _error(
                "MEMORY_EVIDENCE_INVALID",
                "This evidence kind takes a source_id and no reason_code",
                422,
            )
        reason = ""
    await begin_write(db)
    memory = await get_in_company(db, ctx.company_id, memory_id)
    if memory is None:
        raise _not_found()
    if memory.status not in LIVE_STATUSES:
        raise _error(
            "MEMORY_INVALID_TRANSITION", f"A {memory.status} memory takes no evidence", 409
        )
    found = await qualify(db, ctx.company_id, source_type, source_id, reason)
    if found is None:
        raise _source_not_found()
    duplicate = (
        await db.execute(
            select(MemoryEvidence.id).where(
                MemoryEvidence.company_id == ctx.company_id,
                MemoryEvidence.memory_id == memory_id,
                MemoryEvidence.source_type == source_type,
                MemoryEvidence.source_id == source_id,
                MemoryEvidence.reason_code == reason,
            )
        )
    ).first()
    if duplicate is not None:
        raise _error("MEMORY_EVIDENCE_DUPLICATE", "This evidence is already attached", 409)
    row = MemoryEvidence(
        company_id=ctx.company_id,
        memory_id=memory_id,
        evidence_kind=evidence_kind,
        source_type=source_type,
        source_id=source_id,
        reason_code=reason,
        grade=found.grade,
        source_digest=found.digest,
        policy_version=POLICY_VERSION,
        idempotency_key=idempotency_key,
        created_by=ctx.actor[:100],
    )
    db.add(row)
    await db.flush()

    from nexus.services import manager_service as ms

    await ms.audit(
        db, ctx.company_id, "memory.evidence_attached", ctx.actor, "memory", memory_id,
        evidence_id=str(row.id), evidence_kind=evidence_kind, source_type=source_type,
        source_id=source_id, reason_code=reason or None, grade=row.grade,
        policy_version=POLICY_VERSION, idempotency_key=idempotency_key,
    )
    return evidence_view(row)


async def list_evidence(
    db: Any, ctx: MemoryContext, memory_id: uuid.UUID
) -> list[dict[str, Any]]:
    """Every evidence row of one memory, oldest first. The read is audited (ids only)."""
    await require_human_admin(db, ctx)
    if await get_in_company(db, ctx.company_id, memory_id) is None:
        raise _not_found()
    rows = (
        await db.execute(
            select(MemoryEvidence)
            .where(
                MemoryEvidence.company_id == ctx.company_id,
                MemoryEvidence.memory_id == memory_id,
            )
            .order_by(MemoryEvidence.created_at, MemoryEvidence.id)
        )
    ).scalars().all()

    from nexus.services import manager_service as ms

    await ms.audit(
        db, ctx.company_id, "memory.evidence_reviewed", ctx.actor, "memory", memory_id,
        count=len(rows), evidence_ids=[str(r.id) for r in rows],
    )
    return [evidence_view(r) for r in rows]


async def _ledger(db: Any, company_id: uuid.UUID, key: str) -> MemoryOperation | None:
    return (
        await db.execute(
            select(MemoryOperation)
            .where(MemoryOperation.company_id == company_id, MemoryOperation.idempotency_key == key)
            .execution_options(populate_existing=True)
        )
    ).scalar_one_or_none()


def _replay(
    row: MemoryOperation, operation: str, memory_id: uuid.UUID, digest: str
) -> dict[str, Any]:
    if row.request_digest != digest or row.operation != operation or row.memory_id != memory_id:
        raise _error(
            "MEMORY_IDEMPOTENCY_CONFLICT",
            "This Idempotency-Key was already used for a different request",
            409,
        )
    return dict(row.result)


async def run_once(
    db: Any,
    ctx: MemoryContext,
    *,
    key: str,
    operation: str,
    memory_id: uuid.UUID,
    digest: str,
    effect: Callable[[], Awaitable[dict[str, Any]]],
) -> tuple[dict[str, Any], bool]:
    """Run ``effect`` once per (company, key); returns (result, replayed).

    The effect and the ledger row share one savepoint, so both happen or neither. Two
    identical requests race to the ledger's unique key: the loser's savepoint rolls back
    and it returns the winner's stored result. The same key with another request is a
    409, and a lost race to a conflicting transition (also a 409) is re-checked against
    the ledger first, because a winner with the same key makes it a replay, not a conflict.
    """
    await begin_write(db)
    existing = await _ledger(db, ctx.company_id, key)
    if existing is not None:
        return _replay(existing, operation, memory_id, digest), True
    try:
        async with db.begin_nested():
            result = await effect()
            db.add(
                MemoryOperation(
                    company_id=ctx.company_id,
                    memory_id=memory_id,
                    operation=operation,
                    idempotency_key=key,
                    request_digest=digest,
                    actor=ctx.actor[:100],
                    result=result,
                )
            )
            await db.flush()
    except (IntegrityError, MemoryOpError) as exc:
        if isinstance(exc, MemoryOpError) and exc.status_code != 409:
            raise
        winner = await _ledger(db, ctx.company_id, key)
        if winner is not None:
            return _replay(winner, operation, memory_id, digest), True
        if isinstance(exc, MemoryOpError):
            raise
        raise _error("MEMORY_EVIDENCE_DUPLICATE", "This evidence is already attached", 409) from exc
    return result, False
