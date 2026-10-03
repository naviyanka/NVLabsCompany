"""Company work: CEO -> manager -> employee -> verification, on the production services.

Runs on the employee-work fixtures (file SQLite, the real attempt worker). Only the model
call is faked. Waiting is done on the worker's own drain, never on sleeps.
"""

from __future__ import annotations

import asyncio
import uuid
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI, HTTPException, Request

from nexus.api.routes import chat as chat_routes
from nexus.api.routes import task_attempts as attempt_routes
from nexus.api.routes import tasks as task_routes
from nexus.api.routes import work as work_routes
from nexus.auth.principal import Principal
from nexus.models.agent import Agent
from nexus.models.governance import AuditLog
from nexus.models.task import Task
from nexus.models.task_attempt import TaskAttempt
from nexus.runtime import task_attempts as ta
from nexus.services import work_service
from nexus.tools import manager_tools
from nexus.tools.context import INBOUND_MCP, ExecutionContext
from tests.test_employee_work import _me, _rows, db, w  # noqa: F401 -- fixtures

pytestmark = pytest.mark.employee_work

DELIVERABLE = "Q3 summary: revenue up 12%, costs flat."
LEAD = SimpleNamespace(kind="agent", display_name="agent:lead")


class Model:
    """The fake provider: one reply per call, optionally failing or empty."""

    def __init__(self) -> None:
        self.reply = DELIVERABLE
        self.error: Exception | None = None
        self.calls = 0

    async def __call__(self, agent, system_prompt, prompt, history, **kw):
        self.calls += 1
        if self.error is not None:
            raise self.error
        return self.reply, "fake-model", 7


@pytest.fixture
async def co(db, w, monkeypatch):  # noqa: F811
    """Acme: CEO over managers Lead and Bo; Eve reports to Lead, Zed to Bo. Other has a CEO."""
    model = Model()
    monkeypatch.setattr(chat_routes, "_call_llm", model)
    ids = {"model": model, "acme": w["acme"], "other": w["other"]}
    async with db() as s:
        for key in ("acme", "other"):
            ceo = Agent(
                company_id=w[key],
                name=f"{key}-ceo",
                role="ceo",
                is_ceo=True,
                adapter_type="openai",
                model="gpt-x",
            )
            s.add(ceo)
            await s.flush()
            lead = Agent(
                company_id=w[key],
                name=f"{key}-lead",
                role="manager",
                adapter_type="openai",
                model="gpt-x",
                manager_id=ceo.id,
            )
            bo = Agent(
                company_id=w[key],
                name=f"{key}-bo",
                role="manager",
                adapter_type="openai",
                model="gpt-x",
                manager_id=ceo.id,
            )
            s.add_all([lead, bo])
            await s.flush()
            eve = Agent(
                company_id=w[key],
                name=f"{key}-eve",
                role="analyst",
                adapter_type="openai",
                model="gpt-x",
                manager_id=lead.id,
            )
            zed = Agent(
                company_id=w[key],
                name=f"{key}-zed",
                role="analyst",
                adapter_type="openai",
                model="gpt-x",
                manager_id=bo.id,
            )
            s.add_all([eve, zed])
            await s.flush()
            ids.update(
                {
                    f"{key}_ceo": ceo.id,
                    f"{key}_lead": lead.id,
                    f"{key}_bo": bo.id,
                    f"{key}_eve": eve.id,
                    f"{key}_zed": zed.id,
                }
            )
        await s.commit()
    ids["db"] = db
    return ids


async def _order(co, key="k1", title="Quarterly report", company="acme"):
    async with co["db"]() as s:
        task, _ = await work_service.create_work_order(
            s, co[company], scope="human:op", actor="op", title=title, idempotency_key=key
        )
    return task.id


async def _delegate(co, work, manager="acme_lead", company="acme"):
    async with co["db"]() as s:
        return await work_service.delegate_to_manager(
            s, co[company], co[f"{company}_ceo"], co[manager], work, "agent:ceo"
        )


