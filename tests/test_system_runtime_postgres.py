"""The system runtime against a real PostgreSQL provisioned the production way.

Roles come from ``deploy/postgres/provision-roles.sql`` and the schema from the migrator
(see ``test_db_role_separation_postgres``), so these tests see what a deployment sees: the
application role is RLS bound and owns nothing, ``nexus_system`` bypasses RLS but owns
nothing and cannot change the schema, and the migrator stays the owner.

What they show:
  * the role validation the runtime performs at start accepts the provisioned pair and
    names every swapped or over-privileged identity;
  * the privileged connection enumerates tenants, and its use stops there: it cannot alter
    the schema, and company work done through ``tenant_session`` on the application role
    stays inside one tenant;
  * an operation runs per company, isolates a company that fails, and leaves the rest done.
"""

# ruff: noqa: F811 -- fixtures imported from the role-separation suite are used as arguments

import asyncio
import uuid
from datetime import datetime, timedelta

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from nexus.models.budget import CostEvent
from nexus.models.company import Company
from nexus.models.task import Task
from nexus.system_runtime import db
from nexus.system_runtime.ops import OPERATIONS, _per_company
from tests.test_db_role_separation_postgres import (  # noqa: F401 -- fixtures and helpers
    _session,
    admin_url,
    deployed,
    postgres_container,
)

pytestmark = [pytest.mark.postgres, pytest.mark.integration]

DENIED = sa.exc.DBAPIError


def _engine(dep, role):
    return create_async_engine(dep.sa_url(role), poolclass=NullPool)


async def _validate(dep, app_role, system_role):
    app, system = _engine(dep, app_role), _engine(dep, system_role)
    try:
        return await db.validate_roles(app, system)
    finally:
        await app.dispose()
        await system.dispose()


# -- role validation: actual attributes, not usernames ----------------------------------


async def test_the_provisioned_roles_pass_the_runtime_validation(deployed):
    assert await _validate(deployed, deployed.app, deployed.system) == []


async def test_swapped_identities_are_refused_by_attribute(deployed):
    problems = await _validate(deployed, deployed.system, deployed.app)
    assert "APP_ROLE_BYPASSES_RLS" in problems
    assert "SYSTEM_ROLE_NOT_BYPASSRLS" in problems


async def test_the_same_identity_on_both_sides_is_refused(deployed):
    problems = await _validate(deployed, deployed.system, deployed.system)
    assert "APP_AND_SYSTEM_ROLE_IDENTICAL" in problems
    assert "APP_ROLE_BYPASSES_RLS" in problems


async def test_the_schema_owner_is_not_accepted_as_the_system_role(deployed):
    problems = await _validate(deployed, deployed.app, deployed.migrator)
    assert "SYSTEM_ROLE_OWNS_OBJECTS" in problems or "SYSTEM_ROLE_CAN_CREATE" in problems
    assert "SYSTEM_ROLE_NOT_BYPASSRLS" in problems


async def test_a_url_username_is_not_trusted(deployed):
    """A role named like the system role but without BYPASSRLS is still refused."""
    problems = await _validate(deployed, deployed.app, deployed.app)
    assert "SYSTEM_ROLE_NOT_BYPASSRLS" in problems


# -- the privileged connection: enumeration only ---------------------------------------


@pytest.fixture
async def tenants(deployed, monkeypatch):
    """Three companies, two of them with an expired reservation; app and system factories."""
    app = _engine(deployed, deployed.app)
    factory = async_sessionmaker(app, class_=AsyncSession, expire_on_commit=False)
    monkeypatch.setattr("nexus.database.async_session_factory", factory)
    monkeypatch.setenv("SYSTEM_DATABASE_URL", deployed.sa_url(deployed.system))
    monkeypatch.setenv("DATABASE_URL", deployed.sa_url(deployed.app))
    db._engine = None
    db.bootstrap()

    # The database is shared by the module: settle reservations left by earlier tests.
    async with db.discovery_session("task_recovery") as s:
        await s.execute(
            sa.text("UPDATE cost_events SET status = 'released' WHERE status = 'reserved'")
        )
        await s.commit()

    a, b, c = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    past = datetime.utcnow() - timedelta(minutes=5)
    async with _session(app) as s:
        s.add_all([Company(id=i, name=f"Tenant {n}") for i, n in ((a, "A"), (b, "B"), (c, "C"))])
        await s.commit()
    for cid in (a, b):
        async with _session(app, cid) as s:
            s.add(
                CostEvent(
                    company_id=cid,
                    provider="test",
                    cost_cents=5,
                    status="reserved",
                    expires_at=past,
                )
            )
            s.add(Task(id=uuid.uuid4(), company_id=cid, title="t", status="pending", priority=1))
            await s.commit()
    yield {"a": a, "b": b, "c": c, "app": app, "factory": factory}
    await db.dispose()
    await app.dispose()


