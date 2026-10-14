"""Manager plan finalization and the full WorkSpec on ``manager_assign_work``.

A work order closes only when its manager finalized the plan and every child completed. Runs on
the work-service fixtures (file SQLite, the real attempt worker, a fake model call).
"""

# ruff: noqa: F811  (pytest fixtures are imported, then named as test parameters)

from __future__ import annotations

import uuid

import pytest
from fastapi import HTTPException

from nexus.api.routes import chat as chat_routes
from nexus.models.agent import Agent
from nexus.models.task import Task
from nexus.runtime import task_attempts as ta
from nexus.services import work_service
from nexus.tools import manager_tools
from tests.test_employee_work import SPEC, _rows, db, w  # noqa: F401 -- fixtures, helpers
from tests.test_work_service import (  # noqa: F401 -- fixtures, helpers
    DELIVERABLE,
    _assign,
    _ctx,
    _delegate,
    _finalize,
    _get,
    _order,
    _review,
    co,
)

pytestmark = pytest.mark.employee_work


async def _err(coro):
    """(status, code) of the HTTPException the service raises."""
    with pytest.raises(HTTPException) as caught:
        await coro
    return caught.value.status_code, caught.value.detail["code"]


async def _delegated_with_children(co, count=2):
    """A delegated order with ``count`` text children, each submitted and awaiting review."""
    work = await _order(co)
    await _delegate(co, work)
    attempts = []
    for index in range(count):
        _, attempt, _ = await _assign(co, work, key=f"a{index}", title=f"Part {index}")
        attempts.append(attempt.id)
    await ta.drain()
    return work, attempts


