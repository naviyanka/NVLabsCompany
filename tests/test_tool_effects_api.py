"""Operator routes for ambiguous tool effects: admin only, tenant scoped, audited."""

from __future__ import annotations

import uuid
from dataclasses import replace

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlmodel import SQLModel, select

import nexus.models  # noqa: F401 -- registers every table on SQLModel.metadata
from nexus.api.deps import get_principal
from nexus.api.routes.tool_effects import router
from nexus.auth.principal import Principal
from nexus.config import settings
from nexus.models.agent import Agent
from nexus.models.company import Company
from nexus.models.governance import AuditLog
from nexus.models.tool_effect import ToolEffect
from nexus.tools.context import ExecutionContext
from nexus.tools.factory import guarded_call


@pytest.fixture
async def env(tmp_path, monkeypatch):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'api.db'}")
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)
    maker = async_sessionmaker(engine, expire_on_commit=False)

    import nexus.database as database

    monkeypatch.setattr(database, "async_session_factory", maker)
    monkeypatch.setattr(settings, "tool_binding_enforcement", "audit")
    async with maker() as db:
        acme, other = Company(name="Acme"), Company(name="Other")
        db.add_all([acme, other])
        await db.flush()
        agent = Agent(company_id=acme.id, name="A", role="engineer")
        db.add(agent)
        await db.commit()

    async def stuck_effect() -> uuid.UUID:
        ctx = replace(
            ExecutionContext.for_agent(agent, source="hermes"), turn_id=uuid.uuid4()
        )

        async def body():
            raise RuntimeError("reset")

        with pytest.raises(RuntimeError):
            await guarded_call(ctx, "send-it", {"n": 1}, body, source="test",
                               effect="non_idempotent_write")
        async with maker() as db:
            return (await db.execute(select(ToolEffect))).scalars().one().id

    app = FastAPI()
    app.include_router(router)
    state = {"principal": None}
    app.dependency_overrides[get_principal] = lambda: state["principal"]

    def as_(company, role="admin", kind="user"):
        state["principal"] = Principal(
            kind=kind, company_id=company, role=role, user_id=uuid.uuid4(),
            email="ops@acme.test",
        )

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://t"
    ) as client:
        yield {"client": client, "acme": acme.id, "other": other.id, "as_": as_,
               "stuck": stuck_effect, "maker": maker}
    await engine.dispose()


async def test_admin_lists_and_resolves_an_ambiguous_effect(env):
    effect_id = await env["stuck"]()
    env["as_"](env["acme"])
    listed = (await env["client"].get("/api/v1/tool-effects/open")).json()
    assert [r["id"] for r in listed] == [str(effect_id)]
    assert "arguments" not in listed[0] and "result" not in listed[0]

    resp = await env["client"].post(
        f"/api/v1/tool-effects/{effect_id}/resolve",
        json={"outcome": "not_applied", "reason": "provider shows no message"},
    )
    assert resp.status_code == 200 and resp.json()["status"] == "failed"
    async with env["maker"]() as db:
        row = await db.get(ToolEffect, effect_id)
        events = (await db.execute(
            select(AuditLog).where(AuditLog.action == "tool_effect.manual_recovery_resolved")
        )).scalars().all()
    assert row.resolved_by == "ops@acme.test"
    assert len(events) == 1 and events[0].actor_id == "ops@acme.test"
    assert (await env["client"].get("/api/v1/tool-effects/open")).json() == []


@pytest.mark.parametrize("role", ["viewer", "manager", "agent"])
async def test_only_admins_may_resolve(env, role):
    effect_id = await env["stuck"]()
    env["as_"](env["acme"], role=role)
    body = {"outcome": "applied", "reason": "r"}
    assert (await env["client"].post(
        f"/api/v1/tool-effects/{effect_id}/resolve", json=body)).status_code == 403
    assert (await env["client"].get("/api/v1/tool-effects/open")).status_code == 403
    async with env["maker"]() as db:
        assert (await db.get(ToolEffect, effect_id)).status == "ambiguous"


async def test_another_tenant_sees_and_resolves_nothing(env):
    effect_id = await env["stuck"]()
    env["as_"](env["other"])
    assert (await env["client"].get("/api/v1/tool-effects/open")).json() == []
    resp = await env["client"].post(
        f"/api/v1/tool-effects/{effect_id}/resolve", json={"outcome": "applied", "reason": "r"}
    )
    assert resp.status_code == 404


async def test_resolve_validates_and_is_not_repeatable(env):
    effect_id = await env["stuck"]()
    env["as_"](env["acme"])
    url = f"/api/v1/tool-effects/{effect_id}/resolve"
    for bad in ({"outcome": "maybe", "reason": "r"}, {"outcome": "applied", "reason": ""},
                {"outcome": "applied"}):
        assert (await env["client"].post(url, json=bad)).status_code == 422
    ok = {"outcome": "applied", "reason": "confirmed", "note": "delivered"}
    assert (await env["client"].post(url, json=ok)).status_code == 200
    assert (await env["client"].post(url, json=ok)).status_code == 409
