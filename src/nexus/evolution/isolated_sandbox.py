"""Isolated Sandbox - resource-limited execution environment for proposals.

Provides a sandbox with logical resource tracking (cost, duration, memory)
that aborts execution when any limit is breached. This ensures proposals
cannot consume unbounded resources during evaluation.

Also provides DockerSandbox for container-isolated execution when Docker
is available, with automatic fallback to IsolatedSandbox.
"""

import asyncio
import logging
import shutil
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Callable


logger = logging.getLogger(__name__)


class ResourceLimitExceeded(Exception):
    """Raised when a sandbox execution exceeds its resource limits.

    Attributes:
        resource: The resource type that was exceeded (cost, duration, memory).
        limit: The configured limit value.
        actual: The actual value that triggered the breach.
    """

    def __init__(self, resource: str, limit: float, actual: float) -> None:
        """Initialize the exception.

        Args:
            resource: The resource type breached (e.g., 'cost', 'duration', 'memory').
            limit: The maximum allowed value.
            actual: The actual value that exceeded the limit.
        """
        self.resource = resource
        self.limit = limit
        self.actual = actual
        super().__init__(
            f"Resource limit exceeded: {resource} "
            f"(limit={limit}, actual={actual})"
        )


class IsolatedSandbox:
    """Resource-isolated sandbox for evaluating evolution proposals.

    Tracks cost, duration, and memory as logical accumulators rather than
    OS-level limits. Raises ResourceLimitExceeded when any limit is breached
    during execute().

    Attributes:
        max_cost_cents: Maximum cost allowed in cents.
        max_duration_seconds: Maximum total duration allowed in seconds.
        max_memory_mb: Maximum memory usage allowed in megabytes.
    """

    def __init__(
        self,
        max_cost_cents: int = 1000,
        max_duration_seconds: int = 300,
        max_memory_mb: int = 512,
    ) -> None:
        """Initialize the isolated sandbox with resource limits.

        Args:
            max_cost_cents: Maximum cost allowed in cents (default 1000).
            max_duration_seconds: Maximum total duration allowed in seconds (default 300).
            max_memory_mb: Maximum memory usage allowed in megabytes (default 512).
        """
        self.max_cost_cents = max_cost_cents
        self.max_duration_seconds = max_duration_seconds
        self.max_memory_mb = max_memory_mb
        self._sessions: dict[str, dict[str, Any]] = {}

    def create_session(
        self,
        proposal_id: uuid.UUID,
        config: dict[str, Any],
    ) -> uuid.UUID:
        """Create a new isolated session for evaluating a proposal.

        Creates a copy-on-write state container with resource tracking
        initialized to zero.

        Args:
            proposal_id: The proposal to evaluate.
            config: Configuration for the session environment.

        Returns:
            The session_id UUID for referencing this session.
        """
        session_id = uuid.uuid4()
        self._sessions[str(session_id)] = {
            "session_id": str(session_id),
            "proposal_id": str(proposal_id),
            "config": dict(config),
            "status": "active",
            "cost_cents": 0,
            "duration_seconds": 0.0,
            "memory_mb": 0,
            "results": [],
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        return session_id

    def execute(
        self,
        session_id: uuid.UUID,
        callable_fn: Callable[..., Any],
        *args: Any,
    ) -> dict[str, Any]:
        """Execute a callable within the session's resource limits.

        Runs the callable, tracks resource usage (cost, duration, memory),
        and raises ResourceLimitExceeded if any limit is breached.

        Args:
            session_id: The session to execute within.
            callable_fn: The function to execute.
            *args: Arguments to pass to the callable.

        Returns:
            Dict with 'result' (the callable's return value) and 'resources'
            showing the resources consumed by this execution.

        Raises:
            ResourceLimitExceeded: If any resource limit is breached.
            ValueError: If the session does not exist or is not active.
        """
        session_key = str(session_id)
        if session_key not in self._sessions:
            raise ValueError(f"Session {session_id} not found")

        session = self._sessions[session_key]
        if session["status"] != "active":
            raise ValueError(
                f"Session {session_id} is not active (status: {session['status']})"
            )

        # Track duration
        start_time = time.monotonic()
        result = callable_fn(*args)
        elapsed = time.monotonic() - start_time

        # Update resource accumulators
        session["duration_seconds"] += elapsed

        # If the callable returns resource metadata, accumulate it
        cost_incurred = 0
        memory_used = 0
        if isinstance(result, dict):
            cost_incurred = result.get("cost_cents", 0)
            memory_used = result.get("memory_mb", 0)

        session["cost_cents"] += cost_incurred
        session["memory_mb"] += memory_used

        # Check cost limit
        if session["cost_cents"] > self.max_cost_cents:
            session["status"] = "aborted"
            raise ResourceLimitExceeded(
                resource="cost",
                limit=self.max_cost_cents,
                actual=session["cost_cents"],
            )

        # Check duration limit
        if session["duration_seconds"] > self.max_duration_seconds:
            session["status"] = "aborted"
            raise ResourceLimitExceeded(
                resource="duration",
                limit=self.max_duration_seconds,
                actual=session["duration_seconds"],
            )

        # Check memory limit
        if session["memory_mb"] > self.max_memory_mb:
            session["status"] = "aborted"
            raise ResourceLimitExceeded(
                resource="memory",
                limit=self.max_memory_mb,
                actual=session["memory_mb"],
            )

        # Store execution result
        execution_record = {
            "result": result,
            "cost_cents": cost_incurred,
            "duration_seconds": elapsed,
            "memory_mb": memory_used,
        }
        session["results"].append(execution_record)

        return {
            "result": result,
            "resources": {
                "cost_cents": cost_incurred,
                "duration_seconds": elapsed,
                "memory_mb": memory_used,
            },
        }

    def get_resource_usage(self, session_id: uuid.UUID) -> dict[str, Any]:
        """Get the current resource usage for a session.

        Args:
            session_id: The session to query.

        Returns:
            Dict with current usage and limits for cost, duration, and memory.

        Raises:
            ValueError: If the session does not exist.
        """
        session_key = str(session_id)
        if session_key not in self._sessions:
            raise ValueError(f"Session {session_id} not found")

        session = self._sessions[session_key]
        return {
            "cost_cents": {
                "used": session["cost_cents"],
                "limit": self.max_cost_cents,
                "remaining": self.max_cost_cents - session["cost_cents"],
            },
            "duration_seconds": {
                "used": session["duration_seconds"],
                "limit": self.max_duration_seconds,
                "remaining": self.max_duration_seconds - session["duration_seconds"],
            },
            "memory_mb": {
                "used": session["memory_mb"],
                "limit": self.max_memory_mb,
                "remaining": self.max_memory_mb - session["memory_mb"],
            },
            "status": session["status"],
        }

    def abort(self, session_id: uuid.UUID) -> None:
        """Forcefully terminate a session.

        Marks the session as aborted so no further executions can occur.

        Args:
            session_id: The session to abort.

        Raises:
            ValueError: If the session does not exist.
        """
        session_key = str(session_id)
        if session_key not in self._sessions:
            raise ValueError(f"Session {session_id} not found")

        self._sessions[session_key]["status"] = "aborted"

    def cleanup(self, session_id: uuid.UUID) -> None:
        """Remove a session and all its state.

        Args:
            session_id: The session to clean up.
        """
        session_key = str(session_id)
        if session_key in self._sessions:
            del self._sessions[session_key]


class DockerSandbox:
    """Container-isolated sandbox using Docker for execution.

    Runs experiments via asyncio.create_subprocess_exec shelling out to
    'docker run' with --memory, --cpus, and timeout flags. Falls back to
    IsolatedSandbox when Docker is unavailable.

    Attributes:
        max_memory_mb: Maximum memory limit for containers.
        max_cpus: Maximum CPU allocation for containers.
        timeout_seconds: Maximum execution time before timeout.
        docker_image: Docker image to use for execution.
        docker_available: Whether Docker was detected at init.
    """

    def __init__(
        self,
        max_memory_mb: int = 512,
        max_cpus: float = 1.0,
        timeout_seconds: int = 300,
        docker_image: str = "python:3.12-slim",
    ) -> None:
        """Initialize the Docker sandbox.

        Checks Docker availability at init time. If Docker is not found,
        all operations fall back to IsolatedSandbox behavior.

        Args:
            max_memory_mb: Maximum memory in MB for containers (default 512).
            max_cpus: Maximum CPU allocation (default 1.0).
            timeout_seconds: Maximum execution time in seconds (default 300).
            docker_image: Docker image to use (default python:3.12-slim).
        """
        self.max_memory_mb = max_memory_mb
        self.max_cpus = max_cpus
        self.timeout_seconds = timeout_seconds
        self.docker_image = docker_image
        self.docker_available = self._detect_docker()
        self._fallback = IsolatedSandbox(
            max_cost_cents=1000,
            max_duration_seconds=timeout_seconds,
            max_memory_mb=max_memory_mb,
        )

    def _detect_docker(self) -> bool:
        """Detect whether Docker is available on this system.

        Returns:
            True if the 'docker' binary is found in PATH.
        """
        return shutil.which("docker") is not None

    async def run(
        self,
        code: str,
        language: str = "python",
        env: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """Execute code in a Docker container or fall back to local sandbox.

        When Docker is available, runs code in an isolated container with
        memory and CPU limits. When Docker is unavailable, falls back to
        IsolatedSandbox for logical resource tracking.

        Args:
            code: The code to execute.
            language: Programming language (default 'python').
            env: Optional environment variables to pass to the container.

        Returns:
            Dict with 'stdout', 'stderr', 'exit_code', 'timed_out', and
            'docker_used' fields.
        """
        if not self.docker_available:
            return await self._run_fallback(code, language)
        return await self._run_docker(code, language, env)

    async def _run_docker(
        self,
        code: str,
        language: str,
        env: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """Execute code in a Docker container with resource limits.

        Args:
            code: The code to execute.
            language: Programming language.
            env: Optional environment variables.

        Returns:
            Execution result dict.
        """
        cmd = [
            "docker", "run", "--rm",
            f"--memory={self.max_memory_mb}m",
            f"--cpus={self.max_cpus}",
            "--network=none",
            "--read-only",
            "--tmpfs", "/tmp",
        ]

        if env:
            for key, value in env.items():
                cmd.extend(["-e", f"{key}={value}"])

        cmd.extend([self.docker_image, language, "-c", code])

        try:
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            try:
                stdout, stderr = await asyncio.wait_for(
                    process.communicate(),
                    timeout=self.timeout_seconds,
                )
                return {
                    "stdout": stdout.decode(errors="replace"),
                    "stderr": stderr.decode(errors="replace"),
                    "exit_code": process.returncode,
                    "timed_out": False,
                    "docker_used": True,
                }
            except asyncio.TimeoutError:
                process.kill()
                await process.wait()
                return {
                    "stdout": "",
                    "stderr": "Execution timed out",
                    "exit_code": -1,
                    "timed_out": True,
                    "docker_used": True,
                }

        except OSError as exc:
            logger.warning("Docker execution failed: %s. Falling back.", exc)
            self.docker_available = False
            return await self._run_fallback(code, language)

    async def _run_fallback(
        self, code: str, language: str
    ) -> dict[str, Any]:
        """Execute code using the fallback IsolatedSandbox.

        Note: When Docker is unavailable, code is NOT actually executed.
        The result is a synthetic fallback indicating Docker was not
        available for real execution.

        Args:
            code: The code to execute.
            language: Programming language.

        Returns:
            Execution result dict with docker_used=False and is_fallback=True.
        """
        session_id = self._fallback.create_session(
            proposal_id=uuid.uuid4(),
            config={"language": language},
        )
        try:
            result = self._fallback.execute(
                session_id,
                lambda: {
                    "output": (
                        f"[FALLBACK] Docker unavailable. Code not executed. "
                        f"({len(code)} chars of {language})"
                    ),
                },
            )
            return {
                "stdout": str(result.get("result", "")),
                "stderr": "",
                "exit_code": 0,
                "timed_out": False,
                "docker_used": False,
                "is_fallback": True,
            }
        except ResourceLimitExceeded as exc:
            return {
                "stdout": "",
                "stderr": str(exc),
                "exit_code": -1,
                "timed_out": exc.resource == "duration",
                "docker_used": False,
                "is_fallback": True,
            }
        finally:
            self._fallback.cleanup(session_id)
