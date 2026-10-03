"""Goal routes: path-bound company, goal permissions, canonical references, safe lifecycle.

Every goal route goes through the real router. People come in through the real cookie resolver
and the other principal kinds are injected in front of the same routes (``route_world`` from the
agent route tests). A refused call leaves the goal rows and the audit log exactly as they were.
"""

# ruff: noqa: F811  (pytest fixtures are imported, then named as test parameters)

from __future__ import annotations

import uuid
from contextlib import contextmanager

import pytest
from fastapi.routing import APIRoute
from sqlalchemy import event

from nexus.api.deps import get_scoped_company_id
from nexus.api.routes import goals as goal_routes
from nexus.models.agent import Agent
from nexus.models.governance import AuditLog
from nexus.models.governance_studio import GovernanceRestriction
from nexus.models.task import Goal, Task
from tests.test_agent_route_security import route_world  # noqa: F401 -- fixture
from tests.test_employee_work import _rows, db, w  # noqa: F401 -- fixtures
from tests.test_task_route_security import FORMS, _flatten
from tests.test_work_service import _get, co  # noqa: F401 -- fixtures, helpers

pytestmark = pytest.mark.employee_work

GOALS = "/api/v1/companies/{company}/goals"
ITEM = "/api/v1/goals/{goal}"


@contextmanager
def _sql(co):
    seen: list[str] = []
    engine = co["db"].engine.sync_engine

    def hook(conn, cursor, statement, params, context, executemany):
        seen.append(statement)

    event.listen(engine, "before_cursor_execute", hook)
    try:
        yield seen
    finally:
        event.remove(engine, "before_cursor_execute", hook)


async def _goal(co, key="acme", status="active", **kw):
    async with co["db"]() as s:
        goal = Goal(company_id=co[key], title=f"{key}-{status}", status=status, **kw)
        s.add(goal)
        await s.commit()
        return goal.id


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


async def _state(co):
    """Every goal row and the number of audit rows: what a refused call must not change."""
    goals = sorted(
        (str(g.id), g.title, g.status, str(g.parent_id), str(g.owner_agent_id), g.updated_at)
        for g in await _rows(co["db"], Goal)
    )
    return goals, len(await _rows(co["db"], AuditLog))


async def _restrict(co, scope, agent=None):
    async with co["db"]() as s:
        s.add(
            GovernanceRestriction(
                company_id=co["acme"],
                scope=scope,
                agent_id=agent,
                kind="isolation" if scope == "agent" else "lockdown",
                reason="test",
                created_by="admin",
            )
        )
        await s.commit()


def _goal_audits(rows):
    return [r.action for r in rows if r.action.startswith("goal.")]


class TestPathCompany:
    @pytest.mark.parametrize("form", FORMS)
    async def test_own_company_works_in_every_uuid_form(self, form, co, route_world):
        company = FORMS[form](co["acme"])
        base = f"/api/v1/companies/{company}/goals"
        listed = await route_world("GET", base)
        stats = await route_world("GET", f"{base}/stats")
        created = await route_world("POST", base, "admin", {"title": f"g-{form}"})
        assert (listed.status_code, stats.status_code, created.status_code) == (200, 200, 201)
        assert created.json()["company_id"] == str(co["acme"])
        (row,) = await _rows(co["db"], Goal, Goal.title == f"g-{form}")
        assert row.company_id == co["acme"] and row.status == "active"

    @pytest.mark.parametrize("form", FORMS)
    async def test_foreign_and_nonexistent_company_get_the_same_refusal(
        self, form, co, route_world
    ):
        spell = FORMS[form]
        before = await _state(co)
        for method, suffix, body in (
            ("GET", "", None),
            ("GET", "/stats", None),
            ("POST", "", {"title": "leak"}),
        ):
            answers = []
            for target in (co["other"], uuid.uuid4()):
                path = f"/api/v1/companies/{spell(target)}/goals{suffix}"
                with _sql(co) as seen:
                    res = await route_world(method, path, "api_key", body)
                assert seen == [], (method, path, seen)
                answers.append((res.status_code, res.json()))
            assert answers[0] == answers[1] and answers[0][0] == 403, (method, answers)
        assert await _state(co) == before

    async def test_a_caller_in_another_company_is_refused(self, co, route_world):
        for method, suffix, body in (("GET", "", None), ("POST", "", {"title": "x"})):
            path = f"/api/v1/companies/{co['acme']}/goals{suffix}"
            assert (await route_world(method, path, "outsider", body)).status_code == 403
        assert await _rows(co["db"], Goal) == []

    @pytest.mark.parametrize("bad", ["not-a-uuid", "1234"])
    async def test_malformed_company_is_a_validation_error(self, bad, co, route_world):
        res = await route_world("GET", f"/api/v1/companies/{bad}/goals")
        assert res.status_code == 422


