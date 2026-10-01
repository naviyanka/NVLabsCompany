"""Stop running work and lock the company or one agent down.

Cancelling reuses the runtime's own paths (``task_attempts.cancel_attempt`` and
``chat_turns.request_cancel``), so a cancel is the same durable flag the worker already honours.
Nothing here holds a transaction while a worker stops: the audit entry commits first (fail
closed), then the existing cancel runs in its own short transactions.

Lockdown and isolation are :class:`GovernanceRestriction` rows. The overlay turns an active row
into a hard deny for every non-read or explicit-allow-only tool, so they need no other switch.
There is no bypass: only a human administrator creates or releases one, with a reason, and a
company lockdown also needs its confirmation phrase.
"""

from __future__ import annotations

import uuid
from typing import Any

from pydantic import BaseModel, Field
from sqlalchemy import update
from sqlmodel import select

from nexus.models.agent import Agent
from nexus.models.chat_turn import ChatTurn
from nexus.models.governance import AuditLog
from nexus.models.governance_studio import GovernanceRestriction
from nexus.models.task_attempt import ACTIVE_ATTEMPT_STATUSES, TaskAttempt
from nexus.runtime import chat_turns, task_attempts
from nexus.services.governance_studio.audit import actor_of, audit, clip
from nexus.services.governance_studio.errors import fail
from nexus.tools import governance_overlay as overlay

LOCKDOWN_PHRASE = "LOCKDOWN"
RELEASE_PHRASE = "RELEASE LOCKDOWN"
PAGE_MAX = 100
ACTIVE_TURN_STATUSES = ("queued", "claimed", "running")


class CancelBody(BaseModel):
    reason: str = Field(min_length=5, max_length=500)


class LockdownBody(BaseModel):
    reason: str = Field(min_length=5, max_length=500)
    confirm: str = Field(max_length=50)


class IsolateBody(BaseModel):
    reason: str = Field(min_length=5, max_length=500)


def _iso(value: Any) -> str | None:
    return value.isoformat() if value else None


def _attempt(a: TaskAttempt) -> dict[str, Any]:
    return {
        "id": str(a.id), "task_id": str(a.task_id), "agent_id": str(a.agent_id),
        "status": a.status, "attempt_number": a.attempt_number,
        "cancel_requested": a.cancel_requested_at is not None,
        "queued_at": _iso(a.queued_at), "started_at": _iso(a.started_at),
    }


def _turn(t: ChatTurn) -> dict[str, Any]:
    return {
        "id": str(t.id), "session_id": str(t.session_id), "agent_id": str(t.agent_id),
        "status": t.status, "cancel_requested": t.cancel_requested_at is not None,
        "queued_at": _iso(t.queued_at), "started_at": _iso(t.started_at),
    }


async def active_work(
    db: Any, company_id: uuid.UUID, agent_id: uuid.UUID | None = None
) -> dict[str, Any]:
    """Attempts and chat turns that could still act. Ids and states only."""
    attempts = select(TaskAttempt).where(
        TaskAttempt.company_id == company_id, TaskAttempt.status.in_(ACTIVE_ATTEMPT_STATUSES)
    )
    turns = select(ChatTurn).where(
        ChatTurn.company_id == company_id, ChatTurn.status.in_(ACTIVE_TURN_STATUSES)
    )
    if agent_id is not None:
        attempts = attempts.where(TaskAttempt.agent_id == agent_id)
        turns = turns.where(ChatTurn.agent_id == agent_id)
    a = await db.execute(attempts.order_by(TaskAttempt.queued_at).limit(PAGE_MAX))
    t = await db.execute(turns.order_by(ChatTurn.queued_at).limit(PAGE_MAX))
    return {
        "attempts": [_attempt(x) for x in a.scalars().all()],
        "turns": [_turn(x) for x in t.scalars().all()],
    }


async def _agent(db: Any, company_id: uuid.UUID, agent_id: uuid.UUID) -> Agent:
    agent = (
        await db.execute(
            select(Agent).where(Agent.id == agent_id, Agent.company_id == company_id)
        )
    ).scalars().first()
    if agent is None:
        fail(404, "AGENT_NOT_FOUND", "No such agent")
    return agent


