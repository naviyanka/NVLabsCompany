"""Controlled autonomous hiring: requests, policy, approval, materialization, tools.

Runs on the Manager Core fixtures (tests/test_manager_core.py): acme has the
managers Lead (no reports) and Bo (over claude2); "other" is a second tenant.
The CLI registry sees only ``claude`` and ``codex`` as installed. No CLI or
model is run anywhere here: hiring never needs one.
"""

from __future__ import annotations

import asyncio
import uuid

import httpx
import pytest
from fastapi import FastAPI, Request

from nexus.adapters import cli_registry
from nexus.api.routes import approvals as approval_routes
from nexus.api.routes import managers as manager_routes
from nexus.auth.principal import Principal
from nexus.models.agent import Agent
from nexus.models.governance import Approval, ApprovalSignerKey, AuditLog
from nexus.models.notification import Notification
from nexus.models.policy import Policy
from nexus.models.tool import ToolPolicy, ToolProfile, ToolProfileBinding
from nexus.services import ceo_service, hiring_service
from nexus.services.approval_service import ApprovalService
from nexus.tools.mcp_server import MCPServer
from tests.test_approval_signing import _keypair, _sign
from tests.test_employee_work import _me, _rows, db, w  # noqa: F401 -- fixtures
from tests.test_manager_core import _ctx, _payload, team  # noqa: F401 -- fixtures

pytestmark = pytest.mark.employee_work

HIRING_TOOLS = ["manager_request_hire", "manager_list_hiring_requests",
                "manager_get_hiring_request"]


@pytest.fixture
async def h(team, monkeypatch):  # noqa: F811
    monkeypatch.setattr(
        cli_registry.shutil, "which",
        lambda cmd: f"/opt/bin/{cmd}" if cmd in ("claude", "codex") else None,
    )
    monkeypatch.setattr(cli_registry, "_shared_registry", None)
    principals = {
        "admin": _me(team["acme"]),
        "viewer": _me(team["acme"], role="viewer"),
        "outsider": _me(team["other"]),
        "lead_run": Principal(kind="run", company_id=team["acme"], role="agent",
                              run_id=uuid.uuid4(), agent_id=team["lead"]),
        "bo_run": Principal(kind="run", company_id=team["acme"], role="agent",
                            run_id=uuid.uuid4(), agent_id=team["bo"]),
    }
    app = FastAPI()
    app.include_router(manager_routes.router)
    app.include_router(approval_routes.router)

    @app.middleware("http")
    async def as_principal(request: Request, call_next):
        request.state.principal = principals[request.headers.get("x-test-principal", "admin")]
        return await call_next(request)

    client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")
    yield {**team, "client": client, "principals": principals}
    await client.aclose()


async def _call(h, method, path, body=None, who="admin"):
    return await h["client"].request(method, path, json=body, headers={"x-test-principal": who})


def _body(key="k1", **over):
    return {"role": "engineer", "title": "Backend Engineer", "reason": "Ship the API",
            "backend": "claude", "responsibilities": "Own the API service",
            "estimated_monthly_cents": 700, "estimated_one_time_cents": 500,
            "urgency": "high", "idempotency_key": key, **over}


async def _hire(h, manager="lead", who="lead_run", **body):
    path = f"/api/v1/agents/{h[manager]}/hiring-requests"
    return await _call(h, "POST", path, _body(**body), who)


async def _add(db, *rows):  # noqa: F811
    async with db() as s:
        s.add_all(rows)
        await s.commit()


async def _allow(db, h, *tools):  # noqa: F811
    await _add(db, ToolPolicy(company_id=h["acme"], name="hiring", effect="allow",
                              conditions={"tool_name": list(tools or ["manager_request_hire"])}))


async def _policy(db, h, **hiring):  # noqa: F811
    await _add(db, Policy(company_id=h["acme"], name="hiring", rules={"hiring": hiring},
                          priority=10))


AUTO = {"auto_approve": {"enabled": True, "max_monthly_cents": 5000, "max_one_time_cents": 1000}}


async def _actions(db, request_id):  # noqa: F811
    rows = await _rows(db, AuditLog, AuditLog.action.startswith("hiring."))
    return [(r.action, r.actor_type) for r in rows if r.resource_id == str(request_id)]


async def _employees(db, h):  # noqa: F811
    return await _rows(db, Agent, Agent.company_id == h["acme"], Agent.role == "engineer",
                       Agent.name == "Backend Engineer")


