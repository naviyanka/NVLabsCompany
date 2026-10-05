"""Tests for Claude Code Adapter.

Tests cover:
- _parse_stream_json with valid multi-event stream
- _parse_stream_json handling blank/malformed lines
- session_id extraction from result events stored in session.metadata
- --resume flag added when resume_session_id present in payload
- --output-format stream-json is added by default
- --worktree appended when payload['worktree'] is True
- backward compat when plain text (non-JSON) output is returned
- _get_capabilities includes new capability strings
"""

import asyncio
import json
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from nexus.adapters.claude_code_adapter import ClaudeCodeAdapter
from nexus.runtime.adapter import AgentSession, AgentStatus, TaskResult


def _run(coro):
    """Run an async coroutine synchronously."""
    return asyncio.run(coro)


class TestParseStreamJson:
    """Test _parse_stream_json method."""

    @pytest.fixture
    def adapter(self):
        """Create a ClaudeCodeAdapter instance."""
        return ClaudeCodeAdapter()

    def test_valid_multi_event_stream(self, adapter):
        """Parses multiple valid JSON lines into list of event dicts."""
        stream = "\n".join([
            json.dumps({"type": "system", "session_id": "sess-123"}),
            json.dumps({"type": "assistant", "content": "Hello"}),
            json.dumps({"type": "tool_use", "tool": "read_file", "input": {}}),
            json.dumps({"type": "tool_result", "output": "file contents"}),
            json.dumps({"type": "result", "result": "Done!", "session_id": "sess-123"}),
        ])

        events = adapter._parse_stream_json(stream)

        assert len(events) == 5
        assert events[0]["type"] == "system"
        assert events[0]["session_id"] == "sess-123"
        assert events[1]["type"] == "assistant"
        assert events[1]["content"] == "Hello"
        assert events[2]["type"] == "tool_use"
        assert events[3]["type"] == "tool_result"
        assert events[4]["type"] == "result"
        assert events[4]["result"] == "Done!"

    def test_handles_blank_lines(self, adapter):
        """Blank lines are skipped gracefully."""
        stream = (
            json.dumps({"type": "assistant", "content": "hi"})
            + "\n\n\n"
            + json.dumps({"type": "result", "result": "bye"})
            + "\n"
        )

        events = adapter._parse_stream_json(stream)

        assert len(events) == 2
        assert events[0]["type"] == "assistant"
        assert events[1]["type"] == "result"

    def test_handles_malformed_json(self, adapter):
        """Malformed JSON lines are skipped without raising."""
        stream = "\n".join([
            json.dumps({"type": "assistant", "content": "valid"}),
            "this is not json at all",
            "{broken json: ",
            json.dumps({"type": "result", "result": "final"}),
        ])

        events = adapter._parse_stream_json(stream)

        assert len(events) == 2
        assert events[0]["type"] == "assistant"
        assert events[1]["type"] == "result"

    def test_empty_output(self, adapter):
        """Empty string returns empty list."""
        events = adapter._parse_stream_json("")
        assert events == []

    def test_only_blank_lines(self, adapter):
        """Only blank lines returns empty list."""
        events = adapter._parse_stream_json("\n\n\n   \n")
        assert events == []

    def test_non_dict_json_skipped(self, adapter):
        """Non-dict JSON values (arrays, strings, numbers) are skipped."""
        stream = "\n".join([
            json.dumps([1, 2, 3]),
            json.dumps("just a string"),
            json.dumps(42),
            json.dumps({"type": "result", "result": "valid"}),
        ])

        events = adapter._parse_stream_json(stream)

        assert len(events) == 1
        assert events[0]["type"] == "result"

    def test_whitespace_around_json(self, adapter):
        """Whitespace around JSON lines is handled."""
        stream = "   " + json.dumps({"type": "system"}) + "   \n"

        events = adapter._parse_stream_json(stream)

        assert len(events) == 1
        assert events[0]["type"] == "system"


