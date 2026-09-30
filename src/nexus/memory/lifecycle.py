"""Lifecycle transitions for ``memory_records``: archive, reject, supersede.

Nothing here deletes a row or edits content or provenance. Each transition is a
tenant-scoped conditional UPDATE (``WHERE company_id AND id AND status = <observed>``)
that touches only the lifecycle columns, so two racing callers resolve
deterministically: one wins, the other re-reads and either sees its own target
state (idempotent success) or a stable conflict error. The caller commits.

Transitions:
    archive:   candidate | active -> archived
    reject:    candidate          -> rejected
    supersede: candidate | active -> superseded   (plus a new successor row)
A repeated identical transition returns the current row instead of an error.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import update

from nexus.memory.ingest import (
    IngestResult,
    MemoryContext,
    MemoryInput,
    MemoryOpError,
    Origin,
    get_in_company,
    ingest_memory,
)
from nexus.models._time import utcnow
from nexus.models.memory import LIVE_STATUSES, MemoryRecord

_FROM = {
    "archived": LIVE_STATUSES,
    "rejected": ("candidate",),
    "superseded": LIVE_STATUSES,
}
_ACTION = {"archived": "memory.archived", "rejected": "memory.rejected", "superseded": "memory.superseded"}


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
) -> tuple[MemoryRecord, bool]:
    """Move one row to ``target``. Returns (row, changed); ``changed`` is False for an idempotent repeat."""
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


def _conflict() -> MemoryOpError:
    return MemoryOpError(
        "MEMORY_SUPERSESSION_CONFLICT", "Memory was already superseded by another record", 409
    )
