"""Lifecycle and trust transitions for ``memory_records``.

Nothing here deletes a row or edits content or provenance. Each transition is a
tenant-scoped conditional UPDATE (``WHERE company_id AND id AND status = <observed>``)
that touches only the lifecycle columns, so two racing callers resolve
deterministically: one wins, the other re-reads and either sees its own target
state (idempotent success) or a stable conflict error. The caller commits.

Status transitions:
    accept:    candidate          -> active           (status only; trust unchanged)
    archive:   candidate | active -> archived
    reject:    candidate          -> rejected
    supersede: candidate | active -> superseded   (plus a new successor row)
Trust transitions (an active memory, one human administrator, qualifying evidence that is
re-derived here, never a caller's claim; there is no downgrade):
    assert:    untrusted -> asserted   needs evidence graded ``assert`` or ``verify``
    verify:    asserted  -> verified   needs evidence graded ``verify``
archive, reject and supersede repeat as a no-op. accept, assert and verify do not: the
repeat is the 409 ``MEMORY_INVALID_TRANSITION``, and a retry of one request is made
replayable by its Idempotency-Key (``nexus.memory.evidence.run_once``). A memory is
promoted in one step at a time: trust is never changed together with status.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import update

from nexus.memory import evidence
from nexus.memory.ingest import (
    IngestResult,
    MemoryContext,
    MemoryInput,
    MemoryOpError,
    Origin,
    begin_write,
    get_in_company,
    ingest_memory,
)
from nexus.models._time import utcnow
from nexus.models.memory import LIVE_STATUSES, MemoryRecord

_FROM = {
    "active": ("candidate",),
    "archived": LIVE_STATUSES,
    "rejected": ("candidate",),
    "superseded": LIVE_STATUSES,
}
_ACTION = {
    "active": "memory.accepted",
    "archived": "memory.archived",
    "rejected": "memory.rejected",
    "superseded": "memory.superseded",
}


def _refusal(current: MemoryRecord, target: str) -> MemoryOpError:
    if current.status == "archived":
        return MemoryOpError("MEMORY_ALREADY_ARCHIVED", "Memory is already archived", 409)
    return MemoryOpError(
        "MEMORY_INVALID_TRANSITION",
        f"Memory cannot move from {current.status} to {target}",
        409,
    )


async def _transition(
    db: Any,
    ctx: MemoryContext,
    memory_id: uuid.UUID,
    target: str,
    *,
    reason: str | None = None,
    extra: dict[str, Any] | None = None,
    tier: str | None = None,
    audit_extra: dict[str, Any] | None = None,
) -> tuple[MemoryRecord, bool]:
    """Move one row to ``target``.

    Returns (row, changed); ``changed`` is False for an idempotent repeat.
    """
    await begin_write(db)
    record = await get_in_company(db, ctx.company_id, memory_id)
    if record is None:
        raise MemoryOpError("MEMORY_NOT_FOUND", "Memory not found", 404)
    if record.status == target:
        return record, False
    if record.status not in _FROM[target]:
        raise _refusal(record, target)

    now = utcnow()
    values: dict[str, Any] = {
        "status": target,
        "lifecycle_changed_at": now,
        "lifecycle_changed_by": ctx.actor[:100],
        "updated_at": now,
    }
    if tier is not None:
        values["tier"] = tier
    if extra:
        values["record_metadata"] = {**(record.record_metadata or {}), **extra}
    won = await db.execute(
        update(MemoryRecord)
        .where(
            MemoryRecord.company_id == ctx.company_id,
            MemoryRecord.id == memory_id,
            MemoryRecord.status == record.status,
        )
        .values(**values)
        .execution_options(synchronize_session=False)
    )
    fresh = await get_in_company(db, ctx.company_id, memory_id)
    if won.rowcount != 1:
        # Lost the race: judge the winner's state, not the stale read.
        if fresh is not None and fresh.status == target:
            return fresh, False
        raise _refusal(fresh, target) if fresh is not None else MemoryOpError(
            "MEMORY_NOT_FOUND", "Memory not found", 404
        )

    from nexus.services import manager_service as ms

    await ms.audit(
        db, ctx.company_id, _ACTION[target], ctx.actor, "memory", memory_id,
        from_status=record.status, to_status=target, reason=(reason or "")[:200] or None,
        **(audit_extra or {}),
    )
    return fresh, True


async def archive_memory(
    db: Any,
    ctx: MemoryContext,
    memory_id: uuid.UUID,
    *,
    reason: str | None = None,
    extra_metadata: dict[str, Any] | None = None,
    tier: str | None = None,
) -> MemoryRecord:
    """Retire a memory without deleting it. Idempotent."""
    record, _ = await _transition(
        db, ctx, memory_id, "archived", reason=reason, extra=extra_metadata, tier=tier
    )
    return record


async def reject_memory(
    db: Any, ctx: MemoryContext, memory_id: uuid.UUID, *, reason: str | None = None
) -> MemoryRecord:
    """Refuse a candidate. Only candidates can be rejected. Idempotent."""
    record, _ = await _transition(db, ctx, memory_id, "rejected", reason=reason)
    return record


async def supersede_memory(
    db: Any,
    ctx: MemoryContext,
    old_id: uuid.UUID,
    new: MemoryInput,
    origin: Origin,
    *,
    old_extra_metadata: dict[str, Any] | None = None,
) -> IngestResult:
    """Append ``new`` as the successor of ``old_id`` and mark the old row superseded.

    The successor is inserted and the old row closed in one savepoint, so either
    both happen or neither. Repeating the same call returns the same successor;
    superseding a row that another record already replaced is a conflict.
    """
    await begin_write(db)
    old = await get_in_company(db, ctx.company_id, old_id)
    if old is None:
        raise MemoryOpError("MEMORY_NOT_FOUND", "Memory not found", 404)
    if old.status not in (*_FROM["superseded"], "superseded"):
        raise _refusal(old, "superseded")

    # A deterministic source makes a retry of the same correction produce the same key.
    new.supersedes_id = old_id
    if new.source_id is None:
        new.source_type, new.source_id = "memory_record", str(old_id)
        new.extractor_version = new.extractor_version or "supersede-v1"
    try:
        async with db.begin_nested():
            result = await ingest_memory(db, ctx, new, origin)
            if not result.created:
                if result.record.supersedes_id == old_id:
                    return result  # identical repeat
                raise _conflict()
            _, closed = await _transition(
                db, ctx, old_id, "superseded", reason=f"superseded by {result.record.id}",
                extra={"superseded_by": str(result.record.id), **(old_extra_metadata or {})},
            )
            if not closed:
                # Someone else closed it first (or it was already superseded): our
                # successor must not survive, so roll the savepoint back.
                raise _conflict()
    except MemoryOpError as exc:
        if exc.code == "MEMORY_INVALID_TRANSITION" or exc.code == "MEMORY_ALREADY_ARCHIVED":
            # Another writer closed it while we appended; the savepoint already rolled back.
            raise _conflict() from exc
        raise
    return result


async def accept_candidate(
    db: Any, ctx: MemoryContext, memory_id: uuid.UUID, *, idempotency_key: str | None = None
) -> MemoryRecord:
    """candidate -> active, by a human administrator. Status only: trust is untouched.

    Active makes the memory eligible for prompts; it says nothing about whether it is true.
    """
    await evidence.require_human_admin(db, ctx)
    record, changed = await _transition(
        db, ctx, memory_id, "active", audit_extra={"idempotency_key": idempotency_key}
    )
    if not changed:
        raise _refusal(record, "active")
    return record


_TRUST_STEPS = {
    # target -> (required current trust, minimum evidence grade, audit action)
    "asserted": ("untrusted", "assert", "memory.trust_asserted"),
    "verified": ("asserted", "verify", "memory.trust_verified"),
}


async def _promote_trust(
    db: Any,
    ctx: MemoryContext,
    memory_id: uuid.UUID,
    evidence_id: uuid.UUID,
    target: str,
    idempotency_key: str | None,
) -> MemoryRecord:
    frm, need, action = _TRUST_STEPS[target]
    await evidence.require_human_admin(db, ctx)
    await begin_write(db)
    record = await get_in_company(db, ctx.company_id, memory_id)
    if record is None:
        raise MemoryOpError("MEMORY_NOT_FOUND", "Memory not found", 404)
    if record.status != "active" or record.trust_state != frm:
        raise MemoryOpError(
            "MEMORY_INVALID_TRANSITION",
            f"A {record.status} memory with {record.trust_state} trust cannot become {target}",
            409,
        )
    row = await evidence.load_evidence(db, ctx.company_id, memory_id, evidence_id)
    grade = await evidence.requalify(db, ctx.company_id, row)
    if evidence.GRADE_RANK[grade] < evidence.GRADE_RANK[need]:
        raise MemoryOpError(
            "MEMORY_EVIDENCE_NOT_QUALIFYING", f"This evidence cannot support {target} trust", 409
        )

    now = utcnow()
    won = await db.execute(
        update(MemoryRecord)
        .where(
            MemoryRecord.company_id == ctx.company_id,
            MemoryRecord.id == memory_id,
            MemoryRecord.status == "active",
            MemoryRecord.trust_state == frm,
        )
        .values(
            trust_state=target,
            lifecycle_changed_at=now,
            lifecycle_changed_by=ctx.actor[:100],
            updated_at=now,
        )
        .execution_options(synchronize_session=False)
    )
    if won.rowcount != 1:
        raise MemoryOpError(
            "MEMORY_INVALID_TRANSITION",
            "Memory changed while its trust was being promoted",
            409,
        )
    from nexus.services import manager_service as ms

    await ms.audit(
        db, ctx.company_id, action, ctx.actor, "memory", memory_id,
        from_trust_state=frm, to_trust_state=target, evidence_id=str(row.id),
        evidence_kind=row.evidence_kind, source_type=row.source_type, grade=grade,
        policy_version=row.policy_version, idempotency_key=idempotency_key,
    )
    return (await get_in_company(db, ctx.company_id, memory_id)) or record


async def assert_trust(
    db: Any,
    ctx: MemoryContext,
    memory_id: uuid.UUID,
    evidence_id: uuid.UUID,
    *,
    idempotency_key: str | None = None,
) -> MemoryRecord:
    """untrusted -> asserted on an active memory, backed by evidence graded assert or verify."""
    return await _promote_trust(db, ctx, memory_id, evidence_id, "asserted", idempotency_key)


async def verify_trust(
    db: Any,
    ctx: MemoryContext,
    memory_id: uuid.UUID,
    evidence_id: uuid.UUID,
    *,
    idempotency_key: str | None = None,
) -> MemoryRecord:
    """asserted -> verified on an active memory, backed by evidence graded verify.

    ``verified`` is evidence-backed trust, not prompt eligibility. A verified memory can
    still be archived or superseded; that does not touch the evidence.
    """
    return await _promote_trust(db, ctx, memory_id, evidence_id, "verified", idempotency_key)


def _conflict() -> MemoryOpError:
    return MemoryOpError(
        "MEMORY_SUPERSESSION_CONFLICT", "Memory was already superseded by another record", 409
    )