class TestSessionIdExtraction:
    """Test session_id tracking from parsed events."""

    @pytest.fixture
    def adapter(self):
        """Create a ClaudeCodeAdapter instance."""
        return ClaudeCodeAdapter()

    @pytest.fixture
    def agent_id(self):
        """Fixed agent UUID for tests."""
        return uuid.UUID("abcdef01-abcd-abcd-abcd-abcdef012345")

    @pytest.fixture
    def task_id(self):
        """Fixed task UUID for tests."""
        return uuid.UUID("99999999-9999-9999-9999-999999999999")

    def test_extract_session_id_from_system_event(self, adapter):
        """Extracts session_id from a system type event."""
        events = [
            {"type": "system", "session_id": "sess-abc-123"},
            {"type": "assistant", "content": "Hello"},
        ]
        result = adapter._extract_session_id(events)
        assert result == "sess-abc-123"

    def test_extract_session_id_from_result_event(self, adapter):
        """Extracts session_id from a result type event."""
        events = [
            {"type": "assistant", "content": "Working..."},
            {"type": "result", "result": "Done", "session_id": "sess-xyz-789"},
        ]
        result = adapter._extract_session_id(events)
        assert result == "sess-xyz-789"

    def test_no_session_id_returns_none(self, adapter):
        """Returns None when no session_id is found in events."""
        events = [
            {"type": "assistant", "content": "Hello"},
            {"type": "tool_use", "tool": "read"},
        ]
        result = adapter._extract_session_id(events)
        assert result is None

    def test_empty_events_returns_none(self, adapter):
        """Returns None for empty event list."""
        result = adapter._extract_session_id([])
        assert result is None

    @patch("asyncio.create_subprocess_exec")
    def test_session_id_stored_in_metadata(
        self, mock_exec, adapter, agent_id, task_id
    ):
        """Session metadata gets populated with last_session_id after execution."""
        stream_output = "\n".join([
            json.dumps({"type": "system", "session_id": "sess-stored-001"}),
            json.dumps({"type": "assistant", "content": "Working"}),
            json.dumps({
                "type": "result",
                "result": "All done",
                "session_id": "sess-stored-001",
            }),
        ])

        mock_process = AsyncMock()
        mock_process.communicate = AsyncMock(
            return_value=(stream_output.encode(), b"")
        )
        mock_process.returncode = 0
        mock_exec.return_value = mock_process

        config = {"workspace": "/tmp/test_claude"}
        session = _run(adapter.create_session(agent_id, config))

        payload = {"prompt": "do something"}
        result = _run(adapter.execute_task(session, task_id, payload))

        assert result.success is True
        assert session.metadata["last_session_id"] == "sess-stored-001"

    @patch("asyncio.create_subprocess_exec")
    def test_no_session_id_in_output(
        self, mock_exec, adapter, agent_id, task_id
    ):
        """No session_id stored when output has no session_id field."""
        stream_output = "\n".join([
            json.dumps({"type": "assistant", "content": "Working"}),
            json.dumps({"type": "result", "result": "Done"}),
        ])

        mock_process = AsyncMock()
        mock_process.communicate = AsyncMock(
            return_value=(stream_output.encode(), b"")
        )
        mock_process.returncode = 0
        mock_exec.return_value = mock_process

        config = {"workspace": "/tmp/test_claude"}
        session = _run(adapter.create_session(agent_id, config))

        payload = {"prompt": "test"}
        _run(adapter.execute_task(session, task_id, payload))

        assert "last_session_id" not in session.metadata


