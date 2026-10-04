"""The inbound MCP bridge names each write by the client's ``Idempotency-Key``.

The bridge route builds a new ``MCPServer`` for every HTTP request, so nothing in memory can say
"this is the same write". A write must carry an ``Idempotency-Key``; the first request with a key
reserves the next free ordinal of the turn in ``tool_bridge_slots`` and every retry of that key,
from any server instance, finds the same slot ``(-1, ordinal)``. These tests drive the real route
over ASGI on the manager-bridge fixtures.
"""

# ruff: noqa: F811 -- the imported fixtures are used by name, as elsewhere in the suite

from __future__ import annotations

import asyncio
import uuid

import pytest

from nexus.models.tool_effect import ToolBridgeSlot, ToolEffect
from nexus.tools import effects, manager_bridge, manager_tools
from nexus.tools.effects import BridgeSlotError, ToolSlot
from nexus.tools.mcp_server import MCPServer
from tests.test_employee_work import _rows, db, w  # noqa: F401 -- fixtures
from tests.test_manager_bridge import (  # noqa: F401 -- fixtures and helpers
    _allow_delegation,
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
