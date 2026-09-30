"""Effective access: what one agent may do right now, and why.

The decision for a tool capability is made by the same pieces the runtime uses:
:func:`nexus.tools.access.decide_policy` on the company's ToolPolicy rules, RBAC, and the
Governance Studio overlay (restrictions and temporary access). Everything is loaded into a
:class:`Snapshot` with a fixed number of queries, then each capability is decided in memory, so
the cost does not grow with the catalogue. A parity test holds this to
:func:`nexus.tools.access.check_tool_access`.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from sqlalchemy import func
from sqlmodel import select

from nexus.governance.rbac import role_allows
from nexus.models.agent import Agent
from nexus.models.governance_studio import (
    GovernancePolicyVersion,
    GovernanceRestriction,
    GovernanceTempAccess,
)
from nexus.models.secret import Secret, SecretBinding
from nexus.models.tool_invocation import ToolInvocation
from nexus.services.governance_studio.catalog import (
    APPROVAL_ONLY,
    DISPLAY_ONLY,
    ENFORCED,
    UNSUPPORTED,
    build_catalog,
    gate_status,
)
from nexus.tools import governance_overlay as overlay
from nexus.tools.access import PolicyInputs, decide_policy, load_policy_inputs
from nexus.tools.autonomy import classify_action

AGENT_ROLE = "agent"
GRANT_LOOKBACK = 200

STATES = (
    "allowed",
    "denied",
    "approval_required",
    "inherited",
    "temporarily_allowed",
    "temporarily_denied",
    "unsupported",
    "misconfigured",
    "expired",
)

_DECISION = {
    "allowed": "allow",
    "inherited": "allow",
    "temporarily_allowed": "allow",
    "approval_required": "require_approval",
    "denied": "deny",
    "temporarily_denied": "deny",
    "expired": "deny",
}


@dataclass
class Snapshot:
    """One agent's governance state, loaded once."""

    agent: Agent
    inputs: PolicyInputs
    restrictions: list[GovernanceRestriction]
    grants: list[GovernanceTempAccess]
    version: int | None
    last_used: dict[str, datetime] = field(default_factory=dict)
    secret_bindings: int = 0
    at: datetime = field(default_factory=overlay.now)
    role: str = AGENT_ROLE


async def load_snapshot(
    db: Any, company_id: uuid.UUID, agent: Agent, *, with_usage: bool = True
) -> Snapshot:
    """A fixed number of queries, whatever the catalogue size."""
    inputs = await load_policy_inputs(db, company_id, agent)
    restrictions = await overlay.active_restrictions(db, company_id, agent.id)
    grants = list(
        (
            await db.execute(
                select(GovernanceTempAccess)
                .where(
                    GovernanceTempAccess.company_id == company_id,
                    GovernanceTempAccess.agent_id == agent.id,
                )
                .order_by(GovernanceTempAccess.created_at.desc())
                .limit(GRANT_LOOKBACK)
            )
        ).scalars()
    )
    version = (
        await db.execute(
            select(func.max(GovernancePolicyVersion.version_number)).where(
                GovernancePolicyVersion.company_id == company_id
            )
        )
    ).scalar()
    snap = Snapshot(agent, inputs, restrictions, grants, version)
    if with_usage:
        rows = await db.execute(
            select(ToolInvocation.tool_name, func.max(ToolInvocation.created_at))
            .where(
                ToolInvocation.company_id == company_id,
                ToolInvocation.agent_id == agent.id,
                ToolInvocation.status == "success",
            )
            .group_by(ToolInvocation.tool_name)
        )
        snap.last_used = {name: at for name, at in rows.all()}
    snap.secret_bindings = (
        await db.execute(
            select(func.count())
            .select_from(SecretBinding)
            .join(Secret, Secret.id == SecretBinding.secret_id)
            .where(
                Secret.company_id == company_id,
                SecretBinding.agent_id == agent.id,
                SecretBinding.revoked == False,  # noqa: E712
            )
        )
    ).scalar_one()
    return snap


def _result(
    cap: dict[str, Any], snap: Snapshot, state: str, code: str, why: str, **extra: Any
) -> dict[str, Any]:
    used = snap.last_used.get(cap.get("tool_name"))
    return {
        "capability_id": cap["id"],
        "state": state,
        "decision": _DECISION.get(state, "none"),
        "code": code,
        "explanation": why,
        "source": extra.pop("source", None),
        "version_id": snap.version,
        "inheritance_source": extra.pop("inheritance_source", None),
        "conditions": extra.pop("conditions", None),
        "scope": {"agent_id": str(snap.agent.id)},
        "approval": extra.pop("approval", {"required": False}),
        "validity": extra.pop("validity", None),
        "last_used": used.isoformat() if used else None,
        "backend_support": cap["support"],
        "gate": gate_status() if cap["support"] == ENFORCED else None,
        **extra,
    }


def _approval(snap: Snapshot, cap: dict[str, Any]) -> dict[str, Any]:
    bucket = cap.get("bucket") or classify_action(cap.get("tool_name") or "")
    level = (snap.agent.autonomy_policy or {}).get(bucket, 1)
    return {"required": level == 3, "level": level, "bucket": bucket}


def _validity(g: GovernanceTempAccess) -> dict[str, Any]:
    return {
        "grant_id": str(g.id),
        "starts_at": g.starts_at.isoformat(),
        "expires_at": g.expires_at.isoformat(),
        "uses_left": None if g.max_uses is None else max(g.max_uses - g.used_count, 0),
    }


def _is_live(g: GovernanceTempAccess, at: datetime) -> bool:
    return (
        g.status == "active"
        and g.starts_at <= at < g.expires_at
        and (g.max_uses is None or g.used_count < g.max_uses)
    )


