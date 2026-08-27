"""CLI Backend Registry - auto-detects installed CLI backends.

Provides a registry of known CLI-based AI coding assistants, their metadata,
and runtime detection of which CLIs are actually available on the system PATH.
"""

import shutil
import subprocess
from dataclasses import dataclass, field
from typing import Any


@dataclass
class CLIBackendInfo:
    """Metadata for a CLI-based AI backend.

    Modeled after the AIBackend TypeScript interface in NVLabsOrg orchestrator.
    Each entry describes a CLI tool that can be spawned as a subprocess to
    execute AI-assisted coding tasks.
    """

    id: str
    name: str
    command: str
    instruction_path: str = ""
    stability: str = "experimental"
    supports_resume: bool = False
    supports_agent_type: bool = False
    supports_stdin: bool = True
    guard_type: str = "none"
    supports_native_worktree: bool = False
    supports_structured_output: bool = False
    delete_env: list[str] = field(default_factory=list)
    allow_env: list[str] = field(default_factory=list)

    def build_args(self, prompt: str, extra_args: list[str] | None = None) -> list[str]:
        """Build the CLI command arguments for this backend.

        Subclasses or instances can override this method to customize
        argument construction without modifying the adapter source.

        Args:
            prompt: The task prompt to pass.
            extra_args: Additional CLI arguments to append.

        Returns:
            List of command-line arguments ready for subprocess exec.
        """
        # Default implementation: command + extra_args + prompt as positional arg
        cmd = [self.command]
        if extra_args:
            cmd.extend(extra_args)
        cmd.append(prompt)
        return cmd


class _ClaudeBackendInfo(CLIBackendInfo):
    """Claude Code backend with custom argument construction."""

    def build_args(self, prompt: str, extra_args: list[str] | None = None) -> list[str]:
        """Claude Code: uses -p for non-interactive prompt execution."""
        cmd = [self.command]
        if prompt:
            cmd.extend(["-p", prompt])
        if extra_args:
            cmd.extend(extra_args)
        return cmd


class _CodexBackendInfo(CLIBackendInfo):
    """OpenAI Codex CLI backend with custom argument construction."""

    def build_args(self, prompt: str, extra_args: list[str] | None = None) -> list[str]:
        """Codex CLI: --quiet flag, prompt as positional argument."""
        cmd = [self.command, "--quiet"]
        if extra_args:
            cmd.extend(extra_args)
        cmd.append(prompt)
        return cmd


class _AiderBackendInfo(CLIBackendInfo):
    """Aider backend with custom argument construction."""

    def build_args(self, prompt: str, extra_args: list[str] | None = None) -> list[str]:
        """Aider: uses --message flag for non-interactive prompt."""
        cmd = [self.command, "--message", prompt, "--yes"]
        if extra_args:
            cmd.extend(extra_args)
        return cmd


class _KiroBackendInfo(CLIBackendInfo):
    """Kiro CLI backend with custom argument construction."""

    def build_args(self, prompt: str, extra_args: list[str] | None = None) -> list[str]:
        """Kiro CLI: prompt via stdin, minimal args."""
        cmd = [self.command]
        if extra_args:
            cmd.extend(extra_args)
        return cmd


class _HermesBackendInfo(CLIBackendInfo):
    """Hermes Agent CLI backend with custom argument construction.

    Uses `hermes --yolo --provider nous -m model -z "prompt"` for non-interactive
    single-shot execution. The --yolo flag enables autonomous mode.
    """

    def build_args(self, prompt: str, extra_args: list[str] | None = None) -> list[str]:
        """Hermes: uses -z for single-shot prompt, --yolo for auto-mode, --provider nous."""
        cmd = [self.command, "--yolo", "--provider", "nous"]
        # If no model specified in extra_args, use a working free model
        if extra_args and any(a == "-m" or a == "--model" for a in extra_args):
            cmd.extend(extra_args)
        else:
            cmd.extend(["-m", "poolside/laguna-s-2.1:free"])
            if extra_args:
                cmd.extend(extra_args)
        cmd.extend(["-z", prompt])
        return cmd


