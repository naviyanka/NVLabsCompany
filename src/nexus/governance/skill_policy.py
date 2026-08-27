"""Versioned skill access policy (Phase 5.4).

A ``skill_policy`` document decides whether an agent may use a skill::

    {
        "schemaVersion": 1,
        "revision": 3,
        "defaultEffect": "allow",
        "rules": [
            {
                "effect": "deny",
                "subject": {"roles": ["intern"]},
                "resource": {"source_types": ["catalog"]},
                "reason": "Interns may not run community skills.",
                "remediation": "Ask an admin to bind the skill locally.",
            }
        ],
    }

Rules are evaluated in document order; the first match wins. When no rule
matches, ``defaultEffect`` applies.

**Absent policy means allow.** ``decision(None, ...)`` returns an allow — the
system is open by default, so adding the policy layer never breaks an existing
company. Restricting access is an explicit act: publish a policy document.

Every decision carries the ``revision`` it was made under, so an audit trail
records which version of the document produced a given allow or deny.
"""

from __future__ import annotations

import fnmatch
from dataclasses import dataclass, field
from typing import Any

SCHEMA_VERSION: int = 1

_DEFAULT_REMEDIATION: str = (
    "Access to this skill is denied by the company skill policy. "
    "Ask an administrator to grant access or to amend the policy rule."
)


@dataclass(frozen=True)
class SkillRef:
    """The skill being requested.

    Attributes:
        id: Stable skill identifier (UUID string or ``'{scope}:{folder}'``).
        key: Matchable skill key or name; glob patterns are matched against it.
        source_type: Where the skill came from (e.g. ``'local'``, ``'catalog'``,
            ``'claude'``, ``'mcp'``).
    """

    id: str = ""
    key: str = ""
    source_type: str = ""


@dataclass(frozen=True)
class SkillDecision:
    """Result of a skill policy evaluation.

    Attributes:
        allowed: Whether use of the skill is permitted.
        effect: ``'allow'`` or ``'deny'``.
        reason: Human-readable explanation.
        matched_rule: The rule dict that produced the decision, or None when
            the default effect applied.
        matched_rule_index: Index of the matched rule, or None for the default.
        revision: Revision of the policy document that produced the decision.
        remediation: What the caller can do about a deny; empty on allow.
    """

    allowed: bool
    effect: str
    reason: str = ""
    matched_rule: dict[str, Any] | None = None
    matched_rule_index: int | None = None
    revision: int = 0
    remediation: str = ""


@dataclass(frozen=True)
class SkillSubject:
    """The actor requesting a skill.

    Attributes:
        agent_id: The agent's identifier as a string.
        roles: Role names held by the agent.
    """

    agent_id: str = ""
    roles: tuple[str, ...] = field(default_factory=tuple)


def _as_list(value: Any) -> list[str]:
    """Coerce a scalar or sequence of scalars to a list of strings."""
    if value is None:
        return []
    if isinstance(value, (str, bytes)):
        return [str(value)]
    if isinstance(value, (list, tuple, set, frozenset)):
        return [str(v) for v in value]
    return [str(value)]


def _matches_any(candidate: str, patterns: list[str]) -> bool:
    """Return True when candidate equals or glob-matches one of patterns."""
    if not candidate:
        return False
    return any(
        candidate == p or fnmatch.fnmatchcase(candidate, p) for p in patterns
    )


def _subject_matches(spec: Any, subject: SkillSubject) -> bool:
    """Check a rule's subject clause against the requesting actor.

    An absent or empty clause, or ``{"all": true}``, matches every agent.
    Otherwise ``agent_ids`` and ``roles`` are ORed together.

    Args:
        spec: The rule's ``subject`` value.
        subject: The actor being evaluated.

    Returns:
        True when the clause matches.
    """
    if spec is None or spec == {} or spec in ("all", "*"):
        return True
    if not isinstance(spec, dict):
        return False
    if spec.get("all") is True:
        return True

    agent_ids = _as_list(spec.get("agent_ids") or spec.get("agent_id"))
    roles = _as_list(spec.get("roles") or spec.get("role"))
    if not agent_ids and not roles:
        return True

    if agent_ids and _matches_any(subject.agent_id, agent_ids):
        return True
    return bool(roles) and any(_matches_any(r, roles) for r in subject.roles)


