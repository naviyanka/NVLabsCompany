"""A temporary allow must really allow, and be spent exactly once per real invocation.

The simulator, the effective-access matrix and the real ``guarded_call`` are asked the same
question and must agree. Reads (simulator, matrix) never spend a use.
"""

from __future__ import annotations

import asyncio
import dataclasses
import uuid
from datetime import timedelta
from typing import Any

import pytest
from sqlmodel import select

from nexus.models.governance_studio import GovernanceGrantUse, GovernanceTempAccess
from nexus.models.tool import ToolProfile, ToolProfileBinding
from nexus.models.tool_effect import ToolEffect
from nexus.tools import effects, governance_overlay
from nexus.tools.effects import EffectClass, ToolSlot
from nexus.tools.factory import guarded_call
from tests.test_governance_grants import (  # noqa: F401 -- fixtures and helpers
    HIRE,
    READ,
    _active_allow,
    _create,
    _decide,
)
from tests.test_governance_studio import _eff, _policy, api  # noqa: F401 -- fixtures, helpers
from tests.test_tool_access import ctx, factory, t  # noqa: F401 -- fixtures and helper

CAP = {HIRE: "org.ceo_request_hire", READ: "org.ceo_list_managers"}


async def _close(factory, t):  # noqa: F811
    """Company-wide default deny, so a safe read tool is denied until something allows it."""
    async with factory() as db:
        profile = ToolProfile(company_id=t["acme"], name="closed", default_action="deny")
        db.add(profile)
        await db.flush()
        db.add(ToolProfileBinding(company_id=t["acme"], profile_id=profile.id,
                                  target_type="agent", target_id=t["a"]))
        await db.commit()


async def _sim(api, t, tool) -> str:  # noqa: F811
    body = {"agent_id": str(t["a"]), "capability_id": CAP[tool]}
    r = await api("POST", "/simulate", body)
    assert r.status_code == 200, r.text
    return r.json()["current"]["decision"]


async def _three_ways(api, factory, t, tool) -> tuple[bool, bool, bool]:  # noqa: F811
    """(simulator allows, matrix allows, runtime allows) for the exact tool."""
    sim = await _sim(api, t, tool) == "allow"
    matrix = (await _eff(factory, t))[CAP[tool]]["decision"] == "allow"
    runtime = (await _decide(factory, t, tool=tool)).allowed
    return sim, matrix, runtime


async def _row(factory, grant_id) -> GovernanceTempAccess:  # noqa: F811
    async with factory() as db:
        return await db.get(GovernanceTempAccess, uuid.UUID(grant_id))


def _call(t, tool=READ, args=None, slot=ToolSlot(0, 0), effect=None, **ctx_over):  # noqa: F811
    if "turn_id" in ctx_over:
        ctx_over.setdefault("turn_attempt", 1)  # the epoch the runtime captured at the claim
    context = dataclasses.replace(ctx(t), **ctx_over)
    ran: list[int] = []

    async def run():
        ran.append(1)
        return "ok"

    async def go() -> dict[str, Any]:
        return await guarded_call(context, tool, args or {}, run, source="test",
                                  default_risk="write", slot=slot, effect=effect)

    return go, ran


class TestTemporaryAllowActuallyAllows:
    async def test_safe_default_denied_capability_is_allowed_by_a_valid_grant(
        self, api, factory, t  # noqa: F811
    ):
        await _close(factory, t)
        assert await _three_ways(api, factory, t, READ) == (False, False, False)
        await _create(api, t, tool=READ)
        assert await _three_ways(api, factory, t, READ) == (True, True, True)

    async def test_high_risk_capability_needs_an_approved_grant_for_that_exact_tool(
        self, api, factory, t  # noqa: F811
    ):
        assert await _three_ways(api, factory, t, HIRE) == (False, False, False)
        g = await _create(api, t)  # pending approval
        assert await _three_ways(api, factory, t, HIRE) == (False, False, False)
        await api("POST", f"/grants/{g['id']}/approve", {}, who="second_admin")
        assert await _three_ways(api, factory, t, HIRE) == (True, True, True)
        # A grant for another tool is no wildcard.
        assert not (await _decide(factory, t, tool="ceo_record_decision")).allowed

    async def test_an_active_row_without_approval_grants_nothing(self, api, factory, t):  # noqa: F811
        g = await _create(api, t)  # pending; force it active without the approval
        async with factory() as db:
            row = await db.get(GovernanceTempAccess, uuid.UUID(g["id"]))
            row.status = "active"
            db.add(row)
            await db.commit()
        assert await _three_ways(api, factory, t, HIRE) == (False, False, False)

    async def test_grant_cannot_bypass_an_explicit_deny(self, api, factory, t):  # noqa: F811
        await _active_allow(api, t)
        await _policy(factory, t["acme"], name="freeze hiring", effect="deny",
                      conditions={"tool_name": [HIRE]})
        assert await _three_ways(api, factory, t, HIRE) == (False, False, False)

    async def test_temporary_deny_beats_a_temporary_allow(self, api, factory, t):  # noqa: F811
        await _active_allow(api, t)
        await _create(api, t, effect="deny")
        assert await _three_ways(api, factory, t, HIRE) == (False, False, False)

    async def test_guarded_call_runs_the_tool_only_when_the_grant_allows(
        self, api, factory, t  # noqa: F811
    ):
        go, ran = _call(t, HIRE)
        assert (await go())["status"] == "denied" and ran == []
        await _active_allow(api, t)
        assert (await go())["status"] == "success" and ran == [1]


