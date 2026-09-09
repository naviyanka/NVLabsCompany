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
    import os
    if os.environ.get("TEST_DATABASE_URL"):
        yield None
        return

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
    """Run real Alembic migrations against the Postgres container or TEST_DATABASE_URL."""
    import os
    if os.environ.get("TEST_DATABASE_URL"):
        sync_url = os.environ["TEST_DATABASE_URL"]
    else:
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


@pytest.fixture(scope="module")
async def system_user_postgres_url(migrated_postgres_url):
    """Create a privileged system role nexus_system with BYPASSRLS."""
    admin_engine = create_async_engine(migrated_postgres_url)
    async with admin_engine.connect() as conn:
        await conn.execute(sa.text("DO $$ BEGIN CREATE ROLE nexus_system LOGIN PASSWORD 'nexus_sys_pass' BYPASSRLS; EXCEPTION WHEN duplicate_object THEN NULL; END $$;"))
        await conn.execute(sa.text("GRANT ALL ON ALL TABLES IN SCHEMA public TO nexus_system;"))
        await conn.execute(sa.text("GRANT ALL ON ALL SEQUENCES IN SCHEMA public TO nexus_system;"))
        await conn.commit()
    await admin_engine.dispose()

    import urllib.parse
    parsed = urllib.parse.urlparse(migrated_postgres_url)
    netloc = f"nexus_system:nexus_sys_pass@{parsed.hostname}:{parsed.port}"
    sys_url = urllib.parse.urlunparse((parsed.scheme, netloc, parsed.path, parsed.params, parsed.query, parsed.fragment))
    return sys_url


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


@pytest.mark.asyncio
async def test_postgres_idempotency_workflow(app_user_postgres_url):
    """Real PostgreSQL verification of IdempotencyRecord with RLS tenant isolation."""
    from starlette.applications import Starlette
    from starlette.responses import JSONResponse
    from starlette.routing import Route
    from starlette.types import ASGIApp, Receive, Scope, Send
    import httpx
    from datetime import timedelta
    from nexus.models.idempotency import IdempotencyRecord
    from nexus.api.idempotency_middleware import IdempotencyMiddleware
    from nexus.auth.principal import Principal

    engine = create_async_engine(app_user_postgres_url)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    call_count = 0
    should_fail = False

    async def sample_endpoint(request):
        nonlocal call_count
        if should_fail:
            raise RuntimeError("Downstream service crashed")
        call_count += 1
        body = await request.json()
        return JSONResponse({"message": "created", "count": call_count, "name": body.get("name")}, status_code=201)

    app = Starlette(routes=[Route("/api/v1/items", sample_endpoint, methods=["POST"])])

    cid = uuid.uuid4()
    # Create company in DB
    async with session_factory() as session:
        session.add(Company(id=cid, name="Idempotency Test Corp"))
        await session.commit()

    class FakeAuth:
        def __init__(self, app: ASGIApp):
            self.app = app
        async def __call__(self, scope: Scope, receive: Receive, send: Send):
            if scope["type"] == "http":
                scope.setdefault("state", {})["principal"] = Principal(kind="user", company_id=cid, role="admin", email="admin@test.com")
            await self.app(scope, receive, send)

    app.add_middleware(IdempotencyMiddleware)
    app.add_middleware(FakeAuth)

    key = f"key-{uuid.uuid4()}"
    headers = {"Idempotency-Key": key}

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver") as client:
        # 1. First call -> 201 Created
        r1 = await client.post("/api/v1/items", headers=headers, json={"name": "Widget A"})
        assert r1.status_code == 201
        assert r1.json()["count"] == 1
        assert "Idempotent-Replay" not in r1.headers

        # 2. Same key twice -> second returns cached body with Idempotent-Replay: true
        r2 = await client.post("/api/v1/items", headers=headers, json={"name": "Widget A"})
        assert r2.status_code == 201
        assert r2.json()["count"] == 1
        assert r2.headers.get("Idempotent-Replay") == "true"

        # 3. Same key, different body -> 422 IDEMPOTENCY_KEY_REUSED
        r3 = await client.post("/api/v1/items", headers=headers, json={"name": "Widget B"})
        assert r3.status_code == 422
        assert r3.json()["code"] == "IDEMPOTENCY_KEY_REUSED"

        # 4. Handler raises -> row removed, client can retry
        fail_key = f"fail-key-{uuid.uuid4()}"
        fail_headers = {"Idempotency-Key": fail_key}
        should_fail = True
        with pytest.raises(RuntimeError):
            await client.post("/api/v1/items", headers=fail_headers, json={"name": "Crash"})

        # Verify row was deleted, not stuck in_flight or marked complete
        should_fail = False
        r_retry = await client.post("/api/v1/items", headers=fail_headers, json={"name": "Crash"})
        assert r_retry.status_code == 201
        assert r_retry.json()["name"] == "Crash"

        # 5. Expired in_flight row -> reclaimed, not 409
        stuck_key = f"stuck-key-{uuid.uuid4()}"
        async with session_factory() as session:
            await session.execute(
                sa.text("SELECT set_config('nexus.company_id', :cid, false)"),
                {"cid": str(cid)},
            )
            stuck_rec = IdempotencyRecord(
                company_id=cid,
                idem_key=stuck_key,
                endpoint="/api/v1/items",
                request_hash="stale-hash",
                state="in_flight",
                created_at=datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(hours=2),
                expires_at=datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(hours=1),
            )
            session.add(stuck_rec)
            await session.commit()

        r_reclaimed = await client.post("/api/v1/items", headers={"Idempotency-Key": stuck_key}, json={"name": "Reclaimed"})
        assert r_reclaimed.status_code == 201
        assert r_reclaimed.json()["name"] == "Reclaimed"

    await engine.dispose()


