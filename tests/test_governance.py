"""Tests for governance components: KillSwitch, CircuitBreaker, GuardrailChain, RBAC.

Tests real logic paths including consecutive failure detection, cooldown resets,
content validation, and permission checking.
"""

import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest

from nexus.governance.kill_switch import (
    KillSwitch,
    KillSwitchState,
    CircuitBreaker,
    CircuitBreakerState,
)
from nexus.governance.rbac import (
    RBACManager,
    Permission,
    Role,
    ROLE_ADMIN,
    ROLE_AGENT,
    ROLE_MANAGER,
    ROLE_VIEWER,
    STANDARD_ROLES,
)
from nexus.runtime.cycle_guard import CycleGuard, CycleGuardError


# ============================================================
# KillSwitch Tests
# ============================================================


class TestKillSwitchActivation:
    """Tests for KillSwitch activation and deactivation."""

    def test_activate_pauses_agents(self):
        """Activating kill switch marks all company agents as killed."""
        ks = KillSwitch()
        company_id = uuid.uuid4()
        agent_1 = uuid.uuid4()
        agent_2 = uuid.uuid4()

        ks.register_agent(company_id, agent_1)
        ks.register_agent(company_id, agent_2)

        state = ks.activate(company_id, reason="Safety concern")

        assert state.is_active is True
        assert state.reason == "Safety concern"
        assert agent_1 in state.affected_agents
        assert agent_2 in state.affected_agents
        assert ks.is_agent_killed(agent_1) is True
        assert ks.is_agent_killed(agent_2) is True
        assert ks.is_active(company_id) is True

    def test_deactivate_resumes_agents(self):
        """Deactivating kill switch resumes previously paused agents."""
        ks = KillSwitch()
        company_id = uuid.uuid4()
        agent_1 = uuid.uuid4()
        agent_2 = uuid.uuid4()

        ks.register_agent(company_id, agent_1)
        ks.register_agent(company_id, agent_2)

        ks.activate(company_id, reason="Emergency")
        assert ks.is_agent_killed(agent_1) is True

        ks.deactivate(company_id)

        assert ks.is_active(company_id) is False
        assert ks.is_agent_killed(agent_1) is False
        assert ks.is_agent_killed(agent_2) is False

    def test_activate_single_agent(self):
        """Single-agent kill switch only affects that agent."""
        ks = KillSwitch()
        company_id = uuid.uuid4()
        agent_1 = uuid.uuid4()
        agent_2 = uuid.uuid4()

        ks.register_agent(company_id, agent_1)
        ks.register_agent(company_id, agent_2)

        ks.activate_agent(agent_1, reason="Misbehaving")

        assert ks.is_agent_killed(agent_1) is True
        assert ks.is_agent_killed(agent_2) is False
        assert ks.is_active(company_id) is False

    def test_deactivate_single_agent(self):
        """Deactivating a single agent kill switch resumes only that agent."""
        ks = KillSwitch()
        agent_1 = uuid.uuid4()

        ks.activate_agent(agent_1, reason="Test")
        assert ks.is_agent_killed(agent_1) is True

        ks.deactivate_agent(agent_1)
        assert ks.is_agent_killed(agent_1) is False

    def test_inactive_company_returns_false(self):
        """Company without an activation returns False."""
        ks = KillSwitch()
        company_id = uuid.uuid4()
        assert ks.is_active(company_id) is False

    def test_get_state_returns_none_for_unknown(self):
        """get_state returns None for a company never activated."""
        ks = KillSwitch()
        assert ks.get_state(uuid.uuid4()) is None

    def test_get_state_returns_details(self):
        """get_state returns the full KillSwitchState after activation."""
        ks = KillSwitch()
        company_id = uuid.uuid4()
        ks.register_agent(company_id, uuid.uuid4())

        ks.activate(company_id, reason="Test reason", activated_by="admin")

        state = ks.get_state(company_id)
        assert state is not None
        assert state.reason == "Test reason"
        assert state.activated_by == "admin"
        assert state.activated_at is not None


# ============================================================
# CircuitBreaker Tests
# ============================================================