class TestConsumption:
    async def test_reads_never_spend_a_use(self, api, factory, t):  # noqa: F811
        g = await _active_allow(api, t, max_uses=1)
        for _ in range(3):
            await _three_ways(api, factory, t, HIRE)
            assert (await api("GET", "/grants")).status_code == 200
            assert (await api("GET", f"/agents/{t['a']}/effective-access")).status_code == 200
            assert (await api("GET", "/catalog")).status_code == 200
        row = await _row(factory, g["id"])
        assert (row.used_count, row.status) == (0, "active")

    async def test_a_real_invocation_spends_exactly_one_use(self, api, factory, t):  # noqa: F811
        g = await _active_allow(api, t, max_uses=3)
        go, ran = _call(t, HIRE)
        assert (await go())["status"] == "success"
        row = await _row(factory, g["id"])
        assert (row.used_count, row.status, ran) == (1, "active", [1])

    async def test_last_use_marks_the_grant_used_up_and_the_next_call_is_denied(
        self, api, factory, t  # noqa: F811
    ):
        g = await _active_allow(api, t, max_uses=1)
        go, ran = _call(t, HIRE)
        assert (await go())["status"] == "success"
        assert (await _row(factory, g["id"])).status == "used_up"
        assert (await go())["status"] == "denied" and ran == [1]

    async def test_a_denied_request_spends_nothing(self, api, factory, t):  # noqa: F811
        g = await _active_allow(api, t, max_uses=2)
        await _policy(factory, t["acme"], name="freeze hiring", effect="deny",
                      conditions={"tool_name": [HIRE]})
        go, ran = _call(t, HIRE)
        assert (await go())["status"] == "denied" and ran == []
        # Denied by a role check that runs before the grant is even read.
        viewer, ran_v = _call(t, HIRE, principal_role="viewer")
        assert (await viewer())["status"] == "denied" and ran_v == []
        assert (await _row(factory, g["id"])).used_count == 0

    async def test_a_pending_grant_spends_nothing(self, api, factory, t):  # noqa: F811
        g = await _create(api, t, max_uses=2)
        go, _ = _call(t, HIRE)
        assert (await go())["status"] == "denied"
        assert (await _row(factory, g["id"])).used_count == 0

    async def test_a_downstream_tool_failure_still_spends_the_use(self, api, factory, t):  # noqa: F811
        g = await _active_allow(api, t, max_uses=2)

        async def boom():
            raise RuntimeError("tool failed")

        with pytest.raises(RuntimeError):
            await guarded_call(ctx(t), HIRE, {}, boom, source="test", default_risk="write")
        assert (await _row(factory, g["id"])).used_count == 1

    async def test_a_replay_of_one_invocation_is_not_charged_twice(self, api, factory, t):  # noqa: F811
        g = await _active_allow(api, t, max_uses=3)
        turn = uuid.uuid4()
        go, ran = _call(t, HIRE, {"k": 1}, turn_id=turn)
        assert (await go())["status"] == "success"
        assert (await go())["status"] == "success"
        # The tool is undeclared, so it is a non-idempotent write: the second call replays the
        # recorded result instead of running the tool again, and the grant is charged once.
        assert (await _row(factory, g["id"])).used_count == 1 and ran == [1]
        # A different invocation (the next slot of the turn, or another turn) pays again.
        other, _ = _call(t, HIRE, {"k": 2}, slot=ToolSlot(0, 1), turn_id=turn)
        assert (await other())["status"] == "success"
        fresh, _ = _call(t, HIRE, {"k": 1}, turn_id=uuid.uuid4())
        assert (await fresh())["status"] == "success"
        assert (await _row(factory, g["id"])).used_count == 3
        async with factory() as db:
            ledger = (await db.execute(select(GovernanceGrantUse))).scalars().all()
        assert len(ledger) == 3

    async def test_a_replay_after_revoke_is_denied(self, api, factory, t):  # noqa: F811
        g = await _active_allow(api, t, max_uses=3)
        go, _ = _call(t, HIRE, turn_id=uuid.uuid4())
        assert (await go())["status"] == "success"
        await api("POST", f"/grants/{g['id']}/revoke", {"reason": "done with it"})
        assert (await go())["status"] == "denied"

    async def test_concurrent_one_use_invocations_have_one_winner(self, api, factory, t):  # noqa: F811
        g = await _active_allow(api, t, max_uses=1)
        go, ran = _call(t, HIRE)
        results = await asyncio.gather(*(go() for _ in range(5)))
        assert [r["status"] for r in results].count("success") == 1 and ran == [1]
        assert (await _row(factory, g["id"])).used_count == 1

    @pytest.mark.parametrize("fate", ["revoked", "expired"])
    async def test_revoke_or_expiry_before_the_spend_wins(self, api, factory, t, fate):  # noqa: F811
        g = await _active_allow(api, t, max_uses=2)
        async with factory() as db:
            row = await db.get(GovernanceTempAccess, uuid.UUID(g["id"]))
            if fate == "revoked":
                row.status = "revoked"
            else:
                row.expires_at = governance_overlay.now() - timedelta(seconds=1)
            db.add(row)
            await db.commit()
        async with factory() as db:
            spent = await governance_overlay.consume_temp_grant(
                db, t["acme"], uuid.UUID(g["id"]), key="k" * 64
            )
            await db.commit()
        assert spent is False and (await _row(factory, g["id"])).used_count == 0

    async def test_other_tenants_cannot_tell_whether_a_grant_exists(self, api, t):  # noqa: F811
        g = await _create(api, t, tool=READ)
        real = await api("POST", f"/grants/{g['id']}/revoke", {"reason": "not yours"},
                         who="outsider")
        ghost = await api("POST", f"/grants/{uuid.uuid4()}/revoke", {"reason": "not yours"},
                          who="outsider")
        assert real.status_code == ghost.status_code == 404
        assert real.json() == ghost.json()
        listed = (await api("GET", "/grants", who="outsider")).json()["items"]
        assert g["id"] not in [i["id"] for i in listed]


