"""Deterministic risk rules. Fixed table, no model, no score: a finding names what matched.

Two kinds of finding:

- **Combinations** over what an agent can hold at once (:func:`combination_findings`). A
  capability is held when policy would allow it, or when nothing can restrict it at all
  (``unsupported``), so an uncontrolled capability counts against the agent.
- **Rule hygiene** over a proposed rule set (:func:`rule_findings`): broad allows,
  high-impact allows with no owner or review date, and a rule set the author also reviews.

A tag nobody carries yet (pr_author, merge, deploy, hire_approve, spend_approve, policy_edit,
policy_approve) keeps its rule in the table, so the rule starts to fire the moment a capability
gains the tag in the catalogue. Tags live in the catalogue (``catalog._TAGS``), not here.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from nexus.services.governance_studio.catalog import catalog_by_id
from nexus.tools.access import EXPLICIT_ALLOW_ONLY

HIGH_RISKS = frozenset({"high", "destructive", "critical"})
HIGH, MEDIUM = "high", "medium"
LONG_GRANT = timedelta(hours=4)

# (id, severity, groups that must each be held, explanation)
COMBINATIONS = (
    ("SECRET_NETWORK_TERMINAL", HIGH,
     (("secret_reference",), ("arbitrary_network",), ("terminal",)),
     "Secret references, arbitrary network access and a terminal can exfiltrate a secret."),
    ("PR_AUTHOR_MERGE", HIGH, (("pr_author", "code_write"), ("merge",)),
     "One agent can write code and merge the pull request, so a change is never reviewed."),
    ("MERGE_DEPLOY", HIGH, (("merge",), ("deploy",)),
     "One agent can merge and deploy, so a change reaches production unreviewed."),
    ("HIRE_REQUEST_APPROVE", HIGH, (("hire_request",), ("hire_approve",)),
     "One agent can request a hire and approve it."),
    ("SPEND_REQUEST_APPROVE", HIGH, (("spend_request",), ("spend_approve",)),
     "One agent can request a budget and approve it."),
    ("POLICY_EDIT_APPROVE", HIGH, (("policy_edit",), ("policy_approve",)),
     "One agent can edit a policy and approve the change."),
    ("FS_WRITE_OUTSIDE_SANDBOX", MEDIUM, (("fs_write_outside",),),
     "The agent can write files outside its workspace and nothing restricts it."),
    ("BROWSER_AUTH_EXTERNAL_POST", HIGH, (("browser_authentication",), ("external_post",)),
     "A signed-in browser plus external posting can act as a person in public."),
)


def _finding(code: str, severity: str, detail: str, **extra: Any) -> dict[str, Any]:
    return {"code": code, "severity": severity, "detail": detail, **extra}


def held_ids(decisions: list[dict[str, Any]]) -> set[str]:
    """Capability ids the agent holds: allowed now, or impossible to restrict."""
    return {
        d["capability_id"] for d in decisions
        if d["decision"] == "allow" or d["state"] == "unsupported"
    }


def combination_findings(
    decisions: list[dict[str, Any]], tags: dict[str, list[str]] | None = None
) -> list[dict[str, Any]]:
    """Combination findings; ``tags`` (capability id to tags) defaults to the catalogue's."""
    if tags is None:
        tags = {cid: c["tags"] for cid, c in catalog_by_id().items()}
    held = held_ids(decisions)
    carriers: dict[str, list[str]] = {}
    for cap_id in held:
        for tag in tags.get(cap_id, ()):
            carriers.setdefault(tag, []).append(cap_id)
    out = []
    for code, severity, groups, detail in COMBINATIONS:
        if all(any(tag in carriers for tag in group) for group in groups):
            caps = sorted({c for group in groups for tag in group for c in carriers.get(tag, ())})
            out.append(_finding(code, severity, detail, capabilities=caps))
    return out


def _as_list(value: Any) -> list[str]:
    return [value] if isinstance(value, str) else list(value or [])


def _is_broad(conditions: dict[str, Any]) -> bool:
    """Matches every tool, or a pattern of tools, at a high-risk (or unstated) risk level."""
    names = _as_list(conditions.get("tool_name"))
    levels = set(_as_list(conditions.get("risk_level")))
    return (not names or any("*" in n for n in names)) and (not levels or bool(levels & HIGH_RISKS))


def _is_high_impact(conditions: dict[str, Any]) -> bool:
    names = set(_as_list(conditions.get("tool_name")))
    levels = set(_as_list(conditions.get("risk_level")))
    return _is_broad(conditions) or bool(levels & HIGH_RISKS) or bool(names & EXPLICIT_ALLOW_ONLY)


def rule_findings(
    rules: list[dict[str, Any]], *, author: str | None = None, reviewers: list[str] | None = None
) -> list[dict[str, Any]]:
    out = []
    for rule in rules:
        if rule["effect"] != "allow":
            continue
        cond = rule.get("conditions") or {}
        if _is_broad(cond):
            out.append(_finding(
                "WILDCARD_HIGH_RISK", HIGH,
                "An allow rule matches every tool (or a pattern) at high risk.",
                rule=rule["name"],
            ))
        meta = cond.get("governance") or {}
        if _is_high_impact(cond) and not (meta.get("owner") and meta.get("review_by")):
            out.append(_finding(
                "NO_OWNER_OR_REVIEW_DATE", MEDIUM,
                "A permanent high-impact allow has no owner and review date.",
                rule=rule["name"],
            ))
    if author and author in (reviewers or []):
        out.append(_finding(
            "SELF_REVIEW", HIGH, "The author of this change is also listed as its reviewer."
        ))
    return out


def _high_impact_tool(risk_level: str, tool_name: str | None) -> bool:
    return risk_level in HIGH_RISKS or tool_name in EXPLICIT_ALLOW_ONLY


def grant_findings(grants: list[Any], at: datetime) -> list[dict[str, Any]]:
    """A live high-impact allow that stays open for more than a few hours."""
    hours = LONG_GRANT.total_seconds() / 3600
    return [
        _finding(
            "GRANT_LONG_DURATION", MEDIUM,
            f"A high-impact temporary allow stays open for over {hours:g} hours. Shorten it.",
            grant_id=str(g.id), tool=g.tool_name,
        )
        for g in grants
        if g.effect == "allow" and g.status == "active" and g.starts_at <= at < g.expires_at
        and _high_impact_tool(g.risk_level, g.tool_name) and g.expires_at - g.starts_at > LONG_GRANT
    ]


def approval_findings(decisions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """High-risk capabilities a rule or grant allows outright, with no approval step."""
    caps = catalog_by_id()
    open_ = sorted(
        d["capability_id"] for d in decisions
        if d["decision"] == "allow" and d["code"] in ("POLICY_ALLOW", "TEMP_ALLOW")
        and not d["approval"].get("required")
        and _high_impact_tool(*(caps[d["capability_id"]][k] for k in ("risk", "tool_name")))
    )
    if not open_:
        return []
    return [_finding(
        "HIGH_RISK_NO_APPROVAL", MEDIUM,
        "A rule or grant allows high-risk capabilities with no approval required.",
        capabilities=open_,
    )]