class TestPermissions:
    WRITE_DENIED = ("viewer", "employee", "guest", "run", "run_other", "unknown")

    def _writes(self, co, goal):
        return (
            ("POST", GOALS.format(company=co["acme"]), {"title": "new"}),
            ("PUT", ITEM.format(goal=goal), {"title": "renamed"}),
            ("DELETE", ITEM.format(goal=goal), None),
            ("POST", ITEM.format(goal=goal) + "/execute", None),
        )

    @pytest.mark.parametrize("who", WRITE_DENIED)
    async def test_only_goal_writers_change_goals(self, who, co, route_world):
        goal = await _goal(co)
        before = await _state(co)
        calls_before = co["model"].calls
        for method, path, body in self._writes(co, goal):
            res = await route_world(method, path, who, body)
            assert res.status_code == 403, (who, method, path, res.text)
        assert await _state(co) == before
        assert co["model"].calls == calls_before

    @pytest.mark.parametrize("who", ("viewer", "employee", "manager", "admin", "run"))
    async def test_goal_readers(self, who, co, route_world):
        goal = await _goal(co)
        for path in (GOALS.format(company=co["acme"]), ITEM.format(goal=goal)):
            assert (await route_world("GET", path, who)).status_code == 200, (who, path)

    async def test_a_guest_cannot_read_goals(self, co, route_world):
        goal = await _goal(co)
        for path in (GOALS.format(company=co["acme"]), ITEM.format(goal=goal)):
            assert (await route_world("GET", path, "guest")).status_code == 403

    @pytest.mark.parametrize("who", ("admin", "manager", "api_key", "worker"))
    async def test_goal_writers_can_create_update_and_delete(self, who, co, route_world):
        made = await route_world("POST", GOALS.format(company=co["acme"]), who, {"title": "g"})
        assert made.status_code == 201
        goal = made.json()["id"]
        put = await route_world("PUT", ITEM.format(goal=goal), who, {"title": "renamed"})
        assert put.status_code == 200 and put.json()["title"] == "renamed"
        assert (await route_world("DELETE", ITEM.format(goal=goal), who)).status_code == 204
        assert await _rows(co["db"], Goal) == []
        assert _goal_audits(await _rows(co["db"], AuditLog)) == [
            "goal.created",
            "goal.updated",
            "goal.deleted",
        ]

    @pytest.mark.parametrize("name", ("inactive", "removed"))
    async def test_a_deactivated_or_removed_user_is_refused(self, name, co, route_world):
        if name == "inactive":
            await route_world.deactivate(name)
        else:
            await route_world.remove_membership(name)
        res = await route_world("POST", GOALS.format(company=co["acme"]), name, {"title": "x"})
        assert res.status_code == 401
        assert await _rows(co["db"], Goal) == []


