"""Who may change an agent, and which fields they may change.

Every non-GET route in ``nexus.api.routes.agents`` goes through the real router. People come in
through the real cookie resolver (active flag and membership are re-read from the database on
every request); the principals the resolver never builds from a cookie (API key, labelled
worker, run token, unknown kind) are injected in front of the same routes.

Authority fields (role, status, adapter, model, capabilities, budget, autonomy) belong to a human
company administrator. The refusal leaves the agent row identical and writes no audit row.
"""

# ruff: noqa: F811  (pytest fixtures are imported, then named as test parameters)

from __future__ import annotations

import types
import uuid

import httpx
import pytest
from fastapi import FastAPI, Request
from sqlalchemy import delete

from nexus.api.routes import agents as agent_routes
from nexus.api.routes import goals as goal_routes
from nexus.auth.middleware import AuthenticationMiddleware
from nexus.auth.principal import Principal
from nexus.auth.sessions import create_session
from nexus.auth.users import create_user
from nexus.models.agent import Agent
from nexus.models.company import CompanyMembership
from nexus.models.governance import AuditLog
from nexus.models.governance_studio import GovernanceRestriction
from nexus.models.user_profile import UserProfile
from nexus.services import ceo_service
from tests.test_employee_work import _rows, db, w  # noqa: F401 -- fixtures
from tests.test_work_service import _get, co  # noqa: F401 -- fixtures, helpers

pytestmark = pytest.mark.employee_work


@pytest.fixture
async def route_world(co):
    """The agent and goal routers behind real cookie sessions plus synthetic principals."""
    factory = co["db"]
    tokens: dict[str, str] = {}
    ids: dict[str, uuid.UUID] = {}
    async with factory() as s:
        for name, company, role in (
            ("admin", co["acme"], "admin"),
            ("manager", co["acme"], "manager"),
            ("employee", co["acme"], "agent"),
            ("viewer", co["acme"], "viewer"),
            ("inactive", co["acme"], "admin"),
            ("removed", co["acme"], "admin"),
            ("outsider", co["other"], "admin"),
        ):
            user = await create_user(
                s, email=f"{name}@example.com", password="x" * 14, company_id=company, role=role
            )
            ids[name] = user.id
            tokens[name], _ = await create_session(s, user_id=user.id, company_id=company)
        await s.commit()

    synthetic = {
        "guest": Principal(kind="user", company_id=co["acme"], role="guest", user_id=uuid.uuid4()),
        "api_key": Principal(
            kind="service", company_id=co["acme"], role="admin", api_key_id=uuid.uuid4()
        ),
        "worker": Principal(kind="service", company_id=co["acme"], role="admin", label="worker"),
        "service_viewer": Principal(
            kind="service", company_id=co["acme"], role="viewer", api_key_id=uuid.uuid4()
        ),
        "service_agent": Principal(
            kind="service", company_id=co["acme"], role="agent", api_key_id=uuid.uuid4()
        ),
        "run": Principal(
            kind="run",
            company_id=co["acme"],
            role="agent",
            run_id=uuid.uuid4(),
            agent_id=co["acme_eve"],
        ),
        "run_other": Principal(
            kind="run",
            company_id=co["acme"],
            role="agent",
            run_id=uuid.uuid4(),
            agent_id=co["acme_zed"],
        ),
        "unknown": Principal(
            kind="tool",  # type: ignore[arg-type]
            company_id=co["acme"],
            role="admin",
            user_id=uuid.uuid4(),
        ),
        "dev": Principal(kind="service", company_id=co["acme"], role="admin"),
    }
    resolver = AuthenticationMiddleware(None)  # type: ignore[arg-type]
    app = FastAPI()
    app.include_router(agent_routes.router)
    app.include_router(goal_routes.router)

    @app.middleware("http")
    async def authenticate(request: Request, call_next):
        who = request.headers.get("x-test-principal")
        if who:
            request.state.principal = synthetic[who]
        else:
            token = request.cookies.get("nv_session", "")
            async with factory() as s:
                found = await resolver._principal_from_cookie(s, token) if token else None
                await s.commit()
            if found is not None:
                request.state.principal = found
        return await call_next(request)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:

        async def call(method, path, who="admin", body=None):
            client.cookies.clear()
            headers = {}
            if who in tokens:
                client.cookies.set("nv_session", tokens[who])
            else:
                headers["x-test-principal"] = who
            return await client.request(method, path, json=body, headers=headers)

        async def deactivate(name):
            async with factory() as s:
                (await s.get(UserProfile, ids[name])).is_active = False
                await s.commit()

        async def remove_membership(name):
            async with factory() as s:
                await s.execute(
                    delete(CompanyMembership).where(CompanyMembership.user_id == ids[name])
                )
                await s.commit()

        call.deactivate = deactivate
        call.remove_membership = remove_membership
        call.app = app
        yield call


