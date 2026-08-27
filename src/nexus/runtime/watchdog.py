"""Watchdog Auto-Recovery - periodic patrol to detect and recover unhealthy agents.

Performs scheduled patrols to identify and act on:
- Stuck agents: executing but heartbeat is stale beyond threshold
- Orphaned tasks: assigned to terminated/error agents
- Budget-exceeded agents: spending beyond their monthly allocation
- Circuit-broken agents: in cooldown states that may be ready for half-open test

Integrates with HeartbeatMonitor for liveness detection and uses pure logic
with no direct database access (receives agent state via AgentInfo dataclass).
"""

import asyncio
import hashlib
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from nexus.models.heartbeat_run import HeartbeatRun
from nexus.runtime.heartbeat import HeartbeatMonitor

logger = logging.getLogger(__name__)


def stop_fingerprint(run: HeartbeatRun) -> str:
    """Build a stable fingerprint of a run's observable progress.

    Two patrols that see the same fingerprint saw no forward progress: no new
    output, no new continuation attempt, no session change. A run that is
    merely quiet but still advancing changes at least one of these, so the
    fingerprint distinguishes "quiet but fine" from "stalled".

    Args:
        run: The heartbeat run to fingerprint.

    Returns:
        Hex digest of the run's progress-bearing fields.
    """
    parts = [
        str(run.last_output_at),
        str(run.continuation_attempt),
        str(run.session_id_after),
        str(run.stdout_excerpt),
        str(run.stderr_excerpt),
    ]
    return hashlib.sha256("\x1f".join(parts).encode()).hexdigest()


class RecoveryAction(str, Enum):
    """Actions the watchdog can take to recover agents.

    Values:
        RESET_IDLE: Reset a stuck agent back to idle state.
        REASSIGN: Reassign tasks from a failed agent to another.
        MARK_FAILED: Mark orphaned tasks as failed.
        PAUSE: Pause an agent that exceeded its budget.
        HALF_OPEN_TEST: Attempt a half-open test on a circuit-broken agent.
    """

    RESET_IDLE = "reset_idle"
    REASSIGN = "reassign"
    MARK_FAILED = "mark_failed"
    PAUSE = "pause"
    HALF_OPEN_TEST = "half_open_test"
    FLAG_STALLED = "flag_stalled"
    ESCALATE_HUMAN = "escalate_human"


@dataclass
class WatchdogConfig:
    """Configuration for watchdog patrol behavior.

    Attributes:
        patrol_interval_seconds: How often the background patrol runs.
        stuck_threshold_seconds: How long an agent can be executing without
            heartbeat before considered stuck.
        orphan_check: Whether to check for orphaned tasks.
        budget_check: Whether to check for budget-exceeded agents.
        circuit_check: Whether to check for circuit-broken agents.
        stall_check: Whether to check heartbeat runs for silent stalls.
        stall_suspicion_seconds: No output for this long makes a run suspect.
        stall_critical_seconds: No output for this long escalates to a human.
        stall_rearm_seconds: Minimum gap before the same run is flagged again.
    """

    patrol_interval_seconds: int = 30
    stuck_threshold_seconds: int = 300
    orphan_check: bool = True
    budget_check: bool = True
    circuit_check: bool = True
    stall_check: bool = True
    stall_suspicion_seconds: int = 3600
    stall_critical_seconds: int = 14400
    stall_rearm_seconds: int = 1800


@dataclass
class AgentInfo:
    """Agent state information for watchdog patrol.

    Provides all necessary agent data for patrol checks without
    requiring direct database access.

    Attributes:
        agent_id: Unique identifier for the agent.
        status: Current lifecycle status of the agent.
        last_heartbeat_at: Timestamp of the last heartbeat, or None if never.
        budget_monthly_cents: Monthly budget allocation in cents.
        spent_monthly_cents: Amount spent this month in cents.
        assigned_task_ids: List of task IDs currently assigned to this agent.
    """

    agent_id: uuid.UUID
    status: str
    last_heartbeat_at: datetime | None
    budget_monthly_cents: int
    spent_monthly_cents: int
    assigned_task_ids: list[uuid.UUID] = field(default_factory=list)


