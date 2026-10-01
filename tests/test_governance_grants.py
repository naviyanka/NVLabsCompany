"""Governance Studio temporary access: creation, approval, consumption, revoke, expiry."""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlmodel import select

from nexus.models.governance import AuditLog
from nexus.models.governance_studio import GovernanceTempAccess
from nexus.models.tool import ToolProfile, ToolProfileBinding
from nexus.tools import governance_overlay
from nexus.tools.access import check_tool_access
from nexus.tools.factory import guarded_call
from tests.test_governance_studio import _eff, _policy, api  # noqa: F401 -- fixtures, helpers
from tests.test_tool_access import ctx, factory, t  # noqa: F401 -- fixtures and helper

HIRE = "ceo_request_hire"  # explicit-allow-only, so it needs approval
READ = "ceo_list_managers"


def _in(**delta: float) -> str:
    return (datetime.now(UTC) + timedelta(**delta)).isoformat()


def _grant(t, tool=HIRE, effect="allow", **over) -> dict[str, Any]:  # noqa: F811
    return {"agent_id": str(t["a"]), "tool_name": tool, "effect": effect,
            "expires_at": _in(hours=1), "reason": "incident 42", **over}


async def _decide(factory, t, tool=HIRE, **kw):  # noqa: F811
    async with factory() as db:
        return await check_tool_access(
            db, ctx(t, **kw), tool_name=tool, default_risk="write", enforcement="audit"
        )


async def _create(api, t, **over) -> dict[str, Any]:  # noqa: F811
    r = await api("POST", "/grants", _grant(t, **over))
    assert r.status_code == 201, r.text
    return r.json()


async def _active_allow(api, t, **over) -> dict[str, Any]:  # noqa: F811
    g = await _create(api, t, **over)
    r = await api("POST", f"/grants/{g['id']}/approve", {}, who="second_admin")
    assert r.json()["status"] == "active", r.text
    return g


class TestCreation:
    async def test_high_risk_allow_waits_for_someone_else(self, api, factory, t):  # noqa: F811
        g = await _create(api, t)
        assert g["status"] == "pending_approval" and g["approval_id"]
        assert not (await _decide(factory, t)).allowed

        own = await api("POST", f"/grants/{g['id']}/approve", {})
        assert (own.status_code, own.json()["detail"]["code"]) == (403, "SELF_APPROVAL")
        assert not (await _decide(factory, t)).allowed

        ok = await api("POST", f"/grants/{g['id']}/approve", {}, who="second_admin")
        assert ok.status_code == 200 and ok.json()["status"] == "active"
        decision = await _decide(factory, t)
        assert decision.allowed and decision.temp_grant_id == uuid.UUID(g["id"])

    async def test_rejected_grant_never_allows(self, api, factory, t):  # noqa: F811
        g = await _create(api, t)
        r = await api("POST", f"/grants/{g['id']}/reject", {"note": "no"}, who="second_admin")
        assert r.json()["status"] == "rejected"
        assert not (await _decide(factory, t)).allowed
        late = await api("POST", f"/grants/{g['id']}/approve", {}, who="second_admin")
        assert late.status_code == 409

    async def test_read_allow_and_any_deny_are_active_at_once(self, api, t):  # noqa: F811
        assert (await _create(api, t, effect="deny"))["status"] == "active"
        assert (await _create(api, t, tool=READ))["status"] == "active"

    @pytest.mark.parametrize(
        ("over", "code"),
        [
            ({"tool_name": "ceo_*"}, "UNKNOWN_TOOL"),
            ({"tool_name": "nope"}, "UNKNOWN_TOOL"),
            ({"expires_at": _in(hours=-1)}, "EXPIRY_IN_PAST"),
            ({"expires_at": _in(days=3)}, "EXPIRY_TOO_LONG"),
        ],
    )
    async def test_invalid_grants_are_refused(self, api, t, over, code):  # noqa: F811
        r = await api("POST", "/grants", _grant(t, **over))
        assert (r.status_code, r.json()["detail"]["code"]) == (422, code)

    async def test_only_a_human_admin_writes_and_only_inside_the_tenant(self, api, t):  # noqa: F811
        for who in ("viewer", "run", "key"):
            assert (await api("POST", "/grants", _grant(t), who=who)).status_code == 403, who
        foreign = {**_grant(t), "agent_id": str(t["foreign"])}
        assert (await api("POST", "/grants", foreign)).status_code == 404
        assert (await api("POST", "/grants", _grant(t), who="outsider")).status_code == 404

    async def test_writes_are_audited_without_arguments(self, api, factory, t):  # noqa: F811
        g = await _create(api, t, tool=READ)
        await api("POST", f"/grants/{g['id']}/revoke", {"reason": "done with it"})
        async with factory() as db:
            rows = (
                await db.execute(
                    select(AuditLog).where(AuditLog.action.startswith("governance.grant"))
                )
            ).scalars().all()
        assert {r.action for r in rows} == {"governance.grant.created", "governance.grant.revoked"}
        allowed = {"agent_id", "tool_name", "effect", "status", "expires_at", "approval_id",
                   "reason", "used_count"}
        assert all(set(r.details or {}) <= allowed for r in rows)

    async def test_inbox_marks_what_the_caller_may_decide(self, api, t):  # noqa: F811
        await _create(api, t)
        flags = [
            (await api("GET", "/approvals", who=who)).json()["items"][0]["can_decide"]
            for who in ("admin", "second_admin", "viewer")
        ]
        assert flags == [False, True, False]