async def _uses(factory, grant_id) -> list[str]:  # noqa: F811
    async with factory() as db:
        rows = (await db.execute(select(GovernanceGrantUse))).scalars().all()
    return sorted(r.invocation_key for r in rows if str(r.grant_id) == grant_id)


class TestUseIsScopedToTheSlot:
    """A use is paid per durable slot (company, turn, round, position), never per content."""

    async def test_identical_calls_at_two_slots_with_one_use_run_exactly_once(
        self, api, factory, t  # noqa: F811
    ):
        g = await _active_allow(api, t, max_uses=1)
        turn = uuid.uuid4()
        first, ran = _call(t, HIRE, {"k": 1}, turn_id=turn)
        second, ran2 = _call(t, HIRE, {"k": 1}, slot=ToolSlot(0, 1), turn_id=turn)
        assert (await first())["status"] == "success"
        assert (await second())["status"] == "denied"
        assert ran == [1] and ran2 == []
        assert (await _row(factory, g["id"])).used_count == 1
        assert len(await _uses(factory, g["id"])) == 1

    async def test_two_uses_allow_two_slots_and_never_a_third(self, api, factory, t):  # noqa: F811
        g = await _active_allow(api, t, max_uses=2)
        turn = uuid.uuid4()
        statuses, ran_total = [], 0
        for position in range(3):
            go, ran = _call(t, HIRE, {"k": 1}, slot=ToolSlot(0, position), turn_id=turn)
            statuses.append((await go())["status"])
            ran_total += len(ran)
        assert statuses == ["success", "success", "denied"] and ran_total == 2
        row = await _row(factory, g["id"])
        assert (row.used_count, row.status) == (2, "used_up")
        assert len(await _uses(factory, g["id"])) == 2

    async def test_reordering_does_not_move_a_use_between_slots(self, api, factory, t):  # noqa: F811
        g = await _active_allow(api, t, max_uses=1)
        turn = uuid.uuid4()
        later, ran = _call(t, HIRE, {"k": "b"}, slot=ToolSlot(0, 1), turn_id=turn)
        earlier, ran_e = _call(t, HIRE, {"k": "a"}, slot=ToolSlot(0, 0), turn_id=turn)
        assert (await later())["status"] == "success"  # the use now belongs to slot (0, 1)
        assert (await earlier())["status"] == "denied" and ran_e == []
        again = await later()  # and it replays there
        assert again["status"] == "success" and again["replayed"] is True and ran == [1]
        assert (await _row(factory, g["id"])).used_count == 1

    async def test_a_replay_of_the_slot_that_took_the_last_use_is_not_refused_or_recharged(
        self, api, factory, t  # noqa: F811
    ):
        g = await _active_allow(api, t, max_uses=1)
        go, ran = _call(t, HIRE, turn_id=uuid.uuid4())
        assert (await go())["status"] == "success"
        assert (await _row(factory, g["id"])).status == "used_up"
        again = await go()
        assert again["status"] == "success" and again["replayed"] is True
        assert ran == [1] and (await _row(factory, g["id"])).used_count == 1
        assert len(await _uses(factory, g["id"])) == 1

    async def test_a_replay_of_a_used_up_slot_is_still_refused_once_the_grant_expires(
        self, api, factory, t  # noqa: F811
    ):
        g = await _active_allow(api, t, max_uses=1)
        go, ran = _call(t, HIRE, turn_id=uuid.uuid4())
        assert (await go())["status"] == "success"
        async with factory() as db:
            row = await db.get(GovernanceTempAccess, uuid.UUID(g["id"]))
            row.expires_at = governance_overlay.now() - timedelta(seconds=1)
            db.add(row)
            await db.commit()
        assert (await go())["status"] == "denied" and ran == [1]

    async def test_a_busy_concurrent_claimant_spends_nothing(self, api, factory, t):  # noqa: F811
        g = await _active_allow(api, t, max_uses=3)
        context = dataclasses.replace(ctx(t), turn_id=uuid.uuid4(), turn_attempt=1)
        started, release = asyncio.Event(), asyncio.Event()
        ran: list[int] = []

        async def slow():
            ran.append(1)
            started.set()
            await release.wait()
            return "ok"

        def call(run):
            return guarded_call(context, HIRE, {}, run, source="test", default_risk="write",
                                slot=ToolSlot(0, 0))

        holder = asyncio.create_task(call(slow))
        await started.wait()
        busy = await call(slow)
        assert busy["status"] == "effect_in_progress"
        assert (await _row(factory, g["id"])).used_count == 1
        release.set()
        assert (await holder)["status"] == "success" and ran == [1]
        assert (await _row(factory, g["id"])).used_count == 1

    async def test_a_slot_mismatch_spends_nothing(self, api, factory, t):  # noqa: F811
        g = await _active_allow(api, t, max_uses=3)
        turn = uuid.uuid4()
        first, _ = _call(t, HIRE, {"k": 1}, turn_id=turn)
        assert (await first())["status"] == "success"
        different, ran = _call(t, HIRE, {"k": 2}, turn_id=turn)  # same slot, other arguments
        assert (await different())["status"] == "effect_recovery_required" and ran == []
        assert (await _row(factory, g["id"])).used_count == 1
        assert len(await _uses(factory, g["id"])) == 1

    @pytest.mark.parametrize("effect", [EffectClass.IDEMPOTENT_WRITE, None])
    async def test_a_crash_after_the_spend_recovers_the_same_slot_without_spending_again(
        self, api, factory, t, effect  # noqa: F811
    ):
        g = await _active_allow(api, t, max_uses=1)
        turn = uuid.uuid4()
        # The process dies right after the claim committed the ledger row and the grant use,
        # before the tool was dispatched or settled.
        held = await effects.claim(
            t["acme"], turn, ToolSlot(0, 0), HIRE,
            effect or EffectClass.NON_IDEMPOTENT_WRITE, {},
            grant_id=uuid.UUID(g["id"]), epoch=effects.Epoch(None, 1),
        )
        assert held.action == "run"
        assert (await _row(factory, g["id"])).used_count == 1
        async with factory() as db:
            row = (await db.execute(select(ToolEffect))).scalar_one()
            row.lease_expires_at = governance_overlay.now() - timedelta(seconds=1)
            db.add(row)
            await db.commit()

        go, ran = _call(t, HIRE, turn_id=turn, effect=effect)
        result = await go()
        if effect is None:
            # Non-idempotent: it may have run, so a human decides; the use is not paid again.
            assert result["status"] == "effect_recovery_required" and ran == []
        else:
            assert result["status"] == "success" and ran == [1]
        row = await _row(factory, g["id"])
        assert (row.used_count, row.status) == (1, "used_up")
        assert len(await _uses(factory, g["id"])) == 1

    async def test_the_same_slot_of_another_turn_is_another_use(self, api, factory, t):  # noqa: F811
        g = await _active_allow(api, t, max_uses=1)
        one, _ = _call(t, HIRE, turn_id=uuid.uuid4())
        two, ran = _call(t, HIRE, turn_id=uuid.uuid4())
        assert (await one())["status"] == "success"
        assert (await two())["status"] == "denied" and ran == []
        assert (await _row(factory, g["id"])).used_count == 1

    async def test_the_identity_names_company_and_turn(self):
        turn, slot = uuid.uuid4(), ToolSlot(0, 0)
        keys = {
            effects.invocation_key(uuid.uuid4(), turn, slot),
            effects.invocation_key(uuid.uuid4(), turn, slot),
            effects.invocation_key(uuid.uuid4(), uuid.uuid4(), slot),
        }
        assert len(keys) == 3

    async def test_a_call_with_no_slot_is_charged_every_time(self, api, factory, t):  # noqa: F811
        g = await _active_allow(api, t, max_uses=2)

        async def run():
            return "ok"

        for _ in range(2):  # no turn, so no ledger and no identity to dedupe on
            out = await guarded_call(ctx(t), HIRE, {}, run, source="test", default_risk="write")
            assert out["status"] == "success"
        assert (await _row(factory, g["id"])).used_count == 2


