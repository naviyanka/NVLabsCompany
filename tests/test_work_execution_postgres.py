"""Company-work acceptance on a real, migrated PostgreSQL database.

The real app and the real services run end to end: sign-in, CEO directive, work order,
CEO -> manager delegation, manager -> employee assignment, the attempt worker, deliverable,
manager verification, CEO status, restart, audit. Routes and workers run as the application
role (row-level security applies); seeding and direct reads use the migration role.

Only the model call is faked (``chat_routes._call_llm``): no network, no live provider, and
the deliverable is one short fixed string. Waiting is done on the worker's own drain.
"""

# ruff: noqa: F811 -- fixtures imported from the PostgreSQL integration module
from __future__ import annotations

import asyncio
import json
import uuid
from datetime import timedelta
from typing import Any

import httpx
import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlmodel import select

from nexus.api.routes import chat as chat_routes
from nexus.auth import middleware as auth_middleware
from nexus.auth.users import create_user
from nexus.config import settings
from nexus.models.agent import Agent
from nexus.models.budget import BudgetPolicy
from nexus.models.company import Company
from nexus.models.governance import AuditLog
from nexus.models.repository import Repository
from nexus.models.task import Goal, Project, Task
from nexus.models.task_attempt import TaskAttempt
from nexus.runtime import chat_turns
from nexus.runtime import task_attempts as ta
from nexus.services import ceo_service
from nexus.tools import manager_tools
from nexus.tools.context import INBOUND_MCP, ExecutionContext
from tests.test_postgres_integration import (  # noqa: F401 -- module fixtures
    app_user_postgres_url,
    migrated_postgres_url,
    postgres_container,
    system_user_postgres_url,
)

pytestmark = [pytest.mark.postgres, pytest.mark.integration]

DELIVERABLE = "Q3 summary: revenue up 12%, costs flat."
OBJECTIVE = "Summarise the confidential Q3 numbers."
PASSWORD = "correct horse battery staple 9"


class Model:
    """The fake provider: one fixed reply per call, optionally failing."""

    def __init__(self) -> None:
        self.reply = DELIVERABLE
        self.error: Exception | None = None
        self.calls = 0

    async def __call__(self, agent, system_prompt, prompt, history, **kw):
        # The real _call_llm reserves budget first; keep that real so a cap refuses the call.
        hold = await chat_routes._reserve_budget(
            agent, system_prompt, prompt, history, {"model": "gpt-x"}
        )
        self.calls += 1
        try:
            if self.error is not None:
                raise self.error
            return self.reply, "fake-model", 7
        finally:
            await chat_routes._settle_budget(hold, 0, company_id=agent.company_id)


def _ctx(company: uuid.UUID, agent: uuid.UUID) -> ExecutionContext:
    return ExecutionContext(
        company_id=company,
        principal_id=f"run:{uuid.uuid4()}",
        principal_role="agent",
        source=INBOUND_MCP,
        agent_id=agent,
    )


