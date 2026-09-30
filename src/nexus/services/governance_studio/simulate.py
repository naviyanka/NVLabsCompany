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
from nexus.services.governance_studio.catalog import build_catalog, catalog_by_id
from nexus.services.governance_studio.errors import fail


class SimulateBody(BaseModel):
    agent_id: uuid.UUID
    capability_id: str = Field(min_length=1, max_length=255)
    session_id: uuid.UUID | None = None
    proposed_rules: list[rules.RuleBody] | None = Field(default=None, max_length=rules.MAX_RULES)


def _summary(d: dict[str, Any]) -> dict[str, Any]:
    keys = ("state", "decision", "code", "explanation", "source", "approval", "validity")
    return {k: d[k] for k in keys}


def _findings(snap: effective.Snapshot, rule_dicts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    decisions = [effective.decide(snap, c) for c in build_catalog()]
    return risk.combination_findings(decisions) + risk.rule_findings(rule_dicts)


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
    }
    if body.proposed_rules is None:
        out["findings"] = _findings(snap, live)
        return out
    proposed = [rules.to_dict(r) for r in body.proposed_rules]
    trial = replace(
        snap,
        inputs=replace(
            snap.inputs, rules=[rules.to_policy_rule(r, company_id) for r in proposed]
        ),
    )
    out["proposed"] = _summary(effective.decide(trial, cap))
    out["findings"] = _findings(trial, proposed)
    return out
