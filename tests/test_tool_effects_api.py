"""Operator routes for ambiguous tool effects: human administrators only, tenant scoped, audited.

These run behind the real ``AuthenticationMiddleware`` and real credentials (session cookie,
API key, run token), because the property under test is who the middleware lets through, not
what a dependency override returns.
"""

from __future__ import annotations

import uuid
from dataclasses import replace

import httpx
import pytest
from fastapi import FastAPI, HTTPException
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlmodel import SQLModel, select

import nexus.models  # noqa: F401 -- registers every table on SQLModel.metadata
from nexus.api.deps import require_admin, require_user
from nexus.api.routes.tool_effects import router
from nexus.auth.middleware import AuthenticationMiddleware
from nexus.auth.principal import Principal
from nexus.auth.run_tokens import mint_run_token
from nexus.auth.sessions import create_session
from nexus.config import settings
from nexus.models.agent import Agent
from nexus.models.api_key import ApiKey
from nexus.models.company import Company, CompanyMembership
from nexus.models.governance import AuditLog
from nexus.models.tool_effect import ToolEffect
from nexus.models.user_profile import UserProfile
from nexus.tools.context import ExecutionContext
from nexus.tools.effects import ToolSlot
from nexus.tools.factory import guarded_call

OPEN = "/api/v1/tool-effects/open"


@pytest.fixture
async def env(tmp_path, monkeypatch):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'api.db'}")
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)
    maker = async_sessionmaker(engine, expire_on_commit=False)

    import nexus.auth.middleware as middleware
    import nexus.database as database

    monkeypatch.setattr(database, "async_session_factory", maker)
    monkeypatch.setattr(middleware, "async_session_factory", maker)
    monkeypatch.setattr(settings, "tool_binding_enforcement", "audit")
    monkeypatch.setattr(settings, "auth_enabled", True)

    creds: dict[str, dict[str, str]] = {}
    async with maker() as db:
        acme, other = Company(name="Acme"), Company(name="Other")
        db.add_all([acme, other])
        await db.flush()
        agent = Agent(company_id=acme.id, name="A", role="engineer")
        db.add(agent)

        async def human(label: str, company, role: str, *, active=True, member=True):
            user = UserProfile(
                company_id=company.id, email=f"{label}@acme.test", is_active=active
            )
            db.add(user)
            await db.flush()
            if member:
                db.add(CompanyMembership(company_id=company.id, user_id=user.id, role=role))
            token, _ = await create_session(db, user_id=user.id, company_id=company.id)
            csrf = "csrf-" + label
            creds[label] = {
                "cookie": f"{settings.session_cookie_name}={token}; "
                f"{settings.csrf_cookie_name}={csrf}",
                "x-csrf-token": csrf,
            }

        await human("admin", acme, "admin")
        await human("other_admin", other, "admin")
        await human("viewer", acme, "viewer")
        await human("manager", acme, "manager")
        await human("inactive", acme, "admin", active=False)
        await human("removed", acme, "admin", member=False)

        raw_key = ApiKey.generate_key()
        db.add(
            ApiKey(
                company_id=acme.id,
                name="admin-key",
                key_prefix=raw_key[:8],
                key_hash=ApiKey.hash_key(raw_key),
                role="admin",
            )
        )
        creds["api_key"] = {"authorization": f"Bearer {raw_key}"}
        creds["run_token"] = {
            "authorization": "Bearer " + mint_run_token(uuid.uuid4(), agent.id, acme.id)
        }
        creds["anonymous"] = {}
        creds["bypass"] = {"x-company-id": str(acme.id)}
        await db.commit()

    counter = {"n": 0}

    async def stuck_effect() -> uuid.UUID:
        """A non-idempotent write whose run died mid-flight, so its row is ambiguous."""
        ctx = replace(
            ExecutionContext.for_agent(agent, source="hermes"), turn_id=uuid.uuid4()
        )

        async def body():
            raise RuntimeError("reset")

        with pytest.raises(RuntimeError):
            await guarded_call(
                ctx, "send-it", {"n": counter["n"]}, body, source="test",
                effect="non_idempotent_write", slot=ToolSlot(0, 0),
            )
        counter["n"] += 1
        async with maker() as db:
            rows = (await db.execute(select(ToolEffect))).scalars().all()
            return max(rows, key=lambda r: r.created_at).id

    app = FastAPI()
    app.include_router(router)
    app.add_middleware(AuthenticationMiddleware)

    def headers(who: str) -> dict[str, str]:
        return dict(creds[who])

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://t"
    ) as client:
        yield {
            "client": client, "acme": acme.id, "other": other.id, "headers": headers,
            "stuck": stuck_effect, "maker": maker, "monkeypatch": monkeypatch,
        }
    await engine.dispose()


async def _get(env, who, url=OPEN):
    return await env["client"].get(url, headers=env["headers"](who))


async def _resolve(env, who, effect_id, body=None):
    return await env["client"].post(
        f"/api/v1/tool-effects/{effect_id}/resolve",
        json=body or {"outcome": "not_applied", "reason": "provider shows no message"},
        headers=env["headers"](who),
    )


