"""Tests for the Watchdog Auto-Recovery system.

Validates that the Watchdog correctly detects stuck, orphaned, budget-exceeded,
and circuit-broken agents, and takes appropriate recovery actions.
"""

import asyncio
import uuid
from datetime import datetime, timedelta, timezone

import pytest

from nexus.models.heartbeat_run import HeartbeatRun
from nexus.runtime.watchdog import (
    AgentInfo,
    PatrolReport,
    RecoveryAction,
    Watchdog,
    WatchdogConfig,
    stop_fingerprint,
)


@pytest.fixture
def watchdog():
    """Create a Watchdog with default config for testing."""
    config = WatchdogConfig(
        patrol_interval_seconds=1,
        stuck_threshold_seconds=300,
    )
    return Watchdog(config=config)


@pytest.fixture
def sample_agent_id():
    """Provide a fixed UUID for agent-related tests."""
    return uuid.UUID("abcdef01-abcd-abcd-abcd-abcdef012345")


@pytest.fixture
def sample_task_id():
    """Provide a fixed UUID for task-related tests."""
    return uuid.UUID("99999999-9999-9999-9999-999999999999")


class TestStuckAgentDetection:
    """Tests for detecting stuck agents."""

    def test_detects_stuck_agent_with_stale_heartbeat(
        self, watchdog, sample_agent_id, sample_task_id
    ):
        """Patrol detects agent stuck in executing with stale heartbeat."""
        stale_time = datetime.now(timezone.utc) - timedelta(seconds=600)
        agent = AgentInfo(
            agent_id=sample_agent_id,
            status="executing",
            last_heartbeat_at=stale_time,
            budget_monthly_cents=5000,
            spent_monthly_cents=100,
            assigned_task_ids=[sample_task_id],
        )

        report = watchdog.patrol([agent])

        assert report.issues_found >= 1
        stuck_actions = [
            a for a in report.actions_taken
            if a["action"] == RecoveryAction.RESET_IDLE.value
        ]
        assert len(stuck_actions) == 1
        assert stuck_actions[0]["agent_id"] == str(sample_agent_id)

    def test_detects_stuck_agent_with_no_heartbeat(
        self, watchdog, sample_agent_id
    ):
        """Patrol detects agent executing with no heartbeat ever recorded."""
        agent = AgentInfo(
            agent_id=sample_agent_id,
            status="executing",
            last_heartbeat_at=None,
            budget_monthly_cents=5000,
            spent_monthly_cents=100,
            assigned_task_ids=[],
        )

        report = watchdog.patrol([agent])

        stuck_actions = [
            a for a in report.actions_taken
            if a["action"] == RecoveryAction.RESET_IDLE.value
        ]
        assert len(stuck_actions) == 1

    def test_ignores_healthy_executing_agent(
        self, watchdog, sample_agent_id
    ):
        """Patrol does not flag executing agent with recent heartbeat."""
        recent_time = datetime.now(timezone.utc) - timedelta(seconds=10)
        agent = AgentInfo(
            agent_id=sample_agent_id,
            status="executing",
            last_heartbeat_at=recent_time,
            budget_monthly_cents=5000,
            spent_monthly_cents=100,
            assigned_task_ids=[],
        )

        report = watchdog.patrol([agent])

        stuck_actions = [
            a for a in report.actions_taken
            if a["action"] == RecoveryAction.RESET_IDLE.value
        ]
        assert len(stuck_actions) == 0

    def test_ignores_idle_agent(self, watchdog, sample_agent_id):
        """Patrol does not check idle agents for stuck state."""
        agent = AgentInfo(
            agent_id=sample_agent_id,
            status="idle",
            last_heartbeat_at=None,
            budget_monthly_cents=5000,
            spent_monthly_cents=100,
            assigned_task_ids=[],
        )

        report = watchdog.patrol([agent])

        stuck_actions = [
            a for a in report.actions_taken
            if a["action"] == RecoveryAction.RESET_IDLE.value
        ]
        assert len(stuck_actions) == 0


