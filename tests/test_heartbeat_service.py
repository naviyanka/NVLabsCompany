"""Tests for HeartbeatService - rich heartbeat run lifecycle management."""

import uuid
from datetime import datetime, timedelta, timezone

from nexus.models.heartbeat_run import HeartbeatRun, InvocationSource, LivenessState
from nexus.runtime.heartbeat_service import HeartbeatService


class TestCreateRun:
    """Tests for HeartbeatService.create_run."""

    def test_create_run_sets_all_fields(self) -> None:
        """create_run sets agent_id, process_pid, invocation_source, session_id_before."""
        svc = HeartbeatService()
        agent_id = uuid.uuid4()

        run = svc.create_run(
            agent_id=agent_id,
            process_pid=12345,
            invocation_source="scheduled",
            session_id_before="sess-abc",
        )

        assert run.agent_id == agent_id
        assert run.process_pid == 12345
        assert run.invocation_source == "scheduled"
        assert run.session_id_before == "sess-abc"
        assert run.liveness_state == "healthy"
        assert run.continuation_attempt == 0
        assert run.finished_at is None
        assert run.last_output_at is None
        assert run.context_snapshot is None
        assert isinstance(run.id, uuid.UUID)
        assert isinstance(run.started_at, datetime)
        assert isinstance(run.created_at, datetime)

    def test_create_run_with_context_snapshot(self) -> None:
        """create_run stores context_snapshot dict."""
        svc = HeartbeatService()
        agent_id = uuid.uuid4()
        ctx = {"model": "gpt-4", "temperature": 0.7, "tokens_used": 1500}

        run = svc.create_run(
            agent_id=agent_id,
            context_snapshot=ctx,
        )

        assert run.context_snapshot == ctx
        assert run.context_snapshot["model"] == "gpt-4"


class TestUpdateLiveness:
    """Tests for HeartbeatService.update_liveness."""

    def test_update_liveness_transitions_state(self) -> None:
        """update_liveness changes liveness_state."""
        svc = HeartbeatService()
        agent_id = uuid.uuid4()
        run = svc.create_run(agent_id=agent_id)

        assert run.liveness_state == "healthy"

        updated = svc.update_liveness(run.id, "suspected_stale")
        assert updated is not None
        assert updated.liveness_state == "suspected_stale"

        updated = svc.update_liveness(run.id, "confirmed_dead")
        assert updated is not None
        assert updated.liveness_state == "confirmed_dead"

    def test_update_liveness_returns_none_for_unknown_run(self) -> None:
        """update_liveness returns None when run_id is not found."""
        svc = HeartbeatService()
        result = svc.update_liveness(uuid.uuid4(), "healthy")
        assert result is None


class TestRecordOutput:
    """Tests for HeartbeatService.record_output."""

    def test_record_output_sets_excerpts_and_timestamp(self) -> None:
        """record_output sets stdout_excerpt, stderr_excerpt, and last_output_at."""
        svc = HeartbeatService()
        agent_id = uuid.uuid4()
        run = svc.create_run(agent_id=agent_id)

        updated = svc.record_output(run.id, stdout_excerpt="hello", stderr_excerpt="warn")
        assert updated is not None
        assert updated.stdout_excerpt == "hello"
        assert updated.stderr_excerpt == "warn"
        assert updated.last_output_at is not None
        assert isinstance(updated.last_output_at, datetime)

    def test_record_output_truncates_at_2000_chars(self) -> None:
        """record_output truncates stdout and stderr to 2000 characters."""
        svc = HeartbeatService()
        agent_id = uuid.uuid4()
        run = svc.create_run(agent_id=agent_id)

        long_stdout = "x" * 5000
        long_stderr = "y" * 3000

        updated = svc.record_output(run.id, stdout_excerpt=long_stdout, stderr_excerpt=long_stderr)
        assert updated is not None
        assert len(updated.stdout_excerpt) == 2000
        assert len(updated.stderr_excerpt) == 2000
        assert updated.stdout_excerpt == "x" * 2000
        assert updated.stderr_excerpt == "y" * 2000

    def test_record_output_returns_none_for_unknown_run(self) -> None:
        """record_output returns None when run_id is not found."""
        svc = HeartbeatService()
        result = svc.record_output(uuid.uuid4(), stdout_excerpt="test")
        assert result is None


