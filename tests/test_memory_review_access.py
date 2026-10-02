"""Candidate and closed memory is a human-review surface; nobody else can ask for it.

Real sessions go through the real cookie resolver (``_principal_from_cookie``: active user,
live membership, role read from the membership row on every request), so an inactive user, a
removed membership, a session naming another company and anything a client claims about its
own role are all exercised end to end. Run tokens and API keys are injected as the principals
the middleware would build for them.

Every route here is checked on three axes: the default is active only; a non-active
``?status=`` (or ``include_closed``) needs a human administrator of the caller's own company;
a reviewer's read is audited with ids and view, never with memory content.
"""

from __future__ import annotations

import uuid

import httpx
import pytest
from fastapi import FastAPI, Request
from sqlalchemy import delete, select

from nexus.api.routes import memory as agent_routes
from nexus.api.routes import memory_global as global_routes
from nexus.api.routes import memory_graph as graph_routes
from nexus.api.routes import organization as org_routes
from nexus.auth.middleware import AuthenticationMiddleware, rejection_for
from nexus.auth.principal import Principal
from nexus.auth.sessions import create_session
from nexus.auth.users import create_user
from nexus.models.company import CompanyMembership
from nexus.models.governance import AuditLog
from nexus.models.memory import MemoryRecord
from nexus.models.user_profile import UserProfile
from tests.test_tool_access import factory, t  # noqa: F401 -- fixtures

CLOSED = ("candidate", "archived", "superseded", "rejected")
SECRET = "closed-secret-text"
CEO = "/api/v1/organization/ceo"


@pytest.fixture(params=("route", "middleware"))
async def world(request, factory, t):  # noqa: F811
    """The routes behind the real session resolver, with or without the middleware's policy.

    ``route`` leaves the route's own checks as the only guard (authentication disabled);
    ``middleware`` also applies ``rejection_for`` first, as the deployed stack does.
    """
    enforce_in_middleware = request.param == "middleware"
    tokens: dict[str, str] = {}
    ids: dict[str, uuid.UUID] = {}
    async with factory() as db:
        for name, company, role in (
            ("admin", t["acme"], "admin"), ("viewer", t["acme"], "viewer"),
            ("member", t["acme"], "member"),
            ("inactive", t["acme"], "admin"), ("removed", t["acme"], "admin"),
            ("outsider", t["other"], "admin"),
        ):
            user = await create_user(db, email=f"{name}@example.com", password="x" * 14,
                                     company_id=company, role=role)
            ids[name] = user.id
            tokens[name], _ = await create_session(db, user_id=user.id, company_id=company)
        tokens["crossed"], _ = await create_session(db, user_id=ids["viewer"],
                                                    company_id=t["other"])
        await db.commit()

    agent = uuid.uuid4()
    rows = {"active": MemoryRecord(company_id=t["acme"], agent_id=agent, scope="l2_agent",
                                   content="live note", status="active")}
    for st in CLOSED:
        rows[st] = MemoryRecord(company_id=t["acme"], agent_id=agent, scope="l2_agent",
                                content=f"{SECRET} {st}", status=st)
    rows["exec_active"] = MemoryRecord(company_id=t["acme"], scope="executive",
                                       content="live directive", status="active",
                                       memory_type="directive")
    rows["exec_archived"] = MemoryRecord(company_id=t["acme"], scope="executive",
                                         content=f"{SECRET} exec", status="archived",
                                         memory_type="directive")
    async with factory() as db:
        db.add_all(rows.values())
        await db.commit()

    injected = {
        "run": Principal(kind="run", company_id=t["acme"], role="agent", run_id=uuid.uuid4(),
                         agent_id=agent),
        "admin_key": Principal(kind="service", company_id=t["acme"], role="admin",
                               api_key_id=uuid.uuid4()),
    }
    resolver = AuthenticationMiddleware(None)  # type: ignore[arg-type]
    app = FastAPI()
    for router in (agent_routes.router, global_routes.router, graph_routes.router,
                   org_routes.ceo_router):
        app.include_router(router)

    @app.middleware("http")
    async def authenticate(request: Request, call_next):
        if (kind := request.headers.get("x-test-principal")) in injected:
            principal = injected[kind]
        else:
            token = request.cookies.get("nv_session", "")
            async with factory() as db:
                principal = await resolver._principal_from_cookie(db, token) if token else None
                await db.commit()
        if principal is not None:
            request.state.principal = principal
        if enforce_in_middleware and (
            rejection := rejection_for(request.url.path, principal)
        ) is not None:
            return rejection
        return await call_next(request)

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                 base_url="http://test") as client:
        async def call(who, path, **kw):
            client.cookies.clear()
            if who in tokens:
                client.cookies.set("nv_session", tokens[who])
            extra = {"x-test-principal": who} if who in injected else {}
            headers = {**kw.pop("headers", {}), **extra}
            return await client.get(path, headers=headers, **kw)

        async def deactivate(name):
            async with factory() as db:
                (await db.get(UserProfile, ids[name])).is_active = False
                await db.commit()

        async def remove_membership(name):
            async with factory() as db:
                await db.execute(delete(CompanyMembership).where(
                    CompanyMembership.user_id == ids[name]))
                await db.commit()

        async def review_audits():
            async with factory() as db:
                return list((await db.execute(
                    select(AuditLog).where(AuditLog.action == "memory.review_read"))).scalars())

        call.agent, call.rows, call.acme, call.other = agent, rows, t["acme"], t["other"]
        call.deactivate, call.remove_membership = deactivate, remove_membership
        call.review_audits = review_audits
        call.factory, call.engine = factory, factory.kw["bind"]
        yield call


