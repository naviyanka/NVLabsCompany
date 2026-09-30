"""Policy simulator: what would happen, without doing it.

Reads one snapshot and decides in memory with the same code the matrix and the runtime use
(:func:`~nexus.tools.access.decide_policy`, RBAC, restrictions, temporary access). It writes
nothing, spends no grant, calls no tool, model or network, and takes no tool arguments, so
there is nothing to leak. With ``proposed_rules`` it decides the same call against that rule
set instead of the live one, so a change can be compared before it is published.
"""

from __future__ import annotations

import uuid
from dataclasses import replace
from typing import Any

from pydantic import BaseModel, Field

from nexus.models.agent import Agent
from nexus.services.governance_studio import effective, risk, rules
from nexus.services.governance_studio.catalog import UNSUPPORTED, build_catalog, catalog_by_id
from nexus.services.governance_studio.errors import fail


class SimulateBody(BaseModel):
    agent_id: uuid.UUID
    capability_id: str = Field(min_length=1, max_length=255)
    session_id: uuid.UUID | None = None
    proposed_rules: list[rules.RuleBody] | None = Field(default=None, max_length=rules.MAX_RULES)


# The order the real engine asks its questions in. The first "no" (or the final answer) ends it.
_STEPS = (
    ("NOT_ENFORCEABLE", "Capability can be enforced"),
    ("RBAC_DENIED", "Role may execute tools"),
    ("RESTRICTION_ACTIVE", "Company lockdown and agent isolation"),
    ("TEMP_DENY", "Temporary deny"),
    ("POLICY_ALLOW", "Policy rules and profile allow it"),
    ("POLICY_DENY", "Explicit deny rule"),
    ("TEMP_ALLOW", "Temporary allow lifting a default deny"),
    ("DEFAULT_DENY", "Default deny"),
)
_AS_STEP = {"DEFAULT_ALLOW": "POLICY_ALLOW", "GRANT_EXPIRED": "DEFAULT_DENY"}
_INVARIANTS = (
    "Tool-level rules (CEO only, direct reports only, hiring budgets, signature quorum) apply when "
    "the tool really runs. A simulation does not evaluate them."
)


def _steps(code: str) -> list[dict[str, str]]:
    deciding = _AS_STEP.get(code, code)
    codes = [c for c, _ in _STEPS]
    if deciding not in codes:
        return [{"label": "Decided by the capability's support level", "result": "decided"}]
    at = codes.index(deciding)
    return [
        {"label": text, "result": "checked" if i < at else "decided" if i == at else "not reached"}
        for i, (_, text) in enumerate(_STEPS)
    ]


def _blockers(d: dict[str, Any]) -> list[str]:
    out = []
    if d["backend_support"] == UNSUPPORTED:
        out.append("No preventive enforcement exists for this capability")
    gate = d.get("gate") or {}
    out += [f"Feature gate {k} is '{v}', not 'enforce'" for k, v in gate.items() if v != "enforce"]
    return out


def _summary(d: dict[str, Any]) -> dict[str, Any]:
    keys = ("state", "decision", "code", "explanation", "source", "approval", "validity",
            "backend_support")
    return {**{k: d[k] for k in keys}, "steps": _steps(d["code"]), "blockers": _blockers(d)}


def trial(snap: effective.Snapshot, rule_dicts: list[dict[str, Any]], company_id: uuid.UUID):
    """The same snapshot, deciding against ``rule_dicts`` instead of the live rules."""
    converted = [rules.to_policy_rule(r, company_id) for r in rule_dicts]
    return replace(snap, inputs=replace(snap.inputs, rules=converted))


def capability_diff(before: effective.Snapshot, after: effective.Snapshot) -> dict[str, Any]:
    """Every policy-controlled capability whose decision changes, and what policy cannot reach."""
    changes, excluded = [], []
    for cap in build_catalog():
        if not (cap["support"] == "enforced" and cap["tool_name"]):
            excluded.append({
                "capability_id": cap["id"], "name": cap["name"], "support": cap["support"],
                "label": "Not enforceable" if cap["support"] == UNSUPPORTED
                else "Not controlled by policy",
            })
            continue
        was, now = effective.decide(before, cap), effective.decide(after, cap)
        if was["decision"] != now["decision"] or was["code"] != now["code"]:
            changes.append({
                "capability_id": cap["id"], "name": cap["name"], "risk": cap["risk"],
                "before": was["decision"], "after": now["decision"], "code": now["code"],
            })
    return {"changes": changes, "excluded": excluded}


async def impact(
    db: Any, company_id: uuid.UUID, agent: Agent, proposed: list[dict[str, Any]]
) -> dict[str, Any]:
    """What publishing ``proposed`` would change for one agent. Writes nothing."""
    snap = await effective.load_snapshot(db, company_id, agent, with_usage=False)
    after = trial(snap, proposed, company_id)
    return {
        "agent_id": str(agent.id),
        "capability_diff": capability_diff(snap, after),
        "findings": _findings(after, proposed),
    }


def _findings(snap: effective.Snapshot, rule_dicts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    decisions = [effective.decide(snap, c) for c in build_catalog()]
    return (
        risk.combination_findings(decisions)
        + risk.approval_findings(decisions)
        + risk.grant_findings(snap.grants, snap.at)
        + risk.rule_findings(rule_dicts)
    )


async def simulate(
    db: Any, company_id: uuid.UUID, agent: Agent, body: SimulateBody
) -> dict[str, Any]:
    cap = catalog_by_id().get(body.capability_id)
    if cap is None:
        fail(404, "CAPABILITY_NOT_FOUND", "No such capability")
    snap = await effective.load_snapshot(db, company_id, agent, with_usage=False)
    snap.session_id = body.session_id
    live = [rules.from_policy_rule(r) for r in snap.inputs.rules]
    out: dict[str, Any] = {
        "simulated": True,
        "capability_id": cap["id"],
        "agent_id": str(agent.id),
        "current": _summary(effective.decide(snap, cap)),
        "proposed": None,
        "notes": [_INVARIANTS, "Nothing was called, spent or sent."],
    }
    if body.proposed_rules is None:
        out["findings"] = _findings(snap, live)
        return out
    proposed = [rules.to_dict(r) for r in body.proposed_rules]
    after = trial(snap, proposed, company_id)
    out["proposed"] = _summary(effective.decide(after, cap))
    out["findings"] = _findings(after, proposed)
    return out
