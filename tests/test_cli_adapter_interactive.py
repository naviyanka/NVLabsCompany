"""Tests for CLI Adapter interactive stdin protocol.

Tests cover:
- send_message to a running process writes to stdin
- send_message to an exited process raises RuntimeError
- is_interactive flag set from session config
- awaiting_input state tracking
- _stream_output reads lines incrementally and appends to logs
- Broken pipe handling in send_message
"""

import asyncio
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from nexus.adapters.cli_adapter import CLIAdapter
from nexus.runtime.adapter import AgentStatus


def _run(coro):
    """Run an async coroutine synchronously."""
    return asyncio.run(coro)


@pytest.fixture
def adapter():
    """Create a CLIAdapter instance."""
    return CLIAdapter()


@pytest.fixture
def agent_id():
    """Fixed agent UUID for tests."""
    return uuid.UUID("abcdef01-abcd-abcd-abcd-abcdef012345")


@pytest.fixture
def task_id():
    """Fixed task UUID for tests."""
    return uuid.UUID("99999999-9999-9999-9999-999999999999")


class TestIsInteractiveFlag:
    """Test is_interactive flag is set from config during session creation."""

    def test_is_interactive_defaults_to_false(self, adapter, agent_id):
        """is_interactive defaults to False when not specified in config."""
        config = {"backend": "claude", "workspace": "/tmp/test_ws"}
        session = _run(adapter.create_session(agent_id, config))
        assert session.metadata["is_interactive"] is False

    def test_is_interactive_set_true_from_config(self, adapter, agent_id):
        """is_interactive is True when config has interactive=True."""
        config = {
            "backend": "claude",
            "workspace": "/tmp/test_ws",
            "interactive": True,
        }
        session = _run(adapter.create_session(agent_id, config))
        assert session.metadata["is_interactive"] is True

    def test_is_interactive_set_false_explicitly(self, adapter, agent_id):
        """is_interactive is False when config has interactive=False."""
        config = {
            "backend": "claude",
            "workspace": "/tmp/test_ws",
            "interactive": False,
        }
        session = _run(adapter.create_session(agent_id, config))
        assert session.metadata["is_interactive"] is False


class TestAwaitingInputState:
    """Test awaiting_input state tracking in session metadata."""

    def test_awaiting_input_initialized_to_false(self, adapter, agent_id):
        """awaiting_input starts as False after session creation."""
        config = {"backend": "claude", "workspace": "/tmp/test_ws"}
        session = _run(adapter.create_session(agent_id, config))
        assert session.metadata["awaiting_input"] is False

    def test_awaiting_input_can_be_set_externally(self, adapter, agent_id):
        """awaiting_input can be toggled in session metadata."""
        config = {
            "backend": "claude",
            "workspace": "/tmp/test_ws",
            "interactive": True,
        }
        session = _run(adapter.create_session(agent_id, config))

        # Simulate setting awaiting_input to True externally
        session.metadata["awaiting_input"] = True
        assert session.metadata["awaiting_input"] is True

    def test_send_message_resets_awaiting_input(self, adapter, agent_id):
        """send_message sets awaiting_input to False after sending."""
        config = {
            "backend": "claude",
            "workspace": "/tmp/test_ws",
            "interactive": True,
        }
        session = _run(adapter.create_session(agent_id, config))

        # Simulate an active process
        mock_process = MagicMock()
        mock_process.returncode = None
        mock_stdin = AsyncMock()
        mock_stdin.write = MagicMock()
        mock_stdin.drain = AsyncMock()
        mock_process.stdin = mock_stdin
        adapter._processes[session.session_id] = mock_process

        # Set awaiting_input to True
        session.metadata["awaiting_input"] = True

        # Send message should reset it
        result = _run(adapter.send_message(session.session_id, "hello"))
        assert session.metadata["awaiting_input"] is False
        assert "sent" in result.lower()