class TestPlanFinalization:
    async def test_a_verified_child_does_not_close_an_open_plan(self, co):
        work, (first, second) = await _delegated_with_children(co)
        await _review(co, first)
        assert (await _get(co, Task, work)).status == "in_progress"
        # Finalizing with a child still unreviewed leaves the order open.
        _, changed = await _finalize(co, work)
        assert changed is True
        assert (await _get(co, Task, work)).status == "in_progress"
        await _review(co, second)
        parent = await _get(co, Task, work)
        assert parent.status == "completed" and DELIVERABLE in parent.result

    async def test_finalize_after_every_child_completed_closes_the_order(self, co):
        work, (first, second) = await _delegated_with_children(co)
        await _review(co, first)
        await _review(co, second)
        assert (await _get(co, Task, work)).status == "in_progress"
        order, changed = await _finalize(co, work)
        assert (changed, order.status) == (True, "completed")

    async def test_no_task_can_be_added_after_finalize(self, co):
        work, (first,) = await _delegated_with_children(co, count=1)
        await _finalize(co, work)
        assert await _err(_assign(co, work, key="late")) == (409, "WORK_CLOSED")
        assert len(await _rows(co["db"], Task, Task.parent_task_id == work)) == 1
        await _review(co, first)
        assert (await _get(co, Task, work)).status == "completed"

    async def test_finalize_is_idempotent(self, co):
        work, _ = await _delegated_with_children(co, count=1)
        first = await _finalize(co, work)
        again = await _finalize(co, work)
        assert (first[1], again[1]) == (True, False)
        assert first[0].work_spec == again[0].work_spec

    async def test_a_replayed_review_does_not_move_the_order_again(self, co):
        work, (only,) = await _delegated_with_children(co, count=1)
        await _finalize(co, work)
        _, changed = await _review(co, only)
        _, replay = await _review(co, only)
        assert (changed, replay) == (True, False)
        assert (await _get(co, Task, work)).status == "completed"

    async def test_an_empty_plan_cannot_be_finalized(self, co):
        work = await _order(co)
        await _delegate(co, work)
        assert await _err(_finalize(co, work)) == (409, "PLAN_EMPTY")
        # The refused call left no flag behind: a task can still be assigned.
        await _assign(co, work)
        assert (await _finalize(co, work))[1] is True
        await ta.drain()

    async def test_only_the_owning_manager_in_the_same_company_can_finalize(self, co):
        work, _ = await _delegated_with_children(co, count=1)
        assert await _err(_finalize(co, work, manager="acme_bo")) == (404, "TASK_NOT_FOUND")
        assert await _err(_finalize(co, work, company="other")) == (404, "TASK_NOT_FOUND")
        undelegated = await _order(co, key="k2")
        assert await _err(_finalize(co, undelegated)) == (404, "TASK_NOT_FOUND")

    async def test_a_plain_task_cannot_be_finalized(self, co):
        async with co["db"]() as s:
            plain = Task(company_id=co["acme"], title="plain", assigned_agent_id=co["acme_lead"])
            s.add(plain)
            await s.commit()
        assert await _err(_finalize(co, plain.id)) == (404, "TASK_NOT_FOUND")

    async def test_a_cancelled_order_cannot_be_finalized(self, co):
        work, _ = await _delegated_with_children(co, count=1)
        async with co["db"]() as s:
            await work_service.cancel_work(s, co["acme"], work, actor="op")
        assert await _err(_finalize(co, work)) == (409, "WORK_CLOSED")

    async def test_a_failed_child_is_never_counted_as_completed(self, co):
        work, (first, second) = await _delegated_with_children(co)
        await _review(co, first)
        await _review(co, second, "reject", reason="wrong", retry=False)
        order, _ = await _finalize(co, work)
        assert order.status == "in_progress"
        assert (await _get(co, Task, work)).status == "in_progress"

    async def test_a_child_out_of_attempts_still_fails_the_order(self, co):
        work = await _order(co)
        await _delegate(co, work)
        _, attempt, _ = await _assign(co, work, attempts_cap=1)
        await ta.drain()
        await _review(co, attempt.id, "reject", reason="no")
        assert (await _get(co, Task, work)).status == "failed"
        assert await _err(_finalize(co, work)) == (409, "WORK_CLOSED")

    async def test_a_plain_parent_is_never_rolled_up(self, co):
        async with co["db"]() as s:
            parent = Task(company_id=co["acme"], title="p", assigned_agent_id=co["acme_lead"])
            s.add(parent)
            await s.flush()
            s.add(Task(company_id=co["acme"], title="c", parent_task_id=parent.id))
            await s.commit()
        async with co["db"]() as s:
            await work_service._complete_if_done(s, co["acme"], parent.id)
            await s.commit()
        assert (await _get(co, Task, parent.id)).status == "pending"


async def test_an_attempt_with_no_task_row_settles_nothing(co):
    """Recovery of an orphaned attempt must not raise: there is no parent to settle."""
    from nexus.models.task_attempt import TaskAttempt

    orphan = TaskAttempt(
        company_id=co["acme"], task_id=uuid.uuid4(), agent_id=co["acme_eve"], attempt_number=1,
        idempotency_key="orphan", status="expired",
    )
    async with co["db"]() as s:
        await work_service.after_terminal(s, orphan)


