"""Tool Registry - unified tool interface with MCP protocol support and permission-based access."""

from nexus.tools.registry import ToolRegistry, ToolDefinition
from nexus.tools.obsidian import (
    OBSIDIAN_NOTE_REPLACE_NAME,
    OBSIDIAN_NOTE_REPLACE_SCHEMA,
    ObsidianNoteReplaceResult,
    ObsidianToolExecutionError,
    ObsidianNoteReplaceTool,
    obsidian_note_replace_tool_id,
    register_obsidian_note_replace,
)
from nexus.tools.mcp_client import MCPClient
from nexus.tools.executor import ToolExecutor, ToolResult
from nexus.tools.factory import (
    build_autonomy_gate,
    build_guardrail_chain,
    build_tool_executor,
)
from nexus.tools.autonomy import (
    AutonomyDecision,
    AutonomyGate,
    classify_action,
    correlation_id,
    db_policy_loader,
)
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
    "OBSIDIAN_NOTE_REPLACE_NAME",
    "OBSIDIAN_NOTE_REPLACE_SCHEMA",
    "ObsidianNoteReplaceResult",
    "ObsidianToolExecutionError",
    "ObsidianNoteReplaceTool",
    "obsidian_note_replace_tool_id",
    "register_obsidian_note_replace",
    "MCPClient",
    "ToolExecutor",
    "ToolResult",
    "build_autonomy_gate",
    "build_guardrail_chain",
    "build_tool_executor",
    "AutonomyDecision",
    "AutonomyGate",
    "classify_action",
    "correlation_id",
    "db_policy_loader",
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