async def _audit(co, *actions):
    rows = await _rows(co["db"], AuditLog)
    return [r for r in rows if r.action in actions]


def _snapshot(row):
    return {k: v for k, v in row.model_dump().items()}


async def _agent_state(co, agent_id):
    return _snapshot(await _get(co, Agent, agent_id))


UPDATE_ROUTES = (
    ("PUT", "/api/v1/agents/{agent}"),
    ("PATCH", "/api/v1/agents/{agent}"),
    ("PATCH", "/api/v1/companies/{company}/agents/{agent}"),
)

# One value per authority field that differs from what the seeded agent holds.
AUTHORITY_VALUES = {
    "role": "auditor",
    "status": "paused",
    "adapter_type": "anthropic",
    "model": "gpt-y",
    "capabilities": ["deploy"],
    "budget_monthly_cents": 99_999_999,
    "autonomy_policy": {"spend": 1, "delete": 1, "execute_code": 1},
}
PROFILE_VALUES = {"name": "Renamed", "title": "Analyst II"}
DENIED = ("employee", "viewer", "guest", "api_key", "worker", "run", "unknown")
INVALID_SESSION = ("inactive", "removed")


def _path(template, co, agent):
    return template.format(company=co["acme"], agent=agent)


class TestPrincipalMatrix:
    @pytest.mark.parametrize("method,template", UPDATE_ROUTES)
    @pytest.mark.parametrize("who", DENIED)
    async def test_unauthorised_callers_change_nothing(
        self, who, method, template, co, route_world
    ):
        target = co["acme_eve"]
        before = await _agent_state(co, target)
        audits = len(await _rows(co["db"], AuditLog))
        for field, value in {**AUTHORITY_VALUES, **PROFILE_VALUES}.items():
            res = await route_world(method, _path(template, co, target), who, {field: value})
            assert res.status_code == 403, (who, field, res.text)
        res = await route_world(method, _path(template, co, target), who, AUTHORITY_VALUES)
        assert res.status_code == 403
        assert await _agent_state(co, target) == before
        assert len(await _rows(co["db"], AuditLog)) == audits

    @pytest.mark.parametrize("method,template", UPDATE_ROUTES)
    @pytest.mark.parametrize("who", ("run", "run_other"))
    async def test_a_run_token_cannot_elevate_itself_or_anyone(
        self, who, method, template, co, route_world
    ):
        for target in (co["acme_eve"], co["acme_zed"], co["acme_lead"]):
            before = await _agent_state(co, target)
            res = await route_world(
                method, _path(template, co, target), who, {"autonomy_policy": {"spend": 1}}
            )
            assert res.status_code == 403
            assert await _agent_state(co, target) == before

    @pytest.mark.parametrize("method,template", UPDATE_ROUTES)
    @pytest.mark.parametrize("who", INVALID_SESSION)
    async def test_inactive_user_and_removed_membership_are_refused(
        self, who, method, template, co, route_world
    ):
        target = co["acme_eve"]
        before = await _agent_state(co, target)
        body = {"budget_monthly_cents": 5}
        res = await route_world(method, _path(template, co, target), who, body)
        assert res.status_code == 200
        await route_world(method, _path(template, co, target), "admin", {"budget_monthly_cents": 0})
        await (route_world.deactivate if who == "inactive" else route_world.remove_membership)(who)
        res = await route_world(method, _path(template, co, target), who, body)
        assert res.status_code == 401
        assert (await _agent_state(co, target))["budget_monthly_cents"] == 0
        assert before["role"] == (await _agent_state(co, target))["role"]

    @pytest.mark.parametrize("method,template", UPDATE_ROUTES)
    @pytest.mark.parametrize("field", sorted(AUTHORITY_VALUES))
    async def test_a_manager_cannot_change_authority_but_an_admin_can(
        self, field, method, template, co, route_world
    ):
        target = co["acme_eve"]
        before = await _agent_state(co, target)
        value = AUTHORITY_VALUES[field]
        res = await route_world(method, _path(template, co, target), "manager", {field: value})
        assert res.status_code == 403 and res.json()["detail"]["code"] == "HUMAN_ADMIN_REQUIRED"
        assert await _agent_state(co, target) == before
        assert not await _audit(co, "agent.updated")

        res = await route_world(method, _path(template, co, target), "admin", {field: value})
        assert res.status_code == 200, res.text
        assert (await _get(co, Agent, target)).model_dump()[field] == value
        [audit] = await _audit(co, "agent.updated")
        assert audit.details == {"fields": [field]} and audit.actor_type == "user"

    @pytest.mark.parametrize("method,template", UPDATE_ROUTES)
    async def test_a_manager_may_edit_profile_fields(self, method, template, co, route_world):
        target = co["acme_eve"]
        res = await route_world(method, _path(template, co, target), "manager", PROFILE_VALUES)
        assert res.status_code == 200, res.text
        row = await _get(co, Agent, target)
        assert (row.name, row.title) == ("Renamed", "Analyst II")
        assert (row.role, row.budget_monthly_cents) == ("analyst", 0)

    async def test_the_keyless_development_operator_is_the_administrator(
        self, co, route_world, monkeypatch
    ):
        target = co["acme_eve"]
        monkeypatch.setattr(ceo_service, "settings", types.SimpleNamespace(auth_bypass_active=True))
        res = await route_world(
            "PATCH", f"/api/v1/agents/{target}", "dev", {"budget_monthly_cents": 7}
        )
        assert res.status_code == 200
        monkeypatch.setattr(
            ceo_service, "settings", types.SimpleNamespace(auth_bypass_active=False)
        )
        res = await route_world(
            "PATCH", f"/api/v1/agents/{target}", "dev", {"budget_monthly_cents": 8}
        )
        assert res.status_code == 403
        assert (await _get(co, Agent, target)).budget_monthly_cents == 7