class TestCircuitBreakerFailures:
    """Tests for CircuitBreaker consecutive failure threshold."""

    def test_opens_after_consecutive_failures(self):
        """Circuit opens after reaching the failure threshold."""
        cb = CircuitBreaker(failure_threshold=3, cooldown_seconds=60)
        agent_id = uuid.uuid4()

        # First two failures: circuit stays closed
        opened = cb.record_failure(agent_id)
        assert opened is False
        assert cb.is_open(agent_id) is False

        opened = cb.record_failure(agent_id)
        assert opened is False
        assert cb.is_open(agent_id) is False

        # Third failure: circuit opens
        opened = cb.record_failure(agent_id)
        assert opened is True
        assert cb.is_open(agent_id) is True

    def test_success_resets_counter(self):
        """A success resets the consecutive failure count."""
        cb = CircuitBreaker(failure_threshold=3, cooldown_seconds=60)
        agent_id = uuid.uuid4()

        cb.record_failure(agent_id)
        cb.record_failure(agent_id)
        assert cb.get_failure_count(agent_id) == 2

        cb.record_success(agent_id)
        assert cb.get_failure_count(agent_id) == 0

        # Need 3 more failures to open
        cb.record_failure(agent_id)
        cb.record_failure(agent_id)
        assert cb.is_open(agent_id) is False

    def test_resets_after_cooldown(self):
        """Circuit breaker resets to closed after cooldown period elapses."""
        cb = CircuitBreaker(failure_threshold=2, cooldown_seconds=10)
        agent_id = uuid.uuid4()

        # Open the circuit
        cb.record_failure(agent_id)
        cb.record_failure(agent_id)
        assert cb.is_open(agent_id) is True

        # Simulate time passing beyond cooldown
        state = cb._get_state(agent_id)
        state.opened_at = datetime.now(timezone.utc) - timedelta(seconds=15)

        # Now the circuit should be half-open (returns False)
        assert cb.is_open(agent_id) is False
        # Consecutive failures should be reset
        assert cb.get_failure_count(agent_id) == 0

    def test_additional_failures_after_open_dont_re_trigger(self):
        """Failures after circuit is open do not re-trigger the open event."""
        cb = CircuitBreaker(failure_threshold=2, cooldown_seconds=60)
        agent_id = uuid.uuid4()

        cb.record_failure(agent_id)
        opened = cb.record_failure(agent_id)
        assert opened is True

        # Additional failure while open
        opened = cb.record_failure(agent_id)
        assert opened is False  # Already open, not a new opening

    def test_manual_reset(self):
        """Manual reset closes the circuit immediately."""
        cb = CircuitBreaker(failure_threshold=2, cooldown_seconds=300)
        agent_id = uuid.uuid4()

        cb.record_failure(agent_id)
        cb.record_failure(agent_id)
        assert cb.is_open(agent_id) is True

        cb.reset(agent_id)
        assert cb.is_open(agent_id) is False
        assert cb.get_failure_count(agent_id) == 0

    def test_independent_agent_circuits(self):
        """Each agent has its own independent circuit breaker."""
        cb = CircuitBreaker(failure_threshold=2, cooldown_seconds=60)
        agent_1 = uuid.uuid4()
        agent_2 = uuid.uuid4()

        cb.record_failure(agent_1)
        cb.record_failure(agent_1)
        assert cb.is_open(agent_1) is True
        assert cb.is_open(agent_2) is False


# ============================================================
# RBAC Tests
# ============================================================


class TestRBACPermissions:
    """Tests for RBACManager permission checking."""

    def test_admin_has_all_permissions(self):
        """Admin role grants access to all actions on all resources."""
        rbac = RBACManager()
        admin_id = uuid.uuid4()
        rbac.assign_role(admin_id, "admin")

        # Admin can do anything
        assert rbac.check_permission(admin_id, "user", "read", "task") is True
        assert rbac.check_permission(admin_id, "user", "write", "agent") is True
        assert rbac.check_permission(admin_id, "user", "execute", "tool") is True
        assert rbac.check_permission(admin_id, "user", "delete", "company") is True
        assert rbac.check_permission(
            admin_id, "user", "anything", "any_resource", "specific-id"
        ) is True

    def test_agent_limited_permissions(self):
        """Agent role has limited permissions (no admin/approval access)."""
        rbac = RBACManager()
        agent_id = uuid.uuid4()
        rbac.assign_role(agent_id, "agent")

        # Agent can read/write tasks and execute tools
        assert rbac.check_permission(agent_id, "agent", "read", "task") is True
        assert rbac.check_permission(agent_id, "agent", "write", "task") is True
        assert rbac.check_permission(agent_id, "agent", "execute", "tool") is True
        assert rbac.check_permission(agent_id, "agent", "read", "memory") is True
        assert rbac.check_permission(agent_id, "agent", "write", "memory") is True

        # Agent cannot approve things or manage companies
        assert rbac.check_permission(agent_id, "agent", "approve", "approval") is False
        assert rbac.check_permission(agent_id, "agent", "delete", "company") is False

    def test_viewer_read_only(self):
        """Viewer role can only read resources."""
        rbac = RBACManager()
        viewer_id = uuid.uuid4()
        rbac.assign_role(viewer_id, "viewer")

        assert rbac.check_permission(viewer_id, "user", "read", "task") is True
        assert rbac.check_permission(viewer_id, "user", "read", "agent") is True
        assert rbac.check_permission(viewer_id, "user", "write", "task") is False
        assert rbac.check_permission(viewer_id, "user", "execute", "tool") is False

    def test_manager_can_approve(self):
        """Manager role can approve operations."""
        rbac = RBACManager()
        manager_id = uuid.uuid4()
        rbac.assign_role(manager_id, "manager")

        assert rbac.check_permission(manager_id, "user", "approve", "approval") is True
        assert rbac.check_permission(manager_id, "user", "write", "task") is True
        assert rbac.check_permission(manager_id, "user", "write", "agent") is True

    def test_no_role_no_permissions(self):
        """Actor without a role has no permissions."""
        rbac = RBACManager()
        unknown_id = uuid.uuid4()

        assert rbac.check_permission(unknown_id, "user", "read", "task") is False
        assert rbac.check_permission(unknown_id, "user", "write", "task") is False

    def test_explicit_permission_grant(self):
        """Explicit permissions work independently of roles."""
        rbac = RBACManager()
        actor_id = uuid.uuid4()

        # No role assigned, but grant a specific permission
        perm = Permission(action="execute", resource_type="tool", resource_id="special-tool")
        rbac.grant_permission(actor_id, perm)

        assert rbac.check_permission(
            actor_id, "agent", "execute", "tool", "special-tool"
        ) is True
        # Other permissions still denied
        assert rbac.check_permission(actor_id, "agent", "write", "task") is False

    def test_revoke_permission(self):
        """Revoking a permission removes access."""
        rbac = RBACManager()
        actor_id = uuid.uuid4()

        perm = Permission(action="read", resource_type="secret")
        rbac.grant_permission(actor_id, perm)
        assert rbac.check_permission(actor_id, "user", "read", "secret") is True

        rbac.revoke_permission(actor_id, perm)
        assert rbac.check_permission(actor_id, "user", "read", "secret") is False

    def test_assign_invalid_role_returns_false(self):
        """Assigning a non-existent role returns False."""
        rbac = RBACManager()
        actor_id = uuid.uuid4()

        result = rbac.assign_role(actor_id, "nonexistent_role")
        assert result is False

    def test_get_role(self):
        """get_role returns the assigned role name."""
        rbac = RBACManager()
        actor_id = uuid.uuid4()

        assert rbac.get_role(actor_id) is None
        rbac.assign_role(actor_id, "admin")
        assert rbac.get_role(actor_id) == "admin"

    def test_get_permissions_combines_role_and_explicit(self):
        """get_permissions returns both role-based and explicit permissions."""
        rbac = RBACManager()
        actor_id = uuid.uuid4()
        rbac.assign_role(actor_id, "viewer")

        extra_perm = Permission(action="execute", resource_type="special_tool")
        rbac.grant_permission(actor_id, extra_perm)

        all_perms = rbac.get_permissions(actor_id)
        # Should include viewer role perms + explicit perm
        assert len(all_perms) >= 2
        actions = [p.action for p in all_perms]
        assert "read" in actions
        assert "execute" in actions