async def _record(
    db: Any, company_id: uuid.UUID, principal: Any, action: str, rtype: str, rid: Any,
    details: dict[str, Any],
) -> None:
    """Audit and commit before acting. If the audit cannot be written, nothing happens."""
    await audit(db, company_id, principal, action, rtype, rid, details)
    await db.commit()


async def cancel_attempt(
    db: Any, company_id: uuid.UUID, principal: Any, attempt_id: uuid.UUID, body: CancelBody
) -> dict[str, Any]:
    attempt = (
        await db.execute(
            select(TaskAttempt).where(
                TaskAttempt.id == attempt_id, TaskAttempt.company_id == company_id
            )
        )
    ).scalars().first()
    if attempt is None:
        fail(404, "ATTEMPT_NOT_FOUND", "No such attempt")
    await _record(db, company_id, principal, "runtime.cancel_requested", "task_attempt",
                  attempt.id, {"agent_id": str(attempt.agent_id), "reason": clip(body.reason)})
    done = await task_attempts.cancel_attempt(
        db, company_id, attempt.task_id, attempt.id, principal
    )
    return _attempt(done)


async def cancel_turn(
    db: Any, company_id: uuid.UUID, principal: Any, turn_id: uuid.UUID, body: CancelBody
) -> dict[str, Any]:
    turn = (
        await db.execute(
            select(ChatTurn).where(ChatTurn.id == turn_id, ChatTurn.company_id == company_id)
        )
    ).scalars().first()
    if turn is None:
        fail(404, "TURN_NOT_FOUND", "No such turn")
    await _record(db, company_id, principal, "runtime.cancel_requested", "chat_turn",
                  turn.id, {"agent_id": str(turn.agent_id), "reason": clip(body.reason)})
    done = await chat_turns.request_cancel(
        db, company_id, turn.session_id, turn.id, actor_of(principal)
    )
    return _turn(done)


async def cancel_agent(
    db: Any, company_id: uuid.UUID, principal: Any, agent_id: uuid.UUID, body: CancelBody
) -> dict[str, Any]:
    """Cancel every active attempt and turn of one agent."""
    await _agent(db, company_id, agent_id)
    work = await active_work(db, company_id, agent_id)
    await _record(db, company_id, principal, "runtime.agent_cancel_requested", "agent", agent_id,
                  {"attempts": len(work["attempts"]), "turns": len(work["turns"]),
                   "reason": clip(body.reason)})
    for a in work["attempts"]:
        await task_attempts.cancel_attempt(
            db, company_id, uuid.UUID(a["task_id"]), uuid.UUID(a["id"]), principal
        )
    for t in work["turns"]:
        await chat_turns.request_cancel(
            db, company_id, uuid.UUID(t["session_id"]), uuid.UUID(t["id"]), actor_of(principal)
        )
    return {"cancelled_attempts": len(work["attempts"]), "cancelled_turns": len(work["turns"])}


def restriction_view(r: GovernanceRestriction) -> dict[str, Any]:
    return {
        "id": str(r.id), "scope": r.scope, "kind": r.kind,
        "agent_id": str(r.agent_id) if r.agent_id else None, "active": r.active,
        "reason": r.reason, "created_by": r.created_by, "created_at": _iso(r.created_at),
        "released_by": r.released_by, "released_at": _iso(r.released_at),
    }


async def restrictions(db: Any, company_id: uuid.UUID) -> dict[str, Any]:
    rows = await overlay.active_restrictions(db, company_id, None)
    company = next((r for r in rows if r.scope == "company"), None)
    agents = (
        await db.execute(
            select(GovernanceRestriction).where(
                GovernanceRestriction.company_id == company_id,
                GovernanceRestriction.active == True,  # noqa: E712
                GovernanceRestriction.scope == "agent",
            )
        )
    ).scalars().all()
    return {
        "lockdown": restriction_view(company) if company else None,
        "isolated_agents": [restriction_view(r) for r in agents],
    }


