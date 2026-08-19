"""Tests for MCP Stdio Transport.

Tests cover:
- connect spawns subprocess and sends initialize
- list_tools parses tool response from stdout
- call_tool sends correct JSON-RPC and parses MCPResult
- disconnect kills subprocess
- timeout handling when readline takes too long
- error handling when process exits unexpectedly
- health_check returns True when process alive, False when dead
"""

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from nexus.tools.mcp_client import MCPResult, MCPTool
from nexus.tools.mcp_stdio import StdioMCPTransport


def _make_jsonrpc_response(result: dict, request_id: int = 1) -> bytes:
    """Create a newline-terminated JSON-RPC response."""
    resp = {"jsonrpc": "2.0", "id": request_id, "result": result}
    return (json.dumps(resp) + "\n").encode()


def _make_jsonrpc_error(
    code: int, message: str, request_id: int = 1
) -> bytes:
    """Create a newline-terminated JSON-RPC error response."""
    resp = {
        "jsonrpc": "2.0",
        "id": request_id,
        "error": {"code": code, "message": message},
    }
    return (json.dumps(resp) + "\n").encode()


def _mock_process(
    stdout_lines: list[bytes] | None = None,
    returncode: int | None = None,
) -> MagicMock:
    """Create a mock subprocess with configurable stdout responses."""
    process = MagicMock()
    process.returncode = returncode
    process.pid = 12345

    # stdin mock
    process.stdin = MagicMock()
    process.stdin.write = MagicMock()
    process.stdin.drain = AsyncMock()

    # stdout mock
    process.stdout = MagicMock()
    if stdout_lines:
        process.stdout.readline = AsyncMock(side_effect=stdout_lines)
    else:
        process.stdout.readline = AsyncMock(return_value=b"")

    # stderr mock - returns empty to end the background task
    process.stderr = MagicMock()
    process.stderr.readline = AsyncMock(return_value=b"")

    # Process lifecycle
    process.terminate = MagicMock()
    process.kill = MagicMock()
    process.wait = AsyncMock(return_value=0)

    return process


class TestStdioMCPTransportConnect:
    """Test StdioMCPTransport.connect()."""

    @patch("nexus.tools.mcp_stdio.asyncio.create_subprocess_exec")
    async def test_connect_spawns_subprocess_and_initializes(
        self, mock_create_subprocess
    ):
        """connect() spawns subprocess and sends initialize request."""
        init_response = _make_jsonrpc_response(
            {
                "serverInfo": {"name": "test-server", "version": "1.0.0"},
                "capabilities": {"tools": {}},
            }
        )
        process = _mock_process(stdout_lines=[init_response])
        mock_create_subprocess.return_value = process

        transport = StdioMCPTransport(timeout_seconds=5.0)
        server_info = await transport.connect("mcp-server", args=["--db", "test.db"])

        # Verify subprocess was spawned with correct args
        mock_create_subprocess.assert_called_once_with(
            "mcp-server",
            "--db",
            "test.db",
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=None,
        )

        # Verify initialize was sent
        assert process.stdin.write.call_count == 1
        written = process.stdin.write.call_args[0][0]
        request = json.loads(written.decode())
        assert request["method"] == "initialize"
        assert request["params"]["protocolVersion"] == "2024-11-05"
        assert request["id"] == 1

        # Verify server info returned
        assert server_info == {"name": "test-server", "version": "1.0.0"}
        assert transport.is_connected is True

        await transport.disconnect()

    @patch("nexus.tools.mcp_stdio.asyncio.create_subprocess_exec")
    async def test_connect_with_env(self, mock_create_subprocess):
        """connect() passes environment variables to subprocess."""
        init_response = _make_jsonrpc_response({"serverInfo": {}})
        process = _mock_process(stdout_lines=[init_response])
        mock_create_subprocess.return_value = process

        transport = StdioMCPTransport()
        env = {"API_KEY": "secret123"}
        await transport.connect("mcp-server", env=env)

        mock_create_subprocess.assert_called_once_with(
            "mcp-server",
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
        )

        await transport.disconnect()

    @patch("nexus.tools.mcp_stdio.asyncio.create_subprocess_exec")
    async def test_connect_raises_on_spawn_failure(self, mock_create_subprocess):
        """connect() raises RuntimeError when subprocess fails to start."""
        mock_create_subprocess.side_effect = FileNotFoundError(
            "No such file: mcp-server"
        )

        transport = StdioMCPTransport()
        with pytest.raises(RuntimeError, match="Failed to spawn MCP server"):
            await transport.connect("mcp-server")

        assert transport.is_connected is False

    @patch("nexus.tools.mcp_stdio.asyncio.create_subprocess_exec")
    async def test_connect_raises_on_init_error(self, mock_create_subprocess):
        """connect() raises RuntimeError when server returns an error."""
        error_response = _make_jsonrpc_error(-32600, "Invalid request")
        process = _mock_process(stdout_lines=[error_response])
        mock_create_subprocess.return_value = process

        transport = StdioMCPTransport()
        with pytest.raises(RuntimeError, match="MCP init error"):
            await transport.connect("mcp-server")

        assert transport.is_connected is False


