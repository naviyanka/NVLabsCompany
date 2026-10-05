"""Autonomy presets create policy drafts. They never publish and never bypass a deny or a role."""

from __future__ import annotations

import pytest
from sqlalchemy import func
from sqlmodel import select

from nexus.models.agent import Agent
from nexus.models.governance import AuditLog
from nexus.models.governance_studio import GovernancePolicyDraft
from nexus.models.tool import ToolPolicy
from tests.test_governance_grants import _decide
from tests.test_governance_studio import _policy, api  # noqa: F401 -- fixture, helper
from tests.test_tool_access import ctx, factory, t  # noqa: F401 -- fixtures and helper


async def _count(factory, model) -> int:  # noqa: F811
    async with factory() as db:
        return (await db.execute(select(func.count()).select_from(model))).scalar()


def _url(t, key="", who="a") -> str:  # noqa: F811
    return f"/agents/{t[who]}/autonomy-presets" + (f"/{key}" if key else "")


async def _make(factory, t, *, ceo=False, report=False):  # noqa: F811
    async with factory() as db:
        a = await db.get(Agent, t["a"])
        a.is_ceo = ceo
        db.add(a)
        if report:
            b = await db.get(Agent, t["b"])
            b.manager_id = a.id
            db.add(b)
        await db.commit()


async def _draft(api, t, key, who="admin", agent="a"):  # noqa: F811
    return await api("POST", _url(t, key, agent) + "/draft", {"reason": "try this preset"}, who=who)


async def _publish(api, draft):  # noqa: F811
    r = await api("POST", f"/drafts/{draft['id']}/publish", {}, who="second_admin")
    assert r.status_code == 200, r.text
    return r.json()


def _changes(body) -> dict[str, dict]:
    return {c["capability_id"]: c for c in body["capability_diff"]["changes"]}


class TestAvailability:
    async def test_roles_decide_which_presets_an_agent_may_hold(self, api, factory, t):  # noqa: F811
        def reasons(body):
            return {i["key"]: i["unavailable_reason"] for i in body["items"]}

        first = reasons((await api("GET", _url(t))).json())
        assert list(first) == [
            "advisory", "assisted", "task_autonomy", "delegated_autonomy",
            "operational_autonomy", "restricted_executive_autonomy",
        ]
        assert first["task_autonomy"] is None
        assert "direct report" in first["delegated_autonomy"]
        assert "CEO" in first["restricted_executive_autonomy"]
        await _make(factory, t, ceo=True, report=True)
        assert set(reasons((await api("GET", _url(t))).json()).values()) == {None}

    async def test_refused_for_an_agent_that_cannot_hold_it(self, api, t):  # noqa: F811
        for key in ("delegated_autonomy", "operational_autonomy", "restricted_executive_autonomy"):
            for call in (api("GET", _url(t, key)), _draft(api, t, key)):
                r = await call
                assert r.status_code == 409
                assert r.json()["detail"]["code"] == "PRESET_NOT_AVAILABLE"

    async def test_unknown_preset_and_other_tenants_are_404(self, api, t):  # noqa: F811
        assert (await api("GET", _url(t, "root"))).json()["detail"]["code"] == "PRESET_NOT_FOUND"
        for call in (api("GET", _url(t, "advisory"), who="outsider"),
                     _draft(api, t, "advisory", who="outsider")):
            assert (await call).status_code == 404

    async def test_no_cosmetic_autonomy_setter(self, api, t):  # noqa: F811
        r = await api("PUT", f"/agents/{t['a']}/autonomy", {"level": "full"})
        assert r.status_code in (404, 405)


class TestPreviewAndDraft:
    async def test_preview_writes_nothing(self, api, factory, t):  # noqa: F811
        body = (await api("GET", _url(t, "advisory"))).json()
        assert body["applied"] is False and body["draft"] is None
        assert await _count(factory, GovernancePolicyDraft) == 0
        assert await _count(factory, ToolPolicy) == 0

    async def test_only_a_human_admin_drafts_and_it_is_only_a_draft(self, api, factory, t):  # noqa: F811
        for who in ("viewer", "run", "key"):
            assert (await _draft(api, t, "advisory", who=who)).status_code == 403
        r = await _draft(api, t, "advisory")
        assert r.status_code == 201, r.text
        body = r.json()
        assert body["applied"] is False and body["draft"]["status"] == "draft"
        assert await _count(factory, ToolPolicy) == 0, "a draft changes no live rule"
        assert (await api("GET", "/policy")).json()["version"] == 0
        async with factory() as db:
            row = (await db.execute(
                select(AuditLog).where(AuditLog.action == "governance.autonomy_preset.drafted")
            )).scalars().one()
        assert row.details["preset"] == "advisory" and row.details["agent_id"] == str(t["a"])

    async def test_the_same_preset_replaces_its_own_rules_not_duplicates_them(self, api, t):  # noqa: F811
        first = (await _draft(api, t, "assisted")).json()
        await _publish(api, first["draft"])
        again = (await _draft(api, t, "advisory")).json()
        names = [r["name"] for r in again["draft"]["rules"]]
        assert len(names) == len(set(names))
        assert sum(n.endswith(":allow") for n in names) == 1
        assert {c["name"] for c in again["draft"]["diff"]["changed"]} <= set(names)