class TestCreateReferences:
    async def _post(self, co, route_world, **body):
        return await route_world(
            "POST", GOALS.format(company=co["acme"]), "admin", {"title": "child", **body}
        )

    async def test_own_parent_and_owner_are_accepted(self, co, route_world):
        parent = await _goal(co)
        res = await self._post(
            co, route_world, parent_id=str(parent), owner_agent_id=str(co["acme_eve"])
        )
        assert res.status_code == 201
        assert res.json()["parent_id"] == str(parent)
        assert res.json()["owner_agent_id"] == str(co["acme_eve"])

    async def test_a_foreign_parent_is_the_same_404_as_a_missing_one(self, co, route_world):
        foreign = await _goal(co, "other")
        before = await _state(co)
        answers = []
        for parent in (foreign, uuid.uuid4()):
            res = await self._post(co, route_world, parent_id=str(parent))
            answers.append((res.status_code, res.text.replace(str(parent), "<id>")))
        assert answers[0] == answers[1] and answers[0][0] == 404
        assert "GOAL_NOT_FOUND" in answers[0][1]
        assert await _state(co) == before

    @pytest.mark.parametrize("closed", ("completed", "cancelled", "archived"))
    async def test_a_closed_parent_is_409(self, closed, co, route_world):
        parent = await _goal(co, status=closed)
        before = await _state(co)
        res = await self._post(co, route_world, parent_id=str(parent))
        assert res.status_code == 409 and res.json()["detail"]["code"] == "GOAL_CLOSED"
        assert await _state(co) == before

    async def test_a_foreign_owner_is_the_same_404_as_a_missing_one(self, co, route_world):
        before = await _state(co)
        answers = []
        for owner in (co["other_eve"], uuid.uuid4()):
            res = await self._post(co, route_world, owner_agent_id=str(owner))
            answers.append((res.status_code, res.text.replace(str(owner), "<id>")))
        assert answers[0] == answers[1] and answers[0][0] == 404
        assert "AGENT_NOT_FOUND" in answers[0][1]
        assert await _state(co) == before

    @pytest.mark.parametrize("agent_status", ("paused", "terminated", "archived"))
    async def test_an_ineligible_owner_is_409(self, agent_status, co, route_world):
        owner = await _agent(co, agent_status)
        before = await _state(co)
        res = await self._post(co, route_world, owner_agent_id=str(owner))
        assert res.status_code == 409
        assert res.json()["detail"]["code"] == "AGENT_NOT_ASSIGNABLE"
        assert await _state(co) == before

    @pytest.mark.parametrize("field", ("status", "company_id", "completion_reason"))
    async def test_a_client_cannot_choose_status_or_company_on_create(self, field, co, route_world):
        value = {"status": "completed", "company_id": str(co["other"]), "completion_reason": "goal"}
        res = await self._post(co, route_world, **{field: value[field]})
        assert res.status_code == 201
        body = res.json()
        assert (body["status"], body["company_id"], body["completion_reason"]) == (
            "active",
            str(co["acme"]),
            None,
        )


