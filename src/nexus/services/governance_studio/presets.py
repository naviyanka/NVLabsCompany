"""Autonomy presets: a named shape of access that becomes a policy *draft*, never a live change.

A preset is not a second setting. It expands to two ordinary ``ToolPolicy`` rules for one agent
(``agent_id`` condition): an explicit deny for every tool the preset leaves out, and an allow
for the tools it keeps. Both go through the normal draft, diff, review and publish path, so a
human reads the exact change before anything applies.

- The allow rule sits **after** every other rule (highest priority number), so an existing
  explicit deny still wins. The deny rule sits first, so a preset can only tighten what it denies.
- Role and designation are enforced by the tools themselves (``NOT_CEO``, ``NOT_A_DIRECT_REPORT``).
  A preset never tries to replace that: it is refused for an agent that cannot hold it.
- The capability diff is computed by the same decision code as the simulator, before and after,
  so it shows what really changes, including tools a preset allows but an old deny still blocks.
- Only tool capabilities the policy engine enforces are included. Anything else (computer use,
  the approval-only autonomy buckets, data and provider entries) is listed as excluded.
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta
from typing import Any

from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import func
from sqlmodel import select

from nexus.models.agent import Agent
from nexus.services.governance_studio import effective, policies, simulate
from nexus.services.governance_studio.audit import actor_of, audit
from nexus.services.governance_studio.catalog import build_catalog
from nexus.services.governance_studio.errors import fail
from nexus.services.governance_studio.rules import RuleBody

MAX_PRIORITY = 100_000
_STEP = 10
_LIST_MAX = 50

# (key, label, summary). Each level keeps what the one before it allows.
PRESETS: tuple[tuple[str, str, str], ...] = (
    ("advisory", "Advisory", "Read-only tools. It can look and advise, nothing more."),
    ("assisted", "Assisted", "Adds writes that stay inside the company's own data stores."),
    ("task_autonomy", "Task autonomy",
     "Adds tools that reach outside: HTTP requests and messages to chat services."),
    ("delegated_autonomy", "Delegated autonomy",
     "For a manager. Adds delegating tasks to its direct reports."),
    ("operational_autonomy", "Operational autonomy",
     "For a manager. Adds requesting hires, still bound by the hiring rules and approvals."),
    ("restricted_executive_autonomy", "Restricted executive autonomy",
     "For the CEO. Adds the CEO write tools. Hiring keeps its budget and signature rules."),
)
_LEVEL = {key: i for i, (key, _, _) in enumerate(PRESETS)}
_LABEL = {key: label for key, label, _ in PRESETS}


class PresetDraftBody(BaseModel):
    reason: str = Field(min_length=5, max_length=400)
    owner: str | None = Field(default=None, max_length=255)
    review_by: str | None = Field(default=None, max_length=32)


def _level_of(cap: dict[str, Any]) -> int:
    """The lowest preset that keeps this (enforced, named) tool."""
    name = cap["tool_name"]
    if cap["effect_class"] == "read":
        return 0
    if name.startswith("ceo_"):
        return 5
    if name == "manager_request_hire":
        return 4
    if name.startswith("manager_"):
        return 3
    if {"external_post", "arbitrary_network"} & set(cap["tags"]):
        return 2
    return 1


async def _is_manager(db: Any, company_id: uuid.UUID, agent: Agent) -> bool:
    count = (
        await db.execute(
            select(func.count()).select_from(Agent).where(
                Agent.company_id == company_id, Agent.manager_id == agent.id
            )
        )
    ).scalar()
    return bool(count)


def _refusal(key: str, agent: Agent, manager: bool) -> str | None:
    level = _LEVEL[key]
    if level == 5 and not agent.is_ceo:
        return "Only the company's CEO can hold this preset"
    if level in (3, 4) and not manager:
        return "Only an agent with at least one direct report can hold this preset"
    return None


def _holds(cap: dict[str, Any], agent: Agent, manager: bool) -> bool:
    """Whether this agent's designation could ever use the tool."""
    name = cap["tool_name"]
    if name.startswith("ceo_"):
        return agent.is_ceo
    return manager if name.startswith("manager_") else True


def _chunks(names: list[str]) -> list[list[str]]:
    return [names[i : i + _LIST_MAX] for i in range(0, len(names), _LIST_MAX)]


