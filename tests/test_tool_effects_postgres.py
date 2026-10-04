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
from nexus.tools.effects import EffectClass, ToolSlot
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
SLOT = ToolSlot(0, 0)


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


async def go(w, tool, effect=NON_IDEM, args=None, ctx=None, slot=SLOT, name="send-it"):
    return await guarded_call(
        ctx or w.ctx, name, args or {"n": 1}, tool, source="test", effect=effect.value,
        slot=slot,
    )


async def started(tool):
    for _ in range(500):
        if tool.runs:
            return
        await asyncio.sleep(0.01)
    raise AssertionError("tool never started")


def _new_row(company, **over):
    values = dict(
        company_id=company, turn_id=uuid.uuid4(), round_index=0, invocation_index=0,
        tool_name="t",
        effect_class="idempotent_write",
        invocation_key=uuid.uuid4().hex + uuid.uuid4().hex,
        arguments_digest="0" * 64,
        claim_token="tok", lease_expires_at=utcnow() + timedelta(minutes=5),
    )
    values.update(over)
    return ToolEffect(**values)


# --- schema, RLS, ownership ------------------------------------------------------------------


async def _effects_state(engine):
    async with engine.connect() as conn:
        return [
            tuple(r)
            for r in (
                await conn.execute(
                    sa.text(
                        "SELECT c.relname, c.relrowsecurity, c.relforcerowsecurity, "
                        "(SELECT count(*) FROM pg_policies p WHERE p.tablename = c.relname "
                        " AND p.policyname = 'tenant_isolation') "
                        "FROM pg_class c WHERE c.relname IN ('tool_effects', 'tool_notifications') "
                        "ORDER BY c.relname"
                    )
                )
            ).all()
        ]


LIVE = [("tool_effects", True, True, 1), ("tool_notifications", True, True, 1)]


@pytest.fixture
async def migration(migrated_postgres_url):
    cfg = alembic.config.Config("alembic.ini")
    cfg.set_main_option("sqlalchemy.url", migrated_postgres_url)
    engine = create_async_engine(migrated_postgres_url)
    try:
        yield cfg, engine
    finally:
        # Whatever a test did, leave the shared database at head for the tests after it.
        await asyncio.to_thread(alembic.command.upgrade, cfg, "head")
        async with engine.begin() as conn:
            await conn.execute(sa.text("GRANT ALL ON ALL TABLES IN SCHEMA public TO nexus_app"))
        await engine.dispose()


async def _empty_the_ledger(engine):
    """Test setup, as the superuser: a clean ledger so a downgrade is judged on its own rows."""
    async with engine.begin() as conn:
        await conn.execute(sa.text("DELETE FROM tool_notifications"))
        await conn.execute(sa.text("DELETE FROM tool_effects"))




async def test_forced_rls_policy_is_live_on_both_tables(migrated_postgres_url):
    engine = create_async_engine(migrated_postgres_url)
    try:
        assert await _effects_state(engine) == LIVE
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
    await effects.claim(world.acme, world.turn, SLOT, "t", NON_IDEM, {"a": 1})
    async with app_role() as db:  # no tenant bound
        assert (await db.execute(sa.select(ToolEffect))).scalars().all() == []
        db.add(_new_row(world.acme))
        with pytest.raises(DBAPIError, match="row-level security|own company"):
            await db.commit()


async def test_tenants_are_invisible_to_each_other(world):
    await effects.claim(world.acme, world.turn, SLOT, "t", NON_IDEM, {"a": 1})
    async with tenant_session(world.other) as db:
        assert (await db.execute(sa.select(ToolEffect))).scalars().all() == []
        db.add(_new_row(world.acme))  # forged company id
        with pytest.raises(DBAPIError, match="row-level security|own company"):
            await db.commit()
    assert await effects.list_open(world.other) == {"items": [], "next_cursor": None}


async def test_same_call_in_two_tenants_is_two_rows(world):
    a = await effects.claim(world.acme, world.turn, SLOT, "t", NON_IDEM, {"a": 1})
    b = await effects.claim(world.other, world.turn, SLOT, "t", NON_IDEM, {"a": 1})
    assert a.action == b.action == "run" and a.effect_id != b.effect_id