async def _assign(co, work, key="a1", employee="acme_eve", manager="acme_lead", **kw):
    async with co["db"]() as s:
        return await work_service.assign_task(
            s,
            co["acme"],
            co[manager],
            work,
            co[employee],
            title=kw.pop("title", "Summary"),
            objective="Summarise Q3.",
            idempotency_key=key,
            principal=LEAD,
            **kw,
        )


async def _review(co, attempt, decision="verify", reviewer="acme_lead", company="acme", **kw):
    async with co["db"]() as s:
        return await work_service.review(
            s,
            co[company],
            attempt,
            decision=decision,
            reason=kw.pop("reason", None),
            actor="op",
            reviewer_agent_id=co[reviewer] if reviewer else None,
            **kw,
        )


async def _submitted(co, key="k1"):
    """A work order delegated, assigned and run to the point of awaiting review."""
    work = await _order(co, key)
    await _delegate(co, work)
    task, attempt, _ = await _assign(co, work, key=f"a-{key}")
    await ta.drain()
    return work, task.id, attempt.id


async def _get(co, model, row_id):
    async with co["db"]() as s:
        return await s.get(model, row_id)


async def _status(co, work=None, company="acme", **kw):
    async with co["db"]() as s:
        return await work_service.status(s, co[company], work, **kw)


def _item(snap, work_id):
    return next(i for i in snap["work"] if i["id"] == str(work_id))


async def _code(coro):
    with pytest.raises(HTTPException) as caught:
        await coro
    return caught.value.status_code


class TestLifecycle:
    async def test_full_loop_needs_manager_verification(self, co):
        work, task, attempt = await _submitted(co)
        waiting = await _get(co, TaskAttempt, attempt)
        # Submission is not completion.
        assert (waiting.status, waiting.claimed_by) == ("verifying", None)
        assert waiting.output_summary == DELIVERABLE
        assert (await _get(co, Task, task)).status == "in_review"
        assert (await _get(co, Task, work)).status == "in_progress"
        assert co["model"].calls == 1

        done, changed = await _review(co, attempt)
        assert changed and done.status == "completed"
        assert (await _get(co, Task, task)).status == "completed"
        parent = await _get(co, Task, work)
        assert parent.status == "completed" and DELIVERABLE in parent.result
        # The employee ran it, the manager did not.
        assert done.agent_id == co["acme_eve"]

    async def test_status_reports_stored_state(self, co):
        work, _, attempt = await _submitted(co)
        snap = await _status(co)
        item = _item(snap, work)
        assert item["status"] == "in_progress" and item["assignee"]["name"] == "acme-lead"
        assert item["tasks"][0]["attempt"]["awaiting_review"] is True
        assert item["tasks"][0]["result"] is None  # not completed yet
        assert snap["metrics"]["awaiting_review"] == 1
        assert "deliverable" not in item["tasks"][0]["attempt"]
        with_text = await _status(co, with_deliverable=True)
        assert _item(with_text, work)["tasks"][0]["attempt"]["deliverable"] == DELIVERABLE
        await _review(co, attempt)
        done = _item(await _status(co), work)
        assert done["status"] == "completed" and DELIVERABLE in done["result"]

    async def test_audit_has_ids_and_no_deliverable_text(self, co):
        _, _, attempt = await _submitted(co)
        await _review(co, attempt)
        rows = await _rows(co["db"], AuditLog)
        actions = {r.action for r in rows}
        assert {
            "work.created",
            "work.delegated",
            "work.assigned",
            "work.deliverable_submitted",
            "work.verified",
        } <= actions
        leaks = [
            r.action for r in rows if DELIVERABLE in str(r.details) or "Summarise" in str(r.details)
        ]
        assert leaks == []

    async def test_deliverable_is_bounded(self, co):
        co["model"].reply = "x" * 900
        work = await _order(co)
        await _delegate(co, work)
        _, attempt, _ = await _assign(co, work, max_deliverable_chars=100)
        await ta.drain()
        row = await _get(co, TaskAttempt, attempt.id)
        assert len(row.output_summary) == 100 and row.verification["truncated"] is True

    async def test_empty_reply_and_model_failure_are_failures_not_deliverables(self, co):
        co["model"].reply = "   "
        work = await _order(co)
        await _delegate(co, work)
        task, attempt, _ = await _assign(co, work, attempts_cap=1)
        await ta.drain()
        row = await _get(co, TaskAttempt, attempt.id)
        assert (row.status, row.error_code) == ("failed", "EMPTY_DELIVERABLE")
        assert (await _get(co, Task, task.id)).status == "failed"
        assert (await _get(co, Task, work)).status == "failed"

        co["model"].error = RuntimeError("provider down")
        work2 = await _order(co, "k2")
        await _delegate(co, work2)
        _, attempt2, _ = await _assign(co, work2, key="a2", attempts_cap=1)
        await ta.drain()
        row2 = await _get(co, TaskAttempt, attempt2.id)
        assert row2.status == "failed" and row2.output_summary is None