class Stack:
    """The app's engines, patched in. ``restart`` rebuilds them: a service restart."""

    def __init__(self, admin_url, app_url, system_url, monkeypatch, tmp_path) -> None:
        self.urls = (admin_url, app_url, system_url)
        self.mp = monkeypatch
        self.model = Model()
        self.admin = create_async_engine(admin_url)
        self.admin_db = async_sessionmaker(self.admin, class_=AsyncSession, expire_on_commit=False)
        self.clients: list[httpx.AsyncClient] = []
        self.engines: list[Any] = []
        monkeypatch.setattr(settings, "session_cookie_secure", False)
        monkeypatch.setattr(settings, "worktree_root", str(tmp_path / "wt" / "{company_id}"))
        monkeypatch.setattr(chat_routes, "_call_llm", self.model)

        async def prompt(db, agent, company_id, text):
            return "system"

        monkeypatch.setattr(chat_routes, "_build_chat_prompt", prompt)
        self._wire()

    def _wire(self) -> None:
        import nexus.database as database

        _, app_url, system_url = self.urls
        app = create_async_engine(app_url, pool_size=10)
        system = create_async_engine(system_url, pool_size=5)
        self.engines = [app, system]
        self.mp.setattr(settings, "database_url", app_url)
        self.mp.setattr(settings, "system_database_url", system_url)
        factory = async_sessionmaker(app, expire_on_commit=False)
        self.mp.setattr(database, "async_session_factory", factory)
        # The auth middleware bound the default factory when it was imported.
        self.mp.setattr(auth_middleware, "async_session_factory", factory)
        self.mp.setattr(
            database, "_system_session_factory", async_sessionmaker(system, expire_on_commit=False)
        )

    async def restart(self) -> None:
        """Drop every engine and client, build new ones, then recover stale claims."""
        await ta.drain()
        await chat_turns.drain()
        for client in self.clients:
            await client.aclose()
        self.clients.clear()
        for engine in self.engines:
            await engine.dispose()
        self._wire()
        await ta.sweep()

    async def close(self) -> None:
        await ta.drain()
        await chat_turns.drain()
        for client in self.clients:
            await client.aclose()
        for engine in [*self.engines, self.admin]:
            await engine.dispose()

    async def login(self, email: str) -> Session:
        from nexus.main import app

        client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")
        self.clients.append(client)
        reply = await client.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD})
        assert reply.status_code == 200, reply.text
        return Session(client, client.cookies.get(settings.csrf_cookie_name))

    async def seed(self, name: str) -> dict[str, Any]:
        """A company with an admin, a viewer, a CEO, a manager (Lead) and an employee (Eve)."""
        tag = uuid.uuid4().hex[:8]
        ids: dict[str, Any] = {"name": name}
        async with self.admin_db() as s:
            company = Company(name=f"{name}-{tag}")
            s.add(company)
            await s.flush()
            ids["company"] = company.id
            for role in ("admin", "viewer"):
                email = f"{role}-{tag}@example.com"
                await create_user(
                    s, email=email, password=PASSWORD, company_id=company.id, role=role
                )
                ids[role] = email
            ceo = Agent(
                company_id=company.id,
                name="ceo",
                role="ceo",
                is_ceo=True,
                adapter_type="openai",
                model="gpt-x",
            )
            s.add(ceo)
            await s.flush()
            lead = Agent(
                company_id=company.id,
                name="lead",
                role="manager",
                adapter_type="openai",
                model="gpt-x",
                manager_id=ceo.id,
            )
            s.add(lead)
            await s.flush()
            eve = Agent(
                company_id=company.id,
                name="eve",
                role="analyst",
                adapter_type="openai",
                model="gpt-x",
                manager_id=lead.id,
            )
            s.add(eve)
            await s.flush()
            ids.update(ceo=ceo.id, lead=lead.id, eve=eve.id)
            await s.commit()
        return ids

    async def one(self, model, row_id):
        async with self.admin_db() as s:
            return await s.get(model, row_id)

    async def rows(self, model, *where):
        async with self.admin_db() as s:
            return list((await s.execute(select(model).where(*where))).scalars())

    async def scalar(self, query: str, **params):
        async with self.admin_db() as s:
            return (await s.execute(sa.text(query), params)).scalar_one()


class Session:
    """A signed-in browser: cookies plus the CSRF header the dashboard would send."""

    def __init__(self, client: httpx.AsyncClient, csrf: str | None) -> None:
        self.client, self.csrf = client, csrf

    async def call(self, method: str, path: str, body=None, key: str | None = None):
        headers = {"x-csrf-token": self.csrf or ""}
        if key:
            headers["Idempotency-Key"] = key
        return await self.client.request(method, path, json=body, headers=headers)


