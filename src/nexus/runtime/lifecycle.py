"""Agent Lifecycle Manager - manages agent state transitions and operations."""

import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from nexus.models.agent import Agent
from nexus.runtime.adapter import AgentAdapter, AgentSession, AgentStatus


# Valid state transitions
_VALID_TRANSITIONS: dict[str, set[str]] = {
    "idle": {"configuring", "ready", "terminated"},
    "configuring": {"ready", "error", "terminated"},
    "ready": {"executing", "paused", "terminated"},
    "executing": {"idle", "paused", "error", "terminated"},
    "paused": {"ready", "idle", "terminated"},
    "error": {"idle", "configuring", "terminated"},
    "terminated": set(),
}


class LifecycleError(Exception):
    """Raised when an invalid lifecycle transition is attempted."""

    def __init__(self, agent_id: uuid.UUID, from_state: str, to_state: str) -> None:
        self.agent_id = agent_id
        self.from_state = from_state
        self.to_state = to_state
        super().__init__(
            f"Invalid transition for agent {agent_id}: {from_state} -> {to_state}"
        )


class AgentLifecycleManager:
    """Manages agent lifecycle state transitions and coordination with adapters.

    State machine:
        idle -> configuring -> ready -> executing -> idle
        Any state -> paused (except terminated)
        Any state -> error (on failure)
        Any state -> terminated (final)
    """

    def __init__(self, db: AsyncSession, adapter: AgentAdapter) -> None:
        self._db = db
        self._adapter = adapter
        self._sessions: dict[uuid.UUID, AgentSession] = {}

    def _validate_transition(
        self, agent_id: uuid.UUID, current: str, target: str
    ) -> None:
        """Validate that a state transition is allowed."""
        allowed = _VALID_TRANSITIONS.get(current, set())
        if target not in allowed:
            raise LifecycleError(agent_id, current, target)

    async def _update_status(self, agent_id: uuid.UUID, new_status: str) -> None:
        """Update agent status in the database."""
        stmt = (
            update(Agent)
            .where(Agent.id == agent_id)
            .values(status=new_status, updated_at=datetime.now(timezone.utc))
        )
        await self._db.execute(stmt)

    async def _get_agent(self, agent_id: uuid.UUID) -> Agent:
        """Fetch agent from database by ID."""
        stmt = select(Agent).where(Agent.id == agent_id)
        result = await self._db.execute(stmt)
        agent = result.scalar_one_or_none()
        if agent is None:
            raise ValueError(f"Agent {agent_id} not found")
        return agent

    async def create_agent(
        self, company_id: uuid.UUID, name: str, role: str, **kwargs: Any
    ) -> Agent:
        """Create a new agent in idle state.

        Args:
            company_id: The tenant company ID.
            name: Display name for the agent.
            role: The agent's organizational role.
            **kwargs: Additional agent fields.

        Returns:
            The newly created Agent instance.
        """
        agent = Agent(
            company_id=company_id,
            name=name,
            role=role,
            status="idle",
            **kwargs,
        )
        self._db.add(agent)
        await self._db.flush()
        return agent

    async def configure_agent(
        self, agent_id: uuid.UUID, config: dict[str, Any]
    ) -> Agent:
        """Move agent to configuring state and apply configuration.

        Args:
            agent_id: The agent to configure.
            config: Runtime configuration to apply.

        Returns:
            The updated Agent instance.
        """
        agent = await self._get_agent(agent_id)
        self._validate_transition(agent_id, agent.status, "configuring")
        await self._update_status(agent_id, "configuring")

        # Apply configuration
        stmt = (
            update(Agent)
            .where(Agent.id == agent_id)
            .values(
                runtime_config=config,
                status="ready",
                updated_at=datetime.now(timezone.utc),
            )
        )
        await self._db.execute(stmt)
        agent.status = "ready"
        agent.runtime_config = config
        return agent

    async def wake_agent(self, agent_id: uuid.UUID) -> AgentSession:
        """Wake an agent and create an active adapter session.

        Transitions: idle/ready -> ready, then creates adapter session.

        Args:
            agent_id: The agent to wake.

        Returns:
            An active AgentSession for the agent.
        """
        agent = await self._get_agent(agent_id)
        if agent.status not in ("idle", "ready", "paused"):
            self._validate_transition(agent_id, agent.status, "ready")

        session = await self._adapter.create_session(
            agent_id=agent_id,
            config=agent.adapter_config or {},
        )
        self._sessions[agent_id] = session

        await self._update_status(agent_id, "ready")
        return session

    async def execute_agent_task(
        self, agent_id: uuid.UUID, task_id: uuid.UUID, payload: dict[str, Any]
    ) -> Any:
        """Execute a task on an agent, managing state transitions.

        Transitions: ready -> executing -> idle (or error on failure).

        Args:
            agent_id: The agent to use.
            task_id: The task to execute.
            payload: Task parameters.

        Returns:
            The TaskResult from execution.
        """
        agent = await self._get_agent(agent_id)
        self._validate_transition(agent_id, agent.status, "executing")
        await self._update_status(agent_id, "executing")

        session = self._sessions.get(agent_id)
        if session is None:
            session = await self.wake_agent(agent_id)

        try:
            result = await self._adapter.execute_task(session, task_id, payload)
            await self._update_status(agent_id, "idle")
            return result
        except Exception as exc:
            await self._update_status(agent_id, "error")
            stmt = (
                update(Agent)
                .where(Agent.id == agent_id)
                .values(error_reason=str(exc))
            )
            await self._db.execute(stmt)
            raise

    async def monitor_agent(self, agent_id: uuid.UUID) -> dict[str, Any]:
        """Get monitoring info for an agent.

        Args:
            agent_id: The agent to monitor.

        Returns:
            Dictionary with status, last heartbeat, and session info.
        """
        agent = await self._get_agent(agent_id)
        session = self._sessions.get(agent_id)

        info: dict[str, Any] = {
            "agent_id": str(agent_id),
            "status": agent.status,
            "last_heartbeat_at": (
                agent.last_heartbeat_at.isoformat()
                if agent.last_heartbeat_at
                else None
            ),
            "has_active_session": session is not None,
        }

        if session:
            info["session_status"] = session.status.value
            info["session_created_at"] = session.created_at.isoformat()

        return info

    async def suspend_agent(
        self, agent_id: uuid.UUID, reason: str | None = None
    ) -> Agent:
        """Pause/suspend an agent.

        Args:
            agent_id: The agent to suspend.
            reason: Optional reason for the pause.

        Returns:
            The updated Agent instance.
        """
        agent = await self._get_agent(agent_id)
        self._validate_transition(agent_id, agent.status, "paused")

        stmt = (
            update(Agent)
            .where(Agent.id == agent_id)
            .values(
                status="paused",
                pause_reason=reason,
                paused_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc),
            )
        )
        await self._db.execute(stmt)

        # Pause the adapter session if active
        session = self._sessions.get(agent_id)
        if session:
            await self._adapter.pause(session)

        agent.status = "paused"
        return agent

    async def terminate_agent(self, agent_id: uuid.UUID) -> Agent:
        """Terminate an agent permanently.

        Args:
            agent_id: The agent to terminate.

        Returns:
            The updated Agent instance.
        """
        agent = await self._get_agent(agent_id)
        self._validate_transition(agent_id, agent.status, "terminated")
        await self._update_status(agent_id, "terminated")

        # Terminate the adapter session if active
        session = self._sessions.pop(agent_id, None)
        if session:
            await self._adapter.terminate(session)

        agent.status = "terminated"
        return agent
