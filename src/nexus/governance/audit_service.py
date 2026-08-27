"""Audit Service — records ALL significant platform events to the AuditLog table.

This service is the single entry point for audit logging. Every subsystem
calls `record_audit()` to write an immutable record. The function is async
and fire-and-forget (errors are swallowed so audit never blocks operations).

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
import logging
import uuid
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
) -> None:
    """Write an audit log entry to the database.

    This is fire-and-forget — errors are logged but never raised,
    so audit logging can never block the operation being audited.

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
            # Create a new session (for background tasks / orchestrator)
            from nexus.database import async_session_factory
            async with async_session_factory() as new_db:
                await _write_with_chain_retry(new_db, entry)

        logger.info("Audit: %s [%s] %s", action, actor_type, resource_type or "")
    except Exception as e:
        logger.warning("Audit log write failed: %s", e)


async def _chain(session: Any, entry: Any) -> None:
    """Stamp `entry` with the next sequence number and hash-chain links.

    Without this the row lands in `audit_log` with NULL chain columns, where
    `PersistentAuditLogger.verify_chain_integrity` skips it — the event would
    be recorded but not tamper-evident.
    """
    from sqlmodel import select

    from nexus.governance.audit_persistent import (
        PersistentAuditEntry,
        compute_entry_hash,
    )
    from nexus.models.governance import AuditLog

    result = await session.execute(
        select(AuditLog)
        .where(AuditLog.sequence_number.is_not(None))
        .order_by(AuditLog.sequence_number.desc())
        .limit(1)
    )
    tail = result.scalars().first()

    entry.sequence_number = (tail.sequence_number if tail else 0) + 1
    entry.previous_hash = tail.entry_hash if tail else "genesis"
    entry.entry_hash = compute_entry_hash(
        PersistentAuditEntry.from_row(entry), entry.previous_hash
    )


async def _chain_in_savepoint(session: Any, entry: Any) -> None:
    """Add `entry` to the caller's session without risking their transaction.

    A sequence-number collision raises IntegrityError on flush, which would leave
    the caller's transaction unusable. Flushing inside a nested savepoint keeps
    the damage local: on collision the savepoint rolls back and the row is added
    unchained, so the audited request still succeeds.
    """
    from sqlalchemy.exc import IntegrityError

    # The audit row goes into the caller's transaction on purpose: it must not
    # outlive a request that rolls back, and it needs to see that request's
    # uncommitted state.
    #
    # `_chain_lock` serialises tail-read-then-flush within this process, so two
    # coroutines here cannot claim the same sequence number. Across processes
    # they can: a second worker's tail read sees only committed rows, so it can
    # pick a number this process has flushed but not committed. That collision
    # raises on the nested flush below, inside the savepoint, so it degrades to
    # an unchained row rather than poisoning the caller's transaction. The gap
    # is that such a row is invisible to chain verification -- allocating the
    # number from a DB sequence would close it, and needs a migration.
    async with _chain_lock:
        await _chain_safely(session, entry)
        try:
            async with session.begin_nested():
                session.add(entry)
                await session.flush()
            return
        except IntegrityError:
            logger.warning(
                "Audit chain collision on action %s; writing row without chain links",
                entry.action,
            )

    entry.sequence_number = None
    entry.previous_hash = None
    entry.entry_hash = None
    session.add(entry)
    await session.flush()


async def _chain_safely(session: Any, entry: Any) -> None:
    """Chain `entry`, but never let a chain failure lose the audit row.

    Losing the event entirely is worse than losing its tamper-evident link, so a
    failure here leaves the chain columns NULL and warns rather than raising.
    """
    try:
        await _chain(session, entry)
    except Exception as exc:  # noqa: BLE001 - the row must still be written
        logger.warning(
            "Audit chain could not be stamped for action %s; "
            "row will be written without chain links: %s",
            entry.action,
            exc,
        )


# Reading the chain tail and committing the next link must not interleave, or
# two writers pick the same sequence number and one loses the race on a UNIQUE
# violation. This lock serialises them within a process; the retry loop below
# still covers the cross-process case, where a second API worker or the Temporal
# worker writes concurrently.
_chain_lock = asyncio.Lock()


async def _write_with_chain_retry(session: Any, entry: Any, attempts: int = 5) -> None:
    """Insert `entry` on its own session, retrying if the sequence number races.

    On the final attempt the row is written without chain links rather than
    dropped: losing the event is worse than losing its tamper-evident link.
    """
    from sqlalchemy.exc import IntegrityError

    async with _chain_lock:
        for attempt in range(attempts):
            await _chain_safely(session, entry)
            session.add(entry)
            try:
                await session.commit()
                return
            except IntegrityError:
                await session.rollback()
                # Rollback detaches the instance; clear the stamped columns so
                # the next pass re-reads a fresh tail.
                if entry in session:
                    session.expunge(entry)
                entry.sequence_number = None
                entry.previous_hash = None
                entry.entry_hash = None
                if attempt == attempts - 1:
                    logger.warning(
                        "Audit chain contention on action %s after %d attempts; "
                        "writing row without chain links",
                        entry.action,
                        attempts,
                    )
                    session.add(entry)
                    await session.commit()
