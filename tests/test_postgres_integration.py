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
from nexus.models.connection import LLMConnection

pytestmark = [pytest.mark.postgres, pytest.mark.integration]


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
    """PostgreSQL trigger audit_log_append_only must reject UPDATE and DELETE.

    The row is written by the production writer, so it takes the next link of
    its company's chain; the suite can run again on the same database.
    """
    from nexus.governance.audit_service import record_audit

    engine = create_async_engine(migrated_postgres_url)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

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

        await record_audit(
            company_id,
            "security.test",
            actor_type="user",
            actor_id="admin-1",
            db=session,
            raise_on_error=True,
        )
        await session.commit()
        test_id = (
            await session.execute(sa.select(AuditLog.id).where(AuditLog.company_id == company_id))
        ).scalar_one()

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
async def test_connection_rls_isolates_companies(app_user_postgres_url):
    """WP-22b: RLS on llm_connections isolates rows between tenants.

    Fails at baseline because the llm_connections table does not exist.
    """
    engine = create_async_engine(app_user_postgres_url)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    tenant_a = uuid.uuid4()
    tenant_b = uuid.uuid4()

    async with session_factory() as session:
        session.add(Company(id=tenant_a, name="Tenant A"))
        session.add(Company(id=tenant_b, name="Tenant B"))
        await session.commit()

    async with session_factory() as session:
        await session.execute(
            sa.text("SELECT set_config('nexus.company_id', :cid, false)"),
            {"cid": str(tenant_a)},
        )
        session.add(
            LLMConnection(
                id=uuid.uuid4(),
                company_id=tenant_a,
                name="A gateway",
                base_url="https://a.example.com/v1",
                wire_format="openai",
            )
        )
        await session.commit()

    # Tenant B sees nothing, no WHERE clause
    async with session_factory() as session:
        await session.execute(
            sa.text("SELECT set_config('nexus.company_id', :cid, false)"),
            {"cid": str(tenant_b)},
        )
        result = await session.execute(sa.select(LLMConnection))
        assert len(result.scalars().all()) == 0

    # Tenant A sees only its own
    async with session_factory() as session:
        await session.execute(
            sa.text("SELECT set_config('nexus.company_id', :cid, false)"),
            {"cid": str(tenant_a)},
        )
        result = await session.execute(sa.select(LLMConnection))
        conns = result.scalars().all()
        assert len(conns) == 1
        assert conns[0].name == "A gateway"

    await engine.dispose()


@pytest.mark.asyncio
async def test_postgres_idempotency_workflow(app_user_postgres_url, monkeypatch):
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

    from nexus.config import settings

    engine = create_async_engine(app_user_postgres_url)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    # The middleware must reach PostgreSQL as the application role, under RLS.
    monkeypatch.setattr(settings, "database_url", app_user_postgres_url)
    monkeypatch.setattr("nexus.database.async_session_factory", session_factory)

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
        # No relationship() links these models, so the unit of work does not
        # order the inserts by foreign key; write the company first.
        await session.flush()
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


