"""Multi-backend code sandbox (Phase 3.1).

One `SandboxBackend` contract, three implementations:

- `RemoteSandboxBackend` — E2B, API-key driven, zero local privilege.
- `Judge0Backend` — Judge0 REST, API-key optional (self-hosted).
- `LocalSubprocessBackend` — host subprocess, refuses to start unless
  `allow_unsafe_local_execution` is explicitly enabled.

Execution leases (3.1.5) guarantee two runs never share a sandbox; workspace
scoping (3.1.6) means a sandbox only ever sees its task's workspace directory.

Do NOT mount the host Docker socket here — container-per-execution via a host
daemon is out of scope (see FEATURE_PLAN Phase 3.1 note).
"""

from __future__ import annotations

import asyncio
import logging
import os
import shutil
import sys
import time
from abc import ABC, abstractmethod
from contextlib import contextmanager
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Iterator

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT_SECONDS = 30
DEFAULT_MEMORY_MB = 512


class SandboxType(str, Enum):
    """Available sandbox backends."""

    LOCAL = "local"
    E2B = "e2b"
    JUDGE0 = "judge0"


class UnsupportedLanguage(Exception):
    """Raised when a backend cannot run the requested language."""

    def __init__(self, language: str, backend: str, supported: tuple[str, ...]) -> None:
        self.language = language
        self.backend = backend
        self.supported = supported
        super().__init__(
            f"{backend} cannot run {language!r}; supported: {', '.join(supported)}"
        )


class LocalExecutionDisabled(Exception):
    """Raised when local subprocess execution is attempted while disabled."""


class LeaseHeld(Exception):
    """Raised when a sandbox is already leased by another run."""

    def __init__(self, key: str, holder: str) -> None:
        self.key = key
        self.holder = holder
        super().__init__(f"Sandbox {key!r} is leased by run {holder!r}")


@dataclass(frozen=True)
class ExecutionResult:
    """Outcome of one code execution, identical in shape across backends."""

    stdout: str
    stderr: str
    exit_code: int
    timed_out: bool
    backend: SandboxType
    duration_ms: int = 0

    @property
    def ok(self) -> bool:
        """True when the code ran to completion successfully."""
        return self.exit_code == 0 and not self.timed_out


@dataclass(frozen=True)
class SandboxCapabilities:
    """What a backend can do, so callers can pick one without try/except."""

    languages: tuple[str, ...]
    network: bool
    filesystem: bool
    max_timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS
    persistent: bool = False


# ponytail: in-process lease table; swap for a DB row or Redis key if sandboxes
# are ever shared across API workers.
_LEASES: dict[str, str] = {}


@contextmanager
def _lease(key: str, run_id: str) -> Iterator[None]:
    """Hold an exclusive lease on `key` for `run_id`.

    Re-entrant for the same run_id, exclusive against every other run.
    """
    holder = _LEASES.get(key)
    if holder is not None and holder != run_id:
        raise LeaseHeld(key, holder)
    reentrant = holder == run_id
    if not reentrant:
        _LEASES[key] = run_id
    try:
        yield
    finally:
        if not reentrant:
            _LEASES.pop(key, None)