@pytest.fixture
async def stack(
    migrated_postgres_url, app_user_postgres_url, system_user_postgres_url, tmp_path, monkeypatch
):
    s = Stack(
        migrated_postgres_url,
        app_user_postgres_url,
        system_user_postgres_url,
        monkeypatch,
        tmp_path,
    )
    yield s
    await s.close()


async def _submit(stack, co, who, *, key="w1", title="Quarterly report"):
    """Create, delegate (CEO tool), assign (manager tool) and run to awaiting review."""
    made = await who.call(
        "POST", "/api/v1/work", {"title": title, "description": OBJECTIVE}, key=key
    )
    assert made.status_code == 201, made.text
    work = made.json()["id"]
    ceo, lead = _ctx(co["company"], co["ceo"]), _ctx(co["company"], co["lead"])
    delegated = await manager_tools.call(
        ceo, "ceo_delegate_task_to_manager", {"task_id": work, "manager_id": str(co["lead"])}
    )
    assert delegated["created"] is True
    assign = {
        "work_id": work,
        "employee_id": str(co["eve"]),
        "title": "Draft summary",
        "objective": OBJECTIVE,
        "idempotency_key": f"assign-{key}",
        "expected_deliverable": "One paragraph",
    }
    first = await manager_tools.call(lead, "manager_assign_work", assign)
    await ta.drain()
    return work, first["task_id"], first["attempt"]["id"], assign


async def _work(who, work_id):
    reply = await who.call("GET", f"/api/v1/work/{work_id}")
    assert reply.status_code == 200, reply.text
    return reply.json()


def _no_content(text: str) -> None:
    assert DELIVERABLE not in text and OBJECTIVE not in text


