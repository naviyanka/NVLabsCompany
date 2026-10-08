"""Recovery semantics of the tool-effect ledger beyond the basic claim and replay paths.

Covers the position-aware identity (slot), the fail-closed exception rules, database-time
leases, one-time result sealing, once-only notifications and the defaults of paths that
register tools dynamically. Fixtures and helpers come from ``tests.test_tool_effects``.
"""

# ruff: noqa: F811 -- the imported fixtures are used by name, as elsewhere in the suite

from __future__ import annotations

import asyncio
import json
import uuid
from datetime import timedelta

import pytest
from sqlmodel import select

from nexus.models.tool_invocation import ToolInvocation
from nexus.nodes.executor import ExecutorResult
from nexus.tools import effects
from nexus.tools import factory as tool_factory
from nexus.tools.autonomy import AutonomyGate
from nexus.tools.effects import EffectNotStarted, ToolSlot
from nexus.tools.mcp_client import MCPResult
from nexus.tools.mcp_server import MCPServer
from nexus.tools.obsidian import (
    OBSIDIAN_NOTE_REPLACE_NAME,
    OBSIDIAN_REJECTED_STATUSES,
    OBSIDIAN_UNCERTAIN_STATUSES,
)
from tests.test_tool_effects import (  # noqa: F401 -- fixtures and helpers
    IDEM,
    NON_IDEM,
    SLOT,
    Tool,
    audit_rows,
    expire_lease,
    factory,
    go,
    rows,
    turn_ctx,
    world,
)

# --- position-aware identity -----------------------------------------------------------------


async def test_identical_calls_at_different_positions_run_separately(factory, world):
    tool = Tool()
    for slot in (ToolSlot(0, 0), ToolSlot(0, 1), ToolSlot(1, 0), ToolSlot(1, 1)):
        await go(world, tool, slot=slot)
    assert tool.runs == 4
    assert sorted((r.round_index, r.invocation_index) for r in await rows(factory)) == [
        (0, 0), (0, 1), (1, 0), (1, 1),
    ]


async def test_the_round_and_the_position_are_not_interchangeable(factory, world):
    tool = Tool()
    await go(world, tool, slot=ToolSlot(1, 0))
    await go(world, tool, slot=ToolSlot(0, 1))
    assert tool.runs == 2


async def test_recovery_of_the_same_position_reuses_the_row(factory, world):
    tool = Tool(result={"sent": "m1"})
    first = await go(world, tool, slot=ToolSlot(2, 3))
    again = await go(world, tool, slot=ToolSlot(2, 3))
    assert tool.runs == 1 and again["replayed"] is True and again["result"] == first["result"]
    (row,) = await rows(factory)
    assert row.attempt_count == 1 and row.tool_name == "send-it"
    assert (row.round_index, row.invocation_index) == (2, 3)
    assert row.arguments_digest == effects.arguments_digest({"to": "a", "n": 1})


async def test_a_different_tool_or_arguments_at_an_occupied_slot_fail_closed(factory, world):
    await go(world, Tool())
    other_tool, other_args = Tool(), Tool()
    by_tool = await go(world, other_tool, name="other-tool")
    by_args = await go(world, other_args, args={"to": "someone-else", "n": 1})
    assert by_tool["status"] == by_args["status"] == "effect_recovery_required"
    assert other_tool.runs == other_args.runs == 0
    (row,) = await rows(factory)
    assert row.tool_name == "send-it" and row.status == "succeeded"
    assert "tool_effect.slot_mismatch" in {e.action for e in await audit_rows(factory)}


@pytest.mark.parametrize("effect", [IDEM, NON_IDEM])
async def test_a_recovery_that_reorders_its_calls_runs_nothing_twice(factory, world, effect):
    first_a, first_b = Tool(), Tool()
    await go(world, first_a, effect=effect, args={"id": "A"}, slot=ToolSlot(0, 0))
    await go(world, first_b, effect=effect, args={"id": "B"}, slot=ToolSlot(0, 1))
    # The recovered model emits the same two calls in the opposite order.
    swapped_a, swapped_b = Tool(), Tool()
    out_b = await go(world, swapped_b, effect=effect, args={"id": "B"}, slot=ToolSlot(0, 0))
    out_a = await go(world, swapped_a, effect=effect, args={"id": "A"}, slot=ToolSlot(0, 1))
    assert out_a["status"] == out_b["status"] == "effect_recovery_required"
    assert swapped_a.runs == swapped_b.runs == 0
    assert first_a.runs == first_b.runs == 1
    assert len(await rows(factory)) == 2


