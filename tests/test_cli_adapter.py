"""Tests for CLI Adapter and CLI Registry.

Tests cover:
- CLIRegistry auto-detection of backends via shutil.which mocking
- CLIRegistry backend registration and querying
- CLIAdapter.validate_config requires 'backend' key
- CLIAdapter._build_args produces correct args for different backends
- CLIAdapter._do_execute handles subprocess spawn with mocked asyncio
- CLIAdapter session lifecycle (create, heartbeat, terminate)
"""

import asyncio
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from nexus.adapters.cli_adapter import CLIAdapter
from nexus.adapters.cli_registry import CLIBackendInfo, CLIRegistry
from nexus.adapters.registry import AdapterRegistry
from nexus.runtime.adapter import AgentSession, AgentStatus, TaskResult

pytestmark = pytest.mark.core_employee


def _run(coro):
    """Run an async coroutine synchronously."""
    return asyncio.run(coro)


def _fake_process(stdout=b"", stderr=b"", returncode=0):
    """A spawned CLI whose output streams yield once, then EOF."""
    proc = MagicMock()
    proc.pid = None  # no real process tree to kill
    proc.returncode = returncode
    proc.stdin = None
    proc.stdout = MagicMock(read=AsyncMock(side_effect=[stdout, b""]))
    proc.stderr = MagicMock(read=AsyncMock(side_effect=[stderr, b""]))
    proc.wait = AsyncMock(return_value=returncode)
    return proc


@pytest.fixture(autouse=True)
def _no_installed_clis():
    """Executables resolve to the bare command, whatever this machine has."""
    with patch(
        "nexus.adapters.cli_adapter.get_cli_registry",
        return_value=CLIRegistry(auto_detect=False),
    ):
        yield


class TestCLIRegistry:
    """Test CLIRegistry backend detection and management."""

    def test_registry_has_default_backends(self):
        """CLIRegistry has at least 6 default backends registered."""
        registry = CLIRegistry(auto_detect=False)
        backends = registry.get_all()
        assert len(backends) >= 6

    def test_default_backend_ids(self):
        """All expected backend IDs are registered by default."""
        registry = CLIRegistry(auto_detect=False)
        expected_ids = {"claude", "codex", "kiro-cli", "aider", "opencode", "agy"}
        actual_ids = {b.id for b in registry.get_all()}
        assert expected_ids.issubset(actual_ids)

    def test_get_backend_returns_info(self):
        """get_backend returns CLIBackendInfo for known backend."""
        registry = CLIRegistry(auto_detect=False)
        backend = registry.get_backend("claude")
        assert backend is not None
        assert backend.id == "claude"
        assert backend.name == "Claude Code"
        assert backend.command == "claude"
        assert backend.stability == "stable"

    def test_get_backend_unknown_returns_none(self):
        """get_backend returns None for unknown backend."""
        registry = CLIRegistry(auto_detect=False)
        result = registry.get_backend("nonexistent")
        assert result is None

    @patch("nexus.adapters.cli_registry.shutil.which")
    def test_detect_available_finds_installed(self, mock_which):
        """detect_available finds backends on PATH."""
        def which_side_effect(cmd):
            if cmd == "claude":
                return "/usr/local/bin/claude"
            if cmd == "aider":
                return "/usr/local/bin/aider"
            return None

        mock_which.side_effect = which_side_effect

        registry = CLIRegistry(auto_detect=False)
        available = registry.detect_available()

        assert "claude" in available
        assert available["claude"] == "/usr/local/bin/claude"
        assert "aider" in available
        assert available["aider"] == "/usr/local/bin/aider"
        assert "codex" not in available

    @patch("nexus.adapters.cli_registry.shutil.which")
    def test_is_available_checks_detection(self, mock_which):
        """is_available returns True only for detected backends."""
        mock_which.side_effect = lambda cmd: "/bin/claude" if cmd == "claude" else None

        registry = CLIRegistry(auto_detect=False)
        registry.detect_available()

        assert registry.is_available("claude") is True
        assert registry.is_available("codex") is False

    @patch("nexus.adapters.cli_registry.shutil.which")
    def test_get_available_returns_detected_only(self, mock_which):
        """get_available returns only backends found on system."""
        mock_which.side_effect = lambda cmd: "/bin/aider" if cmd == "aider" else None

        registry = CLIRegistry(auto_detect=False)
        registry.detect_available()

        available = registry.get_available()
        assert len(available) == 1
        assert available[0].id == "aider"

    @patch("nexus.adapters.cli_registry.shutil.which")
    def test_auto_detect_on_init(self, mock_which):
        """CLIRegistry with auto_detect=True runs detection on init."""
        mock_which.return_value = None
        registry = CLIRegistry(auto_detect=True)
        # Should have been called for each default backend
        assert mock_which.call_count >= 6

    def test_register_custom_backend(self):
        """register_backend adds a custom backend to the registry."""
        registry = CLIRegistry(auto_detect=False)
        custom = CLIBackendInfo(
            id="custom-ai",
            name="Custom AI CLI",
            command="custom-ai",
            stability="experimental",
        )
        registry.register_backend(custom)

        result = registry.get_backend("custom-ai")
        assert result is not None
        assert result.name == "Custom AI CLI"

    def test_get_path_returns_resolved_path(self):
        """get_path returns the resolved path for available backends."""
        registry = CLIRegistry(auto_detect=False)
        # Manually set available
        registry._available["claude"] = "/usr/local/bin/claude"

        assert registry.get_path("claude") == "/usr/local/bin/claude"
        assert registry.get_path("codex") is None

    @patch("nexus.adapters.cli_registry.subprocess.run")
    def test_probe_version_not_available(self, mock_run):
        """probe_version returns None if backend is not available."""
        registry = CLIRegistry(auto_detect=False)
        result = registry.probe_version("claude")
        assert result is None
        mock_run.assert_not_called()

    def test_to_dict_serialization(self):
        """to_dict produces a serializable dictionary."""
        registry = CLIRegistry(auto_detect=False)
        registry._available["claude"] = "/usr/local/bin/claude"

        data = registry.to_dict()
        assert "backends" in data
        assert "available_count" in data
        assert data["available_count"] == 1
        assert data["total_count"] >= 6
        assert data["backends"]["claude"]["available"] is True
        assert data["backends"]["codex"]["available"] is False

    def test_cli_backend_info_defaults(self):
        """CLIBackendInfo has sensible defaults."""
        info = CLIBackendInfo(id="test", name="Test", command="test-cli")
        assert info.instruction_path == ""
        assert info.stability == "experimental"
        assert info.supports_resume is False
        assert info.supports_agent_type is False
        assert info.supports_stdin is True
        assert info.guard_type == "none"
        assert info.delete_env == []


