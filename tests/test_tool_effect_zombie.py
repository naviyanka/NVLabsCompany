"""A worker that a recovery replaced (a zombie) can never open or replay a write.

The execution epoch ``(execution_id, attempt)`` is copied from the turn row when the runtime
claims the turn, and travels on the server-built ``ExecutionContext``. Before a ledgered write
reaches the autonomy gate, a grant, an approval, a notification or the ledger, it is compared
with the turn's current attempt; a difference is ``stale_execution`` and nothing happens. The
epoch is never refreshed from the database and no model, argument or header can set it.

The occupied-slot replay, the B4 block and the first write after a recovery are in
``test_tool_effect_recovery_epoch``; the PostgreSQL race is in ``test_tool_effects_postgres``.
"""

# ruff: noqa: F811 -- the imported fixtures are used by name, as elsewhere in the suite

from __future__ import annotations

import uuid
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import func, select

from nexus.models.chat_turn import ChatTurn
from nexus.models.tool_effect import ToolNotification
from nexus.tools import effects
from nexus.tools import factory as tool_factory
from nexus.tools.autonomy import AutonomyGate
from nexus.tools.effects import EffectClass, ToolSlot
from nexus.tools.factory import guarded_call
from tests.test_tool_effect_recovery_epoch import _epoch
from tests.test_tool_effects import (  # noqa: F401 -- fixtures and helpers
    IDEM,
    NON_IDEM,
    Tool,
    factory,
    go,
    rows,
    turn_ctx,
    world,
)

STALE = "stale_execution"


class _Approvals:
    """An approval store that records what is asked of it (nothing is ever decided)."""

    def __init__(self):
        self.requested: list[dict] = []

    async def get_async(self, approval_id):
        return None

    async def request_approval(self, **kwargs):
        self.requested.append(kwargs)


class _Gate:
    """Replaces the autonomy gate with one that counts approvals and notices."""

    def __init__(self, monkeypatch, level: int):
        self.sent: list[dict] = []
        self.approvals = _Approvals()

        async def loader(agent_id):
            return {}

        async def notifier(payload):
            self.sent.append(payload)

        monkeypatch.setattr(
            tool_factory,
            "build_autonomy_gate",
            lambda db, **kw: AutonomyGate(
                loader, approvals=self.approvals, notifier=notifier, default_level=level,
                notice_once=effects.claim_notice,
            ),
        )


async def _count(factory, model) -> int:
    async with factory() as db:
        return (await db.execute(select(func.count()).select_from(model))).scalar_one()


async def _move(factory, world, attempt: int, execution_id: str) -> None:
    """Put the turn at ``attempt`` under ``execution_id``, as a recovery's claim does."""
    await _epoch(factory, world, attempt)
    async with factory() as db:
        row = await db.get(ChatTurn, world["turn"])
        row.execution_id = execution_id
        db.add(row)
        await db.commit()


async def _recovered(factory, world, effect):
    """Attempt 1 wrote slot (0, 0); the turn then moved to attempt 2. Returns attempt 1's ctx."""
    await _epoch(factory, world, 1)
    await go(world, Tool(), effect=effect, slot=ToolSlot(0, 0))
    zombie = turn_ctx(world, attempt=1)
    await _epoch(factory, world, 2)
    return zombie


@pytest.mark.parametrize("level", [2, 3])
@pytest.mark.parametrize("slot", [ToolSlot(0, 0), ToolSlot(1, 0)], ids=["occupied", "empty"])
@pytest.mark.parametrize("effect", [NON_IDEM, IDEM], ids=["non_idempotent", "idempotent"])
async def test_a_stale_execution_is_refused_before_every_side_effect(
    factory, world, monkeypatch, effect, slot, level
):
    zombie = await _recovered(factory, world, effect)
    gate = _Gate(monkeypatch, level)
    notices_before = await _count(factory, ToolNotification)
    ledger_before = len(await rows(factory))
    tool = Tool()
    out = await go(world, tool, effect=effect, ctx=zombie, slot=slot)
    assert out["status"] == STALE and "replayed" not in out
    assert tool.runs == 0
    assert len(await rows(factory)) == ledger_before
    assert gate.sent == [] and gate.approvals.requested == []
    assert await _count(factory, ToolNotification) == notices_before
    # The recovery's own state is untouched by the zombie.
    async with factory() as db:
        assert (await db.get(ChatTurn, world["turn"])).attempt_count == 2


async def test_the_current_execution_does_reach_the_gate_so_the_counters_above_mean_something(
    factory, world, monkeypatch
):
    await _recovered(factory, world, NON_IDEM)
    gate = _Gate(monkeypatch, 3)
    tool = Tool()
    out = await go(world, tool, slot=ToolSlot(1, 0))  # the live attempt 2, a new slot
    assert out["status"] == "autonomy_blocked" and tool.runs == 0
    assert len(gate.approvals.requested) == 1


@pytest.mark.parametrize("effect", [NON_IDEM, IDEM], ids=["non_idempotent", "idempotent"])
async def test_a_stale_execution_cannot_replay_what_the_current_one_wrote(factory, world, effect):
    await _epoch(factory, world, 1)  # attempt 1 made no write
    zombie = turn_ctx(world, attempt=1)
    await _epoch(factory, world, 2)
    live = Tool()
    assert (await go(world, live, effect=effect, slot=ToolSlot(0, 0)))["status"] == "success"
    late = Tool()
    again = await go(world, late, effect=effect, ctx=zombie, slot=ToolSlot(0, 0))
    other = await go(world, late, effect=effect, ctx=zombie, slot=ToolSlot(0, 1))
    assert again["status"] == other["status"] == STALE and late.runs == 0
    assert len(await rows(factory)) == 1