class TestUnknownFields:
    FORBIDDEN_FIELDS = {
        "manager_id": lambda co: str(co["acme_ceo"]),
        "is_ceo": lambda co: True,
        "company_id": lambda co: str(co["other"]),
        "department_id": lambda co: str(uuid.uuid4()),
        "team_id": lambda co: str(uuid.uuid4()),
        "permissions": lambda co: {"*": ["*"]},
        "tools": lambda co: ["shell"],
        "connection_id": lambda co: str(uuid.uuid4()),
        "runtime_config": lambda co: {"x": 1},
        "id": lambda co: str(uuid.uuid4()),
        "spent_monthly_cents": lambda co: 0,
    }

    @pytest.mark.parametrize("method,template", UPDATE_ROUTES)
    @pytest.mark.parametrize("field", sorted(FORBIDDEN_FIELDS))
    async def test_identity_and_organisation_fields_are_a_422(
        self, field, method, template, co, route_world
    ):
        target = co["acme_eve"]
        before = await _agent_state(co, target)
        body = {"title": "ok", field: self.FORBIDDEN_FIELDS[field](co)}
        res = await route_world(method, _path(template, co, target), "admin", body)
        assert res.status_code == 422, (field, res.text)
        assert await _agent_state(co, target) == before
        assert not await _audit(co, "agent.updated")
        # An unauthorised caller is stopped before the body is even read.
        res = await route_world(method, _path(template, co, target), "viewer", body)
        assert res.status_code == 403

    @pytest.mark.parametrize("method,template", UPDATE_ROUTES)
    async def test_a_field_that_cannot_be_null_or_negative_is_refused(
        self, method, template, co, route_world
    ):
        target = co["acme_eve"]
        before = await _agent_state(co, target)
        for body in ({"role": None}, {"status": None}, {"budget_monthly_cents": -1}):
            res = await route_world(method, _path(template, co, target), "admin", body)
            assert res.status_code == 422, (body, res.text)
        assert await _agent_state(co, target) == before


