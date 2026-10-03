"""``manager_delegate_task`` cannot take over company work it does not own.

Marked work (a work order or a child of one) belongs to the manager recorded on the order.
Delegating it needs that manager. An unrelated manager gets the same 404 as a missing task,
even when the child failed or sits idle, and nothing is written: no owner change, no attempt.
Ordinary tasks keep their existing behaviour. The tool itself is explicit-allow-only, so a
wildcard or default policy never grants it and a named allow does.
"""

# ruff: noqa: F811  (pytest fixtures are imported, then named as test parameters)

from __future__ import annotations

import json
import uuid

import pytest
from fastapi import HTTPException

from nexus.api.routes import managers as manager_routes
from nexus.models.task import Task
from nexus.models.task_attempt import TaskAttempt
from nexus.models.tool import ToolPolicy
from nexus.services import manager_service as ms
from nexus.tools.mcp_server import MCPServer
from tests.test_employee_work import _me, _rows, db, w  # noqa: F401 -- fixtures
from tests.test_work_service import (  # noqa: F401 -- fixtures and helpers
    LEAD,
    _assign,
    _ctx,
    _delegate,
    _get,
    _order,
    co,
)
from tests.test_work_task_route_guards import _plain

pytestmark = pytest.mark.employee_work


async def _child(co):
    """An order owned by Lead, with a child assigned to Eve (Lead's report)."""
    work = await _order(co)
    await _delegate(co, work)
    task, attempt, _ = await _assign(co, work)
    from nexus.runtime import task_attempts as ta

    await ta.drain()
    return work, task.id, attempt.id


async def _fail(co, task, attempt):
    async with co["db"]() as s:
        a = await s.get(TaskAttempt, attempt)
        a.status = "failed"
        t = await s.get(Task, task)
        t.status = "failed"
        s.add_all([a, t])
        await s.commit()


async def _snapshot(co, *tasks):
    rows = [await _get(co, Task, t) for t in tasks]
    attempts = await _rows(co["db"], TaskAttempt, TaskAttempt.company_id == co["acme"])
    return (
        [(r.status, r.assigned_agent_id) for r in rows],
        sorted((a.task_id, a.agent_id, a.attempt_number, a.status) for a in attempts),
    )


async def _delegate_as(co, manager, employee, task):
    async with co["db"]() as s:
        return await ms.delegate(s, co["acme"], co[manager], co[employee], task, LEAD)


async def _status(coro):
    with pytest.raises(HTTPException) as caught:
        await coro
    return caught.value.status_code, caught.value.detail["code"]


class TestOwnerGuard:
    async def test_the_owning_manager_may_redelegate_its_own_child(self, co):
        _, task, attempt = await _child(co)
        replay, created = await _delegate_as(co, "acme_lead", "acme_eve", task)
        assert (replay.id, created) == (attempt, False)

    async def test_an_unrelated_manager_cannot_take_over_a_failed_child(self, co):
        work, task, attempt = await _child(co)
        await _fail(co, task, attempt)
        before = await _snapshot(co, work, task)
        assert await _status(_delegate_as(co, "acme_bo", "acme_zed", task)) == (
            404,
            "TASK_NOT_FOUND",
        )
        assert await _snapshot(co, work, task) == before

    async def test_a_failed_previous_attempt_does_not_enable_takeover(self, co):
        work, task, attempt = await _child(co)
        await _fail(co, task, attempt)
        for _ in range(2):
            assert (await _status(_delegate_as(co, "acme_bo", "acme_zed", task)))[0] == 404
        row = await _get(co, Task, task)
        assert (row.status, row.assigned_agent_id) == ("failed", co["acme_eve"])
        attempts = await _rows(co["db"], TaskAttempt, TaskAttempt.task_id == task)
        assert [(a.agent_id, a.status) for a in attempts] == [(co["acme_eve"], "failed")]

    async def test_an_unrelated_manager_cannot_take_an_idle_child(self, co):
        work = await _order(co)
        await _delegate(co, work)
        idle = await _plain(co, parent=work, status="pending", assigned_agent_id=co["acme_eve"])
        before = await _snapshot(co, work, idle)
        assert (await _status(_delegate_as(co, "acme_bo", "acme_zed", idle)))[0] == 404
        assert await _snapshot(co, work, idle) == before

    async def test_a_foreign_and_a_missing_task_answer_the_same(self, co):
        work, task, _ = await _child(co)
        missing = await _status(_delegate_as(co, "acme_bo", "acme_zed", uuid.uuid4()))
        unrelated = await _status(_delegate_as(co, "acme_bo", "acme_zed", task))
        assert missing == unrelated == (404, "TASK_NOT_FOUND")

    async def test_the_work_order_itself_is_never_delegated_to_an_employee(self, co):
        work = await _order(co)
        await _delegate(co, work)
        before = await _snapshot(co, work)
        assert await _status(_delegate_as(co, "acme_lead", "acme_eve", work)) == (
            409,
            "WORK_ORDER_NOT_EXECUTABLE",
        )
        assert (await _status(_delegate_as(co, "acme_bo", "acme_zed", work)))[0] == 404
        assert await _snapshot(co, work) == before

    async def test_the_ceo_cannot_reach_a_work_child_through_the_generic_tool(self, co):
        from nexus.tools import manager_tools

        work, task, _ = await _child(co)
        before = await _snapshot(co, work, task)
        ceo = _ctx(co["acme"], co["acme_ceo"])
        args = {"task_id": str(task), "manager_id": str(co["acme_lead"])}
        with pytest.raises(HTTPException) as caught:
            await manager_tools.call(ceo, "ceo_delegate_task_to_manager", args)
        assert caught.value.status_code in (404, 409)
        assert await _snapshot(co, work, task) == before

    async def test_ordinary_tasks_are_not_intercepted_by_the_owner_guard(self, co):
        """An unmarked task passes the guard; what happens next is the pre-existing path
        (the attempt layer wants a work spec), not a 404 from the owner check."""
        from nexus.services import work_service

        ordinary = await _plain(co, status="pending")
        async with co["db"]() as s:
            await work_service.require_work_owner(s, co["acme"], ordinary, co["acme_bo"])
            await work_service.require_work_owner(s, co["acme"], uuid.uuid4(), co["acme_bo"])
        assert await _status(_delegate_as(co, "acme_bo", "acme_zed", ordinary)) == (
            422,
            "TASK_NOT_WORK",
        )
        row = await _get(co, Task, ordinary)
        assert (row.status, row.assigned_agent_id) == ("pending", None)

    async def test_the_http_route_applies_the_same_guard(self, co):
        from types import SimpleNamespace

        work, task, _ = await _child(co)
        attempts = await _rows(co["db"], TaskAttempt, TaskAttempt.task_id == task)
        await _fail(co, task, attempts[0].id)
        before = await _snapshot(co, work, task)
        principal = SimpleNamespace(
            agent_id=None, display_name="op", kind="user", has_permission=lambda *a: True
        )
        body = manager_routes.DelegationRequest(task_id=task, employee_id=co["acme_zed"])
        async with co["db"]() as s:
            with pytest.raises(HTTPException) as caught:
                await manager_routes.delegate_task(
                    co["acme_bo"], body, SimpleNamespace(status_code=200), s, co["acme"], principal
                )
        assert caught.value.status_code == 404
        assert await _snapshot(co, work, task) == before