class TestResumeSupport:
    """Test --resume flag support in _do_execute."""

    @pytest.fixture
    def adapter(self):
        """Create a ClaudeCodeAdapter instance."""
        return ClaudeCodeAdapter()

    @pytest.fixture
    def agent_id(self):
        """Fixed agent UUID for tests."""
        return uuid.UUID("abcdef01-abcd-abcd-abcd-abcdef012345")

    @pytest.fixture
    def task_id(self):
        """Fixed task UUID for tests."""
        return uuid.UUID("99999999-9999-9999-9999-999999999999")

    @patch("asyncio.create_subprocess_exec")
    def test_resume_flag_added_to_args(
        self, mock_exec, adapter, agent_id, task_id
    ):
        """--resume <id> is added when resume_session_id is in payload."""
        mock_process = AsyncMock()
        mock_process.communicate = AsyncMock(
            return_value=(b'{"type":"result","result":"resumed"}\n', b"")
        )
        mock_process.returncode = 0
        mock_exec.return_value = mock_process

        config = {"workspace": "/tmp/test_claude"}
        session = _run(adapter.create_session(agent_id, config))

        payload = {
            "prompt": "continue",
            "resume_session_id": "sess-prev-999",
        }
        _run(adapter.execute_task(session, task_id, payload))

        # Verify the command args contain --resume
        call_args = mock_exec.call_args[0]
        assert "--resume" in call_args
        resume_idx = list(call_args).index("--resume")
        assert call_args[resume_idx + 1] == "sess-prev-999"

    @patch("asyncio.create_subprocess_exec")
    def test_no_resume_flag_without_session_id(
        self, mock_exec, adapter, agent_id, task_id
    ):
        """--resume is not added when resume_session_id is not in payload."""
        mock_process = AsyncMock()
        mock_process.communicate = AsyncMock(
            return_value=(b'{"type":"result","result":"fresh"}\n', b"")
        )
        mock_process.returncode = 0
        mock_exec.return_value = mock_process

        config = {"workspace": "/tmp/test_claude"}
        session = _run(adapter.create_session(agent_id, config))

        payload = {"prompt": "new task"}
        _run(adapter.execute_task(session, task_id, payload))

        call_args = mock_exec.call_args[0]
        assert "--resume" not in call_args

    @patch("asyncio.create_subprocess_exec")
    def test_resume_empty_string_not_added(
        self, mock_exec, adapter, agent_id, task_id
    ):
        """--resume is not added when resume_session_id is empty string."""
        mock_process = AsyncMock()
        mock_process.communicate = AsyncMock(
            return_value=(b'{"type":"result","result":"ok"}\n', b"")
        )
        mock_process.returncode = 0
        mock_exec.return_value = mock_process

        config = {"workspace": "/tmp/test_claude"}
        session = _run(adapter.create_session(agent_id, config))

        payload = {"prompt": "test", "resume_session_id": ""}
        _run(adapter.execute_task(session, task_id, payload))

        call_args = mock_exec.call_args[0]
        assert "--resume" not in call_args


class TestStreamJsonDefaultArgs:
    """Test that --output-format stream-json is in default command args."""

    @pytest.fixture
    def adapter(self):
        """Create a ClaudeCodeAdapter instance."""
        return ClaudeCodeAdapter()

    @pytest.fixture
    def agent_id(self):
        """Fixed agent UUID for tests."""
        return uuid.UUID("abcdef01-abcd-abcd-abcd-abcdef012345")

    @pytest.fixture
    def task_id(self):
        """Fixed task UUID for tests."""
        return uuid.UUID("99999999-9999-9999-9999-999999999999")

    @patch("asyncio.create_subprocess_exec")
    def test_stream_json_in_default_args(
        self, mock_exec, adapter, agent_id, task_id
    ):
        """--output-format stream-json is included in default command args."""
        mock_process = AsyncMock()
        mock_process.communicate = AsyncMock(
            return_value=(b'{"type":"result","result":"done"}\n', b"")
        )
        mock_process.returncode = 0
        mock_exec.return_value = mock_process

        config = {"workspace": "/tmp/test_claude"}
        session = _run(adapter.create_session(agent_id, config))

        payload = {"prompt": "hello"}
        _run(adapter.execute_task(session, task_id, payload))

        call_args = list(mock_exec.call_args[0])
        assert "--output-format" in call_args
        fmt_idx = call_args.index("--output-format")
        assert call_args[fmt_idx + 1] == "stream-json"

    @patch("asyncio.create_subprocess_exec")
    def test_stream_json_with_extra_args(
        self, mock_exec, adapter, agent_id, task_id
    ):
        """Extra args are appended after the default stream-json flag."""
        mock_process = AsyncMock()
        mock_process.communicate = AsyncMock(
            return_value=(b'{"type":"result","result":"done"}\n', b"")
        )
        mock_process.returncode = 0
        mock_exec.return_value = mock_process

        config = {"workspace": "/tmp/test_claude"}
        session = _run(adapter.create_session(agent_id, config))

        payload = {"prompt": "hello", "args": ["--model", "sonnet"]}
        _run(adapter.execute_task(session, task_id, payload))

        call_args = list(mock_exec.call_args[0])
        assert "--output-format" in call_args
        assert "--model" in call_args
        assert "sonnet" in call_args

    @patch("asyncio.create_subprocess_exec")
    def test_result_text_extracted_from_events(
        self, mock_exec, adapter, agent_id, task_id
    ):
        """When stream-json is parsed, result text comes from result events."""
        stream_output = "\n".join([
            json.dumps({"type": "assistant", "content": "Thinking..."}),
            json.dumps({"type": "result", "result": "Final answer here"}),
        ])

        mock_process = AsyncMock()
        mock_process.communicate = AsyncMock(
            return_value=(stream_output.encode(), b"")
        )
        mock_process.returncode = 0
        mock_exec.return_value = mock_process

        config = {"workspace": "/tmp/test_claude"}
        session = _run(adapter.create_session(agent_id, config))

        payload = {"prompt": "What is 2+2?"}
        result = _run(adapter.execute_task(session, task_id, payload))

        assert result.success is True
        assert result.output == "Final answer here"


