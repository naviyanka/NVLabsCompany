"""Task routes: bound to the path company, canonical parent/agent checks, explicit permissions.

A. Every ``/companies/{company_id}/tasks*`` route takes ``PathCompanyId``: a foreign and a
   nonexistent company get the same 403 in all three UUID spellings, and nothing is read or
   written for a rejected path.
B. ``TaskService.create_task`` validates the parent and the assigned agent by ``(company, id)``
   before it inserts, so the routes and a direct service call answer the same.
C. Every Task route declares ``read:task`` or ``write:task``; a static guard fails when a future
   mutation route does not.
"""

# ruff: noqa: F811  (pytest fixtures are imported, then named as test parameters)

from __future__ import annotations

import importlib
import inspect
import pkgutil
import re
import uuid
from contextlib import contextmanager

import pytest
from fastapi import APIRouter, HTTPException
from fastapi.routing import APIRoute
from sqlalchemy import event

import nexus.api.routes as route_pkg
from nexus.api.deps import get_scoped_company_id
from nexus.api.routes import tasks as task_routes
from nexus.governance.rbac import role_allows
from nexus.models.agent import Agent
from nexus.models.task import Task
from nexus.services.task_service import TaskService
from tests.test_employee_work import _rows, db, w  # noqa: F401 -- fixtures
from tests.test_work_service import _get, api, co  # noqa: F401 -- fixtures and helpers
from tests.test_work_task_route_guards import _plain

pytestmark = pytest.mark.employee_work

FORMS = {
    "dashed": str,
    "hex": lambda u: u.hex,
    "urn": lambda u: f"urn:uuid:{u}",
}


@contextmanager
def _sql(co):
    """Every statement the engine runs while the block is open."""
    seen: list[str] = []
    engine = co["db"].engine.sync_engine

    def hook(conn, cursor, statement, params, context, executemany):
        seen.append(statement)

    event.listen(engine, "before_cursor_execute", hook)
    try:
        yield seen
    finally:
        event.remove(engine, "before_cursor_execute", hook)


async def _count(co, model, company_key):
    return len(await _rows(co["db"], model, model.company_id == co[company_key]))


async def _agent(co, status, key="acme"):
    async with co["db"]() as s:
        agent = Agent(
            company_id=co[key],
            name=f"{status}-agent",
            role="analyst",
            adapter_type="openai",
            model="gpt-x",
            status=status,
        )
        s.add(agent)
        await s.commit()
        return agent.id


async def _foreign_task(co):
    return await _plain({**co, "acme": co["other"]})


def _company_routes(co, company):
    base = f"/api/v1/companies/{company}/tasks"
    return [
        ("GET", base, None),
        ("GET", f"{base}/stats", None),
        ("POST", base, {"title": "x"}),
    ]