async def test_the_same_calls_in_the_same_order_replay_both(factory, world):
    one, two = Tool(result={"n": 1}), Tool(result={"n": 2})
    await go(world, one, args={"id": "A"}, slot=ToolSlot(0, 0))
    await go(world, two, args={"id": "B"}, slot=ToolSlot(0, 1))
    again_one = await go(world, Tool(), args={"id": "A"}, slot=ToolSlot(0, 0))
    again_two = await go(world, Tool(), args={"id": "B"}, slot=ToolSlot(0, 1))
    assert again_one["result"] == {"n": 1} and again_two["result"] == {"n": 2}
    assert again_one["replayed"] and again_two["replayed"]


async def test_concurrent_claims_with_different_arguments_for_one_slot_run_once(factory, world):
    gate = asyncio.Event()
    tools = [Tool(gate=gate) for _ in range(6)]
    callers = [
        asyncio.create_task(go(world, tool, args={"n": i})) for i, tool in enumerate(tools)
    ]
    for _ in range(300):
        if sum(t.runs for t in tools) >= 1 and sum(c.done() for c in callers) >= 5:
            break
        await asyncio.sleep(0.01)
    gate.set()
    outs = await asyncio.gather(*callers)
    assert sum(t.runs for t in tools) == 1
    assert sorted(o["status"] for o in outs).count("success") == 1
    assert {o["status"] for o in outs} <= {
        "success", "effect_in_progress", "effect_recovery_required",
    }
    assert len(await rows(factory)) == 1


async def test_a_write_in_a_turn_with_no_slot_is_refused_before_any_side_effect(
    factory, world, monkeypatch
):
    seen = []

    async def spy(*args, **kwargs):
        seen.append(kwargs.get("invocation_key"))

    monkeypatch.setattr(tool_factory, "guard_tool_call", spy)
    monkeypatch.setattr(effects, "claim_notice", spy)
    tool = Tool()
    out = await go(world, tool, slot=None)
    assert out["status"] == "effect_ledger_unavailable" and tool.runs == 0
    assert seen == [] and await rows(factory) == []
    async with factory() as db:
        (inv,) = (await db.execute(select(ToolInvocation))).scalars().all()
    assert inv.status == "effect_ledger_unavailable"


async def test_a_read_only_call_needs_no_slot(factory, world):
    tool = Tool()
    out = await go(world, tool, effect=effects.EffectClass.READ_ONLY, slot=None)
    assert out["status"] == "success" and tool.runs == 1 and await rows(factory) == []


# --- exception semantics: only a typed pre-effect rejection is retryable ----------------------


class _HttpError(Exception):
    def __init__(self, code):
        super().__init__(f"HTTP {code} for SECRET-BODY")
        self.status_code = code


@pytest.mark.parametrize(
    "exc",
    [
        ValueError("late failure"),
        json.JSONDecodeError("not json", "", 0),
        _HttpError(400),
        _HttpError(422),
        _HttpError(503),
        TimeoutError("slow"),
        RuntimeError("unexpected"),
        KeyError("k"),
    ],
)
async def test_a_non_idempotent_exception_is_ambiguous_and_never_retried(factory, world, exc):
    with pytest.raises(type(exc)):
        await go(world, Tool(raises=exc))
    (row,) = await rows(factory)
    assert row.status == "ambiguous" and row.error == type(exc).__name__
    retry = Tool()
    out = await go(world, retry)
    assert out["status"] == "effect_recovery_required" and retry.runs == 0