@dataclass
class PatrolReport:
    """Report summarizing the results of a single patrol run.

    Attributes:
        timestamp: When the patrol was conducted.
        actions_taken: List of dicts describing each recovery action taken.
        agents_checked: Total number of agents inspected.
        issues_found: Number of issues detected during patrol.
    """

    timestamp: datetime
    actions_taken: list[dict[str, Any]]
    agents_checked: int
    issues_found: int


class Watchdog:
    """Performs periodic patrols to detect and recover unhealthy agents.

    Integrates with HeartbeatMonitor for liveness detection and accepts
    agent state via AgentInfo dataclass (no direct DB access). Checks for
    stuck, orphaned, budget-exceeded, and circuit-broken agents, taking
    appropriate recovery actions for each.
    """

    def __init__(
        self,
        heartbeat_monitor: HeartbeatMonitor,
        config: WatchdogConfig | None = None,
    ) -> None:
        """Initialize the watchdog.

        Args:
            heartbeat_monitor: Monitor used to check agent heartbeat health.
            config: Optional configuration for patrol behavior. Uses defaults if None.
        """
        self._heartbeat_monitor = heartbeat_monitor
        self._config = config or WatchdogConfig()
        self._patrol_task: asyncio.Task[None] | None = None
        self._running = False
        self._circuit_states: dict[uuid.UUID, dict[str, Any]] = {}
        # run_id -> {'fingerprint': str, 'flagged_at': datetime | None}
        self._stall_states: dict[uuid.UUID, dict[str, Any]] = {}

    def set_circuit_states(self, states: dict[uuid.UUID, dict[str, Any]]) -> None:
        """Set circuit breaker states for patrol checks.

        Args:
            states: Mapping of agent_id to circuit state dict with keys:
                'state' (str): 'open', 'closed', or 'half_open'
                'cooldown_until' (datetime | None): When cooldown expires
        """
        self._circuit_states = states

    def patrol(
        self,
        agents: list[AgentInfo],
        runs: list[HeartbeatRun] | None = None,
    ) -> PatrolReport:
        """Perform a single patrol run across all provided agents.

        Checks each agent for health issues and takes recovery actions:
        1. Stuck agents (executing with stale heartbeat) -> RESET_IDLE
        2. Orphaned tasks (agent in terminated/error with tasks) -> MARK_FAILED
        3. Budget-exceeded agents (spent > budget) -> PAUSE
        4. Circuit-broken agents (open circuit, cooldown elapsed) -> HALF_OPEN_TEST
        5. Silently stalled runs -> FLAG_STALLED, then ESCALATE_HUMAN

        Args:
            agents: List of AgentInfo representing current agent states.
            runs: Optional active HeartbeatRun list for stall detection.

        Returns:
            PatrolReport summarizing all actions taken during this patrol.
        """
        now = datetime.now(timezone.utc)
        actions: list[dict[str, Any]] = []

        for agent in agents:
            # Check 1: Stuck agents
            stuck_actions = self._check_stuck(agent, now)
            actions.extend(stuck_actions)

            # Check 2: Orphaned tasks
            if self._config.orphan_check:
                orphan_actions = self._check_orphaned(agent, now)
                actions.extend(orphan_actions)

            # Check 3: Budget exceeded
            if self._config.budget_check:
                budget_actions = self._check_budget(agent, now)
                actions.extend(budget_actions)

            # Check 4: Circuit-broken
            if self._config.circuit_check:
                circuit_actions = self._check_circuit(agent, now)
                actions.extend(circuit_actions)

        # Check 5: silently stalled runs
        if self._config.stall_check and runs:
            for run in runs:
                actions.extend(self._check_stalled(run, now))

        return PatrolReport(
            timestamp=now,
            actions_taken=actions,
            agents_checked=len(agents),
            issues_found=len(actions),
        )

    def start_background_patrol(
        self, agents_provider: Any = None, runs_provider: Any = None
    ) -> asyncio.Task[None]:
        """Start periodic background patrol as an asyncio task.

        Args:
            agents_provider: Optional callable that returns list[AgentInfo].
                If None, patrols with an empty list (useful for testing lifecycle).
            runs_provider: Optional callable that returns list[HeartbeatRun]
                for stall detection.

        Returns:
            The created asyncio.Task running the patrol loop.
        """
        self._running = True
        self._patrol_task = asyncio.create_task(
            self._patrol_loop(agents_provider, runs_provider)
        )
        return self._patrol_task

    async def stop(self) -> None:
        """Stop the background patrol task.

        Cancels the running task and waits for it to finish cleanly.
        """
        self._running = False
        if self._patrol_task is not None:
            self._patrol_task.cancel()
            try:
                await self._patrol_task
            except asyncio.CancelledError:
                pass
            self._patrol_task = None

        # Hand the lease back. Without this it lingers for its full TTL and no
        # replica can patrol until it expires, so a restart leaves the fleet
        # unwatched for up to DEFAULT_LEASE_TTL_SECONDS.
        try:
            from nexus.governance.leader_election import get_leader_election

            await get_leader_election().release("watchdog-standalone")
        except Exception as exc:  # noqa: BLE001 - shutdown must not raise
            logger.warning("Could not release watchdog leader lease: %s", exc)

    async def _patrol_loop(
        self, agents_provider: Any, runs_provider: Any = None
    ) -> None:
        """Internal patrol loop running at configured interval.

        Lease-gated so replicas don't double-patrol; the no-Redis fallback
        elects every instance, preserving single-process behavior.

        Args:
            agents_provider: Callable returning current agent states, or None.
            runs_provider: Callable returning active heartbeat runs, or None.
        """
        from nexus.governance.leader_election import is_leader

        # A distinct lease from the scheduler-hosted patrol in watchdog_service.
        # Sharing "watchdog" would mean whichever driver acquired first starved
        # the other for the lease TTL.
        try:
            while self._running:
                if await is_leader("watchdog-standalone"):
                    if agents_provider is not None:
                        agents = agents_provider()
                    else:
                        agents = []
                    runs = runs_provider() if runs_provider is not None else None
                    self.patrol(agents, runs)
                await asyncio.sleep(self._config.patrol_interval_seconds)
        except asyncio.CancelledError:
            return

    def _check_stuck(
        self, agent: AgentInfo, now: datetime
    ) -> list[dict[str, Any]]:
        """Check if an agent is stuck in executing state.

        An agent is stuck if its status is 'executing' and its heartbeat
        is stale beyond the configured threshold.

        Args:
            agent: The agent info to check.
            now: Current timestamp.

        Returns:
            List of action dicts if the agent is stuck, empty otherwise.
        """
        if agent.status != "executing":
            return []

        # Check heartbeat staleness
        if agent.last_heartbeat_at is None:
            # No heartbeat ever recorded for an executing agent is stuck
            return [
                {
                    "action": RecoveryAction.RESET_IDLE.value,
                    "agent_id": str(agent.agent_id),
                    "reason": "Agent executing with no heartbeat recorded",
                    "timestamp": now.isoformat(),
                }
            ]

        elapsed = (now - agent.last_heartbeat_at).total_seconds()
        if elapsed > self._config.stuck_threshold_seconds:
            return [
                {
                    "action": RecoveryAction.RESET_IDLE.value,
                    "agent_id": str(agent.agent_id),
                    "reason": (
                        f"Agent executing with stale heartbeat "
                        f"({elapsed:.0f}s > {self._config.stuck_threshold_seconds}s)"
                    ),
                    "timestamp": now.isoformat(),
                }
            ]

        return []

    def _check_stalled(
        self, run: HeartbeatRun, now: datetime
    ) -> list[dict[str, Any]]:
        """Check whether an active run has silently stalled.

        A run is silent when nothing has been observed since
        `last_output_at` (or `started_at` if it never emitted). Silence alone
        is not a stall: the stop-fingerprint must also be unchanged since the
        previous patrol, which is what separates a legitimately idle run from
        a stalled one. Past the critical threshold the run escalates to a
        human decision rather than being auto-reassigned. Rearm suppresses
        repeat flags for the same run within `stall_rearm_seconds`.

        Args:
            run: The heartbeat run to check.
            now: Current timestamp.

        Returns:
            List of action dicts if the run is stalled, empty otherwise.
        """
        if run.finished_at is not None:
            self._stall_states.pop(run.id, None)
            return []

        reference = run.last_output_at or run.started_at
        if reference is None:
            return []
        if reference.tzinfo is None:
            reference = reference.replace(tzinfo=timezone.utc)
        silent_for = (now - reference).total_seconds()

        fingerprint = stop_fingerprint(run)
        state = self._stall_states.get(run.id)
        self._stall_states[run.id] = {
            "fingerprint": fingerprint,
            "flagged_at": state.get("flagged_at") if state else None,
        }

        if silent_for < self._config.stall_suspicion_seconds:
            return []

        # Forward progress since the last patrol: quiet but fine, not stalled.
        if state is None or state.get("fingerprint") != fingerprint:
            return []

        flagged_at = state.get("flagged_at")
        if (
            flagged_at is not None
            and (now - flagged_at).total_seconds() < self._config.stall_rearm_seconds
        ):
            return []

        self._stall_states[run.id]["flagged_at"] = now

        critical = silent_for >= self._config.stall_critical_seconds
        action = (
            RecoveryAction.ESCALATE_HUMAN if critical else RecoveryAction.FLAG_STALLED
        )
        return [
            {
                "action": action.value,
                "agent_id": str(run.agent_id),
                "run_id": str(run.id),
                "liveness_state": (
                    "confirmed_dead" if critical else "suspected_stale"
                ),
                "stop_fingerprint": fingerprint,
                "reason": (
                    f"Run silent for {silent_for:.0f}s with an unchanged "
                    f"stop-fingerprint (threshold "
                    f"{self._config.stall_critical_seconds if critical else self._config.stall_suspicion_seconds}s)"
                ),
                "timestamp": now.isoformat(),
            }
        ]

    def _check_orphaned(
        self, agent: AgentInfo, now: datetime
    ) -> list[dict[str, Any]]:
        """Check if an agent has orphaned tasks.

        Tasks are orphaned when assigned to an agent in terminated or error state.

        Args:
            agent: The agent info to check.
            now: Current timestamp.

        Returns:
            List of action dicts for each orphaned task, empty otherwise.
        """
        if agent.status not in ("terminated", "error"):
            return []

        if not agent.assigned_task_ids:
            return []

        actions: list[dict[str, Any]] = []
        for task_id in agent.assigned_task_ids:
            actions.append(
                {
                    "action": RecoveryAction.MARK_FAILED.value,
                    "agent_id": str(agent.agent_id),
                    "task_id": str(task_id),
                    "reason": (
                        f"Task orphaned: agent in '{agent.status}' state"
                    ),
                    "timestamp": now.isoformat(),
                }
            )

        return actions

    def _check_budget(
        self, agent: AgentInfo, now: datetime
    ) -> list[dict[str, Any]]:
        """Check if an agent has exceeded its budget.

        Args:
            agent: The agent info to check.
            now: Current timestamp.

        Returns:
            List of action dicts if budget exceeded, empty otherwise.
        """
        if agent.budget_monthly_cents <= 0:
            return []

        if agent.spent_monthly_cents > agent.budget_monthly_cents:
            return [
                {
                    "action": RecoveryAction.PAUSE.value,
                    "agent_id": str(agent.agent_id),
                    "reason": (
                        f"Budget exceeded: spent {agent.spent_monthly_cents} "
                        f"> budget {agent.budget_monthly_cents} cents"
                    ),
                    "timestamp": now.isoformat(),
                }
            ]

        return []

    def _check_circuit(
        self, agent: AgentInfo, now: datetime
    ) -> list[dict[str, Any]]:
        """Check if a circuit-broken agent is ready for half-open test.

        An agent qualifies for half-open test if its circuit is in 'open'
        state and the cooldown period has elapsed.

        Args:
            agent: The agent info to check.
            now: Current timestamp.

        Returns:
            List of action dicts if half-open test is warranted, empty otherwise.
        """
        circuit_state = self._circuit_states.get(agent.agent_id)
        if circuit_state is None:
            return []

        if circuit_state.get("state") != "open":
            return []

        cooldown_until = circuit_state.get("cooldown_until")
        if cooldown_until is not None and now < cooldown_until:
            return []

        return [
            {
                "action": RecoveryAction.HALF_OPEN_TEST.value,
                "agent_id": str(agent.agent_id),
                "reason": "Circuit breaker open with cooldown elapsed, attempting half-open test",
                "timestamp": now.isoformat(),
            }
        ]
