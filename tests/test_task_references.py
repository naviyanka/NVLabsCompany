"""Every foreign reference a Task accepts is loaded by ``(company_id, id)`` before it is written.

A foreign-key constraint accepts any tenant's row and answers a missing one with a database
error, so it is never the check. A foreign and a missing reference give the same 404; a closed
or inactive one gives 409; a refused create leaves no Task and no audit row. The service owns the
rule, so the HTTP routes and a direct caller answer alike.
"""

# ruff: noqa: F811  (pytest fixtures are imported, then named as test parameters)

from __future__ import annotations

import inspect
import uuid

import pytest
from fastapi import HTTPException

from nexus.api.routes import tasks as task_routes
from nexus.api.routes import work as work_routes
from nexus.models.governance import AuditLog
from nexus.models.repository import Repository
from nexus.models.task import Goal, Project, Task
from nexus.models.task_attempt import TaskAttempt
from nexus.runtime import orchestrator
from nexus.runtime import task_attempts as ta
from nexus.runtime.task_attempts import WorkSpec
from nexus.services import task_service, work_service
from nexus.services.task_service import TaskService
from tests.test_employee_work import _rows, db, w  # noqa: F401 -- fixtures
from tests.test_work_service import (  # noqa: F401 -- fixtures and helpers
    _assign,
    _delegate,
    _get,
    api,
    co,
)

pytestmark = pytest.mark.employee_work

CLOSED = ("completed", "cancelled", "archived")


async def _insert(co, row):
    async with co["db"]() as s:
        s.add(row)
        await s.commit()
        return row.id


async def _project(co, company="acme", status="active"):
    return await _insert(co, Project(company_id=co[company], name="P", status=status))


async def _goal(co, company="acme", status="active"):
    return await _insert(co, Goal(company_id=co[company], title="G", status=status))


async def _repo(co, company="acme", active=True):
    return await _insert(
        co,
        Repository(company_id=co[company], name="r", url="https://x.test/r.git", is_active=active),
    )


async def _state(co):
    return (
        len(await _rows(co["db"], Task)),
        len(await _rows(co["db"], AuditLog)),
        len(await _rows(co["db"], TaskAttempt)),
    )


async def _service_create(co, **kw):
    async with co["db"]() as s:
        task = await TaskService(s).create_task(co["acme"], "svc", **kw)
        await s.commit()
        return task


async def _order_with_goal(co, goal_id, key):
    async with co["db"]() as s:
        task, _ = await work_service.create_work_order(
            s,
            co["acme"],
            scope="human:op",
            actor="op",
            title="T",
            idempotency_key=key,
            goal_id=goal_id,
        )
        return task


async def _snapshot(co, *task_ids):
    rows = []
    for task_id in task_ids:
        t = await _get(co, Task, task_id)
        rows.append((t.status, t.assigned_agent_id, t.parent_task_id, t.result))
    return rows, len(await _rows(co["db"], Task)), len(await _rows(co["db"], TaskAttempt))


async def _refused(coro) -> tuple[int, str]:
    with pytest.raises(HTTPException) as caught:
        await coro
    detail = caught.value.detail
    return caught.value.status_code, detail["code"] if isinstance(detail, dict) else str(detail)


