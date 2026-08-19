"""MCP Stdio Transport - communicates with MCP servers via subprocess stdin/stdout.

Implements the same logical interface as MCPClient but spawns the MCP server
as a subprocess and exchanges JSON-RPC messages via stdin/stdout pipes instead
of HTTP requests.
"""

import asyncio
import json
import logging
from typing import Any

from nexus.tools.mcp_client import MCPResult, MCPTool

logger = logging.getLogger(__name__)


class StdioMCPTransport:
    """MCP transport that communicates via subprocess stdio.

    Spawns an MCP server as a child process and sends/receives JSON-RPC
    messages as newline-delimited JSON on stdin/stdout.
    """

    def __init__(self, timeout_seconds: float = 30.0) -> None:
        """Initialize the stdio transport.

        Args:
            timeout_seconds: Default timeout for waiting on server responses.
        """
        self._timeout_seconds = timeout_seconds
        self._process: asyncio.subprocess.Process | None = None
        self._request_id: int = 0
        self._connected: bool = False
        self._server_info: dict[str, Any] = {}
        self._tools_cache: list[MCPTool] = []
        self._stderr_task: asyncio.Task[None] | None = None

    @property
    def is_connected(self) -> bool:
        """Whether the transport is currently connected to a server process."""
        return self._connected

    async def connect(
        self,
        command: str,
        args: list[str] | None = None,
        env: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """Spawn an MCP server subprocess and perform initialization.

        Starts the MCP server as a child process and sends the JSON-RPC
        'initialize' request. Parses and stores the server's capabilities.

        Args:
            command: The command to run (e.g., "mcp-server-sqlite").
            args: Optional list of command-line arguments.
            env: Optional environment variables for the subprocess.

        Returns:
            Server information dictionary (name, version, capabilities).

        Raises:
            RuntimeError: If the subprocess cannot be started or initialization fails.
        """
        cmd_args = [command] + (args or [])

        try:
            self._process = await asyncio.create_subprocess_exec(
                *cmd_args,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=env,
            )
        except (OSError, FileNotFoundError) as exc:
            raise RuntimeError(
                f"Failed to spawn MCP server '{command}': {exc}"
            ) from exc

        # Start background task to read stderr
        self._stderr_task = asyncio.create_task(self._read_stderr_task())

        # Send initialize request
        init_params = {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {
                "name": "nexus-mcp-stdio",
                "version": "1.0.0",
            },
        }

        response = await self._send_request("initialize", init_params)

        if "error" in response:
            await self.disconnect()
            raise RuntimeError(f"MCP init error: {response['error']}")

        result = response.get("result", {})
        self._server_info = result.get("serverInfo", {})
        self._connected = True

        return self._server_info

    async def list_tools(self) -> list[MCPTool]:
        """List all tools available on the connected MCP server.

        Returns:
            List of MCPTool objects describing available tools.

        Raises:
            RuntimeError: If not connected or communication fails.
        """
        self._ensure_connected()

        response = await self._send_request("tools/list", {})

        if "error" in response:
            raise RuntimeError(f"MCP tools/list error: {response['error']}")

        result = response.get("result", {})
        tools_data = result.get("tools", [])

        self._tools_cache = [
            MCPTool(
                name=t["name"],
                description=t.get("description", ""),
                input_schema=t.get("inputSchema", {}),
            )
            for t in tools_data
        ]

        return self._tools_cache

    async def call_tool(
        self, tool_name: str, arguments: dict[str, Any]
    ) -> MCPResult:
        """Invoke a tool on the connected MCP server.

        Args:
            tool_name: The name of the tool to invoke.
            arguments: Arguments to pass to the tool.

        Returns:
            An MCPResult with the tool's output.

        Raises:
            RuntimeError: If not connected or the process has exited.
        """
        self._ensure_connected()

        params = {
            "name": tool_name,
            "arguments": arguments,
        }

        response = await self._send_request("tools/call", params)

        if "error" in response:
            return MCPResult(
                content=response["error"].get("message", "Unknown error"),
                is_error=True,
                metadata={"code": response["error"].get("code")},
            )

        result = response.get("result", {})
        content = result.get("content", [])

        # Extract text content from MCP content blocks
        text_parts: list[str] = []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                text_parts.append(block.get("text", ""))
            elif isinstance(block, str):
                text_parts.append(block)

        return MCPResult(
            content="\n".join(text_parts) if text_parts else result,
            is_error=result.get("isError", False),
        )

    async def disconnect(self) -> None:
        """Disconnect from the MCP server and clean up resources.

        Sends SIGTERM to the subprocess, waits briefly, then sends SIGKILL
        if the process has not exited.
        """
        self._connected = False

        if self._stderr_task and not self._stderr_task.done():
            self._stderr_task.cancel()
            try:
                await self._stderr_task
            except asyncio.CancelledError:
                pass
            self._stderr_task = None

        if self._process is not None:
            if self._process.returncode is None:
                # Process still running - try graceful shutdown
                try:
                    self._process.terminate()
                    await asyncio.wait_for(self._process.wait(), timeout=5.0)
                except asyncio.TimeoutError:
                    # Force kill if graceful shutdown failed
                    self._process.kill()
                    await self._process.wait()
                except ProcessLookupError:
                    pass  # Process already exited

            self._process = None

        self._server_info = {}
        self._tools_cache = []

    def health_check(self) -> bool:
        """Check whether the subprocess is still alive.

        Returns:
            True if the process is running, False otherwise.
        """
        if not self._connected or self._process is None:
            return False
        return self._process.returncode is None

    async def _send_request(
        self, method: str, params: dict[str, Any]
    ) -> dict[str, Any]:
        """Send a JSON-RPC request to the subprocess and read the response.

        Writes a newline-terminated JSON message to stdin and reads a
        newline-terminated JSON response from stdout.

        Args:
            method: The JSON-RPC method name.
            params: The request parameters.

        Returns:
            The parsed JSON-RPC response dictionary.

        Raises:
            RuntimeError: If the process is not available or has exited.
            asyncio.TimeoutError: If reading the response times out.
        """
        if self._process is None or self._process.stdin is None:
            raise RuntimeError("MCP server process is not running")

        if self._process.returncode is not None:
            raise RuntimeError(
                f"MCP server process exited with code {self._process.returncode}"
            )

        self._request_id += 1
        request = {
            "jsonrpc": "2.0",
            "id": self._request_id,
            "method": method,
            "params": params,
        }

        # Write request as newline-terminated JSON
        message = json.dumps(request) + "\n"
        self._process.stdin.write(message.encode())
        await self._process.stdin.drain()

        # Read response line with timeout
        if self._process.stdout is None:
            raise RuntimeError("MCP server stdout is not available")

        raw_line = await asyncio.wait_for(
            self._process.stdout.readline(),
            timeout=self._timeout_seconds,
        )

        if not raw_line:
            raise RuntimeError(
                "MCP server closed stdout (process may have exited)"
            )

        return json.loads(raw_line.decode().strip())

    async def _read_stderr_task(self) -> None:
        """Background task that reads stderr and logs output.

        Runs continuously until the process exits or the task is cancelled.
        """
        if self._process is None or self._process.stderr is None:
            return

        try:
            while True:
                line = await self._process.stderr.readline()
                if not line:
                    break
                decoded = line.decode().rstrip()
                if decoded:
                    logger.warning("MCP server stderr: %s", decoded)
        except asyncio.CancelledError:
            pass
        except Exception as exc:
            logger.debug("Stderr reader stopped: %s", exc)

    def _ensure_connected(self) -> None:
        """Raise RuntimeError if not connected to a server."""
        if not self._connected or self._process is None:
            raise RuntimeError("Not connected to an MCP server")
        if self._process.returncode is not None:
            self._connected = False
            raise RuntimeError(
                f"MCP server process exited unexpectedly "
                f"(code {self._process.returncode})"
            )
