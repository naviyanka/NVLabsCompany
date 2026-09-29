"""Durable employee chat turns: creation, claiming, execution and recovery.

A ``chat_turns`` row owns each employee turn. The HTTP request that created it
does not. The request stores the prompt and a queued turn in one short
transaction, wakes the worker and waits for the result, or answers 202 with
the turn ID. The turn runs whether or not the client is still connected.

Ordering and exclusivity come from the database, not from process memory:

- A worker claims a turn with one conditional UPDATE. The UPDATE succeeds only
  while the turn is queued, not cancelled, no earlier turn of its session is
  unfinished and no other turn of its session is claimed or running. Two
  workers, in one process or in many, cannot both claim it, and two turns of
  one session never run at once.
- The claim sets a lease. The worker renews it in short transactions while the
  model or CLI runs. No transaction is held across the call.
- :func:`sweep` recovers turns whose lease expired, for example after a
  crashed or restarted worker. It completes the turn if its reply is stored,
  cancels it if a cancel was requested, requeues it if attempts are left, and
  otherwise fails it and files a notification. Execution is at least once: a
  worker that loses its lease discards its result.
- Cancelling sets ``cancel_requested_at``. The worker that runs the turn sees
  the flag at its next renewal, or at once in the same process, and stops only
  its own process tree.

The in-process parts (the worker task, the saturation hints, the live chunk
queues and the change event) are only hints that make a waiter or a stream
react sooner. Losing them costs latency, never a turn.
"""

from __future__ import annotations

import asyncio
import contextlib
import contextvars
import dataclasses
import logging
import os
import socket
import time
import uuid
import weakref
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import and_, exists, func, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import aliased

from nexus.models.chat_turn import ACTIVE_STATUSES, TERMINAL_STATUSES, ChatTurn

logger = logging.getLogger(__name__)

WORKER_ID = f"{socket.gethostname()}:{os.getpid()}:{uuid.uuid4().hex[:8]}"

# Process-local event counts (also exported to Prometheus when available).
STATS: Counter[str] = Counter()

_SWEEP_EVERY_SECONDS = 15.0
_BATCH = 50
_KEEPALIVE_POLLS = 15

_prior = aliased(ChatTurn)


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)  # noqa: UP017


def _settings() -> Any:
    from nexus.config import settings

    return settings


def _count(event: str, **observed: float | None) -> None:
    STATS[event] += 1
    from nexus.observability.metrics import record_chat_turn_event

    record_chat_turn_event(event, **observed)


def _scoped(turn_id: uuid.UUID, company_id: uuid.UUID) -> Any:
    return and_(ChatTurn.id == turn_id, ChatTurn.company_id == company_id)


def _no_turn_ahead() -> Any:
    """No other unfinished turn of the session is ahead of this one or running."""
    return ~exists().where(
        _prior.company_id == ChatTurn.company_id,
        _prior.session_id == ChatTurn.session_id,
        _prior.id != ChatTurn.id,
        or_(
            and_(_prior.turn_seq < ChatTurn.turn_seq, _prior.status.not_in(TERMINAL_STATUSES)),
            _prior.status.in_(ACTIVE_STATUSES),
        ),
    )


async def _get(db: Any, company_id: uuid.UUID, turn_id: uuid.UUID) -> ChatTurn | None:
    return (
        await db.execute(select(ChatTurn).where(_scoped(turn_id, company_id)))
    ).scalar_one_or_none()


async def get_turn(company_id: uuid.UUID, turn_id: uuid.UUID) -> ChatTurn | None:
    """The tenant's turn as currently stored, or None."""
    from nexus.database import tenant_session

    async with tenant_session(company_id) as db:
        return await _get(db, company_id, turn_id)


async def _audit(
    db: Any, turn: ChatTurn, action: str, actor_type: str = "system", **details: Any
) -> None:
    from nexus.governance.audit_service import record_audit

    await record_audit(
        turn.company_id,
        action,
        actor_type=actor_type,
        resource_type="chat_turn",
        resource_id=str(turn.id),
        details={
            "agent_id": str(turn.agent_id),
            "session_id": str(turn.session_id),
            "execution_id": turn.execution_id,
            "attempt": turn.attempt_count,
            **details,
        },
        db=db,
    )


async def _publish(turn: ChatTurn, **extra: Any) -> None:
    from nexus.services.session_service import publish_session_event

    await publish_session_event(
        "session.turn",
        turn.company_id,
        {
            "session_id": str(turn.session_id),
            "agent_id": str(turn.agent_id),
            "turn_id": str(turn.id),
            "turn_status": turn.status,
            "execution_id": turn.execution_id,
            **extra,
        },
    )


# ---------------------------------------------------------------------------
# Creation
# ---------------------------------------------------------------------------


@dataclass
class Enqueued:
    turn: ChatTurn
    duplicate: bool


async def _find_by_key(
    db: Any, company_id: uuid.UUID, session_id: uuid.UUID, key: str
) -> ChatTurn | None:
    return (
        await db.execute(
            select(ChatTurn).where(
                ChatTurn.company_id == company_id,
                ChatTurn.session_id == session_id,
                ChatTurn.idempotency_key == key,
            )
        )
    ).scalar_one_or_none()