class TestSendMessage:
    """Test send_message writes to stdin of running process."""

    def test_send_message_to_running_process(self, adapter, agent_id):
        """send_message writes message + newline to process stdin."""
        config = {
            "backend": "claude",
            "workspace": "/tmp/test_ws",
            "interactive": True,
        }
        session = _run(adapter.create_session(agent_id, config))

        # Set up mock process with stdin
        mock_process = MagicMock()
        mock_process.returncode = None
        mock_stdin = AsyncMock()
        mock_stdin.write = MagicMock()
        mock_stdin.drain = AsyncMock()
        mock_process.stdin = mock_stdin
        adapter._processes[session.session_id] = mock_process

        result = _run(adapter.send_message(session.session_id, "test input"))

        # Verify stdin.write was called with encoded message + newline
        mock_stdin.write.assert_called_once_with(b"test input\n")
        mock_stdin.drain.assert_awaited_once()
        assert "Message sent" in result
        assert "10 chars" in result

    def test_send_message_to_exited_process_raises(self, adapter, agent_id):
        """send_message raises RuntimeError if process already exited."""
        config = {
            "backend": "claude",
            "workspace": "/tmp/test_ws",
            "interactive": True,
        }
        session = _run(adapter.create_session(agent_id, config))

        # Set up mock process that has exited
        mock_process = MagicMock()
        mock_process.returncode = 0
        adapter._processes[session.session_id] = mock_process

        with pytest.raises(RuntimeError, match="already exited"):
            _run(adapter.send_message(session.session_id, "hello"))

    def test_send_message_no_process_raises(self, adapter, agent_id):
        """send_message raises RuntimeError if no process is found."""
        config = {
            "backend": "claude",
            "workspace": "/tmp/test_ws",
            "interactive": True,
        }
        session = _run(adapter.create_session(agent_id, config))

        # No process registered for the session
        with pytest.raises(RuntimeError, match="No running process"):
            _run(adapter.send_message(session.session_id, "hello"))

    def test_send_message_broken_pipe(self, adapter, agent_id):
        """send_message raises RuntimeError on BrokenPipeError."""
        config = {
            "backend": "claude",
            "workspace": "/tmp/test_ws",
            "interactive": True,
        }
        session = _run(adapter.create_session(agent_id, config))

        # Set up mock process with stdin that raises BrokenPipeError
        mock_process = MagicMock()
        mock_process.returncode = None
        mock_stdin = AsyncMock()
        mock_stdin.write = MagicMock(side_effect=BrokenPipeError("Broken pipe"))
        mock_process.stdin = mock_stdin
        adapter._processes[session.session_id] = mock_process

        with pytest.raises(RuntimeError, match="Broken pipe"):
            _run(adapter.send_message(session.session_id, "hello"))

    def test_send_message_no_stdin_pipe_raises(self, adapter, agent_id):
        """send_message raises RuntimeError if stdin pipe is None."""
        config = {
            "backend": "claude",
            "workspace": "/tmp/test_ws",
            "interactive": True,
        }
        session = _run(adapter.create_session(agent_id, config))

        # Set up mock process with no stdin pipe
        mock_process = MagicMock()
        mock_process.returncode = None
        mock_process.stdin = None
        adapter._processes[session.session_id] = mock_process

        with pytest.raises(RuntimeError, match="no stdin pipe"):
            _run(adapter.send_message(session.session_id, "hello"))

    def test_send_message_encoding_with_unicode(self, adapter, agent_id):
        """send_message handles unicode characters with errors='replace'."""
        config = {
            "backend": "claude",
            "workspace": "/tmp/test_ws",
            "interactive": True,
        }
        session = _run(adapter.create_session(agent_id, config))

        mock_process = MagicMock()
        mock_process.returncode = None
        mock_stdin = AsyncMock()
        mock_stdin.write = MagicMock()
        mock_stdin.drain = AsyncMock()
        mock_process.stdin = mock_stdin
        adapter._processes[session.session_id] = mock_process

        # Unicode message with special characters
        message = "Hello \u2603 World"
        result = _run(adapter.send_message(session.session_id, message))

        expected_bytes = message.encode("utf-8", errors="replace") + b"\n"
        mock_stdin.write.assert_called_once_with(expected_bytes)
        assert "Message sent" in result


