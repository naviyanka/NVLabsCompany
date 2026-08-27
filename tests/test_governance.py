"""Tests for governance components: RBAC and CycleGuard.

Tests real logic paths including content validation and permission checking.
Kill switch and circuit breaker coverage lives in test_persistent_circuit_breaker.py
now that the in-memory implementations are gone.
"""

import uuid

import pytest

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
