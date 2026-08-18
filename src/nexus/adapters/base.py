"""Base Adapter - provides common logic for all AgentAdapter implementations.

This module provides the BaseAdapter abstract class that handles:
- Session management (create, track, cleanup)
- Cost accumulation (input_tokens, output_tokens, cost_cents per session)
- Artifact collection (list per session)
- Log buffering (list per session)
- Error handling wrapper (try/except returning error TaskResult)
- Heartbeat response handling
- Configuration validation (abstract method for subclasses)
"""

import importlib
import importlib.util
import pathlib
import sys
import uuid
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Any

# Import adapter types directly from the module file to avoid triggering
# nexus.runtime.__init__.py which has heavy dependencies (sqlalchemy etc.)
# that may not be available in all environments.
if "nexus.runtime.adapter" not in sys.modules:
    _adapter_path = (
        pathlib.Path(__file__).parent.parent / "runtime" / "adapter.py"
    )
    _spec = importlib.util.spec_from_file_location(
        "nexus.runtime.adapter", str(_adapter_path)
    )
    if _spec and _spec.loader:
        _module = importlib.util.module_from_spec(_spec)
        sys.modules["nexus.runtime.adapter"] = _module
        _spec.loader.exec_module(_module)

from nexus.runtime.adapter import AgentSession, AgentStatus, TaskResult