class TestPolicy:
    async def test_default_is_approval_required_with_a_notification(self, db, h):  # noqa: F811
        await _allow(db, h)
        r = await _hire(h)
        assert r.status_code == 201, r.text
        view = r.json()
        assert view["status"] == view["policy_decision"] == "approval_required"
        assert view["policy_rule"] == "policy:default:hiring"
        assert view["employee"] is None and await _employees(db, h) == []
        assert view["manager_id"] == str(h["lead"])
        [note] = await _rows(db, Notification, Notification.company_id == h["acme"])
        assert note.notification_metadata["approval_id"] == view["id"]
        assert note.priority == "high" and note.module == "agents"
        assert await _actions(db, view["id"]) == [
            ("hiring.request_submitted", "agent"), ("hiring.policy_evaluated", "agent")]
        # It is in the existing approval queue.
        pending = await _call(h, "GET", f"/api/v1/companies/{h['acme']}/approvals/pending")
        assert [a["id"] for a in pending.json()] == [view["id"]]
        assert pending.json()[0]["required_signatures"] == 1

    async def test_auto_approval_needs_an_explicit_bounded_rule(self, db, h):  # noqa: F811
        await _allow(db, h)
        await _policy(db, h, auto_approve={"enabled": True})  # unbounded: not enough
        assert (await _hire(h, key="a")).json()["status"] == "approval_required"
        assert await _employees(db, h) == []

    async def test_auto_approval_hires_one_employee_under_the_manager(self, db, h):  # noqa: F811
        await _allow(db, h)
        await _policy(db, h, **AUTO)
        r = await _hire(h, model="sonnet")
        view = r.json()
        assert (r.status_code, view["status"]) == (201, "hired"), r.text
        [policy] = await _rows(db, Policy, Policy.company_id == h["acme"])
        assert view["decided_by"] == f"policy:{policy.id}:v1:hiring.auto_approve"
        [agent] = await _employees(db, h)
        assert agent.id == hiring_service.employee_id_for(uuid.UUID(view["id"]))
        assert view["employee"]["id"] == str(agent.id)
        assert agent.manager_id == h["lead"] and agent.status == "idle"
        assert agent.adapter_type == "cli" and agent.model == "sonnet"
        assert agent.adapter_config["backend"] == "claude"
        assert "/opt/bin" not in str(agent.adapter_config)
        assert agent.budget_monthly_cents == 700
        assert await _actions(db, view["id"]) == [
            ("hiring.request_submitted", "agent"), ("hiring.policy_evaluated", "agent"),
            ("hiring.auto_approved", "system"), ("hiring.employee_created", "system")]
        created = await _rows(db, AuditLog, AuditLog.action == "agent.created",
                              AuditLog.resource_id == str(agent.id))
        assert created[0].details["hiring_request_id"] == view["id"]
        # A retry returns the same request and employee.
        again = await _hire(h, model="sonnet")
        assert (again.status_code, again.json()["employee"]["id"]) == (200, str(agent.id))
        assert len(await _employees(db, h)) == 1
        # Above the auto-approval bound: a human decides.
        big = await _hire(h, key="big", estimated_monthly_cents=5001)
        assert big.json()["status"] == "approval_required"

    async def test_under_a_ceo_the_hire_reports_to_its_manager(self, db, h):  # noqa: F811
        async with db() as s:
            await ceo_service.appoint(s, h["acme"], h["bo"], _me(h["acme"]))
        await _allow(db, h)
        await _policy(db, h, **AUTO)
        assert (await _hire(h)).json()["status"] == "hired"
        [agent] = await _employees(db, h)
        assert agent.manager_id == h["lead"]
        roots = await _rows(db, Agent, Agent.company_id == h["acme"], Agent.manager_id.is_(None),
                            Agent.status != "terminated")
        assert [a.id for a in roots] == [h["bo"]]

    @pytest.mark.parametrize(("rules", "body", "code"), [
        ({}, {"backend": "nope"}, "CLI_BACKEND_UNKNOWN"),
        ({}, {"backend": "gemini"}, "CLI_BACKEND_UNAVAILABLE"),
        ({}, {"backend": "freebuff"}, "CLI_BACKEND_NOT_EXECUTABLE"),
        ({"allowed_roles": ["designer"]}, {}, "ROLE_NOT_ALLOWED"),
        ({"allowed_backends": ["codex"]}, {}, "BACKEND_NOT_ALLOWED"),
        ({"allowed_models": ["haiku"]}, {"model": "opus"}, "MODEL_NOT_ALLOWED"),
        ({"max_recurring_monthly_cents": 699}, {}, "RECURRING_BUDGET_EXCEEDED"),
        ({"hiring_budget_monthly_cents": 499}, {}, "HIRING_BUDGET_EXCEEDED"),
        # acme: claude, agy, api, Lead, Bo, claude2.
        ({"max_headcount": 6}, {}, "HEADCOUNT_LIMIT"),
        ({"max_direct_reports": 0}, {}, "DIRECT_REPORTS_LIMIT"),
    ])
    async def test_rejections(self, db, h, rules, body, code):  # noqa: F811
        await _allow(db, h)
        await _policy(db, h, **AUTO, **rules)
        view = (await _hire(h, **body)).json()
        assert view["status"] == "rejected", view
        assert code in [r["code"] for r in view["policy_reasons"]]
        assert view["rejection_reason"]
        assert await _employees(db, h) == []
        assert ("hiring.rejected", "system") in await _actions(db, view["id"])

    async def test_company_budget_is_the_default_recurring_cap(self, db, h):  # noqa: F811
        from nexus.models.company import Company

        await _allow(db, h)
        async with db() as s:
            (await s.get(Company, h["acme"])).budget_monthly_cents = 600
            await s.commit()
        view = (await _hire(h)).json()
        assert [r["code"] for r in view["policy_reasons"]] == ["RECURRING_BUDGET_EXCEEDED"]

    async def test_manager_needs_the_tool_policy(self, db, h):  # noqa: F811
        view = (await _hire(h)).json()
        assert view["status"] == "rejected"
        assert [r["code"] for r in view["policy_reasons"]] == ["TOOL_POLICY_DENIED"]

    async def test_request_text_cannot_set_server_fields(self, db, h):  # noqa: F811
        await _allow(db, h)
        for extra in ({"company_id": str(h["other"])}, {"status": "approved"},
                      {"manager_id": str(h["bo"])}, {"adapter_config": {"path": "/bin/sh"}}):
            r = await _call(h, "POST", f"/api/v1/agents/{h['lead']}/hiring-requests",
                            {**_body(), **extra}, "lead_run")
            assert r.status_code == 422, extra
        # The generic approval route cannot file one either.
        r = await _call(h, "POST", f"/api/v1/companies/{h['acme']}/approvals",
                        {"type": "hire_employee", "requested_by_agent_id": str(h["lead"]),
                         "payload": {"request": _body()}})
        assert r.status_code == 422
        assert await _rows(db, Approval, Approval.company_id == h["acme"]) == []

    async def test_idempotent_submission(self, db, h):  # noqa: F811
        await _allow(db, h)
        first, again = await _hire(h), await _hire(h)
        assert (first.status_code, again.status_code) == (201, 200)
        assert first.json()["id"] == again.json()["id"]
        clash = await _hire(h, title="Other")
        assert clash.status_code == 409
        assert clash.json()["detail"]["code"] == "IDEMPOTENCY_KEY_REUSED"
        # Keys are per manager: Bo's "k1" is Bo's own request.
        bo = await _hire(h, manager="bo", who="bo_run")
        assert bo.status_code == 201 and bo.json()["id"] != first.json()["id"]
        assert len(await _rows(db, Approval, Approval.type == "hire_employee")) == 2