@pytest.mark.parametrize(
    ("over", "name"),
    [
        ({"status": "paused"}, "ck_tool_effects_status"),
        ({"effect_class": "read_only"}, "ck_tool_effects_class"),
        ({"attempt_count": 0}, "ck_tool_effects_attempts"),
        ({"round_index": -2}, "ck_tool_effects_round"),
        ({"invocation_index": -1}, "ck_tool_effects_position"),
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
        *[
            effects.claim(world.acme, world.turn, SLOT, "t", NON_IDEM, {"a": 1})
            for _ in range(RACERS)
        ]
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


# --- position-aware identity -----------------------------------------------------------------


async def test_identical_calls_at_different_positions_run_separately(world):
    tool = Tool()
    await go(world, tool, slot=ToolSlot(0, 0))
    await go(world, tool, slot=ToolSlot(0, 1))
    await go(world, tool, slot=ToolSlot(1, 0))
    assert tool.runs == 3
    assert sorted((r.round_index, r.invocation_index) for r in await world.rows(world.acme)) == [
        (0, 0), (0, 1), (1, 0),
    ]


async def test_recovery_of_the_same_position_reuses_the_row(world):
    tool = Tool(result={"sent": "m1"})
    first = await go(world, tool, slot=ToolSlot(2, 3))
    again = await go(world, tool, slot=ToolSlot(2, 3))
    assert tool.runs == 1 and again["replayed"] is True and again["result"] == first["result"]
    (row,) = await world.rows(world.acme)
    assert row.attempt_count == 1 and row.tool_name == "send-it"


async def test_a_different_call_at_an_occupied_slot_fails_closed(world):
    await go(world, Tool())
    other_tool, other_args = Tool(), Tool()
    different_tool = await go(world, other_tool, name="other-tool")
    different_args = await go(world, other_args, args={"n": 2})
    assert different_tool["status"] == different_args["status"] == "effect_recovery_required"
    assert other_tool.runs == other_args.runs == 0
    (row,) = await world.rows(world.acme)
    assert row.tool_name == "send-it" and row.status == "succeeded"


async def test_concurrent_claims_for_one_slot_have_one_runner_per_position(world):
    claims = await asyncio.gather(
        *[
            effects.claim(world.acme, world.turn, ToolSlot(0, i % 2), "t", NON_IDEM, {"a": i % 2})
            for i in range(RACERS)
        ]
    )
    assert sorted(c.action for c in claims) == ["busy"] * (RACERS - 2) + ["run"] * 2
    assert len(await world.rows(world.acme)) == 2


# --- the database clock decides leases -------------------------------------------------------


@pytest.mark.parametrize("skew", [timedelta(days=1), timedelta(days=-1)])
async def test_a_skewed_worker_clock_does_not_move_a_lease(world, monkeypatch, skew):
    gate = asyncio.Event()
    holder = Tool(gate=gate)
    task = asyncio.create_task(go(world, holder, effect=IDEM))
    await started(holder)

    real = effects.utcnow
    monkeypatch.setattr(effects, "utcnow", lambda: real() + skew)
    rival = Tool()
    # The worker clock says the lease is long expired (or far from it); the database says
    # it is live, so the rival is told to wait and does not run.
    assert (await go(world, rival, effect=IDEM))["status"] == "effect_in_progress"
    assert rival.runs == 0
    monkeypatch.setattr(effects, "utcnow", real)
    gate.set()
    await task
    (row,) = await world.rows(world.acme)
    assert row.status == "succeeded" and row.attempt_count == 1


async def test_a_lease_the_database_says_expired_is_retaken_despite_a_slow_clock(
    world, monkeypatch
):
    gate = asyncio.Event()
    holder = Tool(gate=gate)
    task = asyncio.create_task(go(world, holder, effect=IDEM))
    await started(holder)
    (row,) = await world.rows(world.acme)
    async with AsyncSession(world.engine) as db:
        await db.execute(
            sa.update(ToolEffect)
            .where(ToolEffect.id == row.id)
            .values(
                lease_expires_at=sa.text("timezone('UTC', clock_timestamp()) - interval '1 second'")
            )
        )
        await db.commit()
    real = effects.utcnow
    monkeypatch.setattr(effects, "utcnow", lambda: real() - timedelta(days=1))
    taker = Tool()
    assert (await go(world, taker, effect=IDEM))["status"] == "success" and taker.runs == 1
    monkeypatch.setattr(effects, "utcnow", real)
    gate.set()
    await task
    (row,) = await world.rows(world.acme)
    assert row.attempt_count == 2


# --- sealed results and notifications --------------------------------------------------------


async def test_first_result_equals_the_replayed_result_after_sealing(world):
    big = {"id": "m-77", "token": "sk-" + "a" * 40, "rows": [{"v": "x" * 400} for _ in range(300)]}
    tool = Tool(result=big)
    first = await go(world, tool)
    again = await go(world, tool)
    assert tool.runs == 1 and again["replayed"] is True
    assert first["result"] == again["result"]
    assert first["result"]["id"] == "m-77"
    assert "sk-" + "a" * 40 not in str(first["result"])
    assert first["result"]["token"] != big["token"]


async def test_an_unserializable_result_is_ambiguous_and_not_rerun(world):
    tool = Tool(result={"handle": object()})
    out = await go(world, tool)
    assert out["status"] == "effect_result_unavailable" and tool.runs == 1
    (row,) = await world.rows(world.acme)
    assert row.status == "ambiguous"
    retry = Tool()
    assert (await go(world, retry))["status"] == "effect_recovery_required" and retry.runs == 0


async def test_a_notice_is_claimed_once_per_invocation_even_when_racing(world):
    key = effects.invocation_key(world.acme, world.turn, SLOT)
    results = await asyncio.gather(*[effects.claim_notice(world.acme, key) for _ in range(RACERS)])
    assert results.count(True) == 1
    other = effects.invocation_key(world.acme, world.turn, ToolSlot(0, 1))
    assert await effects.claim_notice(world.acme, other) is True
    assert await effects.claim_notice(world.other, key) is True  # another tenant is its own


# --- guarded downgrade -----------------------------------------------------------------------


async def test_downgrade_of_an_empty_ledger_round_trips(migration, app_role):
    cfg, engine = migration
    await _empty_the_ledger(engine)
    assert await _effects_state(engine) == LIVE
    await asyncio.to_thread(alembic.command.downgrade, cfg, "b4d9f2a61c73")
    assert await _effects_state(engine) == []
    await asyncio.to_thread(alembic.command.upgrade, cfg, "head")
    assert await _effects_state(engine) == LIVE


async def test_downgrade_refuses_while_the_ledger_has_rows(migration, world, monkeypatch):
    cfg, engine = migration
    monkeypatch.delenv("NEXUS_DESTROY_TOOL_EFFECTS", raising=False)
    await effects.claim(world.acme, world.turn, SLOT, "t", NON_IDEM, {"a": 1})
    with pytest.raises(RuntimeError, match="Refusing to downgrade"):
        await asyncio.to_thread(alembic.command.downgrade, cfg, "b4d9f2a61c73")
    # Nothing was deleted and FORCE row level security is back on for both tables.
    assert await _effects_state(engine) == LIVE
    assert len(await world.rows(world.acme)) == 1
    # Anything but the exact acknowledgement is not an override.
    monkeypatch.setenv("NEXUS_DESTROY_TOOL_EFFECTS", "yes")
    with pytest.raises(RuntimeError, match="Refusing to downgrade"):
        await asyncio.to_thread(alembic.command.downgrade, cfg, "b4d9f2a61c73")
    assert len(await world.rows(world.acme)) == 1


async def test_destructive_override_reports_the_loss_and_reupgrade_is_empty(
    migration, world, monkeypatch, capfd
):
    cfg, engine = migration
    await effects.claim(world.acme, world.turn, SLOT, "t", NON_IDEM, {"a": 1})
    monkeypatch.setenv("NEXUS_DESTROY_TOOL_EFFECTS", "destroy-ledger")
    await asyncio.to_thread(alembic.command.downgrade, cfg, "b4d9f2a61c73")
    # Alembic's own logging config owns the logger, so the report is read where it lands.
    report = capfd.readouterr().err
    assert "DESTRUCTIVE DOWNGRADE" in report and "LOST" in report
    assert await _effects_state(engine) == []
    monkeypatch.delenv("NEXUS_DESTROY_TOOL_EFFECTS")
    await asyncio.to_thread(alembic.command.upgrade, cfg, "head")
    assert await _effects_state(engine) == LIVE
    async with engine.connect() as conn:
        counts = [
            (await conn.execute(sa.text(f"SELECT count(*) FROM {t}"))).scalar_one()
            for t in ("tool_effects", "tool_notifications")
        ]
    assert counts == [0, 0]
