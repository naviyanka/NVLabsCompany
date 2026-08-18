"""Tests for Policy Engine: evaluation ordering, condition matching, caching, versioning.

Tests cover the full policy evaluation lifecycle including deny-before-allow
ordering, default-deny behavior, condition matching, built-in policy correctness,
caching, versioning, and context building.
"""

import uuid
from datetime import datetime, timezone

import pytest

from nexus.governance.policies.engine import (
    Policy,
    PolicyDecision,
    PolicyEngine,
    PolicyRule,
)
from nexus.governance.policies.context import ContextBuilder, PolicyContext
from nexus.governance.policies.builtin import (
    BUILTIN_POLICIES,
    agent_creation_requires_approval,
    budget_exceeded_deny,
    cross_tenant_access_denied,
    data_deletion_requires_approval,
    external_communication_requires_approval,
    financial_operations_require_approval,
    nighttime_restricted,
    production_deploy_requires_approval,
    rate_limit_per_agent,
    self_modification_denied,
)


# ============================================================
# Policy Evaluation Ordering Tests
# ============================================================


class TestPolicyEvaluationOrdering:
    """Tests that deny rules take precedence over allow rules."""

    def test_deny_beats_allow(self):
        """A deny rule takes precedence over an allow rule."""
        engine = PolicyEngine()

        allow_policy = Policy(
            name="allow_all",
            priority=50,
            rules=[PolicyRule(rule_type="allow", conditions={"action": ["read"]})],
        )
        deny_policy = Policy(
            name="deny_read",
            priority=50,
            rules=[PolicyRule(rule_type="deny", conditions={"action": ["read"]})],
        )

        engine.add_policy(allow_policy)
        engine.add_policy(deny_policy)

        ctx = PolicyContext(action="read")
        decision = engine.evaluate(ctx)

        assert decision.allowed is False
        assert decision.decision_type == "deny"
        assert decision.policy_name == "deny_read"

    def test_deny_beats_require_approval(self):
        """A deny rule takes precedence over require_approval."""
        engine = PolicyEngine()

        approval_policy = Policy(
            name="needs_approval",
            priority=90,
            rules=[PolicyRule(rule_type="require_approval", conditions={"action": ["deploy"]})],
        )
        deny_policy = Policy(
            name="deny_deploy",
            priority=50,
            rules=[PolicyRule(rule_type="deny", conditions={"action": ["deploy"]})],
        )

        engine.add_policy(approval_policy)
        engine.add_policy(deny_policy)

        ctx = PolicyContext(action="deploy")
        decision = engine.evaluate(ctx)

        assert decision.allowed is False
        assert decision.decision_type == "deny"
        assert decision.policy_name == "deny_deploy"

    def test_require_approval_beats_allow(self):
        """A require_approval rule takes precedence over allow."""
        engine = PolicyEngine()

        allow_policy = Policy(
            name="allow_deploy",
            priority=50,
            rules=[PolicyRule(rule_type="allow", conditions={"action": ["deploy"]})],
        )
        approval_policy = Policy(
            name="approval_deploy",
            priority=90,
            rules=[PolicyRule(rule_type="require_approval", conditions={"action": ["deploy"]})],
        )

        engine.add_policy(allow_policy)
        engine.add_policy(approval_policy)

        ctx = PolicyContext(action="deploy")
        decision = engine.evaluate(ctx)

        assert decision.allowed is False
        assert decision.decision_type == "require_approval"
        assert decision.policy_name == "approval_deploy"

    def test_higher_priority_deny_wins(self):
        """Among multiple deny policies, the highest priority one wins."""
        engine = PolicyEngine()

        low_deny = Policy(
            name="low_deny",
            priority=10,
            rules=[PolicyRule(rule_type="deny", conditions={"action": ["write"]})],
        )
        high_deny = Policy(
            name="high_deny",
            priority=100,
            rules=[PolicyRule(rule_type="deny", conditions={"action": ["write"]})],
        )

        engine.add_policy(low_deny)
        engine.add_policy(high_deny)

        ctx = PolicyContext(action="write")
        decision = engine.evaluate(ctx)

        assert decision.allowed is False
        assert decision.decision_type == "deny"
        assert decision.policy_name == "high_deny"


# ============================================================
# Default Deny Tests
# ============================================================