async def create_turn(
    db: Any,
    record: Any,
    agent: Any,
    prompt: str,
    *,
    principal: Any = None,
    idempotency_key: str | None = None,
    stream: bool = False,
    work_mode: str | None = None,
    require_manager_tools: bool = False,
    record_directive: bool = False,
) -> Enqueued:
    """Store the user's prompt and its queued turn in one transaction, then commit.

    A key already used in this company and session returns the existing turn:
    nothing is stored twice and nothing runs twice. Refusals (ended session,
    unusable pin, agent needing configuration, unresolvable adapter, principal
    of another company, a CEO whose backend cannot have the tools the caller
    requires, a directive not from a human to the CEO) are raised before
    anything is stored. ``record_directive`` stores the prompt, in the same
    transaction, as a human directive in the CEO's executive memory.
    """
    from nexus.api.routes import chat
    from nexus.services import ceo_service
    from nexus.services.session_service import begin_session_turn
    from nexus.tools.context import ExecutionContext

    company_id = record.company_id
    if idempotency_key:
        existing = await _find_by_key(db, company_id, record.id, idempotency_key)
        if existing is not None:
            _count("duplicate_suppressed")
            return Enqueued(existing, True)

    pinned = await begin_session_turn(db, record, agent)
    if getattr(pinned, "status", None) == "configuration_required":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "AGENT_CONFIGURATION_REQUIRED",
                "message": f"{pinned.name} must be configured before it can receive work",
            },
        )
    chat._resolve_adapter_type(pinned, await chat._resolve_connection(pinned))
    try:
        context = ExecutionContext.for_call(pinned, principal, source="chat", session_id=record.id)
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    if work_mode is not None:
        # Server-chosen (task attempts only); the adapter maps it to flags.
        context = dataclasses.replace(context, work_mode=work_mode)
    if require_manager_tools:
        context = dataclasses.replace(context, manager_tools_required=True)
    is_ceo = (require_manager_tools or record_directive) and await ceo_service.is_ceo(
        db, company_id, pinned.id
    )
    if require_manager_tools and is_ceo:
        supported, reason = ceo_service.tool_support(pinned)
        if not supported:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={"code": "CEO_TOOLS_UNSUPPORTED", "message": reason},
            )
    if record_directive:
        # No principal means autonomous work, which is not a person.
        if principal is None or not ceo_service.is_human(principal):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={"code": "HUMAN_DECISION_REQUIRED",
                        "message": "Only a human records a directive"},
            )
        if not is_ceo:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={"code": "NOT_CEO", "message": "Directives go to the company's CEO"},
            )

    message = await chat._persist_message_to_db(
        db, pinned.id, company_id, "user", prompt, session_id=record.id
    )
    if message is None:
        # Nothing has been spent yet; refuse rather than run an unrecorded turn.
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Could not record message"
        )
    turn = ChatTurn(
        company_id=company_id,
        agent_id=pinned.id,
        session_id=record.id,
        idempotency_key=idempotency_key or uuid.uuid4().hex,
        request_id=idempotency_key,
        turn_seq=message.seq,
        prompt_message_id=message.id,
        max_attempts=_settings().chat_turn_max_attempts,
        execution_context=context.to_dict(),
        result={"stream": True} if stream else None,
    )
    db.add(turn)
    try:
        await db.flush()
    except IntegrityError:
        # A concurrent request with the same key committed first.
        await db.rollback()
        existing = await _find_by_key(db, company_id, record.id, turn.idempotency_key)
        if existing is None:
            raise
        _count("duplicate_suppressed")
        return Enqueued(existing, True)
    if record_directive:
        await ceo_service.remember(
            db, company_id,
            ceo_service.MemoryEntry(type="directive", content=prompt[: ceo_service.CONTENT_MAX]),
            recorded_by=context.principal_id, origin="human",
            source={"session_id": record.id, "message_id": message.id, "turn_id": turn.id},
        )
    await _audit(db, turn, "chat.turn_queued", actor_type="user", principal=context.principal_id)
    await db.commit()
    _count("queued")
    await _publish(turn, seq=turn.turn_seq)
    from nexus.services.session_service import publish_session_event

    await publish_session_event(
        "session.message",
        company_id,
        {
            "session_id": str(record.id),
            "agent_id": str(turn.agent_id),
            "turn_id": str(turn.id),
            "seq": turn.turn_seq,
        },
    )
    return Enqueued(turn, False)


# ---------------------------------------------------------------------------
# Claim, lease, finalize
# ---------------------------------------------------------------------------