class TestAcceptance:
    async def test_full_loop_replay_restart_isolation_and_audit(self, stack):
        a, b = await stack.seed("A"), await stack.seed("B")
        admin = await stack.login(a["admin"])
        other = await stack.login(b["admin"])

        # CEO directive over the real chat route, then the work order.
        stack.model.reply = "Understood. I will delegate it."
        told = await admin.call(
            "POST",
            f"/api/v1/agents/{a['ceo']}/chat",
            {"prompt": "Get the quarterly report done."},
            key="directive-1",
        )
        assert told.status_code == 200, told.text
        stack.model.reply = DELIVERABLE
        work, task, attempt, assign = await _submit(stack, a, admin)

        # Awaiting review: durable, submitted, not complete.
        waiting = await stack.one(TaskAttempt, uuid.UUID(attempt))
        assert (waiting.status, waiting.claimed_by) == ("verifying", None)
        assert waiting.agent_id == a["eve"] and waiting.company_id == a["company"]
        assert (await stack.one(Task, uuid.UUID(task))).status == "in_review"
        pending = await _work(admin, work)
        assert pending["status"] != "completed"
        assert pending["tasks"][0]["attempt"]["deliverable"] == DELIVERABLE
        assert pending["tasks"][0]["attempt"]["awaiting_review"] is True
        calls_before = stack.model.calls

        # Replay every mutation: nothing new.
        lead, ceo = _ctx(a["company"], a["lead"]), _ctx(a["company"], a["ceo"])
        again = await admin.call("POST", "/api/v1/work", {"title": "Quarterly report"}, key="w1")
        assert again.status_code in (200, 201) and again.json()["id"] == work
        redelegated = await manager_tools.call(
            ceo, "ceo_delegate_task_to_manager", {"task_id": work, "manager_id": str(a["lead"])}
        )
        reassigned = await manager_tools.call(lead, "manager_assign_work", assign)
        await ta.drain()
        assert redelegated["created"] is False and reassigned["created"] is False
        assert stack.model.calls == calls_before

        # Company B sees and changes nothing: 404s are the same as for a missing id.
        missing = uuid.uuid4()
        for who in (work, str(missing)):
            assert (await other.call("GET", f"/api/v1/work/{who}")).status_code == 404
            assert (await other.call("POST", f"/api/v1/work/{who}/cancel")).status_code == 404
        review_b = await other.call(
            "POST", f"/api/v1/work/attempts/{attempt}/review", {"decision": "verify"}
        )
        review_missing = await other.call(
            "POST", f"/api/v1/work/attempts/{missing}/review", {"decision": "verify"}
        )
        assert review_b.status_code == review_missing.status_code == 404
        gone = {r.json()["detail"]["code"] for r in (review_b, review_missing)}
        assert gone == {"ATTEMPT_NOT_FOUND"}
        assert review_b.text.replace(attempt, "ID") == review_missing.text.replace(
            str(missing), "ID"
        )
        assert (await other.call("GET", "/api/v1/work")).json()["work"] == []

        # Restart: new engines, new clients, stale-claim sweep. Same state, no extra work.
        await stack.restart()
        admin, other = await stack.login(a["admin"]), await stack.login(b["admin"])
        survived = await _work(admin, work)
        assert survived["status"] != "completed"
        assert stack.model.calls == calls_before
        assert (await stack.one(TaskAttempt, uuid.UUID(attempt))).status == "verifying"

        # Manager verification is its own transition; a replay changes nothing.
        verdict = await manager_tools.call(
            _ctx(a["company"], a["lead"]),
            "manager_review_work",
            {"attempt_id": attempt, "decision": "verify"},
        )
        replay = await manager_tools.call(
            _ctx(a["company"], a["lead"]),
            "manager_review_work",
            {"attempt_id": attempt, "decision": "verify"},
        )
        assert (verdict["changed"], replay["changed"]) == (True, False)
        done = await stack.one(TaskAttempt, uuid.UUID(attempt))
        assert done.status == "completed"
        assert (await stack.one(Task, uuid.UUID(task))).status == "completed"
        assert (await stack.one(Task, uuid.UUID(work))).status == "completed"
        assert len(await stack.rows(TaskAttempt, TaskAttempt.company_id == a["company"])) == 1
        assert stack.model.calls == calls_before

        # CEO status reports the stored result, over the tool and in the chat context.
        status = await manager_tools.call(ceo, "ceo_get_work_status", {})
        item = next(i for i in status["work"] if i["id"] == work)
        assert item["status"] == "completed"
        async with stack.admin_db() as s:
            context = await ceo_service.chat_context(s, a["company"], a["ceo"])
        assert "Quarterly report" in context and "completed" in context
        listing = (await admin.call("GET", "/api/v1/work")).json()
        shown = next(i for i in listing["work"] if i["id"] == work)
        assert DELIVERABLE in (shown["tasks"][0]["result"] or "")
        assert (await other.call("GET", "/api/v1/work")).json()["work"] == []

        # Audit: the lifecycle is on the chain, IDs and sizes only.
        actions = {
            r.action for r in await stack.rows(AuditLog, AuditLog.company_id == a["company"])
        }
        assert {
            "task.attempt_claimed",
            "task.attempt_completed",
        } <= actions
        assert any(x.startswith("work.") for x in actions), sorted(actions)
        blob = json.dumps(
            [
                {"action": r.action, "details": r.details}
                for r in await stack.rows(AuditLog, AuditLog.company_id == a["company"])
            ],
            default=str,
        )
        _no_content(blob)
        verify = await admin.call("GET", f"/api/v1/companies/{a['company']}/audit-logs/verify")
        assert verify.status_code == 200 and verify.json().get("valid", True) is True

    async def test_rls_hides_work_from_an_unbound_session(self, stack, app_user_postgres_url):
        a = await stack.seed("A")
        admin = await stack.login(a["admin"])
        await _submit(stack, a, admin)
        engine = create_async_engine(app_user_postgres_url)
        try:
            async with async_sessionmaker(engine)() as s:
                for table in ("tasks", "task_attempts"):
                    count = await s.execute(sa.text(f"SELECT count(*) FROM {table}"))
                    assert count.scalar_one() == 0, table
                await s.execute(
                    sa.text("SELECT set_config('nexus.company_id', :c, false)"),
                    {"c": str(a["company"])},
                )
                bound = await s.execute(sa.text("SELECT count(*) FROM task_attempts"))
                assert bound.scalar_one() == 1
        finally:
            await engine.dispose()