class TestWorktreeSupport:
    """Test --worktree flag support."""

    @pytest.fixture
    def adapter(self):
        """Create a ClaudeCodeAdapter instance."""
        return ClaudeCodeAdapter()

    @pytest.fixture
    def agent_id(self):
        """Fixed agent UUID for tests."""
        return uuid.UUID("abcdef01-abcd-abcd-abcd-abcdef012345")

    @pytest.fixture
    def task_id(self):
        """Fixed task UUID for tests."""
        return uuid.UUID("99999999-9999-9999-9999-999999999999")

    @patch("asyncio.create_subprocess_exec")
    def test_worktree_appended_when_true(
        self, mock_exec, adapter, agent_id, task_id
    ):
        """--worktree is appended when payload['worktree'] is True."""
        mock_process = AsyncMock()
        mock_process.communicate = AsyncMock(
            return_value=(b'{"type":"result","result":"isolated"}\n', b"")
        )
        mock_process.returncode = 0
        mock_exec.return_value = mock_process

        config = {"workspace": "/tmp/test_claude"}
        session = _run(adapter.create_session(agent_id, config))

        payload = {"prompt": "run in isolation", "worktree": True}
        _run(adapter.execute_task(session, task_id, payload))

        call_args = list(mock_exec.call_args[0])
        assert "--worktree" in call_args

    @patch("asyncio.create_subprocess_exec")
    def test_worktree_not_appended_when_false(
        self, mock_exec, adapter, agent_id, task_id
    ):
        """--worktree is not appended when payload['worktree'] is False."""
        mock_process = AsyncMock()
        mock_process.communicate = AsyncMock(
            return_value=(b'{"type":"result","result":"normal"}\n', b"")
        )
        mock_process.returncode = 0
        mock_exec.return_value = mock_process

        config = {"workspace": "/tmp/test_claude"}
        session = _run(adapter.create_session(agent_id, config))

        payload = {"prompt": "normal run", "worktree": False}
        _run(adapter.execute_task(session, task_id, payload))

        call_args = list(mock_exec.call_args[0])
        assert "--worktree" not in call_args

    @patch("asyncio.create_subprocess_exec")
    def test_worktree_not_appended_when_absent(
        self, mock_exec, adapter, agent_id, task_id
    ):
        """--worktree is not appended when worktree key is absent."""
        mock_process = AsyncMock()
        mock_process.communicate = AsyncMock(
            return_value=(b'{"type":"result","result":"default"}\n', b"")
        )
        mock_process.returncode = 0
        mock_exec.return_value = mock_process

        config = {"workspace": "/tmp/test_claude"}
        session = _run(adapter.create_session(agent_id, config))

        payload = {"prompt": "just do it"}
        _run(adapter.execute_task(session, task_id, payload))

        call_args = list(mock_exec.call_args[0])
        assert "--worktree" not in call_args


