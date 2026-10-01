"""Governance Studio: catalogue, effective access, grants, simulator, versions, lockdown.

Runs on the ws05 fixtures (a SQLite file database with two companies). Decisions are held to
``check_tool_access``, the engine the runtime uses, so the screen cannot drift from it.
"""

from __future__ import annotations

import uuid
from typing import Any

import httpx
import pytest
from fastapi import FastAPI, Request
from sqlalchemy import event

from nexus.api.routes import governance_studio as routes
from nexus.auth.principal import Principal
from nexus.models.agent import Agent
from nexus.models.tool import ToolPolicy
from nexus.services.governance_studio import catalog, effective
from nexus.tools.access import check_tool_access
from tests.test_tool_access import ctx, factory, t  # noqa: F401 -- fixtures and helper


def _cap(tool: str) -> dict[str, Any]:
    return next(c for c in catalog.build_catalog() if c.get("tool_name") == tool)


async def _eff(factory, t, agent="a") -> dict[str, dict[str, Any]]:  # noqa: F811
    async with factory() as db:
        a = await db.get(Agent, t[agent])
        out = await effective.effective_access(db, t["acme"], a)
    return {c["id"]: c for c in out["capabilities"]}


async def _policy(factory, company, **kw):  # noqa: F811
    async with factory() as db:
        db.add(ToolPolicy(company_id=company, **kw))
        await db.commit()


class TestCatalog:
    def test_ids_are_unique_and_every_entry_declares_its_enforcement(self):
        caps = catalog.build_catalog()
        assert len({c["id"] for c in caps}) == len(caps)
        assert {c["category"] for c in caps} == set(catalog.CATEGORIES)
        for c in caps:
            assert c["support"] in ("enforced", "approval_only", "display_only", "unsupported")
            assert c["toggleable"] == (c["support"] == "enforced")
            assert bool(c["backends"]) == (c["support"] != "unsupported")

    def test_computer_use_is_never_a_working_control(self):
        computer = [c for c in catalog.build_catalog() if c["category"] == "computer_use"]
        assert computer
        assert all(c["support"] == "unsupported" and not c["toggleable"] for c in computer)
        assert all(not c["approval_support"] and not c["scope_schema"] for c in computer)

    def test_explicit_allow_tools_are_flagged(self):
        assert _cap("ceo_request_hire")["explicit_allow_required"]
        assert _cap("manager_request_hire")["explicit_allow_required"]
        assert not _cap("ceo_list_managers")["explicit_allow_required"]


class TestEffectiveAccess:
    async def test_unconfigured_company_inherits_the_default_allow(self, factory, t):  # noqa: F811
        eff = await _eff(factory, t)
        row = eff["org.ceo_list_managers"]
        assert (row["state"], row["code"]) == ("inherited", "DEFAULT_ALLOW")
        assert row["inheritance_source"] == "system default"
        # Nothing names it, so an explicit-allow-only tool is denied by default.
        assert eff["org.ceo_request_hire"]["state"] == "denied"

    async def test_deny_rule_is_explained_with_its_source(self, factory, t):  # noqa: F811
        await _policy(factory, t["acme"], name="no writes", effect="deny",
                      conditions={"risk_level": ["write"]})
        row = (await _eff(factory, t))["org.manager_delegate_task"]
        assert (row["state"], row["code"]) == ("denied", "POLICY_DENY")
        assert row["source"] == "policy:no writes"
        assert row["conditions"] == {"risk_level": ["write"]}

    async def test_explicit_allow_names_the_tool(self, factory, t):  # noqa: F811
        await _policy(factory, t["acme"], name="wild", effect="allow",
                      conditions={"tool_name": ["ceo_*"]})
        assert (await _eff(factory, t))["org.ceo_request_hire"]["state"] == "denied"
        await _policy(factory, t["acme"], name="named", effect="allow",
                      conditions={"tool_name": ["ceo_request_hire"]})
        row = (await _eff(factory, t))["org.ceo_request_hire"]
        assert (row["state"], row["source"]) == ("allowed", "policy:named")

    async def test_autonomy_level_three_requires_approval(self, factory, t):  # noqa: F811
        async with factory() as db:
            a = await db.get(Agent, t["a"])
            a.autonomy_policy = {"delete": 3, "write_file": 2}
            db.add(a)
            await db.commit()
        eff = await _eff(factory, t)
        assert eff["exec.delete"]["state"] == "approval_required"
        assert eff["exec.write_file"]["code"] == "AUTONOMY_L2"
        assert eff["exec.execute_code"]["code"] == "AUTONOMY_L1"

    async def test_unsupported_items_have_no_decision(self, factory, t):  # noqa: F811
        row = (await _eff(factory, t))["computer.browser"]
        assert (row["state"], row["decision"]) == ("unsupported", "none")

    async def test_secret_capability_reports_a_count_only(self, factory, t):  # noqa: F811
        row = (await _eff(factory, t))["data.secrets"]
        assert row["count"] == 0 and "value" not in row

    @pytest.mark.parametrize(
        "rules",
        [
            [],
            [dict(name="deny writes", effect="deny", conditions={"risk_level": ["write"]})],
            [dict(name="allow named", effect="allow",
                  conditions={"tool_name": ["ceo_request_hire", "manager_request_hire"]})],
            [dict(name="deny one", effect="deny", priority=1,
                  conditions={"tool_name": ["ai-chat"]}),
             dict(name="allow all", effect="allow", priority=2, conditions={})],
        ],
    )
    async def test_matrix_matches_the_runtime_engine(self, factory, t, rules):  # noqa: F811
        for rule in rules:
            await _policy(factory, t["acme"], **rule)
        eff = await _eff(factory, t)
        for cap in catalog.build_catalog():
            if cap["support"] != "enforced":
                continue
            async with factory() as db:
                decision = await check_tool_access(
                    db, ctx(t), tool_name=cap["tool_name"], default_risk=cap["risk"],
                    enforcement="audit",
                )
            shown = eff[cap["id"]]["decision"]
            assert (shown == "allow") == decision.allowed, cap["id"]

    async def test_query_count_is_fixed(self, factory, t):  # noqa: F811
        async def count() -> int:
            statements: list[str] = []
            async with factory() as db:
                a = await db.get(Agent, t["a"])
                sync = db.sync_session.get_bind()
                hook = lambda *args: statements.append(args[2])  # noqa: E731
                event.listen(sync, "before_cursor_execute", hook)
                try:
                    await effective.effective_access(db, t["acme"], a)
                finally:
                    event.remove(sync, "before_cursor_execute", hook)
            return len(statements)

        baseline = await count()
        for i in range(25):
            await _policy(factory, t["acme"], name=f"r{i}", effect="deny", priority=i,
                          conditions={"tool_name": [f"tool_{i}"]})
        assert baseline <= 10
        assert await count() == baseline