class TestSemantics:
    async def test_allow_never_overrides_an_explicit_deny_rule(self, api, factory, t):  # noqa: F811
        await _active_allow(api, t)
        await _policy(factory, t["acme"], name="freeze hiring", effect="deny",
                      conditions={"tool_name": [HIRE]})
        decision = await _decide(factory, t)
        assert not decision.allowed and decision.temp_grant_id is None

    async def test_allow_lifts_a_default_deny_and_a_deny_beats_it(self, api, factory, t):  # noqa: F811
        async with factory() as db:
            profile = ToolProfile(company_id=t["acme"], name="closed", default_action="deny")
            db.add(profile)
            await db.flush()
            db.add(ToolProfileBinding(company_id=t["acme"], profile_id=profile.id,
                                      target_type="agent", target_id=t["a"]))
            await db.commit()
        assert not (await _decide(factory, t, tool=READ)).allowed
        await _create(api, t, tool=READ)
        assert (await _decide(factory, t, tool=READ)).allowed
        await _create(api, t, tool=READ, effect="deny")
        assert not (await _decide(factory, t, tool=READ)).allowed

    async def test_rbac_still_wins(self, api, factory, t):  # noqa: F811
        await _active_allow(api, t)
        assert not (await _decide(factory, t, role="viewer")).allowed

    async def test_other_agent_is_unaffected(self, api, factory, t):  # noqa: F811
        await _active_allow(api, t)
        assert not (await _decide(factory, t, agent="b")).allowed

    async def test_session_bound_grant_only_applies_in_its_session(self, api, factory, t):  # noqa: F811
        await _active_allow(api, t, session_id=str(t["s1"]))
        assert (await _decide(factory, t, session="s1")).allowed
        assert not (await _decide(factory, t, session="s2")).allowed
        assert not (await _decide(factory, t)).allowed

    async def test_one_use_grant_runs_once(self, api, factory, t):  # noqa: F811
        await _active_allow(api, t, max_uses=1)
        ran: list[int] = []

        async def run():
            ran.append(1)
            return "ok"

        async def call():
            return await guarded_call(ctx(t), HIRE, {}, run, source="test", default_risk="write")

        first = await call()
        assert first["status"] == "success"
        second = await call()
        assert second["status"] != "success" and len(ran) == 1

    async def test_parallel_spends_of_a_one_use_grant_win_once(self, api, factory, t):  # noqa: F811
        g = await _active_allow(api, t, max_uses=1)

        async def spend() -> bool:
            async with factory() as db:
                ok = await governance_overlay.consume_temp_grant(
                    db, t["acme"], uuid.UUID(g["id"])
                )
                await db.commit()
                return ok

        results = await asyncio.gather(*(spend() for _ in range(5)))
        assert results.count(True) == 1

    async def test_revoke_ends_the_grant_and_a_second_revoke_conflicts(self, api, factory, t):  # noqa: F811
        g = await _active_allow(api, t)
        assert (await _decide(factory, t)).allowed
        r = await api("POST", f"/grants/{g['id']}/revoke", {"reason": "no longer needed"})
        assert r.json()["status"] == "revoked"
        assert not (await _decide(factory, t)).allowed
        again = await api("POST", f"/grants/{g['id']}/revoke", {"reason": "no longer needed"})
        assert (again.status_code, again.json()["detail"]["code"]) == (409, "GRANT_NOT_ACTIVE")

    async def test_expired_grant_denies_and_shows_expired(self, api, factory, t):  # noqa: F811
        g = await _active_allow(api, t)
        async with factory() as db:
            row = await db.get(GovernanceTempAccess, uuid.UUID(g["id"]))
            row.expires_at = governance_overlay.now() - timedelta(minutes=1)
            db.add(row)
            await db.commit()
        assert not (await _decide(factory, t)).allowed
        assert (await _eff(factory, t))["org.ceo_request_hire"]["state"] == "expired"
        listed = (await api("GET", "/grants?status=expired")).json()["items"]
        assert [i["id"] for i in listed] == [g["id"]]

    async def test_revoking_a_pending_grant_closes_it_for_good(self, api, factory, t):  # noqa: F811
        g = await _create(api, t)
        r = await api("POST", f"/grants/{g['id']}/revoke", {"reason": "changed my mind"})
        assert r.json()["status"] == "revoked"
        late = await api("POST", f"/grants/{g['id']}/approve", {}, who="second_admin")
        assert late.status_code == 409
        assert not (await _decide(factory, t)).allowed

    async def test_effective_access_shows_temporary_states(self, api, factory, t):  # noqa: F811
        await _active_allow(api, t)
        await _create(api, t, tool="ceo_record_decision", effect="deny")
        eff = await _eff(factory, t)
        assert eff["org.ceo_request_hire"]["state"] == "temporarily_allowed"
        assert eff["org.ceo_request_hire"]["validity"]["uses_left"] is None
        assert eff["org.ceo_record_decision"]["state"] == "temporarily_denied"