class TestReplay:
    async def test_create_delegate_assign_replay_is_one_item(self, co):
        first = await _order(co)
        assert await _order(co) == first
        assert await _code(_order(co, title="Another title")) == 409
        _, created = await _delegate(co, first)
        _, again = await _delegate(co, first)
        assert (created, again) == (True, False)
        assert await _code(_delegate(co, first, manager="acme_bo")) == 409
        t1, a1, c1 = await _assign(co, first)
        t2, a2, c2 = await _assign(co, first)
        await ta.drain()
        assert (t1.id, a1.id, c1) == (t2.id, a2.id, True) and c2 is False
        assert len(await _rows(co["db"], Task, Task.parent_task_id == first)) == 1
        assert len(await _rows(co["db"], TaskAttempt, TaskAttempt.task_id == t1.id)) == 1
        assert co["model"].calls == 1
        assert await _code(_assign(co, first, title="Other")) == 409

    async def test_repeated_review_has_one_winner(self, co):
        _, _, attempt = await _submitted(co)
        _, first = await _review(co, attempt)
        _, again = await _review(co, attempt)
        assert (first, again) == (True, False)
        assert await _code(_review(co, attempt, "reject", reason="no")) == 409

    async def test_concurrent_verify_and_reject_one_winner(self, co):
        _, task, attempt = await _submitted(co)
        results = await asyncio.gather(
            _review(co, attempt, "verify"),
            _review(co, attempt, "reject", reason="too thin"),
            return_exceptions=True,
        )
        winners = [r for r in results if not isinstance(r, BaseException)]
        losers = [r for r in results if isinstance(r, HTTPException)]
        assert len(winners) == 1 and len(losers) == 1 and losers[0].status_code == 409
        final = await _get(co, TaskAttempt, attempt)
        assert final.status in ("completed", "failed")
        assert (await _get(co, Task, task)).status == final.status

    async def test_restart_keeps_state_and_repeats_nothing(self, co):
        work, task, attempt = await _submitted(co)
        before = await _status(co)
        # A new service pass: sweep leaves an attempt that waits for review alone.
        await ta.sweep()
        await ta.drain()
        after = await _status(co)
        assert after["work"] == before["work"]
        assert (await _get(co, TaskAttempt, attempt)).status == "verifying"
        assert co["model"].calls == 1
        # Replaying every mutation after the restart changes nothing.
        await _order(co)
        await _delegate(co, work)
        await _assign(co, work, key="a-k1")
        await ta.drain()
        assert co["model"].calls == 1
        assert len(await _rows(co["db"], TaskAttempt)) == 1