def _text(result):
    return result["content"][0]["text"]


async def _policy(co, name, tool_names):
    async with co["db"]() as s:
        s.add_all(
            [
                ToolPolicy(
                    company_id=co["acme"],
                    name="reads",
                    effect="allow",
                    conditions={"risk_level": ["read"]},
                ),
                ToolPolicy(
                    company_id=co["acme"],
                    name=name,
                    effect="allow",
                    conditions={"tool_name": tool_names},
                ),
            ]
        )
        await s.commit()


class TestToolPolicyAndOwnerTogether:
    async def test_a_wildcard_allow_never_grants_the_tool(self, co):
        _, task, _ = await _child(co)
        await _policy(co, "all managers", ["manager_*"])
        server = MCPServer(_ctx(co["acme"], co["acme_lead"]))
        assert "manager_delegate_task" not in {t["name"] for t in await server.list_tools()}
        result = await server.call_tool(
            "manager_delegate_task", {"task_id": str(task), "employee_id": str(co["acme_eve"])}
        )
        assert result["isError"] and "Denied by access policy" in _text(result)

    async def test_a_named_allow_grants_the_owner_but_not_a_takeover(self, co):
        work, task, attempt = await _child(co)
        await _fail(co, task, attempt)
        await _policy(co, "delegation", ["manager_delegate_task"])
        before = await _snapshot(co, work, task)
        # Bo is allowed the tool by name but does not own the order.
        bo = MCPServer(_ctx(co["acme"], co["acme_bo"]))
        refused = await bo.call_tool(
            "manager_delegate_task", {"task_id": str(task), "employee_id": str(co["acme_zed"])}
        )
        assert refused["isError"] and "TASK_NOT_FOUND" in _text(refused)
        assert await _snapshot(co, work, task) == before
        # Lead owns it: the named allow is enough.
        lead = MCPServer(_ctx(co["acme"], co["acme_lead"]))
        ok = await lead.call_tool(
            "manager_delegate_task", {"task_id": str(task), "employee_id": str(co["acme_eve"])}
        )
        assert ok["isError"] is False, ok
        assert json.loads(_text(ok))["attempt"]["task_id"] == str(task)

    async def test_an_explicit_deny_beats_the_named_allow(self, co):
        _, task, _ = await _child(co)
        await _policy(co, "delegation", ["manager_delegate_task"])
        async with co["db"]() as s:
            s.add(
                ToolPolicy(
                    company_id=co["acme"],
                    name="freeze",
                    effect="deny",
                    priority=1,
                    conditions={"tool_name": ["manager_delegate_task"]},
                )
            )
            await s.commit()
        lead = MCPServer(_ctx(co["acme"], co["acme_lead"]))
        result = await lead.call_tool(
            "manager_delegate_task", {"task_id": str(task), "employee_id": str(co["acme_eve"])}
        )
        assert result["isError"] and "Denied by access policy" in _text(result)