@pytest.mark.asyncio
async def test_chat_turn_claim_race_ordering_and_rls(
    app_user_postgres_url, system_user_postgres_url, monkeypatch
):
    """Durable chat turns on PostgreSQL as the application role.

    Racing claims from many workers have one winner, a session's later turn
    cannot be claimed while an earlier one is unfinished, another tenant sees
    none of the rows (RLS, no WHERE clause), and the cross-tenant recovery
    sweep finds an expired lease through the system role.
    """
    import asyncio
    from datetime import timedelta

    from nexus.config import settings
    from nexus.models.agent import Agent
    from nexus.models.agent_session import AgentSessionRecord
    from nexus.models.chat_turn import ChatTurn
    from nexus.runtime import chat_turns

    monkeypatch.setattr(settings, "database_url", app_user_postgres_url)
    monkeypatch.setattr(settings, "system_database_url", system_user_postgres_url)
    app_engine = create_async_engine(app_user_postgres_url)
    app_factory = async_sessionmaker(app_engine, class_=AsyncSession, expire_on_commit=False)
    sys_engine = create_async_engine(system_user_postgres_url)
    sys_factory = async_sessionmaker(sys_engine, class_=AsyncSession, expire_on_commit=False)
    monkeypatch.setattr("nexus.database.async_session_factory", app_factory)
    monkeypatch.setattr("nexus.database._system_session_factory", sys_factory)

    mine, theirs = uuid.uuid4(), uuid.uuid4()
    session_id = uuid.uuid4()
    first, second = uuid.uuid4(), uuid.uuid4()
    for cid in (mine, theirs):
        async with app_factory() as session:
            await session.execute(
                sa.text("SELECT set_config('nexus.company_id', :cid, false)"), {"cid": str(cid)}
            )
            session.add(Company(id=cid, name=f"Turns {cid}"))
            await session.commit()
    async with app_factory() as session:
        await session.execute(
            sa.text("SELECT set_config('nexus.company_id', :cid, false)"), {"cid": str(mine)}
        )
        agent = Agent(company_id=mine, name="Turn Employee", role="engineer")
        session.add(agent)
        await session.flush()
        session.add(AgentSessionRecord(id=session_id, company_id=mine, agent_id=agent.id))
        await session.flush()
        for turn_id, seq in ((first, 1), (second, 2)):
            session.add(
                ChatTurn(
                    id=turn_id, company_id=mine, agent_id=agent.id, session_id=session_id,
                    idempotency_key=f"key-{seq}", turn_seq=seq,
                )
            )
        await session.commit()

    try:
        won = await asyncio.gather(
            *(chat_turns.claim(first, mine, f"worker-{i}") for i in range(8))
        )
        assert sum(w is not None for w in won) == 1
        assert await chat_turns.claim(second, mine, "worker-x") is None

        # Another tenant: no rows without a WHERE clause, and no claim.
        async with app_factory() as session:
            await session.execute(
                sa.text("SELECT set_config('nexus.company_id', :cid, false)"),
                {"cid": str(theirs)},
            )
            assert (await session.execute(sa.select(ChatTurn))).scalars().all() == []
        assert await chat_turns.get_turn(theirs, first) is None
        assert await chat_turns.claim(second, theirs, "worker-y") is None

        outcome = await chat_turns.sweep(now=chat_turns._now() + timedelta(minutes=5))
        assert outcome["recovered"] == 1
        assert (await chat_turns.get_turn(mine, first)).status == "queued"
        assert f"company:{mine}" in outcome
    finally:
        await app_engine.dispose()
        await sys_engine.dispose()


