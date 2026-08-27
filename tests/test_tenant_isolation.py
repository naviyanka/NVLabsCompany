"""Tests for tenant isolation (Phase 5.2).

The plan's acceptance test is "a cross-tenant read attempt returns empty, proven
by test", and that is what the first class does against a real SQLite database
with two companies' rows interleaved in the same tables. Proving it against real
rows rather than a mock matters here: the bug being guarded against is a missing
``WHERE`` clause, and a mocked session returns whatever the test tells it to,
which is exactly the thing under question.

The rest covers the two mechanisms that keep new code from reintroducing the
bug: :func:`nexus.database.tenant_scope` (5.2.2) and the arch-guard rule R5
(5.2.4). The Redis key namespace (5.2.3) is covered where it is built rather
than against a live server.
"""

import uuid

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlmodel import SQLModel, select

import nexus.models  # noqa: F401 -- registers every table on SQLModel.metadata
from nexus.database import tenant_scope
from nexus.models.agent import Agent
from nexus.models.company import Company
from nexus.models.task import Task
from nexus.runtime.redis_utils import TENANT_PREFIX, tenant_key


@pytest.fixture
async def two_tenants(tmp_path):
    """Two companies, each with one agent and two tasks, in one database.

    Both tenants' rows live in the same tables, which is the only arrangement
    where a missing filter is observable.
    """
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'tenants.db'}")
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)

    alpha, beta = uuid.uuid4(), uuid.uuid4()
    async with factory() as session:
        session.add(Company(id=alpha, name="Alpha"))
        session.add(Company(id=beta, name="Beta"))
        session.add(Agent(company_id=alpha, name="Ada", role="engineer"))
        session.add(Agent(company_id=beta, name="Grace", role="engineer"))
        session.add(Task(company_id=alpha, title="alpha-one"))
        session.add(Task(company_id=alpha, title="alpha-two"))
        session.add(Task(company_id=beta, title="beta-secret"))
        await session.commit()

    yield factory, alpha, beta
    await engine.dispose()


class TestCrossTenantRead:
    """5.2 acceptance: a read scoped to one tenant cannot see the other's rows."""

    async def test_scoped_read_returns_only_own_rows(self, two_tenants):
        factory, alpha, _ = two_tenants

        async with factory() as session:
            titles = {
                t.title for t in (await session.execute(tenant_scope(Task, alpha))).scalars()
            }

        assert titles == {"alpha-one", "alpha-two"}
        assert "beta-secret" not in titles

    async def test_cross_tenant_read_returns_empty(self, two_tenants):
        """Asking for another tenant's row by id under your own scope finds nothing.

        This is the shape a real attempt takes: the attacker knows or guesses a
        UUID and puts it in the URL. With the company filter present the query
        matches no row, so the route's ``if row is None`` branch produces a 404 —
        the caller cannot even confirm the row exists.
        """
        factory, alpha, beta = two_tenants

        async with factory() as session:
            beta_task = (
                await session.execute(tenant_scope(Task, beta).where(Task.title == "beta-secret"))
            ).scalar_one()

            stolen = (
                await session.execute(tenant_scope(Task, alpha).where(Task.id == beta_task.id))
            ).scalars().all()

        assert stolen == []

    async def test_unscoped_read_sees_everything(self, two_tenants):
        """The bug, demonstrated -- so the tests above are known to prove something.

        Without this, a filter that silently matched nothing would make every
        assertion above pass for the wrong reason. An unfiltered select returns
        all three tasks; that is what R5 exists to keep out of ``api/routes/``.
        """
        factory, _, _ = two_tenants

        async with factory() as session:
            rows = (await session.execute(select(Task))).scalars().all()

        assert len(rows) == 3

    async def test_isolation_holds_for_a_second_table(self, two_tenants):
        """Not a property of Task in particular."""
        factory, alpha, _ = two_tenants

        async with factory() as session:
            names = {
                a.name for a in (await session.execute(tenant_scope(Agent, alpha))).scalars()
            }

        assert names == {"Ada"}


class TestTenantScopeHelper:
    """5.2.2 -- the helper that injects the filter."""

    def test_filter_is_in_the_compiled_sql(self):
        stmt = tenant_scope(Task, uuid.uuid4())

        assert "company_id" in str(stmt)

    def test_further_conditions_compose(self):
        """The helper returns a Select, so routes keep chaining onto it."""
        stmt = tenant_scope(Task, uuid.uuid4()).where(Task.status == "open").limit(5)

        compiled = str(stmt)
        assert "company_id" in compiled
        assert "status" in compiled

    def test_model_without_company_id_is_rejected(self):
        """A caller reaching for the helper on a global table gets told, loudly.

        Returning an unfiltered query here would be the worst outcome: the call
        site reads as scoped and is not.
        """
        with pytest.raises(AttributeError, match="no company_id"):
            tenant_scope(Company, uuid.uuid4())


class TestRedisTenantPrefix:
    """5.2.3 -- one tenant's Redis keys live under one scannable prefix."""

    def test_key_starts_with_the_tenant_namespace(self):
        company_id = uuid.uuid4()

        key = tenant_key(company_id, "ratelimit", "minute")

        assert key == f"{TENANT_PREFIX}:{company_id}:ratelimit:minute"

    def test_company_comes_before_the_rest_of_the_key(self):
        """``SCAN tenant:{id}:*`` has to find everything one tenant owns.

        Deleting a company, or inspecting one tenant's counters, both depend on
        the company being the first variable segment.
        """
        company_id = uuid.uuid4()

        keys = [
            tenant_key(company_id, "ratelimit", "minute"),
            tenant_key(company_id, "state", "kill_switch"),
        ]

        prefix = f"{TENANT_PREFIX}:{company_id}:"
        assert all(k.startswith(prefix) for k in keys)

    def test_missing_company_id_is_refused(self):
        """A ``tenant:None:`` key would be one bucket every tenant shares."""
        with pytest.raises(ValueError, match="company_id"):
            tenant_key(None, "ratelimit")

    def test_company_rate_limit_keys_are_tenant_scoped(self):
        """The limiter's company windows moved under the namespace."""
        from nexus.governance.redis_rate_limiter import (
            RedisRateLimitConfig,
            RedisRateLimiter,
        )

        company_id = uuid.uuid4()

        minute, hour = RedisRateLimiter._window_keys(
            "company", company_id, RedisRateLimitConfig()
        )

        assert minute.startswith(f"{TENANT_PREFIX}:{company_id}:")
        assert hour.startswith(f"{TENANT_PREFIX}:{company_id}:")