class TestFinishRun:
    """Tests for HeartbeatService.finish_run."""

    def test_finish_run_sets_exit_code_signal_finished_at(self) -> None:
        """finish_run sets exit_code, signal, session_id_after, and finished_at."""
        svc = HeartbeatService()
        agent_id = uuid.uuid4()
        run = svc.create_run(agent_id=agent_id)

        updated = svc.finish_run(
            run.id, exit_code=0, signal=None, session_id_after="sess-def"
        )
        assert updated is not None
        assert updated.exit_code == 0
        assert updated.signal is None
        assert updated.session_id_after == "sess-def"
        assert updated.finished_at is not None
        assert isinstance(updated.finished_at, datetime)
        # exit_code=0 should keep liveness as healthy
        assert updated.liveness_state == "healthy"

    def test_finish_run_with_non_zero_exit_sets_confirmed_dead(self) -> None:
        """finish_run with non-zero exit_code sets liveness to confirmed_dead."""
        svc = HeartbeatService()
        agent_id = uuid.uuid4()
        run = svc.create_run(agent_id=agent_id)

        updated = svc.finish_run(run.id, exit_code=1)
        assert updated is not None
        assert updated.liveness_state == "confirmed_dead"

    def test_finish_run_with_signal_sets_confirmed_dead(self) -> None:
        """finish_run with signal set marks liveness as confirmed_dead."""
        svc = HeartbeatService()
        agent_id = uuid.uuid4()
        run = svc.create_run(agent_id=agent_id)

        updated = svc.finish_run(run.id, signal="SIGKILL")
        assert updated is not None
        assert updated.liveness_state == "confirmed_dead"
        assert updated.signal == "SIGKILL"

    def test_finish_run_returns_none_for_unknown_run(self) -> None:
        """finish_run returns None when run_id is not found."""
        svc = HeartbeatService()
        result = svc.finish_run(uuid.uuid4(), exit_code=0)
        assert result is None


class TestGetActiveRuns:
    """Tests for HeartbeatService.get_active_runs."""

    def test_get_active_runs_filters_by_agent_and_excludes_finished(self) -> None:
        """get_active_runs returns only unfinished runs for the specified agent."""
        svc = HeartbeatService()
        agent_a = uuid.uuid4()
        agent_b = uuid.uuid4()

        run_a1 = svc.create_run(agent_id=agent_a)
        run_a2 = svc.create_run(agent_id=agent_a)
        _run_b1 = svc.create_run(agent_id=agent_b)

        # Finish one of agent_a's runs
        svc.finish_run(run_a1.id, exit_code=0)

        active = svc.get_active_runs(agent_a)
        assert len(active) == 1
        assert active[0].id == run_a2.id

    def test_get_active_runs_returns_empty_for_unknown_agent(self) -> None:
        """get_active_runs returns empty list for an agent with no runs."""
        svc = HeartbeatService()
        assert svc.get_active_runs(uuid.uuid4()) == []


class TestGetLatestRun:
    """Tests for HeartbeatService.get_latest_run."""

    def test_get_latest_run_returns_most_recent(self) -> None:
        """get_latest_run returns the run with the most recent started_at."""
        svc = HeartbeatService()
        agent_id = uuid.uuid4()

        run1 = svc.create_run(agent_id=agent_id)
        # Manually adjust started_at to ensure ordering
        run1.started_at = datetime(2024, 1, 1, 10, 0, 0)

        run2 = svc.create_run(agent_id=agent_id)
        run2.started_at = datetime(2024, 1, 1, 12, 0, 0)

        latest = svc.get_latest_run(agent_id)
        assert latest is not None
        assert latest.id == run2.id

    def test_get_latest_run_returns_none_for_unknown_agent(self) -> None:
        """get_latest_run returns None for an agent with no runs."""
        svc = HeartbeatService()
        assert svc.get_latest_run(uuid.uuid4()) is None


