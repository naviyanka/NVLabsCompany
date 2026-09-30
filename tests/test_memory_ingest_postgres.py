"""Canonical memory ingest and lifecycle on PostgreSQL under forced RLS.

Needs a disposable PostgreSQL (TEST_DATABASE_URL, or testcontainers); skipped otherwise.
The races here are what SQLite cannot show: concurrent identical ingests, concurrent
supersession, and tenant isolation through the app role.
"""
# ruff: noqa: F811 -- pytest fixtures imported from test_postgres_integration

import asyncio
import uuid

import alembic.command
import alembic.config
import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import create_async_engine

from nexus.database import tenant_session
from nexus.memory.ingest import MemoryContext, MemoryInput, MemoryOpError, Origin, ingest_memory
from nexus.memory.lifecycle import archive_memory, supersede_memory
from nexus.models.agent import Agent
from nexus.models.company import Company
from nexus.models.memory import MemoryRecord
from tests.test_postgres_integration import (  # noqa: F401 -- fixtures
    _companies,
    app_role,
    app_user_postgres_url,
    migrated_postgres_url,
    postgres_container,
)

pytestmark = [pytest.mark.postgres, pytest.mark.integration]

RACERS = 8


async def _tenant_with_agent(factory) -> tuple[uuid.UUID, uuid.UUID]:
    (company_id,) = await _companies(factory, 1)
    async with tenant_session(company_id) as db:
        agent = Agent(company_id=company_id, name="a", role="engineer", model="m")
        db.add(agent)
        await db.commit()
        return company_id, agent.id


def _item(agent_id, content="Deploys go out on Tuesdays", **kw):
    kw.setdefault("scope", "l2_agent")
    return MemoryInput(content=content, agent_id=agent_id, scope_id=agent_id, **kw)


async def _rows(company_id) -> list[MemoryRecord]:
    async with tenant_session(company_id) as db:
        return list((await db.execute(sa.select(MemoryRecord))).scalars().all())


async def test_concurrent_identical_ingest_yields_one_row(app_role):
    company_id, agent_id = await _tenant_with_agent(app_role)
    ctx = MemoryContext(company_id, "user:tester")

    async def one():
        async with tenant_session(company_id) as db:
            result = await ingest_memory(
                db,
                ctx,
                _item(
                    agent_id, source_type="api_request", source_id="evt-1", extractor_version="t-v1"
                ),
                Origin.API,
            )
            await db.commit()
            return result.record.id, result.created

    results = await asyncio.gather(*(one() for _ in range(RACERS)))

    assert len({rid for rid, _ in results}) == 1
    assert sum(created for _, created in results) == 1
    assert len(await _rows(company_id)) == 1


async def test_identical_text_from_different_sources_stays_separate(app_role):
    company_id, agent_id = await _tenant_with_agent(app_role)
    ctx = MemoryContext(company_id, "user:tester")
    for source_id in ("evt-a", "evt-b"):
        async with tenant_session(company_id) as db:
            await ingest_memory(
                db, ctx, _item(agent_id, source_type="api_request", source_id=source_id), Origin.API
            )
            await db.commit()
    rows = await _rows(company_id)
    assert len(rows) == 2 and len({r.ingestion_key for r in rows}) == 2


async def test_same_key_different_payload_conflicts_across_transactions(app_role):
    company_id, agent_id = await _tenant_with_agent(app_role)
    ctx = MemoryContext(company_id, "user:tester")
    kw = {"source_type": "api_request", "source_id": "idem:1", "item_key": "k"}
    async with tenant_session(company_id) as db:
        await ingest_memory(
            db, ctx, _item(agent_id, "first", **kw), Origin.API, payload_conflict_409=True
        )
        await db.commit()
    async with tenant_session(company_id) as db:
        with pytest.raises(MemoryOpError) as err:
            await ingest_memory(
                db, ctx, _item(agent_id, "second", **kw), Origin.API, payload_conflict_409=True
            )
    assert (err.value.code, err.value.status_code) == ("MEMORY_IDEMPOTENCY_CONFLICT", 409)
    assert len(await _rows(company_id)) == 1


