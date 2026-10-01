"""``GET /governance/me``: the one answer to "may this caller change governance?".

The principal comes from the real session resolution (``_principal_from_cookie``: active user,
live membership, role read from the membership row on every request). The screen and the
runtime guard share ``errors.can_write``, so they cannot disagree.
"""

from __future__ import annotations

import uuid

import httpx
import pytest
from fastapi import FastAPI, Request
from sqlalchemy import delete

from nexus.api.routes import governance_studio as routes
from nexus.auth.middleware import AuthenticationMiddleware
from nexus.auth.principal import Principal
from nexus.auth.sessions import create_session
from nexus.auth.users import create_user
from nexus.models.company import CompanyMembership
from nexus.models.user_profile import UserProfile
from nexus.services.governance_studio.errors import can_write, require_admin_human
from tests.test_tool_access import ctx, factory, t  # noqa: F401 -- fixtures

RELEASE = {"reason": "parity check", "confirm": "RELEASE LOCKDOWN"}


@pytest.fixture
async def world(factory, t):  # noqa: F811
    """Real users and sessions in two companies, reached through the real cookie resolver."""
    tokens: dict[str, str] = {}
    ids: dict[str, uuid.UUID] = {}
    async with factory() as db:
        for name, company, role in (
            ("admin", t["acme"], "admin"), ("viewer", t["acme"], "viewer"),
            ("inactive", t["acme"], "admin"), ("removed", t["acme"], "admin"),
            ("outsider", t["other"], "admin"),
        ):
            user = await create_user(db, email=f"{name}@example.com", password="x" * 14,
                                     company_id=company, role=role)
            ids[name] = user.id
            tokens[name], _ = await create_session(db, user_id=user.id, company_id=company)
        # a viewer of Acme who presents a session that claims the other company
        tokens["crossed"], _ = await create_session(db, user_id=ids["viewer"],
                                                    company_id=t["other"])
        await db.commit()

    resolver = AuthenticationMiddleware(None)  # type: ignore[arg-type]
    app = FastAPI()
    app.include_router(routes.router)

    @app.middleware("http")
    async def authenticate(request: Request, call_next):
        token = request.cookies.get("nv_session", "")
        async with factory() as db:
            principal = await resolver._principal_from_cookie(db, token) if token else None
            await db.commit()
        if principal is not None:
            request.state.principal = principal
        return await call_next(request)

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                 base_url="http://test") as client:
        async def call(method, path, who, body=None, **kw):
            client.cookies.clear()
            if who in tokens:
                client.cookies.set("nv_session", tokens[who])
            return await client.request(method, f"/api/v1/governance{path}", json=body, **kw)

        async def deactivate(name):
            async with factory() as db:
                (await db.get(UserProfile, ids[name])).is_active = False
                await db.commit()

        async def remove_membership(name):
            async with factory() as db:
                await db.execute(delete(CompanyMembership).where(
                    CompanyMembership.user_id == ids[name]))
                await db.commit()

        call.deactivate, call.remove_membership = deactivate, remove_membership
        yield call


async def test_admin_may_write_and_the_body_is_only_the_flag(world):
    r = await world("GET", "/me", "admin")
    assert (r.status_code, r.json()) == (200, {"can_write": True})


async def test_viewer_is_read_only_but_can_read(world):
    r = await world("GET", "/me", "viewer")
    assert (r.status_code, r.json()) == (200, {"can_write": False})
    assert (await world("GET", "/agents", "viewer")).status_code == 200
    w = await world("POST", "/lockdown/release", "viewer", RELEASE)
    assert (w.status_code, w.json()["detail"]["code"]) == (403, "HUMAN_ADMIN_REQUIRED")


async def test_no_session_is_refused(world):
    assert (await world("GET", "/me", "nobody")).status_code == 401


async def test_inactive_user_fails_closed_at_once(world):
    assert (await world("GET", "/me", "inactive")).json() == {"can_write": True}
    await world.deactivate("inactive")
    assert (await world("GET", "/me", "inactive")).status_code == 401
    assert (await world("POST", "/lockdown/release", "inactive", RELEASE)).status_code == 401


async def test_removed_membership_fails_closed_at_once(world):
    assert (await world("GET", "/me", "removed")).json() == {"can_write": True}
    await world.remove_membership("removed")
    assert (await world("GET", "/me", "removed")).status_code == 401
    assert (await world("POST", "/lockdown/release", "removed", RELEASE)).status_code == 401


async def test_a_session_naming_another_company_is_refused(world):
    # The viewer has no membership in "other", so the session cannot carry them there.
    assert (await world("GET", "/me", "crossed")).status_code == 401


async def test_an_admin_of_another_tenant_is_scoped_to_their_own(world, t):  # noqa: F811
    assert (await world("GET", "/me", "outsider")).json() == {"can_write": True}
    r = await world("POST", f"/agents/{t['a']}/isolate", "outsider", {"reason": "not mine"})
    assert (r.status_code, r.json()["detail"]["code"]) == (404, "AGENT_NOT_FOUND")


async def test_nothing_the_client_sends_changes_the_answer(world):
    forged = {"x-role": "admin", "x-can-write": "true", "x-user-role": "admin"}
    r = await world("GET", "/me?role=admin&can_write=true", "viewer", headers=forged)
    assert r.json() == {"can_write": False}
    w = await world("POST", "/lockdown/release", "viewer",
                    {**RELEASE, "role": "admin", "can_write": True}, headers=forged)
    assert (w.status_code, w.json()["detail"]["code"]) == (403, "HUMAN_ADMIN_REQUIRED")


@pytest.mark.parametrize("principal", [
    Principal(kind="user", company_id=uuid.uuid4(), role="admin", user_id=uuid.uuid4()),
    Principal(kind="user", company_id=uuid.uuid4(), role="viewer", user_id=uuid.uuid4()),
    Principal(kind="user", company_id=uuid.uuid4(), role="member", user_id=uuid.uuid4()),
    Principal(kind="service", company_id=uuid.uuid4(), role="admin", api_key_id=uuid.uuid4()),
    Principal(kind="run", company_id=uuid.uuid4(), role="agent", run_id=uuid.uuid4(),
              agent_id=uuid.uuid4()),
])
def test_the_flag_and_the_write_guard_are_the_same_predicate(principal):
    from fastapi import HTTPException

    try:
        require_admin_human(principal)
        allowed = True
    except HTTPException as exc:
        assert (exc.status_code, exc.detail["code"]) == (403, "HUMAN_ADMIN_REQUIRED")
        allowed = False
    assert allowed == can_write(principal)