async def claim(
    turn_id: uuid.UUID, company_id: uuid.UUID, worker_id: str = WORKER_ID
) -> ChatTurn | None:
    """Claim a queued turn for ``worker_id``; None if it is not claimable right now."""
    from nexus.database import tenant_session

    now = _now()
    async with tenant_session(company_id) as db:
        res = await db.execute(
            update(ChatTurn)
            .where(
                _scoped(turn_id, company_id),
                ChatTurn.status == "queued",
                ChatTurn.cancel_requested_at.is_(None),
                _no_turn_ahead(),
            )
            .values(
                status="claimed",
                claimed_by=worker_id,
                execution_id=str(uuid.uuid4()),
                lease_expires_at=now + timedelta(seconds=_settings().chat_turn_lease_seconds),
                attempt_count=ChatTurn.attempt_count + 1,
                claimed_at=now,
                started_at=None,
                updated_at=now,
            )
            .execution_options(synchronize_session=False)
        )
        if res.rowcount != 1:
            await db.rollback()
            return None
        turn = await _get(db, company_id, turn_id)
        await _audit(db, turn, "chat.turn_claimed", worker=worker_id)
        await db.commit()
    _count("claimed", claim_latency=(now - turn.queued_at).total_seconds())
    await _publish(turn)
    return turn


async def _mark_running(db: Any, turn: ChatTurn, worker_id: str) -> bool:
    now = _now()
    res = await db.execute(
        update(ChatTurn)
        .where(
            _scoped(turn.id, turn.company_id),
            ChatTurn.claimed_by == worker_id,
            ChatTurn.status == "claimed",
            ChatTurn.cancel_requested_at.is_(None),
        )
        .values(status="running", started_at=now, updated_at=now)
        .execution_options(synchronize_session=False)
    )
    if res.rowcount != 1:
        return False
    turn.status, turn.started_at = "running", now
    await _audit(db, turn, "chat.turn_started", worker=worker_id)
    return True


async def renew(turn: ChatTurn, worker_id: str) -> str:
    """Extend the lease. Returns ``ok``, ``cancelled`` (cancel requested) or ``lost``."""
    from nexus.database import tenant_session

    now = _now()
    async with tenant_session(turn.company_id) as db:
        res = await db.execute(
            update(ChatTurn)
            .where(
                _scoped(turn.id, turn.company_id),
                ChatTurn.claimed_by == worker_id,
                ChatTurn.status.in_(ACTIVE_STATUSES),
            )
            .values(
                lease_expires_at=now + timedelta(seconds=_settings().chat_turn_lease_seconds),
                updated_at=now,
            )
            .execution_options(synchronize_session=False)
        )
        cancel_at = (
            await db.execute(
                select(ChatTurn.cancel_requested_at).where(_scoped(turn.id, turn.company_id))
            )
        ).scalar_one_or_none()
        await db.commit()
    if res.rowcount != 1:
        return "lost"
    return "cancelled" if cancel_at is not None else "ok"


async def finalize(
    turn: ChatTurn,
    worker_id: str,
    turn_status: str,
    *,
    prompt: str = "",
    text: str | None = None,
    model_used: str | None = None,
    tokens_used: int = 0,
    execution: dict[str, Any] | None = None,
    partial: bool = False,
    error_code: str | None = None,
    error_message: str | None = None,
    result: dict[str, Any] | None = None,
) -> ChatTurn | None:
    """Store the outcome of a turn this worker still holds, audit it and announce it.

    One path for every entry point (plain POST, SSE, recovery), so the stored
    reply, its metadata and the audit rows are the same however the turn was
    requested. Returns None, storing nothing, if the worker no longer holds
    the turn (its lease expired and recovery took it).
    """
    from nexus.api.routes import chat
    from nexus.database import tenant_session

    execution = execution or {}
    now = _now()
    async with tenant_session(turn.company_id) as db:
        res = await db.execute(
            update(ChatTurn)
            .where(
                _scoped(turn.id, turn.company_id),
                ChatTurn.claimed_by == worker_id,
                ChatTurn.status.in_(ACTIVE_STATUSES),
            )
            .values(
                status=turn_status,
                completed_at=now,
                updated_at=now,
                lease_expires_at=None,
                adapter_used=execution.get("adapter"),
                backend_used=execution.get("backend"),
                model_used=model_used,
                error_code=error_code,
                error_message=(error_message or "")[:2000] or None,
                result={**(turn.result or {}), **(result or {}), "tokens_used": tokens_used},
            )
            .execution_options(synchronize_session=False)
        )
        if res.rowcount != 1:
            await db.rollback()
            _count("result_discarded")
            return None
        reply = None
        if text is not None:
            # Execution provenance only when the adapter reported some.
            payload = {"execution": execution} if set(execution) - {"execution_id"} else None
            if partial:
                payload = {**(payload or {}), "partial": True}
            reply = await chat._persist_message_to_db(
                db,
                turn.agent_id,
                turn.company_id,
                "agent",
                text,
                session_id=turn.session_id,
                model_used=model_used,
                tokens_used=tokens_used,
                payload=payload,
            )
            if reply is None:
                raise RuntimeError("could not store the reply")
            await db.execute(
                update(ChatTurn)
                .where(_scoped(turn.id, turn.company_id))
                .values(response_message_id=reply.id)
                .execution_options(synchronize_session=False)
            )
        fresh = await _get(db, turn.company_id, turn.id)
        await db.refresh(fresh)
        if turn_status == "completed" and text is not None:
            await chat._record_chat_audit(
                db,
                turn.company_id,
                turn.agent_id,
                prompt,
                text,
                model_used or "",
                tokens_used,
                turn.session_id,
                execution_id=turn.execution_id,
            )
        await _audit(
            db,
            fresh,
            f"chat.turn_{turn_status}",
            actor_type="agent" if turn_status == "completed" else "system",
            error_code=error_code,
            adapter=execution.get("adapter"),
            backend=execution.get("backend"),
        )
        await db.commit()
    started = turn.claimed_at or now
    _count(turn_status, duration=(now - started).total_seconds())
    await _publish(fresh, seq=reply.seq if reply else None)
    if reply is not None:
        from nexus.services.session_service import publish_session_event

        await publish_session_event(
            "session.message",
            turn.company_id,
            {
                "session_id": str(turn.session_id),
                "agent_id": str(turn.agent_id),
                "turn_id": str(turn.id),
                "seq": reply.seq,
            },
        )
    return fresh