@pytest.mark.parametrize("effect", [IDEM, NON_IDEM])
async def test_a_typed_pre_effect_rejection_is_retryable(factory, world, effect):
    with pytest.raises(EffectNotStarted):
        await go(world, Tool(raises=EffectNotStarted("refused before dispatch")), effect=effect)
    (row,) = await rows(factory)
    assert row.status == "failed"
    retry = Tool(result={"ok": "second"})
    out = await go(world, retry, effect=effect)
    assert out["status"] == "success" and retry.runs == 1


async def test_an_in_band_mcp_error_is_ambiguous(factory, world):
    tool = Tool(result=MCPResult(content="remote said no", is_error=True))
    await go(world, tool)
    (row,) = await rows(factory)
    assert row.status == "ambiguous"
    retry = Tool()
    assert (await go(world, retry))["status"] == "effect_recovery_required"
    assert retry.runs == 0


# --- the real executor: a send whose success body cannot be read ------------------------------


class _Response:
    def __init__(self, status=200, body=None, readable=True):
        self.status_code, self._body, self._readable = status, body, readable
        self.text = "OK"

    def json(self):
        if not self._readable:
            raise json.JSONDecodeError("Expecting value", "OK", 0)
        return self._body


def _fake_http(monkeypatch, response):
    import httpx

    posts = []

    class Client:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def post(self, *args, **kwargs):
            posts.append(args)
            return response

    monkeypatch.setattr(httpx, "AsyncClient", Client)
    return posts


@pytest.mark.parametrize(
    ("node", "token_env", "arguments"),
    [
        ("msg-discord-send", "DISCORD_BOT_TOKEN", {"channel_id": "1", "content": "hi"}),
        ("msg-telegram-send", "TELEGRAM_BOT_TOKEN", {"chat_id": "1", "text": "hi"}),
    ],
)
async def test_a_success_response_that_cannot_be_read_is_never_resent(
    factory, world, monkeypatch, node, token_env, arguments
):
    monkeypatch.setenv(token_env, "token-value")
    posts = _fake_http(monkeypatch, _Response(readable=False))
    server = MCPServer(turn_ctx(world))
    first = await server.call_tool(node, arguments, slot=SLOT)
    assert first["isError"] is True
    (row,) = await rows(factory)
    assert row.status == "ambiguous"
    # The requeued turn asks again: the message may already be delivered, so it is not resent.
    again = await MCPServer(turn_ctx(world)).call_tool(node, arguments, slot=SLOT)
    assert again["isError"] is True and "not run" in again["content"][0]["text"]
    assert len(posts) == 1


@pytest.mark.parametrize(
    ("node", "token_env", "arguments"),
    [
        ("msg-discord-send", "DISCORD_BOT_TOKEN", {"channel_id": "1", "content": "hi"}),
        ("msg-telegram-send", "TELEGRAM_BOT_TOKEN", {"chat_id": "1", "text": "hi"}),
    ],
)
async def test_a_missing_credential_is_a_typed_rejection_and_retryable(
    factory, world, monkeypatch, node, token_env, arguments
):
    monkeypatch.delenv(token_env, raising=False)
    body = {"id": "m1", "ok": True, "result": {"message_id": 1}}
    posts = _fake_http(monkeypatch, _Response(body=body))
    server = MCPServer(turn_ctx(world))
    assert (await server.call_tool(node, arguments, slot=SLOT))["isError"] is True
    (row,) = await rows(factory)
    assert row.status == "failed" and posts == []
    monkeypatch.setenv(token_env, "token-value")
    done = await MCPServer(turn_ctx(world)).call_tool(node, arguments, slot=SLOT)
    assert done["isError"] is False and len(posts) == 1


# --- db-redis-set: a relative TTL makes a retry unsafe ----------------------------------------


class _Redis:
    """A Redis whose keys expire on a clock the test moves; ``set`` records its arguments."""

    def __init__(self):
        self.now = 0.0
        self.data: dict[str, tuple[str, float | None]] = {}
        self.calls: list[dict] = []

    async def set(self, key, value, **kwargs):
        self.calls.append(kwargs)
        self.data[key] = (value, self.now + kwargs["ex"] if "ex" in kwargs else None)

    async def aclose(self):
        pass