class TestPathCompany:
    @pytest.mark.parametrize("form", FORMS)
    async def test_own_company_works_in_every_uuid_form(self, form, co, api):
        spell = FORMS[form]
        company = spell(co["acme"])
        listed = await api("GET", f"/api/v1/companies/{company}/tasks")
        stats = await api("GET", f"/api/v1/companies/{company}/tasks/stats")
        created = await api("POST", f"/api/v1/companies/{company}/tasks", {"title": f"t-{form}"})
        assert (listed.status_code, stats.status_code, created.status_code) == (200, 200, 201)
        assert created.json()["company_id"] == str(co["acme"])
        (row,) = await _rows(co["db"], Task, Task.title == f"t-{form}")
        assert row.company_id == co["acme"]

    @pytest.mark.parametrize("form", FORMS)
    async def test_foreign_and_nonexistent_company_get_the_same_refusal(self, form, co, api):
        spell = FORMS[form]
        before = (await _count(co, Task, "acme"), await _count(co, Task, "other"))
        for index, (method, _path, body) in enumerate(_company_routes(co, "x")):
            answers = []
            for target in (co["other"], uuid.uuid4()):
                path = _company_routes(co, spell(target))[index][1]
                with _sql(co) as seen:
                    res = await api(method, path, body)
                assert seen == [], (method, path, seen)
                answers.append((res.status_code, res.json()))
            assert answers[0] == answers[1], (method, answers)
            assert answers[0][0] == 403
        assert (await _count(co, Task, "acme"), await _count(co, Task, "other")) == before

    async def test_a_foreign_path_never_acts_on_the_callers_company(self, co, api):
        """The caller's own company must not be listed, written or counted via a foreign path."""
        await _plain(co)
        res = await api("GET", f"/api/v1/companies/{co['other']}/tasks")
        assert res.status_code == 403 and "detail" in res.json()
        res = await api("POST", f"/api/v1/companies/{co['other']}/tasks", {"title": "leak"})
        assert res.status_code == 403
        assert await _rows(co["db"], Task, Task.title == "leak") == []

    async def test_a_caller_in_another_company_gets_403_for_this_one(self, co, api):
        for method, path, body in _company_routes(co, co["acme"]):
            res = await api(method, path, body, who="outsider")
            assert res.status_code == 403, (method, path)

    @pytest.mark.parametrize("bad", ["not-a-uuid", "1234", "zzzz" * 8])
    async def test_malformed_company_returns_the_stable_validation_response(self, bad, co, api):
        with _sql(co) as seen:
            answers = [
                await api(method, path, body) for method, path, body in _company_routes(co, bad)
            ]
        assert seen == []
        assert {r.status_code for r in answers} == {422}
        assert all(r.json()["detail"][0]["loc"][-1] == "company_id" for r in answers)

    async def test_item_routes_treat_a_foreign_task_like_a_missing_one(self, co, api):
        foreign = await _foreign_task(co)
        agent = str(co["other_lead"])
        before = await _get(co, Task, foreign)
        snapshot = (before.status, before.assigned_agent_id, before.parent_task_id)
        total = await _count(co, Task, "other")

        def routes(task):
            return [
                ("GET", f"/api/v1/tasks/{task}", None),
                ("PUT", f"/api/v1/tasks/{task}/assign", {"agent_id": agent}),
                ("POST", f"/api/v1/tasks/{task}/reassign", {"agent_id": agent}),
                ("PUT", f"/api/v1/tasks/{task}/status", {"status": "running"}),
                ("POST", f"/api/v1/tasks/{task}/subtasks", {"title": "x"}),
                ("POST", f"/api/v1/tasks/{task}/cancel", None),
                ("POST", f"/api/v1/tasks/{task}/decompose", None),
            ]

        missing = uuid.uuid4()
        for (method, foreign_path, body), (_, missing_path, _b) in zip(
            routes(foreign), routes(missing)
        ):
            answers = []
            for task, path in ((foreign, foreign_path), (missing, missing_path)):
                res = await api(method, path, body, who="admin")
                answers.append((res.status_code, res.text.replace(str(task), "<id>")))
            # "admin" is acme's principal: the other company's task is foreign to it.
            assert answers[0] == answers[1], (method, foreign_path, answers)
            assert answers[0][0] == 404
        after = await _get(co, Task, foreign)
        assert (after.status, after.assigned_agent_id, after.parent_task_id) == snapshot
        assert await _count(co, Task, "other") == total

    async def test_tasks_module_has_no_raw_company_parameter(self):
        for route in task_routes.router.routes:
            assert isinstance(route, APIRoute)
            raw = {p.name for p in route.dependant.path_params}
            if "{company_id}" in route.path:
                assert "company_id" not in raw, route.path
                assert get_scoped_company_id in _flatten(route.dependant), route.path


def _flatten(dependant):
    for sub in dependant.dependencies:
        yield sub.call
        yield from _flatten(sub)


def _routers():
    for info in pkgutil.iter_modules(route_pkg.__path__):
        module = importlib.import_module(f"nexus.api.routes.{info.name}")
        seen: set[int] = set()
        for router in vars(module).values():
            if isinstance(router, APIRouter) and id(router) not in seen:
                seen.add(id(router))
                yield info.name, router


# Routes that still take {company_id} without PathCompanyId, per module. This is the wider
# follow-up: each module moves to PathCompanyId in its own change and its count drops to zero.
# The Task routes are already at zero. A new unscoped route fails this test.
UNSCOPED_COMPANY_ROUTES = {
    "activity": 3,
    "agent_profiling": 1,
    "agents": 4,
    "audit": 3,
    "communication": 6,
    "company_sim": 8,
    "dashboard": 5,
    "departments": 2,
    "goals": 3,
    "hiring": 2,
    "hr": 7,
    "knowledge": 8,
    "meetings": 3,
    "memory_evidence": 5,
    "memory_global": 3,
    "memory_graph": 1,
    "notifications": 6,
    "pipelines": 3,
    "plaza": 2,
    "tools": 2,
    "triggers": 2,
    "workflows": 1,
    "workspaces": 2,
}