class TestApproval:
    async def _pending(self, db, h, **body):  # noqa: F811
        view = (await _hire(h, **body)).json()
        assert view["status"] == "approval_required", view
        return view["id"]

    async def test_human_approves_once_and_agents_cannot(self, db, h):  # noqa: F811
        await _allow(db, h)
        rid = await self._pending(db, h)
        path = f"/api/v1/approvals/{rid}/approve"
        for who, code in (("lead_run", 403), ("bo_run", 403), ("viewer", 403), ("outsider", 404)):
            r = await _call(h, "POST", path, {"decision_note": "ok"}, who)
            assert r.status_code == code, (who, r.text)
        assert await _employees(db, h) == []
        ok = await _call(h, "POST", path, {"decision_note": "welcome"})
        assert (ok.status_code, ok.json()["status"]) == (200, "approved"), ok.text
        [agent] = await _employees(db, h)
        assert agent.manager_id == h["lead"]
        again = await _call(h, "POST", path, {})
        assert again.status_code == 200 and len(await _employees(db, h)) == 1
        late = await _call(h, "POST", f"/api/v1/approvals/{rid}/reject", {"decision_note": "no"})
        assert late.status_code == 409
        view = (await _call(h, "GET", f"/api/v1/agents/{h['lead']}/hiring-requests/{rid}")).json()
        assert view["status"] == "hired" and view["decided_by"] == "lead@example.test"
        assert await _actions(db, rid) == [
            ("hiring.request_submitted", "agent"), ("hiring.policy_evaluated", "agent"),
            ("hiring.policy_evaluated", "user"), ("hiring.approved", "user"),
            ("hiring.employee_created", "user")]

    async def test_human_rejects_with_a_reason(self, db, h):  # noqa: F811
        await _allow(db, h)
        rid = await self._pending(db, h)
        path = f"/api/v1/approvals/{rid}/reject"
        assert (await _call(h, "POST", path, {"decision_note": "  "})).status_code == 422
        as_agent = await _call(h, "POST", path, {"decision_note": "no"}, "lead_run")
        assert as_agent.status_code == 403
        r = await _call(h, "POST", path, {"decision_note": "Not this quarter"})
        assert (r.status_code, r.json()["status"]) == (200, "rejected")
        assert (await _call(h, "POST", path, {"decision_note": "again"})).status_code == 200
        approve = await _call(h, "POST", f"/api/v1/approvals/{rid}/approve", {})
        assert approve.status_code == 409
        view = (await _call(h, "GET", f"/api/v1/agents/{h['lead']}/hiring-requests")).json()[0]
        assert (view["status"], view["rejection_reason"]) == ("rejected", "Not this quarter")
        assert await _employees(db, h) == []
        assert ("hiring.rejected", "user") in await _actions(db, rid)

    async def test_approval_re_evaluates_policy_and_budget(self, db, h):  # noqa: F811
        await _allow(db, h)
        first = await self._pending(db, h, key="a")
        second = await self._pending(db, h, key="b")
        # Room for one more 700/month hire after the policy tightens.
        await _policy(db, h, max_recurring_monthly_cents=700)
        ok = await _call(h, "POST", f"/api/v1/approvals/{first}/approve", {})
        assert ok.status_code == 200, ok.text
        r = await _call(h, "POST", f"/api/v1/approvals/{second}/approve", {})
        assert r.status_code == 409
        assert r.json()["detail"]["code"] == "HIRING_POLICY_REJECTED"
        assert [x["code"] for x in r.json()["detail"]["reasons"]] == ["RECURRING_BUDGET_EXCEEDED"]
        [approval] = await _rows(db, Approval, Approval.id == uuid.UUID(second))
        assert approval.status == "pending"
        assert len(await _employees(db, h)) == 1
        assert ("hiring.policy_evaluated", "user") in await _actions(db, second)

    async def test_concurrent_approvals_create_one_employee(self, db, h):  # noqa: F811
        await _allow(db, h)
        rid = uuid.UUID(await self._pending(db, h))

        async def approve():
            async with db() as s:
                admin = h["principals"]["admin"]
                result = await hiring_service.approve(s, h["acme"], rid, admin, None)
                await s.commit()
                return result.status

        assert await asyncio.gather(approve(), approve(), approve()) == ["approved"] * 3
        assert len(await _employees(db, h)) == 1
        created = [a for a in await _actions(db, rid) if a[0] == "hiring.employee_created"]
        assert len(created) == 1

    async def test_concurrent_approvals_respect_the_budget(self, db, h):  # noqa: F811
        await _allow(db, h)
        ids = [uuid.UUID(await self._pending(db, h, key=k)) for k in ("a", "b")]
        await _policy(db, h, max_recurring_monthly_cents=700)

        async def approve(rid):
            async with db() as s:
                try:
                    await hiring_service.approve(s, h["acme"], rid, h["principals"]["admin"], None)
                    await s.commit()
                    return "approved"
                except Exception as exc:  # noqa: BLE001
                    return exc.detail["code"]

        results = await asyncio.gather(*(approve(r) for r in ids))
        assert sorted(results) == ["HIRING_POLICY_REJECTED", "approved"]
        assert len(await _employees(db, h)) == 1

    async def test_configuration_required_only_when_asked(self, db, h):  # noqa: F811
        await _allow(db, h)
        await _policy(db, h, **AUTO)
        view = (await _hire(h, backend="gemini", allow_configuration_required=True)).json()
        # Never auto-approved: a human confirms the setup work.
        assert view["status"] == "approval_required"
        assert [r["code"] for r in view["policy_reasons"]] == ["CONFIGURATION_REQUIRED"]
        ok = await _call(h, "POST", f"/api/v1/approvals/{view['id']}/approve", {})
        assert ok.status_code == 200, ok.text
        [agent] = await _employees(db, h)
        assert agent.status == "configuration_required"
        assert agent.adapter_config["backend"] == "gemini"