async def test_admin_lists_and_resolves_an_ambiguous_effect(env):
    effect_id = await env["stuck"]()
    listed = (await _get(env, "admin")).json()
    assert [r["id"] for r in listed["items"]] == [str(effect_id)]
    assert listed["next_cursor"] is None
    item = listed["items"][0]
    assert item["round_index"] == 0 and item["invocation_index"] == 0
    assert "arguments" not in item and "result" not in item

    resp = await _resolve(env, "admin", effect_id)
    assert resp.status_code == 200 and resp.json()["status"] == "failed"
    async with env["maker"]() as db:
        row = await db.get(ToolEffect, effect_id)
        events = (
            await db.execute(
                select(AuditLog).where(AuditLog.action == "tool_effect.manual_recovery_resolved")
            )
        ).scalars().all()
    assert row.resolved_by == "admin@acme.test"
    assert len(events) == 1 and events[0].actor_id == "admin@acme.test"
    assert (await _get(env, "admin")).json()["items"] == []


@pytest.mark.parametrize(
    ("who", "expected"),
    [
        ("inactive", 401),
        ("removed", 401),
        ("anonymous", 401),
        ("viewer", 403),
        ("manager", 403),
        ("api_key", 403),
        ("run_token", 403),
    ],
)
async def test_only_a_live_human_admin_may_list_or_resolve(env, who, expected):
    effect_id = await env["stuck"]()
    assert (await _get(env, who)).status_code == expected
    resp = await _resolve(env, who, effect_id, {"outcome": "applied", "reason": "r"})
    assert resp.status_code == expected
    async with env["maker"]() as db:
        row = await db.get(ToolEffect, effect_id)
    assert row.status == "ambiguous" and row.resolved_by is None


async def test_the_auth_bypass_principal_is_refused(env):
    env["monkeypatch"].setattr(settings, "auth_enabled", False)
    assert settings.auth_bypass_active
    effect_id = await env["stuck"]()
    assert (await _get(env, "bypass")).status_code == 403
    resp = await _resolve(env, "bypass", effect_id, {"outcome": "applied", "reason": "r"})
    assert resp.status_code == 403


@pytest.mark.parametrize("kind", ["service", "run", "robot"])
def test_a_non_human_principal_is_refused_even_with_the_admin_role(kind):
    """The guard is "is a signed-in human", not "has a role", so unknown kinds fail too."""
    principal = Principal(kind=kind, company_id=uuid.uuid4(), role="admin")
    with pytest.raises(HTTPException) as caught:
        require_admin(require_user(principal))
    assert caught.value.status_code == 403


async def test_foreign_and_missing_effects_are_indistinguishable(env):
    effect_id = await env["stuck"]()
    foreign = await _resolve(env, "other_admin", effect_id)
    missing = await _resolve(env, "other_admin", uuid.uuid4())
    assert foreign.status_code == missing.status_code == 404
    assert foreign.json() == missing.json()
    assert (await _get(env, "other_admin")).json()["items"] == []
    async with env["maker"]() as db:
        assert (await db.get(ToolEffect, effect_id)).status == "ambiguous"


async def test_resolve_validates_and_is_not_repeatable(env):
    effect_id = await env["stuck"]()
    url = f"/api/v1/tool-effects/{effect_id}/resolve"
    for bad in (
        {"outcome": "maybe", "reason": "r"},
        {"outcome": "applied", "reason": ""},
        {"outcome": "applied"},
    ):
        resp = await env["client"].post(url, json=bad, headers=env["headers"]("admin"))
        assert resp.status_code == 422
    ok = {"outcome": "applied", "reason": "confirmed", "note": "delivered"}
    assert (await _resolve(env, "admin", effect_id, ok)).status_code == 200
    assert (await _resolve(env, "admin", effect_id, ok)).status_code == 409


async def test_resolve_needs_the_csrf_token_for_a_cookie_session(env):
    effect_id = await env["stuck"]()
    headers = env["headers"]("admin")
    headers.pop("x-csrf-token")
    resp = await env["client"].post(
        f"/api/v1/tool-effects/{effect_id}/resolve",
        json={"outcome": "applied", "reason": "r"},
        headers=headers,
    )
    assert resp.status_code == 403
    async with env["maker"]() as db:
        assert (await db.get(ToolEffect, effect_id)).status == "ambiguous"


async def test_open_list_is_paginated_with_a_stable_cursor(env):
    ids = [await env["stuck"]() for _ in range(3)]
    first = (await _get(env, "admin", f"{OPEN}?limit=2")).json()
    assert len(first["items"]) == 2 and first["next_cursor"]
    # Resolving a row already served must not shift what the next page holds.
    assert (await _resolve(env, "admin", first["items"][0]["id"])).status_code == 200
    second = (
        await _get(env, "admin", f"{OPEN}?limit=2&cursor={first['next_cursor']}")
    ).json()
    assert second["next_cursor"] is None
    seen = {r["id"] for r in first["items"]} | {r["id"] for r in second["items"]}
    assert seen == {str(i) for i in ids}


async def test_an_invalid_cursor_is_rejected(env):
    assert (await _get(env, "admin", f"{OPEN}?cursor=not-a-cursor")).status_code == 422