def _resource_matches(spec: Any, skill: SkillRef) -> bool:
    """Check a rule's resource clause against the requested skill.

    An absent or empty clause matches every skill. Present dimensions
    (``skill_ids``, ``keys``, ``source_types``) are ORed together, so a rule
    naming both an ID and a source type fires on either.

    Args:
        spec: The rule's ``resource`` value.
        skill: The skill being evaluated.

    Returns:
        True when the clause matches.
    """
    if spec is None or spec == {} or spec in ("all", "*"):
        return True
    if not isinstance(spec, dict):
        return False
    if spec.get("all") is True:
        return True

    skill_ids = _as_list(spec.get("skill_ids") or spec.get("skill_id"))
    keys = _as_list(spec.get("keys") or spec.get("key"))
    source_types = _as_list(spec.get("source_types") or spec.get("source_type"))
    if not skill_ids and not keys and not source_types:
        return True

    if skill_ids and _matches_any(skill.id, skill_ids):
        return True
    if keys and _matches_any(skill.key, keys):
        return True
    return bool(source_types) and _matches_any(skill.source_type, source_types)


def decision(
    policy: dict[str, Any] | None,
    subject: SkillSubject,
    skill: SkillRef,
) -> SkillDecision:
    """Evaluate a skill policy document for one (subject, skill) pair.

    Args:
        policy: The ``skill_policy`` document, or None when the company has
            none. A missing document allows everything.
        subject: The agent requesting the skill.
        skill: The skill being requested.

    Returns:
        A SkillDecision carrying the effect, reason, matched rule, the policy
        revision, and a remediation string when denied.

    Raises:
        ValueError: If the document declares an unsupported ``schemaVersion``.
    """
    if not policy:
        return SkillDecision(
            allowed=True,
            effect="allow",
            reason="No skill policy is configured; access is open by default.",
        )

    version = policy.get("schemaVersion", SCHEMA_VERSION)
    if int(version) != SCHEMA_VERSION:
        raise ValueError(
            f"Unsupported skill policy schemaVersion {version!r}; "
            f"this build understands {SCHEMA_VERSION}."
        )

    revision = int(policy.get("revision", 0) or 0)
    default_effect = str(policy.get("defaultEffect", "allow")).lower()
    if default_effect not in ("allow", "deny"):
        raise ValueError(
            f"Invalid defaultEffect {default_effect!r}; expected 'allow' or 'deny'."
        )

    rules = policy.get("rules") or []
    for index, rule in enumerate(rules):
        if not isinstance(rule, dict):
            continue
        if rule.get("enabled") is False:
            continue
        if not _subject_matches(rule.get("subject"), subject):
            continue
        if not _resource_matches(rule.get("resource"), skill):
            continue

        effect = str(rule.get("effect", "deny")).lower()
        allowed = effect == "allow"
        label = rule.get("id") or rule.get("name") or f"rule[{index}]"
        reason = str(
            rule.get("reason")
            or f"Skill policy revision {revision} {effect}s this access via {label}."
        )
        return SkillDecision(
            allowed=allowed,
            effect="allow" if allowed else "deny",
            reason=reason,
            matched_rule=rule,
            matched_rule_index=index,
            revision=revision,
            remediation=(
                ""
                if allowed
                else str(rule.get("remediation") or _DEFAULT_REMEDIATION)
            ),
        )

    allowed = default_effect == "allow"
    return SkillDecision(
        allowed=allowed,
        effect=default_effect,
        reason=(
            f"No skill policy rule matched; default effect "
            f"'{default_effect}' applied at revision {revision}."
        ),
        revision=revision,
        remediation="" if allowed else _DEFAULT_REMEDIATION,
    )
