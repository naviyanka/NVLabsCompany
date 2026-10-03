"""The generic task routes cannot change who owns, or how far along, company work.

A work order (a stamped top-level Task) and its children belong to ``work_service``. Every
generic route that could move one of them answers 409 ``WORK_OWNED_BY_LIFECYCLE`` without an
id in the message; ordinary tasks keep the behaviour they always had.
"""

# ruff: noqa: F811  (pytest fixtures are imported, then named as test parameters)

from __future__ import annotations

import uuid

import pytest

from nexus.models.task import Task
from nexus.runtime import task_attempts as ta
from nexus.services import work_service
from tests.test_employee_work import _rows, db, w  # noqa: F401 -- fixtures
from tests.test_work_service import (  # noqa: F401 -- fixtures and helpers
    _assign,
    _code,
    _delegate,
    _get,
    _order,
    _submitted,
    api,
    co,
)

pytestmark = pytest.mark.employee_work

LOCKED = "WORK_OWNED_BY_LIFECYCLE"


async def _plain(co, *, parent=None, **fields):
    async with co["db"]() as s:
        task = Task(company_id=co["acme"], title="Old ticket", parent_task_id=parent, **fields)
        s.add(task)
        await s.commit()
        return task.id


async def _snapshot(co, *ids):
    out = []
    for task_id in ids:
        row = await _get(co, Task, task_id)
        out.append((row.status, row.assigned_agent_id, row.parent_task_id, row.work_spec))
    return out


def _mutations(co, target):
    """Every generic Task route that writes, with a body that would otherwise be accepted."""
    agent = str(co["acme_bo"])
    return [
        ("PUT", f"/api/v1/tasks/{target}/assign", {"agent_id": agent}),
        ("POST", f"/api/v1/tasks/{target}/reassign", {"agent_id": agent}),
        ("PUT", f"/api/v1/tasks/{target}/status", {"status": "running"}),
        ("PUT", f"/api/v1/tasks/{target}/status", {"status": "pending"}),
        ("POST", f"/api/v1/tasks/{target}/subtasks", {"title": "extra"}),
        ("POST", f"/api/v1/tasks/{target}/decompose", None),
    ]


class TestPredicate:
    async def test_roots_and_children_are_owned_ordinary_tasks_are_not(self, co):
        work, child, _ = await _submitted(co)
        plain_root = await _plain(co)
        plain_child = await _plain(co, parent=plain_root)
        async with co["db"]() as s:
            owned = {
                name: await work_service.is_work_owned(s, co["acme"], task_id)
                for name, task_id in (
                    ("root", work),
                    ("child", child),
                    ("plain_root", plain_root),
                    ("plain_child", plain_child),
                    ("missing", uuid.uuid4()),
                )
            }
            foreign = await work_service.is_work_owned(s, co["other"], work)
        assert owned == {
            "root": True,
            "child": True,
            "plain_root": False,
            "plain_child": False,
            "missing": False,
        }
        assert foreign is False

    async def test_a_child_of_an_ordinary_task_with_work_data_is_not_owned(self, co):
        legacy = await _plain(co, work_spec={"unrelated": "data"})
        child = await _plain(co, parent=legacy)
        async with co["db"]() as s:
            assert not await work_service.is_work_owned(s, co["acme"], legacy)
            assert not await work_service.is_work_owned(s, co["acme"], child)

    async def test_unknown_kind_is_not_a_work_order_but_is_still_owned(self, co):
        """Fails closed: never operable as work, never reassignable through the generic routes."""
        for spec in ({"kind": "other"}, {"kind": 7}, {"kind": ""}):
            task_id = await _plain(co, work_spec=spec)
            task = await _get(co, Task, task_id)
            assert not work_service.is_work_order(task), spec
            async with co["db"]() as s:
                assert await work_service.is_work_owned(s, co["acme"], task_id), spec
                assert await _code(work_service.require_work(s, co["acme"], task_id)) == 404

    async def test_unrelated_work_data_is_neither_a_work_order_nor_owned(self, co):
        for spec in ({"kind": None}, {}, {"unrelated": 1}):
            task_id = await _plain(co, work_spec=spec)
            task = await _get(co, Task, task_id)
            assert not work_service.is_work_order(task), spec
            async with co["db"]() as s:
                assert not await work_service.is_work_owned(s, co["acme"], task_id), spec
                assert await _code(work_service.require_work(s, co["acme"], task_id)) == 404

    async def test_python_and_sql_predicates_agree(self, co):
        from sqlalchemy import select

        specs = [None, {"kind": "work_order"}, {"kind": "other"}, {"unrelated": 1}]
        ids = {}
        for index, spec in enumerate(specs):
            ids[index] = await _plain(co, work_spec=spec)
        async with co["db"]() as s:
            sql = set(
                (
                    await s.execute(
                        select(Task.id).where(
                            Task.company_id == co["acme"], work_service._work_order_clause()
                        )
                    )
                )
                .scalars()
                .all()
            )
        for index in ids:
            task = await _get(co, Task, ids[index])
            assert (task.id in sql) == work_service.is_work_order(task), specs[index]