class TestDefaultDeny:
    """Tests for default-deny behavior when no policies match."""

    def test_empty_engine_denies(self):
        """An engine with no policies defaults to deny."""
        engine = PolicyEngine()
        ctx = PolicyContext(action="anything")
        decision = engine.evaluate(ctx)

        assert decision.allowed is False
        assert decision.decision_type == "deny"
        assert "default deny" in decision.reason.lower()

    def test_unmatched_action_denies(self):
        """An action that matches no policy conditions is denied."""
        engine = PolicyEngine()
        engine.add_policy(Policy(
            name="only_read",
            rules=[PolicyRule(rule_type="allow", conditions={"action": ["read"]})],
        ))

        ctx = PolicyContext(action="write")
        decision = engine.evaluate(ctx)

        assert decision.allowed is False
        assert decision.decision_type == "deny"

    def test_disabled_policy_not_evaluated(self):
        """A disabled policy is not evaluated, leading to default deny."""
        engine = PolicyEngine()
        engine.add_policy(Policy(
            name="allow_all",
            enabled=False,
            rules=[PolicyRule(rule_type="allow", conditions={"action": ["read"]})],
        ))

        ctx = PolicyContext(action="read")
        decision = engine.evaluate(ctx)

        assert decision.allowed is False
        assert decision.decision_type == "deny"


# ============================================================
# Condition Matching Tests
# ============================================================