class TestStdioMCPTransportListTools:
    """Test StdioMCPTransport.list_tools()."""

    @patch("nexus.tools.mcp_stdio.asyncio.create_subprocess_exec")
    async def test_list_tools_parses_response(self, mock_create_subprocess):
        """list_tools() returns a list of MCPTool objects."""
        init_response = _make_jsonrpc_response({"serverInfo": {}})
        tools_response = _make_jsonrpc_response(
            {
                "tools": [
                    {
                        "name": "query_db",
                        "description": "Run a SQL query",
                        "inputSchema": {
                            "type": "object",
                            "properties": {
                                "sql": {"type": "string"}
                            },
                        },
                    },
                    {
                        "name": "list_tables",
                        "description": "List all tables",
                        "inputSchema": {"type": "object"},
                    },
                ]
            },
            request_id=2,
        )
        process = _mock_process(stdout_lines=[init_response, tools_response])
        mock_create_subprocess.return_value = process

        transport = StdioMCPTransport()
        await transport.connect("mcp-server")
        tools = await transport.list_tools()

        assert len(tools) == 2
        assert isinstance(tools[0], MCPTool)
        assert tools[0].name == "query_db"
        assert tools[0].description == "Run a SQL query"
        assert tools[0].input_schema["type"] == "object"
        assert tools[1].name == "list_tables"

        await transport.disconnect()

    @patch("nexus.tools.mcp_stdio.asyncio.create_subprocess_exec")
    async def test_list_tools_raises_when_not_connected(
        self, mock_create_subprocess
    ):
        """list_tools() raises RuntimeError if not connected."""
        transport = StdioMCPTransport()
        with pytest.raises(RuntimeError, match="Not connected"):
            await transport.list_tools()

    @patch("nexus.tools.mcp_stdio.asyncio.create_subprocess_exec")
    async def test_list_tools_raises_on_error_response(
        self, mock_create_subprocess
    ):
        """list_tools() raises RuntimeError on JSON-RPC error."""
        init_response = _make_jsonrpc_response({"serverInfo": {}})
        error_response = _make_jsonrpc_error(-32601, "Method not found")
        process = _mock_process(
            stdout_lines=[init_response, error_response]
        )
        mock_create_subprocess.return_value = process

        transport = StdioMCPTransport()
        await transport.connect("mcp-server")

        with pytest.raises(RuntimeError, match="tools/list error"):
            await transport.list_tools()

        await transport.disconnect()


class TestStdioMCPTransportCallTool:
    """Test StdioMCPTransport.call_tool()."""

    @patch("nexus.tools.mcp_stdio.asyncio.create_subprocess_exec")
    async def test_call_tool_sends_correct_jsonrpc(self, mock_create_subprocess):
        """call_tool() sends correct JSON-RPC request and parses result."""
        init_response = _make_jsonrpc_response({"serverInfo": {}})
        call_response = _make_jsonrpc_response(
            {
                "content": [
                    {"type": "text", "text": "Query executed: 5 rows returned"}
                ],
                "isError": False,
            },
            request_id=2,
        )
        process = _mock_process(stdout_lines=[init_response, call_response])
        mock_create_subprocess.return_value = process

        transport = StdioMCPTransport()
        await transport.connect("mcp-server")
        result = await transport.call_tool(
            "query_db", {"sql": "SELECT * FROM users"}
        )

        # Verify the call_tool request was written
        assert process.stdin.write.call_count == 2
        call_written = process.stdin.write.call_args_list[1][0][0]
        call_request = json.loads(call_written.decode())
        assert call_request["method"] == "tools/call"
        assert call_request["params"]["name"] == "query_db"
        assert call_request["params"]["arguments"] == {
            "sql": "SELECT * FROM users"
        }
        assert call_request["id"] == 2

        # Verify MCPResult
        assert isinstance(result, MCPResult)
        assert result.content == "Query executed: 5 rows returned"
        assert result.is_error is False

        await transport.disconnect()

    @patch("nexus.tools.mcp_stdio.asyncio.create_subprocess_exec")
    async def test_call_tool_handles_error_response(
        self, mock_create_subprocess
    ):
        """call_tool() returns MCPResult with is_error=True on JSON-RPC error."""
        init_response = _make_jsonrpc_response({"serverInfo": {}})
        error_response = _make_jsonrpc_error(-32000, "Tool execution failed")
        process = _mock_process(
            stdout_lines=[init_response, error_response]
        )
        mock_create_subprocess.return_value = process

        transport = StdioMCPTransport()
        await transport.connect("mcp-server")
        result = await transport.call_tool("bad_tool", {})

        assert isinstance(result, MCPResult)
        assert result.is_error is True
        assert "Tool execution failed" in result.content
        assert result.metadata["code"] == -32000

        await transport.disconnect()

    @patch("nexus.tools.mcp_stdio.asyncio.create_subprocess_exec")
    async def test_call_tool_raises_when_not_connected(
        self, mock_create_subprocess
    ):
        """call_tool() raises RuntimeError if not connected."""
        transport = StdioMCPTransport()
        with pytest.raises(RuntimeError, match="Not connected"):
            await transport.call_tool("test", {})


