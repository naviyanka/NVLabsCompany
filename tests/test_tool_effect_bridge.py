"""The inbound MCP bridge names each write by the client's ``Idempotency-Key`` header or the
invocation argument the tool schema declares (stock Claude Code can only send the argument).

The bridge route builds a new ``MCPServer`` for every HTTP request, so nothing in memory can say
"this is the same write". A write must carry an ``Idempotency-Key``; the first request with a key
reserves the next free ordinal of the turn in ``tool_bridge_slots`` and every retry of that key,
from any server instance, finds the same slot ``(-1, ordinal)``. These tests drive the real route
over ASGI on the manager-bridge fixtures.
"""

# ruff: noqa: F811 -- the imported fixtures are used by name, as elsewhere in the suite

from __future__ import annotations

import asyncio
import json
import uuid

import pytest

from nexus.models.tool_effect import ToolBridgeSlot, ToolEffect
from nexus.tools import effects, manager_bridge, manager_tools
from nexus.tools.ceo_tools import CEO_TOOLS
from nexus.tools.effects import BRIDGE_KEY_ARG, BridgeSlotError, ToolSlot
from nexus.tools.mcp_server import MCPServer
from tests.test_employee_work import _rows, db, w  # noqa: F401 -- fixtures
from tests.test_manager_bridge import (  # noqa: F401 -- fixtures and helpers
    CLAUDE,
    _allow_delegation,
    _chat_ctx,
    _token,
    _tool,
    _turn,
    rpc,
)
from tests.test_manager_core import _payload, _staffed, team  # noqa: F401 -- fixtures

pytestmark = pytest.mark.employee_work

WRITE = "manager_delegate_task"


@pytest.fixture
def sends(monkeypatch):
    """Replace the manager tool body with one that counts how often it really runs."""
    calls: list[dict] = []

    async def fake(ctx, name, arguments):
        calls.append(dict(arguments))
        return {"sent": len(calls)}

    monkeypatch.setattr(manager_tools, "call", fake)
    return calls


def _args(team, to="agy"):
    return {"task_id": str(team["task2"]), "employee_id": str(team["acme_" + to])}


async def _start(db, team):
    await _staffed(team)
    await _allow_delegation(db, team["acme"])
    turn = await _turn(db, team["lead"])
    return turn, await _token(turn)


async def _slots(db, turn):
    got = await _rows(db, ToolEffect, ToolEffect.turn_id == turn.id)
    return sorted((r.round_index, r.invocation_index) for r in got)


async def test_two_intentional_identical_writes_run_at_distinct_slots(db, team, rpc, sends):
    turn, token = await _start(db, team)
    args = _args(team)
    one = _payload(await _tool(rpc, token, WRITE, args, key="send-1"))
    two = _payload(await _tool(rpc, token, WRITE, args, key="send-2"))
    assert (one["sent"], two["sent"]) == (1, 2) and len(sends) == 2
    assert await _slots(db, turn) == [(-1, 0), (-1, 1)]


async def test_retrying_the_first_request_replays_and_does_not_run_again(db, team, rpc, sends):
    turn, token = await _start(db, team)
    args = _args(team)
    first = _payload(await _tool(rpc, token, WRITE, args, key="send-1"))
    await _tool(rpc, token, WRITE, args, key="send-2")
    again = _payload(await _tool(rpc, token, WRITE, args, key="send-1"))
    assert again == first and len(sends) == 2
    assert await _slots(db, turn) == [(-1, 0), (-1, 1)]


async def test_a_new_server_and_a_restart_map_the_same_key_to_the_same_slot(db, team, sends):
    turn, token = await _start(db, team)
    ctx = await manager_bridge.authenticate(token)
    args = _args(team)
    first = await MCPServer(ctx, node_tools=False, idempotency_key="k-1").call_tool(WRITE, args)
    # "Restart": nothing from the first server instance is reused.
    ctx = await manager_bridge.authenticate(token)
    again = await MCPServer(ctx, node_tools=False, idempotency_key="k-1").call_tool(WRITE, args)
    assert again == first and len(sends) == 1
    assert await _slots(db, turn) == [(-1, 0)]


async def test_a_new_server_with_a_new_key_gets_a_distinct_slot(db, team, sends):
    turn, token = await _start(db, team)
    ctx = await manager_bridge.authenticate(token)
    args = _args(team)
    await MCPServer(ctx, node_tools=False, idempotency_key="k-1").call_tool(WRITE, args)
    other = await MCPServer(ctx, node_tools=False, idempotency_key="k-2").call_tool(WRITE, args)
    assert other["isError"] is False and len(sends) == 2
    assert await _slots(db, turn) == [(-1, 0), (-1, 1)]