class TestOrphanedTaskDetection:
    """Tests for detecting orphaned tasks."""

    def test_detects_orphaned_tasks_on_terminated_agent(
        self, watchdog, sample_agent_id, sample_task_id
    ):
        """Patrol detects tasks assigned to a terminated agent."""
        task_id_2 = uuid.uuid4()
        agent = AgentInfo(
            agent_id=sample_agent_id,
            status="terminated",
            last_heartbeat_at=None,
            budget_monthly_cents=5000,
            spent_monthly_cents=100,
            assigned_task_ids=[sample_task_id, task_id_2],
        )

        report = watchdog.patrol([agent])

        orphan_actions = [
            a for a in report.actions_taken
            if a["action"] == RecoveryAction.MARK_FAILED.value
        ]
        assert len(orphan_actions) == 2
        task_ids = {a["task_id"] for a in orphan_actions}
        assert str(sample_task_id) in task_ids
        assert str(task_id_2) in task_ids

    def test_detects_orphaned_tasks_on_error_agent(
        self, watchdog, sample_agent_id, sample_task_id
    ):
        """Patrol detects tasks assigned to an agent in error state."""
        agent = AgentInfo(
            agent_id=sample_agent_id,
            status="error",
            last_heartbeat_at=None,
            budget_monthly_cents=5000,
            spent_monthly_cents=100,
            assigned_task_ids=[sample_task_id],
        )

        report = watchdog.patrol([agent])

        orphan_actions = [
            a for a in report.actions_taken
            if a["action"] == RecoveryAction.MARK_FAILED.value
        ]
        assert len(orphan_actions) == 1
        assert orphan_actions[0]["task_id"] == str(sample_task_id)

    def test_no_orphan_for_terminated_without_tasks(
        self, watchdog, sample_agent_id
    ):
        """Patrol does not flag terminated agent with no assigned tasks."""
        agent = AgentInfo(
            agent_id=sample_agent_id,
            status="terminated",
            last_heartbeat_at=None,
            budget_monthly_cents=5000,
            spent_monthly_cents=100,
            assigned_task_ids=[],
        )

        report = watchdog.patrol([agent])

        orphan_actions = [
            a for a in report.actions_taken
            if a["action"] == RecoveryAction.MARK_FAILED.value
        ]
        assert len(orphan_actions) == 0


class TestBudgetExceededDetection:
    """Tests for detecting budget-exceeded agents."""

    def test_detects_budget_exceeded(self, watchdog, sample_agent_id):
        """Patrol pauses agent that exceeded its monthly budget."""
        agent = AgentInfo(
            agent_id=sample_agent_id,
            status="executing",
            last_heartbeat_at=datetime.now(timezone.utc),
            budget_monthly_cents=5000,
            spent_monthly_cents=6000,
            assigned_task_ids=[],
        )

        report = watchdog.patrol([agent])

        pause_actions = [
            a for a in report.actions_taken
            if a["action"] == RecoveryAction.PAUSE.value
        ]
        assert len(pause_actions) == 1
        assert pause_actions[0]["agent_id"] == str(sample_agent_id)
        assert "exceeded" in pause_actions[0]["reason"].lower()

    def test_no_pause_for_within_budget(self, watchdog, sample_agent_id):
        """Patrol does not pause agent within budget."""
        agent = AgentInfo(
            agent_id=sample_agent_id,
            status="executing",
            last_heartbeat_at=datetime.now(timezone.utc),
            budget_monthly_cents=5000,
            spent_monthly_cents=4000,
            assigned_task_ids=[],
        )

        report = watchdog.patrol([agent])

        pause_actions = [
            a for a in report.actions_taken
            if a["action"] == RecoveryAction.PAUSE.value
        ]
        assert len(pause_actions) == 0

    def test_no_pause_for_zero_budget(self, watchdog, sample_agent_id):
        """Patrol does not check agents with zero budget (unlimited)."""
        agent = AgentInfo(
            agent_id=sample_agent_id,
            status="executing",
            last_heartbeat_at=datetime.now(timezone.utc),
            budget_monthly_cents=0,
            spent_monthly_cents=99999,
            assigned_task_ids=[],
        )

        report = watchdog.patrol([agent])

        pause_actions = [
            a for a in report.actions_taken
            if a["action"] == RecoveryAction.PAUSE.value
        ]
        assert len(pause_actions) == 0


