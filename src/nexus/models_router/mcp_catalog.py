"""Gateway MCP tool discovery (WP-22h / M11).

An MCP-capable gateway exposes ``GET /api/mcp/tools`` (management key) listing
the tools it bridges, each ``{name, description, scopes, phase, auditLevel,
sourceEndpoints}``. This discovers them so they can be surfaced in the agent
tools picker and invoked through the existing ``mcp`` adapter — no new adapter.

Fail-open (R12): any transport or parse error returns an empty list and leaves
state untouched. No vendor name here (R9); the endpoint is any Connection.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class GatewayTool:
    """One MCP tool bridged by the gateway."""

    name: str
    description: str
    scopes: tuple[str, ...]
    phase: int | None
    audit_level: str | None


def parse_tools(payload: dict[str, Any]) -> list[GatewayTool]:
    """Map an ``/api/mcp/tools`` response body to GatewayTool records."""
    tools = payload.get("tools", payload) if isinstance(payload, dict) else payload
    out: list[GatewayTool] = []
    for t in tools or []:
        name = t.get("name")
        if not name:
            continue
        out.append(
            GatewayTool(
                name=name,
                description=t.get("description", ""),
                scopes=tuple(t.get("scopes", []) or []),
                phase=t.get("phase"),
                audit_level=t.get("auditLevel"),
            )
        )
    return out


def mcp_url_for(base_url: str) -> str:
    """Derive the MCP stream endpoint from a Connection base_url.

    ``http://host:port/v1`` -> ``http://host:port/api/mcp/stream`` (the ``/v1``
    inference suffix is dropped; the gateway serves MCP under ``/api``).
    """
    root = base_url.rstrip("/")
    if root.endswith("/v1"):
        root = root[: -len("/v1")]
    return f"{root}/api/mcp/stream"


async def discover_tools(base_url: str, mgmt_key: str) -> list[GatewayTool]:
    """Fetch and parse the gateway MCP tool catalog. Fail-open (empty on error).

    Requires the management key: ``/api/mcp/tools`` rejects the inference key.
    """
    import httpx

    root = base_url.rstrip("/")
    if root.endswith("/v1"):
        root = root[: -len("/v1")]
    url = f"{root}/api/mcp/tools"
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(
                url, headers={"Authorization": f"Bearer {mgmt_key}"}
            )
            resp.raise_for_status()
            return parse_tools(resp.json())
    except Exception:
        return []