# ============================================================
# CycleGuard Tests
# ============================================================


class TestCycleGuard:
    """Tests for CycleGuard delegation loop detection."""

    def test_safe_delegation_passes(self):
        """Normal delegation without cycles passes."""
        guard = CycleGuard(max_cycle_count=3, max_ancestor_depth=10)
        agent_a = uuid.uuid4()
        agent_b = uuid.uuid4()

        result = guard.check_delegation(agent_a, agent_b, [])
        assert result is True

    def test_detects_repeated_edge(self):
        """Raises error when same edge repeats beyond threshold."""
        guard = CycleGuard(max_cycle_count=2, max_ancestor_depth=100)
        agent_a = uuid.uuid4()
        agent_b = uuid.uuid4()

        # Build a chain with the edge appearing twice already
        chain = [(agent_a, agent_b), (agent_b, agent_a), (agent_a, agent_b)]

        # Third occurrence of (agent_a, agent_b) exceeds max_cycle_count=2
        with pytest.raises(CycleGuardError) as exc_info:
            guard.check_delegation(agent_a, agent_b, chain)

        assert exc_info.value.source_agent_id == agent_a
        assert exc_info.value.target_agent_id == agent_b
        assert "repeated" in exc_info.value.reason.lower()

    def test_detects_depth_exceeded(self):
        """Raises error when chain depth exceeds maximum."""
        guard = CycleGuard(max_cycle_count=100, max_ancestor_depth=5)
        agent_a = uuid.uuid4()
        agent_b = uuid.uuid4()

        # Chain already at max depth
        chain = [(uuid.uuid4(), uuid.uuid4()) for _ in range(5)]

        with pytest.raises(CycleGuardError) as exc_info:
            guard.check_delegation(agent_a, agent_b, chain)

        assert "depth" in exc_info.value.reason.lower()

    def test_within_limits_passes(self):
        """Chain within both limits passes validation."""
        guard = CycleGuard(max_cycle_count=5, max_ancestor_depth=256)
        agent_a = uuid.uuid4()
        agent_b = uuid.uuid4()
        agent_c = uuid.uuid4()

        chain = [(agent_a, agent_b), (agent_b, agent_c)]
        result = guard.check_delegation(agent_c, agent_a, chain)
        assert result is True

    def test_get_chain_stats(self):
        """get_chain_stats returns correct statistics."""
        guard = CycleGuard(max_cycle_count=5, max_ancestor_depth=256)
        agent_a = uuid.uuid4()
        agent_b = uuid.uuid4()

        chain = [
            (agent_a, agent_b),
            (agent_b, agent_a),
            (agent_a, agent_b),
        ]

        stats = guard.get_chain_stats(chain)
        assert stats["depth"] == 3
        assert stats["unique_edges"] == 2
        assert stats["max_edge_count"] == 2  # (agent_a, agent_b) appears twice