class TestCLIAdapterValidation:
    """Test CLIAdapter configuration validation."""

    @pytest.fixture
    def adapter(self):
        """Create a CLIAdapter instance."""
        return CLIAdapter()

    def test_validate_config_requires_backend(self, adapter):
        """validate_config raises ValueError when 'backend' is missing."""
        with pytest.raises(ValueError, match="backend"):
            adapter.validate_config({"workspace": "/tmp"})

    def test_validate_config_rejects_unknown_backend(self, adapter):
        """validate_config raises ValueError for unknown backend."""
        with pytest.raises(ValueError, match="Unknown CLI backend"):
            adapter.validate_config({"backend": "nonexistent-tool"})

    def test_validate_config_accepts_valid_backend(self, adapter):
        """validate_config succeeds with a known backend."""
        # Should not raise
        adapter.validate_config({"backend": "claude"})
        adapter.validate_config({"backend": "codex"})
        adapter.validate_config({"backend": "aider"})
        adapter.validate_config({"backend": "kiro-cli"})
        adapter.validate_config({"backend": "opencode"})
        adapter.validate_config({"backend": "agy"})


# Golden argument vectors: the verified flags each backend is invoked with.
# _build_args delegates to CLIBackendInfo.build_args, so this also covers the
# registry-level builder.
@pytest.mark.parametrize(
    ("backend_id", "prompt", "extra", "model", "expected"),
    [
        ("claude", "test prompt", None, "", ["claude", "-p", "test prompt"]),
        ("claude", "test prompt", ["--verbose"], "", ["claude", "-p", "--verbose", "test prompt"]),
        # Codex runs `exec` and reads the prompt from stdin, not argv.
        ("codex", "fix this bug", None, "", ["codex", "exec", "--skip-git-repo-check"]),
        ("codex", "hello", None, "o3", ["codex", "exec", "--skip-git-repo-check", "-m", "o3"]),
        # Aider passes the prompt via --message and never auto-confirms.
        ("aider", "refactor this", None, "", ["aider", "--message", "refactor this"]),
        ("aider", "refactor this", ["--verbose"], "", ["aider", "--verbose", "--message", "refactor this"]),
        ("aider", "fix it", None, "gpt-4", ["aider", "--model", "gpt-4", "--message", "fix it"]),
        ("kiro-cli", "analyze code", None, "", ["kiro-cli", "chat", "--no-interactive", "analyze code"]),
        ("opencode", "generate tests", None, "", ["opencode", "run", "generate tests"]),
        ("agy", "run task", None, "", ["agy", "-p", "run task"]),
    ],
    ids=["claude-plain", "claude-verbose", "codex-plain", "codex-model", "aider-plain",
         "aider-verbose", "aider-model", "kiro-cli", "opencode", "agy"],
)
def test_build_args_golden_argv(backend_id, prompt, extra, model, expected):
    adapter = CLIAdapter()
    backend = adapter._registry.get_backend(backend_id)
    assert adapter._build_args(backend, prompt, extra, model=model) == expected