class TestCircuitBrokenDetection:
    """Tests for detecting circuit-broken agents."""

    def test_detects_circuit_broken_with_elapsed_cooldown(
        self, watchdog, sample_agent_id
    ):
        """Patrol suggests half-open test when circuit cooldown has elapsed."""
        past_cooldown = datetime.now(timezone.utc) - timedelta(seconds=60)
        watchdog.set_circuit_states({
            sample_agent_id: {
                "state": "open",
                "cooldown_until": past_cooldown,
            }
        })

        agent = AgentInfo(
            agent_id=sample_agent_id,
            status="idle",
            last_heartbeat_at=datetime.now(timezone.utc),
            budget_monthly_cents=5000,
            spent_monthly_cents=100,
            assigned_task_ids=[],
        )

        report = watchdog.patrol([agent])

        circuit_actions = [
            a for a in report.actions_taken
            if a["action"] == RecoveryAction.HALF_OPEN_TEST.value
        ]
        assert len(circuit_actions) == 1

    def test_no_action_when_cooldown_active(self, watchdog, sample_agent_id):
        """Patrol does not act on circuit-broken agent still in cooldown."""
        future_cooldown = datetime.now(timezone.utc) + timedelta(seconds=300)
        watchdog.set_circuit_states({
            sample_agent_id: {
                "state": "open",
                "cooldown_until": future_cooldown,
            }
        })

        agent = AgentInfo(
            agent_id=sample_agent_id,
            status="idle",
            last_heartbeat_at=datetime.now(timezone.utc),
            budget_monthly_cents=5000,
            spent_monthly_cents=100,
            assigned_task_ids=[],
        )

        report = watchdog.patrol([agent])

        circuit_actions = [
            a for a in report.actions_taken
            if a["action"] == RecoveryAction.HALF_OPEN_TEST.value
        ]
        assert len(circuit_actions) == 0

    def test_no_action_for_closed_circuit(self, watchdog, sample_agent_id):
        """Patrol does not act on agents with closed circuits."""
        watchdog.set_circuit_states({
            sample_agent_id: {
                "state": "closed",
                "cooldown_until": None,
            }
        })

        agent = AgentInfo(
            agent_id=sample_agent_id,
            status="idle",
            last_heartbeat_at=datetime.now(timezone.utc),
            budget_monthly_cents=5000,
            spent_monthly_cents=100,
            assigned_task_ids=[],
        )

        report = watchdog.patrol([agent])

        circuit_actions = [
            a for a in report.actions_taken
            if a["action"] == RecoveryAction.HALF_OPEN_TEST.value
        ]
        assert len(circuit_actions) == 0