class TestNoticeAndApprovalBeforeTheGrantSpend:
    """The autonomy gate runs before the claim spends a grant. What can it leave behind?

    A level-2 notice for a slot whose spend is then refused (the grant was revoked or used up in
    between) is the only residue: one notice for that ledger key, no approval, no ledger row
    (PostgreSQL). It
    authorizes nothing: another slot is judged on its own and a level-3 refusal never reaches
    the grant at all. Recorded as a follow-up in the runbook; it needs no fix.
    """

    @staticmethod
    def _gate(monkeypatch, level, after_notice=None):
        from nexus.tools import factory as tool_factory
        from nexus.tools.autonomy import AutonomyGate

        sent: list[dict] = []
        asked: list[dict] = []

        class Approvals:
            async def get_async(self, approval_id):
                return None

            async def request_approval(self, **kwargs):
                asked.append(kwargs)

        async def loader(agent_id):
            return {}

        async def notifier(payload):
            sent.append(payload)
            if after_notice is not None:
                await after_notice()

        monkeypatch.setattr(
            tool_factory,
            "build_autonomy_gate",
            lambda db, **kw: AutonomyGate(
                loader, approvals=Approvals(), notifier=notifier, default_level=level,
                notice_once=effects.claim_notice,
            ),
        )
        return sent, asked

    async def test_a_notice_for_a_refused_spend_is_the_only_residue_and_authorizes_nothing(
        self, api, factory, t, monkeypatch  # noqa: F811
    ):
        g = await _active_allow(api, t, max_uses=1)

        async def revoke():
            await api("POST", f"/grants/{g['id']}/revoke", {"reason": "revoked mid-call"})

        sent, asked = self._gate(monkeypatch, 2, after_notice=revoke)
        turn = uuid.uuid4()
        first, ran = _call(t, HIRE, {"k": 1}, turn_id=turn)
        assert (await first())["status"] == "denied" and ran == []
        # One notice for that slot; no approval; nothing spent. (The savepoint rollback that
        # leaves no ledger row is a PostgreSQL behaviour: see test_tool_effects_postgres.)
        assert len(sent) == 1 and asked == []
        assert (await _row(factory, g["id"])).used_count == 0
        # Another slot gets no authority from it: refused at the access check, before the gate.
        other, ran_other = _call(t, HIRE, {"k": 1}, slot=ToolSlot(0, 1), turn_id=turn)
        assert (await other())["status"] == "denied" and ran_other == []
        assert len(sent) == 1 and asked == []
        # Retrying the same slot does not notify again.
        assert (await first())["status"] == "denied" and len(sent) == 1

    async def test_a_level_three_refusal_never_reaches_the_grant(
        self, api, factory, t, monkeypatch  # noqa: F811
    ):
        g = await _active_allow(api, t, max_uses=1)
        sent, asked = self._gate(monkeypatch, 3)
        go, ran = _call(t, HIRE, turn_id=uuid.uuid4())
        assert (await go())["status"] == "autonomy_blocked" and ran == []
        # It asks for an approval (and notifies) but never reaches the grant.
        assert len(asked) == 1 and len(sent) == 1
        row = await _row(factory, g["id"])
        assert (row.used_count, row.status) == (0, "active")
        assert await _uses(factory, g["id"]) == []