class TestLifecycle:
    @pytest.mark.parametrize("bad", ("done", "", "COMPLETED", "open"))
    async def test_unknown_status_is_422(self, bad, co, route_world):
        goal = await _goal(co)
        before = await _state(co)
        res = await route_world("PUT", ITEM.format(goal=goal), "admin", {"status": bad})
        assert res.status_code == 422
        assert await _state(co) == before

    @pytest.mark.parametrize("field", ("status", "title", "level"))
    async def test_required_fields_cannot_be_cleared(self, field, co, route_world):
        goal = await _goal(co)
        res = await route_world("PUT", ITEM.format(goal=goal), "admin", {field: None})
        assert res.status_code == 422

    @pytest.mark.parametrize("status", ("active", "in_progress", "blocked", "paused", "completed"))
    async def test_an_open_goal_can_move_to_any_known_status(self, status, co, route_world):
        goal = await _goal(co)
        res = await route_world("PUT", ITEM.format(goal=goal), "admin", {"status": status})
        assert res.status_code == 200 and res.json()["status"] == status

    @pytest.mark.parametrize("closed", ("completed", "cancelled", "archived"))
    @pytest.mark.parametrize("target", ("active", "in_progress", "blocked", "paused", "completed"))
    async def test_a_closed_goal_is_not_silently_reopened(self, closed, target, co, route_world):
        goal = await _goal(co, status=closed)
        before = await _state(co)
        res = await route_world("PUT", ITEM.format(goal=goal), "admin", {"status": target})
        assert res.status_code == 409 and res.json()["detail"]["code"] == "GOAL_CLOSED"
        assert await _state(co) == before

    async def test_a_closed_goal_cannot_be_edited_or_handed_to_an_owner(self, co, route_world):
        goal = await _goal(co, status="completed")
        before = await _state(co)
        for body in (
            {"title": "x"},
            {"owner_agent_id": str(co["acme_eve"])},
            {"status": "archived", "title": "x"},
        ):
            res = await route_world("PUT", ITEM.format(goal=goal), "admin", body)
            assert res.status_code == 409, body
        assert await _state(co) == before

    @pytest.mark.parametrize("closed", ("completed", "cancelled"))
    async def test_a_closed_goal_can_be_archived_once(self, closed, co, route_world):
        goal = await _goal(co, status=closed)
        res = await route_world("PUT", ITEM.format(goal=goal), "admin", {"status": "archived"})
        assert res.status_code == 200 and res.json()["status"] == "archived"
        again = await route_world("PUT", ITEM.format(goal=goal), "admin", {"status": "archived"})
        assert again.status_code == 409

    async def test_owner_is_validated_on_update(self, co, route_world):
        goal = await _goal(co)
        before = await _state(co)
        answers = []
        for owner in (co["other_eve"], uuid.uuid4()):
            res = await route_world(
                "PUT", ITEM.format(goal=goal), "admin", {"owner_agent_id": str(owner)}
            )
            answers.append((res.status_code, res.text.replace(str(owner), "<id>")))
        assert answers[0] == answers[1] and answers[0][0] == 404
        paused = await _agent(co, "paused")
        res = await route_world(
            "PUT", ITEM.format(goal=goal), "admin", {"owner_agent_id": str(paused)}
        )
        assert res.status_code == 409
        assert await _state(co) == before
        res = await route_world(
            "PUT", ITEM.format(goal=goal), "admin", {"owner_agent_id": str(co["acme_eve"])}
        )
        assert res.status_code == 200
        res = await route_world("PUT", ITEM.format(goal=goal), "admin", {"owner_agent_id": None})
        assert res.status_code == 200 and res.json()["owner_agent_id"] is None

    async def test_foreign_and_missing_goals_are_the_same_404_on_every_item_route(
        self, co, route_world
    ):
        foreign = await _goal(co, "other")
        before = await _state(co)
        calls = co["model"].calls
        for method, suffix, body in (
            ("GET", "", None),
            ("PUT", "", {"title": "hijack"}),
            ("DELETE", "", None),
            ("POST", "/execute", None),
        ):
            answers = []
            for goal in (foreign, uuid.uuid4()):
                res = await route_world(method, ITEM.format(goal=goal) + suffix, "admin", body)
                answers.append((res.status_code, res.text.replace(str(goal), "<id>")))
            assert answers[0] == answers[1] and answers[0][0] == 404, (method, answers)
        assert await _state(co) == before
        assert co["model"].calls == calls
        assert (await _get(co, Goal, foreign)).title == "other-active"

    async def test_delete_removes_only_the_callers_goal(self, co, route_world):
        mine = await _goal(co)
        theirs = await _goal(co, "other")
        assert (await route_world("DELETE", ITEM.format(goal=mine), "admin")).status_code == 204
        assert await _get(co, Goal, mine) is None
        assert await _get(co, Goal, theirs) is not None

    async def test_completing_a_goal_with_an_open_work_order_is_refused(self, co, route_world):
        goal = await _goal(co)
        async with co["db"]() as s:
            s.add(
                Task(
                    company_id=co["acme"],
                    title="work",
                    goal_id=goal,
                    status="in_progress",
                    work_spec={"kind": "work_order"},
                )
            )
            await s.commit()
        before = await _state(co)
        res = await route_world("PUT", ITEM.format(goal=goal), "admin", {"status": "completed"})
        assert res.status_code == 409 and res.json()["detail"]["code"] == "GOAL_HAS_OPEN_WORK"
        assert await _state(co) == before
        ok = await route_world("PUT", ITEM.format(goal=goal), "admin", {"status": "blocked"})
        assert ok.status_code == 200

    async def test_ordinary_tasks_do_not_block_completion(self, co, route_world):
        goal = await _goal(co)
        async with co["db"]() as s:
            s.add(Task(company_id=co["acme"], title="plain", goal_id=goal, status="in_progress"))
            await s.commit()
        res = await route_world("PUT", ITEM.format(goal=goal), "admin", {"status": "completed"})
        assert res.status_code == 200


