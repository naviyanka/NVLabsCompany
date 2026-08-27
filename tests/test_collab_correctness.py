"""Tests for Wave 4 collaboration correctness (Phases 4.1-4.3)."""

import asyncio
import uuid

import pytest

from nexus.communication.a2a_router import (
    A2AMessage,
    A2ARouter,
    CommunicationMode,
    correlation_id_for,
    execution_id_for,
)
from nexus.communication.group import GroupManager, HandoffIntent
from nexus.communication.permits import DEFAULT_SUBAGENT_CAP, SubagentPermits
from nexus.runtime.cycle_guard import CycleGuardError


def _delegation(sender, recipient, correlation_id):
    return A2AMessage(
        id=uuid.uuid4(),
        sender=sender,
        recipient=recipient,
        mode=CommunicationMode.delegate,
        payload={"task": "review"},
        correlation_id=correlation_id,
    )


class TestIdempotentA2A:
    """Phase 4.1 - deterministic IDs and delegation dedupe on replay."""

    def test_correlation_id_deterministic(self):
        run, call = uuid.uuid4(), "call-1"
        assert correlation_id_for(run, call) == correlation_id_for(run, call)

    def test_correlation_id_varies_per_tool_call(self):
        run = uuid.uuid4()
        assert correlation_id_for(run, "call-1") != correlation_id_for(run, "call-2")

    def test_execution_id_deterministic_and_distinct(self):
        run, call = uuid.uuid4(), "call-1"
        assert execution_id_for(run, call) == execution_id_for(run, call)
        assert str(execution_id_for(run, call)) != correlation_id_for(run, call)

    def test_replay_produces_one_delegation(self):
        router = A2ARouter()
        sender, recipient = uuid.uuid4(), uuid.uuid4()
        corr = correlation_id_for(uuid.uuid4(), "call-1")

        first = router.send(_delegation(sender, recipient, corr))
        second = router.send(_delegation(sender, recipient, corr))

        assert second is first
        assert len(router.get_execution_chain()) == 1

    def test_distinct_correlation_ids_produce_two_delegations(self):
        router = A2ARouter()
        sender, recipient = uuid.uuid4(), uuid.uuid4()
        run = uuid.uuid4()

        router.send(_delegation(sender, recipient, correlation_id_for(run, "c1")))
        router.send(_delegation(sender, recipient, correlation_id_for(run, "c2")))

        assert len(router.get_execution_chain()) == 2


class TestSubagentPermits:
    """Phase 4.2 - concurrency cap with release on every terminal path."""

    def test_default_cap(self):
        assert SubagentPermits().cap == DEFAULT_SUBAGENT_CAP == 3

    def test_rejects_zero_cap(self):
        with pytest.raises(ValueError):
            SubagentPermits(cap=0)

    @pytest.mark.asyncio
    async def test_ten_subtasks_run_at_most_cap_concurrently(self):
        permits = SubagentPermits(cap=3)
        lead = uuid.uuid4()
        live = 0
        peak = 0

        async def subtask():
            nonlocal live, peak
            async with permits.permit(lead) as ok:
                assert ok
                live += 1
                peak = max(peak, live)
                await asyncio.sleep(0.01)
                live -= 1

        await asyncio.gather(*(subtask() for _ in range(10)))

        assert peak == 3
        assert permits.held(lead) == 0
        assert permits.available(lead) == 3

    @pytest.mark.asyncio
    async def test_waits_when_cap_reached(self):
        permits = SubagentPermits(cap=1)
        lead = uuid.uuid4()

        assert await permits.acquire_subagent_permit(lead)
        assert await permits.acquire_subagent_permit(lead, timeout=0.01) is False

        permits.release_subagent_permit(lead)
        assert await permits.acquire_subagent_permit(lead, timeout=0.01)

    @pytest.mark.asyncio
    async def test_crashed_child_releases_permit(self):
        permits = SubagentPermits(cap=1)
        lead = uuid.uuid4()

        with pytest.raises(RuntimeError):
            async with permits.permit(lead) as ok:
                assert ok
                raise RuntimeError("child killed")

        assert permits.held(lead) == 0
        assert await permits.acquire_subagent_permit(lead, timeout=0.01)

    @pytest.mark.asyncio
    async def test_double_release_is_ignored(self):
        permits = SubagentPermits(cap=2)
        lead = uuid.uuid4()

        await permits.acquire_subagent_permit(lead)
        assert permits.release_subagent_permit(lead) is True
        assert permits.release_subagent_permit(lead) is False
        assert permits.available(lead) == 2

    @pytest.mark.asyncio
    async def test_release_all_sweeps_a_lead(self):
        permits = SubagentPermits(cap=3)
        lead = uuid.uuid4()

        for _ in range(3):
            await permits.acquire_subagent_permit(lead)
        assert permits.release_all(lead) == 3
        assert permits.held(lead) == 0

    @pytest.mark.asyncio
    async def test_caps_are_per_lead(self):
        permits = SubagentPermits(cap=1)
        lead_a, lead_b = uuid.uuid4(), uuid.uuid4()

        assert await permits.acquire_subagent_permit(lead_a)
        assert await permits.acquire_subagent_permit(lead_b, timeout=0.01)