# Default backend definitions
_DEFAULT_BACKENDS: list[CLIBackendInfo] = [
    _ClaudeBackendInfo(
        id="claude",
        name="Claude Code",
        command="claude",
        instruction_path=".claude/CLAUDE.md",
        stability="stable",
        supports_resume=True,
        supports_agent_type=True,
        supports_stdin=True,
        guard_type="hooks",
        supports_native_worktree=True,
        supports_structured_output=True,
        allow_env=["ANTHROPIC_API_KEY"],
    ),
    _CodexBackendInfo(
        id="codex",
        name="OpenAI Codex CLI",
        command="codex",
        instruction_path="AGENTS.md",
        stability="beta",
        supports_resume=False,
        supports_agent_type=False,
        supports_stdin=True,
        guard_type="sandbox",
        allow_env=["OPENAI_API_KEY"],
    ),
    _KiroBackendInfo(
        id="kiro-cli",
        name="Kiro CLI",
        command="kiro",
        instruction_path=".kiro/steering/main.md",
        stability="beta",
        supports_resume=False,
        supports_agent_type=False,
        supports_stdin=True,
        guard_type="none",
    ),
    _AiderBackendInfo(
        id="aider",
        name="Aider",
        command="aider",
        instruction_path=".aider.conf.yml",
        stability="stable",
        supports_resume=False,
        supports_agent_type=False,
        supports_stdin=True,
        guard_type="none",
        allow_env=["OPENAI_API_KEY", "ANTHROPIC_API_KEY"],
    ),
    CLIBackendInfo(
        id="opencode",
        name="OpenCode",
        command="opencode",
        instruction_path="",
        stability="experimental",
        supports_resume=False,
        supports_agent_type=False,
        supports_stdin=True,
        guard_type="none",
    ),
    CLIBackendInfo(
        id="agy",
        name="Agy",
        command="agy",
        instruction_path="",
        stability="experimental",
        supports_resume=False,
        supports_agent_type=False,
        supports_stdin=True,
        guard_type="none",
    ),
    CLIBackendInfo(
        id="cursor",
        name="Cursor",
        command="cursor",
        instruction_path=".cursor/rules/instructions.md",
        stability="beta",
        supports_resume=False,
        supports_agent_type=False,
        supports_stdin=True,
        guard_type="none",
    ),
    _HermesBackendInfo(
        id="hermes",
        name="Hermes Agent (Nous Research)",
        command="hermes",
        instruction_path="",
        stability="stable",
        supports_resume=True,
        supports_agent_type=True,
        supports_stdin=True,
        guard_type="none",
        supports_native_worktree=True,
        supports_structured_output=True,
    ),
]


class CLIRegistry:
    """Registry that manages and auto-detects CLI-based AI backends.

    Maintains a catalog of known CLI backends and can probe the system
    to determine which ones are actually installed and available.
    """

    def __init__(self, auto_detect: bool = True) -> None:
        """Initialize the CLI registry.

        Args:
            auto_detect: If True, run detection on initialization.
        """
        self._backends: dict[str, CLIBackendInfo] = {}
        self._available: dict[str, str] = {}  # id -> resolved path

        # Register all default backends
        for backend in _DEFAULT_BACKENDS:
            self._backends[backend.id] = backend

        if auto_detect:
            self.detect_available()

    def register_backend(self, backend: CLIBackendInfo) -> None:
        """Register a custom CLI backend.

        Args:
            backend: The backend info to register.
        """
        self._backends[backend.id] = backend

    def detect_available(self) -> dict[str, str]:
        """Detect which registered backends are installed on the system.

        Uses shutil.which() to check if each backend's command is on PATH.

        Returns:
            Dictionary mapping backend id to resolved command path.
        """
        self._available = {}
        for backend_id, backend in self._backends.items():
            path = shutil.which(backend.command)
            if path:
                self._available[backend_id] = path
        return dict(self._available)

    def get_available(self) -> list[CLIBackendInfo]:
        """Get all backends that are currently available on the system.

        Returns:
            List of CLIBackendInfo for installed backends.
        """
        return [
            self._backends[bid]
            for bid in self._available
            if bid in self._backends
        ]

    def get_all(self) -> list[CLIBackendInfo]:
        """Get all registered backends regardless of availability.

        Returns:
            List of all registered CLIBackendInfo entries.
        """
        return list(self._backends.values())

    def get_backend(self, backend_id: str) -> CLIBackendInfo | None:
        """Get a specific backend by its identifier.

        Args:
            backend_id: The backend identifier (e.g., 'claude', 'codex').

        Returns:
            The CLIBackendInfo if found, otherwise None.
        """
        return self._backends.get(backend_id)

    def is_available(self, backend_id: str) -> bool:
        """Check if a specific backend is available on the system.

        Args:
            backend_id: The backend identifier to check.

        Returns:
            True if the backend is installed and on PATH.
        """
        return backend_id in self._available

    def get_path(self, backend_id: str) -> str | None:
        """Get the resolved filesystem path for a backend command.

        Args:
            backend_id: The backend identifier.

        Returns:
            The resolved path, or None if not available.
        """
        return self._available.get(backend_id)

    def probe_version(self, backend_id: str) -> str | None:
        """Probe the version of an installed backend via subprocess.

        Attempts to run '<command> --version' and capture the output.

        Args:
            backend_id: The backend identifier.

        Returns:
            Version string if successful, None otherwise.
        """
        if backend_id not in self._available:
            return None

        backend = self._backends.get(backend_id)
        if not backend:
            return None

        try:
            result = subprocess.run(
                [backend.command, "--version"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode == 0 and result.stdout.strip():
                return result.stdout.strip()
            # Some tools output version on stderr
            if result.stderr.strip():
                return result.stderr.strip()
        except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
            pass

        return None

    def to_dict(self) -> dict[str, Any]:
        """Serialize registry state to a dictionary.

        Returns:
            Dictionary with all backends and their availability status.
        """
        return {
            "backends": {
                bid: {
                    "id": b.id,
                    "name": b.name,
                    "command": b.command,
                    "instruction_path": b.instruction_path,
                    "stability": b.stability,
                    "supports_resume": b.supports_resume,
                    "supports_agent_type": b.supports_agent_type,
                    "supports_stdin": b.supports_stdin,
                    "available": bid in self._available,
                    "path": self._available.get(bid),
                }
                for bid, b in self._backends.items()
            },
            "available_count": len(self._available),
            "total_count": len(self._backends),
        }