class TestIncrementContinuation:
    """Tests for HeartbeatService.increment_continuation."""

    def test_increment_continuation_increases_count(self) -> None:
        """increment_continuation increases continuation_attempt by 1 each call."""
        svc = HeartbeatService()
        agent_id = uuid.uuid4()
        run = svc.create_run(agent_id=agent_id)

        assert run.continuation_attempt == 0

        updated = svc.increment_continuation(run.id)
        assert updated is not None
        assert updated.continuation_attempt == 1

        updated = svc.increment_continuation(run.id)
        assert updated is not None
        assert updated.continuation_attempt == 2

    def test_increment_continuation_returns_none_for_unknown_run(self) -> None:
        """increment_continuation returns None when run_id is not found."""
        svc = HeartbeatService()
        result = svc.increment_continuation(uuid.uuid4())
        assert result is None


class TestDetectStale:
    """Tests for HeartbeatService.detect_stale."""

    def test_detect_stale_finds_stale_runs(self) -> None:
        """detect_stale finds active runs with no recent activity."""
        svc = HeartbeatService()
        agent_id = uuid.uuid4()

        # Create a run and backdate its started_at
        run = svc.create_run(agent_id=agent_id)
        run.started_at = datetime.now(timezone.utc) - timedelta(seconds=120)

        # Create a fresh run
        fresh_run = svc.create_run(agent_id=agent_id)

        stale = svc.detect_stale(threshold_seconds=60)
        assert len(stale) == 1
        assert stale[0].id == run.id

        # Fresh run should not be stale
        assert fresh_run.id not in [r.id for r in stale]

    def test_detect_stale_uses_last_output_at_when_available(self) -> None:
        """detect_stale uses last_output_at instead of started_at when set."""
        svc = HeartbeatService()
        agent_id = uuid.uuid4()

        run = svc.create_run(agent_id=agent_id)
        run.started_at = datetime.now(timezone.utc) - timedelta(seconds=120)
        # But output was recent
        run.last_output_at = datetime.now(timezone.utc) - timedelta(seconds=10)

        stale = svc.detect_stale(threshold_seconds=60)
        assert len(stale) == 0

    def test_detect_stale_excludes_finished_runs(self) -> None:
        """detect_stale does not return finished runs."""
        svc = HeartbeatService()
        agent_id = uuid.uuid4()

        run = svc.create_run(agent_id=agent_id)
        run.started_at = datetime.now(timezone.utc) - timedelta(seconds=120)
        svc.finish_run(run.id, exit_code=0)

        stale = svc.detect_stale(threshold_seconds=60)
        assert len(stale) == 0


class TestFullLifecycle:
    """Tests for the full heartbeat run lifecycle."""

    def test_create_record_output_finish(self) -> None:
        """Full lifecycle: create -> record_output -> finish."""
        svc = HeartbeatService()
        agent_id = uuid.uuid4()

        # Create
        run = svc.create_run(
            agent_id=agent_id,
            process_pid=9999,
            invocation_source="heartbeat",
            session_id_before="sess-start",
        )
        assert run.liveness_state == "healthy"
        assert run.finished_at is None

        # Record output
        updated = svc.record_output(run.id, stdout_excerpt="processing...", stderr_excerpt="")
        assert updated is not None
        assert updated.stdout_excerpt == "processing..."
        assert updated.last_output_at is not None

        # Finish successfully
        finished = svc.finish_run(
            run.id, exit_code=0, session_id_after="sess-end"
        )
        assert finished is not None
        assert finished.exit_code == 0
        assert finished.finished_at is not None
        assert finished.session_id_after == "sess-end"
        assert finished.liveness_state == "healthy"

        # No longer in active runs
        active = svc.get_active_runs(agent_id)
        assert len(active) == 0


class TestEnums:
    """Tests for LivenessState and InvocationSource enums."""

    def test_liveness_state_values(self) -> None:
        """LivenessState has expected values."""
        assert LivenessState.healthy == "healthy"
        assert LivenessState.suspected_stale == "suspected_stale"
        assert LivenessState.confirmed_dead == "confirmed_dead"

    def test_invocation_source_values(self) -> None:
        """InvocationSource has expected values."""
        assert InvocationSource.on_demand == "on_demand"
        assert InvocationSource.scheduled == "scheduled"
        assert InvocationSource.trigger == "trigger"
        assert InvocationSource.heartbeat == "heartbeat"
