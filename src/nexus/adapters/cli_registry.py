"""CLI Backend Registry — the canonical catalog of CLI-based AI employees.

This module is the single source of truth for CLI backends: provider presets,
the provider API and the hiring UI all serialize this catalog instead of
keeping their own lists.

Every invocation contract below was checked against the installed binary's
``--help`` or the vendor's official documentation. A backend whose
non-interactive contract could not be verified is kept visible with
``execution_supported=False`` so it can never be hired as a working employee.

Nothing here ever accepts an executable path from a caller: commands resolve
only from ``command_candidates`` via PATH.
"""

import os
import shutil
import subprocess
import time
from dataclasses import dataclass, field
from typing import Any

# How long PATH detection and version probes are reused before re-probing.
DETECTION_TTL_SECONDS = 30.0
VERSION_PROBE_TIMEOUT_SECONDS = 5.0


@dataclass(frozen=True)
class CLIBackendInfo:
    """Immutable specification of one CLI backend.

    ``command`` is kept for backward compatibility; it defaults to the first
    entry of ``command_candidates`` (and vice versa).
    """

    id: str
    name: str
    command: str = ""
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
    aliases: tuple[str, ...] = ()
    command_candidates: tuple[str, ...] = ()
    execution_supported: bool = True
    supports_model: bool = False
    model_flag: str = ""
    resume_flag: str = ""
    supports_interactive: bool = False
    # positional | flag | stdin
    prompt_transport: str = "positional"
    prompt_flag: str = ""
    safe_non_interactive_args: tuple[str, ...] = ()
    # Cataloged permission flags per task-attempt work mode ("write" or
    # "read_only"), as ((mode, args), ...) so the dataclass stays hashable.
    # A backend without an entry cannot run that mode.
    work_args: tuple[tuple[str, tuple[str, ...]], ...] = ()
    # Execution-scoped MCP: the flag that loads one run's MCP config file, and
    # the cataloged args that confine the run to that server's tools. Empty:
    # the CLI has no per-run MCP config, so a manager on it chats without its
    # manager tools (see nexus.tools.manager_bridge).
    mcp_config_flag: str = ""
    mcp_bridge_args: tuple[str, ...] = ()
    # ACP alternative: argv that starts the CLI's ACP server, which takes MCP
    # servers per session in memory (see nexus.adapters.hermes_acp).
    acp_args: tuple[str, ...] = ()
    version_args: tuple[str, ...] = ("--version",)
    # stdout | stderr | either
    version_stream: str = "either"
    install_command: str = ""
    docs_url: str = ""
    default_models: tuple[str, ...] = ()
    recommended_model: str = ""
    notes: str = ""

    def __post_init__(self) -> None:
        if not self.command_candidates and self.command:
            object.__setattr__(self, "command_candidates", (self.command,))
        if not self.command and self.command_candidates:
            object.__setattr__(self, "command", self.command_candidates[0])

    @property
    def allowed_environment_variables(self) -> list[str]:
        return list(self.allow_env)

    @property
    def removed_environment_variables(self) -> list[str]:
        return list(self.delete_env)

    def build_args(
        self,
        prompt: str,
        extra_args: list[str] | None = None,
        model: str = "",
        executable: str | None = None,
        work_mode: str | None = None,
    ) -> list[str]:
        """Build the argv for one non-interactive run.

        Order: executable, cataloged safe args, cataloged work-mode args,
        model flag, extra args, prompt.
        With ``prompt_transport == "stdin"`` the prompt is not in argv; the
        caller must write it to the process's stdin.
        """
        cmd = [executable or self.command, *self.safe_non_interactive_args]
        if work_mode is not None:
            cmd.extend(self.work_mode_args(work_mode))
        if model and self.supports_model and self.model_flag:
            cmd.extend([self.model_flag, model])
        if extra_args:
            cmd.extend(extra_args)
        if self.prompt_transport == "stdin":
            return cmd
        # A prompt starting with "-" would be parsed as an option.
        safe_prompt = f" {prompt}" if prompt.startswith("-") else prompt
        if self.prompt_transport == "flag":
            cmd.extend([self.prompt_flag, safe_prompt])
        else:
            cmd.append(safe_prompt)
        return cmd

    def work_mode_args(self, work_mode: str) -> tuple[str, ...]:
        """This backend's cataloged flags for a work mode.

        Raises:
            ValueError: If the backend has no flags for that mode, so a task
                attempt never runs with the CLI's default permissions.
        """
        args = dict(self.work_args).get(work_mode)
        if args is None:
            raise ValueError(f"{self.id} does not support work mode {work_mode!r}")
        return args


