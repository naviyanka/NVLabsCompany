"""Claude Code Adapter - implements AgentAdapter Protocol via CLI subprocess.

Spawns the Claude Code CLI as an asyncio subprocess, passes tasks as prompts
with workspace context, captures output, and manages the process lifecycle.
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
from nexus.runtime.adapter import AgentSession, AgentStatus, TaskResult


# Default timeout for Claude Code execution
DEFAULT_TIMEOUT_SECONDS = 600

# Regex patterns for parsing Claude Code output
TOKEN_PATTERN = re.compile(
    r"(?:input|prompt)\s*tokens?[:\s]+(\d+)", re.IGNORECASE
)
OUTPUT_TOKEN_PATTERN = re.compile(
    r"(?:output|completion)\s*tokens?[:\s]+(\d+)", re.IGNORECASE
)
COST_PATTERN = re.compile(
    r"(?:cost|total)[:\s]+\$?([\d.]+)", re.IGNORECASE
)


class ClaudeCodeAdapter(BaseAdapter):
    """Agent adapter that spawns Claude Code CLI as a subprocess.

    Implements the full AgentAdapter Protocol by managing Claude Code
    as an asyncio subprocess. Provides workspace isolation per session,
    file system monitoring for artifacts, and cost tracking from output
    parsing.
    """

    adapter_type: str = "claude_code"

    def __init__(self) -> None:
        """Initialize the Claude Code adapter."""
        super().__init__()
        self._processes: dict[str, asyncio.subprocess.Process] = {}
        self._workspaces: dict[str, str] = {}

    def validate_config(self, config: dict[str, Any]) -> None:
        """Validate that required Claude Code configuration keys are present.

        Args:
            config: Configuration dictionary.

        Raises:
            ValueError: If required keys are missing.
        """
        # Claude Code adapter requires either a workspace or uses a temp dir
        # No strict requirements beyond what BaseAdapter checks
        pass

    async def _do_create_session(self, session: AgentSession) -> None:
        """Initialize Claude Code session with workspace isolation.

        Creates a temporary workspace directory for the session.

        Args:
            session: The newly created session.
        """
        workspace = session.config.get("workspace", None)
        if workspace:
            workspace_path = workspace
            os.makedirs(workspace_path, exist_ok=True)
        else:
            workspace_path = tempfile.mkdtemp(
                prefix=f"nexus_claude_code_{session.session_id[:8]}_"
            )

        self._workspaces[session.session_id] = workspace_path
        session.metadata["workspace"] = workspace_path
        session.metadata["timeout"] = session.config.get(
            "timeout", DEFAULT_TIMEOUT_SECONDS
        )
        session.metadata["cli_command"] = session.config.get(
            "cli_command", "claude"
        )

    async def _do_execute(
        self, session: AgentSession, task_id: uuid.UUID, payload: dict[str, Any]
    ) -> TaskResult:
        """Execute a task by spawning Claude Code CLI as a subprocess.

        Args:
            session: The active agent session.
            task_id: The task identifier.
            payload: Must contain 'prompt'. Optionally 'timeout', 'args'.

        Returns:
            TaskResult with captured output, artifacts, and parsed costs.
        """
        prompt = payload.get("prompt", "")
        timeout = payload.get("timeout", session.metadata.get("timeout", DEFAULT_TIMEOUT_SECONDS))
        extra_args = payload.get("args", [])
        workspace = self._workspaces.get(session.session_id, ".")
        cli_command = session.metadata.get("cli_command", "claude")

        # Build command
        cmd = [cli_command]
        if extra_args:
            cmd.extend(extra_args)

        # Track files before execution for artifact detection
        pre_files = self._snapshot_workspace(workspace)

        try:
            # Spawn subprocess
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=workspace,
            )
            self._processes[session.session_id] = process

            # Send prompt via stdin
            stdin_data = prompt.encode("utf-8")

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
                    # Wait briefly for graceful shutdown
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
            input_tokens = self._parse_tokens(stdout_text + stderr_text, TOKEN_PATTERN)
            output_tokens = self._parse_tokens(
                stdout_text + stderr_text, OUTPUT_TOKEN_PATTERN
            )
            cost_cents = self._parse_cost(stdout_text + stderr_text)

            # Detect new/modified files as artifacts
            post_files = self._snapshot_workspace(workspace)
            artifacts = self._detect_artifacts(pre_files, post_files, workspace)

            # Add stdout/stderr as artifacts
            if stdout_text.strip():
                artifacts.append({
                    "type": "stdout",
                    "content": stdout_text[:10000],  # Truncate large outputs
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
                    f"Exit code: {return_code}",
                    f"Workspace: {workspace}",
                ],
            )

        except FileNotFoundError:
            return TaskResult(
                task_id=task_id,
                agent_id=session.agent_id,
                success=False,
                error=f"Claude Code CLI not found: '{cli_command}'. "
                      f"Ensure it is installed and on PATH.",
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
        """Check if the Claude Code process is still running.

        Args:
            session: The active agent session.

        Returns:
            True if no process is active (idle) or process is running.
        """
        process = self._processes.get(session.session_id)
        if process is None:
            # No active process means session is idle but alive
            return True
        return process.returncode is None  # None means still running

    async def _do_terminate(self, session: AgentSession) -> None:
        """Terminate the Claude Code subprocess and clean up workspace.

        Args:
            session: The session being terminated.
        """
        # Kill any running process
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

        # Clean up conversation history
        self._conversation_history.pop(session.session_id, None)
        self._workspaces.pop(session.session_id, None)

    def _get_capabilities(self) -> list[str]:
        """Return Claude Code adapter capabilities.

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
        ]

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
        """Parse token count from Claude Code output.

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
        """Parse cost from Claude Code output.

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
