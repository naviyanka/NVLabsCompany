"""CLI Adapter - generalized CLI subprocess adapter for multiple AI backends.

Extends BaseAdapter to spawn any supported CLI backend as an asyncio subprocess.
The backend-specific command and argument construction is driven by CLIBackendInfo
from the CLIRegistry, making this a single adapter that supports multiple CLI tools.
"""

import asyncio
import os
import re
import shutil
import signal
import tempfile
import uuid
from pathlib import Path
from typing import Any

from nexus.adapters.base import BaseAdapter
from nexus.adapters.cli_registry import CLIBackendInfo, CLIRegistry
from nexus.runtime.adapter import AgentSession, AgentStatus, TaskResult


# Default timeout for CLI execution (10 minutes)
DEFAULT_TIMEOUT_SECONDS = 600

# Regex patterns for parsing CLI output
TOKEN_PATTERN = re.compile(
    r"(?:input|prompt)\s*tokens?[:\s]+(\d+)", re.IGNORECASE
)
OUTPUT_TOKEN_PATTERN = re.compile(
    r"(?:output|completion)\s*tokens?[:\s]+(\d+)", re.IGNORECASE
)
COST_PATTERN = re.compile(
    r"(?:cost|total)[:\s]+\$?([\d.]+)", re.IGNORECASE
)

# Sensitive environment variable patterns that should NOT be passed to
# subprocess environments unless explicitly needed by the backend.
_SENSITIVE_ENV_PATTERNS: list[str] = [
    "OPENAI_API_KEY",
    "ANTHROPIC_API_KEY",
    "SECRET_KEY",
    "DATABASE_URL",
    "DB_PASSWORD",
    "AWS_SECRET_ACCESS_KEY",
    "GITHUB_TOKEN",
    "GITLAB_TOKEN",
    "NEXUS_SECRET_KEY",
]


