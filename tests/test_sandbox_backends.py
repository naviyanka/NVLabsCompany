"""Tests for the multi-backend code sandbox (Phase 3.1)."""

import asyncio
from pathlib import Path

import pytest

from nexus.execution import (
    ExecutionResult,
    Judge0Backend,
    LeaseHeld,
    LocalExecutionDisabled,
    LocalSubprocessBackend,
    RemoteSandboxBackend,
    SandboxBackend,
    SandboxType,
    UnsupportedLanguage,
    get_backend,
)


class _FakeBackend(SandboxBackend):
    """Records what the base class passed through, returns a fixed result."""

    sandbox_type = SandboxType.LOCAL

    def __init__(self, hold: float = 0.0) -> None:
        self.calls: list[dict] = []
        self._hold = hold

    @property
    def capabilities(self):
        from nexus.execution.sandbox import SandboxCapabilities

        return SandboxCapabilities(
            languages=("python",),
            network=False,
            filesystem=True,
            max_timeout_seconds=10,
        )

    async def _execute(self, code, language, timeout, workspace, env):
        self.calls.append(
            {
                "code": code,
                "language": language,
                "timeout": timeout,
                "workspace": workspace,
                "env": env,
            }
        )
        if self._hold:
            await asyncio.sleep(self._hold)
        return ExecutionResult(
            stdout="ok",
            stderr="",
            exit_code=0,
            timed_out=False,
            backend=self.sandbox_type,
        )


class TestContract:
    """Shared behaviour enforced by SandboxBackend.run."""

    @pytest.mark.asyncio
    async def test_unsupported_language_rejected(self) -> None:
        """A language outside capabilities never reaches the backend."""
        backend = _FakeBackend()
        with pytest.raises(UnsupportedLanguage):
            await backend.run("x", language="cobol")
        assert backend.calls == []

    @pytest.mark.asyncio
    async def test_timeout_clamped_to_capability(self) -> None:
        """A caller cannot exceed the backend's max timeout."""
        backend = _FakeBackend()
        await backend.run("x", timeout=9999)
        assert backend.calls[0]["timeout"] == 10

    @pytest.mark.asyncio
    async def test_missing_workspace_rejected(self, tmp_path: Path) -> None:
        """Workspace scoping refuses a path that is not a directory."""
        backend = _FakeBackend()
        with pytest.raises(ValueError):
            await backend.run("x", workspace=tmp_path / "nope")

    @pytest.mark.asyncio
    async def test_workspace_resolved(self, tmp_path: Path) -> None:
        """A valid workspace is resolved and handed to the backend."""
        backend = _FakeBackend()
        await backend.run("x", workspace=tmp_path)
        assert backend.calls[0]["workspace"] == tmp_path.resolve()

    @pytest.mark.asyncio
    async def test_result_carries_backend_and_duration(self) -> None:
        """The envelope stamps the backend and measures elapsed time."""
        result = await _FakeBackend().run("x")
        assert result.backend is SandboxType.LOCAL
        assert result.ok
        assert result.duration_ms >= 0


class TestLeases:
    """3.1.5 — two runs cannot share a sandbox."""

    @pytest.mark.asyncio
    async def test_second_run_id_blocked(self, tmp_path: Path) -> None:
        """A concurrent run with a different run_id is refused."""
        backend = _FakeBackend(hold=0.1)
        first = asyncio.create_task(
            backend.run("x", workspace=tmp_path, run_id="run-a")
        )
        await asyncio.sleep(0.02)
        with pytest.raises(LeaseHeld):
            await backend.run("x", workspace=tmp_path, run_id="run-b")
        await first

    @pytest.mark.asyncio
    async def test_same_run_id_reentrant(self, tmp_path: Path) -> None:
        """The lease holder may execute again inside its own lease."""
        backend = _FakeBackend(hold=0.1)
        both = await asyncio.gather(
            backend.run("a", workspace=tmp_path, run_id="run-a"),
            backend.run("b", workspace=tmp_path, run_id="run-a"),
        )
        assert all(r.ok for r in both)

    @pytest.mark.asyncio
    async def test_lease_released_after_run(self, tmp_path: Path) -> None:
        """A finished run frees the sandbox for anyone else."""
        backend = _FakeBackend()
        await backend.run("x", workspace=tmp_path, run_id="run-a")
        assert (await backend.run("x", workspace=tmp_path, run_id="run-b")).ok

    @pytest.mark.asyncio
    async def test_distinct_workspaces_do_not_collide(self, tmp_path: Path) -> None:
        """Leases are per-workspace, so separate tasks run in parallel."""
        one, two = tmp_path / "one", tmp_path / "two"
        one.mkdir()
        two.mkdir()
        backend = _FakeBackend(hold=0.05)
        results = await asyncio.gather(
            backend.run("x", workspace=one, run_id="run-a"),
            backend.run("x", workspace=two, run_id="run-b"),
        )
        assert all(r.ok for r in results)