class TestAssignWorkSpec:
    async def _lead_with_cli_report(self, co, w):  # noqa: F811
        async with co["db"]() as s:
            (await s.get(Agent, w["acme_claude"])).manager_id = co["acme_lead"]
            await s.commit()
        work = await _order(co)
        await _delegate(co, work)
        return work, _ctx(co["acme"], co["acme_lead"])

    def _args(self, w, work, **over):  # noqa: F811
        return {
            "work_id": str(work),
            "employee_id": str(w["acme_claude"]),
            "title": "Calculator",
            "objective": SPEC["objective"],
            "idempotency_key": "w-1",
            "mode": "write",
            "repository_id": str(w["acme_repo"]),
            "deliverables": SPEC["deliverables"],
            "verification": SPEC["verification"],
            "acceptance_criteria": SPEC["acceptance_criteria"],
            **over,
        }

    async def test_every_field_is_stored_and_a_changed_replay_is_refused(
        self,
        co,
        w,
        monkeypatch,  # noqa: F811
    ):
        monkeypatch.setattr(chat_routes, "_call_llm", co["db"].employee)
        work, lead = await self._lead_with_cli_report(co, w)
        args = self._args(w, work)
        made = await manager_tools.call(lead, "manager_assign_work", args)
        spec = (await _get(co, Task, uuid.UUID(made["task_id"]))).work_spec
        assert spec["mode"] == "write" and spec["repository_id"] == str(w["acme_repo"])
        assert spec["deliverables"] == args["deliverables"]
        assert spec["verification"][0]["command"] == "pytest"
        assert len(spec["acceptance_criteria"]) == 3
        again = await manager_tools.call(lead, "manager_assign_work", args)
        assert again["created"] is False and again["task_id"] == made["task_id"]
        changed = self._args(w, work, deliverables=["src/other.py"])
        assert await _err(manager_tools.call(lead, "manager_assign_work", changed)) == (
            409,
            "IDEMPOTENCY_KEY_REUSED",
        )
        await ta.drain()

    async def test_a_write_child_completes_through_verification_and_rolls_up(
        self,
        co,
        w,
        monkeypatch,  # noqa: F811
    ):
        monkeypatch.setattr(chat_routes, "_call_llm", co["db"].employee)
        work, lead = await self._lead_with_cli_report(co, w)
        made = await manager_tools.call(lead, "manager_assign_work", self._args(w, work))
        await ta.drain()
        assert (await _get(co, Task, uuid.UUID(made["task_id"]))).status == "completed"
        # The finished child alone leaves the open plan open.
        assert (await _get(co, Task, work)).status == "in_progress"
        done = await manager_tools.call(lead, "manager_finalize_plan", {"work_id": str(work)})
        assert done["status"] == "completed"

    async def test_invalid_combinations_are_refused_before_any_child_exists(self, co, w):  # noqa: F811
        work, lead = await self._lead_with_cli_report(co, w)
        cases = (
            {"repository_id": None},  # write needs a repository
            {"deliverables": []},  # write needs a deliverable
            {"verification": []},  # write needs a verification step
            {"mode": "text"},  # text forbids repository, deliverables, verification
            {"mode": "read_only"},  # read_only forbids deliverables
        )
        for index, over in enumerate(cases):
            args = self._args(w, work, idempotency_key=f"bad-{index}", **over)
            args = {k: v for k, v in args.items() if v is not None}
            result = await _err(manager_tools.call(lead, "manager_assign_work", args))
            assert result == (422, "INVALID_WORK_SPEC"), over
        assert await _rows(co["db"], Task, Task.parent_task_id == work) == []

    async def test_a_repository_of_another_company_is_refused(self, co, w):  # noqa: F811
        work, lead = await self._lead_with_cli_report(co, w)
        args = self._args(w, work, repository_id=str(w["other_repo"]))
        result = await _err(manager_tools.call(lead, "manager_assign_work", args))
        assert result == (404, "REPOSITORY_NOT_FOUND")
        assert await _rows(co["db"], Task, Task.parent_task_id == work) == []

    async def test_a_write_task_needs_a_cli_employee_and_leaves_no_orphan(self, co, w):  # noqa: F811
        work, lead = await self._lead_with_cli_report(co, w)
        args = self._args(w, work, employee_id=str(co["acme_eve"]))
        result = await _err(manager_tools.call(lead, "manager_assign_work", args))
        assert result == (422, "EMPLOYEE_NOT_CLI")
        assert await _rows(co["db"], Task, Task.parent_task_id == work) == []

    async def test_the_default_is_still_a_text_task(self, co):
        work = await _order(co)
        await _delegate(co, work)
        task, _, _ = await _assign(co, work)
        assert task.work_spec["mode"] == "text"
        await ta.drain()