class TestCLIAdapterExecution:
    """Test CLIAdapter session lifecycle and subprocess execution."""

    @pytest.fixture
    def adapter(self):
        """Create a CLIAdapter instance."""
        return CLIAdapter()

    @pytest.fixture
    def agent_id(self):
        """Fixed agent UUID for tests."""
        return uuid.UUID("abcdef01-abcd-abcd-abcd-abcdef012345")

    @pytest.fixture
    def task_id(self):
        """Fixed task UUID for tests."""
        return uuid.UUID("99999999-9999-9999-9999-999999999999")

    def test_create_session_sets_workspace(self, adapter, agent_id):
        """create_session initializes workspace and metadata."""
        config = {"backend": "claude", "workspace": "/tmp/test_workspace"}
        session = _run(adapter.create_session(agent_id, config))

        assert session.status == AgentStatus.READY
        assert session.metadata["backend"] == "claude"
        assert session.metadata["workspace"] == "/tmp/test_workspace"
        assert session.session_id in adapter._workspaces

    def test_create_session_creates_temp_workspace(self, adapter, agent_id):
        """create_session creates temp dir when no workspace specified."""
        config = {"backend": "aider"}
        session = _run(adapter.create_session(agent_id, config))

        workspace = session.metadata["workspace"]
        assert "nexus_cli_aider_" in workspace

    def test_heartbeat_no_process(self, adapter, agent_id):
        """Heartbeat returns True when no subprocess is running."""
        config = {"backend": "claude"}
        session = _run(adapter.create_session(agent_id, config))

        result = _run(adapter.send_heartbeat(session))
        assert result is True

    def test_terminate_cleans_up(self, adapter, agent_id):
        """Terminate cleans up session tracking."""
        config = {"backend": "claude"}
        session = _run(adapter.create_session(agent_id, config))
        session_id = session.session_id

        result = _run(adapter.terminate(session))
        assert result is True
        assert session.status == AgentStatus.TERMINATED
        assert session_id not in adapter._workspaces

    def test_get_capabilities(self, adapter, agent_id):
        """CLIAdapter advertises multi_backend capability."""
        config = {"backend": "claude"}
        session = _run(adapter.create_session(agent_id, config))

        caps = _run(adapter.get_capabilities(session))
        assert "execute_task" in caps
        assert "multi_backend" in caps
        assert "subprocess_execution" in caps
        assert "workspace_isolation" in caps

    @patch("asyncio.create_subprocess_exec")
    def test_execute_task_success(self, mock_exec, adapter, agent_id, task_id):
        """_do_execute handles successful subprocess execution."""
        # Set up mock process
        mock_exec.return_value = _fake_process(b"Task completed successfully\n")

        config = {"backend": "claude", "workspace": "/tmp/test_cli"}
        session = _run(adapter.create_session(agent_id, config))

        payload = {"prompt": "Write a hello world program"}
        result = _run(adapter.execute_task(session, task_id, payload))

        assert result.success is True
        assert "Task completed successfully" in result.output
        mock_exec.assert_called_once()

        # Verify the command was built correctly for claude backend
        call_args = mock_exec.call_args
        cmd_args = call_args[0]
        assert cmd_args[0] == "claude"
        assert "-p" in cmd_args

    @patch("asyncio.create_subprocess_exec")
    def test_execute_task_failure(self, mock_exec, adapter, agent_id, task_id):
        """_do_execute returns failure TaskResult on non-zero exit."""
        mock_exec.return_value = _fake_process(
            stderr=b"Error: permission denied\n", returncode=1
        )

        config = {"backend": "codex", "workspace": "/tmp/test_cli"}
        session = _run(adapter.create_session(agent_id, config))

        payload = {"prompt": "do something"}
        result = _run(adapter.execute_task(session, task_id, payload))

        assert result.success is False
        assert "permission denied" in result.error

    @patch("asyncio.create_subprocess_exec")
    def test_execute_task_file_not_found(self, mock_exec, adapter, agent_id, task_id):
        """_do_execute handles missing CLI binary gracefully."""
        mock_exec.side_effect = FileNotFoundError("No such file: 'claude'")

        config = {"backend": "claude", "workspace": "/tmp/test_cli"}
        session = _run(adapter.create_session(agent_id, config))

        payload = {"prompt": "test"}
        result = _run(adapter.execute_task(session, task_id, payload))

        assert result.success is False
        assert "not found" in result.error

    @patch("asyncio.create_subprocess_exec")
    def test_execute_task_parses_tokens(self, mock_exec, adapter, agent_id, task_id):
        """_do_execute parses token counts from output."""
        output = b"Result: done\nInput tokens: 150\nOutput tokens: 75\nCost: $0.05\n"
        mock_exec.return_value = _fake_process(output)

        config = {"backend": "claude", "workspace": "/tmp/test_cli"}
        session = _run(adapter.create_session(agent_id, config))

        payload = {"prompt": "analyze"}
        result = _run(adapter.execute_task(session, task_id, payload))

        assert result.success is True
        assert result.input_tokens == 150
        assert result.output_tokens == 75
        assert result.cost_cents == 5

    @patch("asyncio.create_subprocess_exec")
    def test_execute_task_timeout(self, mock_exec, adapter, agent_id, task_id):
        """_do_execute handles timeout with graceful termination."""
        mock_process = _fake_process()
        mock_process.stdout.read = AsyncMock(side_effect=asyncio.TimeoutError())
        mock_process.send_signal = MagicMock()
        mock_process.kill = MagicMock()
        mock_process.wait = AsyncMock()
        mock_process.returncode = None
        mock_exec.return_value = mock_process

        config = {"backend": "claude", "workspace": "/tmp/test_cli", "timeout": 1}
        session = _run(adapter.create_session(agent_id, config))

        payload = {"prompt": "long running task", "timeout": 1}
        result = _run(adapter.execute_task(session, task_id, payload))

        assert result.success is False
        assert "timed out" in result.error
        mock_process.send_signal.assert_called_once()


