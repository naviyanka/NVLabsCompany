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
from nexus.tools.skills_discovery import (
    LocalSkill,
    parse_skill_frontmatter,
    scan_skill_dir,
    list_local_skills,
)
from nexus.tools.skills_catalog import (
    CatalogSkill,
    CATALOG_URL,
    CATALOG_TTL_SECONDS,
    parse_catalog_markdown,
    load_catalog,
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
    "LocalSkill",
    "parse_skill_frontmatter",
    "scan_skill_dir",
    "list_local_skills",
    "CatalogSkill",
    "CATALOG_URL",
    "CATALOG_TTL_SECONDS",
    "parse_catalog_markdown",
    "load_catalog",
]