class TestBackwardCompatibility:
    """Test backward compat when plain text (non-JSON) output is returned."""

    @pytest.fixture
    def adapter(self):
        """Create a ClaudeCodeAdapter instance."""
        return ClaudeCodeAdapter()

    @pytest.fixture
    def agent_id(self):
        """Fixed agent UUID for tests."""
        return uuid.UUID("abcdef01-abcd-abcd-abcd-abcdef012345")

    @pytest.fixture
    def task_id(self):
        """Fixed task UUID for tests."""
        return uuid.UUID("99999999-9999-9999-9999-999999999999")

    @patch("asyncio.create_subprocess_exec")
    def test_plain_text_output_still_works(
        self, mock_exec, adapter, agent_id, task_id
    ):
        """Plain text output (non-JSON) is returned as-is in result.output."""
        plain_output = "This is just plain text output\nNo JSON here."

        mock_process = AsyncMock()
        mock_process.communicate = AsyncMock(
            return_value=(plain_output.encode(), b"")
        )
        mock_process.returncode = 0
        mock_exec.return_value = mock_process

        config = {"workspace": "/tmp/test_claude"}
        session = _run(adapter.create_session(agent_id, config))

        payload = {"prompt": "run something"}
        result = _run(adapter.execute_task(session, task_id, payload))

        assert result.success is True
        # When no structured events are parsed, output is the raw stdout
        assert result.output == plain_output
        # No session_id should be stored
        assert "last_session_id" not in session.metadata

    @patch("asyncio.create_subprocess_exec")
    def test_mixed_output_with_some_json(
        self, mock_exec, adapter, agent_id, task_id
    ):
        """Mixed output where only some lines are valid JSON."""
        mixed_output = "\n".join([
            "Starting up...",
            json.dumps({"type": "system", "session_id": "sess-mix"}),
            "Some plain log line",
            json.dumps({"type": "result", "result": "completed task"}),
            "Shutting down...",
        ])

        mock_process = AsyncMock()
        mock_process.communicate = AsyncMock(
            return_value=(mixed_output.encode(), b"")
        )
        mock_process.returncode = 0
        mock_exec.return_value = mock_process

        config = {"workspace": "/tmp/test_claude"}
        session = _run(adapter.create_session(agent_id, config))

        payload = {"prompt": "test"}
        result = _run(adapter.execute_task(session, task_id, payload))

        assert result.success is True
        # Should extract result text from the result event
        assert result.output == "completed task"
        # Should extract session_id from system event
        assert session.metadata["last_session_id"] == "sess-mix"


class TestCapabilities:
    """Test _get_capabilities includes new capabilities."""

    @pytest.fixture
    def adapter(self):
        """Create a ClaudeCodeAdapter instance."""
        return ClaudeCodeAdapter()

    @pytest.fixture
    def agent_id(self):
        """Fixed agent UUID for tests."""
        return uuid.UUID("abcdef01-abcd-abcd-abcd-abcdef012345")

    def test_capabilities_include_new_features(self, adapter, agent_id):
        """Capabilities list includes stream_json_parsing, session_resume, worktree_isolation."""
        config = {"workspace": "/tmp/test"}
        session = _run(adapter.create_session(agent_id, config))

        caps = _run(adapter.get_capabilities(session))

        assert "stream_json_parsing" in caps
        assert "session_resume" in caps
        assert "worktree_isolation" in caps

    def test_capabilities_include_original_features(self, adapter, agent_id):
        """Capabilities still include all original capability strings."""
        config = {"workspace": "/tmp/test"}
        session = _run(adapter.create_session(agent_id, config))

        caps = _run(adapter.get_capabilities(session))

        assert "execute_task" in caps
        assert "subprocess_execution" in caps
        assert "workspace_isolation" in caps
        assert "file_system_artifacts" in caps
        assert "cost_parsing" in caps
        assert "timeout_handling" in caps
        assert "graceful_termination" in caps


class TestCommandArgOrdering:
    """Test that command args are built in the correct order."""

    @pytest.fixture
    def adapter(self):
        """Create a ClaudeCodeAdapter instance."""
        return ClaudeCodeAdapter()

    @pytest.fixture
    def agent_id(self):
        """Fixed agent UUID for tests."""
        return uuid.UUID("abcdef01-abcd-abcd-abcd-abcdef012345")

    @pytest.fixture
    def task_id(self):
        """Fixed task UUID for tests."""
        return uuid.UUID("99999999-9999-9999-9999-999999999999")

    @patch("asyncio.create_subprocess_exec")
    def test_full_command_with_all_options(
        self, mock_exec, adapter, agent_id, task_id
    ):
        """All options produce correct arg ordering: cmd, format, resume, worktree, extra."""
        mock_process = AsyncMock()
        mock_process.communicate = AsyncMock(
            return_value=(b'{"type":"result","result":"ok"}\n', b"")
        )
        mock_process.returncode = 0
        mock_exec.return_value = mock_process

        config = {"workspace": "/tmp/test_claude"}
        session = _run(adapter.create_session(agent_id, config))

        payload = {
            "prompt": "do everything",
            "resume_session_id": "sess-prev",
            "worktree": True,
            "args": ["--verbose"],
        }
        _run(adapter.execute_task(session, task_id, payload))

        call_args = list(mock_exec.call_args[0])
        # Command should contain: claude -p prompt --output-format stream-json --verbose --resume sess-prev --worktree
        assert call_args[0] == "claude"
        assert "-p" in call_args
        assert "--output-format" in call_args
        assert "stream-json" in call_args
        assert "--resume" in call_args
        assert "sess-prev" in call_args
        assert "--worktree" in call_args
        assert "--verbose" in call_args

        # Verify ordering: format before resume before worktree
        fmt_idx = call_args.index("--output-format")
        resume_idx = call_args.index("--resume")
        worktree_idx = call_args.index("--worktree")
        assert fmt_idx < resume_idx < worktree_idx


