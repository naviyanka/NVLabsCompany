"""A proposed ToolPolicy rule, validated, and its conversion to the engine's own rule type.

Only the conditions the policy engine understands are accepted, plus a ``governance`` block
(owner and review date) that the engine ignores and the risk rules read. Nothing here is a
second rule format: a proposed rule becomes a :class:`~nexus.tools.policy_engine.PolicyRule`
and is decided by :func:`nexus.tools.access.decide_policy`.
"""

from __future__ import annotations

import uuid
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

from nexus.tools.policy_engine import PolicyRule

MAX_RULES = 100
_LISTS = ("risk_level", "tool_name", "agent_id")
_GOVERNANCE_KEYS = ("owner", "review_by")


class RuleBody(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    effect: Literal["allow", "deny"]
    priority: int = Field(default=100, ge=0, le=100_000)
    description: str | None = Field(default=None, max_length=1000)
    conditions: dict[str, Any] = Field(default_factory=dict)

    @field_validator("conditions")
    @classmethod
    def _known_conditions(cls, value: dict[str, Any]) -> dict[str, Any]:
        unknown = set(value) - {*_LISTS, "time_of_day", "governance"}
        if unknown:
            raise ValueError(f"unknown condition(s): {', '.join(sorted(unknown))}")
        for key in _LISTS:
            items = value.get(key)
            if items is None:
                continue
            if not isinstance(items, list) or len(items) > 50 or not all(
                isinstance(i, str) and 0 < len(i) <= 255 for i in items
            ):
                raise ValueError(f"{key} must be a list of up to 50 short strings")
        window = value.get("time_of_day")
        if window is not None and not (
            isinstance(window, dict)
            and set(window) <= {"start", "end"}
            and all(isinstance(h, int) and 0 <= h <= 24 for h in window.values())
        ):
            raise ValueError("time_of_day must be {start, end} in whole hours 0-24")
        meta = value.get("governance")
        if meta is not None and not (
            isinstance(meta, dict)
            and set(meta) <= set(_GOVERNANCE_KEYS)
            and all(isinstance(v, str) and len(v) <= 255 for v in meta.values())
        ):
            raise ValueError("governance may only hold owner and review_by strings")
        return value


def to_dict(rule: RuleBody) -> dict[str, Any]:
    return rule.model_dump()


def to_policy_rule(rule: dict[str, Any], company_id: uuid.UUID) -> PolicyRule:
    return PolicyRule(
        company_id=company_id,
        name=rule["name"],
        priority=rule["priority"],
        effect=rule["effect"],
        conditions=rule["conditions"],
    )


def from_policy_rule(rule: PolicyRule, description: str | None = None) -> dict[str, Any]:
    return {
        "name": rule.name,
        "effect": rule.effect,
        "priority": rule.priority,
        "description": description,
        "conditions": rule.conditions or {},
    }
