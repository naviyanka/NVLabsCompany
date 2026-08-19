"""Tests for durable execution checkpoints."""

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from nexus.runtime.checkpoint import (
    CheckpointManager,
    CheckpointStatus,
    ExecutionCheckpoint,
    build_checkpoint_state,
)


@pytest.fixture
def manager() -> CheckpointManager:
    """Create a fresh CheckpointManager for each test."""
    return CheckpointManager(max_checkpoint_age_hours=24)


@pytest.fixture
def task_id() -> uuid.UUID:
    """Provide a consistent task ID for tests."""
    return uuid.uuid4()


class TestSaveCheckpoint:
    """Tests for saving checkpoints."""

    def test_save_checkpoint_stores_correctly(
        self, manager: CheckpointManager, task_id: uuid.UUID
    ) -> None:
        """save_checkpoint stores the checkpoint with correct fields."""
        state = build_checkpoint_state(
            agent_context={"agent": "test-agent"},
            completed_steps=[0, 1],
            intermediate_results=[{"step_0": "done"}],
        )

        cp = manager.save_checkpoint(task_id, step_index=2, state=state)

        assert cp.task_id == task_id
        assert cp.step_index == 2
        assert cp.state_json == state
        assert cp.status == CheckpointStatus.active
        assert cp.created_at is not None
        assert isinstance(cp.id, uuid.UUID)


class TestLoadLatest:
    """Tests for loading the latest checkpoint."""

    def test_load_latest_returns_most_recent(
        self, manager: CheckpointManager, task_id: uuid.UUID
    ) -> None:
        """load_latest returns the most recent checkpoint for a task."""
        state1 = {"step": 1}
        state2 = {"step": 2}

        manager.save_checkpoint(task_id, step_index=1, state=state1)
        cp2 = manager.save_checkpoint(task_id, step_index=2, state=state2)

        latest = manager.load_latest(task_id)

        assert latest is not None
        assert latest.id == cp2.id
        assert latest.step_index == 2
        assert latest.state_json == state2

    def test_load_latest_returns_none_for_unknown_task(
        self, manager: CheckpointManager
    ) -> None:
        """load_latest returns None for a task with no checkpoints."""
        unknown_id = uuid.uuid4()
        assert manager.load_latest(unknown_id) is None


class TestCleanup:
    """Tests for checkpoint cleanup."""

    def test_cleanup_marks_all_as_completed(
        self, manager: CheckpointManager, task_id: uuid.UUID
    ) -> None:
        """cleanup marks all active checkpoints for a task as completed."""
        manager.save_checkpoint(task_id, step_index=0, state={"s": 0})
        manager.save_checkpoint(task_id, step_index=1, state={"s": 1})

        manager.cleanup(task_id)

        # All checkpoints for this task should be completed
        active = [
            cp
            for cp in manager._checkpoints
            if cp.task_id == task_id and cp.status == CheckpointStatus.active
        ]
        completed = [
            cp
            for cp in manager._checkpoints
            if cp.task_id == task_id and cp.status == CheckpointStatus.completed
        ]
        assert len(active) == 0
        assert len(completed) == 2
        # updated_at should be set
        for cp in completed:
            assert cp.updated_at is not None


class TestAbandonStale:
    """Tests for stale checkpoint abandonment."""

    def test_abandon_stale_marks_old_checkpoints(self) -> None:
        """abandon_stale marks checkpoints older than max age as abandoned."""
        manager = CheckpointManager(max_checkpoint_age_hours=1)
        task_id = uuid.uuid4()

        cp = manager.save_checkpoint(task_id, step_index=0, state={"old": True})
        # Simulate age by backdating created_at
        cp.created_at = datetime.now(timezone.utc) - timedelta(hours=2)

        # Also add a fresh checkpoint
        fresh_task_id = uuid.uuid4()
        manager.save_checkpoint(fresh_task_id, step_index=0, state={"fresh": True})

        abandoned = manager.abandon_stale()

        assert len(abandoned) == 1
        assert abandoned[0].task_id == task_id
        assert abandoned[0].status == CheckpointStatus.abandoned
        assert abandoned[0].updated_at is not None

        # Fresh checkpoint should remain active
        fresh = manager.load_latest(fresh_task_id)
        assert fresh is not None
        assert fresh.status == CheckpointStatus.active


class TestListActive:
    """Tests for listing active checkpoints."""

    def test_list_active_returns_only_active(
        self, manager: CheckpointManager
    ) -> None:
        """list_active returns only checkpoints with active status."""
        task1 = uuid.uuid4()
        task2 = uuid.uuid4()

        manager.save_checkpoint(task1, step_index=0, state={"t": 1})
        manager.save_checkpoint(task2, step_index=0, state={"t": 2})

        # Cleanup task1 (marks as completed)
        manager.cleanup(task1)

        active = manager.list_active()
        assert len(active) == 1
        assert active[0].task_id == task2


