"""Governance Studio's runtime layer over the ToolPolicy decision.

Runs inside :func:`nexus.tools.access.check_tool_access`, after the company's
ToolPolicy rules have been evaluated, so there is one engine and one decision:

- An active **restriction** (company lockdown or agent isolation) is a hard deny for every
  tool that is not read-risk, and for the explicit-allow-only tools.
- A **temporary deny** is a hard deny.
- A **temporary allow** can only turn a *default* deny (no policy matched) into an allow. It
  never overrides an explicit deny rule, RBAC or an identity failure, and an unlisted
  high-risk tool needs the grant to name it exactly (grants hold one literal tool name).

Reading is side-effect free, so the simulator reuses it. A grant is consumed separately, by
:func:`consume_temp_grant`, with one conditional UPDATE so two concurrent calls cannot both
spend a one-use grant, and a revoke or expiry that lands first wins.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import and_, case, or_, update
from sqlalchemy.exc import IntegrityError
from sqlmodel import select

from nexus.models.governance_studio import (
    GovernanceGrantUse,
    GovernanceRestriction,
    GovernanceTempAccess,
)

READ_RISKS = frozenset({"read", "low"})


def now() -> datetime:
    """Naive UTC, matching every timestamp column."""
    return datetime.now(UTC).replace(tzinfo=None)


@dataclass
class Overlay:
    """What the governance layer adds to one decision."""

    problems: list[tuple[str, str, bool]] = field(default_factory=list)
    grant_id: uuid.UUID | None = None
    policy_overridden: bool = False


def live_grant_filter(company_id: uuid.UUID, at: datetime) -> list[Any]:
    """WHERE terms shared by the read and the consume: active, approved, in window, uses left.

    An allow that went through an approval request counts only once someone approved it, so a
    row that is merely marked active without that approval never grants anything.
    """
    return [
        GovernanceTempAccess.company_id == company_id,
        GovernanceTempAccess.status == "active",
        or_(
            GovernanceTempAccess.effect == "deny",
            GovernanceTempAccess.approved_by.is_not(None),
            and_(
                GovernanceTempAccess.approval_id.is_(None),
                GovernanceTempAccess.risk_level.in_(READ_RISKS),
            ),
        ),
        GovernanceTempAccess.starts_at <= at,
        GovernanceTempAccess.expires_at > at,
        or_(
            GovernanceTempAccess.max_uses.is_(None),
            GovernanceTempAccess.used_count < GovernanceTempAccess.max_uses,
        ),
    ]


def _session_scope(session_id: uuid.UUID | None) -> Any:
    """A grant bound to a session only applies inside that session."""
    unbound = GovernanceTempAccess.session_id.is_(None)
    if session_id is None:
        return unbound
    return or_(unbound, GovernanceTempAccess.session_id == session_id)


async def active_restrictions(
    db: Any, company_id: uuid.UUID, agent_id: uuid.UUID | None
) -> list[GovernanceRestriction]:
    scope = GovernanceRestriction.scope == "company"
    if agent_id is not None:
        scope = or_(scope, GovernanceRestriction.agent_id == agent_id)
    return list(
        (
            await db.execute(
                select(GovernanceRestriction).where(
                    GovernanceRestriction.company_id == company_id,
                    GovernanceRestriction.active == True,  # noqa: E712
                    scope,
                )
            )
        ).scalars()
    )


async def evaluate(
    db: Any,
    company_id: uuid.UUID,
    agent_id: uuid.UUID | None,
    tool_name: str,
    risk_level: str,
    policy: Any,
    *,
    explicit_only: bool = False,
    session_id: uuid.UUID | None = None,
    at: datetime | None = None,
) -> Overlay:
    """The restriction and temp-access verdict for one call. Read only."""
    at = at or now()
    out = Overlay()
    if agent_id is None:
        return out

    if risk_level not in READ_RISKS or explicit_only:
        for r in await active_restrictions(db, company_id, agent_id):
            label = "company lockdown" if r.kind == "lockdown" else "agent isolation"
            out.problems.append(("restriction", f"{label} is active", True))

    grants = list(
        (
            await db.execute(
                select(GovernanceTempAccess)
                .where(
                    *live_grant_filter(company_id, at),
                    GovernanceTempAccess.agent_id == agent_id,
                    GovernanceTempAccess.tool_name == tool_name,
                    _session_scope(session_id),
                )
                .order_by(GovernanceTempAccess.expires_at, GovernanceTempAccess.id)
            )
        ).scalars()
    )
    denies = [g for g in grants if g.effect == "deny"]
    if denies:
        out.problems.append(("temp_access", "a temporary deny is active", True))
        return out
    # An explicit-allow-only tool needs a complete approval on the exact grant, always.
    allows = [
        g for g in grants if g.effect == "allow" and (g.approved_by or not explicit_only)
    ]
    if allows and not policy.allowed and policy.matched_policy_id is None:
        out.grant_id = allows[0].id
        out.policy_overridden = True
    return out


def invocation_key(turn_id: uuid.UUID | None, tool_name: str, arguments: Any) -> str | None:
    """Identity of one invocation for replay protection, or ``None`` when there is no turn."""
    if turn_id is None:
        return None
    canon = json.dumps(arguments, sort_keys=True, default=str, separators=(",", ":"))
    return hashlib.sha256(f"{turn_id}|{tool_name}|{canon}".encode()).hexdigest()


class _NotSpentError(Exception):
    """Raised inside the savepoint so the ledger row is undone when no use was spent."""


async def consume_temp_grant(
    db: Any, company_id: uuid.UUID, grant_id: uuid.UUID, key: str | None = None
) -> bool:
    """Spend one use of a grant atomically. ``False`` when it is no longer live.

    With a ``key`` the use is recorded in a ledger whose ``(grant_id, key)`` is unique, so a
    replay of the same invocation is not charged twice: it is let through only while the grant
    has not been revoked or expired.
    """
    at = now()
    used = GovernanceTempAccess.used_count + 1
    spend = (
        update(GovernanceTempAccess)
        .where(GovernanceTempAccess.id == grant_id, *live_grant_filter(company_id, at))
        .values(
            used_count=used,
            status=case(
                (
                    (GovernanceTempAccess.max_uses.is_not(None))
                    & (used >= GovernanceTempAccess.max_uses),
                    "used_up",
                ),
                else_=GovernanceTempAccess.status,
            ),
        )
    )
    if key is None:
        return bool((await db.execute(spend)).rowcount)
    try:
        async with db.begin_nested():
            db.add(GovernanceGrantUse(company_id=company_id, grant_id=grant_id, invocation_key=key))
            await db.flush()
            if not (await db.execute(spend)).rowcount:
                raise _NotSpentError
    except _NotSpentError:
        return False
    except IntegrityError:
        # Same invocation seen before: it already paid. Revoke or expiry still wins.
        return bool(
            (
                await db.execute(
                    select(GovernanceTempAccess.id).where(
                        GovernanceTempAccess.id == grant_id,
                        GovernanceTempAccess.company_id == company_id,
                        GovernanceTempAccess.status.in_(("active", "used_up")),
                        GovernanceTempAccess.expires_at > at,
                    )
                )
            ).first()
        )
    return True