def _redis(monkeypatch):
    import redis.asyncio as aioredis

    client = _Redis()
    monkeypatch.setattr(aioredis, "from_url", lambda *a, **k: client)
    return client


@pytest.mark.parametrize(
    "arguments", [{"key": "k", "value": "v"}, {"key": "k", "value": "v", "ttl": 60}]
)
async def test_a_redis_set_replays_instead_of_running_twice(factory, world, monkeypatch, arguments):
    redis = _redis(monkeypatch)
    first = await MCPServer(turn_ctx(world)).call_tool("db-redis-set", arguments, slot=SLOT)
    again = await MCPServer(turn_ctx(world)).call_tool("db-redis-set", arguments, slot=SLOT)
    assert first["isError"] is False and again["isError"] is False
    assert len(redis.calls) == 1
    (row,) = await rows(factory)
    assert row.effect_class == NON_IDEM.value and row.status == "succeeded"


@pytest.mark.parametrize(
    "arguments", [{"key": "k", "value": "v"}, {"key": "k", "value": "v", "ttl": 60}]
)
async def test_a_crash_after_redis_accepted_the_set_is_never_retried_later(
    factory, world, monkeypatch, arguments
):
    redis = _redis(monkeypatch)

    async def lost(*args, **kwargs):  # the process dies after Redis accepted the write
        return False

    real = effects.settle
    monkeypatch.setattr(effects, "settle", lost)
    await MCPServer(turn_ctx(world)).call_tool("db-redis-set", arguments, slot=SLOT)
    monkeypatch.setattr(effects, "settle", real)
    (row,) = await rows(factory)
    assert row.status == "executing"
    await expire_lease(factory, row.id)
    expiry = redis.data["k"][1]
    redis.now += 300  # the requeued turn comes back minutes later
    again = await MCPServer(turn_ctx(world)).call_tool("db-redis-set", arguments, slot=SLOT)
    assert again["isError"] is True and "not run" in again["content"][0]["text"]
    assert len(redis.calls) == 1 and redis.data["k"][1] == expiry  # the expiry was not extended
    (row,) = await rows(factory)
    assert row.status == "manual_recovery_required"


# --- leases follow the database clock ---------------------------------------------------------


@pytest.mark.parametrize("skew", [timedelta(days=1), timedelta(days=-1)])
@pytest.mark.parametrize("effect", [IDEM, NON_IDEM])
async def test_a_skewed_worker_clock_does_not_move_a_live_lease(
    factory, world, monkeypatch, skew, effect
):
    gate = asyncio.Event()
    holder = Tool(gate=gate)
    task = asyncio.create_task(go(world, holder, effect=effect))
    for _ in range(200):
        if holder.runs:
            break
        await asyncio.sleep(0.01)
    real = effects.utcnow
    monkeypatch.setattr(effects, "utcnow", lambda: real() + skew)
    rival = Tool()
    assert (await go(world, rival, effect=effect))["status"] == "effect_in_progress"
    assert rival.runs == 0
    monkeypatch.setattr(effects, "utcnow", real)
    gate.set()
    await task
    (row,) = await rows(factory)
    assert row.status == "succeeded" and row.attempt_count == 1


async def test_a_lease_the_database_says_expired_is_retaken_despite_a_slow_clock(
    factory, world, monkeypatch
):
    gate = asyncio.Event()
    holder = Tool(gate=gate)
    task = asyncio.create_task(go(world, holder, effect=IDEM))
    for _ in range(200):
        if holder.runs:
            break
        await asyncio.sleep(0.01)
    (row,) = await rows(factory)
    await expire_lease(factory, row.id)
    real = effects.utcnow
    monkeypatch.setattr(effects, "utcnow", lambda: real() - timedelta(days=1))
    taker = Tool()
    assert (await go(world, taker, effect=IDEM))["status"] == "success" and taker.runs == 1
    monkeypatch.setattr(effects, "utcnow", real)
    gate.set()
    await task
    (row,) = await rows(factory)
    assert row.attempt_count == 2 and row.status == "succeeded"