class TestAssignAndReassign:
    async def test_marked_root_is_refused_in_service_and_routes(self, co, api):
        work = await _order(co)
        await _delegate(co, work)
        before = await _snapshot(co, work)
        for method, path, body in _mutations(co, work)[:2]:
            res = await api(method, path, body)
            assert (res.status_code, res.json()["detail"]["code"]) == (409, LOCKED), path
        assert await _snapshot(co, work) == before

    async def test_work_child_is_refused(self, co, api):
        work, child, _ = await _submitted(co)
        before = await _snapshot(co, work, child)
        for method, path, body in _mutations(co, child)[:2]:
            res = await api(method, path, body)
            assert (res.status_code, res.json()["detail"]["code"]) == (409, LOCKED), path
        assert await _snapshot(co, work, child) == before

    async def test_ordinary_root_and_child_keep_assignment(self, co, api):
        root = await _plain(co)
        child = await _plain(co, parent=root)
        for task_id, agent in ((root, "acme_bo"), (child, "acme_lead")):
            for method, route in (("PUT", "assign"), ("POST", "reassign")):
                res = await api(
                    method, f"/api/v1/tasks/{task_id}/{route}", {"agent_id": str(co[agent])}
                )
                assert res.status_code == 200, res.text
                assert res.json()["assigned_agent_id"] == str(co[agent])

    async def test_error_names_no_id_and_foreign_or_missing_ids_are_not_work(self, co, api):
        work = await _order(co)
        agent = str(co["acme_bo"])
        locked = await api("PUT", f"/api/v1/tasks/{work}/assign", {"agent_id": agent})
        assert str(work) not in locked.text
        missing = uuid.uuid4()
        for who, target in (("admin", missing), ("outsider", work)):
            res = await api("PUT", f"/api/v1/tasks/{target}/assign", {"agent_id": agent}, who=who)
            # Whatever these answer, it is not the lifecycle error: that would confirm the id.
            assert LOCKED not in res.text, (who, res.text)
            assert res.status_code in (403, 404), (who, res.text)
        assert (await _get(co, Task, work)).assigned_agent_id is None

    async def test_run_token_and_viewer_cannot_change_work(self, co, api):
        work, child, _ = await _submitted(co)
        before = await _snapshot(co, work, child)
        for who in ("run", "viewer"):
            for target in (work, child):
                for method, path, body in _mutations(co, target):
                    res = await api(method, path, body, who=who)
                    assert res.status_code == 409, (who, path, res.text)
                    assert res.json()["detail"]["code"] == LOCKED, (who, path)
        assert await _snapshot(co, work, child) == before

    async def test_service_start_refuses_a_work_order_clearly(self, co):
        work = await _order(co)
        await _delegate(co, work)
        async with co["db"]() as s:
            principal = type("P", (), {"display_name": "op"})()
            with pytest.raises(Exception) as caught:
                await ta.start_attempt(s, co["acme"], work, principal)
        assert caught.value.detail["code"] == "WORK_ORDER_NOT_EXECUTABLE"


class TestOtherGenericMutations:
    """The scan: status, subtasks, create-with-parent and decompose cannot touch work."""

    async def test_every_generic_mutation_is_refused_for_work(self, co, api):
        work, child, _ = await _submitted(co)
        before = await _snapshot(co, work, child)
        for target in (work, child):
            for method, path, body in _mutations(co, target):
                res = await api(method, path, body)
                assert res.status_code == 409, (path, res.text)
                assert res.json()["detail"]["code"] == LOCKED, (path, res.text)
        assert await _snapshot(co, work, child) == before
        assert await _rows(co["db"], Task, Task.parent_task_id == work) == [
            await _get(co, Task, child)
        ]
        assert await _rows(co["db"], Task, Task.parent_task_id == child) == []

    async def test_create_task_cannot_hang_a_child_on_work(self, co, api):
        work = await _order(co)
        url = f"/api/v1/companies/{co['acme']}/tasks"
        res = await api("POST", url, {"title": "T", "parent_task_id": str(work)})
        assert (res.status_code, res.json()["detail"]["code"]) == (409, LOCKED)
        assert await _rows(co["db"], Task, Task.parent_task_id == work) == []

    async def test_ordinary_tasks_keep_status_subtasks_and_create(self, co, api):
        root = await _plain(co)
        assert (
            await api("PUT", f"/api/v1/tasks/{root}/status", {"status": "running"})
        ).status_code == 200
        res = await api("POST", f"/api/v1/tasks/{root}/subtasks", {"title": "step"})
        assert res.status_code == 201
        url = f"/api/v1/companies/{co['acme']}/tasks"
        res = await api("POST", url, {"title": "T", "parent_task_id": str(root)})
        assert res.status_code == 201

    async def test_cancel_route_still_goes_through_the_lifecycle(self, co, api):
        work, child, _ = await _submitted(co)
        res = await api("POST", f"/api/v1/tasks/{work}/cancel")
        assert res.status_code == 200, res.text
        assert (await _get(co, Task, work)).status == "cancelled"
