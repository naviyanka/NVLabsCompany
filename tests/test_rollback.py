"""Tests for RollbackManager - Rollback operations, cascade, and safety checks.

Tests record and rollback operations, checkpoint restore, cascading rollback,
and safety checks that block unsafe rollbacks.
"""

import uuid

import pytest

from nexus.governance.rollback import (
    RollbackManager,
    Operation,
    Checkpoint,
    RollbackResult,
)


class TestRecordAndRollback:
    """Tests for basic operation recording and rollback."""

    def test_record_operation(self):
        """Operations can be recorded with all fields."""
        mgr = RollbackManager()
        op = mgr.record_operation(
            action="create_task",
            resource_type="task",
            resource_id="task-001",
            previous_state={},
            new_state={"title": "New task", "status": "open"},
            performed_by="agent-1",
        )

        assert op.action == "create_task"
        assert op.resource_type == "task"
        assert op.resource_id == "task-001"
        assert op.new_state == {"title": "New task", "status": "open"}
        assert op.rolled_back is False

    def test_rollback_single_operation(self):
        """A single operation can be rolled back."""
        mgr = RollbackManager()
        op = mgr.record_operation(
            action="update_status",
            resource_type="task",
            resource_id="task-002",
            previous_state={"status": "open"},
            new_state={"status": "closed"},
        )

        result = mgr.rollback_operation(op.id)

        assert result.success is True
        assert len(result.rolled_back_operations) == 1
        assert result.rolled_back_operations[0].id == op.id
        assert op.rolled_back is True

    def test_rollback_nonexistent_fails(self):
        """Rolling back a nonexistent operation fails."""
        mgr = RollbackManager()
        result = mgr.rollback_operation(uuid.uuid4())

        assert result.success is False
        assert "not found" in result.blocked_reason

    def test_rollback_already_rolled_back_fails(self):
        """Cannot rollback an already-rolled-back operation."""
        mgr = RollbackManager()
        op = mgr.record_operation(
            action="test",
            resource_type="test",
            resource_id="t1",
            previous_state={},
            new_state={"x": 1},
        )
        mgr.rollback_operation(op.id)

        result = mgr.rollback_operation(op.id)
        assert result.success is False
        assert "already been rolled back" in result.blocked_reason

    def test_get_operations_excludes_rolled_back(self):
        """get_operations by default excludes rolled-back operations."""
        mgr = RollbackManager()
        op1 = mgr.record_operation(
            action="a", resource_type="t", resource_id="1",
            previous_state={}, new_state={"v": 1},
        )
        op2 = mgr.record_operation(
            action="b", resource_type="t", resource_id="2",
            previous_state={}, new_state={"v": 2},
        )
        mgr.rollback_operation(op1.id)

        active = mgr.get_operations()
        assert len(active) == 1
        assert active[0].id == op2.id

        all_ops = mgr.get_operations(include_rolled_back=True)
        assert len(all_ops) == 2


class TestCheckpointRollback:
    """Tests for checkpoint creation and rollback-to-checkpoint."""

    def test_create_checkpoint(self):
        """Checkpoints can be created with a name and description."""
        mgr = RollbackManager()
        mgr.record_operation(
            action="setup", resource_type="config", resource_id="c1",
            previous_state={}, new_state={"key": "val"},
        )

        cp = mgr.create_checkpoint("after-setup", description="Initial setup done")

        assert cp.name == "after-setup"
        assert cp.description == "Initial setup done"
        assert cp.operation_index == 1

    def test_rollback_to_checkpoint(self):
        """Rollback to checkpoint reverts all operations after it."""
        mgr = RollbackManager()
        mgr.record_operation(
            action="step1", resource_type="t", resource_id="1",
            previous_state={}, new_state={"v": 1},
        )

        cp = mgr.create_checkpoint("stable")

        op2 = mgr.record_operation(
            action="step2", resource_type="t", resource_id="2",
            previous_state={}, new_state={"v": 2},
        )
        op3 = mgr.record_operation(
            action="step3", resource_type="t", resource_id="3",
            previous_state={}, new_state={"v": 3},
        )

        result = mgr.rollback_to_checkpoint(cp.id)

        assert result.success is True
        assert len(result.rolled_back_operations) == 2
        assert op2.rolled_back is True
        assert op3.rolled_back is True

    def test_rollback_to_nonexistent_checkpoint_fails(self):
        """Rolling back to a nonexistent checkpoint fails."""
        mgr = RollbackManager()
        result = mgr.rollback_to_checkpoint(uuid.uuid4())

        assert result.success is False
        assert "not found" in result.blocked_reason

    def test_checkpoint_preserves_earlier_operations(self):
        """Operations before the checkpoint are not affected."""
        mgr = RollbackManager()
        op1 = mgr.record_operation(
            action="before", resource_type="t", resource_id="1",
            previous_state={}, new_state={"v": 1},
        )

        cp = mgr.create_checkpoint("midpoint")

        mgr.record_operation(
            action="after", resource_type="t", resource_id="2",
            previous_state={}, new_state={"v": 2},
        )

        mgr.rollback_to_checkpoint(cp.id)

        assert op1.rolled_back is False
        active = mgr.get_operations()
        assert len(active) == 1
        assert active[0].id == op1.id


