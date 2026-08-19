"""Tool Registry - unified tool interface with MCP protocol support and permission-based access."""

from nexus.tools.registry import ToolRegistry, ToolDefinition
from nexus.tools.mcp_client import MCPClient
from nexus.tools.executor import ToolExecutor, ToolResult
from nexus.tools.tool_catalog import (
    ToolKind,
    ToolSpec,
    BASE_TOOLS,
    tool_catalog,
    probe_tool,
    get_setup_status,
)

__all__ = [
    "ToolRegistry",
    "ToolDefinition",
    "MCPClient",
    "ToolExecutor",
    "ToolResult",
    "ToolKind",
    "ToolSpec",
    "BASE_TOOLS",
    "tool_catalog",
    "probe_tool",
    "get_setup_status",
]
