"""Kill Switch and Circuit Breaker - emergency controls for agent safety."""

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any


@dataclass
class KillSwitchState:
    """State of a kill switch activation.

    Attributes:
        company_id: The company affected.
        is_active: Whether the kill switch is currently active.
        reason: Why the kill switch was activated.
        activated_at: When the kill switch was activated.
        activated_by: Who activated it.
        affected_agents: List of agent IDs that were paused.
    """

    company_id: uuid.UUID
    is_active: bool = False
    reason: str = ""
    activated_at: datetime | None = None
    activated_by: str | None = None
    affected_agents: list[uuid.UUID] = field(default_factory=list)


@dataclass
class AgentKillState:
    """State of a per-agent kill switch.

    Attributes:
        agent_id: The agent affected.
        is_active: Whether the kill switch is active for this agent.
        reason: Why the agent was paused.
        activated_at: When the switch was activated.
    """

    agent_id: uuid.UUID
    is_active: bool = False
    reason: str = ""
    activated_at: datetime | None = None


class KillSwitch:
    """Emergency kill switch for pausing agents at company or individual level.

    Provides immediate shutdown capability for safety-critical situations.
    When activated at the company level, all agents in that company are paused.
    Individual agent kill switches can target specific agents.
    """

    def __init__(self) -> None:
        """Initialize the kill switch manager."""
        self._company_states: dict[uuid.UUID, KillSwitchState] = {}
        self._agent_states: dict[uuid.UUID, AgentKillState] = {}
        # Company to agents mapping for company-wide kills
        self._company_agents: dict[uuid.UUID, set[uuid.UUID]] = {}

    def register_agent(self, company_id: uuid.UUID, agent_id: uuid.UUID) -> None:
        """Register an agent with its company for kill switch tracking.

        Args:
            company_id: The company the agent belongs to.
            agent_id: The agent's identifier.
        """
        if company_id not in self._company_agents:
            self._company_agents[company_id] = set()
        self._company_agents[company_id].add(agent_id)

    def activate(
        self,
        company_id: uuid.UUID,
        reason: str,
        activated_by: str = "system",
    ) -> KillSwitchState:
        """Activate the kill switch for an entire company.

        Pauses all agents in the company immediately.

        Args:
            company_id: The company to shut down.
            reason: Why the kill switch is being activated.
            activated_by: Who is activating it.

        Returns:
            The KillSwitchState with affected agents listed.
        """
        affected_agents = list(self._company_agents.get(company_id, set()))

        state = KillSwitchState(
            company_id=company_id,
            is_active=True,
            reason=reason,
            activated_at=datetime.now(timezone.utc),
            activated_by=activated_by,
            affected_agents=affected_agents,
        )
        self._company_states[company_id] = state

        # Also mark each agent as killed
        for agent_id in affected_agents:
            self._agent_states[agent_id] = AgentKillState(
                agent_id=agent_id,
                is_active=True,
                reason=f"Company kill switch: {reason}",
                activated_at=datetime.now(timezone.utc),
            )

        return state

    def activate_agent(
        self, agent_id: uuid.UUID, reason: str
    ) -> AgentKillState:
        """Activate the kill switch for a single agent.

        Args:
            agent_id: The agent to pause.
            reason: Why the agent is being paused.

        Returns:
            The AgentKillState.
        """
        state = AgentKillState(
            agent_id=agent_id,
            is_active=True,
            reason=reason,
            activated_at=datetime.now(timezone.utc),
        )
        self._agent_states[agent_id] = state
        return state

    def deactivate(self, company_id: uuid.UUID) -> None:
        """Deactivate the kill switch for a company.

        Resumes all agents that were paused by the company kill switch.

        Args:
            company_id: The company to resume.
        """
        state = self._company_states.get(company_id)
        if state:
            state.is_active = False
            # Resume agents that were paused by company switch
            for agent_id in state.affected_agents:
                agent_state = self._agent_states.get(agent_id)
                if agent_state and "Company kill switch" in agent_state.reason:
                    agent_state.is_active = False

    def deactivate_agent(self, agent_id: uuid.UUID) -> None:
        """Deactivate the kill switch for a single agent.

        Args:
            agent_id: The agent to resume.
        """
        state = self._agent_states.get(agent_id)
        if state:
            state.is_active = False

    def is_active(self, company_id: uuid.UUID) -> bool:
        """Check if the kill switch is active for a company.

        Args:
            company_id: The company to check.

        Returns:
            True if the company kill switch is currently active.
        """
        state = self._company_states.get(company_id)
        return state.is_active if state else False

    def is_agent_killed(self, agent_id: uuid.UUID) -> bool:
        """Check if a specific agent is killed/paused.

        Args:
            agent_id: The agent to check.

        Returns:
            True if the agent's kill switch is active.
        """
        state = self._agent_states.get(agent_id)
        return state.is_active if state else False

    def get_state(self, company_id: uuid.UUID) -> KillSwitchState | None:
        """Get the kill switch state for a company.

        Args:
            company_id: The company to check.

        Returns:
            The KillSwitchState, or None if never activated.
        """
        return self._company_states.get(company_id)


