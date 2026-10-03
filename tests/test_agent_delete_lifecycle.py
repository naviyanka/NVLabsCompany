"""Deleting an agent is lifecycle-safe: permissioned, company-scoped, never strands live work.

* ``DELETE /api/v1/agents/{id}`` needs ``write:agent``.
* An agent that owns a task that is not completed, failed or cancelled (ordinary task, work-order
  root, work child, one in review) or a live attempt is refused: ``409 AGENT_OWNS_ACTIVE_WORK``.
  Ownership is never nulled.
* Retention: a terminal task of this company only loses its owner. A recorded attempt, or any
  row that still references the agent, pins it: ``409 AGENT_HAS_HISTORY`` (never a raw 500).
* The legacy goal orchestrator never routes a work-owned task as a generic unowned one.
"""

# ruff: noqa: F811  (pytest fixtures are imported, then named as test parameters)

from __future__ import annotations

import uuid

import httpx
import pytest
from fastapi import FastAPI, HTTPException, Request

from nexus.api.routes import agents as agent_routes
from nexus.auth.principal import Principal
from nexus.models.agent import Agent
from nexus.models.task import Task
from nexus.models.task_attempt import TaskAttempt
from nexus.runtime import orchestrator
from nexus.runtime import task_attempts as ta
from nexus.services.task_service import TaskService
from tests.test_employee_work import _me, _rows, db, w  # noqa: F401 -- fixtures
from tests.test_work_service import (  # noqa: F401 -- fixtures and helpers
    _assign,
    _delegate,
    _get,
    _order,
    _review,
    _submitted,
    co,
)
from tests.test_work_task_route_guards import _plain

pytestmark = pytest.mark.employee_work

OWNS = "AGENT_OWNS_ACTIVE_WORK"
HISTORY = "AGENT_HAS_HISTORY"


@pytest.fixture
async def call(co):
    principals = {
        "admin": _me(co["acme"]),
        "manager": _me(co["acme"], role="manager"),
        "viewer": _me(co["acme"], role="viewer"),
        "employee": _me(co["acme"], role="agent"),
        "guest": _me(co["acme"], role="guest"),
        "outsider": _me(co["other"]),
        "run": Principal(
            kind="run",
            company_id=co["acme"],
            role="agent",
            run_id=uuid.uuid4(),
            agent_id=co["acme_lead"],
        ),
    }
    app = FastAPI()
    app.include_router(agent_routes.router)

    @app.middleware("http")
    async def as_principal(request: Request, call_next):
        request.state.principal = principals[request.headers.get("x-test-principal", "admin")]
        return await call_next(request)

    client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")

    async def delete(agent, who="admin"):
        return await client.delete(f"/api/v1/agents/{agent}", headers={"x-test-principal": who})

    yield delete
    await client.aclose()


async def _exists(co, agent):
    return await _get(co, Agent, agent) is not None


def _code(res):
    detail = res.json()["detail"]
    return detail["code"] if isinstance(detail, dict) else detail


class TestPermission:
    @pytest.mark.parametrize("who", ["viewer", "employee", "guest", "run"])
    async def test_without_write_agent_nothing_is_deleted(self, who, co, call):
        res = await call(co["acme_zed"], who)
        assert res.status_code == 403, res.text
        assert await _exists(co, co["acme_zed"])

    @pytest.mark.parametrize("who", ["admin", "manager"])
    async def test_admin_and_manager_may_delete_an_idle_agent(self, who, co, call):
        assert (await call(co["acme_zed"], who)).status_code == 204
        assert not await _exists(co, co["acme_zed"])


class TestActiveWorkBlocksDeletion:
    async def test_a_manager_who_owns_a_work_order_is_refused(self, co, call):
        work = await _order(co)
        await _delegate(co, work)
        res = await call(co["acme_lead"])
        assert (res.status_code, _code(res)) == (409, OWNS)
        assert (await _get(co, Task, work)).assigned_agent_id == co["acme_lead"]
        assert await _exists(co, co["acme_lead"])

    async def test_an_employee_with_a_work_child_is_refused(self, co, call):
        work = await _order(co)
        await _delegate(co, work)
        task, attempt, _ = await _assign(co, work)
        res = await call(co["acme_eve"])
        assert (res.status_code, _code(res)) == (409, OWNS)
        await ta.drain()
        assert (await _get(co, Task, task.id)).assigned_agent_id == co["acme_eve"]
        assert await _exists(co, co["acme_eve"])

    async def test_an_employee_awaiting_review_is_refused(self, co, call):
        _, task, _ = await _submitted(co)
        assert (await _get(co, Task, task)).status == "in_review"
        res = await call(co["acme_eve"])
        assert (res.status_code, _code(res)) == (409, OWNS)
        assert (await _get(co, Task, task)).assigned_agent_id == co["acme_eve"]

    async def test_a_live_attempt_is_refused_even_when_its_task_is_closed(self, co, call):
        work = await _order(co)
        await _delegate(co, work)
        task, attempt, _ = await _assign(co, work)
        async with co["db"]() as s:
            row = await s.get(Task, task.id)
            row.status = "cancelled"
            s.add(row)
            await s.commit()
        live = await _get(co, TaskAttempt, attempt.id)
        assert live.status in ta.ACTIVE_ATTEMPT_STATUSES
        res = await call(co["acme_eve"])
        assert (res.status_code, _code(res)) == (409, OWNS)
        assert await _exists(co, co["acme_eve"])

    @pytest.mark.parametrize("status", ["pending", "in_progress", "delegated", "in_review"])
    async def test_an_ordinary_open_task_is_refused(self, status, co, call):
        task = await _plain(co, status=status, assigned_agent_id=co["acme_zed"])
        res = await call(co["acme_zed"])
        assert (res.status_code, _code(res)) == (409, OWNS)
        assert (await _get(co, Task, task)).assigned_agent_id == co["acme_zed"]
        assert await _exists(co, co["acme_zed"])