async def release(turn: ChatTurn, worker_id: str, reason: str) -> bool:
    """Hand a turn this worker holds back to the queue (graceful shutdown)."""
    from nexus.database import tenant_session

    now = _now()
    async with tenant_session(turn.company_id) as db:
        res = await db.execute(
            update(ChatTurn)
            .where(
                _scoped(turn.id, turn.company_id),
                ChatTurn.claimed_by == worker_id,
                ChatTurn.status.in_(ACTIVE_STATUSES),
            )
            .values(status="queued", claimed_by=None, lease_expires_at=None, updated_at=now)
            .execution_options(synchronize_session=False)
        )
        if res.rowcount != 1:
            await db.rollback()
            return False
        await _audit(db, turn, "chat.turn_recovered", reason=reason, worker=worker_id)
        await db.commit()
    _count("recovered")
    return True


# ---------------------------------------------------------------------------
# Cancellation
# ---------------------------------------------------------------------------


async def request_cancel(
    db: Any, company_id: uuid.UUID, session_id: uuid.UUID, turn_id: uuid.UUID, cancelled_by: str
) -> ChatTurn:
    """Cancel a turn durably. Idempotent; a finished turn is returned unchanged.

    A queued turn is cancelled at once. A claimed or running turn gets the
    flag, and its worker stops the execution and stores the outcome.
    """
    turn = await _get(db, company_id, turn_id)
    if turn is None or turn.session_id != session_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"Turn {turn_id} not found"
        )
    if turn.status in TERMINAL_STATUSES:
        return turn
    now = _now()
    res = await db.execute(
        update(ChatTurn)
        .where(_scoped(turn_id, company_id), ChatTurn.status == "queued")
        .values(
            status="cancelled",
            cancel_requested_at=now,
            cancelled_by=cancelled_by,
            completed_at=now,
            updated_at=now,
            error_code="CANCELLED",
        )
        .execution_options(synchronize_session=False)
    )
    if res.rowcount != 1:
        await db.execute(
            update(ChatTurn)
            .where(
                _scoped(turn_id, company_id),
                ChatTurn.status.in_(ACTIVE_STATUSES),
                ChatTurn.cancel_requested_at.is_(None),
            )
            .values(cancel_requested_at=now, cancelled_by=cancelled_by, updated_at=now)
            .execution_options(synchronize_session=False)
        )
    await db.refresh(turn)
    await _audit(
        db, turn, "chat.turn_cancel_requested", actor_type="user", cancelled_by=cancelled_by
    )
    if turn.status == "cancelled":
        await _audit(db, turn, "chat.turn_cancelled")
    await db.commit()
    if turn.status == "cancelled":
        _count("cancelled")
    else:
        get_worker().notify_cancel(turn.id)
    await _publish(turn)
    return turn


# ---------------------------------------------------------------------------
# Recovery
# ---------------------------------------------------------------------------


async def _recover(turn: ChatTurn, now: datetime) -> str:
    """Resolve one active turn whose lease expired. Returns what happened."""
    from nexus.database import tenant_session
    from nexus.models.notification import Notification

    if turn.response_message_id is not None:
        event, values = "completed", {"status": "completed", "completed_at": now}
    elif turn.cancel_requested_at is not None:
        event, values = (
            "cancelled",
            {"status": "cancelled", "completed_at": now, "error_code": "CANCELLED"},
        )
    elif turn.attempt_count < turn.max_attempts:
        event, values = "recovered", {"status": "queued", "claimed_by": None}
    else:
        event, values = (
            "failed",
            {
                "status": "failed",
                "completed_at": now,
                "error_code": "ATTEMPTS_EXHAUSTED",
                "error_message": f"Lease expired on each of {turn.attempt_count} attempts",
            },
        )
    previous_worker = turn.claimed_by
    async with tenant_session(turn.company_id) as db:
        res = await db.execute(
            update(ChatTurn)
            .where(
                _scoped(turn.id, turn.company_id),
                ChatTurn.status.in_(ACTIVE_STATUSES),
                ChatTurn.lease_expires_at < now,
            )
            .values(lease_expires_at=None, updated_at=now, **values)
            .execution_options(synchronize_session=False)
        )
        if res.rowcount != 1:
            await db.rollback()
            return "skipped"
        # ``turn`` was read by the sweep's own session; re-read it in this one.
        turn = await _get(db, turn.company_id, turn.id)
        action = "chat.turn_recovered" if event == "recovered" else f"chat.turn_{event}"
        await _audit(db, turn, action, reason="lease_expired", previous_worker=previous_worker)
        if event == "failed":
            db.add(
                Notification(
                    company_id=turn.company_id,
                    agent_id=turn.agent_id,
                    title="Employee chat turn needs help",
                    description=(
                        f"A chat turn stopped responding {turn.attempt_count} times "
                        "and was not retried again."
                    ),
                    notification_type="error",
                    module="agents",
                    priority="high",
                    notification_metadata={
                        "turn_id": str(turn.id),
                        "session_id": str(turn.session_id),
                        "execution_id": turn.execution_id,
                        "error_code": "ATTEMPTS_EXHAUSTED",
                    },
                )
            )
        await db.commit()
    _count("lease_expired")
    _count(event)
    await _publish(turn)
    return event


