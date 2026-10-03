"""Who may read a full deliverable, and what models and tools see instead.

Principal inventory (``nexus.auth.principal``; the middleware is the only builder):

* ``user``: a session cookie. Built only for an active user with a current membership.
* ``service`` with ``api_key_id``: an API key. Not a person.
* ``service`` without a key and without a label: the ``AUTH_ENABLED=false`` development operator.
* ``service`` with a label (``SYSTEM_ACTOR``): an in-process worker.
* ``run``: a run token naming an agent.
* anything else: unknown, so denied.

``can_view_work_deliverable`` allows the people, the development operator and nothing else.
"""

# ruff: noqa: F811  (pytest fixtures are imported, then named as test parameters)

from __future__ import annotations

import uuid

import httpx
import pytest
from fastapi import FastAPI, Request

from nexus.api.routes import task_attempts as attempt_routes
from nexus.api.routes import work as work_routes
from nexus.auth.middleware import AuthenticationMiddleware
from nexus.auth.principal import Principal
from nexus.auth.sessions import create_session
from nexus.auth.users import create_user
from nexus.models.user_profile import UserProfile
from nexus.runtime import task_attempts as ta
from nexus.services import work_service
from nexus.tools import manager_tools
from tests.test_employee_work import db, w  # noqa: F401 -- fixtures
from tests.test_work_service import _ctx, _submitted, co  # noqa: F401 -- fixtures, helpers

pytestmark = pytest.mark.employee_work

LONG = "Q3 findings. " * 150  # 1950 characters: over the 500 character summary bound
BOUND = ta.SUMMARY_VIEW_CHARS
COMPANY = uuid.uuid4()


def _p(kind, **kw):
    return Principal(kind=kind, company_id=COMPANY, role=kw.pop("role", "admin"), **kw)


PRINCIPALS = {
    "user_admin": (_p("user", user_id=uuid.uuid4()), True),
    "user_manager": (_p("user", user_id=uuid.uuid4(), role="manager"), True),
    "user_viewer": (_p("user", user_id=uuid.uuid4(), role="viewer"), True),
    "user_without_id": (_p("user"), False),
    "user_naming_an_agent": (_p("user", user_id=uuid.uuid4(), agent_id=uuid.uuid4()), False),
    "dev_operator": (_p("service"), True),
    "api_key": (_p("service", api_key_id=uuid.uuid4()), False),
    "api_key_viewer": (_p("service", api_key_id=uuid.uuid4(), role="viewer"), False),
    "labelled_worker": (_p("service", label="system:worker", role="manager"), False),
    "service_naming_a_user": (_p("service", user_id=uuid.uuid4()), False),
    "run_token": (_p("run", role="agent", run_id=uuid.uuid4(), agent_id=uuid.uuid4()), False),
    "run_token_admin_role": (_p("run", run_id=uuid.uuid4(), agent_id=uuid.uuid4()), False),
    "agent_role_user": (_p("user", user_id=uuid.uuid4(), role="agent"), True),
    "unknown_kind": (_p("tool", role="admin", user_id=uuid.uuid4()), False),
    "unknown_role": (_p("user", user_id=uuid.uuid4(), role="owner"), False),
    "none": (None, False),
}


@pytest.mark.parametrize("name", sorted(PRINCIPALS))
def test_predicate_for_every_principal_kind(name):
    principal, expected = PRINCIPALS[name]
    if principal is None:
        with pytest.raises(AttributeError):
            work_service.can_view_work_deliverable(principal)
        return
    assert work_service.can_view_work_deliverable(principal) is expected


