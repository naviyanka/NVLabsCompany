"""Row-level security on memory_records, obsidian_documents, vault_write_grants.

Migration ``e7a1c2d3f407``. Runs against a disposable PostgreSQL (testcontainers,
or ``TEST_DATABASE_URL``); skipped when neither is available.
"""
# ruff: noqa: F811 -- pytest fixtures imported from test_postgres_integration

import asyncio
import uuid
from datetime import UTC, datetime, timedelta

import alembic.command
import alembic.config
import pytest
import sqlalchemy as sa
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from nexus.models.agent import Agent
from nexus.models.company import Company
from nexus.models.memory import MemoryRecord
from nexus.models.obsidian import ObsidianDocument, VaultWriteGrantRecord
from nexus.models.tool import Tool
from tests.test_postgres_integration import (  # noqa: F401 -- fixtures
    _companies,
    app_role,
    app_user_postgres_url,
    migrated_postgres_url,
    postgres_container,
    system_user_postgres_url,
)

pytestmark = [pytest.mark.postgres, pytest.mark.integration]

TABLES = ("memory_records", "obsidian_documents", "vault_write_grants")


async def _rls_flags(engine) -> dict[str, tuple[bool, bool, int]]:
    async with engine.connect() as conn:
        rows = (
            await conn.execute(
                sa.text(
                    "SELECT c.relname, c.relrowsecurity, c.relforcerowsecurity, "
                    "(SELECT count(*) FROM pg_policies p "
                    " WHERE p.tablename = c.relname AND p.policyname = 'tenant_isolation') "
                    "FROM pg_class c WHERE c.relname = ANY(:t)"
                ),
                {"t": list(TABLES)},
            )
        ).all()
    return {name: (rls, force, n) for name, rls, force, n in rows}


async def test_forced_rls_and_migration_round_trip(migrated_postgres_url):
    cfg = alembic.config.Config("alembic.ini")
    cfg.set_main_option("sqlalchemy.url", migrated_postgres_url)
    engine = create_async_engine(migrated_postgres_url)
    try:
        assert await _rls_flags(engine) == {t: (True, True, 1) for t in TABLES}

        await asyncio.to_thread(alembic.command.downgrade, cfg, "e7a1c2d3f406")
        try:
            assert await _rls_flags(engine) == {t: (False, False, 0) for t in TABLES}
        finally:
            await asyncio.to_thread(alembic.command.upgrade, cfg, "head")
        assert await _rls_flags(engine) == {t: (True, True, 1) for t in TABLES}
    finally:
        await engine.dispose()


async def test_rows_are_isolated_between_tenants_on_a_pooled_connection(
    app_user_postgres_url, monkeypatch
):
    from nexus.config import settings
    from nexus.database import tenant_session

    monkeypatch.setattr(settings, "database_url", app_user_postgres_url)
    engine = create_async_engine(app_user_postgres_url, pool_size=1, max_overflow=0)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    monkeypatch.setattr("nexus.database.async_session_factory", factory)
    try:
        a, b = await _companies(factory, 2)
        ids = {}
        for cid in (a, b):
            async with tenant_session(cid) as db:
                mem = MemoryRecord(company_id=cid, scope="company", content=f"secret of {cid}")
                doc = ObsidianDocument(
                    company_id=cid,
                    vault_path=f"notes/{cid}.md",
                    content_hash="0" * 64,
                    mtime=datetime.now(UTC).replace(tzinfo=None),
                )
                db.add_all([mem, doc])
                await db.commit()
                ids[cid] = (mem.id, doc.nexus_id)

        # Alternate tenants on the shared connection: each sees only its own rows.
        for cid, other in ((a, b), (b, a), (a, b)):
            async with tenant_session(cid) as db:
                mems = (await db.execute(sa.select(MemoryRecord))).scalars().all()
                docs = (await db.execute(sa.select(ObsidianDocument))).scalars().all()
                assert [m.id for m in mems] == [ids[cid][0]]
                assert [d.nexus_id for d in docs] == [ids[cid][1]]

                upd = await db.execute(
                    sa.update(MemoryRecord)
                    .where(MemoryRecord.id == ids[other][0])
                    .values(content="x")
                )
                dele = await db.execute(
                    sa.delete(ObsidianDocument).where(ObsidianDocument.nexus_id == ids[other][1])
                )
                assert (upd.rowcount, dele.rowcount) == (0, 0)
                await db.commit()

            async with tenant_session(cid) as db:
                db.add(MemoryRecord(company_id=other, scope="company", content="smuggled"))
                with pytest.raises(DBAPIError, match="row-level security"):
                    await db.commit()

        # No tenant bound: nothing visible, updatable or deletable, and no insert.
        async with factory() as db:
            assert (await db.execute(sa.select(MemoryRecord))).scalars().all() == []
            assert (await db.execute(sa.select(ObsidianDocument))).scalars().all() == []
            upd = await db.execute(sa.update(MemoryRecord).values(content="x"))
            dele = await db.execute(sa.delete(ObsidianDocument))
            assert (upd.rowcount, dele.rowcount) == (0, 0)
            await db.commit()
        async with factory() as db:
            db.add(MemoryRecord(company_id=a, scope="company", content="smuggled"))
            with pytest.raises(DBAPIError, match="row-level security"):
                await db.commit()

        for cid in (a, b):
            async with tenant_session(cid) as db:
                mem = (await db.execute(sa.select(MemoryRecord))).scalar_one()
                assert mem.content == f"secret of {cid}"
    finally:
        await engine.dispose()