class TestTenancyAndTools:
    async def test_cross_tenant_access_is_not_found(self, db, h):  # noqa: F811
        await _allow(db, h)
        rid = (await _hire(h)).json()["id"]
        base = f"/api/v1/agents/{h['lead']}/hiring-requests"
        assert (await _call(h, "GET", base, who="outsider")).status_code == 404
        assert (await _call(h, "GET", f"{base}/{rid}", who="outsider")).status_code == 404
        r = await _call(h, "POST", base, _body(key="x"), "outsider")
        assert r.status_code == 404
        # An agent acts only as itself; another manager does not see Lead's request.
        assert (await _call(h, "POST", base, _body(key="y"), "bo_run")).status_code == 403
        bo = f"/api/v1/agents/{h['bo']}/hiring-requests/{rid}"
        assert (await _call(h, "GET", bo, who="bo_run")).status_code == 404
        # The other tenant's manager cannot be hired for from acme.
        other = f"/api/v1/agents/{h['other_lead']}/hiring-requests"
        assert (await _call(h, "POST", other, _body(key="z"))).status_code == 404
        assert len(await _rows(db, Approval, Approval.type == "hire_employee")) == 1

    async def test_claude_manager_mcp_tools(self, db, h):  # noqa: F811
        server = MCPServer(_ctx(h["acme"], h["bo"]))
        # Write-risk: not offered, and refused, without an explicit ToolPolicy.
        assert "manager_request_hire" not in {t["name"] for t in await server.list_tools()}
        refused = await server.call_tool("manager_request_hire", _body())
        assert refused["isError"] and "Denied by access policy" in refused["content"][0]["text"]
        await _allow(db, h, *HIRING_TOOLS)
        tools = {t["name"]: t for t in await server.list_tools()}
        assert set(HIRING_TOOLS) <= set(tools)
        schema = tools["manager_request_hire"]["inputSchema"]
        assert schema["additionalProperties"] is False and "idempotency_key" in schema["required"]
        bad = await server.call_tool("manager_request_hire", {**_body(), "manager_id": "x"})
        assert bad["isError"] and "invalid arguments" in bad["content"][0]["text"]

        created = _payload(await server.call_tool("manager_request_hire", _body()))
        assert created["created"] is True and created["status"] == "approval_required"
        assert created["manager_id"] == str(h["bo"])
        again = _payload(await server.call_tool("manager_request_hire", _body()))
        assert (again["created"], again["id"]) == (False, created["id"])
        listed = _payload(await server.call_tool("manager_list_hiring_requests", {}))
        assert [r["id"] for r in listed] == [created["id"]]
        one = _payload(await server.call_tool(
            "manager_get_hiring_request", {"request_id": created["id"]}))
        assert one["request"]["title"] == "Backend Engineer"
        # Another manager's request is not found.
        lead = (await _hire(h, key="lead")).json()["id"]
        refused = await server.call_tool("manager_get_hiring_request", {"request_id": lead})
        assert refused["isError"] and "HIRING_REQUEST_NOT_FOUND" in refused["content"][0]["text"]
        # No tool creates an agent directly.
        assert not any("create" in name for name in tools)


