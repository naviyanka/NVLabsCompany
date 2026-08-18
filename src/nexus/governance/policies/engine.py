"""Policy Engine - deterministic policy evaluation with caching and versioning."""

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from nexus.governance.policies.context import PolicyContext


@dataclass
class PolicyRule:
    """A single rule within a policy.

    Attributes:
        rule_type: Type of rule (allow, deny, require_approval, rate_limit, budget_cap).
        conditions: Conditions that must match for this rule to apply.
            Supported condition keys: actor_type, actor_id, resource_type,
            resource_id, action, time_hour_min, time_hour_max, cost_max,
            sensitivity_level, environment.
    """

    rule_type: str
    conditions: dict[str, Any] = field(default_factory=dict)


@dataclass
class Policy:
    """A named policy containing one or more rules.

    Attributes:
        id: Unique policy identifier.
        name: Human-readable policy name.
        description: Description of what this policy enforces.
        rules: List of PolicyRule instances evaluated in order.
        priority: Higher priority policies are evaluated first within same rule_type.
        enabled: Whether this policy is currently active.
        version: Policy version, incremented on updates.
        created_at: When the policy was created.
        updated_at: When the policy was last updated.
    """

    id: uuid.UUID = field(default_factory=uuid.uuid4)
    name: str = ""
    description: str = ""
    rules: list[PolicyRule] = field(default_factory=list)
    priority: int = 0
    enabled: bool = True
    version: int = 1
    created_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    updated_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )


@dataclass
class PolicyDecision:
    """Result of a policy evaluation.

    Attributes:
        allowed: Whether the action is allowed.
        decision_type: The type of decision (allow, deny, require_approval).
        policy_name: Name of the policy that produced this decision.
        reason: Human-readable explanation.
    """

    allowed: bool
    decision_type: str
    policy_name: str = ""
    reason: str = ""