class TestReplayAndRaces:
    async def test_two_workers_race_for_one_claim(self, stack):
        a = await stack.seed("A")
        admin = await stack.login(a["admin"])
        made = await admin.call("POST", "/api/v1/work", {"title": "Race"}, key="r1")
        work = made.json()["id"]
        await manager_tools.call(
            _ctx(a["company"], a["ceo"]),
            "ceo_delegate_task_to_manager",
            {"task_id": work, "manager_id": str(a["lead"])},
        )
        worker = ta.get_worker()
        wake, worker.wake = worker.wake, lambda company_id=None: None
        try:
            assign = {
                "work_id": work,
                "employee_id": str(a["eve"]),
                "title": "Draft",
                "objective": OBJECTIVE,
                "idempotency_key": "race",
            }
            first = await manager_tools.call(
                _ctx(a["company"], a["lead"]), "manager_assign_work", assign
            )
        finally:
            worker.wake = wake
        attempt = uuid.UUID(first["attempt"]["id"])
        won = await asyncio.gather(
            ta.claim(attempt, a["company"], "worker-1"),
            ta.claim(attempt, a["company"], "worker-2"),
        )
        assert sum(1 for c in won if c is not None) == 1
        row = await stack.one(TaskAttempt, attempt)
        assert row.claimed_by in ("worker-1", "worker-2")
        assert (
            len(
                await stack.rows(
                    TaskAttempt,
                    TaskAttempt.company_id == a["company"],
                    TaskAttempt.status != "queued",
                )
            )
            == 1
        )

    async def test_verify_and_reject_race_has_one_winner(self, stack):
        a = await stack.seed("A")
        admin = await stack.login(a["admin"])
        _, _, attempt, _ = await _submit(stack, a, admin)
        lead = _ctx(a["company"], a["lead"])

        async def decide(decision):
            args = {"attempt_id": attempt, "decision": decision, "reason": "no"}
            return await manager_tools.call(lead, "manager_review_work", args)

        outcomes = await asyncio.gather(decide("verify"), decide("reject"), return_exceptions=True)
        wins = [o for o in outcomes if isinstance(o, dict) and o["changed"]]
        assert len(wins) == 1
        final = await stack.one(TaskAttempt, uuid.UUID(attempt))
        assert final.status in ("completed", "failed", "cancelled")

    async def test_crashed_worker_is_recovered_without_rerunning_the_employee(self, stack):
        a = await stack.seed("A")
        admin = await stack.login(a["admin"])
        made = await admin.call("POST", "/api/v1/work", {"title": "Crash"}, key="c1")
        work = made.json()["id"]
        await manager_tools.call(
            _ctx(a["company"], a["ceo"]),
            "ceo_delegate_task_to_manager",
            {"task_id": work, "manager_id": str(a["lead"])},
        )
        worker = ta.get_worker()
        wake, worker.wake = worker.wake, lambda company_id=None: None
        try:
            first = await manager_tools.call(
                _ctx(a["company"], a["lead"]),
                "manager_assign_work",
                {
                    "work_id": work,
                    "employee_id": str(a["eve"]),
                    "title": "Draft",
                    "objective": OBJECTIVE,
                    "idempotency_key": "crash",
                },
            )
        finally:
            worker.wake = wake
        attempt = uuid.UUID(first["attempt"]["id"])
        claimed = await ta.claim(attempt, a["company"], "dead-worker")
        await ta._prepare(claimed, "dead-worker")
        await chat_turns.drain()  # the employee answered; the worker "died" before submitting
        assert stack.model.calls == 1

        await stack.restart()
        outcome = await ta.sweep(ta._now() + timedelta(hours=2))
        assert outcome["recovered"] >= 1
        ta.get_worker().wake(a["company"])
        await ta.drain()
        final = await stack.one(TaskAttempt, attempt)
        assert (final.status, final.claimed_by) == ("verifying", None)
        assert stack.model.calls == 1, "the external effect was replayed"
        assert len(await stack.rows(TaskAttempt, TaskAttempt.company_id == a["company"])) == 1


