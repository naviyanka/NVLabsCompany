"""Temporary allows and denies for one agent and one named tool.

- A deny is active at once: tightening never waits for a second person.
- An allow for a read-risk tool is active at once. An allow for anything else, including every
  explicit-allow-only tool, waits for an approval that someone other than the requester gives
  (:class:`~nexus.services.approval_service.ApprovalService`), and is short-lived.
- Every grant names one tool exactly and ends at a fixed time, so there is no wildcard and no
  open-ended high-risk allow.
- Spending a use is the runtime's job (``governance_overlay.consume_temp_grant``); this module
  only creates, decides and revokes.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from pydantic import BaseModel, Field
from sqlalchemy import or_, update
from sqlmodel import select

from nexus.models.agent import Agent
from nexus.models.governance_studio import GovernanceTempAccess
from nexus.services.approval_service import ApprovalService
from nexus.services.governance_studio.audit import actor_of, audit, clip
from nexus.services.governance_studio.catalog import build_catalog
from nexus.services.governance_studio.errors import fail
from nexus.tools import governance_overlay as overlay

APPROVAL_TYPE = "governance_temp_access"
MAX_ALLOW = timedelta(hours=24)
MAX_READ_ALLOW = timedelta(days=7)
MAX_DENY = timedelta(days=30)
PAGE_MAX = 100


class GrantBody(BaseModel):
    agent_id: uuid.UUID
    tool_name: str = Field(min_length=1, max_length=255)
    effect: Literal["allow", "deny"]
    expires_at: datetime
    max_uses: int | None = Field(default=None, ge=1, le=1000)
    session_id: uuid.UUID | None = None
    reason: str = Field(min_length=5, max_length=500)


class Decision(BaseModel):
    note: str | None = Field(default=None, max_length=500)


class Revoke(BaseModel):
    reason: str = Field(min_length=5, max_length=500)


def _naive_utc(value: datetime) -> datetime:
    return value.astimezone(UTC).replace(tzinfo=None) if value.tzinfo else value


def view(g: GovernanceTempAccess, at: datetime | None = None) -> dict[str, Any]:
    at = at or overlay.now()
    status = g.status
    if status == "active" and g.expires_at <= at:
        status = "expired"
    return {
        "id": str(g.id),
        "agent_id": str(g.agent_id),
        "effect": g.effect,
        "tool_name": g.tool_name,
        "risk_level": g.risk_level,
        "status": status,
        "starts_at": g.starts_at.isoformat(),
        "expires_at": g.expires_at.isoformat(),
        "max_uses": g.max_uses,
        "used_count": g.used_count,
        "session_id": str(g.session_id) if g.session_id else None,
        "reason": g.reason,
        "requested_by": g.requested_by,
        "approved_by": g.approved_by,
        "approval_id": str(g.approval_id) if g.approval_id else None,
        "revoked_by": g.revoked_by,
        "revoked_at": g.revoked_at.isoformat() if g.revoked_at else None,
    }


async def _get(db: Any, company_id: uuid.UUID, grant_id: uuid.UUID) -> GovernanceTempAccess:
    grant = (
        await db.execute(
            select(GovernanceTempAccess).where(
                GovernanceTempAccess.id == grant_id, GovernanceTempAccess.company_id == company_id
            )
        )
    ).scalars().first()
    if grant is None:
        fail(404, "GRANT_NOT_FOUND", "No such grant")
    return grant


async def create(
    db: Any, company_id: uuid.UUID, principal: Any, body: GrantBody
) -> dict[str, Any]:
    agent = (
        await db.execute(
            select(Agent).where(Agent.id == body.agent_id, Agent.company_id == company_id)
        )
    ).scalars().first()
    if agent is None:
        fail(404, "AGENT_NOT_FOUND", "No such agent")
    cap = next(
        (
            c for c in build_catalog()
            if c["support"] == "enforced" and c["tool_name"] == body.tool_name
        ),
        None,
    )
    if cap is None:
        fail(422, "UNKNOWN_TOOL", "Name one enforceable tool exactly; patterns are not accepted")

    now = overlay.now()
    expires = _naive_utc(body.expires_at)
    is_read = cap["risk"] in overlay.READ_RISKS and not cap["explicit_allow_required"]
    limit = MAX_DENY if body.effect == "deny" else (MAX_READ_ALLOW if is_read else MAX_ALLOW)
    if expires <= now:
        fail(422, "EXPIRY_IN_PAST", "The grant must end in the future")
    if expires - now > limit:
        fail(422, "EXPIRY_TOO_LONG", f"This grant may last at most {limit}")

    needs_approval = body.effect == "allow" and not is_read
    grant = GovernanceTempAccess(
        company_id=company_id,
        agent_id=agent.id,
        effect=body.effect,
        tool_name=body.tool_name,
        risk_level=cap["risk"],
        status="pending_approval" if needs_approval else "active",
        starts_at=now,
        expires_at=expires,
        max_uses=body.max_uses,
        session_id=body.session_id,
        reason=clip(body.reason),
        requested_by=actor_of(principal),
    )
    db.add(grant)
    if needs_approval:
        approval = await ApprovalService(db).request_approval(
            company_id,
            APPROVAL_TYPE,
            None,
            {"grant_id": str(grant.id), "agent_id": str(agent.id), "tool_name": body.tool_name,
             "risk_level": cap["risk"], "expires_at": expires.isoformat(),
             "requested_by": grant.requested_by},
            expires_at=expires,
        )
        grant.approval_id = approval.id
    await db.flush()
    await audit(db, company_id, principal, "grant.created", "temp_access", grant.id,
                {"agent_id": str(agent.id), "tool_name": grant.tool_name, "effect": grant.effect,
                 "status": grant.status, "expires_at": expires.isoformat(),
                 "approval_id": str(grant.approval_id) if grant.approval_id else None})
    return view(grant)


async def approve(
    db: Any, company_id: uuid.UUID, principal: Any, grant_id: uuid.UUID, body: Decision
) -> dict[str, Any]:
    """Approve and activate a pending allow. Not by the person who asked for it."""
    grant = await _get(db, company_id, grant_id)
    approver = actor_of(principal)
    if grant.status != "pending_approval":
        fail(409, "GRANT_NOT_PENDING", "This grant is not waiting for approval")
    if approver == grant.requested_by:
        fail(403, "SELF_APPROVAL", "The requester cannot approve their own grant")
    now = overlay.now()
    if grant.expires_at <= now:
        grant.status = "expired"
        await audit(db, company_id, principal, "grant.expired", "temp_access", grant.id)
        return view(grant)

    approval = await ApprovalService(db).approve(grant.approval_id, approver, clip(body.note))
    if approval is None or approval.status != "approved":
        fail(409, "APPROVAL_NOT_PENDING", "The approval was already decided")
    decider = approval.decided_by or approver
    if decider == grant.requested_by:
        fail(403, "SELF_APPROVAL", "The requester cannot approve their own grant")
    result = await db.execute(
        update(GovernanceTempAccess)
        .where(
            GovernanceTempAccess.id == grant.id,
            GovernanceTempAccess.company_id == company_id,
            GovernanceTempAccess.status == "pending_approval",
            GovernanceTempAccess.expires_at > now,
        )
        .values(status="active", approved_by=decider, starts_at=now)
    )
    if not result.rowcount:
        fail(409, "GRANT_NOT_PENDING", "This grant changed while it was being approved")
    await db.refresh(grant)
    await audit(db, company_id, principal, "grant.approved", "temp_access", grant.id,
                {"approval_id": str(grant.approval_id), "approved_by": decider})
    return view(grant)


async def reject(
    db: Any, company_id: uuid.UUID, principal: Any, grant_id: uuid.UUID, body: Decision
) -> dict[str, Any]:
    grant = await _get(db, company_id, grant_id)
    if grant.status != "pending_approval":
        fail(409, "GRANT_NOT_PENDING", "This grant is not waiting for approval")
    await ApprovalService(db).reject(grant.approval_id, actor_of(principal), clip(body.note))
    result = await db.execute(
        update(GovernanceTempAccess)
        .where(
            GovernanceTempAccess.id == grant.id,
            GovernanceTempAccess.company_id == company_id,
            GovernanceTempAccess.status == "pending_approval",
        )
        .values(status="rejected")
    )
    if not result.rowcount:
        fail(409, "GRANT_NOT_PENDING", "This grant changed while it was being rejected")
    await db.refresh(grant)
    await audit(db, company_id, principal, "grant.rejected", "temp_access", grant.id,
                {"approval_id": str(grant.approval_id)})
    return view(grant)


async def revoke(
    db: Any, company_id: uuid.UUID, principal: Any, grant_id: uuid.UUID, body: Revoke
) -> dict[str, Any]:
    """End a grant now. One conditional UPDATE: a use that already ran stays recorded."""
    grant = await _get(db, company_id, grant_id)
    result = await db.execute(
        update(GovernanceTempAccess)
        .where(
            GovernanceTempAccess.id == grant.id,
            GovernanceTempAccess.company_id == company_id,
            GovernanceTempAccess.status.in_(("active", "pending_approval")),
        )
        .values(status="revoked", revoked_by=actor_of(principal), revoked_at=overlay.now())
    )
    if not result.rowcount:
        fail(409, "GRANT_NOT_ACTIVE", "This grant has already ended")
    if grant.approval_id is not None and grant.status == "pending_approval":
        await ApprovalService(db).reject(grant.approval_id, actor_of(principal), "grant revoked")
    await db.refresh(grant)
    await audit(db, company_id, principal, "grant.revoked", "temp_access", grant.id,
                {"reason": clip(body.reason), "used_count": grant.used_count})
    return view(grant)


async def list_grants(
    db: Any,
    company_id: uuid.UUID,
    *,
    agent_id: uuid.UUID | None,
    status: str | None,
    limit: int,
    offset: int,
) -> dict[str, Any]:
    query = select(GovernanceTempAccess).where(GovernanceTempAccess.company_id == company_id)
    if agent_id is not None:
        query = query.where(GovernanceTempAccess.agent_id == agent_id)
    now = overlay.now()
    if status == "expired":
        query = query.where(
            or_(
                GovernanceTempAccess.status == "expired",
                (GovernanceTempAccess.status == "active")
                & (GovernanceTempAccess.expires_at <= now),
            )
        )
    elif status == "active":
        query = query.where(
            GovernanceTempAccess.status == "active", GovernanceTempAccess.expires_at > now
        )
    elif status:
        query = query.where(GovernanceTempAccess.status == status)
    rows = (
        await db.execute(
            query.order_by(GovernanceTempAccess.created_at.desc(), GovernanceTempAccess.id)
            .limit(limit)
            .offset(offset)
        )
    ).scalars().all()
    return {"items": [view(g, now) for g in rows], "limit": limit, "offset": offset}