def test_unscoped_company_routes_do_not_grow_and_tasks_has_none():
    found: dict[str, int] = {}
    for name, router in _routers():
        for route in router.routes:
            if (
                isinstance(route, APIRoute)
                and "{company_id}" in route.path
                and get_scoped_company_id not in set(_flatten(route.dependant))
            ):
                found[name] = found.get(name, 0) + 1
    assert "tasks" not in found
    grown = {m: n for m, n in found.items() if n > UNSCOPED_COMPANY_ROUTES.get(m, 0)}
    assert not grown, f"new routes take a raw company_id; use PathCompanyId: {grown}"
    shrunk = {m: n for m, n in UNSCOPED_COMPANY_ROUTES.items() if found.get(m, 0) < n}
    assert not shrunk, f"lower these counts in UNSCOPED_COMPANY_ROUTES: {shrunk}"


# ---------------------------------------------------------------------------
# B. Parent and assigned agent, one canonical check
# ---------------------------------------------------------------------------

CLOSED = ("completed", "failed", "cancelled")
UNAVAILABLE = ("paused", "terminated", "archived")


async def _case(co, name):
    """(kwargs for the service, expected (status, code)) for a named rejected input."""
    own_parent = await _plain(co)
    if name == "foreign_parent":
        return {"parent_task_id": await _foreign_task(co)}, (404, "PARENT_TASK_NOT_FOUND")
    if name == "missing_parent":
        return {"parent_task_id": uuid.uuid4()}, (404, "PARENT_TASK_NOT_FOUND")
    if name.startswith("parent_"):
        parent = await _plain(co, status=name.removeprefix("parent_"))
        return {"parent_task_id": parent}, (409, "PARENT_TASK_CLOSED")
    if name == "foreign_agent":
        return {"assigned_agent_id": co["other_ceo"]}, (404, "AGENT_NOT_FOUND")
    if name == "missing_agent":
        return {"assigned_agent_id": uuid.uuid4()}, (404, "AGENT_NOT_FOUND")
    agent = await _agent(co, name.removeprefix("agent_"))
    del own_parent
    return {"assigned_agent_id": agent}, (409, "AGENT_NOT_ASSIGNABLE")


CASES = [
    "foreign_parent",
    "missing_parent",
    *(f"parent_{s}" for s in CLOSED),
    "foreign_agent",
    "missing_agent",
    *(f"agent_{s}" for s in UNAVAILABLE),
]