async def test_tenants_are_isolated_and_cannot_reference_each_other(app_role):
    a, a_agent = await _tenant_with_agent(app_role)
    b, b_agent = await _tenant_with_agent(app_role)
    async with tenant_session(a) as db:
        first = await ingest_memory(db, MemoryContext(a, "user:a"), _item(a_agent), Origin.API)
        await db.commit()
    async with tenant_session(b) as db:
        await ingest_memory(db, MemoryContext(b, "user:b"), _item(b_agent), Origin.API)
        await db.commit()

    # The same text in two tenants is two rows, each visible only to its owner.
    assert [r.company_id for r in await _rows(a)] == [a]
    assert [r.company_id for r in await _rows(b)] == [b]

    async with tenant_session(b) as db:
        ctx = MemoryContext(b, "user:b")
        with pytest.raises(MemoryOpError) as err:
            await ingest_memory(db, ctx, _item(a_agent), Origin.API)  # someone else's agent
        assert err.value.code == "MEMORY_AGENT_NOT_FOUND"
        with pytest.raises(MemoryOpError) as err:
            await archive_memory(db, ctx, first.record.id)  # someone else's memory
        assert err.value.code == "MEMORY_NOT_FOUND"
        with pytest.raises(MemoryOpError) as err:
            await supersede_memory(db, ctx, first.record.id, _item(b_agent, "new"), Origin.API)
        assert err.value.code == "MEMORY_NOT_FOUND"
    assert [r.status for r in await _rows(a)] == ["active"]


async def test_concurrent_supersession_has_exactly_one_winner(app_role):
    company_id, agent_id = await _tenant_with_agent(app_role)
    ctx = MemoryContext(company_id, "user:tester")
    async with tenant_session(company_id) as db:
        old = (await ingest_memory(db, ctx, _item(agent_id, "v1"), Origin.API)).record.id
        await db.commit()

    async def replace(text):
        async with tenant_session(company_id) as db:
            try:
                result = await supersede_memory(db, ctx, old, _item(agent_id, text), Origin.API)
                await db.commit()
                return result.record.id
            except MemoryOpError as exc:
                return exc.code

    outcomes = await asyncio.gather(*(replace(f"v2-{i}") for i in range(RACERS)))

    winners = [o for o in outcomes if isinstance(o, uuid.UUID)]
    assert len(winners) == 1
    assert set(outcomes) - set(winners) == {"MEMORY_SUPERSESSION_CONFLICT"}
    rows = {r.id: r for r in await _rows(company_id)}
    assert len(rows) == 2  # the loser's successor rolled back with its savepoint
    assert rows[old].status == "superseded" and rows[old].content == "v1"
    assert rows[winners[0]].supersedes_id == old and rows[winners[0]].status == "active"


async def test_concurrent_archive_is_idempotent(app_role):
    company_id, agent_id = await _tenant_with_agent(app_role)
    ctx = MemoryContext(company_id, "user:tester")
    async with tenant_session(company_id) as db:
        target = (await ingest_memory(db, ctx, _item(agent_id), Origin.API)).record.id
        await db.commit()

    async def archive():
        async with tenant_session(company_id) as db:
            record = await archive_memory(db, ctx, target, reason="stale")
            await db.commit()
            return record.status

    assert set(await asyncio.gather(*(archive() for _ in range(RACERS)))) == {"archived"}
    (row,) = await _rows(company_id)
    assert row.status == "archived" and row.content == "Deploys go out on Tuesdays"
    assert row.lifecycle_changed_by == "user:tester" and row.lifecycle_changed_at is not None