class TestPatrolReport:
    """Tests for patrol report accuracy."""

    def test_report_counts_agents_checked(self, watchdog):
        """PatrolReport correctly counts the number of agents checked."""
        agents = [
            AgentInfo(
                agent_id=uuid.uuid4(),
                status="idle",
                last_heartbeat_at=datetime.now(timezone.utc),
                budget_monthly_cents=5000,
                spent_monthly_cents=100,
                assigned_task_ids=[],
            )
            for _ in range(5)
        ]

        report = watchdog.patrol(agents)

        assert isinstance(report, PatrolReport)
        assert report.agents_checked == 5
        assert isinstance(report.timestamp, datetime)

    def test_report_counts_issues_found(self, watchdog, sample_agent_id):
        """PatrolReport correctly counts total issues found."""
        agents = [
            AgentInfo(
                agent_id=sample_agent_id,
                status="terminated",
                last_heartbeat_at=None,
                budget_monthly_cents=5000,
                spent_monthly_cents=100,
                assigned_task_ids=[uuid.uuid4(), uuid.uuid4()],
            ),
            AgentInfo(
                agent_id=uuid.uuid4(),
                status="executing",
                last_heartbeat_at=None,
                budget_monthly_cents=5000,
                spent_monthly_cents=100,
                assigned_task_ids=[],
            ),
        ]

        report = watchdog.patrol(agents)

        # 2 orphaned tasks + 1 stuck agent = 3 issues
        assert report.issues_found == 3
        assert len(report.actions_taken) == 3

    def test_report_empty_for_healthy_agents(self, watchdog):
        """PatrolReport shows zero issues for healthy agents."""
        agents = [
            AgentInfo(
                agent_id=uuid.uuid4(),
                status="idle",
                last_heartbeat_at=datetime.now(timezone.utc),
                budget_monthly_cents=5000,
                spent_monthly_cents=100,
                assigned_task_ids=[],
            )
        ]

        report = watchdog.patrol(agents)

        assert report.issues_found == 0
        assert report.actions_taken == []
        assert report.agents_checked == 1


class TestBackgroundPatrol:
    """Tests for start/stop background patrol lifecycle."""

    @pytest.mark.asyncio
    async def test_start_creates_task(self):
        """start_background_patrol creates an asyncio task."""
        config = WatchdogConfig(patrol_interval_seconds=1)
        watchdog = Watchdog(config=config)

        task = watchdog.start_background_patrol()

        assert isinstance(task, asyncio.Task)
        assert not task.done()

        await watchdog.stop()

    @pytest.mark.asyncio
    async def test_stop_cancels_task(self):
        """stop() cancels the background patrol task cleanly."""
        config = WatchdogConfig(patrol_interval_seconds=1)
        watchdog = Watchdog(config=config)

        task = watchdog.start_background_patrol()
        assert not task.done()

        await watchdog.stop()

        assert task.done()
        assert watchdog._patrol_task is None

    @pytest.mark.asyncio
    async def test_patrol_loop_runs_with_provider(self):
        """Background patrol runs with an agents_provider function."""
        config = WatchdogConfig(patrol_interval_seconds=0)
        watchdog = Watchdog(config=config)

        call_count = 0
        called = asyncio.Event()

        def provider():
            nonlocal call_count
            call_count += 1
            called.set()
            return []

        watchdog.start_background_patrol(agents_provider=provider)

        # Wait for the first patrol rather than sleeping a fixed interval: a
        # fixed sleep races the loop's own scheduling and flakes under load.
        try:
            await asyncio.wait_for(called.wait(), timeout=5)
        finally:
            await watchdog.stop()

        assert call_count >= 1

    @pytest.mark.asyncio
    async def test_stop_is_idempotent(self):
        """Calling stop() when no task is running does not raise."""
        config = WatchdogConfig(patrol_interval_seconds=1)
        watchdog = Watchdog(config=config)

        # Should not raise even without starting
        await watchdog.stop()