class TestTenancy:
    async def test_foreign_and_missing_agents_are_the_same_404(self, co, route_world):
        for method, template in UPDATE_ROUTES:
            answers = []
            for agent in (co["other_eve"], uuid.uuid4()):
                res = await route_world(method, _path(template, co, agent), "admin", {"title": "x"})
                answers.append((res.status_code, res.text.replace(str(agent), "<id>")))
            assert answers[0] == answers[1] and answers[0][0] == 404, (method, template)
        assert (await _get(co, Agent, co["other_eve"])).title is None

    @pytest.mark.parametrize("method,template", UPDATE_ROUTES)
    async def test_a_foreign_admin_changes_nothing(self, method, template, co, route_world):
        target = co["acme_eve"]
        before = await _agent_state(co, target)
        res = await route_world(
            method, _path(template, co, target), "outsider", {"budget_monthly_cents": 9}
        )
        assert res.status_code in (403, 404)
        assert await _agent_state(co, target) == before

    @pytest.mark.parametrize("who", ("admin", "outsider"))
    async def test_the_company_scoped_route_binds_the_path_company(self, who, co, route_world):
        target = co["other_eve"] if who == "admin" else co["acme_eve"]
        path_company = co["other"] if who == "admin" else co["acme"]
        before = await _agent_state(co, target)
        res = await route_world(
            "PATCH", f"/api/v1/companies/{path_company}/agents/{target}", who, {"title": "x"}
        )
        assert res.status_code == 403
        assert await _agent_state(co, target) == before