_DEFAULT_BACKENDS: list[CLIBackendInfo] = [
    CLIBackendInfo(
        id="claude",
        name="Claude Code",
        command_candidates=("claude",),
        aliases=("claude-code", "claude_code", "claude-cli", "claude_cli"),
        instruction_path=".claude/CLAUDE.md",
        stability="stable",
        # ``-p/--print`` is a boolean; the prompt is positional.
        safe_non_interactive_args=("-p",),
        # Write: edits allowed in the worktree cwd, plus only pytest via Bash.
        # The "=" form keeps the variadic --allowedTools off the prompt.
        work_args=(
            (
                "write",
                (
                    "--permission-mode",
                    "acceptEdits",
                    "--allowedTools=Bash(python -m pytest:*),Bash(python3 -m pytest:*),"
                    "Bash(pytest:*)",
                ),
            ),
            ("read_only", ("--permission-mode", "plan")),
        ),
        # --mcp-config is variadic, so a flag must follow its file. Verified on
        # 2.1.283: without --allowedTools a -p run denies MCP tools; with
        # "mcp__<server>__*" it may call that server's tools and nothing more.
        mcp_config_flag="--mcp-config",
        mcp_bridge_args=("--strict-mcp-config", "--allowedTools=mcp__nexus__*"),
        supports_model=True,
        model_flag="--model",
        supports_resume=True,
        resume_flag="--resume",
        supports_interactive=True,
        supports_agent_type=True,
        guard_type="hooks",
        supports_native_worktree=True,
        supports_structured_output=True,
        allow_env=["ANTHROPIC_API_KEY"],
        install_command="npm install -g @anthropic-ai/claude-code",
        docs_url="https://docs.anthropic.com/en/docs/claude-code/cli-reference",
        default_models=("sonnet", "opus", "haiku"),
        recommended_model="sonnet",
    ),
    CLIBackendInfo(
        id="codex",
        name="OpenAI Codex CLI",
        command_candidates=("codex",),
        instruction_path="AGENTS.md",
        stability="beta",
        # ``codex exec`` reads the prompt from stdin when none is given. Using
        # stdin also avoids cmd.exe re-parsing the prompt through codex.cmd.
        # --skip-git-repo-check: temp workspaces are not git repositories.
        prompt_transport="stdin",
        safe_non_interactive_args=("exec", "--skip-git-repo-check"),
        supports_model=True,
        model_flag="-m",
        guard_type="sandbox",
        allow_env=["OPENAI_API_KEY"],
        install_command="npm install -g @openai/codex",
        docs_url="https://developers.openai.com/codex/cli",
        notes="Runs `codex exec` in its default read-only sandbox.",
    ),
    CLIBackendInfo(
        id="gemini",
        name="Gemini CLI",
        command_candidates=("gemini",),
        instruction_path="GEMINI.md",
        stability="beta",
        prompt_transport="flag",
        prompt_flag="-p",
        supports_model=True,
        model_flag="-m",
        supports_resume=True,
        resume_flag="--resume",
        allow_env=["GEMINI_API_KEY", "GOOGLE_API_KEY"],
        install_command="npm install -g @google/gemini-cli",
        docs_url="https://github.com/google-gemini/gemini-cli",
    ),
    CLIBackendInfo(
        id="agy",
        name="Antigravity / Agy",
        command_candidates=("agy",),
        aliases=("antigravity",),
        stability="experimental",
        # ``-p`` takes the prompt as its value.
        prompt_transport="flag",
        prompt_flag="-p",
        work_args=(("write", ("--mode", "accept-edits")), ("read_only", ("--mode", "plan"))),
        supports_model=True,
        model_flag="--model",
        supports_resume=True,
        resume_flag="--conversation",
        # Agy 1.2.12 has only persistent, global `agy mcp add`; no per-run
        # MCP config, so no manager bridge.
        notes="No instruction file is written; instructions are sent inline.",
    ),
    CLIBackendInfo(
        id="kiro-cli",
        name="Kiro CLI",
        command_candidates=("kiro-cli",),
        aliases=("kiro",),
        instruction_path=".kiro/steering/main.md",
        stability="beta",
        safe_non_interactive_args=("chat", "--no-interactive"),
        supports_resume=True,
        resume_flag="--resume",
        docs_url="https://kiro.dev/docs/cli/",
        notes="Kiro CLI has no per-run model flag; the model comes from its own settings.",
    ),
    CLIBackendInfo(
        id="freebuff",
        name="FreeBuff",
        command_candidates=("freebuff",),
        execution_supported=False,
        notes="Catalog only: `freebuff --help` (0.1.0) shows no non-interactive prompt mode.",
    ),
    CLIBackendInfo(
        id="qwen",
        name="Qwen Code",
        command_candidates=("qwen",),
        instruction_path="QWEN.md",
        stability="experimental",
        prompt_transport="flag",
        prompt_flag="-p",
        supports_model=True,
        model_flag="-m",
        install_command="npm install -g @qwen-code/qwen-code",
        docs_url="https://github.com/QwenLM/qwen-code",
    ),
    CLIBackendInfo(
        id="kimi",
        name="Kimi Code",
        command_candidates=("kimi",),
        execution_supported=False,
        install_command="npm install -g @moonshot-ai/kimi-code",
        notes="Catalog only: non-interactive invocation not verified.",
    ),
    CLIBackendInfo(
        id="opencode",
        name="OpenCode",
        command_candidates=("opencode",),
        instruction_path="AGENTS.md",
        stability="experimental",
        safe_non_interactive_args=("run",),
        supports_model=True,
        model_flag="-m",
        supports_resume=True,
        resume_flag="--session",
        install_command="npm install -g opencode-ai",
        docs_url="https://opencode.ai/docs/cli/",
        notes="Models use the provider/model form.",
    ),
    CLIBackendInfo(
        id="aider",
        name="Aider",
        command_candidates=("aider",),
        stability="stable",
        prompt_transport="flag",
        prompt_flag="--message",
        supports_model=True,
        model_flag="--model",
        allow_env=["OPENAI_API_KEY", "ANTHROPIC_API_KEY"],
        install_command="python -m pip install aider-install && aider-install",
        docs_url="https://aider.chat/docs/scripting.html",
        notes="--yes is an autonomy flag and is never added by default.",
    ),
    CLIBackendInfo(
        id="copilot",
        name="GitHub Copilot CLI",
        command_candidates=("copilot",),
        stability="experimental",
        prompt_transport="flag",
        prompt_flag="-p",
        supports_model=True,
        model_flag="--model",
        supports_resume=True,
        resume_flag="--resume",
        install_command="npm install -g @github/copilot",
        docs_url="https://docs.github.com/en/copilot/how-tos/use-copilot-agents/use-copilot-cli",
        notes="Tools stay gated: --allow-all-tools is never added by default.",
    ),
    CLIBackendInfo(
        id="goose",
        name="Goose",
        command_candidates=("goose",),
        instruction_path=".goosehints",
        stability="experimental",
        safe_non_interactive_args=("run", "--no-session"),
        prompt_transport="flag",
        prompt_flag="-t",
        supports_model=True,
        model_flag="--model",
        docs_url="https://block.github.io/goose/docs/guides/goose-cli-commands",
    ),
    CLIBackendInfo(
        id="crush",
        name="Crush",
        command_candidates=("crush",),
        execution_supported=False,
        docs_url="https://github.com/charmbracelet/crush",
        notes="Catalog only: no documented non-interactive run mode verified.",
    ),
    CLIBackendInfo(
        id="pi",
        name="Pi Coding Agent",
        command_candidates=("pi",),
        execution_supported=False,
        notes="Catalog only: invocation contract not verified.",
    ),
    CLIBackendInfo(
        id="hermes",
        name="Hermes Agent CLI",
        command_candidates=("hermes",),
        aliases=("hermes-cli",),
        stability="beta",
        # ``-z/--oneshot`` prints only the final response.
        prompt_transport="flag",
        prompt_flag="-z",
        supports_model=True,
        model_flag="-m",
        supports_resume=True,
        resume_flag="--resume",
        acp_args=("acp",),
        version_stream="stdout",
        docs_url="https://github.com/NousResearch/hermes-agent",
        notes=(
            "Separate from the Hermes Ollama/API adapter. --yolo is never "
            "added by default; the provider comes from Hermes' own config."
        ),
    ),
    CLIBackendInfo(
        id="amazon-q",
        name="Amazon Q Developer CLI",
        command_candidates=("q",),
        execution_supported=False,
        docs_url="https://docs.aws.amazon.com/amazonq/latest/qdeveloper-ug/command-line.html",
        notes="Catalog only: non-interactive invocation not verified.",
    ),
    CLIBackendInfo(
        id="cursor-agent",
        name="Cursor Agent",
        # Only the dedicated headless binary; the generic ``agent`` name and
        # the ``cursor`` editor launcher are deliberately not candidates.
        command_candidates=("cursor-agent",),
        aliases=("cursor",),
        stability="experimental",
        # ``-p/--print`` is a boolean; the prompt is positional.
        safe_non_interactive_args=("-p",),
        supports_model=True,
        model_flag="--model",
        install_command="curl https://cursor.com/install -fsS | bash",
        docs_url="https://cursor.com/docs/cli/headless",
        notes="--force is never added by default.",
    ),
    CLIBackendInfo(
        id="grok",
        name="Grok CLI",
        command_candidates=("grok",),
        execution_supported=False,
        notes="Catalog only: invocation contract not verified.",
    ),
]