class TestParentAndAgentValidation:
    @pytest.mark.parametrize("name", CASES)
    async def test_routes_and_service_refuse_the_same_way_and_insert_nothing(self, name, co, api):
        kwargs, expected = await _case(co, name)
        sub_parent = kwargs.get("parent_task_id") or await _plain(co)
        foreign_agent = await _get(co, Agent, co["other_ceo"])
        agent_before = foreign_agent.model_dump()
        counts = (await _count(co, Task, "acme"), await _count(co, Task, "other"))

        body = {"title": "child"}
        if "parent_task_id" in kwargs:
            body["parent_task_id"] = str(kwargs["parent_task_id"])
        if "assigned_agent_id" in kwargs:
            body["assigned_agent_id"] = str(kwargs["assigned_agent_id"])
        created = await api("POST", f"/api/v1/companies/{co['acme']}/tasks", body)
        answers = {"create_task": (created.status_code, created.json()["detail"])}

        sub_body = {k: v for k, v in body.items() if k != "parent_task_id"}
        sub = await api("POST", f"/api/v1/tasks/{sub_parent}/subtasks", sub_body)
        answers["create_subtask"] = (sub.status_code, sub.json()["detail"])

        async with co["db"]() as s:
            with pytest.raises(HTTPException) as caught:
                await TaskService(s).create_task(co["acme"], "child", **kwargs)
        answers["service"] = (caught.value.status_code, caught.value.detail)

        for who, (status, detail) in answers.items():
            assert (status, detail["code"]) == expected, (who, detail)
        assert answers["create_task"] == answers["create_subtask"] == answers["service"], name
        assert str(kwargs.get("parent_task_id")) not in str(answers)
        assert (await _count(co, Task, "acme"), await _count(co, Task, "other")) == counts
        assert (await _get(co, Agent, co["other_ceo"])).model_dump() == agent_before
        assert await _rows(co["db"], Task, Task.title.in_(["child"])) == []

    async def test_foreign_and_missing_get_the_same_body(self, co):
        outcomes = []
        for name in ("foreign_parent", "missing_parent", "foreign_agent", "missing_agent"):
            kwargs, _ = await _case(co, name)
            async with co["db"]() as s:
                with pytest.raises(HTTPException) as caught:
                    await TaskService(s).create_task(co["acme"], "child", **kwargs)
            outcomes.append((caught.value.status_code, caught.value.detail))
        assert outcomes[0] == outcomes[1] and outcomes[2] == outcomes[3]

    async def test_an_open_parent_and_an_active_agent_are_accepted(self, co, api):
        parent = await _plain(co)
        res = await api(
            "POST",
            f"/api/v1/companies/{co['acme']}/tasks",
            {
                "title": "ok",
                "parent_task_id": str(parent),
                "assigned_agent_id": str(co["acme_eve"]),
            },
        )
        assert res.status_code == 201, res.text
        sub = await api(
            "POST",
            f"/api/v1/tasks/{parent}/subtasks",
            {"title": "ok2", "assigned_agent_id": str(co["acme_eve"])},
        )
        assert sub.status_code == 201, sub.text
        async with co["db"]() as s:
            task = await TaskService(s).create_task(
                co["acme"], "ok3", parent_task_id=parent, assigned_agent_id=co["acme_eve"]
            )
            await s.commit()
        assert task.parent_task_id == parent

    @pytest.mark.parametrize("route", ["assign", "reassign"])
    async def test_assign_and_reassign_check_the_agent_by_company_and_availability(
        self, route, co, api
    ):
        method = "PUT" if route == "assign" else "POST"
        target = await _plain(co)
        before = await _get(co, Task, target)
        cases = [
            (co["other_ceo"], (404, "AGENT_NOT_FOUND")),
            (uuid.uuid4(), (404, "AGENT_NOT_FOUND")),
        ]
        for s in UNAVAILABLE:
            cases.append((await _agent(co, s), (409, "AGENT_NOT_ASSIGNABLE")))
        for agent, expected in cases:
            res = await api(method, f"/api/v1/tasks/{target}/{route}", {"agent_id": str(agent)})
            assert (res.status_code, res.json()["detail"]["code"]) == expected
        after = await _get(co, Task, target)
        assert after.assigned_agent_id == before.assigned_agent_id
        assert (await _get(co, Agent, co["other_ceo"])).status == "idle"

    @pytest.mark.parametrize("status", CLOSED)
    async def test_decompose_refuses_a_closed_task(self, status, co, api):
        target = await _plain(co, status=status)
        total = await _count(co, Task, "acme")
        res = await api("POST", f"/api/v1/tasks/{target}/decompose")
        assert (res.status_code, res.json()["detail"]["code"]) == (409, "PARENT_TASK_CLOSED")
        assert await _count(co, Task, "acme") == total

    async def test_a_work_parent_is_still_owned_by_the_lifecycle(self, co, api):
        from tests.test_work_service import _order

        work = await _order(co)
        res = await api("POST", f"/api/v1/tasks/{work}/subtasks", {"title": "x"})
        assert (res.status_code, res.json()["detail"]["code"]) == (409, "WORK_OWNED_BY_LIFECYCLE")
        async with co["db"]() as s:
            with pytest.raises(HTTPException) as caught:
                await TaskService(s).create_task(co["acme"], "x", parent_task_id=work)
        assert caught.value.detail["code"] == "WORK_OWNED_BY_LIFECYCLE"


# ---------------------------------------------------------------------------
# C. Permissions
# ---------------------------------------------------------------------------

ROLES = ("admin", "manager", "employee", "viewer", "guest")
ROLE_NAME = {"employee": "agent"}


async def _every_route(co):
    """(kind, method, path, body) for every Task route, each aimed at its own fresh task."""
    base = f"/api/v1/companies/{co['acme']}/tasks"
    agent = str(co["acme_eve"])
    out = []
    for kind, method, path, body in _route_table(base, agent):
        task = await _plain(co)
        out.append((kind, method, path.format(task=task), body))
    return out


