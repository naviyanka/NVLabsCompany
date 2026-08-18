"""Agent Adapter Protocol - the core interface all agent implementations must satisfy."""

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Protocol, runtime_checkable


class AgentStatus(str, Enum):
    """Possible statuses for an agent session."""

    IDLE = "idle"
    CONFIGURING = "configuring"
    READY = "ready"
    EXECUTING = "executing"
    PAUSED = "paused"
    ERROR = "error"
    TERMINATED = "terminated"


@dataclass
class AgentSession:
    """Represents an active session with an agent adapter.

    Holds the session identity, configuration, and current state.
    """

    session_id: str
    agent_id: uuid.UUID
    adapter_type: str
    status: AgentStatus = AgentStatus.IDLE
    config: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class TaskResult:
    """Result returned from an agent task execution.

    Contains the output, cost, and any artifacts produced.
    """

    task_id: uuid.UUID
    agent_id: uuid.UUID
    success: bool
    output: Any = None
    error: str | None = None
    cost_cents: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    artifacts: list[dict[str, Any]] = field(default_factory=list)
    logs: list[str] = field(default_factory=list)
    started_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    completed_at: datetime | None = None
    duration_ms: int = 0


@runtime_checkable
class AgentAdapter(Protocol):
    """Protocol defining the interface for all agent adapters.

    Every external agent system (LangChain, CrewAI, custom LLM, etc.)
    communicates through this stable interface. Implementations must
    provide all 11 methods as async functions.
    """

    async def create_session(
        self, agent_id: uuid.UUID, config: dict[str, Any]
    ) -> AgentSession:
        """Create a new execution session for the given agent.

        Args:
            agent_id: The unique identifier for the agent.
            config: Configuration dictionary for the session.

        Returns:
            An initialized AgentSession instance.
        """
        ...

    async def execute_task(
        self, session: AgentSession, task_id: uuid.UUID, payload: dict[str, Any]
    ) -> TaskResult:
        """Execute a task within an active agent session.

        Args:
            session: The active agent session.
            task_id: The unique identifier for the task.
            payload: Task parameters and instructions.

        Returns:
            A TaskResult with output, cost, and execution details.
        """
        ...

    async def send_heartbeat(self, session: AgentSession) -> bool:
        """Send a heartbeat signal to confirm the session is alive.

        Args:
            session: The active agent session.

        Returns:
            True if the heartbeat was acknowledged.
        """
        ...

    async def get_status(self, session: AgentSession) -> AgentStatus:
        """Get the current status of an agent session.

        Args:
            session: The agent session to check.

        Returns:
            The current AgentStatus.
        """
        ...

    async def pause(self, session: AgentSession) -> bool:
        """Pause the agent session, suspending any active execution.

        Args:
            session: The agent session to pause.

        Returns:
            True if the pause was successful.
        """
        ...

    async def resume(self, session: AgentSession) -> bool:
        """Resume a paused agent session.

        Args:
            session: The paused agent session.

        Returns:
            True if the resume was successful.
        """
        ...

    async def terminate(self, session: AgentSession) -> bool:
        """Terminate the agent session and release all resources.

        Args:
            session: The agent session to terminate.

        Returns:
            True if termination was successful.
        """
        ...

    async def get_capabilities(self, session: AgentSession) -> list[str]:
        """Get the list of capabilities supported by this adapter.

        Args:
            session: The active agent session.

        Returns:
            List of capability identifiers.
        """
        ...

    async def get_cost(self, session: AgentSession) -> dict[str, int]:
        """Get the accumulated cost for the session.

        Args:
            session: The active agent session.

        Returns:
            Dictionary with cost_cents, input_tokens, output_tokens.
        """
        ...

    async def get_artifacts(self, session: AgentSession) -> list[dict[str, Any]]:
        """Get any artifacts produced during execution.

        Args:
            session: The active agent session.

        Returns:
            List of artifact metadata dictionaries.
        """
        ...

    async def get_logs(self, session: AgentSession) -> list[str]:
        """Get execution logs from the session.

        Args:
            session: The active agent session.

        Returns:
            List of log entries.
        """
        ...
