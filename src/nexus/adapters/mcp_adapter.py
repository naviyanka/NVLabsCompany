"""MCP Agent Adapter - implements AgentAdapter Protocol via MCP server.

Connects to any MCP (Model Context Protocol) server as the execution
backend, using tool listing for capability discovery and routing task
execution through MCP tool calls.
"""

import importlib
import importlib.util
import pathlib
import sys
import uuid
from typing import Any

from nexus.adapters.base import BaseAdapter
from nexus.runtime.adapter import AgentSession, TaskResult

# Import MCP client directly from module file to avoid triggering
# nexus.tools.__init__.py which may have heavy dependencies.
if "nexus.tools.mcp_client" not in sys.modules:
    _mcp_path = (
        pathlib.Path(__file__).parent.parent / "tools" / "mcp_client.py"
    )
    _spec = importlib.util.spec_from_file_location(
        "nexus.tools.mcp_client", str(_mcp_path)
    )
    if _spec and _spec.loader:
        _module = importlib.util.module_from_spec(_spec)
        sys.modules["nexus.tools.mcp_client"] = _module
        _spec.loader.exec_module(_module)

from nexus.tools.mcp_client import MCPClient, MCPResult, MCPTool


class MCPAgentAdapter(BaseAdapter):
    """Agent adapter that connects to MCP servers for task execution.

    Implements the full AgentAdapter Protocol by using the MCPClient to
    connect to MCP servers, discover available tools, and route task
    execution through MCP tool calls. Supports multi-tool orchestration
    within a single task.
    """

    adapter_type: str = "mcp"

    def __init__(self) -> None:
        """Initialize the MCP agent adapter."""
        super().__init__()
        self._clients: dict[str, MCPClient] = {}
        self._tools_cache: dict[str, list[MCPTool]] = {}

    def validate_config(self, config: dict[str, Any]) -> None:
        """Validate that required MCP configuration keys are present.

        Args:
            config: Configuration dictionary.

        Raises:
            ValueError: If 'server_url' is missing.
        """
        if "server_url" not in config:
            raise ValueError("MCP adapter requires 'server_url' in config")

    async def _do_create_session(self, session: AgentSession) -> None:
        """Initialize MCP session by connecting to the server.

        Connects to the MCP server, performs initialization handshake,
        and discovers available tools.

        Args:
            session: The newly created session.
        """
        server_url = session.config["server_url"]
        timeout = session.config.get("timeout", 30.0)

        client = MCPClient(timeout_seconds=timeout)
        try:
            server_info = await client.connect(server_url)
            session.metadata["server_info"] = server_info
            session.metadata["server_url"] = server_url

            # Discover available tools
            tools = await client.list_tools()
            self._tools_cache[session.session_id] = tools
            session.metadata["available_tools"] = [
                {"name": t.name, "description": t.description}
                for t in tools
            ]

            self._clients[session.session_id] = client
            self._add_log(
                session.session_id,
                f"Connected to MCP server: {server_info}. "
                f"Discovered {len(tools)} tools.",
            )
        except Exception as e:
            self._add_log(
                session.session_id,
                f"Failed to connect to MCP server: {e}",
            )
            raise

    async def _do_execute(
        self, session: AgentSession, task_id: uuid.UUID, payload: dict[str, Any]
    ) -> TaskResult:
        """Execute a task by calling tools on the MCP server.

        Supports single tool call or multi-tool orchestration based on
        the payload format.

        Args:
            session: The active agent session.
            task_id: The task identifier.
            payload: Must contain 'tool_name' and 'arguments', OR 'tool_calls'
                     list for multi-tool orchestration.

        Returns:
            TaskResult with the tool execution results.
        """
        client = self._clients.get(session.session_id)
        if not client or not client.is_connected:
            return TaskResult(
                task_id=task_id,
                agent_id=session.agent_id,
                success=False,
                error="MCP client not connected",
            )

        # Determine if single or multi-tool execution
        tool_calls = payload.get("tool_calls", None)
        if tool_calls is None:
            # Single tool call
            tool_name = payload.get("tool_name", "")
            arguments = payload.get("arguments", {})
            if not tool_name:
                return TaskResult(
                    task_id=task_id,
                    agent_id=session.agent_id,
                    success=False,
                    error="Payload must contain 'tool_name' or 'tool_calls'",
                )
            tool_calls = [{"tool_name": tool_name, "arguments": arguments}]

        # Execute tool calls sequentially
        results: list[dict[str, Any]] = []
        all_success = True
        combined_output: list[str] = []

        for call in tool_calls:
            tool_name = call.get("tool_name", "")
            arguments = call.get("arguments", {})

            self._add_log(
                session.session_id,
                f"Calling MCP tool: {tool_name}({arguments})",
            )

            try:
                result: MCPResult = await client.call_tool(tool_name, arguments)

                results.append({
                    "tool_name": tool_name,
                    "content": result.content,
                    "is_error": result.is_error,
                    "metadata": result.metadata,
                })

                if result.is_error:
                    all_success = False
                    combined_output.append(
                        f"[{tool_name}] ERROR: {result.content}"
                    )
                else:
                    combined_output.append(
                        f"[{tool_name}] {result.content}"
                    )

            except Exception as e:
                all_success = False
                results.append({
                    "tool_name": tool_name,
                    "content": str(e),
                    "is_error": True,
                    "metadata": {},
                })
                combined_output.append(
                    f"[{tool_name}] EXCEPTION: {e}"
                )

        artifacts = [
            {"type": "mcp_tool_result", **r} for r in results
        ]

        return TaskResult(
            task_id=task_id,
            agent_id=session.agent_id,
            success=all_success,
            output="\n".join(combined_output),
            error=None if all_success else "One or more tool calls failed",
            artifacts=artifacts,
            logs=[f"Executed {len(tool_calls)} MCP tool call(s)"],
        )

    async def _do_heartbeat(self, session: AgentSession) -> bool:
        """Check if the MCP server connection is alive.

        Args:
            session: The active agent session.

        Returns:
            True if the MCP client is still connected.
        """
        client = self._clients.get(session.session_id)
        if client:
            return client.is_connected
        return False

    async def _do_terminate(self, session: AgentSession) -> None:
        """Disconnect from the MCP server and clean up resources.

        Args:
            session: The session being terminated.
        """
        client = self._clients.pop(session.session_id, None)
        if client and client.is_connected:
            await client.disconnect()
        self._tools_cache.pop(session.session_id, None)
        self._conversation_history.pop(session.session_id, None)

    def _get_capabilities(self) -> list[str]:
        """Return MCP adapter capabilities.

        Returns:
            List of supported capability identifiers.
        """
        return [
            "execute_task",
            "mcp_protocol",
            "tool_discovery",
            "multi_tool_orchestration",
            "dynamic_capabilities",
        ]

    async def get_available_tools(
        self, session: AgentSession
    ) -> list[dict[str, Any]]:
        """Get the list of tools available on the connected MCP server.

        Args:
            session: The active agent session.

        Returns:
            List of tool metadata dictionaries.
        """
        tools = self._tools_cache.get(session.session_id, [])
        return [
            {
                "name": t.name,
                "description": t.description,
                "input_schema": t.input_schema,
            }
            for t in tools
        ]