async def test_force_rls_binds_the_table_owner(migrated_postgres_url):
    """A non-superuser table owner is subject to the policy because of FORCE.

    Runs in one transaction that is rolled back, so the temporary owner role and
    the ownership change never persist.
    """
    from nexus.models.company import Company

    engine = create_async_engine(migrated_postgres_url)
    try:
        async with AsyncSession(engine) as db:
            cid = uuid.uuid4()
            db.add(Company(id=cid, name="Owner Corp"))
            await db.flush()
            db.add(MemoryRecord(company_id=cid, scope="company", content="x"))
            await db.flush()

            await db.execute(sa.text("CREATE ROLE tmp_memory_owner NOSUPERUSER NOBYPASSRLS"))
            for table in TABLES:
                await db.execute(sa.text(f"ALTER TABLE {table} OWNER TO tmp_memory_owner"))
            await db.execute(sa.text("SET LOCAL ROLE tmp_memory_owner"))

            # The owner sees nothing without a tenant, and then only its own rows.
            count = "SELECT count(*) FROM memory_records WHERE company_id = :c"
            assert (await db.execute(sa.text(count), {"c": cid})).scalar_one() == 0
            await db.execute(sa.text("SELECT set_config('nexus.company_id', :c, true)"), {"c": str(cid)})  # noqa: E501
            assert (await db.execute(sa.text(count), {"c": cid})).scalar_one() == 1

            await db.rollback()
    finally:
        await engine.dispose()


async def test_ceo_knowledge_seed_runs_as_the_app_role(app_role):
    """The seed writes through tenant_session, so RLS accepts it and it stays idempotent."""
    from nexus import ceo_knowledge_seed as seed
    from nexus.database import tenant_session

    async with tenant_session(seed.COMPANY_ID) as db:
        if await db.get(Company, seed.COMPANY_ID) is None:
            db.add(Company(id=seed.COMPANY_ID, name="Seed Corp"))
            await db.flush()
        if await db.get(Agent, seed.CEO_AGENT_ID) is None:
            db.add(Agent(id=seed.CEO_AGENT_ID, company_id=seed.COMPANY_ID, name="CEO", role="ceo"))
        await db.commit()

    await seed.seed_ceo_knowledge()
    await seed.seed_ceo_knowledge()  # second run is a no-op, not a duplicate

    async with tenant_session(seed.COMPANY_ID) as db:
        n = (
            await db.execute(
                sa.select(sa.func.count(MemoryRecord.id)).where(
                    MemoryRecord.agent_id == seed.CEO_AGENT_ID,
                    MemoryRecord.scope == "api_reference",
                )
            )
        ).scalar_one()
    assert n == sum(1 for e in seed.API_KNOWLEDGE if e["scope"] == "api_reference")