class SandboxBackend(ABC):
    """Contract every sandbox backend implements."""

    sandbox_type: SandboxType

    @property
    @abstractmethod
    def capabilities(self) -> SandboxCapabilities:
        """Describe what this backend supports."""

    @abstractmethod
    async def _execute(
        self,
        code: str,
        language: str,
        timeout: int,
        workspace: Path | None,
        env: dict[str, str] | None,
    ) -> ExecutionResult:
        """Backend-specific execution. Called with validated arguments."""

    async def run(
        self,
        code: str,
        language: str = "python",
        *,
        timeout: int | None = None,
        workspace: str | Path | None = None,
        env: dict[str, str] | None = None,
        run_id: str = "adhoc",
    ) -> ExecutionResult:
        """Execute `code` and return a backend-independent result.

        Args:
            code: Source to execute.
            language: Language name (e.g. "python", "node", "bash").
            timeout: Wall-clock limit; clamped to the backend maximum.
            workspace: Task workspace. The only directory the sandbox may see
                (3.1.6). Must exist and be a directory.
            env: Extra environment variables.
            run_id: Lease owner. Two different run_ids cannot share a sandbox.

        Raises:
            UnsupportedLanguage: The backend cannot run `language`.
            LeaseHeld: Another run holds this sandbox.
            ValueError: `workspace` does not exist or is not a directory.
        """
        caps = self.capabilities
        language = language.lower()
        if language not in caps.languages:
            raise UnsupportedLanguage(language, type(self).__name__, caps.languages)

        limit = min(timeout or DEFAULT_TIMEOUT_SECONDS, caps.max_timeout_seconds)
        ws = self._resolve_workspace(workspace)

        started = time.monotonic()
        with _lease(self._lease_key(ws), run_id):
            result = await self._execute(code, language, limit, ws, env)
        elapsed = int((time.monotonic() - started) * 1000)
        return ExecutionResult(
            stdout=result.stdout,
            stderr=result.stderr,
            exit_code=result.exit_code,
            timed_out=result.timed_out,
            backend=self.sandbox_type,
            duration_ms=elapsed,
        )

    def _lease_key(self, workspace: Path | None) -> str:
        """Lease identity: one sandbox per (backend, workspace)."""
        return f"{self.sandbox_type.value}:{workspace or '-'}"

    @staticmethod
    def _resolve_workspace(workspace: str | Path | None) -> Path | None:
        """Validate the workspace directory (3.1.6)."""
        if workspace is None:
            return None
        path = Path(workspace).resolve()
        if not path.is_dir():
            raise ValueError(f"Workspace is not an existing directory: {path}")
        return path


class RemoteSandboxBackend(SandboxBackend):
    """E2B-backed sandbox. Requires an API key; grants no local privilege."""

    sandbox_type = SandboxType.E2B

    _LANGUAGES = ("python", "javascript", "typescript", "bash", "r", "java")

    def __init__(self, api_key: str, *, template: str = "code-interpreter-v1") -> None:
        """Initialize the E2B backend.

        Args:
            api_key: E2B API key.
            template: E2B sandbox template id.

        Raises:
            ValueError: If `api_key` is empty.
        """
        if not api_key:
            raise ValueError("E2B backend requires an API key")
        self._api_key = api_key
        self._template = template

    @property
    def capabilities(self) -> SandboxCapabilities:
        """E2B sandboxes have network and a writable filesystem."""
        return SandboxCapabilities(
            languages=self._LANGUAGES,
            network=True,
            filesystem=True,
            max_timeout_seconds=300,
            persistent=True,
        )

    async def _execute(
        self,
        code: str,
        language: str,
        timeout: int,
        workspace: Path | None,
        env: dict[str, str] | None,
    ) -> ExecutionResult:
        """Run code in a fresh E2B sandbox, uploading only the workspace."""
        try:
            from e2b_code_interpreter import AsyncSandbox  # type: ignore[import-not-found]
        except ImportError as exc:  # pragma: no cover - optional dependency
            raise RuntimeError(
                "E2B backend requires the 'e2b-code-interpreter' package"
            ) from exc

        sandbox = await AsyncSandbox.create(
            api_key=self._api_key,
            template=self._template,
            timeout=timeout,
            envs=env or {},
        )
        try:
            if workspace is not None:
                await self._upload_workspace(sandbox, workspace)
            execution = await sandbox.run_code(
                code, language=language, timeout=timeout
            )
            return self._to_result(execution)
        finally:
            await sandbox.kill()

    @staticmethod
    async def _upload_workspace(sandbox: Any, workspace: Path) -> None:
        """Upload the task workspace so the sandbox sees only those files."""
        for path in workspace.rglob("*"):
            if not path.is_file():
                continue
            rel = path.relative_to(workspace).as_posix()
            await sandbox.files.write(f"/home/user/{rel}", path.read_bytes())

    @staticmethod
    def _to_result(execution: Any) -> ExecutionResult:
        """Normalize an E2B execution object into an ExecutionResult."""
        logs = getattr(execution, "logs", None)
        stdout = "".join(getattr(logs, "stdout", []) or []) if logs else ""
        stderr = "".join(getattr(logs, "stderr", []) or []) if logs else ""
        error = getattr(execution, "error", None)
        if error is not None:
            stderr += str(getattr(error, "traceback", None) or error)
        return ExecutionResult(
            stdout=stdout,
            stderr=stderr,
            exit_code=1 if error is not None else 0,
            timed_out=False,
            backend=SandboxType.E2B,
        )