def _urls(w):
    """Every route that can return a candidate or closed row, asked for a closed one."""
    return {
        "agent_list": f"/api/v1/agents/{w.agent}/memory?status=archived",
        "agent_list_candidate": f"/api/v1/agents/{w.agent}/memory?status=candidate",
        "company_list": f"/api/v1/companies/{w.acme}/memory?status=rejected",
        "company_list_candidate": f"/api/v1/companies/{w.acme}/memory?status=candidate",
        "executive": f"{CEO}/memory?include_closed=true",
    }


REFUSED = ("viewer", "member", "run", "admin_key", "outsider")


@pytest.mark.parametrize("who", REFUSED)
async def test_only_a_human_admin_can_ask_for_candidate_or_closed_memory(world, who):
    for name, url in _urls(world).items():
        r = await world(who, url)
        # A reviewer of another company asks their own, empty, tenant: nothing leaks either way.
        empty = who == "outsider" and r.status_code == 200 and r.json() == []
        assert r.status_code in (403, 404) or empty, (who, name, r.status_code)
        assert SECRET not in r.text, (who, name)
    for st in CLOSED:
        r = await world(who, f"/api/v1/memory/{world.rows[st].id}")
        assert r.status_code == 404 and SECRET not in r.text, (who, st)
    # The outsider reviews their own empty tenant: audited there, never in this company.
    assert [a for a in await world.review_audits() if a.company_id == world.acme] == []


@pytest.mark.parametrize("who", ("viewer", "member", "run", "admin_key"))
async def test_the_refusal_is_the_review_error_not_an_empty_list(world, who):
    r = await world(who, f"/api/v1/agents/{world.agent}/memory?status=archived")
    assert r.status_code == 403
    assert r.json()["detail"]["code"] == "MEMORY_REVIEW_FORBIDDEN"


@pytest.mark.parametrize("who", ("viewer", "member", "admin"))
async def test_default_lists_and_detail_stay_active_only(world, who):
    listed = (await world(who, f"/api/v1/agents/{world.agent}/memory")).json()
    assert [m["content"] for m in listed] == ["live note"]
    company = (await world(who, f"/api/v1/companies/{world.acme}/memory")).json()
    assert {m["content"] for m in company} == {"live note", "live directive"}
    one = await world(who, f"/api/v1/memory/{world.rows['active'].id}")
    assert one.status_code == 200 and one.json()["content"] == "live note"
    executive = (await world(who, f"{CEO}/memory")).json() if who == "admin" else []
    assert SECRET not in str(executive)
    assert await world.review_audits() == []


async def test_status_active_is_not_a_review_request(world):
    r = await world("viewer", f"/api/v1/agents/{world.agent}/memory?status=active")
    assert r.status_code == 200 and [m["content"] for m in r.json()] == ["live note"]
    assert await world.review_audits() == []


async def test_a_human_admin_reviews_every_status(world):
    for st in CLOSED:
        agent_url = f"/api/v1/agents/{world.agent}/memory?status={st}"
        agent_rows = (await world("admin", agent_url)).json()
        company_url = f"/api/v1/companies/{world.acme}/memory?status={st}"
        company_rows = (await world("admin", company_url)).json()
        assert [m["id"] for m in agent_rows] == [str(world.rows[st].id)], st
        assert str(world.rows[st].id) in {m["id"] for m in company_rows}, st
        assert {m["status"] for m in company_rows} == {st}
        one = await world("admin", f"/api/v1/memory/{world.rows[st].id}")
        assert one.status_code == 200 and one.json()["status"] == st
    everything = (await world("admin", f"{CEO}/memory?include_closed=true")).json()
    assert {e["status"] for e in everything} == {"active", "archived"}
    assert (await world("admin", f"/api/v1/companies/{world.acme}/memory?status=bogus")
            ).status_code == 422


