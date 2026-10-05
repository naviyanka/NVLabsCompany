"""A recovered execution of a turn may replay its earlier writes but not open new ones.

``ChatTurn.attempt_count`` is the recovery epoch: the server reads it from the turn row, so
neither a model nor an HTTP client can set it. Once an earlier execution of the turn claimed a
write, a later execution may only reach slots that are already occupied (and then only with the
same call). A write at an empty slot is ``effect_recovery_required``: the model may have planned
the same write at another position and nothing durable says which positions were planned.
Fixtures come from ``tests.test_tool_effects``.
"""

# ruff: noqa: F811 -- the imported fixtures are used by name, as elsewhere in the suite

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import update

from nexus.models.chat_turn import ChatTurn
from nexus.tools.context import ExecutionContext
from nexus.tools.effects import EffectClass, ToolSlot
from tests.test_tool_effects import (  # noqa: F401 -- fixtures and helpers
    IDEM,
    NON_IDEM,
    Tool,
    factory,
    go,
    rows,
    world,
)

READ = EffectClass.READ_ONLY


async def _epoch(factory, world, attempt: int) -> None:
    """Put the turn in execution number ``attempt`` (creating its row on first use).

    The world's current execution moves with it, so ``go`` runs as the live worker; a test of a
    stale worker passes ``ctx=turn_ctx(world, attempt=<old>)`` itself.
    """
    world["attempt"] = attempt
    async with factory() as db:
        done = await db.execute(
            update(ChatTurn).where(ChatTurn.id == world["turn"]).values(attempt_count=attempt)
        )
        if done.rowcount == 0:
            db.add(
                ChatTurn(
                    id=world["turn"], company_id=world["acme"], agent_id=world["agent"].id,
                    session_id=uuid.uuid4(), idempotency_key=uuid.uuid4().hex, turn_seq=1,
                    status="running", attempt_count=attempt,
                )
            )
        await db.commit()


def _ctx(world):
    from tests.test_tool_effects import turn_ctx

    return turn_ctx(world)


async def test_the_same_write_at_its_original_slot_replays(factory, world):
    await _epoch(factory, world, 1)
    first = Tool()
    await go(world, first, slot=ToolSlot(0, 0))
    await _epoch(factory, world, 2)
    again = Tool()
    out = await go(world, again, slot=ToolSlot(0, 0))
    assert out["status"] == "success" and out["replayed"] is True
    assert (first.runs, again.runs) == (1, 0)


@pytest.mark.parametrize("effect", [NON_IDEM, IDEM])
async def test_the_same_write_shifted_to_an_empty_slot_is_blocked(factory, world, effect):
    await _epoch(factory, world, 1)
    first = Tool()
    await go(world, first, effect=effect, slot=ToolSlot(0, 0))
    await _epoch(factory, world, 2)
    shifted = Tool()
    out = await go(world, shifted, effect=effect, slot=ToolSlot(1, 0))
    assert out["status"] == "effect_recovery_required"
    assert shifted.runs == 0 and first.runs == 1
    assert len(await rows(factory)) == 1  # the blocked call left no row behind


async def test_a_new_write_in_a_normal_turn_is_allowed(factory, world):
    await _epoch(factory, world, 1)
    first, second = Tool(), Tool()
    await go(world, first, slot=ToolSlot(0, 0))
    out = await go(world, second, args={"to": "b"}, slot=ToolSlot(1, 0))
    assert out["status"] == "success" and (first.runs, second.runs) == (1, 1)


async def test_a_recovered_turn_with_no_earlier_write_may_write(factory, world):
    await _epoch(factory, world, 2)
    first, second = Tool(), Tool()
    assert (await go(world, first, slot=ToolSlot(0, 0)))["status"] == "success"
    # Rows this execution made do not count as earlier writes.
    out = await go(world, second, args={"to": "b"}, slot=ToolSlot(1, 0))
    assert out["status"] == "success" and (first.runs, second.runs) == (1, 1)


async def test_reordered_occupied_calls_fail_closed(factory, world):
    await _epoch(factory, world, 1)
    await go(world, Tool(), args={"to": "a"}, slot=ToolSlot(0, 0))
    await go(world, Tool(), args={"to": "b"}, slot=ToolSlot(0, 1))
    await _epoch(factory, world, 2)
    swapped_a, swapped_b = Tool(), Tool()
    one = await go(world, swapped_b, args={"to": "b"}, slot=ToolSlot(0, 0))
    two = await go(world, swapped_a, args={"to": "a"}, slot=ToolSlot(0, 1))
    assert one["status"] == two["status"] == "effect_recovery_required"
    assert swapped_a.runs == swapped_b.runs == 0


async def test_an_extra_earlier_read_only_round_cannot_shift_a_write_into_an_empty_slot(
    factory, world
):
    await _epoch(factory, world, 1)
    await go(world, Tool(), slot=ToolSlot(0, 0))
    await _epoch(factory, world, 2)
    read, write = Tool(), Tool()
    # Recovery spends round 0 on a read, so the write it planned lands in round 1.
    assert (await go(world, read, effect=READ, slot=ToolSlot(0, 0)))["status"] == "success"
    out = await go(world, write, slot=ToolSlot(1, 0))
    assert read.runs == 1 and write.runs == 0
    assert out["status"] == "effect_recovery_required"


async def test_the_recovery_epoch_cannot_be_supplied_by_the_caller(factory, world):
    await _epoch(factory, world, 1)
    await go(world, Tool(), slot=ToolSlot(0, 0))
    await _epoch(factory, world, 2)
    forged = {"to": "a", "attempt_count": 1, "turn_attempt": 1, "recovering": False}
    tool = Tool()
    out = await go(world, tool, args=forged, slot=ToolSlot(1, 0))
    assert out["status"] == "effect_recovery_required" and tool.runs == 0
    # The only epoch field on the context is the one server code captured; no flag can relax it.
    assert not {"attempt_count", "recovering"} & set(ExecutionContext.__slots__)
    with pytest.raises(TypeError):
        ExecutionContext.from_dict({**_ctx(world).to_dict(), "recovering": False})


async def test_the_turn_of_another_company_does_not_make_this_one_recovered(factory, world):
    # A turn row of the same id under another company must not be read as this turn's epoch.
    async with factory() as db:
        db.add(
            ChatTurn(
                id=world["turn"], company_id=world["other"], agent_id=world["agent"].id,
                session_id=uuid.uuid4(), idempotency_key=uuid.uuid4().hex, turn_seq=1,
                status="running", attempt_count=5,
            )
        )
        await db.commit()
    first, second = Tool(), Tool()
    await go(world, first, slot=ToolSlot(0, 0))
    out = await go(world, second, args={"to": "b"}, slot=ToolSlot(1, 0))
    assert out["status"] == "success" and (first.runs, second.runs) == (1, 1)