class CLIRegistry:
    """Catalog plus PATH detection for CLI backends.

    Detection results are cached for ``DETECTION_TTL_SECONDS`` so one UI
    request never spawns a version probe per backend more than once.
    """

    def __init__(self, auto_detect: bool = True) -> None:
        self._backends: dict[str, CLIBackendInfo] = {}
        self._aliases: dict[str, str] = {}
        self._available: dict[str, str] = {}  # id -> resolved path
        self._versions: dict[str, tuple[float, str | None]] = {}
        self._detected_at: float | None = None

        for backend in _DEFAULT_BACKENDS:
            self.register_backend(backend)

        if auto_detect:
            self.detect_available()

    def register_backend(self, backend: CLIBackendInfo) -> None:
        self._backends[backend.id] = backend
        for alias in backend.aliases:
            self._aliases[alias.lower()] = backend.id

    def resolve_backend_id(self, name: str | None) -> str | None:
        """Canonical backend ID for an ID or alias, or None when unknown."""
        if not name:
            return None
        key = name.strip().lower()
        if key in self._backends:
            return key
        return self._aliases.get(key)

    def detect_available(self) -> dict[str, str]:
        """Resolve each backend's command candidates on PATH, in order.

        ``shutil.which`` honours PATHEXT, so Windows ``.exe``/``.cmd``/``.bat``
        shims resolve without a shell.
        """
        self._available = {}
        for backend_id, backend in self._backends.items():
            for candidate in backend.command_candidates:
                path = shutil.which(candidate)
                if path:
                    self._available[backend_id] = path
                    break
        self._detected_at = time.monotonic()
        return dict(self._available)

    def refresh(self, force: bool = False) -> None:
        """Re-detect when the cached detection is older than the TTL."""
        if (
            force
            or self._detected_at is None
            or time.monotonic() - self._detected_at > DETECTION_TTL_SECONDS
        ):
            self._versions.clear()
            self.detect_available()

    def get_available(self) -> list[CLIBackendInfo]:
        return [self._backends[bid] for bid in self._available if bid in self._backends]

    def get_all(self) -> list[CLIBackendInfo]:
        return list(self._backends.values())

    def get_backend(self, backend_id: str | None) -> CLIBackendInfo | None:
        """Backend by canonical ID or alias; None when unknown."""
        canonical = self.resolve_backend_id(backend_id)
        return self._backends.get(canonical) if canonical else None

    def is_available(self, backend_id: str) -> bool:
        return self.resolve_backend_id(backend_id) in self._available

    def get_path(self, backend_id: str) -> str | None:
        canonical = self.resolve_backend_id(backend_id)
        return self._available.get(canonical) if canonical else None

    def probe_version(
        self, backend_id: str, timeout: float = VERSION_PROBE_TIMEOUT_SECONDS
    ) -> str | None:
        """Run the cataloged version command with a strict timeout.

        Never raises; returns the first line of output (home directory
        redacted) or None. Results are cached with the detection TTL.
        """
        canonical = self.resolve_backend_id(backend_id)
        path = self._available.get(canonical) if canonical else None
        if not path:
            return None
        cached = self._versions.get(canonical)
        if cached and time.monotonic() - cached[0] <= DETECTION_TTL_SECONDS:
            return cached[1]

        backend = self._backends[canonical]
        version: str | None = None
        try:
            result = subprocess.run(
                [path, *backend.version_args],
                capture_output=True,
                text=True,
                encoding="utf-8",  # CLIs emit UTF-8; the Windows locale codepage mangles it
                errors="replace",
                timeout=timeout,
                stdin=subprocess.DEVNULL,
            )
            streams = {
                "stdout": [result.stdout],
                "stderr": [result.stderr],
                "either": [result.stdout if result.returncode == 0 else "", result.stderr],
            }[backend.version_stream]
            for text in streams:
                line = next((ln.strip() for ln in (text or "").splitlines() if ln.strip()), "")
                if line:
                    version = _redact_home(line)[:200]
                    break
        except (subprocess.TimeoutExpired, OSError, ValueError):
            version = None
        self._versions[canonical] = (time.monotonic(), version)
        return version

    def describe(self, backend_id: str, probe_version: bool = True) -> dict[str, Any] | None:
        """Public, secret-free description of one backend for the API."""
        backend = self.get_backend(backend_id)
        if backend is None:
            return None
        path = self._available.get(backend.id)
        installed = path is not None
        return {
            "id": backend.id,
            "label": backend.name,
            "aliases": list(backend.aliases),
            "adapter_type": "cli",
            "installed": installed,
            "resolved_command": _redact_home(path) if path else None,
            "version": self.probe_version(backend.id) if installed and probe_version else None,
            "execution_supported": backend.execution_supported,
            # Authentication cannot be checked without running the CLI.
            "configured": None if installed else False,
            "stability": backend.stability,
            "supports_model": backend.supports_model,
            "supports_resume": backend.supports_resume,
            "supports_interactive": backend.supports_interactive,
            "supports_worktree": backend.supports_native_worktree,
            "instruction_path": backend.instruction_path,
            "recommended_model": backend.recommended_model,
            "models": list(backend.default_models),
            "install_command": backend.install_command,
            "docs_url": backend.docs_url,
            "notes": backend.notes,
        }

    def to_dict(self) -> dict[str, Any]:
        """Serialize registry state (legacy shape used by /adapters)."""
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
                    "execution_supported": b.execution_supported,
                    "available": bid in self._available,
                    "path": self._available.get(bid),
                }
                for bid, b in self._backends.items()
            },
            "available_count": len(self._available),
            "total_count": len(self._backends),
        }