def decide(snap: Snapshot, cap: dict[str, Any]) -> dict[str, Any]:
    """The effective decision for one capability."""
    support = cap["support"]
    if support == UNSUPPORTED:
        return _result(
            cap, snap, "unsupported", "NOT_ENFORCEABLE",
            "No preventive enforcement exists for this capability, so it cannot be controlled.",
        )
    if support == DISPLAY_ONLY:
        return _decide_display(snap, cap)
    if support == APPROVAL_ONLY:
        ap = _approval(snap, cap)
        if ap["required"]:
            return _result(
                cap, snap, "approval_required", "AUTONOMY_L3",
                "The agent's autonomy level requires approval first.",
                source="autonomy policy", approval=ap,
            )
        notify = " and notifies an operator." if ap["level"] == 2 else "."
        return _result(
            cap, snap, "allowed", f"AUTONOMY_L{ap['level']}", "Runs" + notify,
            source="autonomy policy", approval=ap,
        )

    name, risk = cap["tool_name"], cap["risk"]
    if not role_allows(snap.role, "execute", "tool", name):
        return _result(
            cap, snap, "denied", "RBAC_DENIED",
            f"Role '{snap.role}' may not execute tools.", source="rbac",
        )

    if (risk not in overlay.READ_RISKS or cap["explicit_allow_required"]) and snap.restrictions:
        r = snap.restrictions[0]
        label = "Company lockdown" if r.kind == "lockdown" else "Agent isolation"
        return _result(
            cap, snap, "denied", "RESTRICTION_ACTIVE",
            f"{label} is active: {r.reason}", source=f"restriction:{r.id}",
        )

    live = [
        g for g in snap.grants
        if g.tool_name == name and g.session_id is None and _is_live(g, snap.at)
    ]
    deny = next((g for g in live if g.effect == "deny"), None)
    if deny is not None:
        return _result(
            cap, snap, "temporarily_denied", "TEMP_DENY", "A temporary deny is active.",
            source=f"grant:{deny.id}", validity=_validity(deny),
        )

    policy = decide_policy(snap.inputs, name, risk)
    rule = next((r for r in snap.inputs.rules if r.id == policy.matched_policy_id), None)
    conditions = rule.conditions if rule else None
    if policy.allowed:
        ap = _approval(snap, cap)
        if ap["required"]:
            state = "approval_required"
        else:
            state = "allowed" if rule is not None else "inherited"
        return _result(
            cap, snap, state, "POLICY_ALLOW" if rule else "DEFAULT_ALLOW", policy.reason,
            source=f"policy:{rule.name}" if rule else snap.inputs.default_source,
            inheritance_source=None if rule else snap.inputs.default_source,
            conditions=conditions, approval=ap,
        )
    if rule is not None:
        return _result(
            cap, snap, "denied", "POLICY_DENY", policy.reason,
            source=f"policy:{rule.name}", conditions=conditions,
        )
    allow = next((g for g in live if g.effect == "allow"), None)
    if allow is not None:
        ap = _approval(snap, cap)
        return _result(
            cap, snap, "approval_required" if ap["required"] else "temporarily_allowed",
            "TEMP_ALLOW", "A temporary allow turns the default deny into an allow.",
            source=f"grant:{allow.id}", validity=_validity(allow), approval=ap,
        )
    lapsed = next(
        (
            g for g in snap.grants
            if g.tool_name == name and g.effect == "allow"
            and (g.status in ("expired", "used_up") or (g.status == "active" and not _is_live(g, snap.at)))  # noqa: E501
        ),
        None,
    )
    if lapsed is not None:
        return _result(
            cap, snap, "expired", "GRANT_EXPIRED",
            "A temporary allow existed but is no longer valid.",
            source=f"grant:{lapsed.id}", validity=_validity(lapsed),
        )
    return _result(
        cap, snap, "denied", "DEFAULT_DENY", policy.reason,
        source=snap.inputs.default_source, inheritance_source=snap.inputs.default_source,
    )


def _decide_display(snap: Snapshot, cap: dict[str, Any]) -> dict[str, Any]:
    cid = cap["id"]
    if cid == "data.secrets":
        n = snap.secret_bindings
        if n:
            return _result(
                cap, snap, "allowed", "SECRET_BOUND",
                f"{n} secret reference(s) bound. Values are never shown.",
                source="secret bindings", count=n,
            )
        return _result(
            cap, snap, "denied", "NO_SECRET_BINDING", "No secrets are bound to this agent.",
            source="secret bindings", count=0,
        )
    if cid == "provider.runtime":
        cfg = snap.agent.adapter_config or {}
        if snap.agent.adapter_type == "cli" and not cfg.get("backend"):
            return _result(
                cap, snap, "misconfigured", "NO_BACKEND",
                "The agent uses a CLI adapter but no backend is set.", source="agent",
            )
        backend = f" ({cfg['backend']})" if cfg.get("backend") else ""
        return _result(
            cap, snap, "allowed", "PROVIDER_SET",
            f"Runs on {snap.agent.adapter_type}{backend}.", source="agent",
        )
    return _result(
        cap, snap, "inherited", "TENANT_SCOPED",
        "Always limited to this company's data by tenant isolation.",
        source="tenant isolation", inheritance_source="company",
    )


async def effective_access(db: Any, company_id: uuid.UUID, agent: Agent) -> dict[str, Any]:
    """The full matrix for one agent."""
    snap = await load_snapshot(db, company_id, agent)
    return {
        "agent_id": str(agent.id),
        "policy_version": snap.version,
        "gates": gate_status(),
        "restricted": [
            {"id": str(r.id), "kind": r.kind, "reason": r.reason} for r in snap.restrictions
        ],
        "capabilities": [{**c, **decide(snap, c)} for c in build_catalog()],
    }
