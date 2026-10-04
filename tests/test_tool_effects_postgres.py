"""Tool-effect ledger on real PostgreSQL: forced RLS, constraints, races, recovery.

Migration ``c5e8a3b71d94``. Runs against a disposable PostgreSQL (testcontainers, or
``TEST_DATABASE_URL``); skipped when neither is available. The races use real concurrent
sessions as the RLS-bound application role and ``asyncio.gather``; the only waiting is a
bounded poll for a worker to have started.
"""
# ruff: noqa: F811 -- pytest fixtures imported from test_postgres_integration

import asyncio
import uuid
from dataclasses import replace
from datetime import timedelta

import alembic.command
import alembic.config
import pytest
import sqlalchemy as sa
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from nexus.config import settings
from nexus.database import tenant_session
from nexus.models._time import utcnow
from nexus.models.agent import Agent
from nexus.models.company import Company
from nexus.models.governance import AuditLog
from nexus.models.tool_effect import ToolEffect
from nexus.tools import effects
from nexus.tools.context import ExecutionContext
from nexus.tools.effects import EffectClass
from nexus.tools.factory import guarded_call
from tests.test_postgres_integration import (  # noqa: F401 -- fixtures
    app_role,
    app_user_postgres_url,
    migrated_postgres_url,
    postgres_container,
)

pytestmark = [pytest.mark.postgres, pytest.mark.integration]

NON_IDEM = EffectClass.NON_IDEMPOTENT_WRITE
IDEM = EffectClass.IDEMPOTENT_WRITE
RACERS = 6


class World:
    """Two companies and an agent in the first, seeded as the superuser."""


@pytest.fixture
async def world(migrated_postgres_url, app_role, monkeypatch):
    monkeypatch.setattr(settings, "tool_binding_enforcement", "audit")
    engine = create_async_engine(migrated_postgres_url)
    w = World()
    w.engine = engine
    w.acme, w.other = uuid.uuid4(), uuid.uuid4()
    async with AsyncSession(engine, expire_on_commit=False) as db:
        db.add_all([Company(id=w.acme, name="Acme"), Company(id=w.other, name="Other")])
        await db.flush()
        w.agent = Agent(company_id=w.acme, name="A", role="engineer")
        db.add(w.agent)
        await db.commit()
    w.turn = uuid.uuid4()
    w.ctx = replace(ExecutionContext.for_agent(w.agent, source="hermes"), turn_id=w.turn)

    async def rows(company):
        async with AsyncSession(engine) as db:  # superuser: not bound to a tenant
            stmt = sa.select(ToolEffect).where(ToolEffect.company_id == company)
            return list((await db.execute(stmt)).scalars())

    w.rows = rows
    yield w
    await engine.dispose()


class Tool:
    def __init__(self, result=None, raises=None, gate=None):
        self.runs = 0
        self.result = {"ok": True} if result is None else result
        self.raises = raises
        self.gate = gate

    async def __call__(self):
        self.runs += 1
        if self.gate is not None:
            await self.gate.wait()
        if self.raises is not None:
            raise self.raises
        return self.result


async def go(w, tool, effect=NON_IDEM, args=None, ctx=None):
    return await guarded_call(
        ctx or w.ctx, "send-it", args or {"n": 1}, tool, source="test", effect=effect.value
    )


async def started(tool):
    for _ in range(500):
        if tool.runs:
            return
        await asyncio.sleep(0.01)
    raise AssertionError("tool never started")


def _new_row(company, **over):
    values = dict(
        company_id=company, turn_id=uuid.uuid4(), tool_name="t", effect_class="idempotent_write",
        invocation_key=uuid.uuid4().hex + uuid.uuid4().hex, arguments_digest="0" * 64,
        claim_token="tok", lease_expires_at=utcnow() + timedelta(minutes=5),
    )
    values.update(over)
    return ToolEffect(**values)


# --- schema, RLS, ownership ------------------------------------------------------------------