class TestLocalBackend:
    """3.1.4 — local execution is off unless explicitly enabled."""

    @pytest.mark.asyncio
    async def test_refuses_when_disabled(self) -> None:
        """Default construction refuses to execute anything."""
        with pytest.raises(LocalExecutionDisabled):
            await LocalSubprocessBackend().run("print(1)")

    @pytest.mark.asyncio
    async def test_runs_when_enabled(self, tmp_path: Path) -> None:
        """With the flag on, real code executes and stdout comes back."""
        backend = LocalSubprocessBackend(
            allow_unsafe_local_execution=True, allow_network=True
        )
        result = await backend.run(
            "print('hello')", workspace=tmp_path, timeout=20
        )
        assert result.ok
        assert "hello" in result.stdout

    @pytest.mark.asyncio
    async def test_nonzero_exit_reported(self, tmp_path: Path) -> None:
        """A failing snippet reports a nonzero exit and stderr."""
        backend = LocalSubprocessBackend(
            allow_unsafe_local_execution=True, allow_network=True
        )
        result = await backend.run(
            "raise SystemExit(3)", workspace=tmp_path, timeout=20
        )
        assert not result.ok
        assert result.exit_code == 3

    @pytest.mark.asyncio
    async def test_timeout_kills_process(self, tmp_path: Path) -> None:
        """A hung snippet is killed and flagged as timed out."""
        backend = LocalSubprocessBackend(
            allow_unsafe_local_execution=True, allow_network=True
        )
        result = await backend.run(
            "import time; time.sleep(30)", workspace=tmp_path, timeout=1
        )
        assert result.timed_out
        assert not result.ok

    @pytest.mark.asyncio
    async def test_cwd_is_workspace(self, tmp_path: Path) -> None:
        """The child process starts inside its task workspace (3.1.6)."""
        backend = LocalSubprocessBackend(
            allow_unsafe_local_execution=True, allow_network=True
        )
        result = await backend.run(
            "import os; print(os.getcwd())", workspace=tmp_path, timeout=20
        )
        assert str(tmp_path.resolve()) in result.stdout

    @pytest.mark.asyncio
    async def test_host_env_not_inherited(self, tmp_path: Path, monkeypatch) -> None:
        """Host secrets are not passed to the child."""
        monkeypatch.setenv("NEXUS_TEST_SECRET", "leaked")
        backend = LocalSubprocessBackend(
            allow_unsafe_local_execution=True, allow_network=True
        )
        result = await backend.run(
            "import os; print(os.environ.get('NEXUS_TEST_SECRET'))",
            workspace=tmp_path,
            timeout=20,
        )
        assert "leaked" not in result.stdout


class TestBackendParity:
    """Accept criterion — one snippet, identical result shape per backend."""

    @pytest.mark.asyncio
    async def test_judge0_and_local_agree_on_shape(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        """Judge0 and local produce the same ExecutionResult contract."""
        judge0 = Judge0Backend(base_url="http://judge0.test")

        async def fake_execute(code, language, timeout, workspace, env):
            return Judge0Backend._to_result(
                {"stdout": "hello\n", "status": {"id": 3}, "exit_code": 0}
            )

        monkeypatch.setattr(judge0, "_execute", fake_execute)
        remote = await judge0.run("print('hello')", workspace=tmp_path)

        local = await LocalSubprocessBackend(
            allow_unsafe_local_execution=True, allow_network=True
        ).run("print('hello')", workspace=tmp_path, timeout=20)

        assert local.stdout.strip() == remote.stdout.strip() == "hello"
        assert local.ok and remote.ok
        assert remote.backend is SandboxType.JUDGE0
        assert local.backend is SandboxType.LOCAL


class TestNormalization:
    """Backend-specific payloads map onto the shared result."""

    def test_judge0_time_limit_exceeded(self) -> None:
        """Judge0 status 5 becomes timed_out."""
        result = Judge0Backend._to_result({"status": {"id": 5}, "stdout": ""})
        assert result.timed_out
        assert not result.ok

    def test_judge0_compile_error_in_stderr(self) -> None:
        """Compile output is surfaced through stderr."""
        result = Judge0Backend._to_result(
            {"status": {"id": 6}, "compile_output": "boom"}
        )
        assert "boom" in result.stderr
        assert not result.ok

    def test_e2b_error_marks_failure(self) -> None:
        """An E2B error object yields exit_code 1 and a stderr trace."""

        class _Logs:
            stdout = ["partial"]
            stderr: list[str] = []

        class _Err:
            traceback = "Traceback: bad"

        class _Exec:
            logs = _Logs()
            error = _Err()

        result = RemoteSandboxBackend._to_result(_Exec())
        assert result.exit_code == 1
        assert "bad" in result.stderr


class TestFactory:
    """get_backend wiring."""

    def test_defaults_to_disabled_local(self) -> None:
        """No settings means local, and local means disabled."""

        class _S:
            pass

        backend = get_backend(settings=_S())
        assert isinstance(backend, LocalSubprocessBackend)
        assert not backend.capabilities.network

    def test_e2b_requires_key(self) -> None:
        """Selecting E2B without a key fails loudly at construction."""

        class _S:
            sandbox_backend = "e2b"
            e2b_api_key = ""

        with pytest.raises(ValueError):
            get_backend(settings=_S())

    def test_judge0_selected(self) -> None:
        """Judge0 is built from the configured base URL."""

        class _S:
            sandbox_backend = "judge0"
            judge0_base_url = "http://judge0.test"
            judge0_api_key = "k"

        assert isinstance(get_backend(settings=_S()), Judge0Backend)

    def test_unknown_backend_rejected(self) -> None:
        """An unknown backend name is a ValueError, not a silent local run."""

        class _S:
            sandbox_backend = "nope"

        with pytest.raises(ValueError):
            get_backend(settings=_S())