def _redact_home(text: str) -> str:
    home = os.path.expanduser("~")
    return text.replace(home, "~") if home and home != "~" else text


_shared_registry: CLIRegistry | None = None


def get_cli_registry() -> CLIRegistry:
    """Process-wide registry whose detection is refreshed on a short TTL."""
    global _shared_registry
    if _shared_registry is None:
        _shared_registry = CLIRegistry(auto_detect=False)
    _shared_registry.refresh()
    return _shared_registry


# ---------------------------------------------------------------------------
# Employee configuration validation — shared by every hiring path.
# ---------------------------------------------------------------------------

_CLI_CONFIG_KEYS = frozenset(
    {"backend", "interactive", "use_worktree", "autonomy_mode", "extra_args"}
)
_MODEL_CHARS = frozenset(
    "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._:/@+-"
)


class CLIConfigError(ValueError):
    """A CLI employee configuration was refused; ``code`` is stable for clients."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def validate_employee_cli_config(
    adapter_type: str,
    adapter_config: dict[str, Any] | None,
    model: str | None,
    *,
    allow_unavailable: bool = False,
    registry: CLIRegistry | None = None,
) -> tuple[dict[str, Any], bool]:
    """Validate and normalize a CLI employee's configuration.

    Returns ``(canonical_adapter_config, ready)``. ``ready`` is False only when
    ``allow_unavailable`` let an uninstalled / catalog-only backend through; the
    caller must then store the employee as ``configuration_required``.

    Raises CLIConfigError for anything that must not be stored.
    """
    if adapter_type != "cli":
        raise CLIConfigError("CLI_CONFIG_INVALID", "adapter_type must be 'cli'")
    registry = registry or get_cli_registry()
    config = dict(adapter_config or {})

    unexpected = sorted(set(config) - _CLI_CONFIG_KEYS)
    if unexpected:
        # Covers executable paths, commands and credentials alike.
        raise CLIConfigError(
            "CLI_CONFIG_INVALID",
            f"Unsupported adapter_config keys: {', '.join(unexpected)}. "
            "Executables resolve server-side; credentials are never stored.",
        )

    raw_backend = config.get("backend")
    if not isinstance(raw_backend, str) or not raw_backend.strip():
        raise CLIConfigError("CLI_BACKEND_REQUIRED", "adapter_config.backend is required")
    backend = registry.get_backend(raw_backend)
    if backend is None:
        raise CLIConfigError("CLI_BACKEND_UNKNOWN", f"Unknown CLI backend '{raw_backend[:80]}'")

    extra_args = config.get("extra_args") or []
    from nexus.tools.access import check_cli_args  # avoid import cycle

    refusal = check_cli_args(extra_args)
    if refusal:
        raise CLIConfigError("CLI_ARGS_FORBIDDEN", refusal)
    if len(extra_args) > 20:
        raise CLIConfigError("CLI_ARGS_FORBIDDEN", "At most 20 extra_args are allowed")

    autonomy = config.get("autonomy_mode", "safe")
    if autonomy != "safe":
        # ponytail: no autonomous CLI mode is wired to the approval layer yet.
        raise CLIConfigError(
            "CLI_AUTONOMY_REQUIRES_APPROVAL",
            f"autonomy_mode '{autonomy}' requires policy approval; only 'safe' is allowed",
        )
    if config.get("use_worktree"):
        raise CLIConfigError(
            "CLI_CONFIG_INVALID", "use_worktree is managed by WorktreeService, not agent config"
        )
    interactive = bool(config.get("interactive", False))
    if interactive and not backend.supports_interactive:
        raise CLIConfigError(
            "CLI_CONFIG_INVALID", f"{backend.name} does not support interactive mode"
        )

    model = (model or "").strip()
    if model:
        if not backend.supports_model:
            raise CLIConfigError(
                "CLI_MODEL_UNSUPPORTED", f"{backend.name} does not accept a model flag"
            )
        if len(model) > 255 or model.startswith("-") or not set(model) <= _MODEL_CHARS:
            raise CLIConfigError("CLI_MODEL_INVALID", "Model contains unsupported characters")

    ready = backend.execution_supported and registry.is_available(backend.id)
    if not ready and not allow_unavailable:
        if not backend.execution_supported:
            raise CLIConfigError(
                "CLI_BACKEND_NOT_EXECUTABLE",
                f"{backend.name} is catalog-only: its non-interactive invocation is not verified",
            )
        raise CLIConfigError(
            "CLI_BACKEND_UNAVAILABLE", f"{backend.name} is not installed on this server"
        )

    return {
        "backend": backend.id,
        "interactive": interactive,
        "use_worktree": False,
        "autonomy_mode": "safe",
        "extra_args": list(extra_args),
    }, ready