def _codes(view):
    return [r["code"] for r in view["policy_reasons"]]


class TestAuthorization:
    """Hiring is permitted only by an allow ToolPolicy naming the tool itself."""

    async def test_a_default_allow_profile_does_not_permit_hiring(self, db, h):  # noqa: F811
        profile = ToolProfile(company_id=h["acme"], name="open", default_action="allow")
        await _add(db, profile)
        await _add(db, ToolProfileBinding(company_id=h["acme"], profile_id=profile.id,
                                          target_type="company", target_id=h["acme"]))
        assert _codes((await _hire(h)).json()) == ["TOOL_POLICY_DENIED"]
        # Unrelated tools keep the profile's default.
        names = {t["name"] for t in await MCPServer(_ctx(h["acme"], h["bo"])).list_tools()}
        assert "manager_list_reports" in names and "manager_request_hire" not in names

    @pytest.mark.parametrize("conditions", [
        {}, {"tool_name": ["*"]}, {"tool_name": ["manager_*"]}, {"tool_name": "manager_request_*"},
        {"risk_level": ["write"]}, {"agent_id": "LEAD"},
    ])
    async def test_a_general_allow_does_not_permit_hiring(self, db, h, conditions):  # noqa: F811
        if conditions.get("agent_id") == "LEAD":
            conditions = {"agent_id": [str(h["lead"])]}
        await _add(db, ToolPolicy(company_id=h["acme"], name="broad", effect="allow",
                                  conditions=conditions))
        assert _codes((await _hire(h)).json()) == ["TOOL_POLICY_DENIED"]

    async def test_a_named_allow_permits_hiring(self, db, h):  # noqa: F811
        await _add(db, ToolPolicy(company_id=h["acme"], name="hire", effect="allow",
                                  conditions={"tool_name": "manager_request_hire",
                                              "agent_id": [str(h["lead"])]}))
        assert (await _hire(h)).json()["status"] == "approval_required"
        # Pinned to Lead: Bo is not authorized by it.
        assert _codes((await _hire(h, manager="bo", who="bo_run")).json()) == [
            "TOOL_POLICY_DENIED"]

    @pytest.mark.parametrize("deny_priority", [-10, 10])
    @pytest.mark.parametrize("deny", [
        {"tool_name": ["manager_request_hire"]}, {"tool_name": ["manager_*"]},
        {"risk_level": ["write"]},
    ])
    async def test_an_explicit_deny_wins(self, db, h, deny, deny_priority):  # noqa: F811
        await _add(db, ToolPolicy(company_id=h["acme"], name="hire", effect="allow", priority=0,
                                  conditions={"tool_name": ["manager_request_hire"]}),
                   ToolPolicy(company_id=h["acme"], name="no", effect="deny",
                              priority=deny_priority, conditions=deny))
        assert _codes((await _hire(h)).json()) == ["TOOL_POLICY_DENIED"]


