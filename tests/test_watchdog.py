"""Tests for the Watchdog Auto-Recovery system.

Validates that the Watchdog correctly detects stuck, orphaned, budget-exceeded,
and circuit-broken agents, and takes appropriate recovery actions.
"""

import asyncio
import uuid
from datetime import datetime, timedelta, timezone

import pytest

from nexus.runtime.heartbeat import HeartbeatMonitor
from nexus.runtime.watchdog import (
    AgentInfo,
    PatrolReport,
    RecoveryAction,
    Watchdog,
    WatchdogConfig,
)


@pytest.fixture
def heartbeat_monitor():
    """Create a fresh HeartbeatMonitor for testing."""
    return HeartbeatMonitor(default_threshold_seconds=60)


@pytest.fixture
def watchdog(heartbeat_monitor):
    """Create a Watchdog with default config for testing."""
    config = WatchdogConfig(
        patrol_interval_seconds=1,
        stuck_threshold_seconds=300,
    )
    return Watchdog(heartbeat_monitor=heartbeat_monitor, config=config)


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
    async def test_start_creates_task(self, heartbeat_monitor):
        """start_background_patrol creates an asyncio task."""
        config = WatchdogConfig(patrol_interval_seconds=1)
        watchdog = Watchdog(heartbeat_monitor=heartbeat_monitor, config=config)

        task = watchdog.start_background_patrol()

        assert isinstance(task, asyncio.Task)
        assert not task.done()

        await watchdog.stop()

    @pytest.mark.asyncio
    async def test_stop_cancels_task(self, heartbeat_monitor):
        """stop() cancels the background patrol task cleanly."""
        config = WatchdogConfig(patrol_interval_seconds=1)
        watchdog = Watchdog(heartbeat_monitor=heartbeat_monitor, config=config)

        task = watchdog.start_background_patrol()
        assert not task.done()

        await watchdog.stop()

        assert task.done()
        assert watchdog._patrol_task is None

    @pytest.mark.asyncio
    async def test_patrol_loop_runs_with_provider(self, heartbeat_monitor):
        """Background patrol runs with an agents_provider function."""
        config = WatchdogConfig(patrol_interval_seconds=0)
        watchdog = Watchdog(heartbeat_monitor=heartbeat_monitor, config=config)

        call_count = 0

        def provider():
            nonlocal call_count
            call_count += 1
            return []

        watchdog.start_background_patrol(agents_provider=provider)

        # Give it a moment to run
        await asyncio.sleep(0.1)
        await watchdog.stop()

        assert call_count >= 1

    @pytest.mark.asyncio
    async def test_stop_is_idempotent(self, heartbeat_monitor):
        """Calling stop() when no task is running does not raise."""
        config = WatchdogConfig(patrol_interval_seconds=1)
        watchdog = Watchdog(heartbeat_monitor=heartbeat_monitor, config=config)

        # Should not raise even without starting
        await watchdog.stop()
