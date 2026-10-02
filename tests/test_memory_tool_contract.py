"""The model-callable memory tool searches active memory and takes no lifecycle argument.

``include_closed`` is not in any tool schema: a model that sends it (forged, or from a
legacy prompt) is refused as an unexpected argument. The refusal comes before any query and
before any audit of a memory read, and the tool never falls back to an active-only answer
for it. Candidate, archived, superseded and rejected content has no model-visible path; the
operator review route (``GET /ceo/memory?include_closed=true``) is a separate, human-only
contract (tests/test_memory_review_access.py).
"""

from __future__ import annotations

import json

import pytest
from sqlalchemy import select

from nexus.models.governance import AuditLog
from nexus.models.memory import MEMORY_STATUSES, MemoryRecord
from nexus.models.tool_invocation import ToolInvocation
from nexus.services import ceo_service
from nexus.tools import manager_tools
from nexus.tools.ceo_tools import CEO_TOOLS
from nexus.tools.mcp_server import MCPServer
from tests.test_ceo_control_plane import CEO, _appoint, _error, c  # noqa: F401 -- fixtures
from tests.test_employee_work import db, w  # noqa: F401 -- fixtures
from tests.test_manager_core import _ctx, _payload, team  # noqa: F401 -- fixture

pytestmark = pytest.mark.employee_work

TOOL = "ceo_search_executive_memory"
CLOSED = tuple(s for s in MEMORY_STATUSES if s != "active")
LEGACY_ARGS = ({"include_closed": True}, {"include_closed": False}, {"status": "archived"})


def test_no_tool_schema_exposes_a_lifecycle_argument():
    for name, tool in {**manager_tools.MANAGER_TOOLS, **CEO_TOOLS}.items():
        schema = manager_tools.input_schema(tool)
        assert schema["additionalProperties"] is False, name
        assert not {"include_closed", "status", "state"} & set(schema.get("properties", {})), name


def test_the_search_tool_schema_has_only_real_arguments_and_says_active_only():
    tool = CEO_TOOLS[TOOL]
    schema = manager_tools.input_schema(tool)
    assert set(schema["properties"]) == {"query", "type", "limit"}
    assert schema["additionalProperties"] is False
    assert "active executive memory" in tool.description.lower()
    assert "never returned" in tool.description


async def _seed(db, company):  # noqa: F811
    rows = [MemoryRecord(company_id=company, scope=ceo_service.EXECUTIVE_SCOPE,
                         memory_type="decision", content="live decision", status="active")]
    rows += [MemoryRecord(company_id=company, scope=ceo_service.EXECUTIVE_SCOPE,
                          memory_type="decision", content=f"hidden {st} decision", status=st)
             for st in CLOSED]
    async with db() as s:
        s.add_all(rows)
        await s.commit()


async def _chief_server(c):  # noqa: F811
    await _appoint(c, c["chief"])
    return MCPServer(_ctx(c["acme"], c["chief"]))


async def test_active_memory_is_returned_and_every_other_status_is_excluded(db, c):  # noqa: F811
    server = await _chief_server(c)
    await _seed(db, c["acme"])
    found = _payload(await server.call_tool(TOOL, {"query": "decision"}))
    assert [e["content"] for e in found] == ["live decision"]
    assert "hidden" not in json.dumps(found)
    for st in CLOSED:
        assert st not in {e["status"] for e in found}
        none = _payload(await server.call_tool(TOOL, {"query": f"hidden {st}"}))
        assert none == [], st


@pytest.mark.parametrize("args", LEGACY_ARGS)
async def test_a_forged_or_legacy_lifecycle_argument_is_rejected(db, c, monkeypatch, args):  # noqa: F811
    server = await _chief_server(c)
    await _seed(db, c["acme"])
    executed = []

    async def refuse(*a, **k):
        executed.append((a, k))
        raise AssertionError("a rejected call must not query memory")

    monkeypatch.setattr(ceo_service, "recall", refuse)
    monkeypatch.setattr(ceo_service, "review_recall", refuse)
    async with db() as s:
        before = len((await s.execute(select(AuditLog))).scalars().all())

    out = await server.call_tool(TOOL, args)

    text = _error(out)
    assert "invalid arguments" in text and next(iter(args)) in text and "hidden" not in text
    assert executed == []
    async with db() as s:
        after = list((await s.execute(select(AuditLog))).scalars().all())
        invocations = list((await s.execute(select(ToolInvocation))).scalars().all())
    assert len(after) == before  # nothing was audited as a memory read
    assert not [a for a in after if "memory" in a.action]
    assert all(i.status != "success" for i in invocations)


async def test_a_rejected_argument_does_not_fall_back_to_an_active_only_answer(db, c):  # noqa: F811
    server = await _chief_server(c)
    await _seed(db, c["acme"])
    out = await server.call_tool(TOOL, {"include_closed": True, "query": "decision"})
    assert out["isError"] is True
    assert "live decision" not in out["content"][0]["text"]


async def test_the_catalog_the_model_sees_carries_the_active_only_contract(db, c):  # noqa: F811
    server = await _chief_server(c)
    listed = {t["name"]: t for t in await server.list_tools()}[TOOL]
    assert "include_closed" not in json.dumps(listed["inputSchema"])
    assert listed["inputSchema"]["additionalProperties"] is False
    assert "Only active memory is searched" in listed["description"]


async def test_the_operator_review_route_still_serves_closed_rows_to_a_human_admin(db, c):  # noqa: F811
    await _appoint(c, c["chief"])
    await _seed(db, c["acme"])
    default = (await c["call"]("GET", f"{CEO}/memory")).json()
    assert [e["content"] for e in default] == ["live decision"]
    review = (await c["call"]("GET", f"{CEO}/memory?include_closed=true")).json()
    assert {e["content"] for e in review} == {"live decision", *(
        f"hidden {st} decision" for st in CLOSED)}
    for who in ("viewer", "admin_key", "viewer_key", "chief_run"):
        refused = await c["call"]("GET", f"{CEO}/memory?include_closed=true", who=who)
        assert refused.status_code == 403 and "hidden" not in refused.text, who