@pytest.mark.asyncio
async def test_task_attempt_claim_race_and_rls(
    app_user_postgres_url, system_user_postgres_url, monkeypatch
):
    """Task attempts and their effect ledger on PostgreSQL as the application role.

    One of many racing claims wins, the partial unique index refuses a second
    active attempt, another tenant sees no attempt or effect row (RLS, no WHERE
    clause), and the system-role sweep recovers an expired lease.
    """
    import asyncio
    from datetime import timedelta

    from sqlalchemy.exc import IntegrityError

    from nexus.config import settings
    from nexus.models.agent import Agent
    from nexus.models.task_attempt import TaskAttempt, WorkEffect
    from nexus.runtime import task_attempts

    monkeypatch.setattr(settings, "database_url", app_user_postgres_url)
    monkeypatch.setattr(settings, "system_database_url", system_user_postgres_url)
    app_engine = create_async_engine(app_user_postgres_url)
    app_factory = async_sessionmaker(app_engine, class_=AsyncSession, expire_on_commit=False)
    sys_engine = create_async_engine(system_user_postgres_url)
    sys_factory = async_sessionmaker(sys_engine, class_=AsyncSession, expire_on_commit=False)
    monkeypatch.setattr("nexus.database.async_session_factory", app_factory)
    monkeypatch.setattr("nexus.database._system_session_factory", sys_factory)

    async def as_tenant(session, cid):
        await session.execute(
            sa.text("SELECT set_config('nexus.company_id', :cid, false)"), {"cid": str(cid)}
        )

    mine, theirs = uuid.uuid4(), uuid.uuid4()
    for cid in (mine, theirs):
        async with app_factory() as session:
            await as_tenant(session, cid)
            session.add(Company(id=cid, name=f"Attempts {cid}"))
            await session.commit()
    async with app_factory() as session:
        await as_tenant(session, mine)
        agent = Agent(company_id=mine, name="Worker", role="engineer", adapter_type="cli",
                      adapter_config={"backend": "claude"})
        session.add(agent)
        await session.flush()
        task = Task(company_id=mine, title="Work", assigned_agent_id=agent.id,
                    work_spec={"mode": "read_only"})
        session.add(task)
        await session.flush()
        attempt = TaskAttempt(company_id=mine, task_id=task.id, agent_id=agent.id,
                              attempt_number=1, idempotency_key="k1")
        session.add(attempt)
        await session.flush()
        session.add(WorkEffect(company_id=mine, task_id=task.id, attempt_id=attempt.id,
                               kind="git_commit", effect_key=f"commit:{attempt.id}"))
        await session.commit()

    try:
        async with app_factory() as session:
            await as_tenant(session, mine)
            session.add(TaskAttempt(company_id=mine, task_id=task.id, agent_id=agent.id,
                                    attempt_number=2, idempotency_key="k2"))
            with pytest.raises(IntegrityError):
                await session.commit()

        won = await asyncio.gather(
            *(task_attempts.claim(attempt.id, mine, f"worker-{i}") for i in range(8))
        )
        assert sum(w is not None for w in won) == 1

        async with app_factory() as session:
            await as_tenant(session, theirs)
            assert (await session.execute(sa.select(TaskAttempt))).scalars().all() == []
            assert (await session.execute(sa.select(WorkEffect))).scalars().all() == []
        assert await task_attempts.get_attempt(theirs, attempt.id) is None
        assert await task_attempts.claim(attempt.id, theirs, "worker-y") is None

        outcome = await task_attempts.sweep(now=task_attempts._now() + timedelta(minutes=5))
        assert outcome["recovered"] == 1
        recovered = await task_attempts.get_attempt(mine, attempt.id)
        assert (recovered.status, recovered.recoveries) == ("queued", 1)
    finally:
        await app_engine.dispose()
        await sys_engine.dispose()


@pytest.mark.asyncio
async def test_secret_backend_loads_from_a_pooled_engine_inside_a_running_loop(
    migrated_postgres_url,
):
    """Regression: loading secrets from sync code while the app loop runs.

    The shared engine's pooled asyncpg connection belongs to this loop; the
    backend's sync bridge runs on another loop and used to fail with "attached
    to a different loop", silently starting with an empty store.
    """
    from nexus.governance.secret_backend import FernetSecretBackend

    engine = create_async_engine(migrated_postgres_url)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    cid = uuid.uuid4()
    async with factory() as session:
        session.add(Company(id=cid, name="Secrets"))
        await session.commit()  # the pool now holds a connection bound to this loop
    try:
        writer = FernetSecretBackend("k" * 32, session_factory=factory, company_id=cid)
        assert writer.encrypt("gh-token", "s3cret")
        reader = FernetSecretBackend("k" * 32, session_factory=factory, company_id=cid)
        assert reader.decrypt("gh-token") == "s3cret"
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_tenant_session_keeps_tenant_context_across_commits(app_user_postgres_url, monkeypatch):
    """Regression: a commit inside ``tenant_session`` lost the tenant context.

    The context was set once on the first pooled connection. After a commit
    the session returns that connection to the (FIFO) pool, so the next
    statement ran on another connection with no tenant set: RLS hid the rows
    the session had just written (an employee's new worktree read back as
    ``WORKTREE_NOT_FOUND``), and the first connection went back to the pool
    still carrying the tenant for whoever checked it out next.
    """
    import asyncio

    from nexus.config import settings
    from nexus.database import tenant_session

    monkeypatch.setattr(settings, "database_url", app_user_postgres_url)
    engine = create_async_engine(app_user_postgres_url)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    monkeypatch.setattr("nexus.database.async_session_factory", factory)
    setting = sa.text("SELECT current_setting('nexus.company_id', true), pg_backend_pid()")

    async def warm() -> None:
        async with engine.connect() as conn:
            await conn.execute(sa.text("SELECT 1"))
            await asyncio.sleep(0)  # hold it while the other one connects

    try:
        # Two idle pooled connections, so a commit hands the session another one.
        await asyncio.gather(warm(), warm())
        cid = uuid.uuid4()
        async with tenant_session(cid) as db:
            before, pid_before = (await db.execute(setting)).one()
            await db.commit()
            after, pid_after = (await db.execute(setting)).one()
        assert pid_after != pid_before, "the scenario needs the commit to switch connections"
        assert before == after == str(cid)

        async def untenanted() -> str | None:
            async with factory() as session:
                value = (await session.execute(setting)).one()[0]
                await asyncio.sleep(0)
                return value

        # No pooled connection keeps the tenant once the session is over.
        assert set(await asyncio.gather(untenanted(), untenanted())) <= {None, ""}
    finally:
        await engine.dispose()