async def test_an_interrupted_write_whose_slot_is_never_claimed_again_reaches_the_operator(
    factory, world
):
    gate = asyncio.Event()
    holder = Tool(gate=gate)  # the crashed worker: it never settles while the lease runs
    task = asyncio.create_task(go(world, holder))
    for _ in range(200):
        if holder.runs:
            break
        await asyncio.sleep(0.01)
    # The turn is recovered within the lease: the slot is busy, and the turn finishes without it.
    assert (await go(world, Tool()))["status"] == "effect_in_progress"
    assert await effects.expire_leases(world["acme"]) == 0
    assert (await effects.list_open(world["acme"]))["items"] == []

    (row,) = await rows(factory)
    await expire_lease(factory, row.id)
    assert await effects.expire_leases(world["acme"]) == 1
    assert await effects.expire_leases(world["acme"]) == 0
    (item,) = (await effects.list_open(world["acme"]))["items"]
    assert item["id"] == str(row.id) and item["status"] == "ambiguous"
    assert await effects.expire_leases(world["other"]) == 0

    gate.set()  # the old holder finishing late cannot settle a row it no longer holds
    await task
    (row,) = await rows(factory)
    assert row.status == "ambiguous" and holder.runs == 1
    assert any(a.action == "tool_effect.ambiguous" for a in await audit_rows(factory))

    await effects.resolve_manual_recovery(
        world["acme"], row.id, "applied", actor="operator", reason="checked the target"
    )
    (row,) = await rows(factory)
    assert row.status == "succeeded"


async def test_an_expired_idempotent_write_is_still_retaken_by_its_next_claim(factory, world):
    gate = asyncio.Event()
    task = asyncio.create_task(go(world, Tool(gate=gate), effect=IDEM))
    for _ in range(200):
        if await rows(factory):
            break
        await asyncio.sleep(0.01)
    (row,) = await rows(factory)
    await expire_lease(factory, row.id)
    assert await effects.expire_leases(world["acme"]) == 1
    taker = Tool()
    assert (await go(world, taker, effect=IDEM))["status"] == "success" and taker.runs == 1
    gate.set()
    await task
    (row,) = await rows(factory)
    assert row.status == "succeeded"


# --- one sealed form of every result ----------------------------------------------------------


async def test_the_first_result_equals_the_replayed_result(factory, world):
    token = "sk-" + "a" * 40
    big = {
        "id": "m-77",
        "status": "sent",
        "token": token,
        "api_key": "plain-secret-value",
        "rows": [{"v": "x" * 400} for _ in range(300)],
    }
    tool = Tool(result=big)
    first = await go(world, tool)
    again = await go(world, tool)
    assert tool.runs == 1 and again["replayed"] is True
    assert first["result"] == again["result"]
    shown = first["result"]
    assert shown["id"] == "m-77" and shown["status"] == "sent"
    assert token not in str(shown) and "plain-secret-value" not in str(shown)
    (row,) = await rows(factory)
    assert row.result["truncated"]["original_bytes"] > effects.MAX_RESULT_BYTES
    assert len(json.dumps(row.result)) < effects.MAX_RESULT_BYTES * 2


async def test_a_typed_result_is_the_same_object_kind_on_replay(factory, world):
    tool = Tool(result=ExecutorResult(success=True, outputs={"id": 7, "token": "sk-" + "b" * 30}))
    first = await go(world, tool)
    again = await go(world, tool)
    assert isinstance(first["result"], ExecutorResult)
    assert isinstance(again["result"], ExecutorResult)
    assert first["result"] == again["result"]
    assert "sk-" + "b" * 30 not in str(first["result"].outputs)


async def test_an_unserializable_result_is_ambiguous_and_not_rerun(factory, world):
    tool = Tool(result={"handle": object()})
    out = await go(world, tool)
    assert out["status"] == "effect_result_unavailable" and tool.runs == 1
    (row,) = await rows(factory)
    assert row.status == "ambiguous" and "result not retainable" in row.error
    retry = Tool()
    assert (await go(world, retry))["status"] == "effect_recovery_required"
    assert retry.runs == 0