class TestCLIAdapterInRegistry:
    """Test that CLIAdapter is properly registered in AdapterRegistry."""

    def test_cli_adapter_registered(self):
        """CLIAdapter is registered under 'cli' key in default registry."""
        registry = AdapterRegistry(auto_register=True)
        assert registry.is_registered("cli")
        assert "cli" in registry.get_adapter_types()

    def test_create_cli_adapter_from_registry(self):
        """AdapterRegistry can create a CLIAdapter instance."""
        registry = AdapterRegistry(auto_register=True)
        adapter = registry.create_adapter("cli")
        assert isinstance(adapter, CLIAdapter)
        assert adapter.adapter_type == "cli"

    def test_registry_has_all_defaults_plus_cli(self):
        """Auto-registered registry has all 7 default adapters including 'cli'."""
        registry = AdapterRegistry(auto_register=True)
        types = registry.get_adapter_types()
        assert "openai" in types
        assert "anthropic" in types
        assert "ollama" in types
        assert "claude_code" in types
        assert "cli" in types
        assert "http" in types
        assert "mcp" in types
        assert len(types) >= 7

    def test_cli_adapter_capabilities_via_registry(self):
        """get_capabilities returns CLI adapter capabilities from registry."""
        registry = AdapterRegistry(auto_register=True)
        caps = registry.get_capabilities("cli")
        assert "multi_backend" in caps
        assert "execute_task" in caps