def _work_context(work_mode):
    """A server-built task-attempt context, as the runtime hands the adapter."""
    from nexus.tools.context import ExecutionContext

    return ExecutionContext(
        company_id=uuid.uuid4(), principal_id="p", principal_role="agent",
        source="chat", agent_id=uuid.uuid4(), work_mode=work_mode,
    )


def _claude_session(alias, work_mode, config=None):
    """The adapter and session a Claude employee gets for ``alias``, as chat builds them."""
    from nexus.adapters.registry import AdapterRegistry
    from nexus.adapters.uastl import resolve_provider

    key, resolved = resolve_provider(alias, None, connection=None, adapter_config=None)
    adapter = AdapterRegistry().create_adapter(key)
    session_config = {**resolved, "workspace": "/tmp/test_claude_work", **(config or {})}
    session = _run(adapter.create_session(uuid.uuid4(), session_config))
    session.context = _work_context(work_mode) if work_mode else None
    return key, adapter, session


def _spawned(mock_exec, adapter, session, payload):
    """Run one task with a mocked subprocess; return (result, argv or None)."""
    proc = AsyncMock()
    proc.communicate = AsyncMock(return_value=(b'{"type":"result","result":"ok"}\n', b""))
    proc.returncode = 0
    mock_exec.return_value = proc
    result = _run(adapter.execute_task(session, uuid.uuid4(), payload))
    return result, (list(mock_exec.call_args[0]) if mock_exec.call_args else None)


def _claude_backend():
    from nexus.adapters.cli_registry import get_cli_registry

    return get_cli_registry().get_backend("claude")