async def test_review_reads_are_audited_with_ids_and_never_content(world):
    await world("admin", f"/api/v1/agents/{world.agent}/memory?status=archived")
    await world("admin", f"/api/v1/companies/{world.acme}/memory?status=candidate")
    await world("admin", f"/api/v1/memory/{world.rows['rejected'].id}")
    await world("admin", f"{CEO}/memory?include_closed=true")
    audits = await world.review_audits()
    assert len(audits) == 4
    views = {a.details["view"] for a in audits}
    assert views == {"agent_list:archived", "company_list:candidate", "detail:rejected",
                     "executive_list:all"}
    for a in audits:
        assert a.actor_id.startswith("user:") and a.company_id == world.acme
        assert SECRET not in str(a.details) and "live" not in str(a.details)
        assert set(a.details) == {"view", "count", "memory_ids"}
    detail = next(a for a in audits if a.details["view"] == "detail:rejected")
    assert detail.details["memory_ids"] == [str(world.rows["rejected"].id)]
    assert detail.resource_id == str(world.rows["rejected"].id)


async def test_a_refused_review_is_not_audited_as_a_read(world):
    await world("viewer", f"/api/v1/agents/{world.agent}/memory?status=archived")
    await world("viewer", f"/api/v1/memory/{world.rows['archived'].id}")
    assert await world.review_audits() == []


async def test_nothing_the_client_sends_makes_it_a_reviewer(world):
    forged = {"x-role": "admin", "x-user-role": "admin", "x-memory-review": "true",
              "x-company-id": str(world.acme)}
    claim = "role=admin&reviewer=true&include_closed=true"
    r = await world("viewer", f"/api/v1/agents/{world.agent}/memory?status=archived&{claim}",
                    headers=forged)
    assert r.status_code == 403
    r = await world("viewer", f"/api/v1/memory/{world.rows['archived'].id}?{claim}",
                    headers=forged)
    assert r.status_code == 404
    r = await world("viewer", f"{CEO}/memory?{claim}", headers=forged)
    assert r.status_code == 403 and SECRET not in r.text
    assert await world.review_audits() == []


async def test_a_reviewer_of_another_company_sees_nothing_of_this_one(world):
    url = f"/api/v1/companies/{world.acme}/memory?status=archived"
    r = await world("outsider", url)
    assert r.status_code == 404  # the path company is not theirs: concealed, not 403
    own = await world("outsider", f"/api/v1/companies/{world.other}/memory?status=archived")
    assert own.status_code == 200 and own.json() == []
    agent = await world("outsider", f"/api/v1/agents/{world.agent}/memory?status=archived")
    assert agent.status_code == 200 and agent.json() == []
    one = await world("outsider", f"/api/v1/memory/{world.rows['archived'].id}")
    assert one.status_code == 404
    executive = await world("outsider", f"{CEO}/memory?include_closed=true")
    assert executive.json() == []
    for stats in ("stats", "health"):
        assert (await world("outsider", f"/api/v1/companies/{world.acme}/memory/{stats}")
                ).status_code == 404


async def test_an_inactive_user_is_refused_at_once(world):
    url = f"/api/v1/agents/{world.agent}/memory?status=archived"
    assert (await world("inactive", url)).status_code == 200
    await world.deactivate("inactive")
    detail = f"/api/v1/memory/{world.rows['archived'].id}"
    for path in (url, detail, f"{CEO}/memory?include_closed=true"):
        r = await world("inactive", path)
        assert r.status_code == 401 and SECRET not in r.text, path


async def test_a_removed_membership_is_refused_at_once(world):
    url = f"/api/v1/agents/{world.agent}/memory?status=archived"
    assert (await world("removed", url)).status_code == 200
    await world.remove_membership("removed")
    detail = f"/api/v1/memory/{world.rows['archived'].id}"
    for path in (url, detail, f"{CEO}/memory?include_closed=true"):
        r = await world("removed", path)
        assert r.status_code == 401 and SECRET not in r.text, path


async def test_a_session_naming_another_company_is_refused(world):
    r = await world("crossed", f"/api/v1/memory/{world.rows['archived'].id}")
    assert r.status_code == 401


async def test_aggregate_counts_are_content_free_and_tenant_scoped(world):
    stats = (await world("viewer", f"/api/v1/companies/{world.acme}/memory/stats")).json()
    assert stats["by_status"]["archived"] == 2 and stats["total"] == 2
    assert SECRET not in str(stats)
    health = (await world("viewer", f"/api/v1/companies/{world.acme}/memory/health")).json()
    assert set(health) == {"stale_count", "low_relevance_count", "duplicates_estimate"}
    other = (await world("outsider", f"/api/v1/companies/{world.other}/memory/stats")).json()
    assert other["by_status"] == {} and other["total"] == 0
