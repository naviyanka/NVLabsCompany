"""Deterministic risk rules. Fixed table, no model, no score: a finding names what matched.

Two kinds of finding:

- **Combinations** over what an agent can hold at once (:func:`combination_findings`). A
  capability is held when policy would allow it, or when nothing can restrict it at all
  (``unsupported``), so an uncontrolled capability counts against the agent.
- **Rule hygiene** over a proposed rule set (:func:`rule_findings`): broad allows,
  high-impact allows with no owner or review date, and a rule set the author also reviews.

A tag nobody carries yet (pull-request approval, deploy, hire approval, spend approval) keeps
its rule in the table, so the rule starts to fire the moment a capability gains the tag.
"""

from __future__ import annotations

from typing import Any

from nexus.tools.access import EXPLICIT_ALLOW_ONLY

HIGH_RISKS = frozenset({"high", "destructive", "critical"})
HIGH, MEDIUM = "high", "medium"

_NETWORK = {"tool.http-request", "tool.msg-discord-send", "tool.msg-slack-send",
            "tool.msg-telegram-send", "tool.msg-webhook-notify", "exec.send_external_message"}

TAGS: dict[str, frozenset[str]] = {
    "data.secrets": frozenset({"secret"}),
    "computer.terminal": frozenset({"terminal"}),
    "exec.execute_code": frozenset({"terminal"}),
    "exec.write_file": frozenset({"code_write"}),
    "computer.filesystem_write": frozenset({"code_write", "fs_write_outside"}),
    "computer.browser": frozenset({"browser_auth"}),
    "exec.spend": frozenset({"spend_request"}),
    "org.ceo_request_hire": frozenset({"hire_request"}),
    "org.manager_request_hire": frozenset({"hire_request"}),
    **{cap: frozenset({"network", "external_post"}) for cap in _NETWORK},
}

# (id, severity, groups that must each be held, explanation)
COMBINATIONS = (
    ("SECRET_NETWORK_TERMINAL", HIGH, (("secret",), ("network",), ("terminal",)),
     "Secret references, network access and a terminal together can exfiltrate a secret."),
    ("CODE_WRITE_PR_APPROVE", HIGH, (("code_write",), ("pr_approve", "pr_merge")),
     "One agent can write code and approve or merge the pull request."),
    ("MERGE_DEPLOY", HIGH, (("pr_merge",), ("deploy",)),
     "One agent can merge and deploy, so a change reaches production unreviewed."),
    ("HIRE_REQUEST_APPROVE", HIGH, (("hire_request",), ("hire_approve",)),
     "One agent can request a hire and approve it."),
    ("SPEND_REQUEST_APPROVE", HIGH, (("spend_request",), ("spend_approve",)),
     "One agent can request a budget and approve it."),
    ("FS_WRITE_OUTSIDE_SANDBOX", MEDIUM, (("fs_write_outside",),),
     "The agent can write files outside its workspace and nothing restricts it."),
    ("BROWSER_AUTH_EXTERNAL_POST", HIGH, (("browser_auth",), ("external_post",)),
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


def combination_findings(decisions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    held = held_ids(decisions)
    carriers: dict[str, list[str]] = {}
    for cap_id in held:
        for tag in TAGS.get(cap_id, ()):
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