class TestStdioMCPTransportDisconnect:
    """Test StdioMCPTransport.disconnect()."""

    @patch("nexus.tools.mcp_stdio.asyncio.create_subprocess_exec")
    async def test_disconnect_terminates_process(self, mock_create_subprocess):
        """disconnect() sends SIGTERM and waits for process to exit."""
        init_response = _make_jsonrpc_response({"serverInfo": {}})
        process = _mock_process(stdout_lines=[init_response])
        mock_create_subprocess.return_value = process

        transport = StdioMCPTransport()
        await transport.connect("mcp-server")
        assert transport.is_connected is True

        await transport.disconnect()

        process.terminate.assert_called_once()
        assert transport.is_connected is False

    @patch("nexus.tools.mcp_stdio.asyncio.create_subprocess_exec")
    async def test_disconnect_force_kills_on_timeout(
        self, mock_create_subprocess
    ):
        """disconnect() force kills if SIGTERM does not work within timeout."""
        init_response = _make_jsonrpc_response({"serverInfo": {}})
        process = _mock_process(stdout_lines=[init_response])
        # First call (after terminate) times out, second call (after kill) succeeds
        process.wait = AsyncMock(
            side_effect=[asyncio.TimeoutError, 0]
        )
        mock_create_subprocess.return_value = process

        transport = StdioMCPTransport()
        await transport.connect("mcp-server")

        await transport.disconnect()

        process.terminate.assert_called_once()
        process.kill.assert_called_once()

    @patch("nexus.tools.mcp_stdio.asyncio.create_subprocess_exec")
    async def test_disconnect_handles_already_exited(
        self, mock_create_subprocess
    ):
        """disconnect() handles the case where process already exited."""
        init_response = _make_jsonrpc_response({"serverInfo": {}})
        process = _mock_process(stdout_lines=[init_response])
        mock_create_subprocess.return_value = process

        transport = StdioMCPTransport()
        await transport.connect("mcp-server")

        # Simulate process already exited after connect
        process.returncode = 0

        await transport.disconnect()

        # Should not try to terminate since it already exited
        process.terminate.assert_not_called()

    @patch("nexus.tools.mcp_stdio.asyncio.create_subprocess_exec")
    async def test_disconnect_when_not_connected(self, mock_create_subprocess):
        """disconnect() is safe to call when not connected."""
        transport = StdioMCPTransport()
        # Should not raise
        await transport.disconnect()


class TestStdioMCPTransportTimeout:
    """Test timeout handling."""

    @patch("nexus.tools.mcp_stdio.asyncio.create_subprocess_exec")
    async def test_timeout_on_readline(self, mock_create_subprocess):
        """_send_request raises TimeoutError when readline is too slow."""
        # Simulate a hanging readline
        async def slow_readline():
            await asyncio.sleep(10)
            return b""

        process = _mock_process()
        process.stdout.readline = slow_readline
        mock_create_subprocess.return_value = process

        transport = StdioMCPTransport(timeout_seconds=0.1)
        # Manually set up state as if we're partially connected
        transport._process = process
        transport._connected = True

        with pytest.raises(asyncio.TimeoutError):
            await transport._send_request("test/method", {})

    @patch("nexus.tools.mcp_stdio.asyncio.create_subprocess_exec")
    async def test_connect_timeout(self, mock_create_subprocess):
        """connect() raises TimeoutError when server does not respond."""

        async def slow_readline():
            await asyncio.sleep(10)
            return b""

        process = _mock_process()
        process.stdout.readline = slow_readline
        # stderr also needs to not block forever
        process.stderr.readline = AsyncMock(return_value=b"")
        mock_create_subprocess.return_value = process

        transport = StdioMCPTransport(timeout_seconds=0.1)

        with pytest.raises(asyncio.TimeoutError):
            await transport.connect("slow-server")