def _rules(
    key: str, agent: Agent, manager: bool, live: list[dict[str, Any]], owner: str, review_by: str
) -> tuple[list[dict[str, Any]], list[str]]:
    tools = [c for c in build_catalog() if c["support"] == "enforced" and c["tool_name"]]
    kept = sorted(
        c["tool_name"] for c in tools if _level_of(c) <= _LEVEL[key] and _holds(c, agent, manager)
    )
    left_out = sorted(c["tool_name"] for c in tools if c["tool_name"] not in kept)
    prefix = f"autonomy:{agent.id}:"
    others = [r for r in live if not r["name"].startswith(prefix)]
    last = max((r["priority"] for r in others), default=0) + _STEP
    if last > MAX_PRIORITY:
        fail(409, "PRIORITY_EXHAUSTED", "Existing rules leave no room after them for this preset")
    meta = {"owner": owner, "review_by": review_by}
    label = _LABEL[key]
    out = []
    for effect, names, priority in (("deny", left_out, 0), ("allow", kept, last)):
        for n, part in enumerate(_chunks(names), 1):
            out.append({
                "name": f"{prefix}{effect}" + (f":{n}" if n > 1 else ""),
                "effect": effect,
                "priority": priority,
                "description": f"Autonomy preset: {label}",
                "conditions": {"agent_id": [str(agent.id)], "tool_name": part, "governance": meta},
            })
    return others + out, kept


async def list_for(db: Any, company_id: uuid.UUID, agent: Agent) -> dict[str, Any]:
    manager = await _is_manager(db, company_id, agent)
    return {"items": [
        {"key": k, "label": label, "summary": summary,
         "unavailable_reason": _refusal(k, agent, manager)}
        for k, label, summary in PRESETS
    ]}


async def _build(
    db: Any, company_id: uuid.UUID, agent: Agent, key: str, owner: str, review_by: str
) -> tuple[list[dict[str, Any]], dict[str, Any], int]:
    if key not in _LEVEL:
        fail(404, "PRESET_NOT_FOUND", "No such autonomy preset")
    manager = await _is_manager(db, company_id, agent)
    reason = _refusal(key, agent, manager)
    if reason:
        fail(409, "PRESET_NOT_AVAILABLE", reason)
    live = await policies.live_rules(db, company_id)
    rules, kept = _rules(key, agent, manager, live, owner, review_by)
    before = await effective.load_snapshot(db, company_id, agent, with_usage=False)
    after = simulate.trial(before, rules, company_id)
    diff = simulate.capability_diff(before, after)
    diff["blocked"] = _still_blocked(after, set(kept))
    return rules, diff, await policies.current_version(db, company_id)


def _still_blocked(after: effective.Snapshot, kept: set[str]) -> list[dict[str, Any]]:
    """Tools the preset keeps that an older explicit deny (or another rule) still blocks."""
    decided = [(c, effective.decide(after, c)) for c in build_catalog() if c["tool_name"] in kept]
    return [
        {"capability_id": c["id"], "code": d["code"]} for c, d in decided if d["decision"] == "deny"
    ]


def _defaults(principal: Any, body: PresetDraftBody | None) -> tuple[str, str]:
    owner = (body.owner if body and body.owner else None) or actor_of(principal)
    review = (body.review_by if body and body.review_by else None) or (
        date.today() + timedelta(days=90)
    ).isoformat()
    return owner, review


async def preview(
    db: Any, company_id: uuid.UUID, principal: Any, agent: Agent, key: str
) -> dict[str, Any]:
    owner, review_by = _defaults(principal, None)
    rules, diff, version = await _build(db, company_id, agent, key, owner, review_by)
    return _out(agent, key, version, rules, diff, draft=None)


async def create_draft(
    db: Any, company_id: uuid.UUID, principal: Any, agent: Agent, key: str, body: PresetDraftBody
) -> dict[str, Any]:
    owner, review_by = _defaults(principal, body)
    rules, diff, version = await _build(db, company_id, agent, key, owner, review_by)
    label = _LABEL[key]
    try:
        draft_body = policies.DraftBody(
            rules=[RuleBody(**r) for r in rules],
            reason=f"{label} preset for {agent.name}: {body.reason}"[:500],
        )
    except (ValidationError, ValueError):
        fail(409, "LIVE_RULES_NOT_EDITABLE",
             "A live rule uses a condition the editor cannot carry; edit policy directly")
    draft = await policies.create_draft(db, company_id, principal, draft_body)
    await audit(db, company_id, principal, "autonomy_preset.drafted", "policy_draft", draft["id"],
                {"agent_id": str(agent.id), "preset": key, "base_version": version})
    return _out(agent, key, version, rules, diff, draft=draft)


def _out(
    agent: Agent, key: str, version: int, rules: list[dict[str, Any]], diff: dict[str, Any],
    *, draft: dict[str, Any] | None,
) -> dict[str, Any]:
    return {
        "agent_id": str(agent.id),
        "preset": key,
        "base_version": version,
        "applied": False,
        "rules": [r for r in rules if r["name"].startswith(f"autonomy:{agent.id}:")],
        "capability_diff": diff,
        "draft": draft,
    }