class TestLifecycleRoutes:
    async def test_create_requires_write_agent_and_binds_the_company(self, co, route_world):
        url = f"/api/v1/companies/{co['acme']}/agents"
        count = len(await _rows(co["db"], Agent))
        for who in ("viewer", "guest", "employee", "run", "unknown"):
            res = await route_world("POST", url, who, {"name": "N", "role": "analyst"})
            assert res.status_code == 403, who
        res = await route_world(
            "POST",
            f"/api/v1/companies/{co['other']}/agents",
            "admin",
            {"name": "N", "role": "analyst"},
        )
        assert res.status_code == 403
        assert len(await _rows(co["db"], Agent)) == count
        res = await route_world("POST", url, "manager", {"name": "N", "role": "analyst"})
        assert res.status_code == 201, res.text
        created = await _get(co, Agent, uuid.UUID(res.json()["id"]))
        assert created.company_id == co["acme"] and created.is_ceo is False
        assert created.manager_id == co["acme_ceo"]

    @pytest.mark.parametrize(
        "body",
        (
            {"role": "CEO"},
            {"role": "Engineering Manager"},
            {"role": "analyst", "autonomy_policy": {"spend": 1}},
            {"role": "analyst", "budget_monthly_cents": 100},
        ),
    )
    async def test_privileged_creates_need_a_human_administrator(self, body, co, route_world):
        url = f"/api/v1/companies/{co['acme']}/agents"
        count = len(await _rows(co["db"], Agent))
        for who in ("manager", "api_key", "worker"):
            res = await route_world("POST", url, who, {"name": "N", **body})
            assert res.status_code == 403, (who, res.text)
        assert len(await _rows(co["db"], Agent)) == count
        assert not await _audit(co, "agent.created")
        res = await route_world("POST", url, "admin", {"name": "N", **body})
        assert res.status_code == 201, res.text

    async def test_clone_is_for_human_administrators_and_copies_no_authority(self, co, route_world):
        source = co["acme_eve"]
        async with co["db"]() as s:
            row = await s.get(Agent, source)
            row.autonomy_policy = {"spend": 1}
            row.adapter_config = {
                "backend": "claude",
                "api_key": "sk-secret",
                "base_url": "http://x",
            }
            row.permissions = {"*": ["*"]}
            row.tools = ["shell"]
            row.runtime_config = {"k": 1}
            row.budget_monthly_cents = 500
            await s.commit()
        count = len(await _rows(co["db"], Agent))
        for who in ("manager", "viewer", "employee", "run", "api_key", "worker", "unknown"):
            res = await route_world("POST", f"/api/v1/agents/{source}/clone", who)
            assert res.status_code == 403, who
        assert len(await _rows(co["db"], Agent)) == count
        res = await route_world("POST", f"/api/v1/agents/{source}/clone", "admin")
        assert res.status_code == 201, res.text
        clone = await _get(co, Agent, uuid.UUID(res.json()["id"]))
        assert clone.autonomy_policy is None and clone.permissions is None and clone.tools is None
        assert clone.runtime_config is None and clone.connection_id is None
        assert clone.adapter_config == {"backend": "claude"}
        assert (clone.is_ceo, clone.status, clone.budget_monthly_cents) == (False, "idle", 500)
        assert (await _audit(co, "agent.cloned"))[0].details == {"source_agent_id": str(source)}
        res = await route_world("POST", f"/api/v1/agents/{co['other_eve']}/clone", "admin")
        assert res.status_code == 404

    async def test_pause_and_wake_need_write_agent(self, co, route_world):
        target = co["acme_eve"]
        for action in ("pause", "wake"):
            for who in ("viewer", "guest", "employee", "run", "unknown"):
                res = await route_world("POST", f"/api/v1/agents/{target}/{action}", who)
                assert res.status_code == 403, (action, who)
        assert (await _get(co, Agent, target)).status == "idle"
        res = await route_world("POST", f"/api/v1/agents/{target}/pause", "manager")
        assert res.status_code == 200 and res.json()["status"] == "paused"
        res = await route_world("POST", f"/api/v1/agents/{target}/wake", "manager")
        assert res.status_code == 200 and res.json()["status"] == "ready"
        assert [a.action for a in await _audit(co, "agent.paused", "agent.woken")] == [
            "agent.paused",
            "agent.woken",
        ]
        for who in ("viewer", "run"):
            res = await route_world("POST", f"/api/v1/agents/{co['other_eve']}/pause", who)
            assert res.status_code == 403
        res = await route_world("POST", f"/api/v1/agents/{co['other_eve']}/pause", "admin")
        assert res.status_code == 404

    @pytest.mark.parametrize("scope", ("agent", "company"))
    async def test_wake_respects_isolation_and_lockdown(self, scope, co, route_world):
        target = co["acme_eve"]
        await route_world("POST", f"/api/v1/agents/{target}/pause", "admin")
        async with co["db"]() as s:
            s.add(
                GovernanceRestriction(
                    company_id=co["acme"],
                    scope=scope,
                    agent_id=target if scope == "agent" else None,
                    kind="isolation" if scope == "agent" else "lockdown",
                    reason="test",
                    created_by="admin",
                )
            )
            await s.commit()
        for who in ("admin", "manager", "api_key"):
            res = await route_world("POST", f"/api/v1/agents/{target}/wake", who)
            assert res.status_code == 409, (who, res.text)
            assert res.json()["detail"]["code"] == "AGENT_RESTRICTED"
        assert (await _get(co, Agent, target)).status == "paused"
        assert not await _audit(co, "agent.woken")
        # An unrelated agent is not isolated by another agent's restriction.
        if scope == "agent":
            other = co["acme_zed"]
            res = await route_world("POST", f"/api/v1/agents/{other}/wake", "admin")
            assert res.status_code == 200
        # Pausing only removes capability, so it stays available.
        res = await route_world("POST", f"/api/v1/agents/{target}/pause", "admin")
        assert res.status_code == 200

    async def test_a_run_token_cannot_wake_itself_out_of_isolation(self, co, route_world):
        target = co["acme_eve"]
        await route_world("POST", f"/api/v1/agents/{target}/pause", "admin")
        res = await route_world("POST", f"/api/v1/agents/{target}/wake", "run")
        assert res.status_code == 403
        assert (await _get(co, Agent, target)).status == "paused"

    async def test_heartbeat_is_narrow(self, co, route_world):
        target = co["acme_eve"]
        before = await _agent_state(co, target)
        # Refused: another agent's token, a viewer, the unknown kind, a foreign admin.
        for who in ("run_other", "viewer", "guest", "unknown", "employee"):
            res = await route_world("POST", f"/api/v1/agents/{target}/heartbeat", who)
            assert res.status_code == 403, who
        assert await _agent_state(co, target) == before
        # Allowed: the agent itself, a manager, an administrator.
        for who in ("run", "manager", "admin"):
            res = await route_world("POST", f"/api/v1/agents/{target}/heartbeat", who)
            assert res.status_code == 200, (who, res.text)
        after = await _agent_state(co, target)
        changed = {k for k in before if before[k] != after[k]}
        assert changed == {"last_heartbeat_at"}
        # It writes the heartbeat only, whatever the caller sends.
        res = await route_world(
            "POST",
            f"/api/v1/agents/{target}/heartbeat",
            "run",
            {"role": "ceo", "budget_monthly_cents": 99, "status": "active"},
        )
        assert res.status_code == 200
        final = await _agent_state(co, target)
        assert {k for k in before if before[k] != final[k]} == {"last_heartbeat_at"}
        res = await route_world("POST", f"/api/v1/agents/{co['other_eve']}/heartbeat", "admin")
        assert res.status_code == 404

    async def test_delete_still_requires_write_agent(self, co, route_world):
        target = co["acme_zed"]
        for who in ("viewer", "guest", "employee", "run", "unknown"):
            res = await route_world("DELETE", f"/api/v1/agents/{target}", who)
            assert res.status_code == 403, who
        assert await _get(co, Agent, target) is not None
        res = await route_world("DELETE", f"/api/v1/agents/{co['other_eve']}", "admin")
        assert res.status_code == 404

    async def test_delegate_and_manager_keep_their_own_permissions(self, co, route_world):
        body = {"target_agent_id": str(co["acme_zed"]), "title": "t"}
        res = await route_world("POST", f"/api/v1/agents/{co['acme_eve']}/delegate", "viewer", body)
        assert res.status_code == 403
        res = await route_world(
            "PUT",
            f"/api/v1/agents/{co['acme_eve']}/manager",
            "run",
            {"manager_id": str(co["acme_bo"])},
        )
        assert res.status_code == 403
        res = await route_world(
            "PUT",
            f"/api/v1/agents/{co['acme_eve']}/manager",
            "unknown",
            {"manager_id": str(co["acme_bo"])},
        )
        assert res.status_code == 403
        assert (await _get(co, Agent, co["acme_eve"])).manager_id == co["acme_lead"]