async def test_an_unretainable_result_of_an_idempotent_tool_may_be_retried(factory, world):
    first = Tool(result={"handle": object()})
    assert (await go(world, first, effect=IDEM))["status"] == "effect_result_unavailable"
    second = Tool(result={"ok": True})
    assert (await go(world, second, effect=IDEM))["status"] == "success"
    assert (first.runs, second.runs) == (1, 1)
    (row,) = await rows(factory)
    assert row.attempt_count == 2


async def test_a_result_with_nan_is_not_retainable(factory, world):
    out = await go(world, Tool(result={"v": float("nan")}))
    assert out["status"] == "effect_result_unavailable"


# --- notifications are claimed once per logical invocation ------------------------------------


class _Notices:
    """An autonomy gate at level 2 whose notifier counts what it sends."""

    def __init__(self, monkeypatch, level=2):
        self.sent: list[dict] = []
        self.policy_reads = 0
        self.level = level

        async def loader(agent_id):
            self.policy_reads += 1
            return {}

        async def notifier(payload):
            self.sent.append(payload)

        monkeypatch.setattr(
            tool_factory,
            "build_autonomy_gate",
            lambda db, **kw: AutonomyGate(
                loader,
                approvals=None,
                notifier=notifier,
                default_level=self.level,
                notice_once=effects.claim_notice,
            ),
        )


async def test_the_first_call_sends_one_notice_and_a_completed_replay_sends_none(
    factory, world, monkeypatch
):
    notices = _Notices(monkeypatch)
    tool = Tool()
    await go(world, tool)
    assert len(notices.sent) == 1
    again = await go(world, tool)
    assert again["replayed"] is True and tool.runs == 1
    assert len(notices.sent) == 1
    # Policy is judged on every call, only the notice is deduplicated.
    assert notices.policy_reads == 2


async def test_racing_claims_for_one_slot_send_at_most_one_notice(factory, world, monkeypatch):
    notices = _Notices(monkeypatch)
    gate = asyncio.Event()
    tool = Tool(gate=gate)
    callers = [asyncio.create_task(go(world, tool)) for _ in range(6)]
    for _ in range(300):
        if tool.runs >= 1 and sum(c.done() for c in callers) >= 5:
            break
        await asyncio.sleep(0.01)
    gate.set()
    await asyncio.gather(*callers)
    assert tool.runs == 1 and len(notices.sent) == 1


async def test_a_changed_slot_gets_its_own_notice(factory, world, monkeypatch):
    notices = _Notices(monkeypatch)
    tool = Tool()
    await go(world, tool, slot=ToolSlot(0, 0))
    await go(world, tool, slot=ToolSlot(0, 1))
    await go(world, tool, slot=ToolSlot(0, 0))
    assert len(notices.sent) == 2 and tool.runs == 2


async def test_a_revoked_autonomy_blocks_the_replayed_result(factory, world, monkeypatch):
    notices = _Notices(monkeypatch)
    tool = Tool(result={"secret-looking": "result"})
    await go(world, tool)
    # The agent's autonomy is tightened to "needs approval" before the recovery.
    notices.level = 3
    again = await go(world, tool)
    assert again["status"] == "autonomy_blocked" and "replayed" not in again
    assert "result" not in again and tool.runs == 1


# --- a path that registers tools dynamically defaults to non-idempotent -----------------------


async def test_a_hermes_tool_registered_without_an_effect_runs_as_non_idempotent(
    factory, world
):
    from nexus.adapters.hermes_adapter import HermesAdapter

    calls = []

    async def handler(**arguments):
        calls.append(arguments)
        return {"done": True}

    adapter = HermesAdapter()
    adapter.register_tool("dynamic-tool", handler)
    ctx = turn_ctx(world)
    await adapter._execute_tool("dynamic-tool", {"a": 1}, context=ctx, slot=ToolSlot(0, 0))
    again = await adapter._execute_tool("dynamic-tool", {"a": 1}, context=ctx, slot=ToolSlot(0, 0))
    assert again["replayed"] is True and len(calls) == 1
    (row,) = await rows(factory)
    assert row.effect_class == "non_idempotent_write"
    # An ambiguous run of such a tool is never retried by a recovered turn.
    boom = Tool(raises=RuntimeError("reset"))

    async def failing(**arguments):
        return await boom()

    adapter.register_tool("flaky-tool", failing)
    out = await adapter._execute_tool("flaky-tool", {}, context=ctx, slot=ToolSlot(0, 1))
    assert out["status"] == "failed"
    out = await adapter._execute_tool("flaky-tool", {}, context=ctx, slot=ToolSlot(0, 1))
    assert out["status"] == "effect_recovery_required" and boom.runs == 1