async def test_background_audit_write_carries_the_tenant(app_user_postgres_url, monkeypatch):
    """Regression: ``record_audit`` without a session wrote with no tenant.

    Its own session inherited whatever tenant a pooled connection happened to
    carry. On a clean connection the RLS policy rejected the row, and the
    failure was only logged, so background events (attempt claims, cancels,
    chat responses) were silently missing from the audit log.
    """
    from nexus.config import settings
    from nexus.governance.audit_service import record_audit

    monkeypatch.setattr(settings, "database_url", app_user_postgres_url)
    engine = create_async_engine(app_user_postgres_url)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    monkeypatch.setattr("nexus.database.async_session_factory", factory)
    cid = uuid.uuid4()
    try:
        async with factory() as session:
            session.add(Company(id=cid, name="Audited"))
            await session.commit()

        await record_audit(cid, "test.background_event", resource_id="r-1", raise_on_error=True)

        async with factory() as session:
            await session.execute(
                sa.text("SELECT set_config('nexus.company_id', :cid, false)"), {"cid": str(cid)}
            )
            rows = (await session.execute(sa.select(AuditLog.action))).scalars().all()
        assert rows == ["test.background_event"]
    finally:
        await engine.dispose()


@pytest.fixture
async def app_role(app_user_postgres_url, monkeypatch):
    """The application's session factory, connected as the RLS-bound app role."""
    from nexus.config import settings

    monkeypatch.setattr(settings, "database_url", app_user_postgres_url)
    engine = create_async_engine(app_user_postgres_url)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    monkeypatch.setattr("nexus.database.async_session_factory", factory)
    yield factory
    await engine.dispose()


async def _companies(factory, count: int) -> list[uuid.UUID]:
    ids = [uuid.uuid4() for _ in range(count)]
    async with factory() as session:
        for cid in ids:
            session.add(Company(id=cid, name=f"Tenant {cid}"))
        await session.commit()
    return ids


