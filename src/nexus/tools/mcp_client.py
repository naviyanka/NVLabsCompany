"""MCP Client - implements the Model Context Protocol for tool communication."""

import uuid
from dataclasses import dataclass, field
from typing import Any


@dataclass
class MCPTool:
    """A tool discovered via the MCP protocol.

    Attributes:
        name: The tool's name as reported by the server.
        description: Human-readable description.
        input_schema: JSON Schema for the tool's parameters.
    """

    name: str
    description: str = ""
    input_schema: dict[str, Any] = field(default_factory=dict)


@dataclass
class MCPResult:
    """Result of an MCP tool invocation.

    Attributes:
        content: The result content (text or structured data).
        is_error: Whether the invocation resulted in an error.
        metadata: Additional server-provided metadata.
    """

    content: Any = None
    is_error: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)


class MCPClient:
    """Client for the Model Context Protocol (MCP).

    Provides methods to connect to an MCP server, discover available
    tools, invoke them, and manage the connection lifecycle.
    """

    def __init__(self, timeout_seconds: float = 30.0) -> None:
        """Initialize the MCP client.

        Args:
            timeout_seconds: Default timeout for server communications.
        """
        self._timeout_seconds = timeout_seconds
        self._server_url: str | None = None
        self._session_id: str | None = None
        self._connected = False
        self._server_info: dict[str, Any] = {}
        self._tools_cache: list[MCPTool] = []

    @property
    def is_connected(self) -> bool:
        """Whether the client is currently connected to a server."""
        return self._connected

    async def connect(self, server_url: str) -> dict[str, Any]:
        """Connect to an MCP server and perform initialization.

        Sends the initialize request and processes the server's capabilities.

        Args:
            server_url: The URL of the MCP server to connect to.

        Returns:
            Server information dictionary (name, version, capabilities).

        Raises:
            RuntimeError: If connection or initialization fails.
        """
        import httpx

        self._server_url = server_url.rstrip("/")

        # Send initialize request (MCP protocol)
        init_payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {
                    "name": "nexus-mcp-client",
                    "version": "1.0.0",
                },
            },
        }

        async with httpx.AsyncClient(timeout=self._timeout_seconds) as client:
            response = await client.post(
                f"{self._server_url}/mcp",
                json=init_payload,
            )

            if response.status_code != 200:
                raise RuntimeError(
                    f"MCP connection failed: {response.status_code} {response.text}"
                )

            data = response.json()
            if "error" in data:
                raise RuntimeError(f"MCP init error: {data['error']}")

            result = data.get("result", {})
            self._server_info = result.get("serverInfo", {})
            self._session_id = str(uuid.uuid4())
            self._connected = True

            return self._server_info

    async def list_tools(self) -> list[MCPTool]:
        """List all tools available on the connected MCP server.

        Returns:
            List of MCPTool objects describing available tools.

        Raises:
            RuntimeError: If not connected or request fails.
        """
        if not self._connected or not self._server_url:
            raise RuntimeError("Not connected to an MCP server")

        import httpx

        payload = {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/list",
            "params": {},
        }

        async with httpx.AsyncClient(timeout=self._timeout_seconds) as client:
            response = await client.post(
                f"{self._server_url}/mcp",
                json=payload,
            )

            if response.status_code != 200:
                raise RuntimeError(
                    f"MCP tools/list failed: {response.status_code}"
                )

            data = response.json()
            if "error" in data:
                raise RuntimeError(f"MCP tools/list error: {data['error']}")

            result = data.get("result", {})
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
            RuntimeError: If not connected or invocation fails.
        """
        if not self._connected or not self._server_url:
            raise RuntimeError("Not connected to an MCP server")

        import httpx

        payload = {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {
                "name": tool_name,
                "arguments": arguments,
            },
        }

        async with httpx.AsyncClient(timeout=self._timeout_seconds) as client:
            response = await client.post(
                f"{self._server_url}/mcp",
                json=payload,
            )

            if response.status_code != 200:
                return MCPResult(
                    content=f"HTTP error: {response.status_code}",
                    is_error=True,
                )

            data = response.json()
            if "error" in data:
                return MCPResult(
                    content=data["error"].get("message", "Unknown error"),
                    is_error=True,
                    metadata={"code": data["error"].get("code")},
                )

            result = data.get("result", {})
            content = result.get("content", [])

            # Extract text content from MCP content blocks
            text_parts = []
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
        """Disconnect from the MCP server and clean up resources."""
        self._connected = False
        self._server_url = None
        self._session_id = None
        self._tools_cache = []
        self._server_info = {}