@pytest.mark.asyncio
async def test_postgres_atomic_budget_reservations_concurrency(app_user_postgres_url):
    """Under 50 concurrent requests competing for a $100 cap ($10 each),
    exactly 10 must succeed and 40 must be denied, never violating CHECK constraint."""
    import asyncio
    from nexus.models.budget import BudgetPolicy, CostEvent
    from nexus.services.budget_service import BudgetService

    engine = create_async_engine(app_user_postgres_url)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    cid = uuid.uuid4()
    policy_id = uuid.uuid4()

    async with session_factory() as session:
        # Create company first and commit
        session.add(Company(id=cid, name="Budget Concurrency Corp"))
        await session.commit()

    async with session_factory() as session:
        await session.execute(
            sa.text("SELECT set_config('nexus.company_id', :cid, false)"),
            {"cid": str(cid)},
        )
        # Create budget policy: $100 (10,000 cents) limit
        policy = BudgetPolicy(
            id=policy_id,
            company_id=cid,
            scope_type="company",
            scope_id=cid,
            metric="cost_cents",
            window_kind="monthly",
            amount=10000,
            spent_cents=0,
            reserved_cents=0,
            warn_percent=80,
            hard_stop_enabled=True,
            is_active=True,
        )
        session.add(policy)
        await session.commit()

    async def attempt_reserve(worker_id: int):
        # Each worker opens its own DB session and sets tenant RLS context
        async with session_factory() as session:
            await session.execute(
                sa.text("SELECT set_config('nexus.company_id', :cid, false)"),
                {"cid": str(cid)},
            )
            svc = BudgetService(session)
            # Try to reserve $10 (1000 cents)
            allowed, reservation, check = await svc.reserve(
                company_id=cid,
                estimate_cents=1000,
                scope_type="company",
                scope_id=cid,
            )
            return allowed, reservation

    # Launch 50 concurrent tasks
    tasks = [attempt_reserve(i) for i in range(50)]
    results = await asyncio.gather(*tasks)

    successes = [r for r in results if r[0] is True]
    failures = [r for r in results if r[0] is False]

    assert len(successes) == 10, f"Expected exactly 10 successes, got {len(successes)}"
    assert len(failures) == 40, f"Expected exactly 40 failures, got {len(failures)}"

    # Check database state directly
    async with session_factory() as session:
        await session.execute(
            sa.text("SELECT set_config('nexus.company_id', :cid, false)"),
            {"cid": str(cid)},
        )
        res = await session.execute(sa.select(BudgetPolicy).where(BudgetPolicy.id == policy_id))
        pol = res.scalar_one()
        assert pol.reserved_cents == 10000
        assert pol.spent_cents == 0
        assert pol.spent_cents + pol.reserved_cents <= pol.amount

        # Commit half of the reservations ($10 -> actual $8) and release the other half
        svc = BudgetService(session)
        for i, (allowed, res_event) in enumerate(successes):
            await session.execute(
                sa.text("SELECT set_config('nexus.company_id', :cid, false)"),
                {"cid": str(cid)},
            )
            if i < 5:
                # Settle for 800 cents
                committed = await svc.commit_reservation(res_event.id, cost_cents=800)
                assert committed is True
            else:
                # Release hold
                released = await svc.release_reservation(res_event.id)
                assert released is True

        await session.execute(
            sa.text("SELECT set_config('nexus.company_id', :cid, false)"),
            {"cid": str(cid)},
        )
        res = await session.execute(sa.select(BudgetPolicy).where(BudgetPolicy.id == policy_id))
        pol = res.scalar_one()
        print("Final pol:", pol.spent_cents, pol.reserved_cents)
        # 5 committed at 800 cents = 4000 spent_cents, 0 remaining reserved_cents
        assert pol.spent_cents == 4000
        assert pol.reserved_cents == 0

    await engine.dispose()


