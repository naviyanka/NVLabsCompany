"""Integration test against real PostgreSQL + pgvector container via Testcontainers.

Verifies:
1. Full Alembic migration upgrade to head on PostgreSQL (with pgvector/pgvector:pg16).
2. Audit log DB-level trigger rejects UPDATE and DELETE operations.
3. Row-Level Security (RLS) enforcement per tenant session context for non-superusers.
"""

import uuid
from datetime import datetime, timezone
import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker

import alembic.config
import alembic.command

from nexus.models.governance import AuditLog
from nexus.models.company import Company
from nexus.models.task import Task


@pytest.fixture(scope="module")
def postgres_container():
    """Start a real PostgreSQL + pgvector container if Docker is available, else skip."""
    pytest.importorskip("testcontainers.postgres")
    from testcontainers.postgres import PostgresContainer

    try:
        container = PostgresContainer("pgvector/pgvector:pg16")
        container.start()
    except Exception as exc:
        pytest.skip(f"Docker/Postgres container unavailable: {exc}")

    yield container
    try:
        container.stop()
    except Exception:
        pass


@pytest.fixture(scope="module")
def migrated_postgres_url(postgres_container):
    """Run real Alembic migrations against the Postgres container."""
    sync_url = postgres_container.get_connection_url()
    async_url = sync_url.replace("postgresql+psycopg2://", "postgresql+asyncpg://").replace("postgresql://", "postgresql+asyncpg://")
    
    alembic_cfg = alembic.config.Config("alembic.ini")
    alembic_cfg.set_main_option("sqlalchemy.url", async_url)
    alembic.command.upgrade(alembic_cfg, "head")

    return async_url


@pytest.fixture(scope="module")
async def app_user_postgres_url(migrated_postgres_url):
    """Create a standard (non-superuser) application role nexus_app to test RLS enforcement."""
    admin_engine = create_async_engine(migrated_postgres_url)
    async with admin_engine.connect() as conn:
        await conn.execute(sa.text("DO $$ BEGIN CREATE ROLE nexus_app LOGIN PASSWORD 'nexus_pass'; EXCEPTION WHEN duplicate_object THEN NULL; END $$;"))
        await conn.execute(sa.text("GRANT ALL ON ALL TABLES IN SCHEMA public TO nexus_app;"))
        await conn.execute(sa.text("GRANT ALL ON ALL SEQUENCES IN SCHEMA public TO nexus_app;"))
        await conn.commit()
    await admin_engine.dispose()

    # Construct URL for nexus_app
    import urllib.parse
    parsed = urllib.parse.urlparse(migrated_postgres_url)
    netloc = f"nexus_app:nexus_pass@{parsed.hostname}:{parsed.port}"
    app_url = urllib.parse.urlunparse((parsed.scheme, netloc, parsed.path, parsed.params, parsed.query, parsed.fragment))
    return app_url


@pytest.mark.asyncio
async def test_postgres_audit_log_immutability(migrated_postgres_url):
    """PostgreSQL trigger audit_log_append_only must reject UPDATE and DELETE."""
    engine = create_async_engine(migrated_postgres_url)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    test_id = uuid.uuid4()
    company_id = uuid.uuid4()

    async with session_factory() as session:
        # Set tenant session variable so RLS allows insert
        await session.execute(
            sa.text("SELECT set_config('nexus.company_id', :cid, false)"),
            {"cid": str(company_id)},
        )

        company = Company(
            id=company_id,
            name="Security Test Corp",
            description="Testing trigger immutability",
            budget_monthly_cents=100000,
        )
        session.add(company)
        await session.flush()

        entry = AuditLog(
            id=test_id,
            company_id=company_id,
            actor_type="user",
            actor_id="admin-1",
            action="security.test",
            created_at=datetime.now(timezone.utc).replace(tzinfo=None),
            sequence_number=1,
            entry_hash="hash1",
            previous_hash="genesis",
        )
        session.add(entry)
        await session.commit()

    # Attempt to UPDATE immutable column
    async with session_factory() as session:
        await session.execute(
            sa.text("SELECT set_config('nexus.company_id', :cid, false)"),
            {"cid": str(company_id)},
        )
        stmt = (
            sa.update(AuditLog)
            .where(AuditLog.id == test_id)
            .values(action="tampered.action")
        )
        with pytest.raises(Exception) as exc_info:
            await session.execute(stmt)
            await session.commit()

        assert "audit_log is append-only" in str(exc_info.value)
        await session.rollback()

    # Attempt to DELETE audit row
    async with session_factory() as session:
        await session.execute(
            sa.text("SELECT set_config('nexus.company_id', :cid, false)"),
            {"cid": str(company_id)},
        )
        stmt = sa.delete(AuditLog).where(AuditLog.id == test_id)
        with pytest.raises(Exception) as exc_info:
            await session.execute(stmt)
            await session.commit()

        assert "audit_log is append-only" in str(exc_info.value)
        await session.rollback()

    await engine.dispose()


@pytest.mark.asyncio
async def test_postgres_row_level_security(app_user_postgres_url):
    """PostgreSQL RLS must isolate rows between tenants even with no WHERE clause."""
    engine = create_async_engine(app_user_postgres_url)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    tenant_a = uuid.uuid4()
    tenant_b = uuid.uuid4()

    # Setup companies and tasks
    async with session_factory() as session:
        session.add(Company(id=tenant_a, name="Tenant A"))
        session.add(Company(id=tenant_b, name="Tenant B"))
        await session.commit()

    # Insert Task as Tenant A
    async with session_factory() as session:
        await session.execute(
            sa.text("SELECT set_config('nexus.company_id', :cid, false)"),
            {"cid": str(tenant_a)},
        )
        task_a = Task(
            id=uuid.uuid4(),
            company_id=tenant_a,
            title="Tenant A Private Task",
            status="pending",
            priority=1,
        )
        session.add(task_a)
        await session.commit()

    # Query without WHERE clause as Tenant B -> returns empty
    async with session_factory() as session:
        await session.execute(
            sa.text("SELECT set_config('nexus.company_id', :cid, false)"),
            {"cid": str(tenant_b)},
        )
        result = await session.execute(sa.select(Task))
        tasks_b = result.scalars().all()
        assert len(tasks_b) == 0

    # Query without WHERE clause as Tenant A -> returns Tenant A task only
    async with session_factory() as session:
        await session.execute(
            sa.text("SELECT set_config('nexus.company_id', :cid, false)"),
            {"cid": str(tenant_a)},
        )
        result = await session.execute(sa.select(Task))
        tasks_a = result.scalars().all()
        assert len(tasks_a) == 1
        assert tasks_a[0].title == "Tenant A Private Task"

    await engine.dispose()