class TestProject:
    async def test_own_project_is_accepted(self, co, api):
        project = await _project(co)
        res = await api(
            "POST",
            f"/api/v1/companies/{co['acme']}/tasks",
            {"title": "in project", "project_id": str(project)},
        )
        assert res.status_code == 201 and res.json()["project_id"] == str(project)
        assert (await _service_create(co, project_id=project)).project_id == project

    async def test_foreign_and_missing_projects_get_the_same_404(self, co, api):
        foreign = await _project(co, "other")
        before = await _state(co)
        path = f"/api/v1/companies/{co['acme']}/tasks"
        answers = []
        for project in (foreign, uuid.uuid4()):
            res = await api("POST", path, {"title": "x", "project_id": str(project)})
            service = await _refused(_service_create(co, project_id=project))
            answers.append((res.status_code, res.text.replace(str(project), "<id>"), service))
        assert answers[0] == answers[1]
        assert answers[0][0] == 404 and answers[0][2] == (404, "PROJECT_NOT_FOUND")
        assert str(foreign) not in answers[0][1]
        assert await _state(co) == before

    @pytest.mark.parametrize("state", CLOSED)
    async def test_a_closed_project_is_a_409(self, state, co, api):
        project = await _project(co, status=state)
        before = await _state(co)
        res = await api(
            "POST",
            f"/api/v1/companies/{co['acme']}/tasks",
            {"title": "x", "project_id": str(project)},
        )
        assert res.status_code == 409
        assert await _refused(_service_create(co, project_id=project)) == (409, "PROJECT_CLOSED")
        assert await _state(co) == before

    async def test_a_foreign_project_row_is_left_alone(self, co, api):
        foreign = await _project(co, "other")
        await api(
            "POST",
            f"/api/v1/companies/{co['acme']}/tasks",
            {"title": "x", "project_id": str(foreign)},
        )
        row = await _get(co, Project, foreign)
        assert (row.company_id, row.status, row.name) == (co["other"], "active", "P")


class TestGoal:
    async def test_own_goal_links_the_order_and_its_children(self, co, api):
        goal = await _goal(co)
        res = await api("POST", "/api/v1/work", {"title": "T", "goal_id": str(goal)}, key="g-own")
        assert res.status_code == 201
        work = uuid.UUID(res.json()["id"])
        await _delegate(co, work)
        task, _, _ = await _assign(co, work)
        assert (await _get(co, Task, work)).goal_id == goal
        assert (await _get(co, Task, task.id)).goal_id == goal

    async def test_foreign_and_missing_goals_get_the_same_404(self, co, api):
        foreign = await _goal(co, "other")
        before = await _state(co)
        answers = []
        for index, goal in enumerate((foreign, uuid.uuid4())):
            res = await api(
                "POST", "/api/v1/work", {"title": "T", "goal_id": str(goal)}, key=f"g-{index}"
            )
            service = await _refused(_order_with_goal(co, goal, f"s-{index}"))
            answers.append((res.status_code, res.text.replace(str(goal), "<id>"), service))
        assert answers[0] == answers[1]
        assert answers[0][0] == 404 and answers[0][2] == (404, "GOAL_NOT_FOUND")
        assert str(foreign) not in answers[0][1]
        assert await _state(co) == before

    @pytest.mark.parametrize("state", CLOSED)
    async def test_a_closed_goal_is_a_409(self, state, co, api):
        goal = await _goal(co, status=state)
        before = await _state(co)
        res = await api("POST", "/api/v1/work", {"title": "T", "goal_id": str(goal)}, key="g-c")
        assert res.status_code == 409
        assert await _refused(_order_with_goal(co, goal, "g-c2")) == (409, "GOAL_CLOSED")
        assert await _state(co) == before

    async def test_the_legacy_goal_loop_leaves_linked_work_alone(self, co):
        """A goal-linked order and child are never run, decomposed or re-owned by the goal loop."""
        goal_id = await _goal(co)
        order = await _order_with_goal(co, goal_id, "lk")
        await _delegate(co, order.id)
        child, _, _ = await _assign(co, order.id)
        await ta.drain()
        before = await _snapshot(co, order.id, child.id)
        calls = co["model"].calls
        async with co["db"]() as s:
            goal = await s.get(Goal, goal_id)
            for _ in range(2):
                try:
                    await orchestrator._drive_goal(s, goal)
                except Exception:  # noqa: BLE001 -- only the work rows are under test
                    await s.rollback()
        assert co["model"].calls == calls
        assert await _snapshot(co, order.id, child.id) == before