async def test_concurrent_requests_get_distinct_slots(db, team, rpc, sends):
    turn, token = await _start(db, team)
    args = _args(team)
    results = await asyncio.gather(
        *(_tool(rpc, token, WRITE, args, key=f"burst-{i}") for i in range(4))
    )
    assert all(r["isError"] is False for r in results) and len(sends) == 4
    assert await _slots(db, turn) == [(-1, 0), (-1, 1), (-1, 2), (-1, 3)]
    assert {r.ordinal for r in await _rows(db, ToolBridgeSlot)} == {0, 1, 2, 3}


async def test_a_retry_with_different_arguments_fails_closed(db, team, rpc, sends):
    turn, token = await _start(db, team)
    await _tool(rpc, token, WRITE, _args(team, "agy"), key="send-1")
    changed = await _tool(rpc, token, WRITE, _args(team, "claude"), key="send-1")
    assert changed["isError"] and "IDEMPOTENCY_KEY_REUSED" in changed["content"][0]["text"]
    assert len(sends) == 1 and await _slots(db, turn) == [(-1, 0)]


async def test_a_write_with_no_idempotency_key_fails_before_dispatch(db, team, rpc, sends):
    turn, token = await _start(db, team)
    refused = await _tool(rpc, token, WRITE, _args(team))
    assert refused["isError"] and "IDEMPOTENCY_KEY_REQUIRED" in refused["content"][0]["text"]
    assert sends == [] and await _slots(db, turn) == []
    assert await _rows(db, ToolBridgeSlot) == []


async def test_a_malformed_key_is_rejected_by_the_route(db, team, rpc, sends):
    turn, token = await _start(db, team)
    for bad in ("", "has space", "x" * 129, "semi;colon"):
        response = await rpc(
            token, "tools/call", {"name": WRITE, "arguments": _args(team)},
            headers={"idempotency-key": bad},
        )
        assert response.status_code == 400
    assert sends == [] and await _slots(db, turn) == []


async def test_a_read_only_call_needs_no_key_and_takes_no_slot(db, team, rpc):
    turn, token = await _start(db, team)
    reports = _payload(await _tool(rpc, token, "manager_list_reports"))
    assert {r["name"] for r in reports} == {"claude", "agy"}
    assert await _rows(db, ToolBridgeSlot) == []


async def test_another_company_cannot_reach_or_share_a_slot(db, team, rpc, sends, w):
    turn, token = await _start(db, team)
    args = _args(team)
    await _tool(rpc, token, WRITE, args, key="send-1")
    # A credential naming the other company for this turn is refused outright ...
    import jwt

    from nexus.config import settings
    from nexus.models._time import utcnow

    forged = jwt.encode(
        {"sub": str(team["lead"]), "company_id": str(team["other"]),
         "execution_id": turn.execution_id, "aud": manager_bridge.AUDIENCE,
         "exp": utcnow() + __import__("datetime").timedelta(minutes=5)},
        settings.secret_key, algorithm="HS256",
    )
    response = await rpc(
        forged, "tools/call", {"name": WRITE, "arguments": args},
        headers={"idempotency-key": "send-1"},
    )
    assert response.status_code == 401 and len(sends) == 1
    # ... and the same key under the other company is a different, independent slot.
    mine = await effects.reserve_bridge_slot(team["acme"], turn.id, "send-1", WRITE, args)
    theirs = await effects.reserve_bridge_slot(team["other"], turn.id, "send-1", WRITE, args)
    assert mine == theirs == ToolSlot(-1, 0)
    keys = {(r.company_id, r.idempotency_key) for r in await _rows(db, ToolBridgeSlot)}
    assert keys == {(team["acme"], "send-1"), (team["other"], "send-1")}


async def test_the_client_cannot_pick_the_turn_or_the_recovery_epoch(db, team, rpc, sends):
    turn, token = await _start(db, team)
    args = _args(team)
    spoof = {"x-turn-id": str(uuid.uuid4()), "x-company-id": str(team["other"]),
             "x-recovering": "false", "x-attempt": "1"}
    response = await rpc(
        token, "tools/call", {"name": WRITE, "arguments": args},
        headers={"idempotency-key": "send-1", **spoof},
    )
    assert response.status_code == 200
    (slot,) = await _rows(db, ToolBridgeSlot)
    assert (slot.company_id, slot.turn_id) == (team["acme"], turn.id)


