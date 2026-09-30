"""The server-built capability catalogue.

Every entry says how (and whether) it is enforced, so the dashboard never shows a working
control for something the backend cannot prevent. Tool entries come from the same registries
the runtime serves (CEO and manager tools, the MCP node registry); nothing is hardcoded
in the dashboard.
"""

from __future__ import annotations

from typing import Any

from nexus.config import settings
from nexus.tools.access import EXPLICIT_ALLOW_ONLY
from nexus.tools.autonomy import (
    ACTION_DELETE,
    ACTION_EXECUTE_CODE,
    ACTION_SEND_EXTERNAL_MESSAGE,
    ACTION_SPEND,
    ACTION_WRITE_FILE,
)

CATEGORIES = ("organization", "tools", "execution", "computer_use", "data", "providers")

# enforced: the ToolPolicy engine allows or denies it (and a grant or lockdown can change that).
# approval_only: the autonomy gate can run, notify or require approval, but not deny.
# display_only: enforced by tenant isolation or RBAC; shown, not configurable here.
# unsupported: nothing prevents it; shown so the gap is visible, with no toggle.
ENFORCED, APPROVAL_ONLY, DISPLAY_ONLY, UNSUPPORTED = (
    "enforced",
    "approval_only",
    "display_only",
    "unsupported",
)

_TOOL_SCOPE = {"conditions": ["risk_level", "tool_name", "agent_id", "time_of_day"]}
_GATE = {"name": "tool_binding_enforcement"}

_AUTONOMY_BUCKETS = (
    (ACTION_DELETE, "Delete data", "high"),
    (ACTION_EXECUTE_CODE, "Execute code", "high"),
    (ACTION_SEND_EXTERNAL_MESSAGE, "Send external messages", "high"),
    (ACTION_WRITE_FILE, "Write files", "write"),
    (ACTION_SPEND, "Spend money", "high"),
)

_COMPUTER_USE = (
    ("browser", "Browser control", "Drive a browser, including signed-in sessions."),
    ("terminal", "Terminal", "Run shell commands on the host."),
    ("filesystem_write", "Filesystem write", "Write files outside the agent workspace."),
    ("desktop", "Desktop control", "Control the desktop through screenshots and input."),
)


def _entry(
    cap_id: str,
    name: str,
    description: str,
    category: str,
    risk: str,
    support: str,
    *,
    tool_name: str | None = None,
    **extra: Any,
) -> dict[str, Any]:
    effect = "read" if risk in ("read", "low") else "write"
    return {
        "id": cap_id,
        "name": name,
        "description": description,
        "category": category,
        "risk": risk,
        "effect_class": effect,
        "tool_name": tool_name,
        "explicit_allow_required": tool_name in EXPLICIT_ALLOW_ONLY,
        "approval_support": support in (ENFORCED, APPROVAL_ONLY),
        "scope_schema": _TOOL_SCOPE if support == ENFORCED else {},
        "backends": {
            ENFORCED: ["tool_policy", "rbac", "governance_overlay"],
            APPROVAL_ONLY: ["autonomy_gate"],
            DISPLAY_ONLY: ["rbac", "tenant_isolation"],
            UNSUPPORTED: [],
        }[support],
        "feature_gates": [_GATE] if support == ENFORCED else [],
        "support": support,
        "toggleable": support == ENFORCED,
        **extra,
    }


def build_catalog() -> list[dict[str, Any]]:
    """All capabilities, in a stable order. Cheap and pure: no database."""
    from nexus.tools.ceo_tools import CEO_TOOLS
    from nexus.tools.manager_tools import MANAGER_TOOLS
    from nexus.tools.mcp_server import exposed_nodes, risk_level_for

    out: list[dict[str, Any]] = []
    for name, tool in sorted({**MANAGER_TOOLS, **CEO_TOOLS}.items()):
        out.append(
            _entry(
                f"org.{name}", name, tool.description, "organization", tool.risk, ENFORCED,
                tool_name=name,
            )
        )
    for node_id, node in sorted(exposed_nodes().items()):
        out.append(
            _entry(
                f"tool.{node_id}", node.name, node.description or "", "tools",
                risk_level_for(node), ENFORCED, tool_name=node_id,
            )
        )
    for bucket, name, risk in _AUTONOMY_BUCKETS:
        out.append(
            _entry(
                f"exec.{bucket}", name,
                "Run, notify an operator, or require approval (L1-L3). Not deniable here.",
                "execution", risk, APPROVAL_ONLY, bucket=bucket,
            )
        )
    for key, name, description in _COMPUTER_USE:
        out.append(
            _entry(
                f"computer.{key}", name,
                f"{description} Not preventable: CLI agents run out of process.",
                "computer_use", "high", UNSUPPORTED,
            )
        )
    out += [
        _entry("data.memory", "Company memory", "Read and write the agent's scoped memory.",
               "data", "write", DISPLAY_ONLY),
        _entry("data.secrets", "Secret references",
               "Use secrets bound to the agent. Values are never shown or returned here.",
               "data", "high", DISPLAY_ONLY),
        _entry("provider.runtime", "Runtime provider", "The CLI or model backend it runs on.",
               "providers", "low", DISPLAY_ONLY),
    ]
    return out


def catalog_by_id() -> dict[str, dict[str, Any]]:
    return {c["id"]: c for c in build_catalog()}


def gate_status() -> dict[str, str]:
    return {"tool_binding_enforcement": settings.tool_binding_enforcement}
