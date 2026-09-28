"""Audit Service — records ALL significant platform events to the AuditLog table.

This service is the single entry point for audit logging. Every subsystem
calls `record_audit()` to write an immutable record. The function is async
and fire-and-forget (errors are logged, not raised, so audit never blocks
operations) unless the caller passes ``raise_on_error``. A row is written with
its chain links or not at all.

Events captured:
- Chat messages sent/received
- Agent status changes (wake, pause, fire, create)
- Task lifecycle (create, assign, status change, complete)
- Pipeline execution (trigger, stage complete, fail)
- Settings changes
- API key operations
- Approval decisions
- Inter-agent communication
- Orchestrator actions (goal decomposition, task routing)
"""

import asyncio
import contextlib
import logging
import uuid
import weakref
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)


async def record_audit(
    company_id: uuid.UUID,
    action: str,
    *,
    actor_type: str = "system",
    actor_id: str | None = None,
    resource_type: str | None = None,
    resource_id: str | None = None,
    details: dict[str, Any] | None = None,
    ip_address: str | None = None,
    db: Any | None = None,
    raise_on_error: bool = False,
) -> None:
    """Write an audit log entry to the database.

    Default mode is fire-and-forget for existing callers. ``raise_on_error``
    makes durability-sensitive operations fail closed when persistence fails.

    Args:
        company_id: The company/tenant this event belongs to.
        action: What happened (e.g. 'chat.message_sent', 'agent.created').
        actor_type: Who did it — 'user', 'agent', 'system', 'orchestrator'.
        actor_id: Identifier of the actor (user email, agent UUID, etc.).
        resource_type: What was affected — 'agent', 'task', 'pipeline', etc.
        resource_id: The ID of the affected resource.
        details: Additional context as a JSON dict.
        ip_address: Client IP if available.
        db: Optional existing DB session (avoids SQLite locking issues).
    """
    try:
        from nexus.models.governance import AuditLog

        entry = AuditLog(
            id=uuid.uuid4(),
            company_id=company_id,
            actor_type=actor_type,
            actor_id=actor_id,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            details=details,
            ip_address=ip_address,
            created_at=datetime.now(timezone.utc).replace(tzinfo=None),
        )

        if db is not None:
            # Use the caller's session, inside a savepoint so a chain collision
            # cannot poison the transaction of the request being audited.
            await _chain_in_savepoint(db, entry)
        else:
            # Create a new session (for background tasks / orchestrator), in
            # the event's tenant: audit_log is under row-level security.
            from nexus.database import tenant_session
            async with tenant_session(company_id) as new_db:
                await _write_with_chain_retry(new_db, entry)

        logger.info("Audit: %s [%s] %s", action, actor_type, resource_type or "")
    except Exception as exc:
        # The row was not written. It is never written without chain links.
        logger.error("Audit log write failed for %s: %s", action, exc)
        if raise_on_error:
            raise RuntimeError("audit log write failed") from exc


async def _chain(session: Any, entry: Any) -> None:
    """Stamp `entry` with the next link of its company's chain.

    Each company has its own chain: the sequence number and the previous hash
    come from that company's tail only, and ``(company_id, sequence_number)``
    is unique. Events without a company (system events) form one more chain.
    A tenant cannot see another tenant's rows under RLS, so a single global
    chain could neither be allocated nor verified by the application role.

    On PostgreSQL a transaction-scoped advisory lock on the company's chain is
    taken first. It is held until the transaction that inserts the row ends, so
    writers of one company serialise across processes, and the tail read after
    it sees every committed link. Writers of different companies do not wait
    on each other.
    """
    from sqlalchemy import text
    from sqlmodel import select

    from nexus.governance.audit_persistent import (
        PersistentAuditEntry,
        compute_entry_hash,
    )
    from nexus.models.governance import AuditLog

    if _is_postgres(session):
        await session.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
            {"key": f"audit_chain:{entry.company_id or 'system'}"},
        )
    scope = (
        AuditLog.company_id.is_(None)
        if entry.company_id is None
        else AuditLog.company_id == entry.company_id
    )
    result = await session.execute(
        select(AuditLog)
        .where(scope, AuditLog.sequence_number.is_not(None))
        .order_by(AuditLog.sequence_number.desc())
        .limit(1)
    )
    tail = result.scalars().first()

    entry.sequence_number = (tail.sequence_number if tail else 0) + 1
    entry.previous_hash = tail.entry_hash if tail else "genesis"
    entry.entry_hash = compute_entry_hash(
        PersistentAuditEntry.from_row(entry), entry.previous_hash
    )