class TestRejectAndRetry:
    async def test_reject_with_retry_runs_one_more_attempt(self, co):
        work, task, attempt = await _submitted(co)
        rejected, changed = await _review(co, attempt, "reject", reason="needs numbers", retry=True)
        assert changed and rejected.status == "failed"
        await ta.drain()
        attempts = await _rows(co["db"], TaskAttempt, TaskAttempt.task_id == task)
        assert sorted(a.attempt_number for a in attempts) == [1, 2]
        second = next(a for a in attempts if a.attempt_number == 2)
        assert second.status == "verifying"
        assert (await _get(co, Task, task)).status == "in_review"
        await _review(co, second.id)
        assert (await _get(co, Task, work)).status == "completed"

    async def test_retry_is_capped(self, co):
        work = await _order(co)
        await _delegate(co, work)
        task, attempt, _ = await _assign(co, work, attempts_cap=1)
        await ta.drain()
        await _review(co, attempt.id, "reject", reason="no", retry=True)
        await ta.drain()
        assert len(await _rows(co["db"], TaskAttempt, TaskAttempt.task_id == task.id)) == 1
        assert (await _get(co, Task, task.id)).status == "failed"
        assert (await _get(co, Task, work)).status == "failed"

    async def test_reject_needs_a_reason(self, co):
        _, _, attempt = await _submitted(co)
        assert await _code(_review(co, attempt, "reject")) == 422


class TestCancel:
    async def test_cancel_awaiting_review_and_replay(self, co):
        work, task, attempt = await _submitted(co)
        async with co["db"]() as s:
            row, changed = await work_service.cancel_work(s, co["acme"], work, actor="op")
        assert changed and row.status == "cancelled"
        assert (await _get(co, TaskAttempt, attempt)).status == "cancelled"
        assert (await _get(co, Task, task)).status == "cancelled"
        async with co["db"]() as s:
            _, again = await work_service.cancel_work(s, co["acme"], work, actor="op")
        assert again is False
        assert await _code(_review(co, attempt)) == 409

    async def test_completed_work_cannot_be_cancelled(self, co):
        work, _, attempt = await _submitted(co)
        await _review(co, attempt)
        async with co["db"]() as s:
            assert await _code(work_service.cancel_work(s, co["acme"], work, actor="op")) == 409
        assert (await _get(co, Task, work)).status == "completed"

    async def test_cancelled_work_takes_no_new_assignment(self, co):
        work = await _order(co)
        await _delegate(co, work)
        async with co["db"]() as s:
            await work_service.cancel_work(s, co["acme"], work, actor="op")
        assert await _code(_assign(co, work)) == 409
        assert co["model"].calls == 0


class TestAuthority:
    async def test_employee_cannot_review_own_work_and_others_see_nothing(self, co):
        _, _, attempt = await _submitted(co)
        # The executor is refused; another manager cannot see it; the owner can act.
        async with co["db"]() as s:
            code = await _code(
                work_service.review(
                    s,
                    co["acme"],
                    attempt,
                    decision="verify",
                    reason=None,
                    actor="eve",
                    reviewer_agent_id=co["acme_eve"],
                )
            )
        assert code == 403
        assert await _code(_review(co, attempt, reviewer="acme_bo")) == 404
        assert (await _get(co, TaskAttempt, attempt)).status == "verifying"
        assert (await _review(co, attempt))[1] is True

    async def test_managers_act_only_in_their_scope(self, co):
        work = await _order(co)
        await _delegate(co, work)
        assert await _code(_assign(co, work, employee="acme_zed")) == 403  # not Lead's report
        assert await _code(_assign(co, work, employee="acme_zed", manager="acme_bo")) == 404
        assert await _code(_assign(co, work, employee="other_eve")) == 404  # foreign agent
        assert await _rows(co["db"], Task, Task.parent_task_id == work) == []

    async def test_foreign_company_ids_are_plain_404s(self, co):
        work, _, attempt = await _submitted(co)
        assert await _code(_status(co, work, company="other")) == 404
        assert await _code(_review(co, attempt, reviewer=None, company="other")) == 404
        async with co["db"]() as s:
            assert await _code(work_service.cancel_work(s, co["other"], work, actor="x")) == 404
        assert await _code(_delegate(co, work, manager="other_lead", company="other")) == 404
        assert (await _status(co, company="other"))["work"] == []

    async def test_work_order_closed_to_the_wrong_delegation(self, co):
        work = await _order(co)
        await _delegate(co, work)
        # Bo is a CEO report but does not own it.
        assert await _code(_assign(co, work, employee="acme_zed", manager="acme_bo")) == 404


