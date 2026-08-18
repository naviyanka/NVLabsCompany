"""Heartbeat Monitor - tracks agent liveness and detects unresponsive agents."""

import uuid
from datetime import datetime, timezone


class HeartbeatMonitor:
    """Tracks last heartbeat times for agents and detects stale sessions.

    Maintains an in-memory registry of heartbeats. In production, this
    would be backed by Redis for distributed operation, but the interface
    remains the same.
    """

    def __init__(self, default_threshold_seconds: int = 60) -> None:
        """Initialize the heartbeat monitor.

        Args:
            default_threshold_seconds: Default number of seconds after which
                an agent is considered stale if no heartbeat received.
        """
        self._heartbeats: dict[uuid.UUID, datetime] = {}
        self._default_threshold = default_threshold_seconds

    def register_heartbeat(self, agent_id: uuid.UUID) -> datetime:
        """Record a heartbeat for the given agent.

        Args:
            agent_id: The agent sending the heartbeat.

        Returns:
            The timestamp recorded for this heartbeat.
        """
        now = datetime.now(timezone.utc)
        self._heartbeats[agent_id] = now
        return now

    def check_health(
        self, agent_id: uuid.UUID, threshold_seconds: int | None = None
    ) -> bool:
        """Check if an agent is healthy based on its last heartbeat.

        Args:
            agent_id: The agent to check.
            threshold_seconds: Custom threshold in seconds. Uses default if None.

        Returns:
            True if the agent has heartbeated within the threshold window.
            False if stale or never registered.
        """
        last_beat = self._heartbeats.get(agent_id)
        if last_beat is None:
            return False

        threshold = threshold_seconds or self._default_threshold
        elapsed = (datetime.now(timezone.utc) - last_beat).total_seconds()
        return elapsed <= threshold

    def get_stale_agents(
        self, threshold_seconds: int | None = None
    ) -> list[uuid.UUID]:
        """Get list of agents that have not sent a heartbeat within threshold.

        Args:
            threshold_seconds: Custom threshold in seconds. Uses default if None.

        Returns:
            List of agent IDs that are considered stale.
        """
        threshold = threshold_seconds or self._default_threshold
        now = datetime.now(timezone.utc)
        stale: list[uuid.UUID] = []

        for agent_id, last_beat in self._heartbeats.items():
            elapsed = (now - last_beat).total_seconds()
            if elapsed > threshold:
                stale.append(agent_id)

        return stale

    def get_last_heartbeat(self, agent_id: uuid.UUID) -> datetime | None:
        """Get the last heartbeat time for an agent.

        Args:
            agent_id: The agent to look up.

        Returns:
            The datetime of the last heartbeat, or None if never registered.
        """
        return self._heartbeats.get(agent_id)

    def remove_agent(self, agent_id: uuid.UUID) -> None:
        """Remove an agent from heartbeat tracking.

        Args:
            agent_id: The agent to remove.
        """
        self._heartbeats.pop(agent_id, None)