def _route_table(base, agent):
    return [
        ("read", "GET", base, None),
        ("read", "GET", base + "/stats", None),
        ("read", "GET", "/api/v1/tasks/{task}", None),
        ("read", "GET", "/api/v1/tasks/{task}/subtasks", None),
        ("write", "POST", base, {"title": "p"}),
        ("write", "PUT", "/api/v1/tasks/{task}/assign", {"agent_id": agent}),
        ("write", "PUT", "/api/v1/tasks/{task}/status", {"status": "running"}),
        ("write", "POST", "/api/v1/tasks/{task}/subtasks", {"title": "p"}),
        ("write", "POST", "/api/v1/tasks/{task}/reassign", {"agent_id": agent}),
        ("write", "POST", "/api/v1/tasks/{task}/cancel", None),
        ("write", "POST", "/api/v1/tasks/{task}/decompose", None),
    ]


class TestPermissions:
    @pytest.mark.parametrize("who", ROLES)
    async def test_each_role_gets_exactly_what_rbac_grants(self, who, co, api):
        role = ROLE_NAME.get(who, who)
        for kind, method, path, body in await _every_route(co):
            allowed = role_allows(role, kind, "task")
            fresh = path
            res = await api(method, fresh, body, who=who)
            if allowed:
                assert res.status_code < 300, (who, method, path, res.text)
            else:
                assert res.status_code == 403, (who, method, path, res.status_code)
                assert res.json()["detail"] == f"Role '{role}' may not {kind} task"

    async def test_a_viewer_reads_and_cannot_mutate_anything(self, co, api):
        routes = await _every_route(co)
        before = await _count(co, Task, "acme")
        for kind, method, path, body in routes:
            res = await api(method, path, body, who="viewer")
            assert res.status_code == (200 if kind == "read" else 403), (method, path)
        assert await _count(co, Task, "acme") == before

    async def test_a_run_token_follows_the_agent_role(self, co, api):
        for kind, method, path, body in await _every_route(co):
            res = await api(method, path, body, who="run")
            assert (res.status_code < 300) == role_allows("agent", kind, "task"), (method, path)

    async def test_a_denied_mutation_changes_nothing(self, co, api):
        target = await _plain(co)
        before = await _get(co, Task, target)
        for method, path, body in (
            ("PUT", f"/api/v1/tasks/{target}/assign", {"agent_id": str(co["acme_eve"])}),
            ("PUT", f"/api/v1/tasks/{target}/status", {"status": "running"}),
            ("POST", f"/api/v1/tasks/{target}/cancel", None),
        ):
            for who in ("viewer", "guest"):
                with _sql(co) as seen:
                    res = await api(method, path, body, who=who)
                assert res.status_code == 403
                assert not [q for q in seen if q.lstrip().upper().startswith(("UPDATE", "INSERT"))]
        after = await _get(co, Task, target)
        assert (after.status, after.assigned_agent_id) == (before.status, before.assigned_agent_id)


def _permissions(route):
    out = set()
    for call in _flatten(route.dependant):
        if call.__module__ == "nexus.api.deps" and call.__qualname__.startswith(
            "require_permission.<locals>"
        ):
            cell = inspect.getclosurevars(call).nonlocals
            out.add((cell["action"], cell["resource_type"]))
    return out


TASK_PATH = re.compile(r"/tasks(/|$)")
MUTATING = {"POST", "PUT", "PATCH", "DELETE"}


class TestStaticRouteGuard:
    def test_every_task_route_declares_its_permission(self):
        checked = 0
        for name, router in _routers():
            for route in router.routes:
                if not (isinstance(route, APIRoute) and TASK_PATH.search(route.path)):
                    continue
                perms = _permissions(route)
                if route.methods & MUTATING:
                    assert ("write", "task") in perms, (name, sorted(route.methods), route.path)
                else:
                    assert perms & {("read", "task"), ("write", "task")}, (name, route.path)
                checked += 1
        assert checked >= 17

    def test_task_routes_declare_the_documented_permissions(self):
        table = {
            (m, r.path): _permissions(r)
            for r in task_routes.router.routes
            if isinstance(r, APIRoute)
            for m in r.methods
        }
        assert len(table) == 11
        for (method, path), perms in table.items():
            expected = {("read", "task")} if method == "GET" else {("write", "task")}
            assert perms == expected, (method, path)

    def test_http_permissions_do_not_use_tool_policy(self):
        source = inspect.getsource(task_routes)
        for banned in ("ToolPolicy", "check_tool_access", "decide_policy"):
            assert banned not in source
        for route in task_routes.router.routes:
            for call in _flatten(route.dependant):
                assert "tools" not in call.__module__, (route.path, call)