class TestFailures:
    async def test_provider_failure_leaves_stable_failed_state(self, stack):
        a = await stack.seed("A")
        admin = await stack.login(a["admin"])
        stack.model.error = RuntimeError("provider down: secret-detail")
        work, task, attempt, _ = await _submit(stack, a, admin)
        row = await stack.one(TaskAttempt, uuid.UUID(attempt))
        assert row.status == "failed" and not row.output_summary
        assert (await stack.one(Task, uuid.UUID(task))).status != "completed"
        shown = await _work(admin, work)
        assert shown["status"] != "completed"
        audit = json.dumps(
            [r.details for r in await stack.rows(AuditLog, AuditLog.company_id == a["company"])],
            default=str,
        )
        assert "secret-detail" not in audit

    async def test_budget_refusal_stops_before_the_model_call(self, stack):
        a = await stack.seed("A")
        async with stack.admin_db() as s:
            s.add(
                BudgetPolicy(
                    company_id=a["company"],
                    scope_type="company",
                    scope_id=a["company"],
                    metric="cost_cents",
                    window_kind="monthly",
                    amount=0,
                    hard_stop_enabled=True,
                )
            )
            await s.commit()
        admin = await stack.login(a["admin"])
        _, task, attempt, _ = await _submit(stack, a, admin)
        row = await stack.one(TaskAttempt, uuid.UUID(attempt))
        assert row.status == "failed" and stack.model.calls == 0
        assert (await stack.one(Task, uuid.UUID(task))).status != "completed"

    async def test_reject_with_retry_then_cap(self, stack):
        a = await stack.seed("A")
        admin = await stack.login(a["admin"])
        work, task, attempt, _ = await _submit(stack, a, admin)
        lead = _ctx(a["company"], a["lead"])
        rejected = await manager_tools.call(
            lead,
            "manager_review_work",
            {"attempt_id": attempt, "decision": "reject", "reason": "too thin", "retry": True},
        )
        assert rejected["changed"] is True
        await ta.drain()
        attempts = await stack.rows(TaskAttempt, TaskAttempt.task_id == uuid.UUID(task))
        assert sorted(x.attempt_number for x in attempts) == [1, 2]
        second = next(x for x in attempts if x.attempt_number == 2)
        assert second.status == "verifying"
        done = await manager_tools.call(
            lead, "manager_review_work", {"attempt_id": str(second.id), "decision": "verify"}
        )
        assert done["changed"] is True
        assert (await stack.one(Task, uuid.UUID(work))).status == "completed"

    async def test_cancel_work_awaiting_review(self, stack):
        a = await stack.seed("A")
        admin = await stack.login(a["admin"])
        work, task, attempt, _ = await _submit(stack, a, admin)
        first = await admin.call("POST", f"/api/v1/work/{work}/cancel")
        again = await admin.call("POST", f"/api/v1/work/{work}/cancel")
        assert first.status_code == again.status_code == 200
        assert (first.json()["changed"], again.json()["changed"]) == (True, False)
        assert (await stack.one(Task, uuid.UUID(work))).status == "cancelled"
        assert (await stack.one(TaskAttempt, uuid.UUID(attempt))).status == "cancelled"
        late = await admin.call(
            "POST", f"/api/v1/work/attempts/{attempt}/review", {"decision": "verify"}
        )
        assert late.status_code in (404, 409)
        assert (await stack.one(Task, uuid.UUID(work))).status == "cancelled"

    async def test_unauthorized_verification_is_refused(self, stack):
        a = await stack.seed("A")
        admin = await stack.login(a["admin"])
        viewer = await stack.login(a["viewer"])
        _, task, attempt, _ = await _submit(stack, a, admin)
        review = {"decision": "verify"}
        assert (
            await viewer.call("POST", f"/api/v1/work/attempts/{attempt}/review", review)
        ).status_code == 403
        # The employee who did the work cannot verify it.
        with pytest.raises(Exception):
            await manager_tools.call(
                _ctx(a["company"], a["eve"]),
                "manager_review_work",
                {"attempt_id": attempt, "decision": "verify"},
            )
        assert (await stack.one(TaskAttempt, uuid.UUID(attempt))).status == "verifying"
        assert (await stack.one(Task, uuid.UUID(task))).status == "in_review"

    async def test_another_companys_manager_cannot_review(self, stack):
        a, b = await stack.seed("A"), await stack.seed("B")
        admin = await stack.login(a["admin"])
        _, _, attempt, _ = await _submit(stack, a, admin)
        with pytest.raises(Exception) as caught:
            await manager_tools.call(
                _ctx(b["company"], b["lead"]),
                "manager_review_work",
                {"attempt_id": attempt, "decision": "verify"},
            )
        assert "404" in str(caught.value) or "not found" in str(caught.value).lower()
        assert (await stack.one(TaskAttempt, uuid.UUID(attempt))).status == "verifying"

    async def test_task_routes_cannot_complete_work(self, stack):
        a = await stack.seed("A")
        admin = await stack.login(a["admin"])
        work, task, _, _ = await _submit(stack, a, admin)
        reply = await admin.call("PUT", f"/api/v1/tasks/{task}/status", {"status": "completed"})
        assert reply.status_code == 409
        assert (await stack.one(Task, uuid.UUID(task))).status == "in_review"

    async def test_cross_tenant_parent_and_agent_are_refused(self, stack):
        a, b = await stack.seed("A"), await stack.seed("B")
        admin = await stack.login(a["admin"])
        async with stack.admin_db() as s:
            theirs = Task(company_id=b["company"], title="Theirs")
            s.add(theirs)
            await s.commit()
            foreign = theirs.id
        before = len(await stack.rows(Task))
        url = f"/api/v1/companies/{a['company']}/tasks"
        for body in (
            {"title": "x", "parent_task_id": str(foreign)},
            {"title": "x", "assigned_agent_id": str(b["eve"])},
        ):
            assert (await admin.call("POST", url, body)).status_code == 404
        sub = await admin.call("POST", f"/api/v1/tasks/{foreign}/subtasks", {"title": "x"})
        assert sub.status_code == 404
        leak = await admin.call("POST", f"/api/v1/companies/{b['company']}/tasks", {"title": "x"})
        assert leak.status_code == 403
        assert len(await stack.rows(Task)) == before

    async def test_an_unrelated_manager_cannot_take_over_a_failed_work_child(self, stack):
        a = await stack.seed("A")
        admin = await stack.login(a["admin"])
        _, task, attempt, _ = await _submit(stack, a, admin)
        async with stack.admin_db() as s:
            bo = Agent(
                company_id=a["company"],
                name="bo",
                role="manager",
                adapter_type="openai",
                model="gpt-x",
                manager_id=a["ceo"],
            )
            s.add(bo)
            await s.flush()
            zed = Agent(
                company_id=a["company"],
                name="zed",
                role="analyst",
                adapter_type="openai",
                model="gpt-x",
                manager_id=bo.id,
            )
            s.add(zed)
            (await s.get(TaskAttempt, uuid.UUID(attempt))).status = "failed"
            (await s.get(Task, uuid.UUID(task))).status = "failed"
            await s.commit()
            bo_id, zed_id = bo.id, zed.id
        attempts = len(await stack.rows(TaskAttempt, TaskAttempt.task_id == uuid.UUID(task)))
        with pytest.raises(Exception) as caught:
            await manager_tools.call(
                _ctx(a["company"], bo_id),
                "manager_delegate_task",
                {"task_id": task, "employee_id": str(zed_id)},
            )
        assert "404" in str(caught.value) or "not found" in str(caught.value).lower()
        row = await stack.one(Task, uuid.UUID(task))
        assert (row.status, row.assigned_agent_id) == ("failed", a["eve"])
        after = await stack.rows(TaskAttempt, TaskAttempt.task_id == uuid.UUID(task))
        assert len(after) == attempts

    async def test_task_and_work_references_are_validated_by_company(self, stack):
        """Foreign keys accept any tenant's row: the service must refuse it, and the same way
        for a missing id. Nothing is written for a refused request."""
        a, b = await stack.seed("A"), await stack.seed("B")
        admin = await stack.login(a["admin"])
        async with stack.admin_db() as s:
            rows = {
                "own_project": Project(company_id=a["company"], name="own"),
                "foreign_project": Project(company_id=b["company"], name="theirs"),
                "closed_project": Project(company_id=a["company"], name="done", status="archived"),
                "own_goal": Goal(company_id=a["company"], title="own"),
                "foreign_goal": Goal(company_id=b["company"], title="theirs"),
                "closed_goal": Goal(company_id=a["company"], title="done", status="completed"),
                "foreign_repo": Repository(
                    company_id=b["company"], name="r", url="https://x.test/r"
                ),
            }
            s.add_all(rows.values())
            await s.commit()
            ids = {name: row.id for name, row in rows.items()}
        url = f"/api/v1/companies/{a['company']}/tasks"
        before = (len(await stack.rows(Task)), len(await stack.rows(AuditLog)))

        own = await admin.call("POST", url, {"title": "ok", "project_id": str(ids["own_project"])})
        assert own.status_code == 201 and own.json()["project_id"] == str(ids["own_project"])
        after_own = (len(await stack.rows(Task)), len(await stack.rows(AuditLog)))

        answers = {}
        for name, project in (
            ("foreign", ids["foreign_project"]),
            ("missing", uuid.uuid4()),
        ):
            res = await admin.call("POST", url, {"title": "x", "project_id": str(project)})
            answers[name] = (res.status_code, res.text.replace(str(project), "<id>"))
        assert answers["foreign"] == answers["missing"] and answers["foreign"][0] == 404
        archived = str(ids["closed_project"])
        closed = await admin.call("POST", url, {"title": "x", "project_id": archived})
        assert closed.status_code == 409
        spec = {"mode": "read_only", "repository_id": str(ids["foreign_repo"])}
        repo = await admin.call("POST", url, {"title": "x", "work_spec": spec})
        assert repo.status_code == 404

        goals = {}
        for name, goal in (("foreign", ids["foreign_goal"]), ("missing", uuid.uuid4())):
            res = await admin.call(
                "POST", "/api/v1/work", {"title": "T", "goal_id": str(goal)}, key=f"g-{name}"
            )
            goals[name] = (res.status_code, res.text.replace(str(goal), "<id>"))
        assert goals["foreign"] == goals["missing"] and goals["foreign"][0] == 404
        shut = await admin.call(
            "POST", "/api/v1/work", {"title": "T", "goal_id": str(ids["closed_goal"])}, key="g-c"
        )
        assert shut.status_code == 409
        assert (len(await stack.rows(Task)), len(await stack.rows(AuditLog))) == after_own
        assert after_own[0] == before[0] + 1

        linked = await admin.call(
            "POST", "/api/v1/work", {"title": "T", "goal_id": str(ids["own_goal"])}, key="g-own"
        )
        assert linked.status_code == 201
        assert (await stack.one(Task, uuid.UUID(linked.json()["id"]))).goal_id == ids["own_goal"]
        assert (await stack.one(Project, ids["foreign_project"])).company_id == b["company"]