class TestCLIAdapterEnvFiltering:
    """Test that sensitive env vars are stripped from subprocess environment."""

    @pytest.fixture
    def adapter(self):
        """Create a CLIAdapter instance."""
        return CLIAdapter()

    @pytest.fixture
    def agent_id(self):
        """Fixed agent UUID for tests."""
        return uuid.UUID("abcdef01-abcd-abcd-abcd-abcdef012345")

    @pytest.fixture
    def task_id(self):
        """Fixed task UUID for tests."""
        return uuid.UUID("99999999-9999-9999-9999-999999999999")

    @patch("asyncio.create_subprocess_exec")
    @patch.dict(
        "os.environ",
        {
            "OPENAI_API_KEY": "sk-secret",
            "ANTHROPIC_API_KEY": "sk-ant-secret",
            "DATABASE_URL": "postgres://secret",
            "SECRET_KEY": "mysecret",
            "HOME": "/home/user",
            "PATH": "/usr/bin",
        },
        clear=True,
    )
    def test_sensitive_vars_stripped_for_generic_backend(
        self, mock_exec, adapter, agent_id, task_id
    ):
        """Sensitive env vars are stripped for backends without allow_env."""
        mock_exec.return_value = _fake_process(b"done")

        config = {"backend": "opencode", "workspace": "/tmp/test_cli"}
        session = _run(adapter.create_session(agent_id, config))

        payload = {"prompt": "test"}
        _run(adapter.execute_task(session, task_id, payload))

        # Check the env passed to subprocess
        call_kwargs = mock_exec.call_args[1]
        env = call_kwargs["env"]
        assert "OPENAI_API_KEY" not in env
        assert "ANTHROPIC_API_KEY" not in env
        assert "DATABASE_URL" not in env
        assert "SECRET_KEY" not in env
        # Non-sensitive vars should still be present
        assert env.get("HOME") == "/home/user"
        assert env.get("PATH") == "/usr/bin"

    @patch("asyncio.create_subprocess_exec")
    @patch.dict(
        "os.environ",
        {
            "OPENAI_API_KEY": "sk-secret",
            "ANTHROPIC_API_KEY": "sk-ant-secret",
            "DATABASE_URL": "postgres://secret",
            "HOME": "/home/user",
        },
        clear=True,
    )
    def test_allowed_vars_kept_for_claude_backend(
        self, mock_exec, adapter, agent_id, task_id
    ):
        """Claude backend keeps ANTHROPIC_API_KEY (in allow_env)."""
        mock_exec.return_value = _fake_process(b"done")

        config = {"backend": "claude", "workspace": "/tmp/test_cli"}
        session = _run(adapter.create_session(agent_id, config))

        payload = {"prompt": "test"}
        _run(adapter.execute_task(session, task_id, payload))

        call_kwargs = mock_exec.call_args[1]
        env = call_kwargs["env"]
        # Claude should keep ANTHROPIC_API_KEY
        assert env.get("ANTHROPIC_API_KEY") == "sk-ant-secret"
        # But not OPENAI_API_KEY or DATABASE_URL
        assert "OPENAI_API_KEY" not in env
        assert "DATABASE_URL" not in env


class TestCLIAdapterWorkspaceCleanup:
    """Test that temp workspaces are cleaned up on termination."""

    @pytest.fixture
    def adapter(self):
        """Create a CLIAdapter instance."""
        return CLIAdapter()

    @pytest.fixture
    def agent_id(self):
        """Fixed agent UUID for tests."""
        return uuid.UUID("abcdef01-abcd-abcd-abcd-abcdef012345")

    def test_terminate_cleans_temp_workspace(self, adapter, agent_id):
        """Terminate removes temp workspace directory."""
        import tempfile
        import os

        config = {"backend": "aider"}
        session = _run(adapter.create_session(agent_id, config))

        workspace = session.metadata["workspace"]
        # Verify temp workspace was created
        assert os.path.isdir(workspace)
        assert workspace.startswith(tempfile.gettempdir())

        # Terminate should clean it up
        _run(adapter.terminate(session))
        assert not os.path.isdir(workspace)

    def test_terminate_does_not_remove_user_workspace(self, adapter, agent_id):
        """Terminate does NOT remove user-specified workspace directories."""
        import tempfile
        import os

        # Create a workspace outside of tempdir
        user_workspace = tempfile.mkdtemp(dir="/tmp", prefix="user_ws_")
        try:
            config = {"backend": "claude", "workspace": user_workspace}
            session = _run(adapter.create_session(agent_id, config))

            _run(adapter.terminate(session))
            # User workspace should still exist
            assert os.path.isdir(user_workspace)
        finally:
            os.rmdir(user_workspace)


