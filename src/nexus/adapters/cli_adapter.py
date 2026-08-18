"""CLI Adapter - generalized CLI subprocess adapter for multiple AI backends.

Extends BaseAdapter to spawn any supported CLI backend as an asyncio subprocess.
The backend-specific command and argument construction is driven by CLIBackendInfo
from the CLIRegistry, making this a single adapter that supports multiple CLI tools.
"""

import asyncio
import os
import re
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
        in the session for use during execution.

        Args:
            session: The newly created session.
        """
        workspace = session.config.get("workspace", None)
        if workspace:
            workspace_path = workspace
            os.makedirs(workspace_path, exist_ok=True)
        else:
            backend_id = session.config.get("backend", "cli")
            workspace_path = tempfile.mkdtemp(
                prefix=f"nexus_cli_{backend_id}_{session.session_id[:8]}_"
            )

        self._workspaces[session.session_id] = workspace_path
        session.metadata["workspace"] = workspace_path
        session.metadata["timeout"] = session.config.get(
            "timeout", DEFAULT_TIMEOUT_SECONDS
        )
        session.metadata["backend"] = session.config["backend"]

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

        # Prepare environment - remove vars specified by backend
        env = os.environ.copy()
        for var in backend.delete_env:
            env.pop(var, None)

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

            # Send prompt via stdin if backend supports it
            stdin_data = prompt.encode("utf-8") if backend.supports_stdin else None

            try:
                stdout_bytes, stderr_bytes = await asyncio.wait_for(
                    process.communicate(input=stdin_data),
                    timeout=timeout,
                )
            except asyncio.TimeoutError:
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
        self._workspaces.pop(session.session_id, None)

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
        ]

    def _build_args(
        self,
        backend: CLIBackendInfo,
        prompt: str,
        extra_args: list[str] | None = None,
    ) -> list[str]:
        """Build the CLI command arguments for the given backend.

        Each backend has different conventions for how prompts and options
        are passed. This method constructs the appropriate argument list.

        Args:
            backend: The backend info describing the CLI tool.
            prompt: The task prompt to pass.
            extra_args: Additional CLI arguments to append.

        Returns:
            List of command-line arguments ready for subprocess exec.
        """
        cmd = [backend.command]

        if backend.id == "claude":
            # Claude Code: reads prompt from stdin, supports --print for
            # non-interactive mode
            cmd.append("--print")
            if extra_args:
                cmd.extend(extra_args)

        elif backend.id == "codex":
            # Codex CLI: pass prompt as positional argument
            cmd.append("--quiet")
            if extra_args:
                cmd.extend(extra_args)
            cmd.append(prompt)

        elif backend.id == "aider":
            # Aider: uses --message flag for non-interactive prompt
            cmd.extend(["--message", prompt])
            cmd.append("--yes")
            if extra_args:
                cmd.extend(extra_args)

        elif backend.id == "kiro-cli":
            # Kiro CLI: prompt via stdin
            if extra_args:
                cmd.extend(extra_args)

        elif backend.id == "opencode":
            # OpenCode: prompt as positional argument
            if extra_args:
                cmd.extend(extra_args)
            cmd.append(prompt)

        elif backend.id == "agy":
            # Agy: prompt as positional argument
            if extra_args:
                cmd.extend(extra_args)
            cmd.append(prompt)

        else:
            # Generic fallback: append prompt as argument
            if extra_args:
                cmd.extend(extra_args)
            cmd.append(prompt)

        return cmd

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