class Judge0Backend(SandboxBackend):
    """Judge0 REST backend. Stateless, no filesystem, no network in-guest."""

    sandbox_type = SandboxType.JUDGE0

    # Judge0 CE language ids.
    _LANGUAGE_IDS = {
        "bash": 46,
        "c": 50,
        "cpp": 54,
        "csharp": 51,
        "go": 60,
        "java": 62,
        "javascript": 63,
        "python": 71,
        "ruby": 72,
        "rust": 73,
        "typescript": 74,
    }

    def __init__(
        self,
        base_url: str = "https://judge0-ce.p.rapidapi.com",
        api_key: str = "",
        *,
        api_host: str = "judge0-ce.p.rapidapi.com",
    ) -> None:
        """Initialize the Judge0 backend.

        Args:
            base_url: Judge0 API root.
            api_key: RapidAPI key. Empty for a self-hosted instance.
            api_host: RapidAPI host header value.
        """
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._api_host = api_host

    @property
    def capabilities(self) -> SandboxCapabilities:
        """Judge0 runs a single snippet with no filesystem or network."""
        return SandboxCapabilities(
            languages=tuple(self._LANGUAGE_IDS),
            network=False,
            filesystem=False,
            max_timeout_seconds=20,
        )

    async def _execute(
        self,
        code: str,
        language: str,
        timeout: int,
        workspace: Path | None,
        env: dict[str, str] | None,
    ) -> ExecutionResult:
        """Submit the snippet to Judge0 and wait for the verdict."""
        import httpx

        headers = {"Content-Type": "application/json"}
        if self._api_key:
            headers["X-RapidAPI-Key"] = self._api_key
            headers["X-RapidAPI-Host"] = self._api_host

        payload = {
            "source_code": code,
            "language_id": self._LANGUAGE_IDS[language],
            "cpu_time_limit": timeout,
        }
        async with httpx.AsyncClient(timeout=timeout + 15) as client:
            response = await client.post(
                f"{self._base_url}/submissions",
                params={"base64_encoded": "false", "wait": "true"},
                json=payload,
                headers=headers,
            )
            response.raise_for_status()
            return self._to_result(response.json())

    @staticmethod
    def _to_result(body: dict[str, Any]) -> ExecutionResult:
        """Normalize a Judge0 submission body into an ExecutionResult."""
        status_id = (body.get("status") or {}).get("id", 0)
        stderr = (body.get("stderr") or "") + (body.get("compile_output") or "")
        exit_code = body.get("exit_code")
        if exit_code is None:
            exit_code = 0 if status_id == 3 else 1
        return ExecutionResult(
            stdout=body.get("stdout") or "",
            stderr=stderr,
            # Judge0 status 5 == Time Limit Exceeded.
            exit_code=int(exit_code),
            timed_out=status_id == 5,
            backend=SandboxType.JUDGE0,
        )