async def sweep(now: datetime | None = None) -> Counter[str]:
    """One recovery pass over every tenant. Safe to run on many workers at once.

    Also refreshes the queued/active gauges and returns the companies that
    have queued turns, so a freshly started worker knows where to look.
    """
    from nexus.database import system_session, tenant_session
    from nexus.observability.metrics import set_chat_turns

    now = now or _now()
    ttl = timedelta(seconds=_settings().chat_turn_queue_ttl_seconds)
    outcome: Counter[str] = Counter()
    async with system_session("chat turn recovery") as db:
        expired = (
            (
                await db.execute(
                    select(ChatTurn)
                    .where(ChatTurn.status.in_(ACTIVE_STATUSES), ChatTurn.lease_expires_at < now)
                    .limit(_BATCH)
                )
            )
            .scalars()
            .all()
        )
        stale = (
            (
                await db.execute(
                    select(ChatTurn)
                    .where(ChatTurn.status == "queued", ChatTurn.queued_at < now - ttl)
                    .limit(_BATCH)
                )
            )
            .scalars()
            .all()
        )
        by_status = dict(
            (
                await db.execute(
                    select(ChatTurn.status, func.count())
                    .where(ChatTurn.status.in_(("queued", *ACTIVE_STATUSES)))
                    .group_by(ChatTurn.status)
                )
            ).all()
        )
        waiting = set(
            (
                await db.execute(
                    select(ChatTurn.company_id).where(ChatTurn.status == "queued").distinct()
                )
            )
            .scalars()
            .all()
        )
    set_chat_turns("queued", by_status.get("queued", 0))
    set_chat_turns("active", sum(by_status.get(s, 0) for s in ACTIVE_STATUSES))

    for turn in expired:
        outcome[await _recover(turn, now)] += 1
    for turn in stale:
        async with tenant_session(turn.company_id) as db:
            res = await db.execute(
                update(ChatTurn)
                .where(_scoped(turn.id, turn.company_id), ChatTurn.status == "queued")
                .values(
                    status="expired",
                    completed_at=now,
                    updated_at=now,
                    error_code="QUEUE_TTL_EXPIRED",
                )
                .execution_options(synchronize_session=False)
            )
            if res.rowcount != 1:
                await db.rollback()
                continue
            turn = await _get(db, turn.company_id, turn.id)
            await _audit(db, turn, "chat.turn_expired", reason="queue_ttl")
            await db.commit()
        _count("expired")
        outcome["expired"] += 1
        await _publish(turn)
    outcome.update({f"company:{cid}": 1 for cid in waiting})
    return outcome


# ---------------------------------------------------------------------------
# Worker
# ---------------------------------------------------------------------------