class CLIAdapter(BaseAdapter):
    """Generalized CLI adapter that supports multiple AI coding backends.

    Unlike ClaudeCodeAdapter which is hardcoded for the 'claude' CLI, this
    adapter uses CLIBackendInfo from the CLIRegistry to construct the
    appropriate command and arguments for any supported CLI backend.

    Configuration requires a 'backend' key specifying which CLI to use
    (e.g., 'claude', 'codex', 'aider', 'kiro-cli', 'opencode', 'agy').
    """

    adapter_type: str = "cli"

    def __init__(self) -> None:
        """Initialize the CLI adapter with a backend registry."""
        super().__init__()
        self._processes: dict[str, asyncio.subprocess.Process] = {}
        self._workspaces: dict[str, str] = {}
        self._registry = CLIRegistry(auto_detect=False)

    def validate_config(self, config: dict[str, Any]) -> None:
        """Validate that required CLI adapter configuration is present.

        Args:
            config: Configuration dictionary. Must contain 'backend' key.

        Raises:
            ValueError: If 'backend' key is missing or backend is unknown.
        """
        if "backend" not in config:
            raise ValueError(
                "CLIAdapter requires 'backend' key in config. "
                "Supported backends: "
                + ", ".join(b.id for b in self._registry.get_all())
            )

        backend_id = config["backend"]
        backend = self._registry.get_backend(backend_id)
        if backend is None:
            raise ValueError(
                f"Unknown CLI backend: '{backend_id}'. "
                f"Supported backends: "
                + ", ".join(b.id for b in self._registry.get_all())
            )

    async def _do_create_session(self, session: AgentSession) -> None:
        """Initialize CLI session with workspace isolation.

        Creates or uses a workspace directory and stores backend metadata
        in the session for use during execution. Sets the is_interactive
        and awaiting_input flags based on config.

        Args:
            session: The newly created session.
        """
        workspace = session.config.get("workspace", None)
        if workspace:
            workspace_path = workspace
            os.makedirs(workspace_path, exist_ok=True)
            session.metadata["_temp_workspace"] = False
        else:
            backend_id = session.config.get("backend", "cli")
            workspace_path = tempfile.mkdtemp(
                prefix=f"nexus_cli_{backend_id}_{session.session_id[:8]}_"
            )
            session.metadata["_temp_workspace"] = True

        self._workspaces[session.session_id] = workspace_path
        session.metadata["workspace"] = workspace_path
        session.metadata["timeout"] = session.config.get(
            "timeout", DEFAULT_TIMEOUT_SECONDS
        )
        session.metadata["backend"] = session.config["backend"]
        session.metadata["is_interactive"] = session.config.get(
            "interactive", False
        )
        session.metadata["awaiting_input"] = False

    async def _do_execute(
        self, session: AgentSession, task_id: uuid.UUID, payload: dict[str, Any]
    ) -> TaskResult:
        """Execute a task by spawning the configured CLI backend as a subprocess.

        Args:
            session: The active agent session.
            task_id: The task identifier.
            payload: Must contain 'prompt'. Optionally 'timeout', 'args'.

        Returns:
            TaskResult with captured output, artifacts, and parsed costs.
        """
        prompt = payload.get("prompt", "")
        timeout = payload.get(
            "timeout", session.metadata.get("timeout", DEFAULT_TIMEOUT_SECONDS)
        )
        extra_args = payload.get("args", [])
        workspace = self._workspaces.get(session.session_id, ".")
        backend_id = session.metadata.get("backend", "claude")

        backend = self._registry.get_backend(backend_id)
        if backend is None:
            return TaskResult(
                task_id=task_id,
                agent_id=session.agent_id,
                success=False,
                error=f"Backend '{backend_id}' not found in registry.",
            )

        # Build command arguments
        cmd = self._build_args(backend, prompt, extra_args)

        # Track files before execution for artifact detection
        pre_files = self._snapshot_workspace(workspace)

        # Write instruction file if backend supports it and a system prompt is available
        instruction_file_path: str | None = None
        system_prompt = (
            payload.get("system_prompt", "")
            or session.config.get("system_prompt", "")
        )
        if backend.instruction_path and system_prompt:
            instruction_file_path = self._write_instruction_file(
                workspace, backend, system_prompt, session
            )

        # Prepare environment - strip sensitive vars and backend-specific deletions.
        # Only pass env vars that the backend actually needs. Backends that require
        # specific API keys (e.g., claude needs ANTHROPIC_API_KEY, codex needs
        # OPENAI_API_KEY) should declare them via allow_env on CLIBackendInfo.
        env = os.environ.copy()
        for var in backend.delete_env:
            env.pop(var, None)
        # Strip sensitive variables unless the backend explicitly needs them
        allowed = set(getattr(backend, "allow_env", None) or [])
        for sensitive_var in _SENSITIVE_ENV_PATTERNS:
            if sensitive_var not in allowed:
                env.pop(sensitive_var, None)

        try:
            # Spawn subprocess
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=workspace,
                env=env,
            )
            self._processes[session.session_id] = process

            # For interactive sessions, spawn _stream_output as a background
            # task so output is surfaced in real time while the process runs.
            is_interactive = session.metadata.get("is_interactive", False)
            stream_task: asyncio.Task | None = None  # type: ignore[type-arg]
            if is_interactive and process.stdout is not None:
                stream_task = asyncio.create_task(
                    self._stream_output(process, session.session_id)
                )
                # Mark session as awaiting input once streaming starts
                session.metadata["awaiting_input"] = True

            # Send prompt via stdin if backend supports it
            stdin_data = prompt.encode("utf-8") if backend.supports_stdin else None

            try:
                if is_interactive:
                    # In interactive mode, write the initial prompt to stdin
                    # (if supported) but don't close stdin - keep it open for
                    # subsequent send_message() calls. Wait for the process to
                    # exit while _stream_output consumes stdout in the background.
                    if stdin_data and process.stdin is not None:
                        process.stdin.write(stdin_data + b"\n")
                        await process.stdin.drain()
                    await asyncio.wait_for(process.wait(), timeout=timeout)
                    # Ensure all buffered output is consumed
                    if stream_task is not None:
                        await stream_task
                    # Read any stderr that was buffered
                    stderr_bytes = b""
                    if process.stderr is not None:
                        stderr_bytes = await process.stderr.read()
                    # stdout was consumed by _stream_output
                    stdout_bytes = b""
                else:
                    stdout_bytes, stderr_bytes = await asyncio.wait_for(
                        process.communicate(input=stdin_data),
                        timeout=timeout,
                    )
            except asyncio.TimeoutError:
                # Cancel the stream task if it's running
                if stream_task is not None:
                    stream_task.cancel()
                    try:
                        await stream_task
                    except asyncio.CancelledError:
                        pass
                # Graceful termination: SIGTERM then SIGKILL
                self._add_log(
                    session.session_id,
                    f"Timeout after {timeout}s, sending SIGTERM",
                )
                try:
                    process.send_signal(signal.SIGTERM)
                    try:
                        await asyncio.wait_for(process.wait(), timeout=5.0)
                    except asyncio.TimeoutError:
                        self._add_log(
                            session.session_id,
                            "SIGTERM timeout, sending SIGKILL",
                        )
                        process.kill()
                        await process.wait()
                except ProcessLookupError:
                    pass

                return TaskResult(
                    task_id=task_id,
                    agent_id=session.agent_id,
                    success=False,
                    error=f"Execution timed out after {timeout} seconds",
                    logs=[f"Timeout: {timeout}s exceeded"],
                )

            stdout_text = stdout_bytes.decode("utf-8", errors="replace")
            stderr_text = stderr_bytes.decode("utf-8", errors="replace")
            return_code = process.returncode

            # Parse token counts and cost from output
            combined_output = stdout_text + stderr_text
            input_tokens = self._parse_tokens(combined_output, TOKEN_PATTERN)
            output_tokens = self._parse_tokens(
                combined_output, OUTPUT_TOKEN_PATTERN
            )
            cost_cents = self._parse_cost(combined_output)

            # Detect new/modified files as artifacts
            post_files = self._snapshot_workspace(workspace)
            artifacts = self._detect_artifacts(pre_files, post_files, workspace)

            # Add stdout/stderr as artifacts
            if stdout_text.strip():
                artifacts.append({
                    "type": "stdout",
                    "content": stdout_text[:10000],
                })
            if stderr_text.strip():
                artifacts.append({
                    "type": "stderr",
                    "content": stderr_text[:5000],
                })

            success = return_code == 0

            return TaskResult(
                task_id=task_id,
                agent_id=session.agent_id,
                success=success,
                output=stdout_text,
                error=stderr_text if not success else None,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                cost_cents=cost_cents,
                artifacts=artifacts,
                logs=[
                    f"Backend: {backend_id}",
                    f"Exit code: {return_code}",
                    f"Workspace: {workspace}",
                ],
            )

        except FileNotFoundError:
            return TaskResult(
                task_id=task_id,
                agent_id=session.agent_id,
                success=False,
                error=(
                    f"CLI backend '{backend.name}' not found: '{backend.command}'. "
                    f"Ensure it is installed and on PATH."
                ),
            )
        except Exception as e:
            return TaskResult(
                task_id=task_id,
                agent_id=session.agent_id,
                success=False,
                error=f"Subprocess error: {type(e).__name__}: {e}",
            )
        finally:
            self._processes.pop(session.session_id, None)
            # Clean up temporary instruction file
            if instruction_file_path:
                self._cleanup_instruction_file(instruction_file_path)

    async def send_message(self, session_id: str, message: str) -> str:
        """Send a message to the stdin of a running interactive process.

        Writes the given message (followed by a newline) to the process's
        stdin pipe. The process must be running and have an open stdin pipe.

        Args:
            session_id: The session identifier for the running process.
            message: The text message to send via stdin.

        Returns:
            Acknowledgment string confirming the message was sent.

        Raises:
            RuntimeError: If the process has already exited or is not found.
        """
        process = self._processes.get(session_id)
        if process is None:
            raise RuntimeError(
                f"No running process for session '{session_id}'. "
                "Process may have already exited."
            )
        if process.returncode is not None:
            raise RuntimeError(
                f"Process for session '{session_id}' has already exited "
                f"with return code {process.returncode}."
            )
        if process.stdin is None:
            raise RuntimeError(
                f"Process for session '{session_id}' has no stdin pipe."
            )

        try:
            encoded = message.encode("utf-8", errors="replace")
            process.stdin.write(encoded + b"\n")
            await process.stdin.drain()
        except BrokenPipeError:
            raise RuntimeError(
                f"Broken pipe: process for session '{session_id}' is no "
                "longer accepting input. The process may have exited."
            )

        # Update awaiting_input state
        session = self._sessions.get(session_id)
        if session:
            session.metadata["awaiting_input"] = False

        self._add_log(session_id, f"Sent message to stdin ({len(message)} chars)")
        return f"Message sent ({len(message)} chars)"

    async def _stream_output(
        self, process: asyncio.subprocess.Process, session_id: str
    ) -> None:
        """Read stdout from a process line-by-line and append to session logs.

        Reads incrementally from the process stdout pipe until EOF. Each
        line is decoded with errors='replace' and added to session logs.

        Args:
            process: The asyncio subprocess to read from.
            session_id: The session identifier for log attribution.
        """
        if process.stdout is None:
            return

        while True:
            line_bytes = await process.stdout.readline()
            if not line_bytes:
                break
            line = line_bytes.decode("utf-8", errors="replace").rstrip("\n")
            self._add_log(session_id, f"[stdout] {line}")

    async def _do_heartbeat(self, session: AgentSession) -> bool:
        """Check if the CLI process is still running.

        Args:
            session: The active agent session.

        Returns:
            True if no process is active (idle) or process is running.
        """
        process = self._processes.get(session.session_id)
        if process is None:
            return True
        return process.returncode is None

    async def _do_terminate(self, session: AgentSession) -> None:
        """Terminate the CLI subprocess and clean up workspace.

        Args:
            session: The session being terminated.
        """
        process = self._processes.pop(session.session_id, None)
        if process and process.returncode is None:
            try:
                process.send_signal(signal.SIGTERM)
                try:
                    await asyncio.wait_for(process.wait(), timeout=5.0)
                except asyncio.TimeoutError:
                    process.kill()
                    await process.wait()
            except ProcessLookupError:
                pass

        self._conversation_history.pop(session.session_id, None)

        # Clean up temp workspace directory if it was auto-created
        workspace_path = self._workspaces.pop(session.session_id, None)
        if workspace_path and session.metadata.get("_temp_workspace", False):
            try:
                shutil.rmtree(workspace_path, ignore_errors=True)
            except OSError:
                pass

    def _get_capabilities(self) -> list[str]:
        """Return CLI adapter capabilities.

        Returns:
            List of supported capability identifiers.
        """
        return [
            "execute_task",
            "subprocess_execution",
            "workspace_isolation",
            "file_system_artifacts",
            "cost_parsing",
            "timeout_handling",
            "graceful_termination",
            "multi_backend",
            "interactive_stdin",
        ]

    def _build_args(
        self,
        backend: CLIBackendInfo,
        prompt: str,
        extra_args: list[str] | None = None,
    ) -> list[str]:
        """Build the CLI command arguments for the given backend.

        Delegates to the backend's build_args method, which allows each
        CLIBackendInfo subclass to define its own argument construction logic.
        New backends only need to override build_args on their CLIBackendInfo
        rather than editing this adapter source.

        Args:
            backend: The backend info describing the CLI tool.
            prompt: The task prompt to pass.
            extra_args: Additional CLI arguments to append.

        Returns:
            List of command-line arguments ready for subprocess exec.
        """
        return backend.build_args(prompt, extra_args)

    def _write_instruction_file(
        self,
        workspace: str,
        backend: CLIBackendInfo,
        system_prompt: str,
        session: AgentSession,
    ) -> str | None:
        """Write a temporary instruction file that the CLI backend reads automatically.

        Each CLI backend has a designated instruction path (e.g., `.claude/CLAUDE.md`,
        `AGENTS.md`, `.kiro/steering/main.md`). This method writes the agent's system
        prompt to that path in the workspace so the CLI picks it up natively.

        Returns the absolute path of the written file (for cleanup), or None if skipped.
        """
        if not backend.instruction_path:
            return None

        instruction_path = Path(workspace) / backend.instruction_path
        try:
            # Create parent directories if needed
            instruction_path.parent.mkdir(parents=True, exist_ok=True)

            # Don't overwrite existing instruction files the user has set up
            if instruction_path.exists():
                self._add_log(
                    session.session_id,
                    f"Instruction file already exists at {instruction_path}, skipping write",
                )
                return None

            # Write the system prompt as the instruction file
            agent_name = session.config.get("agent_name", "Agent")
            content = (
                f"# {agent_name} — System Instructions\n\n"
                f"{system_prompt}\n"
            )
            instruction_path.write_text(content, encoding="utf-8")
            self._add_log(
                session.session_id,
                f"Wrote instruction file: {instruction_path}",
            )
            return str(instruction_path)
        except OSError as e:
            self._add_log(
                session.session_id,
                f"Failed to write instruction file: {e}",
            )
            return None

    def _cleanup_instruction_file(self, path: str) -> None:
        """Remove a temporary instruction file created for a CLI execution."""
        try:
            file_path = Path(path)
            if file_path.exists():
                file_path.unlink()
                # Remove parent dir if it's empty and was created by us
                parent = file_path.parent
                if parent.exists() and not any(parent.iterdir()):
                    parent.rmdir()
        except OSError:
            pass  # Best effort cleanup

    def _snapshot_workspace(self, workspace: str) -> dict[str, float]:
        """Take a snapshot of files in the workspace with modification times.

        Args:
            workspace: Path to the workspace directory.

        Returns:
            Dictionary mapping file paths to modification times.
        """
        snapshot: dict[str, float] = {}
        workspace_path = Path(workspace)
        if workspace_path.exists():
            try:
                for filepath in workspace_path.rglob("*"):
                    if filepath.is_file():
                        try:
                            snapshot[str(filepath)] = filepath.stat().st_mtime
                        except OSError:
                            pass
            except OSError:
                pass
        return snapshot

    def _detect_artifacts(
        self,
        pre: dict[str, float],
        post: dict[str, float],
        workspace: str,
    ) -> list[dict[str, Any]]:
        """Detect new or modified files as artifacts.

        Args:
            pre: File snapshot before execution.
            post: File snapshot after execution.
            workspace: The workspace path.

        Returns:
            List of artifact dictionaries for new/modified files.
        """
        artifacts: list[dict[str, Any]] = []
        for filepath, mtime in post.items():
            if filepath not in pre:
                artifacts.append({
                    "type": "file_created",
                    "path": filepath,
                    "workspace": workspace,
                })
            elif pre[filepath] < mtime:
                artifacts.append({
                    "type": "file_modified",
                    "path": filepath,
                    "workspace": workspace,
                })
        return artifacts

    def _parse_tokens(self, text: str, pattern: re.Pattern[str]) -> int:
        """Parse token count from CLI output.

        Args:
            text: The combined stdout/stderr text.
            pattern: Regex pattern to match token counts.

        Returns:
            Parsed token count, or 0 if not found.
        """
        match = pattern.search(text)
        if match:
            try:
                return int(match.group(1))
            except (ValueError, IndexError):
                pass
        return 0

    def _parse_cost(self, text: str) -> int:
        """Parse cost from CLI output.

        Args:
            text: The combined stdout/stderr text.

        Returns:
            Parsed cost in cents, or 0 if not found.
        """
        match = COST_PATTERN.search(text)
        if match:
            try:
                dollars = float(match.group(1))
                return int(dollars * 100)
            except (ValueError, IndexError):
                pass
        return 0