async def test_a_forged_epoch_in_the_arguments_changes_nothing(factory, world):
    zombie = await _recovered(factory, world, NON_IDEM)
    forged = {
        "turn_attempt": 2, "attempt_count": 2, "execution_id": "x", "recovering": False,
        "turn_execution": "x", "nexus_invocation_key": "k-1",
    }
    tool = Tool()
    out = await go(world, tool, ctx=zombie, args=forged, slot=ToolSlot(1, 0))
    assert out["status"] == STALE and tool.runs == 0
    # And the live execution is judged by the row, not by what the arguments claim.
    live = await go(world, tool, args={**forged, "turn_attempt": 1}, slot=ToolSlot(1, 0))
    assert live["status"] == "effect_recovery_required" and tool.runs == 0


async def test_a_write_with_no_epoch_is_refused(factory, world):
    await _epoch(factory, world, 1)
    bare = replace(turn_ctx(world), turn_attempt=None)
    tool = Tool()
    out = await go(world, tool, ctx=bare)
    assert out["status"] == STALE and tool.runs == 0 and await rows(factory) == []


async def test_a_stale_epoch_is_not_refreshed_from_the_database(factory, world):
    await _epoch(factory, world, 1)
    zombie = turn_ctx(world, attempt=1)
    await _epoch(factory, world, 2)
    tool = Tool()
    for slot in (ToolSlot(0, 0), ToolSlot(0, 0)):  # it stays stale however often it retries
        assert (await go(world, tool, ctx=zombie, slot=slot))["status"] == STALE
    assert tool.runs == 0 and zombie.turn_attempt == 1


async def test_reads_are_not_fenced_and_never_touch_the_epoch(factory, world):
    zombie = await _recovered(factory, world, NON_IDEM)
    tool = Tool()
    out = await go(world, tool, effect=EffectClass.READ_ONLY, ctx=zombie, slot=None)
    assert out["status"] == "success" and tool.runs == 1
    assert len(await rows(factory)) == 1
    async with factory() as db:
        assert (await db.get(ChatTurn, world["turn"])).attempt_count == 2


async def test_the_other_company_s_turn_row_is_not_this_turns_epoch(factory, world):
    await _epoch(factory, world, 1)
    zombie = turn_ctx(world, attempt=1)
    async with factory() as db:  # the same id under another company is somebody else's turn
        row = await db.get(ChatTurn, world["turn"])
        row.company_id = world["other"]
        db.add(row)
        await db.commit()
    tool = Tool()
    assert (await go(world, tool, ctx=zombie))["status"] == "success" and tool.runs == 1


# --- the legacy chat path: a real ``_call_llm`` hands the claimed epoch to the tool context ---


async def test_the_chat_route_fences_a_tool_write_of_a_replaced_worker(
    factory, world, monkeypatch
):
    from nexus.api.routes import chat as chat_routes

    await _move(factory, world, 1, "exec-1")
    seen: list[dict] = []
    ran: list[int] = []

    class Adapter:
        async def create_session(self, agent_id, config):
            return SimpleNamespace(context=None, worktree_path=None)

        async def execute_task(self, session, task_id, payload):
            async def write():
                ran.append(1)
                return {"ok": True}

            seen.append(
                await guarded_call(
                    session.context, "send-it", {"to": "a"}, write, source="hermes",
                    effect=NON_IDEM.value, slot=ToolSlot(0, 0),
                )
            )
            return SimpleNamespace(
                success=True, output="done", input_tokens=1, output_tokens=1, artifacts=[],
                error=None,
            )

        async def terminate(self, session):
            return None

    class Registry:
        def is_self_metered(self, key):
            return False

        def create_adapter(self, key):
            return Adapter()

    monkeypatch.setattr("nexus.adapters.registry.AdapterRegistry", Registry)
    monkeypatch.setattr(chat_routes, "_resolve_connection", AsyncMock(return_value=None))
    monkeypatch.setattr(chat_routes, "_resolve_adapter_type", lambda agent, conn=None: ("fake", {}))
    monkeypatch.setattr(chat_routes, "_reserve_budget", AsyncMock(return_value=None))
    monkeypatch.setattr(chat_routes, "_settle_budget", AsyncMock())
    monkeypatch.setattr(chat_routes, "_remember_response", AsyncMock(return_value=0))
    agent = world["agent"]

    async def worker(epoch):
        await chat_routes._call_llm(
            agent, "sys", "hi", [], turn_id=world["turn"], turn_epoch=epoch,
            execution={"execution_id": str(uuid.uuid4())},
        )
        return seen[-1]["status"]

    # The live execution (attempt 1) writes once.
    assert await worker(("exec-1", 1)) == "success" and ran == [1]
    # A recovery advances the turn; the old worker, still holding epoch 1, wakes up and tries.
    await _move(factory, world, 2, "exec-2")
    assert await worker(("exec-1", 1)) == STALE and ran == [1]
    # Even an attempt number that matches is stale when the execution id is not the row's.
    assert await worker(("exec-1", 2)) == STALE and ran == [1]
    # A worker that was given no epoch cannot write either.
    assert await worker(None) == STALE and ran == [1]
    # The recovery's own execution replays the occupied slot, and runs nothing.
    assert await worker(("exec-2", 2)) == "success" and ran == [1]
    assert len(await rows(factory)) == 1
