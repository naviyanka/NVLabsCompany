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
import subprocess
import tempfile
import time
import uuid
from pathlib import Path
from typing import Any

from nexus.adapters.base import BaseAdapter
from nexus.adapters.cli_registry import (
    CLIBackendInfo,
    CLIRegistry,
    _redact_home,
    get_cli_registry,
)
from nexus.governance.fs_roots import is_link, pinned_directory
from nexus.runtime.adapter import AgentSession, AgentStatus, TaskResult

# Create a file that must not exist yet. O_NOFOLLOW is POSIX only; O_EXCL alone
# already refuses an existing link on every platform.
_CREATE_NEW = (
    os.O_WRONLY | os.O_CREAT | os.O_EXCL
    | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_BINARY", 0)
)


def _resolves_to_itself(path: Path) -> bool:
    """True when no symlink or junction lies anywhere on ``path``."""
    return os.path.normcase(str(path.resolve())) == os.path.normcase(str(path))


# Default timeout for CLI execution (10 minutes)
DEFAULT_TIMEOUT_SECONDS = 600

# Most bytes kept from each of stdout and stderr; the rest is drained and dropped
# so a chatty CLI cannot exhaust server memory.
MAX_OUTPUT_BYTES = 1_000_000

# cmd.exe re-parses the command line of a .cmd/.bat shim, so no quoting makes
# these characters safe in its arguments.
_CMD_SHIM_UNSAFE = frozenset('"%&|<>^!\r\n')

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


_SECRET_NAME_MARKERS = ("KEY", "TOKEN", "SECRET", "PASSWORD", "PASSWD", "CREDENTIAL")