class TestCLIBackendInfoBuildArgs:
    """Test CLIBackendInfo.build_args extensibility."""

    def test_custom_backend_build_args_default(self):
        """Default build_args appends prompt as positional argument."""
        backend = CLIBackendInfo(
            id="custom",
            name="Custom",
            command="custom-cli",
        )
        args = backend.build_args("hello world")
        assert args == ["custom-cli", "hello world"]

    def test_custom_backend_build_args_with_extra(self):
        """Default build_args includes extra_args before prompt."""
        backend = CLIBackendInfo(
            id="custom",
            name="Custom",
            command="custom-cli",
        )
        args = backend.build_args("hello", ["--verbose", "--fast"])
        assert args == ["custom-cli", "--verbose", "--fast", "hello"]


def _work_context(work_mode):
    """A server-built task-attempt context, as the runtime hands the adapter."""
    from nexus.tools.context import ExecutionContext

    return ExecutionContext(
        company_id=uuid.uuid4(), principal_id="p", principal_role="agent",
        source="chat", agent_id=uuid.uuid4(), work_mode=work_mode,
    )


class TestWorkModeFlagProtection:
    """Caller-supplied extra args cannot override the work-mode catalogue's flags."""

    @pytest.mark.parametrize("work_mode", ["text", "read_only", "write"])
    @pytest.mark.parametrize(
        ("backend_id", "extra"),
        [
            ("agy", ["--mode", "accept-edits"]),
            ("agy", ["--mode=accept-edits"]),
            ("agy", ["--MODE=accept-edits"]),
            ("agy", ["--mod=accept-edits"]),
            ("claude", ["--permission-mode", "bypassPermissions"]),
            ("claude", ["--permission-mode=bypassPermissions"]),
            ("claude", ["--allowedTools=Bash(*)"]),
            ("claude", ["--allowedtools", "Bash(*)"]),
        ],
    )
    def test_override_is_refused(self, backend_id, extra, work_mode):
        backend = CLIRegistry(auto_detect=False).get_backend(backend_id)
        with pytest.raises(ValueError, match="controlled by the work mode"):
            backend.build_args("p", extra, work_mode=work_mode)

    def test_every_cataloged_work_flag_is_protected(self):
        checked = 0
        for backend in CLIRegistry(auto_detect=False).get_all():
            for mode, args in backend.work_args:
                for flag in (a for a in args if a.startswith("-")):
                    for extra in ([flag, "x"], [f"{flag.split('=', 1)[0]}=x"]):
                        with pytest.raises(ValueError):
                            backend.build_args("p", extra, work_mode=mode)
                        checked += 1
        assert checked >= 6

    def test_unrelated_extra_args_and_non_work_runs_are_unchanged(self):
        agy = CLIRegistry(auto_detect=False).get_backend("agy")
        cmd = agy.build_args("p", ["--verbose", "--model-x"], work_mode="text")
        assert cmd[:6] == ["agy", "--mode", "plan", "--verbose", "--model-x", "-p"]
        # Outside a work attempt the catalogue controls nothing, so nothing is refused here.
        assert "--mode" in agy.build_args("p", ["--mode", "other"])

    @pytest.mark.parametrize("where", ["config", "payload"])
    @patch("asyncio.create_subprocess_exec")
    def test_attempt_is_refused_before_the_cli_starts(self, mock_exec, where):
        adapter = CLIAdapter()
        override = ["--mode=accept-edits"]
        config = {"backend": "agy", "workspace": "/tmp/test_cli"}
        payload = {"prompt": "do it"}
        if where == "config":
            config["extra_args"] = override
        else:
            payload["args"] = override
        session = _run(adapter.create_session(uuid.uuid4(), config))
        session.context = _work_context("text")

        result = _run(adapter.execute_task(session, uuid.uuid4(), payload))

        assert result.success is False
        assert "controlled by the work mode" in result.error
        mock_exec.assert_not_called()

    @patch("asyncio.create_subprocess_exec")
    def test_claude_permission_override_is_still_refused(self, mock_exec):
        adapter = CLIAdapter()
        config = {"backend": "claude", "workspace": "/tmp/test_cli"}
        session = _run(adapter.create_session(uuid.uuid4(), config))
        session.context = _work_context("write")
        payload = {"prompt": "x", "args": ["--dangerously-skip-permissions"]}

        result = _run(adapter.execute_task(session, uuid.uuid4(), payload))

        assert result.success is False and "not allowed" in result.error
        mock_exec.assert_not_called()