class ChatTurnWorker:
    """Claims and runs queued turns on one event loop.

    Started by the application lifespan (``persistent``: polls, sweeps and
    drains on shutdown). A route that enqueues a turn also wakes it, which
    starts it on demand when no lifespan ran it (tests, embedded apps); such
    an on-demand worker exits once nothing it can claim is left.
    """

    def __init__(self, worker_id: str = WORKER_ID, *, persistent: bool = False) -> None:
        self.worker_id = worker_id
        self.persistent = persistent
        self.saturated: dict[uuid.UUID, int] = {}  # turn -> retry_after, for waiters
        self._task: asyncio.Task | None = None
        self._wake = asyncio.Event()
        self._changed = asyncio.Event()
        self._stopping = False
        self._running: dict[uuid.UUID, asyncio.Task] = {}
        self._cancels: dict[uuid.UUID, asyncio.Event] = {}
        self._listeners: dict[uuid.UUID, list[asyncio.Queue]] = {}
        self._buffers: dict[uuid.UUID, str] = {}  # text streamed so far, for late subscribers
        self._companies: set[uuid.UUID] = set()
        self._last_sweep = float("-inf")

    # -- hints ---------------------------------------------------------------

    def wake(self, company_id: uuid.UUID | None = None) -> None:
        if company_id is not None:
            self._companies.add(company_id)
        self._wake.set()
        if not self._stopping and (self._task is None or self._task.done()):
            # A fresh context: the worker outlives the request that woke it and
            # must not carry that request's context variables into other turns.
            self._task = asyncio.get_running_loop().create_task(
                self._loop(), name="chat-turn-worker", context=contextvars.Context()
            )

    def change_event(self) -> asyncio.Event:
        """Set at the next local turn change. Take it before reading the database."""
        return self._changed

    def _notify(self) -> None:
        event, self._changed = self._changed, asyncio.Event()
        event.set()

    def notify_cancel(self, turn_id: uuid.UUID) -> None:
        event = self._cancels.get(turn_id)
        if event is not None:
            event.set()

    def subscribe(self, turn_id: uuid.UUID) -> tuple[asyncio.Queue, str]:
        """Live text of a turn running here: a queue of chunks (None when it ends),
        and the text already streamed before subscribing."""
        queue: asyncio.Queue = asyncio.Queue()
        self._listeners.setdefault(turn_id, []).append(queue)
        return queue, self._buffers.get(turn_id, "")

    def unsubscribe(self, turn_id: uuid.UUID, queue: asyncio.Queue) -> None:
        queues = self._listeners.get(turn_id, [])
        if queue in queues:
            queues.remove(queue)
        if not queues:
            self._listeners.pop(turn_id, None)

    def _emit(self, turn_id: uuid.UUID, item: str | None) -> None:
        if item is not None:
            self._buffers[turn_id] = self._buffers.get(turn_id, "") + item
        for queue in self._listeners.get(turn_id, []):
            queue.put_nowait(item)

    # -- loop ----------------------------------------------------------------

    async def _loop(self) -> None:
        while not self._stopping:
            self._wake.clear()
            pending = False
            try:
                if self.persistent and time.monotonic() - self._last_sweep >= _SWEEP_EVERY_SECONDS:
                    self._last_sweep = time.monotonic()
                    found = await sweep()
                    self._companies.update(
                        uuid.UUID(k.split(":", 1)[1]) for k in found if k.startswith("company:")
                    )
                pending = await self._dispatch()
            except Exception:  # noqa: BLE001 -- keep the worker alive; the next pass retries
                logger.exception("chat turn worker pass failed")
                pending = True
            if not (self.persistent or pending or self._running or self._wake.is_set()):
                return
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(self._wake.wait(), _settings().chat_turn_poll_seconds)

    async def _candidates(self) -> list[tuple[uuid.UUID, uuid.UUID]]:
        from nexus.database import tenant_session

        found: list[tuple[uuid.UUID, uuid.UUID]] = []
        for company_id in list(self._companies):
            async with tenant_session(company_id) as db:
                rows = (
                    await db.execute(
                        select(ChatTurn.id, ChatTurn.company_id)
                        .where(
                            ChatTurn.company_id == company_id,
                            ChatTurn.status == "queued",
                            ChatTurn.cancel_requested_at.is_(None),
                            _no_turn_ahead(),
                        )
                        .order_by(ChatTurn.queued_at)
                        .limit(_BATCH)
                    )
                ).all()
            found += [(r[0], r[1]) for r in rows]
        return found

    async def _dispatch(self) -> bool:
        """Claim what this worker can run now. True if a turn is left waiting for capacity."""
        import nexus.runtime.orchestrator as orchestrator
        from nexus.governance.bulkhead import GlobalSaturated, TenantSaturated

        pending = False
        saturated: dict[uuid.UUID, int] = {}
        for turn_id, company_id in await self._candidates():
            if self._stopping:
                break
            if turn_id in self._running:
                continue
            slot = contextlib.AsyncExitStack()
            try:
                await slot.enter_async_context(orchestrator._tenant_bulkhead.acquire(company_id))
            except (TenantSaturated, GlobalSaturated) as exc:
                saturated[turn_id] = exc.retry_after
                pending = True
                continue
            try:
                turn = await claim(turn_id, company_id, self.worker_id)
            except BaseException:
                await slot.aclose()
                raise
            if turn is None:
                await slot.aclose()
                continue
            self._cancels[turn_id] = asyncio.Event()
            self._running[turn_id] = asyncio.get_running_loop().create_task(
                self._run(turn, slot), name=f"chat-turn-{turn_id}"
            )
        self.saturated = saturated
        if pending:
            self._notify()
        return pending

    async def _run(self, turn: ChatTurn, slot: contextlib.AsyncExitStack) -> None:
        import anyio

        try:
            await self._execute(turn)
        except asyncio.CancelledError:
            # Shutdown: hand the turn back so any worker can take it at once.
            with anyio.CancelScope(shield=True):
                with contextlib.suppress(Exception):
                    await release(turn, self.worker_id, "worker_shutdown")
            raise
        except Exception:  # noqa: BLE001 -- the lease expires and recovery takes over
            logger.exception("chat turn %s failed outside its own error handling", turn.id)
        finally:
            with anyio.CancelScope(shield=True):
                await slot.aclose()
            self._running.pop(turn.id, None)
            self._cancels.pop(turn.id, None)
            self._emit(turn.id, None)
            self._buffers.pop(turn.id, None)
            self._notify()
            self.wake()  # the session's next turn may be claimable now

    async def _execute(self, turn: ChatTurn) -> None:
        from nexus.api.routes import chat
        from nexus.database import tenant_session
        from nexus.models.agent_session import AgentSessionRecord
        from nexus.models.chat import ChatMessage
        from nexus.services.session_service import begin_session_turn
        from nexus.tools.context import ExecutionContext

        company_id = turn.company_id
        execution: dict[str, Any] = {"execution_id": turn.execution_id}
        partial: list[str] = []
        prompt = ""
        try:
            async with tenant_session(company_id) as db:
                record = (
                    await db.execute(
                        select(AgentSessionRecord).where(
                            AgentSessionRecord.id == turn.session_id,
                            AgentSessionRecord.company_id == company_id,
                        )
                    )
                ).scalar_one()
                agent = await begin_session_turn(
                    db, record, await chat._load_agent(db, turn.agent_id, company_id)
                )
                prompt_row = (
                    await db.execute(
                        select(ChatMessage).where(
                            ChatMessage.id == turn.prompt_message_id,
                            ChatMessage.company_id == company_id,
                        )
                    )
                ).scalar_one()
                prompt = prompt_row.text
                system_prompt = await chat._build_chat_prompt(db, agent, company_id, prompt)
                history = await session_history(
                    db, company_id, turn.session_id, before_seq=turn.turn_seq
                )
                running = await _mark_running(db, turn, self.worker_id)
                await db.commit()
            if not running:
                if await renew(turn, self.worker_id) == "cancelled":
                    await finalize(
                        turn, self.worker_id, "cancelled", prompt=prompt, error_code="CANCELLED"
                    )
                return
            await _publish(turn)

            context = (
                ExecutionContext.from_dict(turn.execution_context)
                if turn.execution_context
                else None
            )
            if (turn.result or {}).get("stream"):
                call = chat._stream_llm(
                    agent,
                    system_prompt,
                    prompt,
                    history,
                    session_id=turn.session_id,
                    context=context,
                    execution=execution,
                    on_chunk=lambda text: (partial.append(text), self._emit(turn.id, text)),
                )
            else:
                call = chat._call_llm(
                    agent,
                    system_prompt,
                    prompt,
                    history,
                    session_id=turn.session_id,
                    context=context,
                    execution=execution,
                )
            outcome, value = await self._supervise(turn, asyncio.ensure_future(call))
        except HTTPException as exc:
            outcome, value = "error", exc
        except Exception as exc:  # noqa: BLE001 -- stored on the turn below
            outcome, value = "error", exc

        if outcome == "done":
            text, model_used, tokens_used = value
            await finalize(
                turn,
                self.worker_id,
                "completed",
                prompt=prompt,
                text=text,
                model_used=model_used,
                tokens_used=tokens_used,
                execution=execution,
            )
        elif outcome == "cancelled":
            await finalize(
                turn,
                self.worker_id,
                "cancelled",
                prompt=prompt,
                text="".join(partial) or None,
                partial=True,
                execution=execution,
                error_code="CANCELLED",
                error_message="Cancelled by request",
            )
        elif outcome == "error":
            await finalize(
                turn,
                self.worker_id,
                "failed",
                prompt=prompt,
                execution=execution,
                **_failure(value),
            )
        # "lost": another worker or recovery owns the turn now; store nothing.

    async def _supervise(self, turn: ChatTurn, call: asyncio.Future) -> tuple[str, Any]:
        """Wait for the call, renewing the lease; stop it on cancel or a lost lease."""
        interval = max(0.5, _settings().chat_turn_lease_seconds / 3)
        cancel = self._cancels.setdefault(turn.id, asyncio.Event())
        cancelled = asyncio.ensure_future(cancel.wait())
        try:
            while True:
                done, _ = await asyncio.wait(
                    {call, cancelled}, timeout=interval, return_when=asyncio.FIRST_COMPLETED
                )
                if call in done:
                    return "done", call.result()
                state = (
                    "cancelled" if cancelled in done else await _safe_renew(turn, self.worker_id)
                )
                if state != "ok":
                    call.cancel()
                    await asyncio.wait({call})
                    return state, None
        finally:
            cancelled.cancel()
            if not call.done():
                call.cancel()
                await asyncio.wait({call})