class TestCapabilityDiffMatchesRuntime:
    async def test_advisory_keeps_reads_and_drops_writes(self, api, factory, t):  # noqa: F811
        body = (await api("GET", _url(t, "advisory"))).json()
        changes = _changes(body)
        assert changes["tool.db-redis-set"]["before"] == "allow"
        assert changes["tool.db-redis-set"]["after"] == "deny"
        assert changes["tool.http-request"]["after"] == "deny"
        assert changes["tool.ai-chat"]["after"] == "allow", "a read tool stays allowed"
        excluded = {e["capability_id"]: e["label"] for e in body["capability_diff"]["excluded"]}
        assert excluded["computer.browser"] == "Not enforceable"
        assert excluded["computer.terminal"] == "Not enforceable"
        assert excluded["exec.spend"] == "Not controlled by policy"

    async def test_published_preset_behaves_as_the_diff_promised(self, api, factory, t):  # noqa: F811
        draft = (await _draft(api, t, "assisted")).json()
        diff = _changes(draft)
        await _publish(api, draft["draft"])
        for cap, tool in (("tool.http-request", "http-request"),
                          ("tool.db-redis-set", "db-redis-set"),
                          ("tool.ai-chat", "ai-chat")):
            allowed = (await _decide(factory, t, tool=tool)).allowed
            promised = diff[cap]["after"] if cap in diff else "allow"
            assert allowed == (promised == "allow"), cap
        assert not (await _decide(factory, t, tool="http-request")).allowed
        assert (await _decide(factory, t, tool="db-redis-set")).allowed

    async def test_each_level_keeps_what_the_one_before_allows(self, api, factory, t):  # noqa: F811
        await _make(factory, t, ceo=True, report=True)
        allowed: list[set[str]] = []
        for key in ("advisory", "assisted", "task_autonomy", "delegated_autonomy",
                    "operational_autonomy"):
            draft = (await _draft(api, t, key)).json()
            rules = [r for r in draft["rules"] if r["effect"] == "allow"]
            allowed.append({n for r in rules for n in r["conditions"]["tool_name"]})
        for lower, higher in zip(allowed, allowed[1:]):
            assert lower <= higher
        assert "manager_delegate_task" in allowed[3] and "manager_delegate_task" not in allowed[2]
        assert "manager_request_hire" in allowed[4] and "manager_request_hire" not in allowed[3]
        assert not any(n.startswith("ceo_") and n not in (
            "ceo_get_organization_snapshot", "ceo_list_managers", "ceo_get_manager_status",
            "ceo_list_pending_approvals", "ceo_search_executive_memory",
            "ceo_get_work_status") for n in allowed[4])


class TestNeverBypasses:
    async def test_an_existing_explicit_deny_still_wins(self, api, factory, t):  # noqa: F811
        await _policy(factory, t["acme"], name="freeze network", effect="deny", priority=5,
                      conditions={"tool_name": ["http-request"]})
        body = (await api("GET", _url(t, "task_autonomy"))).json()
        blocked = [b["capability_id"] for b in body["capability_diff"]["blocked"]]
        assert "tool.http-request" in blocked
        draft = (await _draft(api, t, "task_autonomy")).json()
        await _publish(api, draft["draft"])
        assert not (await _decide(factory, t, tool="http-request")).allowed
        # The preset's own allow is ordered after every other rule.
        live = {r.name: r.priority for r in await _rules(factory)}
        assert live[f"autonomy:{t['a']}:allow"] > live["freeze network"]

    async def test_a_preset_never_reaches_another_agent(self, api, factory, t):  # noqa: F811
        draft = (await _draft(api, t, "advisory")).json()
        await _publish(api, draft["draft"])
        assert not (await _decide(factory, t, tool="db-redis-set")).allowed
        other = await _decide(factory, t, tool="db-redis-set", agent="b")
        assert other.allowed, "the deny is scoped to the agent it was drafted for"

    async def test_preset_rules_carry_an_owner_and_review_date(self, api, t):  # noqa: F811
        draft = (await _draft(api, t, "task_autonomy")).json()
        assert not [f for f in draft["draft"]["findings"] if f["code"] == "NO_OWNER_OR_REVIEW_DATE"]
        for rule in draft["rules"]:
            assert rule["conditions"]["agent_id"] == [str(t["a"])]
            assert rule["conditions"]["governance"]["review_by"]


async def _rules(factory):  # noqa: F811
    async with factory() as db:
        return (await db.execute(select(ToolPolicy))).scalars().all()


@pytest.mark.parametrize("key", ["advisory", "assisted", "task_autonomy"])
async def test_every_available_preset_yields_a_valid_draft(api, t, key):  # noqa: F811
    r = await _draft(api, t, key)
    assert r.status_code == 201
    assert r.json()["draft"]["rules"]