class TestStreamOutput:
    """Test _stream_output reads stdout line-by-line and logs."""

    def test_stream_output_reads_lines(self, adapter, agent_id):
        """_stream_output reads lines from stdout and adds to session logs."""
        config = {
            "backend": "claude",
            "workspace": "/tmp/test_ws",
            "interactive": True,
        }
        session = _run(adapter.create_session(agent_id, config))

        # Create mock process with stdout that returns lines then EOF
        mock_process = MagicMock()
        lines = [b"line one\n", b"line two\n", b"line three\n", b""]
        mock_stdout = AsyncMock()
        mock_stdout.readline = AsyncMock(side_effect=lines)
        mock_process.stdout = mock_stdout

        _run(adapter._stream_output(mock_process, session.session_id))

        # Check that logs contain the output lines
        logs = _run(adapter.get_logs(session))
        stdout_logs = [log for log in logs if "[stdout]" in log]
        assert len(stdout_logs) == 3
        assert any("line one" in log for log in stdout_logs)
        assert any("line two" in log for log in stdout_logs)
        assert any("line three" in log for log in stdout_logs)

    def test_stream_output_handles_empty_stdout(self, adapter, agent_id):
        """_stream_output handles immediate EOF gracefully."""
        config = {
            "backend": "claude",
            "workspace": "/tmp/test_ws",
            "interactive": True,
        }
        session = _run(adapter.create_session(agent_id, config))

        mock_process = MagicMock()
        mock_stdout = AsyncMock()
        mock_stdout.readline = AsyncMock(return_value=b"")
        mock_process.stdout = mock_stdout

        # Should not raise
        _run(adapter._stream_output(mock_process, session.session_id))

        logs = _run(adapter.get_logs(session))
        stdout_logs = [log for log in logs if "[stdout]" in log]
        assert len(stdout_logs) == 0

    def test_stream_output_no_stdout_pipe(self, adapter, agent_id):
        """_stream_output returns immediately if stdout is None."""
        config = {
            "backend": "claude",
            "workspace": "/tmp/test_ws",
            "interactive": True,
        }
        session = _run(adapter.create_session(agent_id, config))

        mock_process = MagicMock()
        mock_process.stdout = None

        # Should not raise or hang
        _run(adapter._stream_output(mock_process, session.session_id))

    def test_stream_output_decodes_with_replace(self, adapter, agent_id):
        """_stream_output decodes bytes with errors='replace' for bad data."""
        config = {
            "backend": "claude",
            "workspace": "/tmp/test_ws",
            "interactive": True,
        }
        session = _run(adapter.create_session(agent_id, config))

        # Create line with invalid UTF-8 bytes
        invalid_line = b"hello \xff\xfe world\n"
        mock_process = MagicMock()
        mock_stdout = AsyncMock()
        mock_stdout.readline = AsyncMock(side_effect=[invalid_line, b""])
        mock_process.stdout = mock_stdout

        _run(adapter._stream_output(mock_process, session.session_id))

        logs = _run(adapter.get_logs(session))
        stdout_logs = [log for log in logs if "[stdout]" in log]
        assert len(stdout_logs) == 1
        # The replacement character should be present for invalid bytes
        assert "hello" in stdout_logs[0]
        assert "world" in stdout_logs[0]


class TestInteractiveCapability:
    """Test that interactive_stdin capability is advertised."""

    def test_capabilities_include_interactive_stdin(self, adapter, agent_id):
        """CLIAdapter advertises interactive_stdin capability."""
        config = {"backend": "claude", "workspace": "/tmp/test_ws"}
        session = _run(adapter.create_session(agent_id, config))

        caps = _run(adapter.get_capabilities(session))
        assert "interactive_stdin" in caps


class TestBackwardCompatibility:
    """Test that existing non-interactive behavior is unchanged."""

    @patch("asyncio.create_subprocess_exec")
    def test_execute_task_still_works(
        self, mock_exec, adapter, agent_id, task_id
    ):
        """Non-interactive execute_task still works as before."""
        mock_process = AsyncMock()
        mock_process.communicate = AsyncMock(
            return_value=(b"Task done\n", b"")
        )
        mock_process.returncode = 0
        mock_exec.return_value = mock_process

        config = {"backend": "claude", "workspace": "/tmp/test_cli"}
        session = _run(adapter.create_session(agent_id, config))

        # Verify non-interactive defaults
        assert session.metadata["is_interactive"] is False
        assert session.metadata["awaiting_input"] is False

        payload = {"prompt": "Write hello world"}
        result = _run(adapter.execute_task(session, task_id, payload))

        assert result.success is True
        assert "Task done" in result.output

    def test_session_without_interactive_config(self, adapter, agent_id):
        """Session creation without interactive config works normally."""
        config = {"backend": "aider", "workspace": "/tmp/test_ws"}
        session = _run(adapter.create_session(agent_id, config))

        assert session.status == AgentStatus.READY
        assert session.metadata["backend"] == "aider"
        assert session.metadata["is_interactive"] is False
        assert session.metadata["awaiting_input"] is False