def _ctx(company, agent):
    return ExecutionContext(
        company_id=company,
        principal_id=f"run:{uuid.uuid4()}",
        principal_role="agent",
        source=INBOUND_MCP,
        agent_id=agent,
    )


class TestTools:
    async def test_ceo_and_manager_tools_drive_the_loop(self, co):
        ceo = _ctx(co["acme"], co["acme_ceo"])
        lead = _ctx(co["acme"], co["acme_lead"])
        made = await manager_tools.call(
            ceo,
            "ceo_create_goal_or_work_order",
            {"kind": "work_order", "title": "Board deck", "idempotency_key": "ceo-1"},
        )
        again = await manager_tools.call(
            ceo,
            "ceo_create_goal_or_work_order",
            {"kind": "work_order", "title": "Board deck", "idempotency_key": "ceo-1"},
        )
        assert made["created"] is True and again["created"] is False
        work_id = made["work"]["id"] if "work" in made else made["id"]
        args = {"task_id": work_id, "manager_id": str(co["acme_lead"])}
        one = await manager_tools.call(ceo, "ceo_delegate_task_to_manager", args)
        two = await manager_tools.call(ceo, "ceo_delegate_task_to_manager", args)
        assert (one["created"], two["created"]) == (True, False)
        assign = {
            "work_id": work_id,
            "employee_id": str(co["acme_eve"]),
            "title": "Draft",
            "objective": "Draft the deck outline.",
            "idempotency_key": "m-1",
            "expected_deliverable": "A bullet outline",
        }
        first = await manager_tools.call(lead, "manager_assign_work", assign)
        await ta.drain()
        repeat = await manager_tools.call(lead, "manager_assign_work", assign)
        assert (first["created"], repeat["created"]) == (True, False)
        attempt_id = first["attempt"]["id"]
        verdict = await manager_tools.call(
            lead, "manager_review_work", {"attempt_id": attempt_id, "decision": "verify"}
        )
        assert verdict["changed"] is True
        status = await manager_tools.call(ceo, "ceo_get_work_status", {})
        assert _item(status, work_id)["status"] == "completed"
        assert "deliverable" not in str(status)

    async def test_tool_arguments_cannot_widen_authority(self, co):
        lead = _ctx(co["acme"], co["acme_lead"])
        bad = {
            "work_id": str(uuid.uuid4()),
            "employee_id": str(co["acme_eve"]),
            "title": "t",
            "objective": "o",
            "idempotency_key": "k",
            "role": "admin",
            "max_attempts": 50,
        }
        with pytest.raises(ValueError):
            await manager_tools.call(lead, "manager_assign_work", bad)
        employee = _ctx(co["acme"], co["acme_eve"])
        with pytest.raises(Exception):
            await manager_tools.call(
                employee,
                "manager_review_work",
                {"attempt_id": str(uuid.uuid4()), "decision": "verify"},
            )