class TestConditionMatching:
    """Tests for condition matching logic in policy rules."""

    def test_actor_type_match(self):
        """Rules match on actor_type condition."""
        engine = PolicyEngine()
        engine.add_policy(Policy(
            name="deny_agents",
            rules=[PolicyRule(
                rule_type="deny",
                conditions={"actor_type": "agent", "action": ["execute"]},
            )],
        ))

        # Agent is denied
        ctx = PolicyContext(actor_type="agent", action="execute")
        decision = engine.evaluate(ctx)
        assert decision.allowed is False
        assert decision.decision_type == "deny"

        # User is not matched by this rule, goes to default deny
        ctx = PolicyContext(actor_type="user", action="execute")
        decision = engine.evaluate(ctx)
        assert decision.allowed is False
        assert decision.policy_name == ""  # default deny

    def test_resource_type_match(self):
        """Rules match on resource_type condition."""
        engine = PolicyEngine()
        engine.add_policy(Policy(
            name="allow_read_tasks",
            rules=[PolicyRule(
                rule_type="allow",
                conditions={"action": ["read"], "resource_type": "task"},
            )],
        ))

        # Matches task
        ctx = PolicyContext(action="read", resource_type="task")
        decision = engine.evaluate(ctx)
        assert decision.allowed is True

        # Does not match other resource
        ctx = PolicyContext(action="read", resource_type="secret")
        decision = engine.evaluate(ctx)
        assert decision.allowed is False

    def test_resource_type_list_match(self):
        """Resource type can be a list of valid types."""
        engine = PolicyEngine()
        engine.add_policy(Policy(
            name="allow_read_multiple",
            rules=[PolicyRule(
                rule_type="allow",
                conditions={"action": ["read"], "resource_type": ["task", "agent"]},
            )],
        ))

        ctx = PolicyContext(action="read", resource_type="task")
        assert engine.evaluate(ctx).allowed is True

        ctx = PolicyContext(action="read", resource_type="agent")
        assert engine.evaluate(ctx).allowed is True

        ctx = PolicyContext(action="read", resource_type="secret")
        assert engine.evaluate(ctx).allowed is False

    def test_action_list_match(self):
        """Action condition can be a list of actions."""
        engine = PolicyEngine()
        engine.add_policy(Policy(
            name="allow_crud",
            rules=[PolicyRule(
                rule_type="allow",
                conditions={"action": ["read", "write", "delete"]},
            )],
        ))

        ctx = PolicyContext(action="read")
        assert engine.evaluate(ctx).allowed is True

        ctx = PolicyContext(action="write")
        assert engine.evaluate(ctx).allowed is True

        ctx = PolicyContext(action="execute")
        assert engine.evaluate(ctx).allowed is False

    def test_cost_min_match(self):
        """cost_min condition matches when cost exceeds threshold."""
        engine = PolicyEngine()
        engine.add_policy(Policy(
            name="expensive_needs_approval",
            rules=[PolicyRule(
                rule_type="require_approval",
                conditions={"action": ["purchase"], "cost_min": 10000},
            )],
        ))

        # Under threshold - no match, default deny
        ctx = PolicyContext(action="purchase", cost=5000)
        decision = engine.evaluate(ctx)
        assert decision.decision_type == "deny"
        assert decision.policy_name == ""

        # Over threshold - requires approval
        ctx = PolicyContext(action="purchase", cost=15000)
        decision = engine.evaluate(ctx)
        assert decision.decision_type == "require_approval"

    def test_time_hour_normal_range(self):
        """Time condition matches hours in a normal range (e.g., 17-8 wraps)."""
        engine = PolicyEngine()
        engine.add_policy(Policy(
            name="nighttime_deny",
            rules=[PolicyRule(
                rule_type="deny",
                conditions={"action": ["deploy"], "time_hour_min": 17, "time_hour_max": 8},
            )],
        ))

        # 20:00 is in range (17-8 wraps: 17,18,...,23,0,1,...,8)
        ctx = PolicyContext(
            action="deploy",
            timestamp=datetime(2024, 1, 15, 20, 0, tzinfo=timezone.utc),
        )
        decision = engine.evaluate(ctx)
        assert decision.decision_type == "deny"

        # 3:00 AM is in range
        ctx = PolicyContext(
            action="deploy",
            timestamp=datetime(2024, 1, 15, 3, 0, tzinfo=timezone.utc),
        )
        decision = engine.evaluate(ctx)
        assert decision.decision_type == "deny"

        # 12:00 is NOT in range (17-8 wrapped)
        ctx = PolicyContext(
            action="deploy",
            timestamp=datetime(2024, 1, 15, 12, 0, tzinfo=timezone.utc),
        )
        decision = engine.evaluate(ctx)
        # No match, default deny (because no allow policy either)
        assert decision.policy_name == ""

    def test_sensitivity_level_match(self):
        """Sensitivity level condition matches correctly."""
        engine = PolicyEngine()
        engine.add_policy(Policy(
            name="protect_critical",
            rules=[PolicyRule(
                rule_type="deny",
                conditions={
                    "action": ["delete"],
                    "sensitivity_level": ["high", "critical"],
                },
            )],
        ))

        # Critical resource
        ctx = PolicyContext(action="delete", sensitivity_level="critical")
        decision = engine.evaluate(ctx)
        assert decision.decision_type == "deny"
        assert decision.policy_name == "protect_critical"

        # Low resource - no match
        ctx = PolicyContext(action="delete", sensitivity_level="low")
        decision = engine.evaluate(ctx)
        assert decision.policy_name == ""  # default deny, not the policy

    def test_environment_match(self):
        """Environment conditions match against context environment dict."""
        engine = PolicyEngine()
        engine.add_policy(Policy(
            name="cross_tenant_deny",
            rules=[PolicyRule(
                rule_type="deny",
                conditions={
                    "action": ["read", "write"],
                    "environment": {"cross_tenant": True},
                },
            )],
        ))

        # Cross-tenant access
        ctx = PolicyContext(
            action="read",
            environment={"cross_tenant": True},
        )
        decision = engine.evaluate(ctx)
        assert decision.decision_type == "deny"
        assert decision.policy_name == "cross_tenant_deny"

        # Same-tenant access
        ctx = PolicyContext(
            action="read",
            environment={"cross_tenant": False},
        )
        decision = engine.evaluate(ctx)
        assert decision.policy_name == ""  # default deny, not the cross-tenant policy


# ============================================================
# Budget Cap Tests
# ============================================================


class TestBudgetCap:
    """Tests for budget_cap rule type."""

    def test_budget_cap_denies_over_limit(self):
        """Budget cap denies when cost exceeds the limit."""
        engine = PolicyEngine()
        engine.add_policy(Policy(
            name="budget_limit",
            priority=95,
            rules=[PolicyRule(
                rule_type="budget_cap",
                conditions={"cost_max": 100000},
            )],
        ))

        ctx = PolicyContext(action="purchase", cost=200000)
        decision = engine.evaluate(ctx)
        assert decision.allowed is False
        assert decision.decision_type == "deny"
        assert "budget cap" in decision.reason.lower()

    def test_budget_cap_allows_under_limit(self):
        """Budget cap does not deny when cost is under the limit."""
        engine = PolicyEngine()
        engine.add_policy(Policy(
            name="budget_limit",
            priority=95,
            rules=[PolicyRule(
                rule_type="budget_cap",
                conditions={"cost_max": 100000},
            )],
        ))
        engine.add_policy(Policy(
            name="allow_purchase",
            priority=50,
            rules=[PolicyRule(
                rule_type="allow",
                conditions={"action": ["purchase"]},
            )],
        ))

        ctx = PolicyContext(action="purchase", cost=5000)
        decision = engine.evaluate(ctx)
        assert decision.allowed is True