async def test_a_recovered_turn_replays_its_keyed_write_but_not_a_new_key(db, team, rpc, sends):
    from sqlalchemy import update

    from nexus.models.chat_turn import ChatTurn

    turn, token = await _start(db, team)
    args = _args(team)
    first = _payload(await _tool(rpc, token, WRITE, args, key="send-1"))
    # The turn is recovered: a new execution of it, the second attempt.
    new_execution = str(uuid.uuid4())
    async with db() as s:
        await s.execute(update(ChatTurn).where(ChatTurn.id == turn.id)
                        .values(execution_id=new_execution, attempt_count=2))
        await s.commit()
        turn = await s.get(ChatTurn, turn.id)
    token = await _token(turn)
    assert _payload(await _tool(rpc, token, WRITE, args, key="send-1")) == first
    fresh = await _tool(rpc, token, WRITE, args, key="send-2")
    assert fresh["isError"] and "operator" in fresh["content"][0]["text"]
    assert len(sends) == 1
    assert [r.ordinal for r in await _rows(db, ToolBridgeSlot)] == [0, 1]
    assert await _slots(db, turn) == [(-1, 0)]


async def test_reserve_refuses_a_missing_key_directly():
    with pytest.raises(BridgeSlotError):
        await effects.reserve_bridge_slot(uuid.uuid4(), uuid.uuid4(), None, WRITE, {})
    assert not effects.valid_bridge_key("")
    assert effects.valid_bridge_key("a.b_c:d~e-1")


# --- the declared invocation argument: what stock Claude Code can send ------------------------


async def _arg_call(rpc, token, name, args, key, **headers):
    """One write with its identity in the declared argument, and optionally a header too."""
    response = await rpc(
        token, "tools/call", {"name": name, "arguments": {**args, BRIDGE_KEY_ARG: key}},
        headers=headers or None,
    )
    assert response.status_code == 200, response.text
    return response.json()["result"]


async def test_an_argument_only_write_needs_no_custom_header(db, team, rpc, sends):
    turn, token = await _start(db, team)
    out = _payload(await _arg_call(rpc, token, WRITE, _args(team), "arg-1"))
    assert out == {"sent": 1}
    # The reserved argument is the bridge's, not the tool's: it never reaches the handler.
    assert sends == [_args(team)] and await _slots(db, turn) == [(-1, 0)]


async def test_header_and_argument_that_match_are_one_identity(db, team, rpc, sends):
    turn, token = await _start(db, team)
    both = await _arg_call(
        rpc, token, WRITE, _args(team), "same-1", **{"idempotency-key": "same-1"}
    )
    assert both["isError"] is False
    again = await _tool(rpc, token, WRITE, _args(team), key="same-1")  # header alone, same slot
    assert _payload(again) == _payload(both) and len(sends) == 1
    assert await _slots(db, turn) == [(-1, 0)]


async def test_header_and_argument_that_disagree_fail_before_dispatch(db, team, rpc, sends):
    turn, token = await _start(db, team)
    refused = await _arg_call(
        rpc, token, WRITE, _args(team), "arg-1", **{"idempotency-key": "hdr-1"}
    )
    assert refused["isError"] and "IDEMPOTENCY_KEY_CONFLICT" in refused["content"][0]["text"]
    assert sends == [] and await _rows(db, ToolBridgeSlot) == []


@pytest.mark.parametrize("bad", ["", "has space", "x" * 129, "semi;colon", 7, None, ["a"]])
async def test_a_malformed_argument_fails_before_dispatch(db, team, rpc, sends, bad):
    turn, token = await _start(db, team)
    refused = await _arg_call(rpc, token, WRITE, _args(team), bad)
    assert refused["isError"] and "IDEMPOTENCY_KEY_INVALID" in refused["content"][0]["text"]
    assert sends == [] and await _rows(db, ToolBridgeSlot) == []


async def test_retrying_an_argument_call_replays_and_a_new_argument_runs_again(
    db, team, rpc, sends
):
    turn, token = await _start(db, team)
    args = _args(team)
    first = _payload(await _arg_call(rpc, token, WRITE, args, "arg-1"))
    retry = _payload(await _arg_call(rpc, token, WRITE, args, "arg-1"))
    assert retry == first and len(sends) == 1
    second = _payload(await _arg_call(rpc, token, WRITE, args, "arg-2"))  # identical business args
    assert second == {"sent": 2} and len(sends) == 2
    assert await _slots(db, turn) == [(-1, 0), (-1, 1)]


async def test_an_argument_reused_for_other_arguments_or_another_tool_is_refused(
    db, team, rpc, sends
):
    turn, token = await _start(db, team)
    await _arg_call(rpc, token, WRITE, _args(team, "agy"), "arg-1")
    changed = await _arg_call(rpc, token, WRITE, _args(team, "claude"), "arg-1")
    assert changed["isError"] and "IDEMPOTENCY_KEY_REUSED" in changed["content"][0]["text"]
    # The hire tool names its identity `idempotency_key`; the same value for it is another tool.
    other = await rpc(
        token, "tools/call",
        {"name": "manager_request_hire", "arguments": {"idempotency_key": "arg-1"}},
    )
    assert "IDEMPOTENCY_KEY_REUSED" in other.json()["result"]["content"][0]["text"]
    assert len(sends) == 1 and await _slots(db, turn) == [(-1, 0)]