@pytest.fixture
async def api(co):
    principals = {
        "admin": _me(co["acme"]),
        "viewer": _me(co["acme"], role="viewer"),
        "manager": _me(co["acme"], role="manager"),
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
    app.include_router(work_routes.router)
    app.include_router(task_routes.router)
    app.include_router(attempt_routes.router)

    @app.middleware("http")
    async def as_principal(request: Request, call_next):
        request.state.principal = principals[request.headers.get("x-test-principal", "admin")]
        return await call_next(request)

    client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")

    async def call(method, path, body=None, who="admin", key=None):
        headers = {"x-test-principal": who, **({"Idempotency-Key": key} if key else {})}
        return await client.request(method, path, json=body, headers=headers)

    yield call
    await client.aclose()


class TestRoutes:
    async def test_create_needs_a_key_and_replays(self, co, api):
        assert (await api("POST", "/api/v1/work", {"title": "T"})).status_code == 422
        first = await api("POST", "/api/v1/work", {"title": "T"}, key="op-1")
        again = await api("POST", "/api/v1/work", {"title": "T"}, key="op-1")
        assert (first.status_code, again.status_code) == (201, 200)
        assert first.json()["id"] == again.json()["id"]
        assert (
            await api("POST", "/api/v1/work", {"title": "Other"}, key="op-1")
        ).status_code == 409
        assert len(await _rows(co["db"], Task, Task.title == "T")) == 1

    async def test_agents_and_viewers_cannot_use_the_human_routes(self, co, api):
        assert (await api("POST", "/api/v1/work", {"title": "T"}, "run", "k")).status_code == 403
        assert (await api("POST", "/api/v1/work", {"title": "T"}, "viewer", "k")).status_code == 403

    async def test_review_and_cancel_over_http_and_foreign_404(self, co, api):
        work, _, attempt = await _submitted(co)
        listing = (await api("GET", "/api/v1/work")).json()
        assert _item(listing, work)["tasks"][0]["attempt"]["deliverable"] == DELIVERABLE
        assert (await api("GET", f"/api/v1/work/{work}", who="outsider")).status_code == 404
        assert (await api("POST", f"/api/v1/work/{work}/cancel", who="outsider")).status_code == 404
        body = {"decision": "verify"}
        url = f"/api/v1/work/attempts/{attempt}/review"
        assert (await api("POST", url, body, who="outsider")).status_code == 404
        assert (await api("POST", url, body, who="run")).status_code == 403
        first = (await api("POST", url, body)).json()
        again = (await api("POST", url, body)).json()
        assert (first["changed"], again["changed"]) == (True, False)
        done = (await api("GET", f"/api/v1/work/{work}")).json()
        assert done["status"] == "completed"
        assert (await api("POST", f"/api/v1/work/{work}/cancel")).status_code == 409

    async def test_run_tokens_cannot_act_and_never_read_a_deliverable(self, co, api):
        work, task, attempt = await _submitted(co)
        body = {"manager_id": str(co["acme_lead"])}
        for method, path, payload in (
            ("POST", f"/api/v1/work/{work}/delegate", body),
            ("POST", f"/api/v1/work/{work}/cancel", None),
            ("POST", f"/api/v1/work/attempts/{attempt}/review", {"decision": "verify"}),
        ):
            res = await api(method, path, payload, who="run")
            assert (res.status_code, res.json()["detail"]["code"]) == (403, "AGENT_USES_TOOLS")
        assert (await _get(co, Task, work)).status == "in_progress"
        assert (await _get(co, Task, task)).status == "in_review"
        assert (await _get(co, TaskAttempt, attempt)).status == "verifying"
        listed = (await api("GET", "/api/v1/work", who="run")).json()
        one = (await api("GET", f"/api/v1/work/{work}", who="run")).json()
        for item in (_item(listed, work), one):
            reply = item["tasks"][0]["attempt"]
            assert reply["awaiting_review"] is True and "deliverable" not in reply
        assert DELIVERABLE not in (await api("GET", "/api/v1/work", who="run")).text
        assert DELIVERABLE not in (await api("GET", f"/api/v1/work/{work}", who="run")).text
        human = (await api("GET", f"/api/v1/work/{work}")).json()
        assert human["tasks"][0]["attempt"]["deliverable"] == DELIVERABLE

    async def test_delegate_route_uses_the_companys_ceo(self, co, api):
        work = await _order(co)
        url = f"/api/v1/work/{work}/delegate"
        body = {"manager_id": str(co["acme_lead"])}
        assert (await api("POST", url, body)).json()["created"] is True
        assert (await api("POST", url, body)).json()["created"] is False
        assert (await api("POST", url, {"manager_id": str(co["other_lead"])})).status_code == 404

    async def test_generic_task_routes_cannot_complete_work(self, co, api):
        work, task, attempt = await _submitted(co)
        for target in (work, task):
            for state in ("completed", "failed", "cancelled", "in_review"):
                res = await api("PUT", f"/api/v1/tasks/{target}/status", {"status": state})
                assert res.status_code == 409, (state, res.text)
        assert (await _get(co, Task, task)).status == "in_review"
        assert (await _get(co, TaskAttempt, attempt)).status == "verifying"


class TestOrdinaryTasksStayOutOfWork:
    """An old top-level Task is not a work order: no stamp, no lifecycle, no work routes."""

    async def _plain(self, co, **fields):
        async with co["db"]() as s:
            task = Task(company_id=co["acme"], title="Old ticket", **fields)
            s.add(task)
            await s.commit()
            return task.id

    async def test_work_orders_are_stamped_and_plain_tasks_are_not(self, co):
        work = await _order(co)
        plain = await self._plain(co)
        assert work_service.is_work_order(await _get(co, Task, work))
        assert not work_service.is_work_order(await _get(co, Task, plain))
        assert (await _get(co, Task, plain)).work_spec is None

    async def test_plain_tasks_do_not_appear_in_status(self, co):
        plain = await self._plain(co)
        work = await _order(co)
        ids = {i["id"] for i in (await _status(co))["work"]}
        assert ids == {str(work)}
        assert await _code(_status(co, plain)) == 404

    async def test_plain_task_cannot_be_delegated_or_assigned(self, co):
        plain = await self._plain(co)
        assert await _code(_delegate(co, plain)) == 404
        # Even if someone set the manager on it directly, the manager cannot assign under it.
        owned = await self._plain(co, assigned_agent_id=co["acme_lead"], status="delegated")
        assert await _code(_assign(co, owned)) == 404
        assert await _rows(co["db"], Task, Task.parent_task_id == owned) == []
        assert (await _get(co, Task, plain)).status == "pending"

    async def test_work_routes_treat_a_plain_task_as_missing(self, co, api):
        plain = await self._plain(co)
        body = {"manager_id": str(co["acme_lead"])}
        assert (await api("GET", f"/api/v1/work/{plain}")).status_code == 404
        assert (await api("POST", f"/api/v1/work/{plain}/cancel")).status_code == 404
        assert (await api("POST", f"/api/v1/work/{plain}/delegate", body)).status_code == 404
        listing = (await api("GET", "/api/v1/work")).json()
        assert listing["work"] == []
        row = await _get(co, Task, plain)
        assert (row.status, row.assigned_agent_id) == ("pending", None)

    async def test_plain_task_is_never_awaiting_review(self, co):
        plain = await self._plain(co)
        snap = await _status(co)
        assert snap["metrics"]["awaiting_review"] == 0
        async with co["db"]() as s:
            assert (
                await _code(
                    work_service.review(
                        s,
                        co["acme"],
                        plain,
                        decision="verify",
                        reason=None,
                        actor="op",
                        reviewer_agent_id=None,
                    )
                )
                == 404
            )

    async def test_the_stamp_cannot_be_forged_through_the_task_routes(self, co, api):
        url = f"/api/v1/companies/{co['acme']}/tasks"
        res = await api("POST", url, {"title": "T", "work_spec": {"kind": "work_order"}})
        assert res.status_code == 422, res.text
        assert res.json()["detail"]["code"] == "INVALID_WORK_SPEC"

    async def test_pending_work_order_cannot_be_finished_through_the_task_routes(self, co, api):
        work = await _order(co)
        for state in ("completed", "failed", "cancelled", "in_review", "delegated"):
            res = await api("PUT", f"/api/v1/tasks/{work}/status", {"status": state})
            assert res.status_code == 409, (state, res.text)
        assert (await _get(co, Task, work)).status == "pending"

    async def test_plain_task_keeps_the_generic_routes(self, co, api):
        plain = await self._plain(co)
        res = await api("PUT", f"/api/v1/tasks/{plain}/status", {"status": "completed"})
        assert res.status_code == 200, res.text