# ============================================================
# Built-in Policy Tests
# ============================================================


class TestBuiltinPolicies:
    """Tests for pre-configured built-in policies."""

    def test_builtin_policy_count(self):
        """All 10 built-in policies are defined."""
        assert len(BUILTIN_POLICIES) == 10

    def test_all_builtin_policies_have_names(self):
        """All built-in policies have non-empty names."""
        for policy in BUILTIN_POLICIES:
            assert policy.name != ""
            assert policy.description != ""

    def test_all_builtin_policies_enabled(self):
        """All built-in policies are enabled by default."""
        for policy in BUILTIN_POLICIES:
            assert policy.enabled is True

    def test_self_modification_denied_is_deny_type(self):
        """self_modification_denied uses deny rule type."""
        assert self_modification_denied.rules[0].rule_type == "deny"
        assert "agent" in str(self_modification_denied.rules[0].conditions.get("actor_type", ""))

    def test_cross_tenant_denied_is_deny_type(self):
        """cross_tenant_access_denied uses deny rule type."""
        assert cross_tenant_access_denied.rules[0].rule_type == "deny"
        env = cross_tenant_access_denied.rules[0].conditions.get("environment", {})
        assert env.get("cross_tenant") is True

    def test_production_deploy_requires_approval_type(self):
        """production_deploy_requires_approval uses require_approval rule type."""
        assert production_deploy_requires_approval.rules[0].rule_type == "require_approval"
        assert "deploy" in production_deploy_requires_approval.rules[0].conditions.get("action", [])

    def test_budget_exceeded_deny_is_budget_cap(self):
        """budget_exceeded_deny uses budget_cap rule type."""
        assert budget_exceeded_deny.rules[0].rule_type == "budget_cap"
        assert "cost_max" in budget_exceeded_deny.rules[0].conditions

    def test_rate_limit_per_agent_is_rate_limit(self):
        """rate_limit_per_agent uses rate_limit rule type."""
        assert rate_limit_per_agent.rules[0].rule_type == "rate_limit"
        assert rate_limit_per_agent.rules[0].conditions.get("actor_type") == "agent"

    def test_deny_policies_have_highest_priority(self):
        """Deny-type built-in policies have the highest priorities."""
        deny_policies = [p for p in BUILTIN_POLICIES if any(r.rule_type == "deny" for r in p.rules)]
        approval_policies = [p for p in BUILTIN_POLICIES if any(r.rule_type == "require_approval" for r in p.rules)]

        max_approval_priority = max(p.priority for p in approval_policies)
        for dp in deny_policies:
            assert dp.priority >= max_approval_priority

    def test_builtin_policies_in_engine(self):
        """All built-in policies can be loaded into the engine."""
        engine = PolicyEngine()
        for policy in BUILTIN_POLICIES:
            engine.add_policy(policy)

        assert len(engine._policies) == 10

        # Test self-modification denied for agents
        ctx = PolicyContext(
            actor_type="agent",
            action="modify_policy",
            resource_type="governance",
        )
        decision = engine.evaluate(ctx)
        assert decision.allowed is False
        assert decision.decision_type == "deny"


# ============================================================
# Policy Caching Tests
# ============================================================


class TestPolicyCaching:
    """Tests for policy caching behavior."""

    def test_cache_stores_version(self):
        """Adding a policy caches its version."""
        engine = PolicyEngine()
        policy = Policy(name="test_policy", version=1)
        engine.add_policy(policy)

        assert engine.get_cached_version("test_policy") == 1

    def test_cache_updates_on_policy_update(self):
        """Updating a policy updates the cached version."""
        engine = PolicyEngine()
        policy = Policy(name="test_policy", version=1)
        engine.add_policy(policy)
        assert engine.get_cached_version("test_policy") == 1

        # Update the policy (re-add with same name)
        updated_policy = Policy(name="test_policy", version=1)
        engine.add_policy(updated_policy)
        assert engine.get_cached_version("test_policy") == 2

    def test_cache_removed_on_policy_removal(self):
        """Removing a policy removes its cache entry."""
        engine = PolicyEngine()
        policy = Policy(name="test_policy")
        engine.add_policy(policy)
        assert engine.get_cached_version("test_policy") is not None

        engine.remove_policy("test_policy")
        assert engine.get_cached_version("test_policy") is None


