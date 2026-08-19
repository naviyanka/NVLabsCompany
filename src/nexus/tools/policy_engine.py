"""Tool Policy Engine - evaluates tool access policies and resolves profiles.

Provides enterprise-grade tool governance through priority-ordered policy evaluation
and hierarchical profile resolution (agent -> department -> company).
"""

import fnmatch
import uuid
from dataclasses import dataclass, field
from typing import Any


@dataclass
class PolicyDecision:
    """Result of a policy evaluation.

    Attributes:
        allowed: Whether the action is allowed.
        matched_policy_id: The ID of the policy that matched, or None if using default.
        reason: Human-readable explanation of the decision.
    """

    allowed: bool
    matched_policy_id: uuid.UUID | None = None
    reason: str = ""


@dataclass
class PolicyRule:
    """In-memory representation of a tool policy for evaluation.

    Attributes:
        id: Unique policy identifier.
        company_id: The company this policy belongs to.
        name: Policy name.
        priority: Evaluation priority (lower number = higher priority).
        effect: The action to take if matched (allow or deny).
        conditions: Conditions that must be met for this policy to match.
        is_active: Whether the policy is currently active.
    """

    id: uuid.UUID = field(default_factory=uuid.uuid4)
    company_id: uuid.UUID | None = None
    name: str = ""
    priority: int = 0
    effect: str = "deny"  # allow, deny
    conditions: dict[str, Any] = field(default_factory=dict)
    is_active: bool = True


@dataclass
class ProfileBinding:
    """In-memory representation of a profile binding for resolution.

    Attributes:
        id: Unique binding identifier.
        profile_id: The profile this binding refers to.
        target_type: The type of target (agent, department, company).
        target_id: The ID of the target.
        priority: Resolution priority (lower number = higher priority).
        default_action: The default action of the bound profile.
    """

    id: uuid.UUID = field(default_factory=uuid.uuid4)
    profile_id: uuid.UUID = field(default_factory=uuid.uuid4)
    target_type: str = "company"  # agent, department, company
    target_id: uuid.UUID = field(default_factory=uuid.uuid4)
    priority: int = 0
    default_action: str = "allow"


class ToolPolicyEngine:
    """Evaluates tool access policies in priority order.

    Policies are evaluated sequentially sorted by priority (lowest first).
    The first matching policy determines the decision. If no policy matches,
    the default action is 'allow'.
    """

    def __init__(self, default_effect: str = "allow") -> None:
        """Initialize the policy engine.

        Args:
            default_effect: Default effect when no policy matches (allow or deny).
        """
        self._policies: list[PolicyRule] = []
        self._default_effect = default_effect

    def load_policies(self, policies: list[PolicyRule]) -> None:
        """Load policies into the engine, sorted by priority.

        Args:
            policies: List of policy rules to load.
        """
        self._policies = sorted(policies, key=lambda p: p.priority)

    def evaluate(
        self,
        agent_id: uuid.UUID,
        tool_name: str,
        risk_level: str,
        context: dict[str, Any] | None = None,
    ) -> PolicyDecision:
        """Evaluate policies for a tool access request.

        Evaluates active policies in priority order. First match wins.

        Args:
            agent_id: The agent requesting tool access.
            tool_name: The name of the tool being accessed.
            risk_level: The risk level of the tool (read, write, destructive).
            context: Additional context for condition evaluation (e.g., time_of_day).

        Returns:
            PolicyDecision indicating whether access is allowed or denied.
        """
        ctx = context or {}

        for policy in self._policies:
            if not policy.is_active:
                continue
            if self._matches(policy, agent_id, tool_name, risk_level, ctx):
                return PolicyDecision(
                    allowed=(policy.effect == "allow"),
                    matched_policy_id=policy.id,
                    reason=f"Matched policy '{policy.name}' (priority {policy.priority})",
                )

        # No policy matched, use default
        return PolicyDecision(
            allowed=(self._default_effect == "allow"),
            matched_policy_id=None,
            reason=f"No matching policy; default action is '{self._default_effect}'",
        )

    def _matches(
        self,
        policy: PolicyRule,
        agent_id: uuid.UUID,
        tool_name: str,
        risk_level: str,
        context: dict[str, Any],
    ) -> bool:
        """Check if a policy's conditions match the request.

        Args:
            policy: The policy to check.
            agent_id: The requesting agent.
            tool_name: The tool being accessed.
            risk_level: The tool's risk level.
            context: Additional evaluation context.

        Returns:
            True if all conditions match.
        """
        conditions = policy.conditions or {}

        # Check risk_level condition
        if "risk_level" in conditions:
            allowed_levels = conditions["risk_level"]
            if isinstance(allowed_levels, str):
                allowed_levels = [allowed_levels]
            if risk_level not in allowed_levels:
                return False

        # Check tool_name pattern condition
        if "tool_name" in conditions:
            patterns = conditions["tool_name"]
            if isinstance(patterns, str):
                patterns = [patterns]
            if not any(fnmatch.fnmatch(tool_name, pat) for pat in patterns):
                return False

        # Check agent_id condition
        if "agent_id" in conditions:
            allowed_agents = conditions["agent_id"]
            if isinstance(allowed_agents, str):
                allowed_agents = [allowed_agents]
            if str(agent_id) not in allowed_agents:
                return False

        # Check time_of_day condition
        if "time_of_day" in conditions:
            time_condition = conditions["time_of_day"]
            current_hour = context.get("hour")
            if current_hour is not None:
                start = time_condition.get("start", 0)
                end = time_condition.get("end", 24)
                if not (start <= current_hour < end):
                    return False

        return True


class ProfileResolver:
    """Resolves the effective profile for an agent.

    Checks bindings in priority order: agent-level, then department-level,
    then company-level. Returns the highest-priority (lowest number) binding.
    """

    def __init__(self) -> None:
        """Initialize the profile resolver."""
        self._bindings: list[ProfileBinding] = []

    def load_bindings(self, bindings: list[ProfileBinding]) -> None:
        """Load profile bindings, sorted by priority.

        Args:
            bindings: List of profile bindings to load.
        """
        self._bindings = sorted(bindings, key=lambda b: b.priority)

    def resolve(
        self,
        agent_id: uuid.UUID,
        department_id: uuid.UUID | None = None,
        company_id: uuid.UUID | None = None,
    ) -> ProfileBinding | None:
        """Resolve the effective profile for an agent.

        Checks agent -> department -> company bindings in priority order.
        The first match at the most specific level wins.

        Args:
            agent_id: The agent to resolve for.
            department_id: The agent's department ID (optional).
            company_id: The agent's company ID (optional).

        Returns:
            The matched ProfileBinding, or None if no binding matches.
        """
        # Build candidate target IDs in specificity order
        targets: list[tuple[str, uuid.UUID]] = [("agent", agent_id)]
        if department_id:
            targets.append(("department", department_id))
        if company_id:
            targets.append(("company", company_id))

        # Check bindings in priority order, preferring more specific targets
        for target_type, target_id in targets:
            for binding in self._bindings:
                if binding.target_type == target_type and binding.target_id == target_id:
                    return binding

        return None