async def test_a_hermes_write_without_a_slot_is_refused(factory, world):
    from nexus.adapters.hermes_adapter import HermesAdapter

    calls = []

    async def handler(**arguments):
        calls.append(arguments)
        return {}

    adapter = HermesAdapter()
    adapter.register_tool("dynamic-tool", handler)
    out = await adapter._execute_tool("dynamic-tool", {}, context=turn_ctx(world), slot=None)
    assert out["status"] == "effect_ledger_unavailable" and calls == []


async def test_a_tool_connection_call_is_ledgered_as_non_idempotent(factory, world):
    from nexus.adapters.mcp_adapter import MCPAgentAdapter
    from nexus.runtime.adapter import AgentSession

    class Client:
        is_connected = True

        def __init__(self):
            self.calls = []

        async def call_tool(self, name, arguments):
            self.calls.append(name)
            return MCPResult(content="done")

    adapter, client = MCPAgentAdapter(), Client()
    session = AgentSession(
        session_id=str(uuid.uuid4()), agent_id=world["agent"].id, adapter_type="mcp", config={}
    )
    session.context = turn_ctx(world)
    adapter._logs = {session.session_id: []}
    adapter._clients = {session.session_id: client}
    payload = {"tool_calls": [{"tool_name": "remote-write", "arguments": {"a": 1}},
                              {"tool_name": "remote-write", "arguments": {"a": 1}}]}
    await adapter._do_execute(session, uuid.uuid4(), payload)
    # Two identical calls at two positions are two writes.
    assert client.calls == ["remote-write", "remote-write"]
    recovered = await adapter._do_execute(session, uuid.uuid4(), payload)
    assert client.calls == ["remote-write", "remote-write"]  # replayed, not resent
    assert recovered.success is True
    assert {r.effect_class for r in await rows(factory)} == {"non_idempotent_write"}
    assert sorted((r.round_index, r.invocation_index) for r in await rows(factory)) == [
        (0, 0), (0, 1),
    ]


# --- Obsidian structured failures --------------------------------------------------------------


@pytest.mark.parametrize("status", sorted(OBSIDIAN_REJECTED_STATUSES))
def test_an_obsidian_rejection_status_is_a_retryable_failure(status):
    outcome = effects.outcome_of({"status": status, "reason": "r"}, OBSIDIAN_NOTE_REPLACE_NAME)
    assert outcome[0] == "failed"


@pytest.mark.parametrize("status", sorted(OBSIDIAN_UNCERTAIN_STATUSES))
def test_an_obsidian_uncertain_status_is_ambiguous(status):
    assert effects.outcome_of({"status": status}, OBSIDIAN_NOTE_REPLACE_NAME)[0] == "ambiguous"


def test_a_status_dict_from_any_other_tool_is_a_plain_result():
    assert effects.outcome_of({"status": "conflict"}, "other-tool")[0] == "succeeded"
    assert effects.outcome_of({"status": "conflict"})[0] == "succeeded"


async def test_an_obsidian_failure_dict_is_settled_as_a_failure_through_the_ledger(factory, world):
    await go(
        world,
        Tool(result={"status": "recovery_failure", "reason": "r"}),
        effect=IDEM,
        name=OBSIDIAN_NOTE_REPLACE_NAME,
    )
    (row,) = await rows(factory)
    assert row.status == "ambiguous"
    await go(
        world,
        Tool(result={"status": "conflict", "reason": "hash changed"}),
        effect=IDEM,
        name=OBSIDIAN_NOTE_REPLACE_NAME,
        slot=ToolSlot(0, 1),
    )
    statuses = {(r.invocation_index): r.status for r in await rows(factory)}
    assert statuses == {0: "ambiguous", 1: "failed"}