class PolicyEngine:
    """Deterministic policy evaluation engine.

    Evaluates policies against a PolicyContext to produce a PolicyDecision.
    Evaluation order: deny > require_approval > allow.
    Default behavior is deny for unmatched actions.

    Supports policy caching (dict-based) and versioning (auto-increment on update).
    """

    def __init__(self) -> None:
        """Initialize the policy engine."""
        self._policies: dict[str, Policy] = {}
        # Cache: policy name -> version (for invalidation tracking)
        self._cache: dict[str, int] = {}

    def add_policy(self, policy: Policy) -> None:
        """Add or update a policy in the engine.

        If a policy with the same name already exists, its version is
        incremented and the policy is replaced.

        Args:
            policy: The policy to add.
        """
        existing = self._policies.get(policy.name)
        if existing:
            policy.version = existing.version + 1
            policy.updated_at = datetime.now(timezone.utc)

        self._policies[policy.name] = policy
        self._cache[policy.name] = policy.version

    def remove_policy(self, policy_name: str) -> bool:
        """Remove a policy from the engine.

        Args:
            policy_name: Name of the policy to remove.

        Returns:
            True if the policy was found and removed.
        """
        if policy_name in self._policies:
            del self._policies[policy_name]
            self._cache.pop(policy_name, None)
            return True
        return False

    def get_policy(self, policy_name: str) -> Policy | None:
        """Get a policy by name.

        Args:
            policy_name: Name of the policy.

        Returns:
            The Policy, or None if not found.
        """
        return self._policies.get(policy_name)

    def get_cached_version(self, policy_name: str) -> int | None:
        """Get the cached version number for a policy.

        Args:
            policy_name: Name of the policy.

        Returns:
            The cached version number, or None if not cached.
        """
        return self._cache.get(policy_name)

    def evaluate(self, context: PolicyContext) -> PolicyDecision:
        """Evaluate all enabled policies against the given context.

        Evaluation order:
        1. All deny rules are checked first (highest priority wins).
        2. All require_approval rules are checked next.
        3. All allow rules are checked last.
        4. If no rule matches, the default decision is deny.

        This ensures deny always takes precedence over other rule types,
        and require_approval takes precedence over allow.

        Args:
            context: The PolicyContext describing the request.

        Returns:
            A PolicyDecision indicating whether the action is allowed.
        """
        # Collect matching rules grouped by type
        deny_matches: list[tuple[Policy, PolicyRule]] = []
        approval_matches: list[tuple[Policy, PolicyRule]] = []
        allow_matches: list[tuple[Policy, PolicyRule]] = []
        rate_limit_matches: list[tuple[Policy, PolicyRule]] = []
        budget_cap_matches: list[tuple[Policy, PolicyRule]] = []

        # Get enabled policies sorted by priority (highest first)
        enabled_policies = sorted(
            (p for p in self._policies.values() if p.enabled),
            key=lambda p: p.priority,
            reverse=True,
        )

        for policy in enabled_policies:
            for rule in policy.rules:
                if self._matches_conditions(rule, context):
                    if rule.rule_type == "deny":
                        deny_matches.append((policy, rule))
                    elif rule.rule_type == "require_approval":
                        approval_matches.append((policy, rule))
                    elif rule.rule_type == "allow":
                        allow_matches.append((policy, rule))
                    elif rule.rule_type == "rate_limit":
                        rate_limit_matches.append((policy, rule))
                    elif rule.rule_type == "budget_cap":
                        budget_cap_matches.append((policy, rule))

        # Evaluation order: deny > budget_cap > rate_limit > require_approval > allow
        if deny_matches:
            policy, rule = deny_matches[0]
            return PolicyDecision(
                allowed=False,
                decision_type="deny",
                policy_name=policy.name,
                reason=policy.description or f"Denied by policy: {policy.name}",
            )

        if budget_cap_matches:
            policy, rule = budget_cap_matches[0]
            cost_max = rule.conditions.get("cost_max", 0)
            if context.cost > cost_max:
                return PolicyDecision(
                    allowed=False,
                    decision_type="deny",
                    policy_name=policy.name,
                    reason=f"Budget cap exceeded: cost {context.cost} > limit {cost_max}",
                )

        if rate_limit_matches:
            # Rate limit rules match but actual enforcement is done externally;
            # here we signal that a rate limit policy applies
            policy, rule = rate_limit_matches[0]
            return PolicyDecision(
                allowed=False,
                decision_type="rate_limit",
                policy_name=policy.name,
                reason=f"Rate limited by policy: {policy.name}",
            )

        if approval_matches:
            policy, rule = approval_matches[0]
            return PolicyDecision(
                allowed=False,
                decision_type="require_approval",
                policy_name=policy.name,
                reason=policy.description or f"Requires approval: {policy.name}",
            )

        if allow_matches:
            policy, rule = allow_matches[0]
            return PolicyDecision(
                allowed=True,
                decision_type="allow",
                policy_name=policy.name,
                reason=f"Allowed by policy: {policy.name}",
            )

        # Default deny - no matching rules
        return PolicyDecision(
            allowed=False,
            decision_type="deny",
            policy_name="",
            reason="No matching policy found - default deny",
        )

    def _matches_conditions(
        self, rule: PolicyRule, context: PolicyContext
    ) -> bool:
        """Check if a rule's conditions match the given context.

        All specified conditions must match (AND logic). A condition
        not present in the rule is considered to match any value.

        Args:
            rule: The PolicyRule with conditions to check.
            context: The PolicyContext to evaluate against.

        Returns:
            True if all conditions match.
        """
        conditions = rule.conditions

        # Actor type matching
        if "actor_type" in conditions:
            if conditions["actor_type"] != context.actor_type:
                return False

        # Actor ID matching
        if "actor_id" in conditions:
            if conditions["actor_id"] != context.actor_id:
                return False

        # Resource type matching
        if "resource_type" in conditions:
            expected = conditions["resource_type"]
            if isinstance(expected, list):
                if context.resource_type not in expected:
                    return False
            elif expected != context.resource_type:
                return False

        # Resource ID matching
        if "resource_id" in conditions:
            if conditions["resource_id"] != context.resource_id:
                return False

        # Action matching
        if "action" in conditions:
            expected = conditions["action"]
            if isinstance(expected, list):
                if context.action not in expected:
                    return False
            elif expected != context.action:
                return False

        # Time-based matching (hour of day)
        if "time_hour_min" in conditions or "time_hour_max" in conditions:
            hour = context.timestamp.hour
            min_hour = conditions.get("time_hour_min", 0)
            max_hour = conditions.get("time_hour_max", 23)
            if min_hour <= max_hour:
                # Normal range (e.g., 9-17)
                if not (min_hour <= hour <= max_hour):
                    return False
            else:
                # Wrapped range (e.g., 22-6 means 22,23,0,1,2,3,4,5,6)
                if not (hour >= min_hour or hour <= max_hour):
                    return False

        # Cost matching (rule matches if cost exceeds threshold)
        if "cost_min" in conditions:
            if context.cost < conditions["cost_min"]:
                return False

        # Cost max (for budget_cap rules)
        if "cost_max" in conditions:
            # For budget_cap rules, condition matches any request (the check
            # is done in evaluate). For other rules, match if cost exceeds.
            if rule.rule_type != "budget_cap":
                if context.cost <= conditions["cost_max"]:
                    return False

        # Sensitivity level matching
        if "sensitivity_level" in conditions:
            expected = conditions["sensitivity_level"]
            if isinstance(expected, list):
                if context.sensitivity_level not in expected:
                    return False
            elif expected != context.sensitivity_level:
                return False

        # Environment matching
        if "environment" in conditions:
            env_conditions = conditions["environment"]
            for key, value in env_conditions.items():
                if key not in context.environment:
                    return False
                if context.environment[key] != value:
                    return False

        return True
