"""``/companies/{company_id}/memory*`` conceals the tenant: one 404 for every company but yours.

An existing foreign company, a company that does not exist and one the caller cannot reach
must be indistinguishable: same status, same stable code, same body. Nothing is queried for
the path company, so no row, count, id, name or audit entry can differ either. Both layers
that can answer are covered (the ``world`` fixture runs with the middleware policy and
without it): a request is judged by the caller's own company, never by the company named in
the URL. Inside their own company a caller keeps the ordinary authorization answers, so a
non-admin asking for a non-active status still gets the review 403.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import event, select

import nexus.database as database
from nexus.api import deps
from nexus.api.routes import memory as agent_routes
from nexus.auth.middleware import COMPANY_NOT_FOUND, rejection_for
from nexus.auth.principal import Principal
from nexus.models.governance import AuditLog
from nexus.models.memory import MemoryRecord
from tests.test_memory_review_access import SECRET, world  # noqa: F401 -- fixture
from tests.test_tool_access import factory, t  # noqa: F401 -- fixtures world builds on

NOT_FOUND = {"detail": COMPANY_NOT_FOUND}
SUFFIXES = ("", "?status=archived", "?status=candidate", "/stats", "/health", "/graph")
ROUTES = tuple(f"/api/v1/companies/{{c}}/memory{s}" for s in SUFFIXES)
CALLERS = ("admin", "viewer", "member", "run", "admin_key")


def _own_status(who: str, route: str) -> int:
    """Inside the caller's own company the ordinary authorization answers apply."""
    reviewing = "status=archived" in route or "status=candidate" in route
    return 403 if reviewing and who != "admin" else 200


def _sep(route: str) -> str:
    return "&" if "?" in route else "?"


@pytest.fixture
def sql(world, monkeypatch):  # noqa: F811
    """Every statement the database runs, and every tenant a session was bound to."""
    statements: list[str] = []
    bound: list[uuid.UUID] = []
    engine = world.engine.sync_engine

    def record(conn, cursor, statement, *args):
        statements.append(statement)

    event.listen(engine, "before_cursor_execute", record)
    real = database._bind_tenant

    def spy(session, company_id):
        bound.append(company_id)
        return real(session, company_id)

    monkeypatch.setattr(database, "_bind_tenant", spy)
    yield statements, bound
    event.remove(engine, "before_cursor_execute", record)


async def _snapshot(world):  # noqa: F811
    async with world.factory() as db:
        rows = (
            await db.execute(
                select(MemoryRecord.id, MemoryRecord.status, MemoryRecord.content,
                       MemoryRecord.updated_at)
            )
        ).all()
        audits = (await db.execute(select(AuditLog.id))).scalars().all()
    return sorted(map(tuple, rows)), sorted(audits)


@pytest.mark.parametrize("route", ROUTES)
@pytest.mark.parametrize("who", CALLERS)
async def test_own_company_keeps_normal_authorization(world, who, route):  # noqa: F811
    r = await world(who, route.format(c=world.acme))
    assert r.status_code == _own_status(who, route), (who, route, r.text[:200])
    if r.status_code == 403:
        assert r.json()["detail"]["code"] == "MEMORY_REVIEW_FORBIDDEN"


@pytest.mark.parametrize("route", ROUTES)
@pytest.mark.parametrize("who", CALLERS)
async def test_foreign_and_nonexistent_companies_are_the_same_404(world, who, route):  # noqa: F811
    seen = {}
    for label, company in (("foreign", world.other), ("missing", uuid.uuid4())):
        r = await world(who, route.format(c=company))
        assert r.status_code == 404, (who, route, label, r.status_code)
        assert r.json() == NOT_FOUND, (who, route, label)
        seen[label] = (r.status_code, r.json(), r.headers.get("content-type"))
    assert seen["foreign"] == seen["missing"]


@pytest.mark.parametrize("route", ROUTES)
async def test_a_foreign_admin_is_concealed_too(world, route):  # noqa: F811
    for company in (world.acme, uuid.uuid4()):
        r = await world("outsider", route.format(c=company))
        assert (r.status_code, r.json()) == (404, NOT_FOUND), (route, company)
        assert SECRET not in r.text