async def _safe_renew(turn: ChatTurn, worker_id: str) -> str:
    try:
        return await renew(turn, worker_id)
    except Exception:  # noqa: BLE001 -- keep running; if the lease lapses, recovery decides
        logger.warning("lease renewal failed for chat turn %s", turn.id, exc_info=True)
        return "ok"


def _failure(exc: BaseException) -> dict[str, Any]:
    """The turn columns for an execution that raised, without secrets or tracebacks."""
    from nexus.models_router.preflight import BudgetInfraUnavailable

    if isinstance(exc, HTTPException):
        detail = exc.detail
        code = detail.get("code") if isinstance(detail, dict) else None
        message = detail.get("message") if isinstance(detail, dict) else str(detail)
        return {
            "error_code": code or f"HTTP_{exc.status_code}",
            "error_message": message,
            "result": {"http_status": exc.status_code, "detail": detail},
        }
    if isinstance(exc, BudgetInfraUnavailable):
        return {
            "error_code": "BUDGET_UNAVAILABLE",
            "error_message": "Budget ledger unavailable; the call was refused",
            "result": {"http_status": 503},
        }
    return {
        "error_code": "EXECUTION_ERROR",
        "error_message": f"{type(exc).__name__}: {exc}"[:500],
        "result": {"http_status": 500},
    }