class TestStalledRunDetection:
    """Tests for silent stall detection on heartbeat runs (Phase 1.4)."""

    def _run(self, agent_id, last_output_at=None, started_at=None):
        return HeartbeatRun(
            agent_id=agent_id,
            started_at=started_at or datetime.now(timezone.utc),
            last_output_at=last_output_at,
        )

    def test_flags_run_silent_past_suspicion_threshold(
        self, watchdog, sample_agent_id
    ):
        """A run with no output for over an hour is flagged as stalled."""
        run = self._run(
            sample_agent_id,
            last_output_at=datetime.now(timezone.utc) - timedelta(hours=2),
        )
        # First patrol records the fingerprint baseline.
        assert watchdog.patrol([], [run]).actions_taken == []
        report = watchdog.patrol([], [run])
        assert len(report.actions_taken) == 1
        action = report.actions_taken[0]
        assert action["action"] == RecoveryAction.FLAG_STALLED.value
        assert action["run_id"] == str(run.id)
        assert action["liveness_state"] == "suspected_stale"

    def test_ignores_legitimately_idle_run(self, watchdog, sample_agent_id):
        """A quiet run that still makes progress is not flagged."""
        run = self._run(
            sample_agent_id,
            last_output_at=datetime.now(timezone.utc) - timedelta(hours=2),
        )
        assert watchdog.patrol([], [run]).actions_taken == []
        # Forward progress changes the stop-fingerprint.
        run.continuation_attempt += 1
        assert watchdog.patrol([], [run]).actions_taken == []

    def test_ignores_run_within_suspicion_window(self, watchdog, sample_agent_id):
        """A run that emitted output recently is not flagged."""
        run = self._run(
            sample_agent_id,
            last_output_at=datetime.now(timezone.utc) - timedelta(minutes=5),
        )
        watchdog.patrol([], [run])
        assert watchdog.patrol([], [run]).actions_taken == []

    def test_escalates_to_human_past_critical_threshold(
        self, watchdog, sample_agent_id
    ):
        """A run silent beyond four hours escalates to a human decision."""
        run = self._run(
            sample_agent_id,
            last_output_at=datetime.now(timezone.utc) - timedelta(hours=5),
        )
        watchdog.patrol([], [run])
        action = watchdog.patrol([], [run]).actions_taken[0]
        assert action["action"] == RecoveryAction.ESCALATE_HUMAN.value
        assert action["action"] != RecoveryAction.REASSIGN.value
        assert action["liveness_state"] == "confirmed_dead"

    def test_rearm_suppresses_repeat_flag(self, watchdog, sample_agent_id):
        """The same stalled run is not re-flagged inside the rearm window."""
        run = self._run(
            sample_agent_id,
            last_output_at=datetime.now(timezone.utc) - timedelta(hours=2),
        )
        watchdog.patrol([], [run])
        assert len(watchdog.patrol([], [run]).actions_taken) == 1
        assert watchdog.patrol([], [run]).actions_taken == []

    def test_finished_run_never_flagged(self, watchdog, sample_agent_id):
        """A finished run is out of scope for stall detection."""
        run = self._run(
            sample_agent_id,
            last_output_at=datetime.now(timezone.utc) - timedelta(hours=6),
        )
        run.finished_at = datetime.now(timezone.utc)
        watchdog.patrol([], [run])
        assert watchdog.patrol([], [run]).actions_taken == []

    def test_falls_back_to_started_at_when_no_output(
        self, watchdog, sample_agent_id
    ):
        """A run that never emitted output is measured from started_at."""
        run = self._run(
            sample_agent_id,
            started_at=datetime.now(timezone.utc) - timedelta(hours=2),
        )
        watchdog.patrol([], [run])
        assert len(watchdog.patrol([], [run]).actions_taken) == 1

    def test_stall_check_disabled(self, sample_agent_id):
        """stall_check=False skips stall detection entirely."""
        wd = Watchdog(config=WatchdogConfig(stall_check=False))
        run = self._run(
            sample_agent_id,
            last_output_at=datetime.now(timezone.utc) - timedelta(hours=6),
        )
        wd.patrol([], [run])
        assert wd.patrol([], [run]).actions_taken == []


class TestStopFingerprint:
    """Tests for the stop-fingerprint helper."""

    def test_stable_for_unchanged_run(self):
        """The same run state produces the same fingerprint."""
        run = HeartbeatRun(agent_id=uuid.uuid4())
        assert stop_fingerprint(run) == stop_fingerprint(run)

    def test_changes_on_new_output(self):
        """New output changes the fingerprint."""
        run = HeartbeatRun(agent_id=uuid.uuid4())
        before = stop_fingerprint(run)
        run.stdout_excerpt = "progress"
        run.last_output_at = datetime.now(timezone.utc)
        assert stop_fingerprint(run) != before

    def test_changes_on_continuation(self):
        """A new continuation attempt changes the fingerprint."""
        run = HeartbeatRun(agent_id=uuid.uuid4())
        before = stop_fingerprint(run)
        run.continuation_attempt += 1
        assert stop_fingerprint(run) != before
