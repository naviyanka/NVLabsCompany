"""Phase 4.2 — delegation permits cap concurrent sub-agents per lead."""

import asyncio
import contextlib
import uuid

from nexus.company.delegation import DelegationEngine


async def test_ten_subtasks_run_at_most_three_concurrently():
    engine = DelegationEngine(subagent_cap=3)
    lead = uuid.uuid4()
    live = 0
    peak = 0

    async def child(n: int) -> None:
        nonlocal live, peak
        async with engine.subagent_permit(lead, f"child-{n}") as granted:
            assert granted
            live += 1
            peak = max(peak, live)
            await asyncio.sleep(0.01)
            live -= 1

    await asyncio.gather(*(child(n) for n in range(10)))
    assert peak == 3
    assert engine.held_subagent_permits(lead) == 0


async def test_killed_child_releases_permit():
    engine = DelegationEngine(subagent_cap=1)
    lead = uuid.uuid4()

    async def child() -> None:
        async with engine.subagent_permit(lead, "doomed"):
            await asyncio.sleep(10)

    task = asyncio.create_task(child())
    await asyncio.sleep(0.01)
    assert engine.held_subagent_permits(lead) == 1
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task
    assert engine.held_subagent_permits(lead) == 0
    # Slot is reusable after the kill.
    assert await engine.acquire_subagent_permit(lead, "next", timeout=0.05)


async def test_cap_is_per_lead_and_acquire_release_are_idempotent():
    engine = DelegationEngine(subagent_cap=1)
    lead_a, lead_b = uuid.uuid4(), uuid.uuid4()

    assert await engine.acquire_subagent_permit(lead_a, "h1")
    # Re-acquire for the same holder does not consume a second slot.
    assert await engine.acquire_subagent_permit(lead_a, "h1")
    # A different lead has its own budget.
    assert await engine.acquire_subagent_permit(lead_b, "h1", timeout=0.05)
    # lead_a is full — a second holder waits and times out.
    assert not await engine.acquire_subagent_permit(lead_a, "h2", timeout=0.05)

    assert engine.release_subagent_permit(lead_a, "h1")
    assert not engine.release_subagent_permit(lead_a, "h1")  # double release is a no-op
    assert await engine.acquire_subagent_permit(lead_a, "h2", timeout=0.05)