OPEN = {"auto_approve": {"enabled": True, "max_monthly_cents": 100_000,
                         "max_one_time_cents": 100_000}}


class TestQuorum:
    """A hire's amount is its first-year commitment; the existing quorum applies."""

    @pytest.mark.parametrize(("monthly", "once", "amount", "quorum"), [
        (0, 9_999, 9_999, 1), (0, 10_000, 10_000, 2), (0, 10_001, 10_001, 2),  # one-time only
        (833, 0, 9_996, 1), (834, 0, 10_008, 2),  # recurring only
        (700, 500, 8_900, 1), (800, 400, 10_000, 2),  # both
    ])
    async def test_amount_and_quorum(self, db, h, monthly, once, amount, quorum):  # noqa: F811
        await _allow(db, h)
        await _policy(db, h, **OPEN)
        view = (await _hire(h, estimated_monthly_cents=monthly,
                            estimated_one_time_cents=once)).json()
        assert (view["amount_cents"], view["required_signatures"]) == (amount, quorum)
        [row] = await _rows(db, Approval, Approval.id == uuid.UUID(view["id"]))
        assert (row.payload["amount_cents"], row.required_signatures) == (amount, quorum)
        assert row.payload["request"]["estimated_monthly_cents"] == monthly
        assert row.payload["request"]["estimated_one_time_cents"] == once
        if quorum == 1:
            # Auto-approved: the amount and the deciding rule stay on the request.
            assert view["status"] == "hired"
            assert row.payload["policy"]["rule"].endswith(":hiring.auto_approve")
        else:
            # Policy never stands in for a quorum.
            assert view["status"] == "approval_required"
            assert _codes(view) == ["SIGNATURE_QUORUM_REQUIRED"]
            assert await _employees(db, h) == []

    async def test_no_employee_until_the_quorum_is_met_then_exactly_one(self, db, h):  # noqa: F811
        await _allow(db, h)
        await _policy(db, h, **OPEN)
        view = (await _hire(h, estimated_monthly_cents=0, estimated_one_time_cents=10_000)).json()
        rid = uuid.UUID(view["id"])
        signers = {}
        for subject in ("alice", "bob"):
            signers[subject], public = _keypair()
            await _add(db, ApprovalSignerKey(company_id=h["acme"], subject=subject,
                                             public_key=public))

        async def sign(subject):
            async with db() as s:
                approval = await s.get(Approval, rid)
                signature = _sign(signers[subject], approval)
                await ApprovalService(s).add_signature(rid, subject, signature)
                await s.commit()

        for signer in (None, "alice"):
            if signer:
                await sign(signer)
            r = await _call(h, "POST", f"/api/v1/approvals/{rid}/approve", {})
            assert r.status_code == 409 and r.json()["detail"]["code"] == "APPROVAL_QUORUM_NOT_MET"
            assert await _employees(db, h) == []
            [row] = await _rows(db, Approval, Approval.id == rid)
            assert row.status == "pending"
        await sign("bob")

        async def approve():
            async with db() as s:
                admin = h["principals"]["admin"]
                result = await hiring_service.approve(s, h["acme"], rid, admin, None)
                await s.commit()
                return result.status

        assert await asyncio.gather(approve(), approve(), approve()) == ["approved"] * 3
        assert len(await _employees(db, h)) == 1
        created = [a for a in await _actions(db, rid) if a[0] == "hiring.employee_created"]
        assert len(created) == 1

    async def test_a_tampered_amount_is_refused(self, db, h):  # noqa: F811
        await _allow(db, h)
        view = (await _hire(h, estimated_monthly_cents=0, estimated_one_time_cents=50_000)).json()
        rid = uuid.UUID(view["id"])
        async with db() as s:
            row = await s.get(Approval, rid)
            row.payload = {**row.payload, "amount_cents": 1}
            row.required_signatures = 1
            await s.commit()
        r = await _call(h, "POST", f"/api/v1/approvals/{rid}/approve", {})
        assert r.status_code == 409 and r.json()["detail"]["code"] == "HIRING_AMOUNT_MISMATCH"
        assert await _employees(db, h) == []

    def test_commitment_is_one_time_plus_twelve_months(self):
        most = hiring_service.HireRequest(**_body(estimated_monthly_cents=100_000_000,
                                                  estimated_one_time_cents=100_000_000))
        assert hiring_service.commitment_cents(most) == 1_300_000_000
        assert hiring_service.commitment_cents(most) <= hiring_service.MAX_COMMITMENT_CENTS
        for bad in ({"estimated_monthly_cents": -1}, {"estimated_one_time_cents": 100_000_001}):
            with pytest.raises(ValueError):
                hiring_service.HireRequest(**_body(**bad))


