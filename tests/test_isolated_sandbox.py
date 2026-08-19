"""Tests for the Isolated Sandbox module.

Validates IsolatedSandbox resource tracking and limit enforcement,
including session creation, execution within limits, resource breaches,
abort, and cleanup.
"""

import uuid

import pytest

from nexus.evolution.isolated_sandbox import IsolatedSandbox, ResourceLimitExceeded


@pytest.fixture
def proposal_id():
    """Provide a fixed proposal UUID for tests."""
    return uuid.UUID("22222222-2222-2222-2222-222222222222")


@pytest.fixture
def sandbox():
    """Provide a default IsolatedSandbox instance."""
    return IsolatedSandbox(
        max_cost_cents=1000,
        max_duration_seconds=300,
        max_memory_mb=512,
    )


class TestIsolatedSandbox:
    """Tests for IsolatedSandbox session management and resource tracking."""

    def test_create_session_returns_uuid(self, sandbox, proposal_id):
        """Test that create_session returns a valid UUID."""
        session_id = sandbox.create_session(
            proposal_id=proposal_id,
            config={"model": "test-model"},
        )

        assert isinstance(session_id, uuid.UUID)

    def test_execute_within_limits_returns_result(self, sandbox, proposal_id):
        """Test execution within resource limits returns the result."""
        session_id = sandbox.create_session(
            proposal_id=proposal_id,
            config={"model": "test-model"},
        )

        def task_fn():
            return {"output": "success", "cost_cents": 10, "memory_mb": 50}

        result = sandbox.execute(session_id, task_fn)

        assert result["result"]["output"] == "success"
        assert "resources" in result
        assert result["resources"]["cost_cents"] == 10
        assert result["resources"]["memory_mb"] == 50

    def test_execute_breaching_cost_raises_resource_limit_exceeded(self, proposal_id):
        """Test that exceeding cost limit raises ResourceLimitExceeded."""
        sandbox = IsolatedSandbox(max_cost_cents=100, max_duration_seconds=300, max_memory_mb=512)
        session_id = sandbox.create_session(
            proposal_id=proposal_id,
            config={},
        )

        def expensive_fn():
            return {"cost_cents": 150, "memory_mb": 10}

        with pytest.raises(ResourceLimitExceeded) as exc_info:
            sandbox.execute(session_id, expensive_fn)

        assert exc_info.value.resource == "cost"
        assert exc_info.value.limit == 100
        assert exc_info.value.actual == 150

    def test_execute_breaching_duration_raises_resource_limit_exceeded(self, proposal_id):
        """Test that exceeding duration limit raises ResourceLimitExceeded."""
        import time

        sandbox = IsolatedSandbox(
            max_cost_cents=1000,
            max_duration_seconds=0,  # Zero seconds - any execution breaches this
            max_memory_mb=512,
        )
        session_id = sandbox.create_session(
            proposal_id=proposal_id,
            config={},
        )

        def slow_fn():
            time.sleep(0.01)  # Tiny sleep to ensure some duration
            return {"cost_cents": 0, "memory_mb": 0}

        with pytest.raises(ResourceLimitExceeded) as exc_info:
            sandbox.execute(session_id, slow_fn)

        assert exc_info.value.resource == "duration"
        assert exc_info.value.limit == 0

    def test_execute_breaching_memory_raises_resource_limit_exceeded(self, proposal_id):
        """Test that exceeding memory limit raises ResourceLimitExceeded."""
        sandbox = IsolatedSandbox(max_cost_cents=1000, max_duration_seconds=300, max_memory_mb=100)
        session_id = sandbox.create_session(
            proposal_id=proposal_id,
            config={},
        )

        def memory_hungry_fn():
            return {"cost_cents": 0, "memory_mb": 200}

        with pytest.raises(ResourceLimitExceeded) as exc_info:
            sandbox.execute(session_id, memory_hungry_fn)

        assert exc_info.value.resource == "memory"
        assert exc_info.value.limit == 100
        assert exc_info.value.actual == 200

    def test_get_resource_usage_returns_accurate_tracking(self, sandbox, proposal_id):
        """Test that get_resource_usage returns accurate accumulated values."""
        session_id = sandbox.create_session(
            proposal_id=proposal_id,
            config={},
        )

        def task_fn():
            return {"cost_cents": 50, "memory_mb": 100}

        sandbox.execute(session_id, task_fn)
        usage = sandbox.get_resource_usage(session_id)

        assert usage["cost_cents"]["used"] == 50
        assert usage["cost_cents"]["limit"] == 1000
        assert usage["cost_cents"]["remaining"] == 950
        assert usage["memory_mb"]["used"] == 100
        assert usage["memory_mb"]["limit"] == 512
        assert usage["memory_mb"]["remaining"] == 412
        assert usage["duration_seconds"]["used"] > 0
        assert usage["duration_seconds"]["limit"] == 300
        assert usage["status"] == "active"

    def test_resource_usage_accumulates_across_executions(self, sandbox, proposal_id):
        """Test that resource usage accumulates across multiple executions."""
        session_id = sandbox.create_session(
            proposal_id=proposal_id,
            config={},
        )

        def task_fn():
            return {"cost_cents": 30, "memory_mb": 50}

        sandbox.execute(session_id, task_fn)
        sandbox.execute(session_id, task_fn)

        usage = sandbox.get_resource_usage(session_id)
        assert usage["cost_cents"]["used"] == 60
        assert usage["memory_mb"]["used"] == 100

    def test_abort_marks_session_inactive(self, sandbox, proposal_id):
        """Test that abort marks the session as aborted."""
        session_id = sandbox.create_session(
            proposal_id=proposal_id,
            config={},
        )

        sandbox.abort(session_id)

        usage = sandbox.get_resource_usage(session_id)
        assert usage["status"] == "aborted"

    def test_execute_after_abort_raises_value_error(self, sandbox, proposal_id):
        """Test that executing after abort raises ValueError."""
        session_id = sandbox.create_session(
            proposal_id=proposal_id,
            config={},
        )

        sandbox.abort(session_id)

        def task_fn():
            return {"cost_cents": 0, "memory_mb": 0}

        with pytest.raises(ValueError, match="not active"):
            sandbox.execute(session_id, task_fn)

    def test_cleanup_removes_session(self, sandbox, proposal_id):
        """Test that cleanup removes the session from tracking."""
        session_id = sandbox.create_session(
            proposal_id=proposal_id,
            config={},
        )

        sandbox.cleanup(session_id)

        with pytest.raises(ValueError, match="not found"):
            sandbox.get_resource_usage(session_id)

    def test_execute_with_non_dict_result(self, sandbox, proposal_id):
        """Test execution when callable returns a non-dict value."""
        session_id = sandbox.create_session(
            proposal_id=proposal_id,
            config={},
        )

        def simple_fn():
            return 42

        result = sandbox.execute(session_id, simple_fn)

        assert result["result"] == 42
        assert result["resources"]["cost_cents"] == 0
        assert result["resources"]["memory_mb"] == 0

    def test_execute_with_args(self, sandbox, proposal_id):
        """Test execution passes args to callable."""
        session_id = sandbox.create_session(
            proposal_id=proposal_id,
            config={},
        )

        def add_fn(a, b):
            return {"value": a + b, "cost_cents": 5, "memory_mb": 1}

        result = sandbox.execute(session_id, add_fn, 3, 7)

        assert result["result"]["value"] == 10
        assert result["resources"]["cost_cents"] == 5