async def session_history(
    db: Any,
    company_id: uuid.UUID,
    session_id: uuid.UUID,
    *,
    before_seq: int | None = None,
    limit: int = 10,
) -> list[dict[str, Any]]:
    """The last ``limit`` messages before the turn at ``before_seq``, in _call_llm's shape.

    A reply belongs where its turn's prompt is, not where it was stored: when
    prompts are queued back to back, the earlier turn's reply is stored after
    the later prompt, yet the later turn must see it, right after its prompt.
    """
    from nexus.models.chat import ChatMessage

    replied = aliased(ChatTurn)
    stmt = (
        select(ChatMessage)
        .outerjoin(
            replied,
            and_(
                replied.response_message_id == ChatMessage.id,
                replied.company_id == company_id,
                replied.session_id == session_id,
            ),
        )
        .where(
            ChatMessage.company_id == company_id,
            ChatMessage.session_id == session_id,
            ChatMessage.kind == "message",
        )
    )
    place = func.coalesce(replied.turn_seq, ChatMessage.seq)
    if before_seq is not None:
        stmt = stmt.where(place < before_seq)
    stmt = stmt.order_by(place.desc(), ChatMessage.seq.desc()).limit(limit)
    rows = (await db.execute(stmt)).scalars()
    return [{"sender": r.sender, "text": r.text} for r in reversed(list(rows))]


# ---------------------------------------------------------------------------
# Per-loop worker and waiting
# ---------------------------------------------------------------------------

_workers: weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, ChatTurnWorker] = (
    weakref.WeakKeyDictionary()
)


def get_worker() -> ChatTurnWorker:
    """This event loop's worker (asyncio primitives cannot cross loops)."""
    loop = asyncio.get_running_loop()
    worker = _workers.get(loop)
    if worker is None:
        worker = _workers[loop] = ChatTurnWorker()
    return worker


async def start_worker() -> ChatTurnWorker:
    worker = get_worker()
    worker.persistent = True
    worker._stopping = False
    worker.wake()
    return worker


async def stop_worker(drain_seconds: float = 30.0) -> None:
    """Stop claiming, let running turns finish, then hand the rest back to the queue."""
    worker = get_worker()
    worker._stopping = True
    worker._wake.set()
    if worker._task is not None:
        with contextlib.suppress(Exception, asyncio.CancelledError):
            await worker._task
    running = list(worker._running.values())
    if running:
        _, left = await asyncio.wait(running, timeout=drain_seconds)
        for task in left:
            task.cancel()
        if left:
            await asyncio.wait(left)


async def drain() -> None:
    """Wait until this loop's worker has nothing running or claimable (tests, shutdown)."""
    worker = get_worker()
    while worker._task is not None and not worker._task.done():
        await asyncio.wait({worker._task})


async def wait_for_turn(
    company_id: uuid.UUID, turn_id: uuid.UUID, timeout: float
) -> tuple[ChatTurn, int | None]:
    """The turn once terminal, or ``(turn, retry_after)`` while it is still pending.

    Returns early with the bulkhead's retry-after when this process could not
    start the turn for lack of capacity; the turn stays queued and runs when
    capacity frees up.
    """
    worker = get_worker()
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while True:
        changed = worker.change_event()
        turn = await get_turn(company_id, turn_id)
        if turn is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail=f"Turn {turn_id} not found"
            )
        if turn.status in TERMINAL_STATUSES:
            return turn, None
        retry_after = worker.saturated.get(turn_id)
        if retry_after is not None and turn.status == "queued":
            return turn, retry_after
        remaining = deadline - loop.time()
        if remaining <= 0:
            return turn, max(1, round(_settings().chat_turn_poll_seconds))
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(
                changed.wait(), min(remaining, _settings().chat_turn_poll_seconds)
            )


def turn_state(turn: ChatTurn, retry_after: int | None = None) -> dict[str, Any]:
    """The client view of a turn that is not (or not yet) completed."""
    return {
        "turn_id": str(turn.id),
        "session_id": str(turn.session_id),
        "agent_id": str(turn.agent_id),
        "execution_id": turn.execution_id,
        "status": turn.status,
        "seq": turn.turn_seq,
        "prompt_message_id": str(turn.prompt_message_id) if turn.prompt_message_id else None,
        "attempt_count": turn.attempt_count,
        "error_code": turn.error_code,
        "cancel_requested": turn.cancel_requested_at is not None,
        "retry_after": retry_after,
    }


def raise_for_outcome(turn: ChatTurn) -> None:
    """Re-raise a failed, cancelled or expired turn as the HTTP error it amounts to."""
    if turn.status == "completed":
        return
    if turn.status == "failed":
        result = turn.result or {}
        detail = result.get("detail") or {"code": turn.error_code, "message": turn.error_message}
        if isinstance(detail, dict):
            detail = {**detail, "turn_id": str(turn.id)}
        raise HTTPException(status_code=result.get("http_status", 500), detail=detail)
    raise HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail={
            "code": "TURN_CANCELLED" if turn.status == "cancelled" else "TURN_EXPIRED",
            "message": f"The turn was {turn.status}",
            "turn_id": str(turn.id),
        },
    )