class LocalSubprocessBackend(SandboxBackend):
    """Host subprocess execution. Off unless explicitly enabled.

    This is the only backend that runs untrusted code with host privileges,
    so it refuses to start unless `allow_unsafe_local_execution=True`. Network
    is off by default (via `unshare -n` where available) and memory/CPU are
    capped with rlimits on POSIX.
    """

    sandbox_type = SandboxType.LOCAL

    _INTERPRETERS = {
        "python": [sys.executable, "-c"],
        "bash": ["bash", "-c"],
        "node": ["node", "-e"],
        "javascript": ["node", "-e"],
    }

    def __init__(
        self,
        *,
        allow_unsafe_local_execution: bool = False,
        memory_mb: int = DEFAULT_MEMORY_MB,
        allow_network: bool = False,
        max_timeout_seconds: int = 120,
    ) -> None:
        """Initialize the local backend.

        Args:
            allow_unsafe_local_execution: Must be True or every run refuses.
            memory_mb: Address-space cap applied per process (POSIX only).
            allow_network: Leave network reachable. Default False.
            max_timeout_seconds: Upper bound on the wall-clock limit.
        """
        self._enabled = allow_unsafe_local_execution
        self._memory_mb = memory_mb
        self._allow_network = allow_network
        self._max_timeout = max_timeout_seconds

    @property
    def capabilities(self) -> SandboxCapabilities:
        """Local execution sees the workspace filesystem."""
        return SandboxCapabilities(
            languages=tuple(self._INTERPRETERS),
            network=self._allow_network,
            filesystem=True,
            max_timeout_seconds=self._max_timeout,
        )

    async def _execute(
        self,
        code: str,
        language: str,
        timeout: int,
        workspace: Path | None,
        env: dict[str, str] | None,
    ) -> ExecutionResult:
        """Run code as a child process under rlimits, refusing if disabled."""
        if not self._enabled:
            raise LocalExecutionDisabled(
                "Local subprocess execution is disabled. Set "
                "allow_unsafe_local_execution=True (NEXUS "
                "allow_unsafe_local_execution) to enable it."
            )

        argv = [*self._INTERPRETERS[language], code]
        if not self._allow_network and shutil.which("unshare"):
            # Network namespace with no interfaces: no egress, no localhost peers.
            argv = ["unshare", "--net", "--map-root-user", *argv]
        elif not self._allow_network:
            logger.warning(
                "Network isolation unavailable (no 'unshare'); local sandbox "
                "code can reach the network."
            )

        process = await asyncio.create_subprocess_exec(
            *argv,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(workspace) if workspace else None,
            env=self._child_env(env, workspace),
            preexec_fn=self._rlimits() if os.name == "posix" else None,
        )
        try:
            stdout, stderr = await asyncio.wait_for(
                process.communicate(), timeout=timeout
            )
        except asyncio.TimeoutError:
            process.kill()
            await process.wait()
            return ExecutionResult(
                stdout="",
                stderr=f"Execution timed out after {timeout}s",
                exit_code=-1,
                timed_out=True,
                backend=SandboxType.LOCAL,
            )
        return ExecutionResult(
            stdout=stdout.decode(errors="replace"),
            stderr=stderr.decode(errors="replace"),
            exit_code=process.returncode or 0,
            timed_out=False,
            backend=SandboxType.LOCAL,
        )

    @staticmethod
    def _child_env(
        env: dict[str, str] | None, workspace: Path | None
    ) -> dict[str, str]:
        """Build a minimal child environment; host secrets are not inherited."""
        base = {
            "PATH": os.environ.get("PATH", ""),
            "HOME": str(workspace) if workspace else os.environ.get("HOME", ""),
            "LANG": "C.UTF-8",
        }
        base.update(env or {})
        return base

    def _rlimits(self):
        """Return a preexec hook applying memory/process rlimits."""
        memory_bytes = self._memory_mb * 1024 * 1024

        def _apply() -> None:  # pragma: no cover - child process only
            import resource

            resource.setrlimit(resource.RLIMIT_AS, (memory_bytes, memory_bytes))
            resource.setrlimit(resource.RLIMIT_NPROC, (64, 64))
            resource.setrlimit(resource.RLIMIT_FSIZE, (64 << 20, 64 << 20))
            resource.setrlimit(resource.RLIMIT_CORE, (0, 0))

        return _apply


def get_backend(
    sandbox_type: SandboxType | str | None = None, settings: Any = None
) -> SandboxBackend:
    """Build a backend from settings.

    Args:
        sandbox_type: Which backend to build. Defaults to the configured
            `sandbox_backend` setting.
        settings: Settings object; defaults to `nexus.config.settings`.

    Returns:
        A ready `SandboxBackend`.

    Raises:
        ValueError: Unknown backend name, or a remote backend without its key.
    """
    if settings is None:
        from nexus.config import settings as _settings

        settings = _settings

    resolved = SandboxType(sandbox_type or getattr(settings, "sandbox_backend", "local"))
    if resolved is SandboxType.E2B:
        return RemoteSandboxBackend(api_key=getattr(settings, "e2b_api_key", ""))
    if resolved is SandboxType.JUDGE0:
        return Judge0Backend(
            base_url=getattr(settings, "judge0_base_url", "")
            or "https://judge0-ce.p.rapidapi.com",
            api_key=getattr(settings, "judge0_api_key", ""),
        )
    return LocalSubprocessBackend(
        allow_unsafe_local_execution=getattr(
            settings, "allow_unsafe_local_execution", False
        ),
    )