def _filter_env(env: dict[str, str], allow: list[str] | None) -> dict[str, str]:
    """Drop secret-looking variables unless the backend allowlists them.

    Name-based so a new ``*_API_KEY`` or ``*_TOKEN`` is stripped without
    anyone remembering to list it; the explicit list covers the rest.
    """
    allowed = {v.upper() for v in allow or []}
    return {
        k: v
        for k, v in env.items()
        if k.upper() in allowed
        or not (
            k.upper() in _SENSITIVE_ENV_PATTERNS
            or any(m in k.upper() for m in _SECRET_NAME_MARKERS)
        )
    }


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
        if not backend.execution_supported:
            raise ValueError(
                f"CLI backend '{backend.id}' is catalog-only: its non-interactive "
                "invocation is not verified"
            )

    async def _do_create_session(self, session: AgentSession) -> None:
        """Initialize CLI session with workspace isolation.

        Creates or uses a workspace directory and stores backend metadata
        in the session for use during execution. Sets the is_interactive
        and awaiting_input flags based on config.

        Agent worktrees are not made here. The server sets
        ``session.worktree_path`` after this returns when the agent session
        holds one (see ``nexus.services.worktree_service``), and execution
        then runs in it. The old ``use_worktree``/``auto_merge`` options,
        which created, merged and removed worktrees in whatever repository
        the config named, are refused rather than silently ignored.

        Args:
            session: The newly created session.
        """
        for legacy in ("use_worktree", "auto_merge"):
            if session.config.get(legacy):
                raise ValueError(
                    f"{legacy} is no longer supported; agent worktrees are managed by the server"
                )
        workspace = session.config.get("workspace", None)

        if workspace:
            # ponytail: a configured directory is still honoured for callers
            # that set one; agent worktrees override it at execution.
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
        # Canonical ID, so an alias ("antigravity") runs the backend it names.
        session.metadata["backend"] = self._registry.resolve_backend_id(
            session.config["backend"]
        )
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
        # Stored employee args first, then per-request args; both are guarded.
        extra_args = [
            *(session.config.get("extra_args") or []),
            *(payload.get("args") or []),
        ]
        from nexus.tools.access import check_cli_args

        refused = check_cli_args(extra_args)
        if refused:
            return TaskResult(
                task_id=task_id, agent_id=session.agent_id, success=False, error=refused
            )
        # The session's agent worktree when it has one, else the directory the
        # session was created with. Never the server's own working directory.
        workspace = session.worktree_path or self._workspaces.get(session.session_id)
        if not workspace:
            return TaskResult(
                task_id=task_id,
                agent_id=session.agent_id,
                success=False,
                error="Session has no workspace",
            )
        # No default: a session without a known, executable backend fails
        # closed rather than running some other CLI.
        backend_id = session.metadata.get("backend")
        backend = self._registry.get_backend(backend_id)
        if backend is None or not backend.execution_supported:
            return TaskResult(
                task_id=task_id,
                agent_id=session.agent_id,
                success=False,
                error=f"CLI backend '{backend_id}' is unknown or not executable.",
            )
        backend_id = backend.id

        # The executable comes only from the catalog's command candidates on
        # PATH, never from config or the request. Unresolved falls back to the
        # bare command, which fails below as "not found".
        executable = get_cli_registry().get_path(backend_id) or backend.command
        model = str(session.config.get("model") or "")

        system_prompt = (
            payload.get("system_prompt", "")
            or session.config.get("system_prompt", "")
        )
        if system_prompt and not backend.instruction_path:
            # No instruction file this CLI reads natively: carry it inline.
            prompt = f"{system_prompt}\n\n---\n\n{prompt}"

        # A task attempt's permission mode comes from the server-built context
        # and maps to cataloged flags only. A backend without flags for the
        # mode is refused rather than run with its default permissions.
        work_mode = getattr(getattr(session, "context", None), "work_mode", None)
        try:
            cmd = self._build_args(
                backend, prompt, extra_args, model=model, executable=executable,
                work_mode=work_mode,
            )
        except ValueError as exc:
            return TaskResult(
                task_id=task_id, agent_id=session.agent_id, success=False, error=str(exc)
            )
        if executable.lower().endswith((".cmd", ".bat")) and any(
            _CMD_SHIM_UNSAFE & set(arg) for arg in cmd[1:]
        ):
            return TaskResult(
                task_id=task_id,
                agent_id=session.agent_id,
                success=False,
                error=(
                    f"{backend.name} is installed as a Windows batch shim, which "
                    "cannot safely receive quotes, %, &, |, <, >, ^, ! or line "
                    "breaks in arguments. Install a native executable or rephrase."
                ),
            )
        stdin_prompt = backend.prompt_transport == "stdin"
        # Off the event loop: a cache miss spawns `<cli> --version`, which
        # would otherwise stall every other chat while it runs.
        version = await asyncio.to_thread(get_cli_registry().probe_version, backend_id)
        started = time.monotonic()

        def _meta(exit_code: int | None) -> dict[str, Any]:
            return {
                "type": "cli_execution",
                "adapter": "cli",
                "backend": backend_id,
                "model": model,
                "executable": _redact_home(executable),
                "version": version,
                "duration_ms": int((time.monotonic() - started) * 1000),
                "exit_code": exit_code,
                "session_id": session.session_id,
                "task_id": str(task_id),
            }

        # Track files before execution for artifact detection
        pre_files = self._snapshot_workspace(workspace)

        # Write instruction file if backend supports it and a system prompt is available
        instruction_file_path: str | None = None
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
        from nexus.config import settings

        operator_allow = [v.strip() for v in settings.cli_env_allowlist.split(",") if v.strip()]
        env = _filter_env(env, [*(backend.allow_env or []), *operator_allow])

        is_interactive = session.metadata.get("is_interactive", False)
        process: asyncio.subprocess.Process | None = None
        try:
            # Argument array, never a shell. The child leads its own process
            # group on POSIX so a timeout can kill everything it spawned.
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdin=(
                    asyncio.subprocess.PIPE
                    if stdin_prompt or is_interactive
                    else asyncio.subprocess.DEVNULL
                ),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=workspace,
                env=env,
                start_new_session=os.name != "nt",
            )
            self._processes[session.session_id] = process

            # For interactive sessions, spawn _stream_output as a background
            # task so output is surfaced in real time while the process runs.
            stream_task: asyncio.Task | None = None  # type: ignore[type-arg]
            if is_interactive and process.stdout is not None:
                stream_task = asyncio.create_task(
                    self._stream_output(process, session.session_id)
                )
                # Mark session as awaiting input once streaming starts
                session.metadata["awaiting_input"] = True

            # The prompt goes on stdin only for stdin-transport backends; the
            # others already carry it in argv.
            stdin_data = prompt.encode("utf-8") if stdin_prompt else None

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
                        stderr_bytes = await _read_bounded(process.stderr)
                    # stdout was consumed by _stream_output
                    stdout_bytes = b""
                else:
                    stdout_bytes, stderr_bytes = await asyncio.wait_for(
                        _communicate_bounded(process, stdin_data),
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
                self._add_log(
                    session.session_id,
                    f"Timeout after {timeout}s, terminating process tree",
                )
                await _terminate_tree(process)

                return TaskResult(
                    task_id=task_id,
                    agent_id=session.agent_id,
                    success=False,
                    error=f"Execution timed out after {timeout} seconds",
                    artifacts=[_meta(None)],
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
            artifacts.append(_meta(return_code))

            success = return_code == 0
            error = None
            if not success:
                error = _redact_home(stderr_text.strip()[:4000]) or (
                    f"{backend.name} exited with code {return_code}"
                )

            return TaskResult(
                task_id=task_id,
                agent_id=session.agent_id,
                success=success,
                output=stdout_text,
                error=error,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                cost_cents=cost_cents,
                artifacts=artifacts,
                logs=[
                    f"Backend: {backend_id}",
                    f"Exit code: {return_code}",
                    f"Workspace: {_redact_home(workspace)}",
                ],
            )

        except asyncio.CancelledError:
            # The request was cancelled (client disconnect or Cancel): stop
            # this turn's own process tree and nothing else. Shielded so the
            # kill finishes even if the cancellation is delivered again.
            if process is not None and process.returncode is None:
                await asyncio.shield(asyncio.ensure_future(_terminate_tree(process)))
            raise
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
                error=_redact_home(f"Subprocess error: {type(e).__name__}: {e}"),
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
        """Read stdout from a process line-by-line, log it, and publish to WebSocket.

        Reads incrementally from the process stdout pipe until EOF. Each
        line is decoded with errors='replace', added to session logs, and
        broadcast to the agent's WebSocket channel for real-time UI streaming.

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

            # Publish to WebSocket channel for real-time streaming
            try:
                from nexus.api.routes.ws import manager as ws_manager
                await ws_manager.broadcast_to_channel(
                    f"agent:{session_id[:8]}",
                    {"type": "agent_output", "session_id": session_id, "line": line},
                )
            except Exception:
                pass  # WebSocket delivery is best-effort

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

        Only a temporary workspace this adapter made is deleted. An agent
        worktree is left alone: ending the agent session hands it to review
        (``release_session_worktree``); nothing here commits, merges or
        removes it.

        Args:
            session: The session being terminated.
        """
        process = self._processes.pop(session.session_id, None)
        if process and process.returncode is None:
            await _terminate_tree(process)

        self._conversation_history.pop(session.session_id, None)

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
        model: str = "",
        executable: str | None = None,
        work_mode: str | None = None,
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
            model: Model name, passed only through the backend's model flag.
            executable: Resolved executable path; defaults to the bare command.
            work_mode: A task attempt's mode, mapped to cataloged flags.

        Returns:
            List of command-line arguments ready for subprocess exec.
        """
        return backend.build_args(
            prompt, extra_args, model=model, executable=executable, work_mode=work_mode
        )

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

        The workspace can be an agent's worktree, which the agent may have
        filled with symlinks or junctions. No directory on the way to the file
        may be a link, the file is only ever created, never opened if it is
        already there (a dangling link included), and on Windows the directory
        is held open between that check and the write. A link means the file is
        skipped, not written through it.
        """
        if not backend.instruction_path:
            return None

        root = Path(workspace).resolve()
        instruction_path = root / backend.instruction_path
        try:
            # Create parent directories one at a time, refusing any that is a link
            parent = root
            for part in Path(backend.instruction_path).parent.parts:
                parent = parent / part
                if is_link(parent):
                    raise OSError(f"{parent} is a link")
                parent.mkdir(exist_ok=True)

            # Don't overwrite existing instruction files the user has set up
            if os.path.lexists(instruction_path):
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
            with pinned_directory(parent):
                if not _resolves_to_itself(parent):
                    raise OSError(f"{parent} is reached through a link")
                # O_EXCL fails on any existing name, a link included, so a
                # link planted since the check is never followed.
                fd = os.open(instruction_path, _CREATE_NEW, 0o644)
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    f.write(content)
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
        """Remove a temporary instruction file created for a CLI execution.

        The CLI ran in the workspace in between. If the file or any directory
        above it is now a link, nothing is removed, so cleanup cannot delete
        a file the link points to.
        """
        try:
            file_path = Path(path)
            parent = file_path.parent
            with pinned_directory(parent):
                if not _resolves_to_itself(parent) or is_link(file_path) or not file_path.is_file():
                    return
                file_path.unlink()
            # Remove parent dir if it's empty and was created by us
            if not any(parent.iterdir()):
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


async def _read_bounded(stream: Any, limit: int = MAX_OUTPUT_BYTES) -> bytes:
    """Read a stream to EOF, keeping at most ``limit`` bytes."""
    kept = bytearray()
    while True:
        chunk = await stream.read(65536)
        if not chunk:
            return bytes(kept)
        if len(kept) < limit:
            kept.extend(chunk[: limit - len(kept)])


async def _communicate_bounded(
    process: asyncio.subprocess.Process, stdin_data: bytes | None
) -> tuple[bytes, bytes]:
    """``communicate()`` with each output stream capped at MAX_OUTPUT_BYTES."""
    if stdin_data is not None and process.stdin is not None:
        try:
            process.stdin.write(stdin_data)
            await process.stdin.drain()
        except (BrokenPipeError, ConnectionResetError):
            pass
        process.stdin.close()
    stdout, stderr, _ = await asyncio.gather(
        _read_bounded(process.stdout), _read_bounded(process.stderr), process.wait()
    )
    return stdout, stderr


async def _terminate_tree(process: asyncio.subprocess.Process) -> None:
    """Stop a CLI and everything it spawned: SIGTERM, then SIGKILL.

    Windows uses ``taskkill /T /F``; POSIX signals the process group the child
    leads (it was started with ``start_new_session``).
    """
    pid = process.pid
    try:
        if isinstance(pid, int) and os.name == "nt":
            await asyncio.to_thread(
                subprocess.run,
                ["taskkill", "/T", "/F", "/PID", str(pid)],
                capture_output=True,
                timeout=10,
                check=False,
            )
        elif isinstance(pid, int):
            os.killpg(pid, signal.SIGTERM)
        else:
            process.send_signal(signal.SIGTERM)
        try:
            await asyncio.wait_for(process.wait(), timeout=5.0)
        except asyncio.TimeoutError:
            if isinstance(pid, int) and os.name != "nt":
                os.killpg(pid, signal.SIGKILL)
            else:
                process.kill()
            await process.wait()
    except (ProcessLookupError, PermissionError, OSError, subprocess.SubprocessError):
        pass