class TestRetention:
    @pytest.mark.parametrize("status", ["completed", "failed", "cancelled"])
    async def test_a_terminal_task_only_loses_its_owner(self, status, co, call):
        task = await _plain(co, status=status, assigned_agent_id=co["acme_zed"])
        assert (await call(co["acme_zed"])).status_code == 204
        row = await _get(co, Task, task)
        assert (row.status, row.assigned_agent_id) == (status, None)
        assert not await _exists(co, co["acme_zed"])

    async def test_an_agent_with_a_recorded_attempt_is_pinned_not_a_500(self, co, call):
        work, task, attempt = await _submitted(co)
        await _review(co, attempt)
        assert (await _get(co, TaskAttempt, attempt)).status == "completed"
        res = await call(co["acme_eve"])
        assert (res.status_code, _code(res)) == (409, HISTORY)
        row = await _get(co, Task, task)
        assert (row.status, row.assigned_agent_id) == ("completed", co["acme_eve"])
        assert await _exists(co, co["acme_eve"])

    async def test_a_late_foreign_key_failure_becomes_the_same_stable_answer(self, co, call):
        """Another table still points at the agent: rollback, 409, nothing half-deleted."""
        async with co["db"]() as s:
            s.add(
                Task(
                    company_id=co["other"],
                    title="Elsewhere",
                    status="completed",
                    assigned_agent_id=co["acme_zed"],
                )
            )
            await s.commit()
        res = await call(co["acme_zed"])
        assert (res.status_code, _code(res)) == (409, HISTORY)
        assert await _exists(co, co["acme_zed"])


class TestCompanyScope:
    async def test_a_foreign_principal_gets_404_and_changes_nothing(self, co, call):
        task = await _plain(co, status="completed", assigned_agent_id=co["acme_zed"])
        res = await call(co["acme_zed"], "outsider")
        assert res.status_code == 404
        assert (await _get(co, Task, task)).assigned_agent_id == co["acme_zed"]
        assert await _exists(co, co["acme_zed"])

    async def test_a_missing_agent_answers_like_a_foreign_one(self, co, call):
        missing = await call(uuid.uuid4())
        foreign = await call(co["other_zed"])
        assert (missing.status_code, foreign.status_code) == (404, 404)
        assert await _exists(co, co["other_zed"])

    async def test_another_companys_task_is_never_nulled(self, co, call):
        """The old unscoped UPDATE nulled every company's rows that named the agent."""
        async with co["db"]() as s:
            foreign = Task(
                company_id=co["other"],
                title="Elsewhere",
                status="completed",
                assigned_agent_id=co["acme_zed"],
            )
            s.add(foreign)
            await s.commit()
            foreign_id = foreign.id
        assert (await call(co["acme_zed"])).status_code == 409
        assert (await _get(co, Task, foreign_id)).assigned_agent_id == co["acme_zed"]

    async def test_an_ordinary_unowned_task_is_untouched(self, co, call):
        control = await _plain(co, status="pending")
        assert (await call(co["acme_zed"])).status_code == 204
        row = await _get(co, Task, control)
        assert (row.status, row.assigned_agent_id) == ("pending", None)


class TestRemovedAgentsAreNotAssignable:
    async def test_a_deleted_agent_cannot_be_given_work(self, co, call):
        assert (await call(co["acme_zed"])).status_code == 204
        async with co["db"]() as s:
            with pytest.raises(HTTPException) as caught:
                await TaskService(s).create_task(
                    co["acme"], "x", None, 1, assigned_agent_id=co["acme_zed"]
                )
        assert caught.value.status_code == 404


class TestLegacyOrchestratorNeverRoutesWork:
    async def _ready(self, co):
        async with co["db"]() as s:
            for key in ("acme_eve", "acme_zed"):
                agent = await s.get(Agent, co[key])
                agent.status, agent.budget_monthly_cents = "ready", 10_000
                s.add(agent)
            await s.commit()

    async def test_a_marked_root_and_child_are_filtered_out(self, co):
        work = await _order(co)
        await _delegate(co, work)
        child = await _plain(co, parent=work, status="pending")
        spec_only = await _plain(co, status="pending", work_spec={"unrelated": 1})
        ordinary = await _plain(co, status="pending")
        async with co["db"]() as s:
            rows = [await s.get(Task, i) for i in (work, child, spec_only, ordinary)]
            kept = await orchestrator._without_work_owned(s, co["acme"], rows)
        assert [t.id for t in kept] == [ordinary]

    async def test_route_subtasks_assigns_only_the_ordinary_task(self, co):
        await self._ready(co)
        work = await _order(co)
        child = await _plain(co, parent=work, status="pending")
        ordinary = await _plain(co, status="pending")
        async with co["db"]() as s:
            rows = [await s.get(Task, i) for i in (work, child, ordinary)]
            await orchestrator._route_subtasks(s, rows, co["acme"])
            await s.commit()
        assert (await _get(co, Task, work)).assigned_agent_id is None
        assert (await _get(co, Task, child)).assigned_agent_id is None
        assert (await _get(co, Task, ordinary)).assigned_agent_id is not None

    async def test_route_subtasks_with_only_work_changes_nothing(self, co):
        await self._ready(co)
        work = await _order(co)
        async with co["db"]() as s:
            await orchestrator._route_subtasks(s, [await s.get(Task, work)], co["acme"])
            await s.commit()
        row = await _get(co, Task, work)
        assert (row.status, row.assigned_agent_id) == ("pending", None)