async def test_forced_rls_policy_and_migration_round_trip(migrated_postgres_url):
    cfg = alembic.config.Config("alembic.ini")
    cfg.set_main_option("sqlalchemy.url", migrated_postgres_url)
    engine = create_async_engine(migrated_postgres_url)

    async def state():
        async with engine.connect() as conn:
            return [
                tuple(r)
                for r in (
                    await conn.execute(
                        sa.text(
                            "SELECT c.relrowsecurity, c.relforcerowsecurity, "
                            "(SELECT count(*) FROM pg_policies p WHERE p.tablename = c.relname "
                            " AND p.policyname = 'tenant_isolation') "
                            "FROM pg_class c WHERE c.relname = 'tool_effects'"
                        )
                    )
                ).all()
            ]

    try:
        assert await state() == [(True, True, 1)]
        await asyncio.to_thread(alembic.command.downgrade, cfg, "b4d9f2a61c73")
        try:
            assert await state() == []
        finally:
            await asyncio.to_thread(alembic.command.upgrade, cfg, "head")
        assert await state() == [(True, True, 1)]
    finally:
        await engine.dispose()


async def test_application_role_does_not_own_the_table(world, app_user_postgres_url):
    async with world.engine.connect() as conn:
        owner = (
            await conn.execute(
                sa.text(
                    "SELECT pg_get_userbyid(relowner) FROM pg_class WHERE relname = 'tool_effects'"
                )
            )
        ).scalar_one()
    assert owner != sa.engine.make_url(app_user_postgres_url).username


async def test_force_rls_binds_the_table_owner(migrated_postgres_url):
    """A non-superuser owner is subject to the policy because of FORCE; rolled back after."""
    engine = create_async_engine(migrated_postgres_url)
    try:
        async with AsyncSession(engine) as db:
            cid = uuid.uuid4()
            db.add(Company(id=cid, name="Owner Corp"))
            await db.flush()
            db.add(_new_row(cid))
            await db.flush()
            await db.execute(sa.text("CREATE ROLE tmp_effects_owner NOSUPERUSER NOBYPASSRLS"))
            await db.execute(sa.text("ALTER TABLE tool_effects OWNER TO tmp_effects_owner"))
            await db.execute(sa.text("SET LOCAL ROLE tmp_effects_owner"))
            count = "SELECT count(*) FROM tool_effects WHERE company_id = :c"
            assert (await db.execute(sa.text(count), {"c": cid})).scalar_one() == 0
            await db.execute(
                sa.text("SELECT set_config('nexus.company_id', :c, true)"), {"c": str(cid)}
            )
            assert (await db.execute(sa.text(count), {"c": cid})).scalar_one() == 1
            await db.rollback()
    finally:
        await engine.dispose()


async def test_unbound_session_reads_nothing_and_cannot_insert(world, app_role):
    await effects.claim(world.acme, world.turn, "t", NON_IDEM, {"a": 1})
    async with app_role() as db:  # no tenant bound
        assert (await db.execute(sa.select(ToolEffect))).scalars().all() == []
        db.add(_new_row(world.acme))
        with pytest.raises(DBAPIError, match="row-level security|own company"):
            await db.commit()


async def test_tenants_are_invisible_to_each_other(world):
    await effects.claim(world.acme, world.turn, "t", NON_IDEM, {"a": 1})
    async with tenant_session(world.other) as db:
        assert (await db.execute(sa.select(ToolEffect))).scalars().all() == []
        db.add(_new_row(world.acme))  # forged company id
        with pytest.raises(DBAPIError, match="row-level security|own company"):
            await db.commit()
    assert await effects.list_open(world.other) == []


async def test_same_call_in_two_tenants_is_two_rows(world):
    a = await effects.claim(world.acme, world.turn, "t", NON_IDEM, {"a": 1})
    b = await effects.claim(world.other, world.turn, "t", NON_IDEM, {"a": 1})
    assert a.action == b.action == "run" and a.effect_id != b.effect_id


@pytest.mark.parametrize(
    ("over", "name"),
    [
        ({"status": "paused"}, "ck_tool_effects_status"),
        ({"effect_class": "read_only"}, "ck_tool_effects_class"),
        ({"attempt_count": 0}, "ck_tool_effects_attempts"),
        ({"claim_token": None}, "ck_tool_effects_executing_claim"),
        ({"lease_expires_at": None}, "ck_tool_effects_executing_claim"),
    ],
)
async def test_check_constraints_hold(world, over, name):
    async with tenant_session(world.acme) as db:
        db.add(_new_row(world.acme, **over))
        with pytest.raises(IntegrityError, match=name):
            await db.commit()


async def test_unique_key_per_tenant(world):
    key = uuid.uuid4().hex + uuid.uuid4().hex
    async with tenant_session(world.acme) as db:
        db.add(_new_row(world.acme, invocation_key=key))
        await db.commit()
    async with tenant_session(world.acme) as db:
        db.add(_new_row(world.acme, invocation_key=key))
        with pytest.raises(IntegrityError, match="uq_tool_effects_key"):
            await db.commit()