async def test_concurrent_argument_calls_get_distinct_slots(db, team, rpc, sends):
    turn, token = await _start(db, team)
    results = await asyncio.gather(
        *(_arg_call(rpc, token, WRITE, _args(team), f"burst-{i}") for i in range(4))
    )
    assert all(r["isError"] is False for r in results) and len(sends) == 4
    assert await _slots(db, turn) == [(-1, 0), (-1, 1), (-1, 2), (-1, 3)]


async def test_a_new_server_maps_the_same_argument_to_the_same_slot(db, team, sends):
    turn, token = await _start(db, team)
    args = {**_args(team), BRIDGE_KEY_ARG: "k-1"}
    ctx = await manager_bridge.authenticate(token)
    first = await MCPServer(ctx, node_tools=False, bridge=True).call_tool(WRITE, dict(args))
    ctx = await manager_bridge.authenticate(token)
    again = await MCPServer(ctx, node_tools=False, bridge=True).call_tool(WRITE, dict(args))
    assert again == first and len(sends) == 1 and await _slots(db, turn) == [(-1, 0)]


async def test_a_client_that_ignores_the_schema_is_told_what_is_missing(db, team, rpc, sends):
    turn, token = await _start(db, team)
    refused = await _tool(rpc, token, WRITE, _args(team))
    text = refused["content"][0]["text"]
    assert "IDEMPOTENCY_KEY_REQUIRED" in text and BRIDGE_KEY_ARG in text and sends == []


async def test_claude_discovers_the_required_argument_and_needs_no_dynamic_header(
    db, team, rpc, sends
):
    turn, token = await _start(db, team)
    bridge = await manager_bridge.open_bridge(
        _chat_ctx(turn.company_id, turn.agent_id), uuid.UUID(turn.execution_id), CLAUDE, 600
    )
    try:
        with open(bridge.config_path, encoding="utf-8") as f:
            server = json.load(f)["mcpServers"]["nexus"]
        bearer = bridge.env[manager_bridge.TOKEN_ENV]
    finally:
        bridge.close()
    # The generated config sets one static header, the credential: nothing per call.
    assert set(server["headers"]) == {"Authorization"} and server["type"] == "http"
    listed = {
        t["name"]: t for t in (await rpc(bearer, "tools/list")).json()["result"]["tools"]
    }
    catalog = {**manager_tools.MANAGER_TOOLS, **CEO_TOOLS}
    for name, tool in listed.items():
        declared = catalog[name]
        field = manager_tools.key_field(declared)
        if manager_tools.is_write(declared):
            assert field in tool["inputSchema"]["required"], name
            assert tool["inputSchema"]["properties"][field]["maxLength"] == 128
            assert "NEW unique value" in tool["description"], name
        else:
            assert BRIDGE_KEY_ARG not in tool["inputSchema"].get("properties", {}), name
    assert BRIDGE_KEY_ARG in listed[WRITE]["inputSchema"]["required"]
    # The whole flow with the discovered schema and no header: run, replay, run again, refuse.
    args = _args(team)
    one = await _arg_call(rpc, bearer, WRITE, args, "claude-1")
    assert one["isError"] is False
    assert _payload(await _arg_call(rpc, bearer, WRITE, args, "claude-1")) == _payload(one)
    assert (await _arg_call(rpc, bearer, WRITE, args, "claude-2"))["isError"] is False
    changed = await _arg_call(rpc, bearer, WRITE, _args(team, "claude"), "claude-1")
    assert changed["isError"] and len(sends) == 2
    # A read needs neither header nor argument, and takes no slot.
    assert (await _tool(rpc, bearer, "manager_list_reports"))["isError"] is False
    assert len(await _rows(db, ToolBridgeSlot)) == 2


async def test_a_request_authenticated_before_a_recovery_cannot_write_or_reserve_a_slot(
    db, team, sends
):
    from sqlalchemy import update

    from nexus.models.chat_turn import ChatTurn

    turn, token = await _start(db, team)
    ctx = await manager_bridge.authenticate(token)  # the epoch is fixed here, at attempt 1
    async with db() as s:  # a recovery then claims the turn again
        await s.execute(update(ChatTurn).where(ChatTurn.id == turn.id)
                        .values(execution_id=str(uuid.uuid4()), attempt_count=2))
        await s.commit()
    args = {**_args(team), BRIDGE_KEY_ARG: "late-1"}
    out = await MCPServer(ctx, node_tools=False, bridge=True).call_tool(WRITE, args)
    assert out["isError"] and "stale_execution" in out["content"][0]["text"]
    assert sends == [] and await _rows(db, ToolBridgeSlot) == []
    assert await _slots(db, turn) == []