class TestExecute:
    def _url(self, goal):
        return ITEM.format(goal=goal) + "/execute"

    @pytest.mark.parametrize("closed", ("completed", "cancelled", "archived"))
    async def test_a_closed_goal_does_not_run(self, closed, co, route_world):
        goal = await _goal(co, status=closed)
        res = await route_world("POST", self._url(goal), "admin")
        assert res.status_code == 409 and res.json()["detail"]["code"] == "GOAL_CLOSED"
        assert co["model"].calls == 0

    async def test_a_goal_with_open_work_does_not_run_or_create_tasks(self, co, route_world):
        goal = await _goal(co)
        async with co["db"]() as s:
            s.add(
                Task(
                    company_id=co["acme"],
                    title="work",
                    goal_id=goal,
                    status="pending",
                    work_spec={"kind": "work_order"},
                )
            )
            await s.commit()
        tasks = len(await _rows(co["db"], Task))
        res = await route_world("POST", self._url(goal), "admin")
        assert res.status_code == 409 and res.json()["detail"]["code"] == "GOAL_HAS_OPEN_WORK"
        assert co["model"].calls == 0
        assert len(await _rows(co["db"], Task)) == tasks

    async def test_an_ineligible_owner_does_not_run(self, co, route_world):
        owner = await _agent(co, "paused")
        goal = await _goal(co, owner_agent_id=owner)
        res = await route_world("POST", self._url(goal), "admin")
        assert res.status_code == 409
        assert res.json()["detail"]["code"] == "AGENT_NOT_ASSIGNABLE"
        assert co["model"].calls == 0

    @pytest.mark.parametrize("scope", ("agent", "company"))
    async def test_isolation_and_lockdown_stop_execution(self, scope, co, route_world):
        goal = await _goal(co, owner_agent_id=co["acme_eve"])
        await _restrict(co, scope, co["acme_eve"] if scope == "agent" else None)
        before = await _state(co)
        res = await route_world("POST", self._url(goal), "admin")
        assert res.status_code == 409 and res.json()["detail"]["code"] == "AGENT_RESTRICTED"
        assert co["model"].calls == 0
        assert await _state(co) == before

    async def test_an_owned_goal_runs_scoped_to_its_company(self, co, route_world):
        goal = await _goal(co, owner_agent_id=co["acme_eve"])
        theirs = await _goal(co, "other")
        tasks = len(await _rows(co["db"], Task))
        res = await route_world("POST", self._url(goal), "admin")
        assert res.status_code == 200, res.text
        assert co["model"].calls >= 1
        assert (await _get(co, Goal, theirs)).status == "active"
        assert "goal.executed" in _goal_audits(await _rows(co["db"], AuditLog))
        assert len(await _rows(co["db"], Task)) == tasks


class TestStaticGuard:
    def _routes(self):
        return [r for r in goal_routes.router.routes if isinstance(r, APIRoute)]

    @staticmethod
    def _qualnames(route):
        return [getattr(c, "__qualname__", "") for c in _flatten(route.dependant)]

    def test_there_are_goal_routes_to_check(self):
        assert len(self._routes()) == 7

    def test_every_goal_route_declares_a_permission(self):
        for route in self._routes():
            names = self._qualnames(route)
            assert any(n.startswith("require_permission.") for n in names), route.path

    def test_every_non_get_route_needs_write_goal_and_gates_principal_kinds(self):
        for route in self._routes():
            if route.methods <= {"GET"}:
                continue
            names = self._qualnames(route)
            assert any(n.startswith("require_permission.") for n in names), route.path
            assert any(n.startswith("principal_kinds.") for n in names), route.path
            assert route.dependencies is not None
            assert goal_routes.WRITE_GOAL[0] in route.dependencies, route.path

    def test_every_get_route_needs_read_goal(self):
        for route in self._routes():
            if route.methods <= {"GET"}:
                assert goal_routes.READ_GOAL[0] in route.dependencies, route.path

    def test_company_in_the_url_always_uses_the_path_company_dependency(self):
        found = 0
        for route in self._routes():
            if "{company_id}" in route.path:
                found += 1
                assert get_scoped_company_id in _flatten(route.dependant), route.path
        assert found == 3

    def test_the_goal_status_vocabulary_covers_what_the_orchestrator_writes(self):
        assert {"active", "in_progress", "blocked", "completed"} <= set(goal_routes.GOAL_STATUSES)