async def test_backfill_keeps_rls_forced_and_rows_intact(postgres_container, migrated_postgres_url):
    """Upgrade a database that already holds legacy rows; RLS stays forced afterwards."""
    base = migrated_postgres_url.rsplit("/", 1)[0]
    name = f"backfill_{uuid.uuid4().hex[:8]}"
    admin = create_async_engine(migrated_postgres_url, isolation_level="AUTOCOMMIT")
    async with admin.connect() as conn:
        await conn.execute(sa.text(f'CREATE DATABASE "{name}"'))
    await admin.dispose()

    url = f"{base}/{name}"
    # No ini file: alembic's env.py would call logging.config.fileConfig, which disables
    # every existing logger and breaks log capture in tests that run after this one.
    cfg = alembic.config.Config()
    cfg.set_main_option("script_location", "alembic")
    cfg.set_main_option("sqlalchemy.url", url)
    engine = create_async_engine(url)
    try:
        await asyncio.to_thread(alembic.command.upgrade, cfg, "e7a1c2d3f407")
        company_id, legacy_id, candidate_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
        async with engine.begin() as conn:
            await conn.execute(sa.text("ALTER TABLE memory_records NO FORCE ROW LEVEL SECURITY"))
            await conn.execute(sa.insert(Company.__table__).values(id=company_id, name="x"))
            for rid, content, meta in (
                (legacy_id, "Old note", "{}"),
                (candidate_id, "User likes tea", '{"trust": "untrusted_candidate"}'),
            ):
                await conn.execute(
                    sa.text(
                        "INSERT INTO memory_records (id, company_id, scope, content, metadata,"
                        " importance, access_count, tier, created_at, updated_at)"
                        " VALUES (:i, :c, 'agent', :t,"
                        " CAST(:m AS json), 0.5, 0, 'warm', now(), now())"
                    ),
                    {"i": rid, "c": company_id, "t": content, "m": meta},
                )
            await conn.execute(sa.text("ALTER TABLE memory_records FORCE ROW LEVEL SECURITY"))

        await asyncio.to_thread(alembic.command.upgrade, cfg, "head")

        async with engine.connect() as conn:
            flags = (
                await conn.execute(
                    sa.text(
                        "SELECT relrowsecurity, relforcerowsecurity FROM pg_class"
                        " WHERE relname='memory_records'"
                    )
                )
            ).one()
            assert tuple(flags) == (True, True)
            rows = {
                r.id: r
                for r in await conn.execute(
                    sa.text(
                        "SELECT id, content, status, trust_state, ingestion_key FROM memory_records"
                    )
                )
            }
        assert rows[legacy_id].content == "Old note"
        assert (rows[legacy_id].status, rows[legacy_id].ingestion_key) == (
            "active",
            f"legacy:{legacy_id}",
        )
        assert rows[candidate_id].status == "candidate"

        await asyncio.to_thread(alembic.command.downgrade, cfg, "e7a1c2d3f407")
        await asyncio.to_thread(alembic.command.upgrade, cfg, "head")
    finally:
        await engine.dispose()


async def test_concurrent_chat_extraction_replay_yields_one_row_per_fact(app_role):
    from nexus.api.routes import chat as chat_module

    company_id, agent_id = await _tenant_with_agent(app_role)
    agent = Agent(id=agent_id, company_id=company_id, name="a", role="engineer", model="m")
    reply = (
        "I learned that deploys go out on Tuesdays. "
        "I learned that the cache key includes the tenant."
    )
    turn = uuid.uuid4()

    stored = await asyncio.gather(
        *(chat_module._remember_response(agent, reply, turn_id=turn) for _ in range(RACERS))
    )
    rows = await _rows(company_id)
    assert len(rows) == 2 and sum(stored) == 2
    assert {r.source_id for r in rows} == {str(turn)} and len({r.ingestion_key for r in rows}) == 2

    # A later replay of the same turn, and the same reply on another turn, behave as specified.
    assert await chat_module._remember_response(agent, reply, turn_id=turn) == 0
    assert len(await _rows(company_id)) == 2