def _discovery(name):
    return lambda: db.discovery_session(name)


async def _status(app, cid):
    async with _session(app, cid) as s:
        return sorted(
            (
                await s.execute(sa.select(CostEvent.status).where(CostEvent.company_id == cid))
            ).scalars()
        )


async def test_the_privileged_connection_enumerates_tenants_the_app_role_cannot_see(tenants):
    async with _session(tenants["app"]) as s:
        assert (await s.execute(sa.select(Task))).scalars().all() == [], (
            "unbound app role sees nothing"
        )
    async with db.discovery_session("task_recovery") as s:
        seen = set((await s.execute(sa.select(Task.company_id).distinct())).scalars())
    assert {tenants["a"], tenants["b"]} <= seen


async def test_the_privileged_connection_cannot_change_the_schema_or_its_protections(tenants):
    statements = [
        "DROP TABLE cost_events",
        "TRUNCATE tasks",
        "ALTER TABLE tasks DISABLE ROW LEVEL SECURITY",
        "CREATE TABLE intruder (id int)",
        "ALTER TABLE tasks NO FORCE ROW LEVEL SECURITY",
    ]
    for statement in statements:
        async with db.discovery_session("task_recovery") as s:
            with pytest.raises(DENIED):
                await s.execute(sa.text(statement))
            await s.rollback()


async def test_an_operation_does_its_writes_per_company_on_the_app_role(tenants):
    result = await OPERATIONS["budget_reservation_reap"].run(
        _discovery("budget_reservation_reap"), datetime.utcnow()
    )

    assert (result.seen, result.processed, result.failed) == (2, 2, 0)
    assert await _status(tenants["app"], tenants["a"]) == ["released"]
    assert await _status(tenants["app"], tenants["b"]) == ["released"]
    assert await _status(tenants["app"], tenants["c"]) == []


async def test_a_company_that_fails_does_not_stop_the_other_and_is_retried_next_run(
    tenants, monkeypatch
):
    from nexus.services.budget_service import BudgetService

    real = BudgetService.reap_expired_reservations
    calls = {"n": 0}

    async def flaky(self, company_id=None):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("simulated failure for the first company")
        return await real(self, company_id)

    monkeypatch.setattr(BudgetService, "reap_expired_reservations", flaky)
    op = OPERATIONS["budget_reservation_reap"]
    first = await op.run(_discovery("budget_reservation_reap"), datetime.utcnow())
    assert (first.processed, first.failed) == (1, 1)

    monkeypatch.setattr(BudgetService, "reap_expired_reservations", real)
    second = await op.run(_discovery("budget_reservation_reap"), datetime.utcnow())
    assert (second.seen, second.failed) == (1, 0), "only the failed company is left to retry"
    for key in ("a", "b"):
        assert await _status(tenants["app"], tenants[key]) == ["released"]


async def test_tenant_work_started_from_discovery_cannot_cross_tenants(tenants):
    """Ids come from the privileged read; every write is bound to one company by the session."""
    from nexus.database import tenant_session

    async with db.discovery_session("task_recovery") as s:
        ids = list((await s.execute(sa.select(Task.company_id).distinct())).scalars())

    async def work(company_id):
        async with tenant_session(company_id) as tdb:
            mine = (await tdb.execute(sa.select(Task))).scalars().all()
            assert {t.company_id for t in mine} == {company_id}
            other = next(i for i in (tenants["a"], tenants["b"]) if i != company_id)
            with pytest.raises(DENIED):
                tdb.add(
                    Task(id=uuid.uuid4(), company_id=other, title="x", status="pending", priority=1)
                )
                await tdb.commit()

    from nexus.system_runtime.ops import OpResult

    result = OpResult()
    await _per_company(result, [i for i in ids if i in (tenants["a"], tenants["b"])], work)
    assert (result.processed, result.failed) == (2, 0)


async def test_discovery_session_is_unavailable_after_dispose(tenants):
    await db.dispose()
    with pytest.raises(db.SystemRuntimeError) as caught:
        async with db.discovery_session("task_recovery"):
            pass
    assert caught.value.code == "SYSTEM_RUNTIME_NOT_BOOTSTRAPPED"
    await asyncio.sleep(0)