def _is_postgres(session: Any) -> bool:
    return session.get_bind().dialect.name == "postgresql"


def _unstamp(entry: Any) -> None:
    entry.sequence_number = None
    entry.previous_hash = None
    entry.entry_hash = None


class AuditChainError(RuntimeError):
    """The next link of an audit chain could not be allocated.

    Raised instead of writing the row without chain links: an unchained row is
    invisible to chain verification, so it is never written.
    """


async def _chain_in_savepoint(session: Any, entry: Any, attempts: int = 5) -> None:
    """Add `entry` to the caller's session without risking their transaction.

    The audit row goes into the caller's transaction on purpose: it must not
    outlive a request that rolls back, and it needs to see that request's
    uncommitted state. Chaining and the flush run inside a savepoint, so a
    failure (a lock timeout, a unique violation) rolls back only the savepoint
    and leaves the caller's transaction usable. On PostgreSQL the chain lock
    taken inside the savepoint passes to the caller's transaction when the
    savepoint is released, and is held until the caller commits.

    Raises:
        AuditChainError: no link could be allocated; nothing was written.
    """
    async with _local_lock(session):
        for _ in range(attempts):
            try:
                async with session.begin_nested():
                    await _chain(session, entry)
                    session.add(entry)
                    await session.flush()
                return
            except Exception as exc:  # noqa: BLE001 - retried, then raised below
                last = exc
                if entry in session:
                    session.expunge(entry)
                _unstamp(entry)
    raise AuditChainError(
        f"audit chain link for {entry.action!r} not allocated after {attempts} attempts"
    ) from last


# SQLite has no advisory locks. There, reading the chain tail and inserting the
# next link must not interleave within the process, or two writers pick the
# same sequence number; this lock serialises them. The unique constraint on
# (company_id, sequence_number) and the bounded retries cover what it cannot.
#
# PostgreSQL uses the advisory lock in `_chain` instead, and must not also take
# this one: a writer holding the advisory lock until its caller commits could
# then wait here on a writer that waits on the advisory lock.
#
# One lock per event loop: an asyncio.Lock binds to the first loop that waits on
# it, and a later loop (asyncio.run in a worker thread, a test) would then get
# RuntimeError on every contended write.
_chain_locks: weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, asyncio.Lock] = (
    weakref.WeakKeyDictionary()
)


def _chain_lock() -> asyncio.Lock:
    loop = asyncio.get_running_loop()
    lock = _chain_locks.get(loop)
    if lock is None:
        lock = _chain_locks[loop] = asyncio.Lock()
    return lock


def _local_lock(session: Any) -> Any:
    return contextlib.nullcontext() if _is_postgres(session) else _chain_lock()


async def _write_with_chain_retry(session: Any, entry: Any, attempts: int = 5) -> None:
    """Insert `entry` on its own session, retrying if allocating the link fails.

    Each attempt is one transaction: chain lock, tail read, insert, commit.

    Raises:
        AuditChainError: every attempt failed; nothing was written.
    """
    async with _local_lock(session):
        for _ in range(attempts):
            try:
                await _chain(session, entry)
                session.add(entry)
                await session.commit()
                return
            except Exception as exc:  # noqa: BLE001 - retried, then raised below
                last = exc
                await session.rollback()
                # Rollback detaches the instance; clear the stamped columns so
                # the next pass re-reads a fresh tail.
                if entry in session:
                    session.expunge(entry)
                _unstamp(entry)
    raise AuditChainError(
        f"audit chain link for {entry.action!r} not allocated after {attempts} attempts"
    ) from last