@dataclass
class CircuitBreakerState:
    """Internal state for an agent's circuit breaker.

    Attributes:
        agent_id: The agent being monitored.
        consecutive_failures: Number of consecutive failures.
        is_open: Whether the circuit is open (agent is blocked).
        last_failure_at: When the last failure occurred.
        opened_at: When the circuit was opened.
        cooldown_seconds: Time before the circuit resets.
    """

    agent_id: uuid.UUID
    consecutive_failures: int = 0
    is_open: bool = False
    last_failure_at: datetime | None = None
    opened_at: datetime | None = None
    cooldown_seconds: int = 300


class CircuitBreaker:
    """Circuit breaker pattern for agent execution safety.

    Opens (blocks the agent) after N consecutive failures.
    Auto-resets after a configurable cooldown period.
    Prevents cascading failures from misbehaving agents.
    """

    def __init__(
        self,
        failure_threshold: int = 5,
        cooldown_seconds: int = 300,
    ) -> None:
        """Initialize the circuit breaker.

        Args:
            failure_threshold: Consecutive failures before circuit opens.
            cooldown_seconds: Seconds before an open circuit resets.
        """
        self._failure_threshold = failure_threshold
        self._cooldown_seconds = cooldown_seconds
        self._states: dict[uuid.UUID, CircuitBreakerState] = {}

    def _get_state(self, agent_id: uuid.UUID) -> CircuitBreakerState:
        """Get or create the circuit breaker state for an agent.

        Args:
            agent_id: The agent to look up.

        Returns:
            The CircuitBreakerState for the agent.
        """
        if agent_id not in self._states:
            self._states[agent_id] = CircuitBreakerState(
                agent_id=agent_id,
                cooldown_seconds=self._cooldown_seconds,
            )
        return self._states[agent_id]

    def record_failure(self, agent_id: uuid.UUID) -> bool:
        """Record a failure for an agent.

        If this causes the consecutive failure count to reach the
        threshold, the circuit opens.

        Args:
            agent_id: The agent that failed.

        Returns:
            True if the circuit just opened due to this failure.
        """
        state = self._get_state(agent_id)
        state.consecutive_failures += 1
        state.last_failure_at = datetime.now(timezone.utc)

        if state.consecutive_failures >= self._failure_threshold and not state.is_open:
            state.is_open = True
            state.opened_at = datetime.now(timezone.utc)
            return True

        return False

    def record_success(self, agent_id: uuid.UUID) -> None:
        """Record a success for an agent, resetting the failure counter.

        Args:
            agent_id: The agent that succeeded.
        """
        state = self._get_state(agent_id)
        state.consecutive_failures = 0
        # A success while circuit is open closes it
        if state.is_open:
            state.is_open = False
            state.opened_at = None

    def is_open(self, agent_id: uuid.UUID) -> bool:
        """Check if the circuit breaker is open for an agent.

        If the cooldown period has elapsed since the circuit opened,
        it transitions to half-open (returns False to allow a test request).

        Args:
            agent_id: The agent to check.

        Returns:
            True if the circuit is open (agent should be blocked).
        """
        state = self._get_state(agent_id)

        if not state.is_open:
            return False

        # Check if cooldown has elapsed (auto-reset)
        if state.opened_at:
            elapsed = datetime.now(timezone.utc) - state.opened_at
            if elapsed >= timedelta(seconds=state.cooldown_seconds):
                # Transition to half-open - allow next request
                state.is_open = False
                state.opened_at = None
                state.consecutive_failures = 0
                return False

        return True

    def get_failure_count(self, agent_id: uuid.UUID) -> int:
        """Get the current consecutive failure count for an agent.

        Args:
            agent_id: The agent to check.

        Returns:
            Number of consecutive failures.
        """
        state = self._get_state(agent_id)
        return state.consecutive_failures

    def reset(self, agent_id: uuid.UUID) -> None:
        """Manually reset the circuit breaker for an agent.

        Args:
            agent_id: The agent to reset.
        """
        if agent_id in self._states:
            state = self._states[agent_id]
            state.is_open = False
            state.consecutive_failures = 0
            state.opened_at = None