# ============================================================
# Policy Versioning Tests
# ============================================================


class TestPolicyVersioning:
    """Tests for policy version tracking."""

    def test_new_policy_starts_at_version_1(self):
        """A newly added policy has version 1."""
        engine = PolicyEngine()
        policy = Policy(name="versioned_policy")
        engine.add_policy(policy)

        stored = engine.get_policy("versioned_policy")
        assert stored is not None
        assert stored.version == 1

    def test_updating_policy_increments_version(self):
        """Updating (re-adding) a policy increments its version."""
        engine = PolicyEngine()
        policy = Policy(name="versioned_policy", version=1)
        engine.add_policy(policy)

        # Re-add policy
        updated = Policy(name="versioned_policy", version=1)
        engine.add_policy(updated)

        stored = engine.get_policy("versioned_policy")
        assert stored is not None
        assert stored.version == 2

    def test_multiple_updates_track_version(self):
        """Multiple updates correctly increment version each time."""
        engine = PolicyEngine()
        policy = Policy(name="multi_update")
        engine.add_policy(policy)

        for i in range(5):
            engine.add_policy(Policy(name="multi_update"))

        stored = engine.get_policy("multi_update")
        assert stored is not None
        assert stored.version == 6  # original 1 + 5 updates


# ============================================================
# Context Builder Tests
# ============================================================


class TestContextBuilder:
    """Tests for ContextBuilder fluent interface."""

    def test_build_minimal_context(self):
        """Building with no configuration yields empty context."""
        ctx = ContextBuilder().build()

        assert ctx.actor_type == ""
        assert ctx.actor_id == ""
        assert ctx.resource_type == ""
        assert ctx.action == ""
        assert ctx.cost == 0

    def test_with_actor(self):
        """with_actor sets actor_type and actor_id."""
        ctx = (
            ContextBuilder()
            .with_actor("agent", "agent-123")
            .build()
        )

        assert ctx.actor_type == "agent"
        assert ctx.actor_id == "agent-123"

    def test_with_resource(self):
        """with_resource sets resource_type, resource_id, and sensitivity_level."""
        ctx = (
            ContextBuilder()
            .with_resource("database", "prod-db-1", "critical")
            .build()
        )

        assert ctx.resource_type == "database"
        assert ctx.resource_id == "prod-db-1"
        assert ctx.sensitivity_level == "critical"

    def test_with_action(self):
        """with_action sets the action field."""
        ctx = (
            ContextBuilder()
            .with_action("deploy")
            .build()
        )

        assert ctx.action == "deploy"

    def test_with_cost(self):
        """with_cost sets the cost field."""
        ctx = (
            ContextBuilder()
            .with_cost(50000)
            .build()
        )

        assert ctx.cost == 50000

    def test_with_environment(self):
        """with_environment sets time, load, and incidents."""
        fixed_time = datetime(2024, 6, 15, 14, 30, tzinfo=timezone.utc)
        ctx = (
            ContextBuilder()
            .with_environment(time=fixed_time, load=0.85, incidents=["INC-001"])
            .build()
        )

        assert ctx.timestamp == fixed_time
        assert ctx.environment["load"] == 0.85
        assert ctx.environment["incidents"] == ["INC-001"]

    def test_chaining(self):
        """All builder methods can be chained."""
        ctx = (
            ContextBuilder()
            .with_actor("user", "user-456")
            .with_resource("task", "task-789", "medium")
            .with_action("write")
            .with_cost(1000)
            .with_environment(load=0.5)
            .build()
        )

        assert ctx.actor_type == "user"
        assert ctx.actor_id == "user-456"
        assert ctx.resource_type == "task"
        assert ctx.resource_id == "task-789"
        assert ctx.sensitivity_level == "medium"
        assert ctx.action == "write"
        assert ctx.cost == 1000
        assert ctx.environment["load"] == 0.5

    def test_default_sensitivity_level(self):
        """Default sensitivity_level is 'low' when not specified."""
        ctx = (
            ContextBuilder()
            .with_resource("task", "task-1")
            .build()
        )

        assert ctx.sensitivity_level == "low"