class BaseAdapter(ABC):
    """Abstract base class for all agent adapters.

    Provides common session tracking, cost accumulation, artifact collection,
    log buffering, and error handling. Subclasses override the _do_* hooks
    to implement provider-specific behavior.
    """

    adapter_type: str = "base"

    def __init__(self) -> None:
        """Initialize the base adapter with empty session tracking."""
        self._sessions: dict[str, AgentSession] = {}
        self._cost_tracking: dict[str, dict[str, int]] = {}
        self._artifacts: dict[str, list[dict[str, Any]]] = {}
        self._logs: dict[str, list[str]] = {}
        self._conversation_history: dict[str, list[dict[str, Any]]] = {}

    @abstractmethod
    def validate_config(self, config: dict[str, Any]) -> None:
        """Validate adapter-specific configuration.

        Args:
            config: Configuration dictionary to validate.

        Raises:
            ValueError: If required configuration keys are missing or invalid.
        """
        ...

    async def create_session(
        self, agent_id: uuid.UUID, config: dict[str, Any]
    ) -> AgentSession:
        """Create a new execution session for the given agent.

        Validates config, initializes tracking structures, then delegates
        to _do_create_session for provider-specific initialization.

        Args:
            agent_id: The unique identifier for the agent.
            config: Configuration dictionary for the session.

        Returns:
            An initialized AgentSession instance.

        Raises:
            ValueError: If configuration validation fails.
        """
        self.validate_config(config)

        session_id = str(uuid.uuid4())
        session = AgentSession(
            session_id=session_id,
            agent_id=agent_id,
            adapter_type=self.adapter_type,
            status=AgentStatus.CONFIGURING,
            config=config,
            created_at=datetime.now(timezone.utc),
            metadata={},
        )

        self._sessions[session_id] = session
        self._cost_tracking[session_id] = {
            "cost_cents": 0,
            "input_tokens": 0,
            "output_tokens": 0,
        }
        self._artifacts[session_id] = []
        self._logs[session_id] = []
        self._conversation_history[session_id] = []

        await self._do_create_session(session)
        session.status = AgentStatus.READY
        self._add_log(session_id, f"Session created for agent {agent_id}")
        return session

    async def execute_task(
        self, session: AgentSession, task_id: uuid.UUID, payload: dict[str, Any]
    ) -> TaskResult:
        """Execute a task within an active agent session with error handling.

        Wraps _do_execute in error handling, tracks timing and costs.

        Args:
            session: The active agent session.
            task_id: The unique identifier for the task.
            payload: Task parameters and instructions.

        Returns:
            A TaskResult with output, cost, and execution details.
        """
        started_at = datetime.now(timezone.utc)
        session.status = AgentStatus.EXECUTING
        self._add_log(session.session_id, f"Executing task {task_id}")

        try:
            result = await self._do_execute(session, task_id, payload)
            completed_at = datetime.now(timezone.utc)
            duration_ms = int(
                (completed_at - started_at).total_seconds() * 1000
            )
            result.started_at = started_at
            result.completed_at = completed_at
            result.duration_ms = duration_ms

            # Accumulate costs
            self._accumulate_cost(
                session.session_id,
                result.cost_cents,
                result.input_tokens,
                result.output_tokens,
            )

            # Collect artifacts
            if result.artifacts:
                self._artifacts[session.session_id].extend(result.artifacts)

            # Buffer logs
            if result.logs:
                self._logs[session.session_id].extend(result.logs)

            session.status = AgentStatus.READY
            self._add_log(
                session.session_id,
                f"Task {task_id} completed (success={result.success})",
            )
            return result

        except Exception as e:
            completed_at = datetime.now(timezone.utc)
            duration_ms = int(
                (completed_at - started_at).total_seconds() * 1000
            )
            session.status = AgentStatus.ERROR
            error_msg = f"{type(e).__name__}: {e}"
            self._add_log(
                session.session_id, f"Task {task_id} failed: {error_msg}"
            )
            return TaskResult(
                task_id=task_id,
                agent_id=session.agent_id,
                success=False,
                output=None,
                error=error_msg,
                started_at=started_at,
                completed_at=completed_at,
                duration_ms=duration_ms,
            )

    async def send_heartbeat(self, session: AgentSession) -> bool:
        """Send a heartbeat signal to confirm the session is alive.

        Args:
            session: The active agent session.

        Returns:
            True if the session is alive and tracking.
        """
        if session.session_id not in self._sessions:
            return False
        if session.status == AgentStatus.TERMINATED:
            return False
        return await self._do_heartbeat(session)

    async def get_status(self, session: AgentSession) -> AgentStatus:
        """Get the current status of an agent session.

        Args:
            session: The agent session to check.

        Returns:
            The current AgentStatus.
        """
        if session.session_id in self._sessions:
            return self._sessions[session.session_id].status
        return AgentStatus.TERMINATED

    async def pause(self, session: AgentSession) -> bool:
        """Pause the agent session.

        Args:
            session: The agent session to pause.

        Returns:
            True if the pause was successful.
        """
        if session.status in (AgentStatus.READY, AgentStatus.EXECUTING):
            session.status = AgentStatus.PAUSED
            self._add_log(session.session_id, "Session paused")
            return True
        return False

    async def resume(self, session: AgentSession) -> bool:
        """Resume a paused agent session.

        Args:
            session: The paused agent session.

        Returns:
            True if the resume was successful.
        """
        if session.status == AgentStatus.PAUSED:
            session.status = AgentStatus.READY
            self._add_log(session.session_id, "Session resumed")
            return True
        return False

    async def terminate(self, session: AgentSession) -> bool:
        """Terminate the agent session and release all resources.

        Args:
            session: The agent session to terminate.

        Returns:
            True if termination was successful.
        """
        if session.session_id in self._sessions:
            await self._do_terminate(session)
            session.status = AgentStatus.TERMINATED
            self._add_log(session.session_id, "Session terminated")
            # Clean up tracking
            self._sessions.pop(session.session_id, None)
            return True
        return False

    async def get_capabilities(self, session: AgentSession) -> list[str]:
        """Get the list of capabilities supported by this adapter.

        Args:
            session: The active agent session.

        Returns:
            List of capability identifiers.
        """
        return self._get_capabilities()

    async def get_cost(self, session: AgentSession) -> dict[str, int]:
        """Get the accumulated cost for the session.

        Args:
            session: The active agent session.

        Returns:
            Dictionary with cost_cents, input_tokens, output_tokens.
        """
        return self._cost_tracking.get(
            session.session_id,
            {"cost_cents": 0, "input_tokens": 0, "output_tokens": 0},
        )

    async def get_artifacts(
        self, session: AgentSession
    ) -> list[dict[str, Any]]:
        """Get any artifacts produced during execution.

        Args:
            session: The active agent session.

        Returns:
            List of artifact metadata dictionaries.
        """
        return self._artifacts.get(session.session_id, [])

    async def get_logs(self, session: AgentSession) -> list[str]:
        """Get execution logs from the session.

        Args:
            session: The active agent session.

        Returns:
            List of log entries.
        """
        return self._logs.get(session.session_id, [])

    # --- Hook methods for subclasses to override ---

    async def _do_create_session(self, session: AgentSession) -> None:
        """Provider-specific session initialization.

        Override in subclasses for custom setup logic.

        Args:
            session: The newly created session.
        """
        pass

    @abstractmethod
    async def _do_execute(
        self, session: AgentSession, task_id: uuid.UUID, payload: dict[str, Any]
    ) -> TaskResult:
        """Provider-specific task execution logic.

        Must be implemented by all subclasses.

        Args:
            session: The active agent session.
            task_id: The unique identifier for the task.
            payload: Task parameters and instructions.

        Returns:
            A TaskResult with output and execution details.
        """
        ...

    async def _do_heartbeat(self, session: AgentSession) -> bool:
        """Provider-specific heartbeat logic.

        Override in subclasses that need custom heartbeat behavior.

        Args:
            session: The active agent session.

        Returns:
            True if the heartbeat was acknowledged.
        """
        return True

    async def _do_terminate(self, session: AgentSession) -> None:
        """Provider-specific termination and cleanup logic.

        Override in subclasses that need custom teardown.

        Args:
            session: The session being terminated.
        """
        pass

    def _get_capabilities(self) -> list[str]:
        """Return static list of capabilities for this adapter type.

        Override in subclasses to advertise specific features.

        Returns:
            List of capability identifiers.
        """
        return ["execute_task"]

    # --- Utility methods ---

    def _accumulate_cost(
        self,
        session_id: str,
        cost_cents: int,
        input_tokens: int,
        output_tokens: int,
    ) -> None:
        """Accumulate cost metrics for a session.

        Args:
            session_id: The session to update.
            cost_cents: Additional cost in cents.
            input_tokens: Additional input tokens consumed.
            output_tokens: Additional output tokens produced.
        """
        if session_id in self._cost_tracking:
            self._cost_tracking[session_id]["cost_cents"] += cost_cents
            self._cost_tracking[session_id]["input_tokens"] += input_tokens
            self._cost_tracking[session_id]["output_tokens"] += output_tokens

    def _add_log(self, session_id: str, message: str) -> None:
        """Add a log entry for a session.

        Args:
            session_id: The session to log to.
            message: The log message.
        """
        if session_id in self._logs:
            timestamp = datetime.now(timezone.utc).isoformat()
            self._logs[session_id].append(f"[{timestamp}] {message}")

    def _add_artifact(
        self, session_id: str, artifact: dict[str, Any]
    ) -> None:
        """Add an artifact to the session's collection.

        Args:
            session_id: The session to add the artifact to.
            artifact: The artifact metadata dictionary.
        """
        if session_id in self._artifacts:
            self._artifacts[session_id].append(artifact)