class TestStaticGuard:
    def test_every_non_get_agent_route_declares_a_permission_dependency(self):
        """A new non-GET route must declare ``WRITE_AGENT``/``require_permission`` or heartbeat."""
        missing = []
        for route in agent_routes.router.routes:
            methods = set(route.methods) - {"GET", "HEAD", "OPTIONS"}
            if not methods:
                continue
            calls = [d.call for d in route.dependant.dependencies]
            has_permission = any(
                getattr(c, "__qualname__", "").startswith("require_permission.") for c in calls
            )
            if not (has_permission or agent_routes.heartbeat_principal in calls):
                missing.append(f"{sorted(methods)} {route.path}")
        assert not missing, f"agent routes without an explicit permission dependency: {missing}"

    def test_every_write_route_also_denies_unknown_principal_kinds(self):
        for route in agent_routes.router.routes:
            if not set(route.methods) - {"GET", "HEAD", "OPTIONS"}:
                continue
            calls = [d.call for d in route.dependant.dependencies]
            assert agent_routes.heartbeat_principal in calls or any(
                getattr(c, "__qualname__", "").startswith("principal_kinds.") for c in calls
            ), route.path

    def test_every_update_field_is_classified_and_the_body_forbids_extras(self):
        fields = set(agent_routes.AgentUpdate.model_fields)
        assert fields == agent_routes.AUTHORITY_FIELDS | agent_routes.PROFILE_FIELDS, (
            "classify every AgentUpdate field as authority or profile"
        )
        assert not agent_routes.AUTHORITY_FIELDS & agent_routes.PROFILE_FIELDS
        assert agent_routes.AgentUpdate.model_config.get("extra") == "forbid"

    def test_the_three_update_routes_share_one_implementation(self):
        import inspect

        for fn in (
            agent_routes.update_agent,
            agent_routes.patch_agent,
            agent_routes.patch_agent_company_scoped,
        ):
            assert "apply_agent_update" in inspect.getsource(fn), fn.__name__
            assert "update(Agent)" not in inspect.getsource(fn), fn.__name__

    async def test_the_agent_table_is_untouched_by_denied_calls(self, co, route_world):
        before = sorted(
            (a.id, a.role, a.status, a.budget_monthly_cents) for a in await _rows(co["db"], Agent)
        )
        for who in DENIED:
            await route_world("PATCH", f"/api/v1/agents/{co['acme_eve']}", who, AUTHORITY_VALUES)
            await route_world("POST", f"/api/v1/agents/{co['acme_eve']}/clone", who)
        after = sorted(
            (a.id, a.role, a.status, a.budget_monthly_cents) for a in await _rows(co["db"], Agent)
        )
        assert after == before
        assert not (await _audit(co, "agent.updated", "agent.cloned"))
