"""WP-22h / M11: gateway MCP tool discovery.

Discovers the tools an MCP-capable gateway bridges (GET /api/mcp/tools,
management key) so they can be surfaced and invoked through the existing mcp
adapter. R1: tests invoke the parser/url-deriver/discovery. R10: discovery is
tested against httpx.MockTransport; no network.
"""

import httpx

from nexus.models_router.mcp_catalog import (
    discover_tools,
    mcp_url_for,
    parse_tools,
)

# Shape verified live against the gateway /api/mcp/tools (45 tools).
_PAYLOAD = {
    "total": 2,
    "mappedTotal": 2,
    "tools": [
        {
            "name": "omniroute_tool_search",
            "description": "Search MCP tools.",
            "scopes": ["read:tools"],
            "phase": 1,
            "auditLevel": "basic",
            "sourceEndpoints": ["/api/mcp"],
        },
        {"name": "", "description": "no name -> dropped"},
    ],
}


def test_parse_tools_maps_fields_and_drops_nameless():
    tools = parse_tools(_PAYLOAD)
    assert len(tools) == 1  # the empty-name entry is dropped
    t = tools[0]
    assert t.name == "omniroute_tool_search"
    assert t.scopes == ("read:tools",)
    assert t.phase == 1
    assert t.audit_level == "basic"


def test_mcp_url_for_drops_v1_suffix():
    assert mcp_url_for("http://gw:20128/v1") == "http://gw:20128/api/mcp/stream"
    assert mcp_url_for("http://gw:20128/v1/") == "http://gw:20128/api/mcp/stream"
    # no /v1 suffix: appended directly under the same root
    assert mcp_url_for("http://gw:20128") == "http://gw:20128/api/mcp/stream"


def test_discover_tools_fetches_with_mgmt_key(monkeypatch):
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["auth"] = request.headers.get("Authorization")
        return httpx.Response(200, json=_PAYLOAD)

    transport = httpx.MockTransport(handler)
    real_init = httpx.AsyncClient.__init__

    def _init(self, *a, **k):
        k["transport"] = transport
        real_init(self, *a, **k)

    monkeypatch.setattr(httpx.AsyncClient, "__init__", _init)

    import asyncio

    tools = asyncio.run(discover_tools("http://gw:20128/v1", mgmt_key="mgmt-key"))
    assert len(tools) == 1
    assert seen["url"] == "http://gw:20128/api/mcp/tools"  # /v1 dropped, /api used
    assert seen["auth"] == "Bearer mgmt-key"


def test_discover_tools_fails_open_on_error(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403)  # inference key / no scope

    transport = httpx.MockTransport(handler)
    real_init = httpx.AsyncClient.__init__

    def _init(self, *a, **k):
        k["transport"] = transport
        real_init(self, *a, **k)

    monkeypatch.setattr(httpx.AsyncClient, "__init__", _init)

    import asyncio

    assert asyncio.run(discover_tools("http://gw:20128/v1", mgmt_key="x")) == []
