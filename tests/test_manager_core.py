"""Manager Core: reporting lines, delegation, employee status, roll-up and manager tools.

Runs on the employee-work fixtures (tests/test_employee_work.py): a file
SQLite database, real git repositories and worktrees, the real attempt worker
and verifier, and a faked model call. Delegated work therefore goes through
the production TaskAttempt path end to end.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from datetime import timedelta

import httpx
import pytest
from fastapi import FastAPI, Request

from nexus.api.routes import agents as agent_routes
from nexus.api.routes import managers as manager_routes
from nexus.auth.principal import Principal
from nexus.models.agent import Agent
from nexus.models.governance import AuditLog
from nexus.models.task import Task
from nexus.models.task_attempt import TaskAttempt
from nexus.models.tool import ToolPolicy
from nexus.runtime import task_attempts as ta
from nexus.services import manager_service
from nexus.tools.context import INBOUND_MCP, ExecutionContext
from nexus.tools.mcp_server import MCPServer
from tests.test_employee_work import _me, _rows, _task, db, w  # noqa: F401 -- fixtures

pytestmark = pytest.mark.employee_work


@pytest.fixture
async def team(db, w):  # noqa: F811
    """Acme: manager Lead (Claude) over claude and agy; manager Bo over claude2.

    Bo's report and the extra tasks are created here; the reporting lines for
    Lead are set through the API by each test that needs them.
    """
    ids = dict(w)
    async with db() as s:
        lead = Agent(company_id=w["acme"], name="Lead", role="manager", adapter_type="cli",
                     adapter_config={"backend": "claude"}, model="")
        bo = Agent(company_id=w["acme"], name="Bo", role="manager", adapter_type="cli",
                   adapter_config={"backend": "claude"}, model="")
        s.add_all([lead, bo])
        await s.flush()
        claude2 = Agent(company_id=w["acme"], name="claude2", role="engineer", adapter_type="cli",
                        adapter_config={"backend": "claude"}, model="", manager_id=bo.id)
        other_lead = Agent(company_id=w["other"], name="OtherLead", role="manager",
                           adapter_type="cli", adapter_config={"backend": "claude"}, model="")
        s.add_all([claude2, other_lead])
        await s.commit()
        ids.update(lead=lead.id, bo=bo.id, claude2=claude2.id, other_lead=other_lead.id)
    ids["task2"] = await _task(db, w["acme"], None, w["acme_repo"], title="Second")
    ids["bo_task"] = await _task(db, w["acme"], None, w["acme_repo"], title="Bo's task")

    principals = {
        "admin": _me(w["acme"]),
        "viewer": _me(w["acme"], role="viewer"),
        "outsider": _me(w["other"]),
        "lead_run": Principal(kind="run", company_id=w["acme"], role="agent",
                              run_id=uuid.uuid4(), agent_id=lead.id),
        "bo_run": Principal(kind="run", company_id=w["acme"], role="agent",
                            run_id=uuid.uuid4(), agent_id=bo.id),
    }
    app = FastAPI()
    app.include_router(agent_routes.router)
    app.include_router(manager_routes.router)

    @app.middleware("http")
    async def as_principal(request: Request, call_next):
        request.state.principal = principals[request.headers.get("x-test-principal", "admin")]
        return await call_next(request)

    client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")
    ids["client"] = client
    yield ids
    await client.aclose()


async def _call(t, method, path, body=None, who="admin"):
    return await t["client"].request(method, path, json=body, headers={"x-test-principal": who})


async def _report_to(t, employee, manager, who="admin"):
    return await _call(t, "PUT", f"/api/v1/agents/{employee}/manager",
                       {"manager_id": manager and str(manager)}, who)


async def _delegate(t, task, employee, manager=None, who="admin"):
    manager = manager or t["lead"]
    return await _call(t, "POST", f"/api/v1/agents/{manager}/delegations",
                       {"task_id": str(task), "employee_id": str(employee)}, who)


async def _staffed(t):
    for employee in (t["acme_claude"], t["acme_agy"]):
        assert (await _report_to(t, employee, t["lead"])).status_code == 200


async def _actions(db, prefix):  # noqa: F811
    rows = await _rows(db, AuditLog, AuditLog.action.startswith(prefix))
    return [(r.action, r.resource_type, r.resource_id, r.details) for r in rows]


def _ctx(company, agent):
    return ExecutionContext(company_id=company, principal_id=f"run:{uuid.uuid4()}",
                            principal_role="agent", source=INBOUND_MCP, agent_id=agent)


# --- reporting lines (existing PUT /manager route) --------------------------


class TestRelationships:
    async def test_same_tenant_reports_are_listed_and_audited(self, db, team):  # noqa: F811
        await _staffed(team)
        async with db() as s:
            reports = await manager_service.direct_reports(s, team["acme"], team["lead"])
        assert {r.id for r in reports} == {team["acme_claude"], team["acme_agy"]}
        changed = await _actions(db, "agent.manager_changed")
        assert {row[2] for row in changed} == {str(team["acme_claude"]), str(team["acme_agy"])}

    async def test_cross_tenant_reporting_line_is_refused(self, db, team):  # noqa: F811
        assert (await _report_to(team, team["acme_claude"], team["other_lead"])).status_code == 404
        assert (
            await _report_to(team, team["acme_claude"], team["lead"], who="outsider")
        ).status_code == 404
        async with db() as s:
            assert await manager_service.direct_reports(s, team["acme"], team["other_lead"]) == []

    async def test_self_management_and_cycles_are_refused(self, db, team):  # noqa: F811
        assert (await _report_to(team, team["lead"], team["lead"])).status_code == 409
        await _staffed(team)
        # Lead manages claude, so Lead cannot report to claude.
        assert (await _report_to(team, team["lead"], team["acme_claude"])).status_code == 409
        # Nor transitively: claude2 -> Bo -> Lead, then Lead -> claude2.
        assert (await _report_to(team, team["bo"], team["lead"])).status_code == 200
        assert (await _report_to(team, team["lead"], team["claude2"])).status_code == 409


# --- delegation ------------------------------------------------------------


class TestDelegation:
    async def test_delegation_runs_through_the_task_attempt_path(self, db, team):  # noqa: F811
        await _staffed(team)
        response = await _delegate(team, team["task2"], team["acme_agy"])
        assert response.status_code == 201, response.text
        view = response.json()
        assert view["agent_id"] == str(team["acme_agy"])
        assert view["idempotency_key"] == f"manager:{team['lead']}:{team['acme_agy']}"
        async with db() as s:
            task = await s.get(Task, team["task2"])
        assert task.assigned_agent_id == team["acme_agy"]

        await ta.drain()
        async with db() as s:
            done = await ta._get(s, team["acme"], uuid.UUID(view["id"]))
        assert done.status == "completed", done.error
        assert [c["agent"] for c in db.emp.calls] == [team["acme_agy"]]

    async def test_unmanaged_or_foreign_employee_is_refused(self, db, team):  # noqa: F811
        await _staffed(team)
        # claude2 reports to Bo, not Lead.
        refused = await _delegate(team, team["task2"], team["claude2"])
        assert (refused.status_code, refused.json()["detail"]["code"]) == (
            403, "NOT_A_DIRECT_REPORT"
        )
        foreign = await _delegate(team, team["task2"], team["other_claude"])
        assert foreign.status_code == 404
        # An outsider cannot reach Lead at all; an agent may act only as itself.
        assert (await _delegate(team, team["task2"], team["acme_agy"], who="outsider")
                ).status_code == 404
        assert (await _delegate(team, team["task2"], team["acme_agy"], who="bo_run")
                ).status_code == 403
        assert (await _delegate(team, team["task2"], team["acme_agy"], who="viewer")
                ).status_code == 403
        assert await _rows(db, TaskAttempt, TaskAttempt.task_id == team["task2"]) == []

    async def test_duplicate_delegation_creates_one_attempt(self, db, team):  # noqa: F811
        await _staffed(team)
        worker = ta.get_worker()
        wake, worker.wake = worker.wake, (lambda company_id=None: None)
        try:
            async def once():
                async with db() as s:
                    return await manager_service.delegate(
                        s, team["acme"], team["lead"], team["acme_agy"], team["task2"],
                        _me(team["acme"]),
                    )

            results = await asyncio.gather(once(), once())
            again = await _delegate(team, team["task2"], team["acme_agy"])
        finally:
            worker.wake = wake
        assert len({a.id for a, _ in results}) == 1
        assert sorted(created for _, created in results) == [False, True]
        assert (again.status_code, again.json()["id"]) == (200, str(results[0][0].id))
        assert len(await _rows(db, TaskAttempt, TaskAttempt.task_id == team["task2"])) == 1

    async def test_two_managers_run_work_concurrently(self, db, team):  # noqa: F811
        await _staffed(team)
        a, b = await asyncio.gather(
            _delegate(team, team["task2"], team["acme_agy"], who="lead_run"),
            _delegate(team, team["bo_task"], team["claude2"], manager=team["bo"], who="bo_run"),
        )
        assert (a.status_code, b.status_code) == (201, 201), (a.text, b.text)
        await ta.drain()
        async with db() as s:
            done = [await ta._get(s, team["acme"], uuid.UUID(r.json()["id"])) for r in (a, b)]
        assert [d.status for d in done] == ["completed", "completed"]
        assert [d.agent_id for d in done] == [team["acme_agy"], team["claude2"]]

        lead = (await _call(team, "GET", f"/api/v1/agents/{team['lead']}/rollup")).json()
        bo = (await _call(team, "GET", f"/api/v1/agents/{team['bo']}/rollup")).json()
        assert [x["title"] for x in lead["work"]["completed"]] == ["Second"]
        assert [x["title"] for x in bo["work"]["completed"]] == ["Bo's task"]
        # Bo cannot read Lead's team.
        assert (await _call(team, "GET", f"/api/v1/agents/{team['lead']}/rollup", who="bo_run")
                ).status_code == 403


# --- status and roll-up ----------------------------------------------------


async def _attempt_row(db, t, task, agent, status, **kw):  # noqa: F811
    async with db() as s:
        row = TaskAttempt(company_id=t["acme"], task_id=task, agent_id=agent, attempt_number=1,
                          idempotency_key=uuid.uuid4().hex, status=status, **kw)
        s.add(row)
        await s.commit()
    return row


class TestStatus:
    async def test_rollup_buckets_are_derived_from_attempts(self, db, team):  # noqa: F811
        await _staffed(team)
        now = ta._now()
        acme, claude, agy = team["acme"], team["acme_claude"], team["acme_agy"]
        tasks = {}
        for title, agent in [("done", claude), ("broken", claude), ("stuck", agy),
                             ("running", agy), ("stale", claude), ("waiting", agy)]:
            tasks[title] = await _task(db, acme, agent, team["acme_repo"], title=title)
        await _attempt_row(db, team, tasks["done"], claude, "completed", completed_at=now,
                           output_summary="shipped", artifacts=[{"path": "src/a.py"}],
                           updated_at=now - timedelta(minutes=3))
        await _attempt_row(db, team, tasks["broken"], claude, "failed", error_code="TESTS_FAILED",
                           error="1 failed", updated_at=now - timedelta(minutes=2))
        await _attempt_row(db, team, tasks["stuck"], agy, "blocked", error_code="BLOCKED",
                           error="needs credentials", updated_at=now - timedelta(minutes=1))
        await _attempt_row(db, team, tasks["running"], agy, "running", started_at=now,
                           lease_expires_at=now + timedelta(minutes=5), updated_at=now,
                           report={"state": "in_progress", "progress_percent": 40}, report_seq=2)
        await _attempt_row(db, team, tasks["stale"], claude, "running",
                           lease_expires_at=now - timedelta(minutes=1),
                           updated_at=now - timedelta(hours=1))

        response = await _call(team, "GET", f"/api/v1/agents/{team['lead']}/rollup")
        assert response.status_code == 200
        body = response.json()
        titles = {k: sorted(x["title"] for x in v) for k, v in body["work"].items()}
        # w's own "Calculator" task is assigned to claude and never started.
        assert titles == {
            "active": ["running"],
            "queued": ["Calculator", "waiting"],
            "completed": ["done"],
            "failed_blocked": ["broken", "stuck"],
            "stale": ["stale"],
        }
        assert body["counts"] == {"active": 1, "queued": 2, "completed": 1,
                                  "failed_blocked": 2, "stale": 1}
        assert body["manager"]["id"] == str(team["lead"])
        assert body["summary"].startswith("Lead has 2 direct report(s): 1 active, 2 queued")
        assert "claude: broken" in body["summary"] and "agy: stuck" in body["summary"]
        assert body["generated_at"] and body["data_as_of"]

        by_name = {r["employee"]["name"]: r for r in body["direct_reports"]}
        agy_status, claude_status = by_name["agy"], by_name["claude"]
        assert agy_status["state"] == "working"
        assert agy_status["active"]["task_title"] == "running"
        assert agy_status["progress"] == {"report": {"state": "in_progress",
                                                     "progress_percent": 40}, "report_seq": 2}
        assert agy_status["latest_failure"]["error"] == "needs credentials"
        assert agy_status["backend"] == "agy"
        assert claude_status["state"] == "stale"
        assert claude_status["last_success"]["summary"] == "shipped"
        assert claude_status["latest_failure"]["error_code"] == "TESTS_FAILED"
        assert claude_status["latest_evidence"]["artifacts"] == [{"path": "src/a.py"}]

    async def test_failed_and_blocked_employees_show_their_blocker(self, db, team):  # noqa: F811
        await _staffed(team)
        now = ta._now()
        for agent, status in [(team["acme_claude"], "failed"), (team["acme_agy"], "blocked")]:
            task = await _task(db, team["acme"], agent, team["acme_repo"], title=status)
            await _attempt_row(db, team, task, agent, status, error=f"{status}!", updated_at=now)
        for agent, state in [(team["acme_claude"], "failed"), (team["acme_agy"], "blocked")]:
            got = await _call(team, "GET",
                              f"/api/v1/agents/{team['lead']}/reports/{agent}/status")
            assert got.status_code == 200
            assert (got.json()["state"], got.json()["latest_failure"]["error"]) == (
                state, f"{state}!"
            )
        # Not Lead's report, and not visible to Bo.
        assert (await _call(team, "GET", f"/api/v1/agents/{team['lead']}/reports/"
                            f"{team['claude2']}/status")).status_code == 403
        assert (await _call(team, "GET", f"/api/v1/agents/{team['lead']}/reports/"
                            f"{team['acme_agy']}/status", who="bo_run")).status_code == 403

    async def test_manager_reads_and_delegation_are_audited(self, db, team):  # noqa: F811
        await _staffed(team)
        lead, agy = team["lead"], team["acme_agy"]
        assert (await _delegate(team, team["task2"], agy)).status_code == 201
        await ta.drain()
        assert (await _call(team, "GET", f"/api/v1/agents/{lead}/reports/{agy}/status")
                ).status_code == 200
        evidence = await _call(team, "GET", f"/api/v1/agents/{lead}/tasks/{team['task2']}/evidence")
        assert evidence.status_code == 200
        assert evidence.json()["attempts"][0]["status"] == "completed"
        assert (await _call(team, "GET", f"/api/v1/agents/{lead}/rollup")).status_code == 200

        # The delegation is recorded on the attempt's own queued row.
        (queued,) = await _actions(db, "task.attempt_queued")
        assert queued[3]["delegated_by"] == str(lead) and queued[3]["agent_id"] == str(agy)
        assert queued[3]["task_id"] == str(team["task2"])
        assert queued[3]["idempotency_key"] == f"manager:{lead}:{agy}"
        rows = await _actions(db, "manager.")
        assert [(a, rt, rid) for a, rt, rid, _ in rows] == [
            ("manager.status_inspected", "agent", str(agy)),
            ("manager.evidence_inspected", "task", str(team["task2"])),
            ("manager.report_generated", "agent", str(lead)),
        ]
        assert all(r[3]["manager_id"] == str(lead) for r in rows[:2])


# --- manager tools (inbound MCP) -------------------------------------------


def _payload(result):
    assert result["isError"] is False, result
    return json.loads(result["content"][0]["text"])


class TestManagerTools:
    async def test_manager_sees_read_tools_and_only_its_reports(self, db, team):  # noqa: F811
        await _staffed(team)
        server = MCPServer(_ctx(team["acme"], team["lead"]))
        names = {t["name"] for t in await server.list_tools()}
        assert {"manager_list_reports", "manager_employee_status", "manager_task_evidence",
                "manager_rollup"} <= names
        # Write-risk: denied by the inbound default policy.
        assert "manager_delegate_task" not in names

        reports = _payload(await server.call_tool("manager_list_reports", {}))
        assert {r["name"] for r in reports} == {"claude", "agy"}
        status = _payload(await server.call_tool(
            "manager_employee_status", {"employee_id": str(team["acme_agy"])}))
        assert status["state"] == "idle"
        rollup = _payload(await server.call_tool("manager_rollup", {}))
        assert rollup["manager"]["name"] == "Lead"

        refused = await server.call_tool(
            "manager_employee_status", {"employee_id": str(team["claude2"])})
        assert refused["isError"] and "NOT_A_DIRECT_REPORT" in refused["content"][0]["text"]
        foreign = await server.call_tool(
            "manager_employee_status", {"employee_id": str(team["other_claude"])})
        assert foreign["isError"] and "AGENT_NOT_FOUND" in foreign["content"][0]["text"]
        bad = await server.call_tool("manager_rollup", {"manager_id": str(team["bo"])})
        assert bad["isError"] and "unexpected arguments" in bad["content"][0]["text"]
        denied = await server.call_tool("manager_delegate_task", {
            "task_id": str(team["task2"]), "employee_id": str(team["acme_agy"])})
        assert denied["isError"] and "Denied by access policy" in denied["content"][0]["text"]
        assert await _rows(db, TaskAttempt, TaskAttempt.task_id == team["task2"]) == []

    async def test_delegate_tool_needs_a_policy_and_a_report(self, db, team):  # noqa: F811
        await _staffed(team)
        async with db() as s:
            s.add_all([
                ToolPolicy(company_id=team["acme"], name="reads", effect="allow",
                           conditions={"risk_level": ["read"]}),
                ToolPolicy(company_id=team["acme"], name="delegation", effect="allow",
                           conditions={"tool_name": ["manager_delegate_task"]}),
            ])
            await s.commit()
        server = MCPServer(_ctx(team["acme"], team["lead"]))
        assert "manager_delegate_task" in {t["name"] for t in await server.list_tools()}
        args = {"task_id": str(team["bo_task"]), "employee_id": str(team["claude2"])}
        refused = await server.call_tool("manager_delegate_task", args)
        assert refused["isError"] and "NOT_A_DIRECT_REPORT" in refused["content"][0]["text"]

        args = {"task_id": str(team["task2"]), "employee_id": str(team["acme_agy"])}
        first = _payload(await server.call_tool("manager_delegate_task", args))
        # SQLite has one writer: let the attempt the first call woke finish.
        await ta.drain()
        again = _payload(await server.call_tool("manager_delegate_task", args))
        assert (first["created"], again["created"]) == (True, False)
        assert first["attempt"]["id"] == again["attempt"]["id"]
        # One queued attempt, recorded as the manager's delegation, acted by
        # the manager agent; the refused and the repeated call queue nothing.
        (queued,) = await _actions(db, "task.attempt_queued")
        assert queued[2] == first["attempt"]["id"]
        assert queued[3]["delegated_by"] == str(team["lead"])

    async def test_employees_and_other_tenants_get_no_manager_tools(self, db, team):  # noqa: F811
        await _staffed(team)
        employee = MCPServer(_ctx(team["acme"], team["acme_agy"]))
        assert not any(t["name"].startswith("manager_") for t in await employee.list_tools())
        # An employee's "team" is empty; it cannot reach its manager's.
        assert _payload(await employee.call_tool("manager_list_reports", {})) == []
        # A context claiming Lead under another company fails the access check.
        spoofed = MCPServer(_ctx(team["other"], team["lead"]))
        refused = await spoofed.call_tool("manager_list_reports", {})
        assert refused["isError"] and "Denied by access policy" in refused["content"][0]["text"]