@pytest.mark.asyncio
async def test_orchestrator_tick_sees_work_as_app_role(
    app_user_postgres_url, system_user_postgres_url, monkeypatch
):
    """Positive control: orchestrator discovers cross-tenant goals under system role,
    and drives/creates subtasks under standard app role with RLS enforcement (WP-15b)."""
    from nexus.models.agent import Agent
    from nexus.models.task import Goal, Task
    from nexus.runtime.orchestrator import _tick
    from nexus.config import settings

    # Wire database settings so system_session and tenant_session connect to test Postgres
    monkeypatch.setattr(settings, "database_url", app_user_postgres_url)
    monkeypatch.setattr(settings, "system_database_url", system_user_postgres_url)

    app_engine = create_async_engine(app_user_postgres_url)
    app_factory = async_sessionmaker(app_engine, class_=AsyncSession, expire_on_commit=False)

    sys_engine = create_async_engine(system_user_postgres_url)
    sys_factory = async_sessionmaker(sys_engine, class_=AsyncSession, expire_on_commit=False)

    monkeypatch.setattr("nexus.database.async_session_factory", app_factory)
    monkeypatch.setattr("nexus.database._system_session_factory", sys_factory)

    cid = uuid.uuid4()
    agent_id = uuid.uuid4()
    goal_id = uuid.uuid4()

    # 1. Setup company, agent, and goal under app role with tenant context
    async with app_factory() as session:
        await session.execute(
            sa.text("SELECT set_config('nexus.company_id', :cid, false)"),
            {"cid": str(cid)},
        )
        company = Company(id=cid, name="RLS Orchestrator Test Corp")
        session.add(company)
        agent = Agent(
            id=agent_id,
            company_id=cid,
            name="Orchestrator Agent",
            role="Worker",
            capabilities=["task_execution"],
        )
        session.add(agent)
        goal = Goal(
            id=goal_id,
            company_id=cid,
            title="Deploy high-availability cluster",
            description="Setup cluster and configure redundancy",
            owner_agent_id=agent_id,
            status="active",
        )
        session.add(goal)
        await session.commit()

    # 2. Invoke real _tick() directly
    await _tick()

    # 3. Verify subtasks exist under tenant session
    async with app_factory() as session:
        await session.execute(
            sa.text("SELECT set_config('nexus.company_id', :cid, false)"),
            {"cid": str(cid)},
        )
        res = await session.execute(sa.select(Task).where(Task.goal_id == goal_id))
        subtasks = res.scalars().all()
        assert len(subtasks) > 0, "Subtasks should be created by real _tick() under tenant context"

    await app_engine.dispose()
    await sys_engine.dispose()