# --- routes -------------------------------------------------------------------------------


@pytest.fixture
async def api(factory, t):  # noqa: F811
    def user(company, role="admin", email="p@example.test"):
        return Principal(kind="user", company_id=company, role=role, user_id=uuid.uuid4(),
                         email=email)

    principals = {
        "admin": user(t["acme"]),
        "second_admin": user(t["acme"], email="q@example.test"),
        "viewer": user(t["acme"], "viewer", "v@example.test"),
        "outsider": user(t["other"]),
        "run": Principal(kind="run", company_id=t["acme"], role="agent", run_id=uuid.uuid4(),
                         agent_id=t["a"]),
        "key": Principal(kind="service", company_id=t["acme"], role="admin",
                         api_key_id=uuid.uuid4(), label="k"),
    }
    app = FastAPI()
    app.include_router(routes.router)

    @app.middleware("http")
    async def as_principal(request: Request, call_next):
        request.state.principal = principals[request.headers.get("x-who", "admin")]
        return await call_next(request)

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                 base_url="http://test") as client:
        async def call(method, path, body=None, who="admin"):
            return await client.request(method, f"/api/v1/governance{path}", json=body,
                                        headers={"x-who": who})
        yield call


class TestReadRoutes:
    async def test_people_read_agents_and_access(self, api, t):  # noqa: F811
        for who in ("admin", "viewer"):
            r = await api("GET", "/agents", who=who)
            assert r.status_code == 200 and {i["name"] for i in r.json()["items"]} == {"A", "B"}
            r = await api("GET", f"/agents/{t['a']}/effective-access", who=who)
            assert r.status_code == 200 and r.json()["capabilities"]

    async def test_agents_and_keys_are_refused(self, api, t):  # noqa: F811
        for who in ("run", "key"):
            for path in ("/catalog", "/agents", f"/agents/{t['a']}/effective-access"):
                r = await api("GET", path, who=who)
                assert r.status_code == 403, (who, path)
                assert r.json()["detail"]["code"] == "HUMAN_REQUIRED"

    async def test_another_tenants_agent_is_a_404(self, api, t):  # noqa: F811
        r = await api("GET", f"/agents/{t['foreign']}/effective-access")
        assert (r.status_code, r.json()["detail"]["code"]) == (404, "AGENT_NOT_FOUND")
        r = await api("GET", f"/agents/{t['a']}/effective-access", who="outsider")
        assert r.status_code == 404

    async def test_listing_is_bounded(self, api):
        assert (await api("GET", "/agents?limit=1")).json()["items"].__len__() == 1
        assert (await api("GET", "/agents?limit=1000")).status_code == 422