async def test_vault_write_grants_refuse_a_foreign_or_unbound_insert(app_role):
    from nexus.database import tenant_session

    a, b = await _companies(app_role, 2)

    # The legitimate path still works, and the grant is invisible to the other tenant.
    async with tenant_session(a) as db:
        agent = Agent(company_id=a, name="Writer", role="staff")
        tool = Tool(company_id=a, name="vault_write", tool_type="function")
        db.add_all([agent, tool])
        await db.flush()
        db.add(
            VaultWriteGrantRecord(
                company_id=a, agent_id=agent.id, tool_id=tool.id, subtree="Knowledge"
            )
        )
        await db.commit()
    async with tenant_session(a) as db:
        assert len((await db.execute(sa.select(VaultWriteGrantRecord))).scalars().all()) == 1
    async with tenant_session(b) as db:
        assert (await db.execute(sa.select(VaultWriteGrantRecord))).scalars().all() == []
        gone = await db.execute(sa.delete(VaultWriteGrantRecord))
        assert gone.rowcount == 0
        await db.commit()

    for bound, target in ((None, a), (a, b)):
        async with (tenant_session(bound) if bound else app_role()) as db:
            db.add(
                VaultWriteGrantRecord(
                    company_id=target, agent_id=uuid.uuid4(), tool_id=uuid.uuid4(), subtree="x"
                )
            )
            with pytest.raises(DBAPIError, match="row-level security"):
                await db.commit()


async def test_system_role_sees_every_tenants_memory(
    app_user_postgres_url, system_user_postgres_url, monkeypatch
):
    from nexus.config import settings
    from nexus.database import tenant_session

    monkeypatch.setattr(settings, "database_url", app_user_postgres_url)
    app_engine = create_async_engine(app_user_postgres_url)
    app_factory = async_sessionmaker(app_engine, class_=AsyncSession, expire_on_commit=False)
    monkeypatch.setattr("nexus.database.async_session_factory", app_factory)
    sys_engine = create_async_engine(system_user_postgres_url)
    try:
        a, b = await _companies(app_factory, 2)
        for cid in (a, b):
            async with tenant_session(cid) as db:
                db.add(MemoryRecord(company_id=cid, scope="company", content="x"))
                await db.commit()
        async with sys_engine.connect() as conn:
            seen = set(
                (
                    await conn.execute(
                        sa.text(
                            "SELECT DISTINCT company_id FROM memory_records "
                            "WHERE company_id = ANY(:ids)"
                        ),
                        {"ids": [a, b]},
                    )
                ).scalars().all()
            )
        assert seen == {a, b}
    finally:
        await app_engine.dispose()
        await sys_engine.dispose()


async def test_memory_maintenance_only_touches_its_own_tenant(app_role):
    from nexus.database import tenant_session
    from nexus.runtime import orchestrator

    stale = datetime.now(UTC).replace(tzinfo=None) - timedelta(days=30)
    a, b = await _companies(app_role, 2)
    for cid in (a, b):
        async with tenant_session(cid) as db:
            agent = Agent(company_id=cid, name="Worker", role="staff")
            db.add(agent)
            await db.flush()
            db.add(
                MemoryRecord(
                    company_id=cid,
                    agent_id=agent.id,
                    scope="agent",
                    content="private",
                    importance=0.95,
                    tier="warm",
                    last_accessed_at=stale,
                )
            )
            await db.commit()

    async with tenant_session(a) as db:
        await orchestrator._memory_maintenance(db, a)
        await db.commit()

    for cid, expected in ((a, 0.95 * 0.95), (b, 0.95)):
        async with tenant_session(cid) as db:
            row = (await db.execute(sa.select(MemoryRecord))).scalar_one()
            assert row.importance == pytest.approx(expected)
            assert (row.scope, row.tier) == ("agent", "warm")


async def test_unbound_or_blank_tenant_reads_nothing_and_never_raises_a_cast_error(app_role):
    from nexus.database import tenant_session

    (a,) = await _companies(app_role, 1)
    async with tenant_session(a) as db:
        db.add(MemoryRecord(company_id=a, scope="agent", content="visible only to A"))
        await db.commit()

    async with app_role() as db:  # the setting was never set on this connection
        for table in TABLES:
            assert (await db.execute(sa.text(f"SELECT count(*) FROM {table}"))).scalar_one() == 0
        # A blank setting (what a released transaction-local value reads as) is the same.
        await db.execute(sa.text("SELECT set_config('nexus.company_id', '', true)"))
        for table in TABLES:
            assert (await db.execute(sa.text(f"SELECT count(*) FROM {table}"))).scalar_one() == 0
        await db.rollback()