async def test_concurrent_audit_writes_form_one_valid_chain_per_company(app_role):
    """Racing writers of two companies, through both writer paths, as the app role.

    Each company gets its own gap-free chain from genesis, both verify, no
    sequence repeats within a company, no row is left unchained, and the
    verify endpoint of one company reads only that company's chain.
    """
    import asyncio

    from nexus.api.routes.audit import verify_audit_chain
    from nexus.database import tenant_session
    from nexus.governance.audit_service import record_audit

    first, second = await _companies(app_role, 2)
    per_company = 12

    async def in_callers_session(cid: uuid.UUID, index: int) -> None:
        async with tenant_session(cid) as db:
            await record_audit(cid, f"caller.{index}", db=db, raise_on_error=True)
            await db.commit()

    writes = []
    for index in range(per_company // 2):
        for cid in (first, second):
            writes.append(record_audit(cid, f"own.{index}", raise_on_error=True))
            writes.append(in_callers_session(cid, index))
    await asyncio.gather(*writes)

    for cid, other in ((first, second), (second, first)):
        async with tenant_session(cid) as db:
            rows = (
                await db.execute(sa.select(AuditLog).order_by(AuditLog.sequence_number))
            ).scalars().all()
            leaked = (
                await db.execute(sa.select(AuditLog).where(AuditLog.company_id == other))
            ).scalars().all()
        assert leaked == []
        assert {row.company_id for row in rows} == {cid}
        assert [row.sequence_number for row in rows] == list(range(1, per_company + 1))
        assert rows[0].previous_hash == "genesis"
        assert await verify_audit_chain(cid, db=None) == {
            "valid": True, "checked": per_company, "scope": "company",
        }


async def test_an_audit_write_without_a_tenant_is_refused_not_unchained(app_role):
    """A row the app role may not insert is not retried into an unchained row."""
    from nexus.governance.audit_service import record_audit

    (cid,) = await _companies(app_role, 1)
    async with app_role() as db:  # no tenant context
        with pytest.raises(RuntimeError, match="audit log write failed"):
            await record_audit(cid, "no.tenant", db=db, raise_on_error=True)
        await db.rollback()
    async with app_role() as db:
        await db.execute(
            sa.text("SELECT set_config('nexus.company_id', :cid, false)"), {"cid": str(cid)}
        )
        assert (await db.execute(sa.select(AuditLog))).scalars().all() == []


async def test_alternating_tenants_on_one_pooled_connection(app_user_postgres_url, monkeypatch):
    """tenant_session on a pool of one: every session sees only its own tenant."""
    from nexus.config import settings
    from nexus.database import tenant_session

    monkeypatch.setattr(settings, "database_url", app_user_postgres_url)
    engine = create_async_engine(app_user_postgres_url, pool_size=1, max_overflow=0)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    monkeypatch.setattr("nexus.database.async_session_factory", factory)
    try:
        tenants = await _companies(factory, 2)
        pids = set()
        for round_ in range(3):
            for cid in tenants:
                async with tenant_session(cid) as db:
                    db.add(Task(company_id=cid, title=f"{cid}:{round_}"))
                    await db.commit()
                    pids.add((await db.execute(sa.text("SELECT pg_backend_pid()"))).scalar_one())
                    titles = (await db.execute(sa.select(Task.title))).scalars().all()
                assert sorted(titles) == [f"{cid}:{r}" for r in range(round_ + 1)]
        assert len(pids) == 1, "the scenario needs one shared connection"
        async with factory() as db:
            assert (await db.execute(sa.select(Task))).scalars().all() == []
    finally:
        await engine.dispose()


async def test_a_session_without_a_tenant_cannot_mutate_tenant_rows(app_role):
    from sqlalchemy.exc import DBAPIError

    from nexus.database import tenant_session

    (cid,) = await _companies(app_role, 1)
    async with tenant_session(cid) as db:
        task = Task(company_id=cid, title="protected")
        db.add(task)
        await db.commit()

    async with app_role() as db:
        updated = await db.execute(sa.update(Task).where(Task.id == task.id).values(title="x"))
        deleted = await db.execute(sa.delete(Task).where(Task.id == task.id))
        assert (updated.rowcount, deleted.rowcount) == (0, 0)
        await db.commit()
    async with app_role() as db:
        db.add(Task(company_id=cid, title="smuggled"))
        with pytest.raises(DBAPIError, match="row-level security"):
            await db.commit()

    async with tenant_session(cid) as db:
        assert (await db.execute(sa.select(Task.title))).scalars().all() == ["protected"]


@pytest.mark.parametrize(
    "path, body, title",
    [
        (
            "/api/v1/channels/slack/events",
            {
                "type": "event_callback",
                "event": {"type": "app_mention", "text": "hi", "user": "U1"},
            },
            "Slack mention from U1",
        ),
        (
            "/api/v1/channels/telegram/webhook",
            {"message": {"text": "/task write the report", "chat": {"id": 7}}},
            "write the report",
        ),
    ],
)
async def test_channel_webhooks_write_into_the_callers_company(
    app_role, monkeypatch, path, body, title
):
    """Slack and Telegram tasks land in the caller's company under RLS."""
    import httpx

    from nexus.config import settings
    from nexus.database import tenant_session
    from nexus.main import app

    caller, other = await _companies(app_role, 2)
    monkeypatch.setattr(settings, "auth_enabled", False)  # X-Company-Id is the principal
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(path, json=body, headers={"X-Company-Id": str(caller)})
    assert response.status_code == 200

    async with tenant_session(caller) as db:
        assert (await db.execute(sa.select(Task.title))).scalars().all() == [title]
    async with tenant_session(other) as db:
        assert (await db.execute(sa.select(Task))).scalars().all() == []


async def test_hiring_races_hold_limits_and_hire_once(app_role, monkeypatch):
    """Manager hiring on PostgreSQL as the app role.

    Racing auto-approved submissions cannot exceed the headcount limit, racing
    human approvals of one request create one employee, and another tenant
    sees none of the requests (RLS, no WHERE clause).
    """
    import asyncio

    from fastapi import HTTPException

    from nexus.adapters import cli_registry
    from nexus.auth.principal import Principal
    from nexus.database import tenant_session
    from nexus.models.agent import Agent
    from nexus.models.policy import Policy
    from nexus.models.tool import ToolPolicy
    from nexus.services import hiring_service

    monkeypatch.setattr(cli_registry.shutil, "which", lambda cmd: f"/opt/bin/{cmd}")
    monkeypatch.setattr(cli_registry, "_shared_registry", None)
    auto_co, manual_co, other = await _companies(app_role, 3)
    managers = {}
    for cid in (auto_co, manual_co):
        async with tenant_session(cid) as db:
            manager = Agent(company_id=cid, name="Lead", role="manager", adapter_type="cli",
                            adapter_config={"backend": "claude"}, model="")
            db.add_all([manager, ToolPolicy(company_id=cid, name="hiring", effect="allow",
                                            conditions={"tool_name": ["manager_request_hire"]})])
            if cid == auto_co:
                db.add(Policy(company_id=cid, name="hiring", priority=10, rules={"hiring": {
                    "max_headcount": 2,
                    "auto_approve": {"enabled": True, "max_monthly_cents": 5000,
                                     "max_one_time_cents": 5000},
                }}))
            await db.commit()
            managers[cid] = manager.id

    def request(key: str, once: int = 0) -> hiring_service.HireRequest:
        # 800 a month: a 9600-cent first year, under the signature quorum.
        return hiring_service.HireRequest(
            role="engineer", title=f"Engineer {key}", reason="Ship", backend="claude",
            estimated_monthly_cents=800, estimated_one_time_cents=once, idempotency_key=key,
        )

    async def submit(cid: uuid.UUID, key: str, once: int = 0) -> str:
        async with tenant_session(cid) as db:
            approval, _ = await hiring_service.submit(
                db, cid, managers[cid], request(key, once), "agent:x"
            )
            await db.commit()
            return approval.status

    # Headcount 2 leaves room for one hire next to the manager.
    statuses = await asyncio.gather(*(submit(auto_co, f"k{i}") for i in range(6)))
    assert sorted(statuses) == ["approved"] + ["rejected"] * 5
    async with tenant_session(auto_co) as db:
        hired = (
            await db.execute(sa.select(Agent).where(Agent.role == "engineer"))
        ).scalars().all()
    assert len(hired) == 1 and hired[0].manager_id == managers[auto_co]

    assert await submit(manual_co, "one") == "pending"
    [pending] = await _hiring(manual_co)
    admin = Principal(kind="user", company_id=manual_co, role="admin", user_id=uuid.uuid4(),
                      email="admin@example.test")

    async def approve() -> str:
        async with tenant_session(manual_co) as db:
            approval = await hiring_service.approve(db, manual_co, pending.id, admin, None)
            await db.commit()
            return approval.status

    assert await asyncio.gather(*(approve() for _ in range(5))) == ["approved"] * 5
    async with tenant_session(manual_co) as db:
        hired = (
            await db.execute(sa.select(Agent).where(Agent.role == "engineer"))
        ).scalars().all()
    assert [a.id for a in hired] == [hiring_service.employee_id_for(pending.id)]

    # Above the quorum threshold: racing signatures, then racing final approvals.
    from nexus.models.governance import Approval, ApprovalSignerKey
    from nexus.services.approval_service import ApprovalService
    from tests.test_approval_signing import _keypair, _sign

    assert await submit(manual_co, "big", once=20_000) == "pending"
    [quorum] = [a for a in await _hiring(manual_co) if a.payload["amount_cents"] == 29_600]
    assert quorum.required_signatures == 2
    keys = {subject: _keypair() for subject in ("alice", "bob")}
    async with tenant_session(manual_co) as db:
        db.add_all([ApprovalSignerKey(company_id=manual_co, subject=s, public_key=k[1])
                    for s, k in keys.items()])
        await db.commit()

    async def sign(subject: str) -> None:
        async with tenant_session(manual_co) as db:
            approval = await db.get(Approval, quorum.id)
            signature = _sign(keys[subject][0], approval)
            await ApprovalService(db).add_signature(quorum.id, subject, signature)
            await db.commit()

    async def approve_big() -> str:
        async with tenant_session(manual_co) as db:
            try:
                approval = await hiring_service.approve(db, manual_co, quorum.id, admin, None)
            except HTTPException as exc:
                return exc.detail["code"]
            await db.commit()
            return approval.status

    assert await approve_big() == "APPROVAL_QUORUM_NOT_MET"
    await asyncio.gather(sign("alice"), sign("bob"))
    assert await asyncio.gather(*(approve_big() for _ in range(5))) == ["approved"] * 5
    async with tenant_session(manual_co) as db:
        hired = (await db.execute(sa.select(Agent.id).where(Agent.role == "engineer"))).all()
    expected = [hiring_service.employee_id_for(a.id) for a in (pending, quorum)]
    assert sorted(r.id for r in hired) == sorted(expected)

    assert await _hiring(other) == []


async def _hiring(cid: uuid.UUID) -> list:
    from nexus.database import tenant_session
    from nexus.models.governance import Approval

    async with tenant_session(cid) as db:
        return (await db.execute(sa.select(Approval))).scalars().all()


@pytest.mark.asyncio
async def test_organization_snapshot_race_and_rls(
    app_user_postgres_url, system_user_postgres_url, monkeypatch
):
    """Organization snapshots on PostgreSQL as the application role.

    Racing generations create one version; an unchanged payload creates none;
    a changed one creates the next; another tenant sees no snapshot or state
    row (RLS, no WHERE clause); and the system-role tick reconciles every
    company.
    """
    import asyncio

    from nexus.config import settings
    from nexus.models.organization_snapshot import OrganizationSnapshot, OrganizationSnapshotState
    from nexus.services import org_snapshot

    monkeypatch.setattr(settings, "database_url", app_user_postgres_url)
    monkeypatch.setattr(settings, "system_database_url", system_user_postgres_url)
    app_engine = create_async_engine(app_user_postgres_url)
    app_factory = async_sessionmaker(app_engine, class_=AsyncSession, expire_on_commit=False)
    sys_engine = create_async_engine(system_user_postgres_url)
    sys_factory = async_sessionmaker(sys_engine, class_=AsyncSession, expire_on_commit=False)
    monkeypatch.setattr("nexus.database.async_session_factory", app_factory)
    monkeypatch.setattr("nexus.database._system_session_factory", sys_factory)

    async def as_tenant(session, cid):
        await session.execute(
            sa.text("SELECT set_config('nexus.company_id', :cid, false)"), {"cid": str(cid)}
        )

    mine, theirs = uuid.uuid4(), uuid.uuid4()
    for cid in (mine, theirs):
        async with app_factory() as session:
            await as_tenant(session, cid)
            session.add(Company(id=cid, name=f"Snapshot {cid}"))
            await session.commit()

    try:
        results = await asyncio.gather(*(org_snapshot.generate(mine) for _ in range(8)))
        assert [r["outcome"] for r in results].count("created") == 1
        assert (await org_snapshot.generate(mine))["outcome"] == "unchanged"
        async with app_factory() as session:
            await as_tenant(session, mine)
            session.add(Task(company_id=mine, title="New work"))
            await session.commit()
        assert (await org_snapshot.generate(mine)) == {"outcome": "created", "version": 2}

        async with app_factory() as session:
            await as_tenant(session, theirs)
            assert (await session.execute(sa.select(OrganizationSnapshot))).scalars().all() == []
            assert (
                await session.execute(sa.select(OrganizationSnapshotState))
            ).scalars().all() == []
            empty = await org_snapshot.read(session, mine)
        assert empty["snapshot"] is None and empty["version"] is None

        # Other tests' companies share this database; reconcile them all.
        monkeypatch.setattr(org_snapshot, "MAX_PER_TICK", 10_000)
        reconciled = await org_snapshot.tick()
        assert theirs in reconciled
        async with app_factory() as session:
            await as_tenant(session, mine)
            versions = (
                await session.execute(sa.select(OrganizationSnapshot.version))
            ).scalars().all()
        assert sorted(versions) == [1, 2]
    finally:
        await app_engine.dispose()
        await sys_engine.dispose()


@pytest.mark.asyncio
async def test_postgres_ceo_designation_schema(migrated_postgres_url):
    """The migration leaves ``agents.is_ceo`` and a partial unique index: one CEO per company."""
    engine = create_async_engine(migrated_postgres_url)
    async with engine.connect() as conn:
        column = (await conn.execute(sa.text(
            "SELECT 1 FROM information_schema.columns "
            "WHERE table_name = 'agents' AND column_name = 'is_ceo'"))).scalar()
        index = (await conn.execute(sa.text(
            "SELECT indexdef FROM pg_indexes WHERE indexname = 'uq_agents_one_ceo'"))).scalar()
    await engine.dispose()
    assert column == 1
    assert "UNIQUE" in index and "is_ceo" in index


@pytest.mark.asyncio
async def test_postgres_concurrent_ceo_appointments_have_one_winner(migrated_postgres_url):
    """Two appointments that both saw no CEO race: one wins, the other gets CEO_CONFLICT."""
    import asyncio

    from fastapi import HTTPException

    from nexus.auth.principal import Principal
    from nexus.models.agent import Agent
    from nexus.services import ceo_service

    engine = create_async_engine(migrated_postgres_url)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    company_id = uuid.uuid4()
    async with session_factory() as session:
        session.add(Company(id=company_id, name="CEO Race Corp"))
        await session.flush()
        candidates = [Agent(company_id=company_id, name=n, role="exec") for n in ("Ada", "Bo")]
        session.add_all(candidates)
        await session.commit()
    admin = Principal(kind="user", company_id=company_id, role="admin", user_id=uuid.uuid4(),
                      email="owner@example.test")

    async def appoint(agent):
        async with session_factory() as session:
            await session.execute(
                sa.text("SELECT set_config('nexus.company_id', :cid, false)"),
                {"cid": str(company_id)})
            try:
                return await ceo_service.appoint(session, company_id, agent.id, admin)
            except HTTPException as exc:
                return exc

    results = await asyncio.gather(*(appoint(a) for a in candidates))
    losers = [r for r in results if isinstance(r, HTTPException)]
    assert len(losers) == 1 and losers[0].status_code == 409
    assert "CEO_CONFLICT" in str(losers[0].detail)

    async with session_factory() as session:
        agents = (await session.execute(
            sa.select(Agent).where(Agent.company_id == company_id))).scalars().all()
    await engine.dispose()
    ceos = [a for a in agents if a.is_ceo]
    assert len(ceos) == 1
    assert [a.id for a in agents if a.manager_id is None] == [ceos[0].id]