@pytest.mark.parametrize("alias", ["claude", "claude_code"])
class TestClaudeWorkModeRestrictions:
    """A Claude employee's task attempt runs with the canonical work-mode flags."""

    @pytest.mark.parametrize("work_mode", ["text", "read_only", "write"])
    @patch("asyncio.create_subprocess_exec")
    def test_attempt_gets_exactly_the_canonical_flags(self, mock_exec, alias, work_mode):
        key, adapter, session = _claude_session(alias, work_mode)
        assert key == "claude_code"
        _, argv = _spawned(mock_exec, adapter, session, {"prompt": "hi"})
        canonical = list(_claude_backend().work_mode_args(work_mode))
        assert argv == ["claude", "-p", "hi", "--output-format", "stream-json", "--verbose",
                        *canonical]
        # No manager bridge: a work attempt is offered no governed tool.
        assert "--mcp-config" not in argv and "--strict-mcp-config" not in argv

    @patch("asyncio.create_subprocess_exec")
    def test_text_attempt_is_read_only(self, mock_exec, alias):
        _, adapter, session = _claude_session(alias, "text")
        _, argv = _spawned(mock_exec, adapter, session, {"prompt": "hi"})
        assert argv[-2:] == ["--permission-mode", "plan"]

    @patch("asyncio.create_subprocess_exec")
    def test_safe_extra_args_are_kept_after_the_work_flags(self, mock_exec, alias):
        _, adapter, session = _claude_session(alias, "text")
        _, argv = _spawned(mock_exec, adapter, session,
                           {"prompt": "hi", "args": ["--model", "sonnet"]})
        assert argv[-4:] == ["--permission-mode", "plan", "--model", "sonnet"]

    @pytest.mark.parametrize(
        "override",
        [
            ["--permission-mode", "bypassPermissions"],
            ["--permission-mode=bypassPermissions"],
            ["--PERMISSION-MODE=bypassPermissions"],
            ["--permission=bypassPermissions"],
            ["--perm", "bypassPermissions"],
            ["--allowedTools=Bash(*)"],
            ["--allowedtools", "Bash(*)"],
            ["--allowed=Bash(*)"],
            ["--dangerously-skip-permissions"],
            ["--settings", "x.json"],
            ["--mcp-config", "x.json"],
        ],
    )
    @pytest.mark.parametrize("work_mode", ["text", "write"])
    @patch("asyncio.create_subprocess_exec")
    def test_payload_override_is_refused_before_the_process_starts(
        self, mock_exec, alias, work_mode, override
    ):
        _, adapter, session = _claude_session(alias, work_mode)
        result, _ = _spawned(mock_exec, adapter, session, {"prompt": "hi", "args": override})
        assert result.success is False and result.error
        mock_exec.assert_not_called()

    @patch("asyncio.create_subprocess_exec")
    def test_agent_config_cannot_add_arguments(self, mock_exec, alias):
        """This adapter never reads stored extra args, so config cannot override a flag."""
        config = {"extra_args": ["--permission-mode", "bypassPermissions"]}
        _, adapter, session = _claude_session(alias, "text", config)
        _, argv = _spawned(mock_exec, adapter, session, {"prompt": "hi"})
        assert "bypassPermissions" not in argv
        assert argv.count("--permission-mode") == 1

    @patch("asyncio.create_subprocess_exec")
    def test_unsupported_work_mode_fails_before_the_process_starts(self, mock_exec, alias):
        _, adapter, session = _claude_session(alias, "yolo")
        result, _ = _spawned(mock_exec, adapter, session, {"prompt": "hi"})
        assert result.success is False and "yolo" in result.error
        mock_exec.assert_not_called()

    @patch("asyncio.create_subprocess_exec")
    def test_non_work_run_keeps_its_command(self, mock_exec, alias):
        _, adapter, session = _claude_session(alias, None)
        _, argv = _spawned(mock_exec, adapter, session,
                           {"prompt": "hi", "args": ["--model", "sonnet"]})
        assert argv == ["claude", "-p", "hi", "--output-format", "stream-json", "--verbose",
                        "--model", "sonnet"]

    def test_work_context_has_no_manager_tools_or_bridge(self, alias):
        from nexus.tools import manager_bridge, manager_tools

        ctx = _work_context("text")
        assert _run(manager_tools.catalog(ctx)) == {}
        assert _run(manager_bridge.open_bridge(ctx, uuid.uuid4(), _claude_backend(), 5.0)) is None


class TestClaudeAndCliAdaptersShareTheCatalogue:
    """Both adapters consume the one work-mode catalogue and override check."""

    @pytest.mark.parametrize("work_mode", ["text", "read_only", "write"])
    @patch("asyncio.create_subprocess_exec")
    def test_same_work_flags_from_both_adapters(self, mock_exec, work_mode):
        backend = _claude_backend()
        cli_argv = backend.build_args("hi", work_mode=work_mode)
        canonical = list(backend.work_mode_args(work_mode))
        assert canonical and canonical[0] in cli_argv
        _, adapter, session = _claude_session("claude", work_mode)
        _, argv = _spawned(mock_exec, adapter, session, {"prompt": "hi"})
        assert argv[-len(canonical):] == canonical

    def test_claude_adapter_has_no_flag_list_of_its_own(self):
        import inspect

        src = inspect.getsource(ClaudeCodeAdapter)
        assert "work_mode_args" in src and "refuse_work_flag_override" in src
        assert "plan" not in src and "acceptEdits" not in src

    @patch("asyncio.create_subprocess_exec")
    def test_the_shared_override_check_stops_both_adapters(self, mock_exec):
        from nexus.adapters.cli_adapter import CLIAdapter
        from nexus.adapters.cli_registry import CLIBackendInfo

        def refuse(self, extra_args):
            raise ValueError("shared check ran")

        with patch.object(CLIBackendInfo, "refuse_work_flag_override", refuse):
            _, adapter, session = _claude_session("claude", "text")
            result, _ = _spawned(mock_exec, adapter, session, {"prompt": "hi"})
            assert result.error == "shared check ran"

            cli = CLIAdapter()
            cli_session = _run(cli.create_session(
                uuid.uuid4(), {"backend": "claude", "workspace": "/tmp/test_claude_work"}
            ))
            cli_session.context = _work_context("text")
            cli_result = _run(cli.execute_task(cli_session, uuid.uuid4(), {"prompt": "hi"}))
            assert cli_result.error == "shared check ran"
        mock_exec.assert_not_called()