# --- execute-once on PostgreSQL --------------------------------------------------------------


async def test_concurrent_claims_have_one_winner(world):
    claims = await asyncio.gather(
        *[effects.claim(world.acme, world.turn, "t", NON_IDEM, {"a": 1}) for _ in range(RACERS)]
    )
    assert sorted(c.action for c in claims) == ["busy"] * (RACERS - 1) + ["run"]
    assert len(await world.rows(world.acme)) == 1


async def test_concurrent_identical_calls_run_the_tool_once(world):
    gate = asyncio.Event()
    tool = Tool(gate=gate)
    callers = [asyncio.create_task(go(world, tool)) for _ in range(RACERS)]
    await started(tool)
    for _ in range(500):
        if sum(t.done() for t in callers) >= RACERS - 1:
            break
        await asyncio.sleep(0.01)
    gate.set()
    outs = await asyncio.gather(*callers)
    assert tool.runs == 1
    assert sorted(o["status"] for o in outs) == ["effect_in_progress"] * (RACERS - 1) + ["success"]


async def test_replay_after_success_runs_nothing(world):
    tool = Tool(result={"sent": "m1"})
    first = await go(world, tool)
    again = await go(world, tool)
    assert tool.runs == 1 and again["replayed"] is True and again["result"] == first["result"]


async def test_ambiguous_non_idempotent_waits_for_a_person_then_resolves(world):
    with pytest.raises(RuntimeError):
        await go(world, Tool(raises=RuntimeError("reset")))
    (row,) = await world.rows(world.acme)
    assert row.status == "ambiguous"

    retry = Tool()
    assert (await go(world, retry))["status"] == "effect_recovery_required"
    assert retry.runs == 0
    assert (await world.rows(world.acme))[0].status == "manual_recovery_required"

    # Two operators racing on one decision: one wins, the other is refused.
    results = await asyncio.gather(
        effects.resolve_manual_recovery(world.acme, row.id, "applied", actor="a", reason="r"),
        effects.resolve_manual_recovery(world.acme, row.id, "not_applied", actor="b", reason="r"),
        return_exceptions=True,
    )
    assert sum(isinstance(r, dict) for r in results) == 1
    assert sum(isinstance(r, effects.EffectStateError) for r in results) == 1
    async with AsyncSession(world.engine) as db:
        events = (
            await db.execute(
                sa.select(AuditLog).where(
                    AuditLog.company_id == world.acme,
                    AuditLog.action == "tool_effect.manual_recovery_resolved",
                )
            )
        ).scalars().all()
    assert len(events) == 1


async def test_expired_lease_on_idempotent_call_is_retaken_once(world):
    gate = asyncio.Event()
    slow = Tool(gate=gate, result={"who": "zombie"})
    task = asyncio.create_task(go(world, slow, effect=IDEM))
    await started(slow)
    (row,) = await world.rows(world.acme)
    async with AsyncSession(world.engine) as db:
        await db.execute(
            sa.update(ToolEffect)
            .where(ToolEffect.id == row.id)
            .values(lease_expires_at=utcnow() - timedelta(seconds=1))
        )
        await db.commit()

    takers = [Tool(result={"who": f"t{i}"}) for i in range(RACERS)]
    outs = await asyncio.gather(*[go(world, t, effect=IDEM) for t in takers])
    assert sum(t.runs for t in takers) == 1
    assert sum(1 for o in outs if o["status"] == "success" and "replayed" not in o) == 1
    gate.set()
    await task  # the zombie's late settle changes nothing
    (row,) = await world.rows(world.acme)
    assert row.status == "succeeded" and row.attempt_count == 2
    assert row.result["value"]["who"].startswith("t")


async def test_ledger_audit_is_written_as_the_application_role(world):
    with pytest.raises(RuntimeError):
        await go(world, Tool(raises=RuntimeError("reset")))
    async with AsyncSession(world.engine) as db:
        actions = {
            a.action
            for a in (
                await db.execute(
                    sa.select(AuditLog).where(
                        AuditLog.company_id == world.acme, AuditLog.action.like("tool_effect.%")
                    )
                )
            ).scalars()
        }
    assert "tool_effect.ambiguous" in actions