class TestWorkSpecReferences:
    async def test_a_foreign_or_missing_repository_is_a_404(self, co):
        foreign = await _repo(co, "other")
        before = await _state(co)
        answers = []
        for repo in (foreign, uuid.uuid4()):
            spec = {"mode": "read_only", "repository_id": str(repo)}
            answers.append(await _refused(_service_create(co, work_spec=spec)))
        assert answers == [(404, "REPOSITORY_NOT_FOUND")] * 2
        assert await _state(co) == before

    async def test_an_inactive_repository_is_a_409(self, co):
        repo = await _repo(co, active=False)
        spec = {"mode": "read_only", "repository_id": str(repo)}
        before = await _state(co)
        assert await _refused(_service_create(co, work_spec=spec)) == (409, "REPOSITORY_INACTIVE")
        assert await _state(co) == before

    async def test_an_own_repository_is_accepted(self, co, api):
        repo = await _repo(co)
        spec = {"mode": "read_only", "repository_id": str(repo)}
        res = await api(
            "POST", f"/api/v1/companies/{co['acme']}/tasks", {"title": "w", "work_spec": spec}
        )
        assert res.status_code == 201

    async def test_a_foreign_reviewed_task_is_a_404(self, co):
        theirs = await _insert(co, Task(company_id=co["other"], title="theirs"))
        spec = {
            "mode": "read_only",
            "repository_id": str(await _repo(co)),
            "review_of_task_id": str(theirs),
        }
        before = await _state(co)
        assert await _refused(_service_create(co, work_spec=spec)) == (
            404,
            "REVIEWED_TASK_NOT_FOUND",
        )
        assert await _state(co) == before


class TestServerOwnedFields:
    async def test_task_create_ignores_caller_supplied_identity(self, co, api):
        forged = {
            "id": str(uuid.uuid4()),
            "company_id": str(co["other"]),
            "status": "completed",
            "result": "forged",
            "goal_id": str(await _goal(co)),
            "created_at": "2001-01-01T00:00:00",
        }
        res = await api("POST", f"/api/v1/companies/{co['acme']}/tasks", {"title": "t", **forged})
        assert res.status_code == 201
        row = await _get(co, Task, uuid.UUID(res.json()["id"]))
        assert str(row.id) != forged["id"] and row.company_id == co["acme"]
        assert (row.status, row.result, row.goal_id) == ("pending", None, None)
        assert row.created_at.year != 2001

    async def test_work_create_refuses_unknown_fields(self, co, api):
        before = await _state(co)
        for extra in (
            {"id": str(uuid.uuid4())},
            {"company_id": str(co["other"])},
            {"status": "completed"},
        ):
            res = await api("POST", "/api/v1/work", {"title": "T", **extra}, key="forge")
            assert res.status_code == 422
        assert await _state(co) == before


# Every caller-supplied reference on a Task and the validator that loads it by (company, id).
# A new foreign key on Task, or a new UUID field on a create body, fails the guard below until
# it has an entry here and the create path calls its validator.
TASK_FK_RULES = {
    "project_id": "require_project",
    "assigned_agent_id": "require_assignable_agent",
    "parent_task_id": "require_parent",
    "goal_id": "require_goal",
}
SPEC_FIELD_RULES = {"repository_id", "review_of_task_id"}  # require_work_spec_references


class TestGuard:
    def test_every_task_foreign_key_has_a_company_validation_rule(self):
        fks = {c.name for c in Task.__table__.columns if c.foreign_keys and c.name != "company_id"}
        assert fks == set(TASK_FK_RULES), (
            f"Task foreign keys {sorted(fks ^ set(TASK_FK_RULES))} have no company-validation "
            "rule: load the row by (company_id, id) in the service, then list it here."
        )

    def test_the_create_paths_call_each_validator(self):
        create = inspect.getsource(TaskService.create_task)
        order = inspect.getsource(work_service.create_work_order)
        for field, validator in TASK_FK_RULES.items():
            assert hasattr(task_service, validator), validator
            source = order if field == "goal_id" else create
            assert validator in source, f"{field}: {validator} is not called on its create path"
        assert "require_work_spec_references" in create

    def test_every_uuid_field_a_caller_can_send_is_covered(self):
        def uuid_fields(model):
            return {n for n, f in model.model_fields.items() if "UUID" in str(f.annotation)}

        accepted = (
            uuid_fields(task_routes.TaskCreate)
            | uuid_fields(work_routes.WorkCreate)
            | uuid_fields(WorkSpec)
        )
        covered = set(TASK_FK_RULES) | SPEC_FIELD_RULES
        assert accepted <= covered, f"unvalidated reference fields: {sorted(accepted - covered)}"