@pytest.mark.parametrize("route", ROUTES)
async def test_admin_authority_stops_at_their_own_company(world, route):  # noqa: F811
    own = await world("outsider", route.format(c=world.other))
    assert own.status_code == 200  # the outsider administers `other`, and only that
    r = await world("admin", route.format(c=world.other))
    assert (r.status_code, r.json()) == (404, NOT_FOUND)  # acme's admin has no standing there


@pytest.mark.parametrize("route", ROUTES)
async def test_a_forged_claim_cannot_select_another_tenant(world, route):  # noqa: F811
    forged = {"x-role": "admin", "x-company-id": str(world.acme), "x-memory-review": "true"}
    for company in (world.acme, world.other, uuid.uuid4()):
        url = route.format(c=company) + _sep(route) + "role=admin&company_id=" + str(world.acme)
        r = await world("outsider", url, headers=forged)
        assert r.status_code == (200 if company == world.other else 404), (route, company)
        assert SECRET not in r.text
    # A non-admin forging admin headers is still a non-admin in their own company.
    r = await world("viewer", f"/api/v1/companies/{world.acme}/memory?status=archived",
                    headers=forged)
    assert r.status_code == 403


@pytest.mark.parametrize("route", ROUTES)
@pytest.mark.parametrize("who", ("inactive", "removed"))
async def test_inactive_or_removed_callers_learn_nothing(world, who, route):  # noqa: F811
    await (world.deactivate if who == "inactive" else world.remove_membership)(who)
    answers = set()
    for company in (world.acme, world.other, uuid.uuid4()):
        r = await world(who, route.format(c=company))
        assert r.status_code == 401 and SECRET not in r.text, (who, route, company)
        answers.add((r.status_code, r.text))
    assert len(answers) == 1  # existence cannot be told apart


@pytest.mark.parametrize("route", ROUTES)
@pytest.mark.parametrize("who", CALLERS)
async def test_concealed_requests_read_nothing_write_nothing_and_audit_nothing(
    world, sql, who, route  # noqa: F811
):
    statements, bound = sql
    before = await _snapshot(world)
    start = len(statements)  # the snapshot itself reads memory_records
    for company in (world.other, uuid.uuid4()):
        assert (await world(who, route.format(c=company))).status_code == 404
    assert [s for s in statements[start:] if "memory_records" in s] == []  # no memory query
    assert set(bound) <= {world.acme}  # no session was bound to a path company
    assert await _snapshot(world) == before
    assert await world.review_audits() == []


@pytest.mark.parametrize("route", ROUTES)
async def test_a_foreign_admins_request_creates_no_review_audit_here(world, route):  # noqa: F811
    await world("outsider", route.format(c=world.acme))
    assert [a for a in await world.review_audits() if a.company_id == world.acme] == []


def test_every_company_memory_route_uses_the_concealing_dependency():
    from nexus.api.routes import memory_global, memory_graph
    from nexus.main import app

    prefix = "/api/v1/companies/{company_id}/memory"
    found = {}
    for router in (memory_global.router, memory_graph.router):
        for route in router.routes:
            if route.path.startswith(prefix):
                calls = [d.call for d in route.dependant.dependencies]
                assert agent_routes.get_memory_company_id in calls, route.path
                assert deps.get_scoped_company_id not in calls, route.path
                found[route.path] = route.methods
    assert found == {
        f"{prefix}": {"GET"},
        f"{prefix}/stats": {"GET"},
        f"{prefix}/health": {"GET"},
        f"{prefix}/graph": {"GET"},
    }
    # No create, update or archive lives under this prefix; a new route must be added here.
    published = {p: set(v) for p, v in app.openapi()["paths"].items() if p.startswith(prefix)}
    assert published == {p: {"get"} for p in found}
def test_only_the_memory_paths_conceal_other_company_paths_keep_the_403():
    mine, theirs = uuid.uuid4(), uuid.uuid4()
    me = Principal(kind="user", company_id=mine, role="admin", user_id=uuid.uuid4())
    assert rejection_for(f"/api/v1/companies/{theirs}/agents", me).status_code == 403
    assert rejection_for(f"/api/v1/companies/{theirs}/memoryx", me).status_code == 403
    for tail in ("memory", "memory/stats", "memory/graph", "memory/health"):
        assert rejection_for(f"/api/v1/companies/{theirs}/{tail}", me).status_code == 404
    assert rejection_for(f"/api/v1/companies/{mine}/memory", me) is None