class TestRecoverInterrupted:
    """Tests for startup recovery of interrupted tasks."""

    def test_recover_interrupted_finds_all_active(
        self, manager: CheckpointManager
    ) -> None:
        """recover_interrupted returns all active checkpoint task/state pairs."""
        task1 = uuid.uuid4()
        task2 = uuid.uuid4()
        task3 = uuid.uuid4()

        state1 = {"task": "one"}
        state2 = {"task": "two"}
        state3 = {"task": "three"}

        manager.save_checkpoint(task1, step_index=0, state=state1)
        manager.save_checkpoint(task2, step_index=1, state=state2)
        manager.save_checkpoint(task3, step_index=2, state=state3)

        # Complete task3
        manager.cleanup(task3)

        interrupted = manager.recover_interrupted()

        task_ids = [tid for tid, _ in interrupted]
        assert task1 in task_ids
        assert task2 in task_ids
        assert task3 not in task_ids
        assert len(interrupted) == 2

        # Check states are correct
        state_map = dict(interrupted)
        assert state_map[task1] == state1
        assert state_map[task2] == state2


class TestResumeFromCheckpoint:
    """Tests for resuming from a checkpoint."""

    def test_resume_returns_state_dict(
        self, manager: CheckpointManager, task_id: uuid.UUID
    ) -> None:
        """resume_from_checkpoint returns state_json from latest active checkpoint."""
        state = build_checkpoint_state(
            agent_context={"model": "gpt-4"},
            completed_steps=[0, 1, 2],
            intermediate_results=[{"r": 1}, {"r": 2}, {"r": 3}],
            metadata={"retry_count": 1},
        )

        manager.save_checkpoint(task_id, step_index=3, state=state)

        result = manager.resume_from_checkpoint(task_id)

        assert result is not None
        assert result["agent_context"] == {"model": "gpt-4"}
        assert result["completed_steps"] == [0, 1, 2]
        assert result["intermediate_results"] == [{"r": 1}, {"r": 2}, {"r": 3}]
        assert result["metadata"] == {"retry_count": 1}

    def test_resume_returns_none_for_unknown_task(
        self, manager: CheckpointManager
    ) -> None:
        """resume_from_checkpoint returns None when no active checkpoint exists."""
        assert manager.resume_from_checkpoint(uuid.uuid4()) is None


class TestBuildCheckpointState:
    """Tests for the build_checkpoint_state helper function."""

    def test_creates_correct_structure(self) -> None:
        """build_checkpoint_state creates a dict with all required keys."""
        state = build_checkpoint_state(
            agent_context={"agent_id": "agent-1", "company": "acme"},
            completed_steps=[0, 1, 2],
            intermediate_results=[{"output": "hello"}, {"output": "world"}],
            metadata={"version": "1.0"},
        )

        assert state["agent_context"] == {"agent_id": "agent-1", "company": "acme"}
        assert state["completed_steps"] == [0, 1, 2]
        assert state["intermediate_results"] == [
            {"output": "hello"},
            {"output": "world"},
        ]
        assert state["metadata"] == {"version": "1.0"}

    def test_metadata_defaults_to_empty_dict(self) -> None:
        """build_checkpoint_state uses empty dict when metadata is None."""
        state = build_checkpoint_state(
            agent_context={},
            completed_steps=[],
            intermediate_results=[],
        )

        assert state["metadata"] == {}


class TestMultipleTasks:
    """Tests for multiple tasks with independent checkpoints."""

    def test_multiple_tasks_independent(
        self, manager: CheckpointManager
    ) -> None:
        """Multiple tasks maintain independent checkpoint histories."""
        task_a = uuid.uuid4()
        task_b = uuid.uuid4()

        state_a1 = {"task": "a", "step": 1}
        state_a2 = {"task": "a", "step": 2}
        state_b1 = {"task": "b", "step": 1}

        manager.save_checkpoint(task_a, step_index=1, state=state_a1)
        manager.save_checkpoint(task_a, step_index=2, state=state_a2)
        manager.save_checkpoint(task_b, step_index=1, state=state_b1)

        # Latest for task_a should be step 2
        latest_a = manager.load_latest(task_a)
        assert latest_a is not None
        assert latest_a.step_index == 2
        assert latest_a.state_json == state_a2

        # Latest for task_b should be step 1
        latest_b = manager.load_latest(task_b)
        assert latest_b is not None
        assert latest_b.step_index == 1
        assert latest_b.state_json == state_b1

        # Cleanup task_a should not affect task_b
        manager.cleanup(task_a)

        assert manager.load_latest(task_a) is None
        assert manager.load_latest(task_b) is not None
        assert manager.load_latest(task_b).status == CheckpointStatus.active