class TestStdioMCPTransportErrorHandling:
    """Test error handling for unexpected process exits."""

    @patch("nexus.tools.mcp_stdio.asyncio.create_subprocess_exec")
    async def test_send_request_raises_when_process_exited(
        self, mock_create_subprocess
    ):
        """_send_request raises RuntimeError when process has exited."""
        init_response = _make_jsonrpc_response({"serverInfo": {}})
        process = _mock_process(stdout_lines=[init_response])
        mock_create_subprocess.return_value = process

        transport = StdioMCPTransport()
        await transport.connect("mcp-server")

        # Simulate process exit
        process.returncode = 1

        with pytest.raises(RuntimeError, match="exited with code 1"):
            await transport._send_request("tools/list", {})

    @patch("nexus.tools.mcp_stdio.asyncio.create_subprocess_exec")
    async def test_send_request_raises_on_empty_stdout(
        self, mock_create_subprocess
    ):
        """_send_request raises RuntimeError when stdout is closed."""
        init_response = _make_jsonrpc_response({"serverInfo": {}})
        process = _mock_process(stdout_lines=[init_response, b""])
        mock_create_subprocess.return_value = process

        transport = StdioMCPTransport()
        await transport.connect("mcp-server")

        with pytest.raises(RuntimeError, match="closed stdout"):
            await transport._send_request("tools/list", {})

    @patch("nexus.tools.mcp_stdio.asyncio.create_subprocess_exec")
    async def test_ensure_connected_raises_on_unexpected_exit(
        self, mock_create_subprocess
    ):
        """_ensure_connected raises when process exited unexpectedly."""
        init_response = _make_jsonrpc_response({"serverInfo": {}})
        process = _mock_process(stdout_lines=[init_response])
        mock_create_subprocess.return_value = process

        transport = StdioMCPTransport()
        await transport.connect("mcp-server")

        # Simulate unexpected exit
        process.returncode = 137

        with pytest.raises(RuntimeError, match="exited unexpectedly"):
            await transport.list_tools()

        assert transport.is_connected is False


class TestStdioMCPTransportHealthCheck:
    """Test health_check() method."""

    @patch("nexus.tools.mcp_stdio.asyncio.create_subprocess_exec")
    async def test_health_check_true_when_running(self, mock_create_subprocess):
        """health_check() returns True when subprocess is alive."""
        init_response = _make_jsonrpc_response({"serverInfo": {}})
        process = _mock_process(stdout_lines=[init_response])
        mock_create_subprocess.return_value = process

        transport = StdioMCPTransport()
        await transport.connect("mcp-server")

        assert transport.health_check() is True

        await transport.disconnect()

    @patch("nexus.tools.mcp_stdio.asyncio.create_subprocess_exec")
    async def test_health_check_false_when_dead(self, mock_create_subprocess):
        """health_check() returns False when subprocess has exited."""
        init_response = _make_jsonrpc_response({"serverInfo": {}})
        process = _mock_process(stdout_lines=[init_response])
        mock_create_subprocess.return_value = process

        transport = StdioMCPTransport()
        await transport.connect("mcp-server")

        # Simulate process death
        process.returncode = 1

        assert transport.health_check() is False

        await transport.disconnect()

    def test_health_check_false_when_not_connected(self):
        """health_check() returns False when not connected."""
        transport = StdioMCPTransport()
        assert transport.health_check() is False

    @patch("nexus.tools.mcp_stdio.asyncio.create_subprocess_exec")
    async def test_health_check_false_after_disconnect(
        self, mock_create_subprocess
    ):
        """health_check() returns False after disconnect."""
        init_response = _make_jsonrpc_response({"serverInfo": {}})
        process = _mock_process(stdout_lines=[init_response])
        mock_create_subprocess.return_value = process

        transport = StdioMCPTransport()
        await transport.connect("mcp-server")
        await transport.disconnect()

        assert transport.health_check() is False


class TestStdioMCPTransportRequestIds:
    """Test monotonically increasing request IDs."""

    @patch("nexus.tools.mcp_stdio.asyncio.create_subprocess_exec")
    async def test_request_ids_increment(self, mock_create_subprocess):
        """Request IDs increase monotonically with each request."""
        init_response = _make_jsonrpc_response({"serverInfo": {}})
        tools_response = _make_jsonrpc_response({"tools": []}, request_id=2)
        call_response = _make_jsonrpc_response(
            {"content": [{"type": "text", "text": "ok"}]},
            request_id=3,
        )
        process = _mock_process(
            stdout_lines=[init_response, tools_response, call_response]
        )
        mock_create_subprocess.return_value = process

        transport = StdioMCPTransport()
        await transport.connect("mcp-server")
        await transport.list_tools()
        await transport.call_tool("test", {})

        # Check that IDs were 1, 2, 3
        calls = process.stdin.write.call_args_list
        ids = [json.loads(c[0][0].decode())["id"] for c in calls]
        assert ids == [1, 2, 3]

        await transport.disconnect()