class TestCascadingRollback:
    """Tests for cascading rollback of dependent operations."""

    def test_cascading_rollback_removes_dependents(self):
        """Cascading rollback rolls back the target and all dependents."""
        mgr = RollbackManager()
        op1 = mgr.record_operation(
            action="create_parent", resource_type="task", resource_id="parent",
            previous_state={}, new_state={"title": "Parent"},
        )
        op2 = mgr.record_operation(
            action="create_child", resource_type="task", resource_id="child",
            previous_state={}, new_state={"title": "Child"},
            dependencies=[op1.id],
        )
        op3 = mgr.record_operation(
            action="create_grandchild", resource_type="task", resource_id="grandchild",
            previous_state={}, new_state={"title": "Grandchild"},
            dependencies=[op2.id],
        )

        result = mgr.cascading_rollback(op1.id)

        assert result.success is True
        assert op1.rolled_back is True
        assert op2.rolled_back is True
        assert op3.rolled_back is True
        assert len(result.rolled_back_operations) == 3

    def test_cascading_rollback_nonexistent_fails(self):
        """Cascading rollback of nonexistent operation fails."""
        mgr = RollbackManager()
        result = mgr.cascading_rollback(uuid.uuid4())
        assert result.success is False

    def test_cascading_rollback_already_rolled_back_fails(self):
        """Cannot cascade rollback an already-rolled-back operation."""
        mgr = RollbackManager()
        op = mgr.record_operation(
            action="test", resource_type="t", resource_id="1",
            previous_state={}, new_state={"v": 1},
        )
        mgr.rollback_operation(op.id)

        result = mgr.cascading_rollback(op.id)
        assert result.success is False

    def test_cascading_only_rolls_back_related(self):
        """Cascading rollback does not affect unrelated operations."""
        mgr = RollbackManager()
        op1 = mgr.record_operation(
            action="target", resource_type="t", resource_id="1",
            previous_state={}, new_state={"v": 1},
        )
        op_unrelated = mgr.record_operation(
            action="unrelated", resource_type="t", resource_id="2",
            previous_state={}, new_state={"v": 2},
        )
        op_dependent = mgr.record_operation(
            action="dependent", resource_type="t", resource_id="3",
            previous_state={}, new_state={"v": 3},
            dependencies=[op1.id],
        )

        mgr.cascading_rollback(op1.id)

        assert op1.rolled_back is True
        assert op_dependent.rolled_back is True
        assert op_unrelated.rolled_back is False


class TestSafetyChecks:
    """Tests for rollback safety checks that block unsafe operations."""

    def test_safe_rollback_passes_check(self):
        """Operation with no dependents passes safety check."""
        mgr = RollbackManager()
        op = mgr.record_operation(
            action="safe", resource_type="t", resource_id="1",
            previous_state={}, new_state={"v": 1},
        )

        is_safe, reason = mgr.safety_check(op.id)
        assert is_safe is True
        assert "Safe" in reason

    def test_unsafe_rollback_blocked_by_dependents(self):
        """Operation with active dependents fails safety check."""
        mgr = RollbackManager()
        op1 = mgr.record_operation(
            action="parent", resource_type="t", resource_id="1",
            previous_state={}, new_state={"v": 1},
        )
        op2 = mgr.record_operation(
            action="child", resource_type="t", resource_id="2",
            previous_state={}, new_state={"v": 2},
            dependencies=[op1.id],
        )

        is_safe, reason = mgr.safety_check(op1.id)
        assert is_safe is False
        assert "depend on this one" in reason

    def test_rolled_back_dependents_dont_block(self):
        """If dependents are already rolled back, safety check passes."""
        mgr = RollbackManager()
        op1 = mgr.record_operation(
            action="parent", resource_type="t", resource_id="1",
            previous_state={}, new_state={"v": 1},
        )
        op2 = mgr.record_operation(
            action="child", resource_type="t", resource_id="2",
            previous_state={}, new_state={"v": 2},
            dependencies=[op1.id],
        )

        # Rollback the dependent first
        mgr.rollback_operation(op2.id)

        # Now the parent is safe to rollback
        is_safe, reason = mgr.safety_check(op1.id)
        assert is_safe is True

    def test_safety_check_nonexistent_operation(self):
        """Safety check on nonexistent operation returns unsafe."""
        mgr = RollbackManager()
        is_safe, reason = mgr.safety_check(uuid.uuid4())
        assert is_safe is False
        assert "not found" in reason

    def test_safety_check_already_rolled_back(self):
        """Safety check on already rolled-back operation returns unsafe."""
        mgr = RollbackManager()
        op = mgr.record_operation(
            action="test", resource_type="t", resource_id="1",
            previous_state={}, new_state={"v": 1},
        )
        mgr.rollback_operation(op.id)

        is_safe, reason = mgr.safety_check(op.id)
        assert is_safe is False
        assert "already been rolled back" in reason

    def test_rollback_with_dependents_is_blocked(self):
        """Direct rollback is blocked when dependents exist."""
        mgr = RollbackManager()
        op1 = mgr.record_operation(
            action="parent", resource_type="t", resource_id="1",
            previous_state={}, new_state={"v": 1},
        )
        op2 = mgr.record_operation(
            action="child", resource_type="t", resource_id="2",
            previous_state={}, new_state={"v": 2},
            dependencies=[op1.id],
        )

        result = mgr.rollback_operation(op1.id)
        assert result.success is False
        assert "depend on this one" in result.blocked_reason


class TestRollbackHistory:
    """Tests for rollback history tracking."""

    def test_rollback_history_tracked(self):
        """All rollback attempts (success and failure) are tracked."""
        mgr = RollbackManager()
        op = mgr.record_operation(
            action="test", resource_type="t", resource_id="1",
            previous_state={}, new_state={"v": 1},
        )

        mgr.rollback_operation(op.id)
        mgr.rollback_operation(uuid.uuid4())  # This will fail

        history = mgr.get_rollback_history()
        assert len(history) == 2
        assert history[0].success is True
        assert history[1].success is False