@pytest.fixture
async def world(co):  # noqa: F811
    """Real sessions through the real cookie resolver, plus synthetic non-human principals."""
    db_factory = co["db"]
    tokens: dict[str, str] = {}
    ids: dict[str, uuid.UUID] = {}
    async with db_factory() as s:
        for name, company, role in (
            ("admin", co["acme"], "admin"),
            ("viewer", co["acme"], "viewer"),
            ("inactive", co["acme"], "admin"),
            ("outsider", co["other"], "admin"),
        ):
            user = await create_user(
                s, email=f"{name}@example.com", password="x" * 14, company_id=company, role=role
            )
            ids[name] = user.id
            tokens[name], _ = await create_session(s, user_id=user.id, company_id=company)
        await s.commit()

    synthetic = {
        "api_key": Principal(
            kind="service", company_id=co["acme"], role="admin", api_key_id=uuid.uuid4()
        ),
        "run": Principal(
            kind="run",
            company_id=co["acme"],
            role="agent",
            run_id=uuid.uuid4(),
            agent_id=co["acme_lead"],
        ),
        "worker": Principal(kind="service", company_id=co["acme"], role="admin", label="w"),
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
    app.include_router(work_routes.router)
    app.include_router(attempt_routes.router)

    @app.middleware("http")
    async def authenticate(request: Request, call_next):
        who = request.headers.get("x-test-principal")
        if who:
            request.state.principal = synthetic[who]
        else:
            token = request.cookies.get("nv_session", "")
            async with db_factory() as s:
                found = await resolver._principal_from_cookie(s, token) if token else None
                await s.commit()
            if found is not None:
                request.state.principal = found
        return await call_next(request)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:

        async def call(method, path, who, body=None):
            client.cookies.clear()
            headers = {}
            if who in tokens:
                client.cookies.set("nv_session", tokens[who])
            else:
                headers["x-test-principal"] = who
            return await client.request(method, path, json=body, headers=headers)

        async def deactivate(name):
            async with db_factory() as s:
                (await s.get(UserProfile, ids[name])).is_active = False
                await s.commit()

        call.deactivate = deactivate
        yield call


async def _long_submission(co):
    co["model"].reply = LONG
    return await _submitted(co)


def _surfaces(work, task, attempt):
    return {
        "work_list": "/api/v1/work",
        "work_one": f"/api/v1/work/{work}",
        "attempts": f"/api/v1/tasks/{task}/attempts",
        "attempt": f"/api/v1/tasks/{task}/attempts/{attempt}",
    }


class TestRoutes:
    async def test_people_read_the_whole_deliverable(self, co, world):
        work, task, attempt = await _long_submission(co)
        for who in ("admin", "viewer", "dev"):
            for name, url in _surfaces(work, task, attempt).items():
                res = await world("GET", url, who)
                assert res.status_code == 200, (who, name, res.text)
                assert LONG.strip() in res.text, (who, name)

    async def test_everyone_else_gets_a_bounded_summary_at_most(self, co, world):
        work, task, attempt = await _long_submission(co)
        for who in ("api_key", "run", "worker", "unknown"):
            for name, url in _surfaces(work, task, attempt).items():
                res = await world("GET", url, who)
                assert res.status_code == 200, (who, name, res.text)
                assert LONG.strip() not in res.text, (who, name)
                assert "Q3 findings. " * (BOUND // 13 + 3) not in res.text, (who, name)
        body = (await world("GET", _surfaces(work, task, attempt)["attempt"], "run")).json()
        assert len(body["output_summary"]) == BOUND

    async def test_review_response_follows_the_same_rule(self, co, world):
        work, task, attempt = await _long_submission(co)
        url = f"/api/v1/work/attempts/{attempt}/review"
        # An API key acts on the work routes but never receives the deliverable back.
        res = await world("POST", url, "api_key", {"decision": "verify"})
        assert res.status_code == 200, res.text
        assert LONG.strip() not in res.text
        assert len(res.json()["attempt"]["output_summary"]) == BOUND
        again = await world("POST", url, "admin", {"decision": "verify"})
        assert LONG.strip() in again.text

    async def test_foreign_tenant_sees_nothing(self, co, world):
        work, task, attempt = await _long_submission(co)
        for url in _surfaces(work, task, attempt).values():
            res = await world("GET", url, "outsider")
            assert res.status_code in (404, 200), res.text
            assert "Q3 findings" not in res.text, url

    async def test_inactive_user_and_removed_membership_get_nothing(self, co, world):
        work, task, attempt = await _long_submission(co)
        url = _surfaces(work, task, attempt)["work_one"]
        assert (await world("GET", url, "inactive")).status_code == 200
        await world.deactivate("inactive")
        res = await world("GET", url, "inactive")
        assert res.status_code == 401 and "Q3 findings" not in res.text
        # Removed membership is refused by the same resolver (tests/test_governance_me.py
        # pins it on the real cookie path); a user without one never becomes a principal.
        from sqlalchemy import delete

        from nexus.models.company import CompanyMembership

        async with co["db"]() as s:
            await s.execute(delete(CompanyMembership))
            await s.commit()
        res = await world("GET", url, "viewer")
        assert res.status_code == 401 and "Q3 findings" not in res.text


class TestModelTools:
    async def test_ceo_and_manager_tools_never_carry_the_full_deliverable(self, co):
        work, task, attempt = await _long_submission(co)
        ceo = _ctx(co["acme"], co["acme_ceo"])
        lead = _ctx(co["acme"], co["acme_lead"])
        views = {
            "ceo_get_work_status": await manager_tools.call(ceo, "ceo_get_work_status", {}),
            "ceo_get_work_status_one": await manager_tools.call(
                ceo, "ceo_get_work_status", {"work_id": str(work)}
            ),
            "employee_status": await manager_tools.call(
                lead, "manager_employee_status", {"employee_id": str(co["acme_eve"])}
            ),
            "evidence": await manager_tools.call(
                lead, "manager_task_evidence", {"task_id": str(task)}
            ),
            "rollup": await manager_tools.call(lead, "manager_rollup", {}),
        }
        for name, view in views.items():
            assert LONG.strip() not in str(view), name
            assert "Q3 findings. " * (BOUND // 13 + 3) not in str(view), name
        verdict = await manager_tools.call(
            lead, "manager_review_work", {"attempt_id": str(attempt), "decision": "verify"}
        )
        assert LONG.strip() not in str(verdict)
        assert len(verdict["attempt"]["output_summary"]) == BOUND
        assert verdict["changed"] is True