class TestFrozenHandoffIntent:
    """Phase 4.3 - staged then frozen intent, applied exactly once."""

    async def _group(self, gm, members):
        return await gm.create_group(
            company_id=uuid.uuid4(), name="Handoff", agent_ids=members
        )

    @pytest.mark.asyncio
    async def test_intent_is_frozen(self):
        gm = GroupManager()
        a, b = uuid.uuid4(), uuid.uuid4()
        group = await self._group(gm, [a, b])

        intent = gm.stage_handoff(group.id, a, b, "take #42", mention_targets=[b])

        assert isinstance(intent, HandoffIntent)
        assert intent.metadata["mention_targets"] == [str(b)]
        with pytest.raises(Exception):
            intent.to_agent_id = uuid.uuid4()  # type: ignore[misc]
        with pytest.raises(TypeError):
            intent.metadata["handoff"] = False  # type: ignore[index]

    @pytest.mark.asyncio
    async def test_handoff_delivers_exactly_once(self):
        gm = GroupManager()
        a, b = uuid.uuid4(), uuid.uuid4()
        group = await self._group(gm, [a, b])

        intent = gm.stage_handoff(group.id, a, b, "take #42", correlation_id="h-1")
        first = await gm.deliver_handoff(intent)
        second = await gm.deliver_handoff(intent)

        assert second is first
        history = await gm.get_group_history(group.id)
        assert len([m for m in history if m.message_type == "handoff"]) == 1

    @pytest.mark.asyncio
    async def test_cycle_a_to_b_to_a_is_refused(self):
        gm = GroupManager()
        a, b = uuid.uuid4(), uuid.uuid4()
        group = await self._group(gm, [a, b])

        await gm.handoff_in_group(group.id, a, b, "A hands to B")
        with pytest.raises(CycleGuardError):
            await gm.handoff_in_group(group.id, b, a, "B hands back to A")

    @pytest.mark.asyncio
    async def test_forward_chain_allowed(self):
        gm = GroupManager()
        a, b, c = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
        group = await self._group(gm, [a, b, c])

        assert await gm.handoff_in_group(group.id, a, b, "to B") is not None
        assert await gm.handoff_in_group(group.id, b, c, "to C") is not None

    @pytest.mark.asyncio
    async def test_missing_group_returns_none(self):
        gm = GroupManager()
        assert gm.stage_handoff(uuid.uuid4(), uuid.uuid4(), uuid.uuid4(), "x") is None
        assert (
            await gm.handoff_in_group(uuid.uuid4(), uuid.uuid4(), uuid.uuid4(), "x")
            is None
        )