class TestRetry:
    async def test_failed_materialization_retries_and_releases_capacity(  # noqa: F811
        self, db, h, monkeypatch  # noqa: F811
    ):
        await _allow(db, h)
        rid = uuid.UUID((await _hire(h)).json()["id"])
        real, calls = hiring_service.normalize_cli_employee, []

        def flaky(*args, **kwargs):
            calls.append(1)
            if len(calls) == 2:  # approval's re-evaluation passes; materialization fails once
                raise hiring_service._error(503, "CLI_REGISTRY_BUSY", "Registry busy")
            return real(*args, **kwargs)

        monkeypatch.setattr(hiring_service, "normalize_cli_employee", flaky)
        path = f"/api/v1/approvals/{rid}/approve"
        failed = await _call(h, "POST", path, {})
        assert failed.json()["detail"]["code"] == "HIRING_MATERIALIZATION_FAILED"
        assert await _employees(db, h) == []
        async with db() as s:
            # Approved, not yet materialized: its capacity stays reserved.
            assert len(await hiring_service._committed(s, h["acme"], None)) == 1
        ok = await _call(h, "POST", path, {})
        assert ok.status_code == 200, ok.text
        [agent] = await _employees(db, h)
        async with db() as s:
            assert await hiring_service._committed(s, h["acme"], None) == []
        actions = [a for a, _ in await _actions(db, rid)]
        assert actions[-2:] == ["hiring.materialization_failed", "hiring.employee_created"]
        # Counted once, by the employee: there is room for exactly one more.
        await _policy(db, h, max_recurring_monthly_cents=2 * agent.budget_monthly_cents)
        assert (await _hire(h, key="next")).json()["status"] == "approval_required"