async def _open(
    db: Any, company_id: uuid.UUID, principal: Any, *, scope: str, kind: str,
    agent_id: uuid.UUID | None, reason: str,
) -> dict[str, Any]:
    existing = (
        await db.execute(
            select(GovernanceRestriction).where(
                GovernanceRestriction.company_id == company_id,
                GovernanceRestriction.scope == scope,
                GovernanceRestriction.kind == kind,
                GovernanceRestriction.agent_id == agent_id
                if agent_id else GovernanceRestriction.agent_id.is_(None),
                GovernanceRestriction.active == True,  # noqa: E712
            )
        )
    ).scalars().first()
    if existing is not None:
        fail(409, "ALREADY_ACTIVE", f"A {kind} is already active")
    row = GovernanceRestriction(
        company_id=company_id, scope=scope, kind=kind, agent_id=agent_id,
        reason=clip(reason), created_by=actor_of(principal),
    )
    db.add(row)
    await db.flush()
    await audit(db, company_id, principal, f"{kind}.started", "restriction", row.id,
                {"scope": scope, "agent_id": str(agent_id) if agent_id else None,
                 "reason": row.reason})
    return restriction_view(row)


async def _close(
    db: Any, company_id: uuid.UUID, principal: Any, *, scope: str, kind: str,
    agent_id: uuid.UUID | None, reason: str,
) -> dict[str, Any]:
    where = [
        GovernanceRestriction.company_id == company_id,
        GovernanceRestriction.scope == scope,
        GovernanceRestriction.kind == kind,
        GovernanceRestriction.active == True,  # noqa: E712
        GovernanceRestriction.agent_id == agent_id
        if agent_id else GovernanceRestriction.agent_id.is_(None),
    ]
    row = (await db.execute(select(GovernanceRestriction).where(*where))).scalars().first()
    if row is None:
        fail(409, "NOT_ACTIVE", f"No {kind} is active")
    await db.execute(
        update(GovernanceRestriction)
        .where(*where)
        .values(active=False, released_by=actor_of(principal), released_at=overlay.now())
    )
    await audit(db, company_id, principal, f"{kind}.released", "restriction", row.id,
                {"scope": scope, "agent_id": str(agent_id) if agent_id else None,
                 "reason": clip(reason)})
    await db.refresh(row)
    return restriction_view(row)


def _confirm(given: str, phrase: str) -> None:
    if given.strip() != phrase:
        fail(422, "CONFIRMATION_REQUIRED", f"Type {phrase} to confirm")


async def lockdown(
    db: Any, company_id: uuid.UUID, principal: Any, body: LockdownBody
) -> dict[str, Any]:
    _confirm(body.confirm, LOCKDOWN_PHRASE)
    return await _open(db, company_id, principal, scope="company", kind="lockdown",
                       agent_id=None, reason=body.reason)


async def release_lockdown(
    db: Any, company_id: uuid.UUID, principal: Any, body: LockdownBody
) -> dict[str, Any]:
    _confirm(body.confirm, RELEASE_PHRASE)
    return await _close(db, company_id, principal, scope="company", kind="lockdown",
                        agent_id=None, reason=body.reason)


async def isolate(
    db: Any, company_id: uuid.UUID, principal: Any, agent_id: uuid.UUID, body: IsolateBody
) -> dict[str, Any]:
    await _agent(db, company_id, agent_id)
    return await _open(db, company_id, principal, scope="agent", kind="isolation",
                       agent_id=agent_id, reason=body.reason)


async def release_isolation(
    db: Any, company_id: uuid.UUID, principal: Any, agent_id: uuid.UUID, body: IsolateBody
) -> dict[str, Any]:
    await _agent(db, company_id, agent_id)
    return await _close(db, company_id, principal, scope="agent", kind="isolation",
                        agent_id=agent_id, reason=body.reason)


async def timeline(
    db: Any, company_id: uuid.UUID, *, action: str | None, limit: int, offset: int
) -> dict[str, Any]:
    """Governance audit entries, newest first. Their details hold ids and bounded reasons only."""
    query = select(AuditLog).where(
        AuditLog.company_id == company_id, AuditLog.action.like("governance.%")
    )
    if action:
        query = query.where(AuditLog.action == action)
    rows = (
        await db.execute(
            query.order_by(AuditLog.created_at.desc(), AuditLog.id).limit(limit).offset(offset)
        )
    ).scalars().all()
    return {
        "items": [
            {"id": str(r.id), "action": r.action, "actor": r.actor_id,
             "resource_type": r.resource_type, "resource_id": r.resource_id,
             "details": r.details, "at": _iso(r.created_at)}
            for r in rows
        ],
        "limit": limit, "offset": offset,
    }
