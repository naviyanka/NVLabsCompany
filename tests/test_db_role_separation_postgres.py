"""Database role separation against a real PostgreSQL.

A schema owner can drop triggers, disable row level security and alter policies, so the
application role must own nothing. These tests provision the three roles with the canonical
bootstrap (``deploy/postgres/provision-roles.sql``), migrate as the migrator through the
production entry point (``nexus.db_migrate``), and then try, as the application role, to
remove each protection. The existing PostgreSQL suites connect as a superuser and grant the
app role ``ALL``, so they cannot see any of this.

Roles are cluster wide, so every deployment gets random role names and its own database.
"""

import asyncio
import secrets
import uuid
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from pathlib import Path

import alembic.command
import alembic.config
import asyncpg
import pytest
import sqlalchemy as sa
from sqlalchemy.engine import URL, make_url
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from nexus import db_migrate
from nexus.models.company import Company
from nexus.models.governance import AuditLog
from nexus.models.memory import MemoryRecord
from nexus.models.task import Task
from tests.test_postgres_integration import postgres_container  # noqa: F401 -- fixture

pytestmark = [pytest.mark.postgres, pytest.mark.integration]

ROOT = Path(__file__).resolve().parent.parent
PROVISION = ROOT / "deploy" / "postgres" / "provision-roles.sql"
REMEDIATE = ROOT / "deploy" / "postgres" / "remediate-ownership.sql"
DENIED = asyncpg.exceptions.InsufficientPrivilegeError


@dataclass
class Deployment:
    admin: URL
    suffix: str = field(default_factory=lambda: secrets.token_hex(4))
    extra_roles: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.db = f"nexus_roles_{self.suffix}"
        self.migrator = f"nexus_migrator_{self.suffix}"
        self.app = f"nexus_app_{self.suffix}"
        self.system = f"nexus_system_{self.suffix}"
        self.passwords = {r: secrets.token_hex(12) for r in (self.migrator, self.app, self.system)}

    def url(self, role: str) -> URL:
        return self.admin.set(
            drivername="postgresql+asyncpg",
            database=self.db,
            username=role,
            password=self.passwords[role],
        )

    def sa_url(self, role: str) -> str:
        return self.url(role).render_as_string(hide_password=False)

    def dsn(self, role: str | None = None) -> str:
        url = self.url(role) if role else self.admin.set(database=self.db)
        return url.set(drivername="postgresql").render_as_string(hide_password=False)

    def role_settings(self, *, passwords: bool = True) -> dict[str, str]:
        out = {
            "nexus.migrator_role": self.migrator,
            "nexus.app_role": self.app,
            "nexus.system_role": self.system,
        }
        if passwords:
            out |= {
                "nexus.migrator_password": self.passwords[self.migrator],
                "nexus.app_password": self.passwords[self.app],
                "nexus.system_password": self.passwords[self.system],
            }
        return out

    def migrate_env(self) -> dict[str, str]:
        return {
            "MIGRATION_DATABASE_URL": self.sa_url(self.migrator),
            "NEXUS_MIGRATION_ROLE": self.migrator,
            "DATABASE_USER": self.app,
            "DATABASE_SYSTEM_USER": self.system,
        }


async def _run_script(dsn: str, path: Path, settings: dict[str, str]) -> list[str]:
    """Run a bootstrap script the way psql would, with the inputs as session settings."""
    notices: list[str] = []
    conn = await asyncpg.connect(dsn)
    conn.add_log_listener(lambda _c, message: notices.append(message.message))
    try:
        for name, value in settings.items():
            await conn.execute("SELECT set_config($1, $2, false)", name, value)
        await conn.execute(path.read_text(encoding="utf-8"))
    finally:
        await conn.close()
    return notices


async def _fetch(dsn: str, sql: str, *args):
    conn = await asyncpg.connect(dsn)
    try:
        return await conn.fetch(sql, *args)
    finally:
        await conn.close()


async def _val(dsn: str, sql: str, *args):
    rows = await _fetch(dsn, sql, *args)
    return rows[0][0] if rows else None


async def _exec(dsn: str, sql: str) -> None:
    conn = await asyncpg.connect(dsn)
    try:
        await conn.execute(sql)
    finally:
        await conn.close()


async def _create(dep: Deployment, *, provision: bool = True) -> None:
    await _exec(
        dep.admin.set(drivername="postgresql").render_as_string(hide_password=False),
        f'CREATE DATABASE "{dep.db}"',
    )
    if provision:
        await _run_script(dep.dsn(), PROVISION, dep.role_settings())


async def _drop(dep: Deployment) -> None:
    admin = dep.admin.set(drivername="postgresql").render_as_string(hide_password=False)
    await _exec(admin, f'DROP DATABASE IF EXISTS "{dep.db}" WITH (FORCE)')
    for role in (dep.migrator, dep.app, dep.system, *dep.extra_roles):
        await _exec(admin, f'DROP ROLE IF EXISTS "{role}"')


def _alembic(dep: Deployment, role: str, action: str, target: str) -> None:
    cfg = alembic.config.Config(str(ROOT / "alembic.ini"))
    cfg.set_main_option("sqlalchemy.url", dep.sa_url(role).replace("%", "%%"))
    getattr(alembic.command, action)(cfg, target)


@pytest.fixture(scope="module")
def admin_url(postgres_container):  # noqa: F811
    import os

    if os.environ.get("TEST_DATABASE_URL"):
        return make_url(os.environ["TEST_DATABASE_URL"])
    return make_url(postgres_container.get_connection_url())


def _deployment(admin_url, *, migrate: bool = True, provision: bool = True):
    dep = Deployment(admin_url)
    try:
        asyncio.run(_create(dep, provision=provision))
        if migrate:
            asyncio.run(db_migrate.run(dep.migrate_env()))
    except BaseException:
        asyncio.run(_drop(dep))
        raise
    return dep


@pytest.fixture(scope="module")
def deployed(admin_url):
    dep = _deployment(admin_url)
    yield dep
    asyncio.run(_drop(dep))


@pytest.fixture
def fresh(admin_url):
    dep = _deployment(admin_url)
    yield dep
    asyncio.run(_drop(dep))


@pytest.fixture
def roles_only(admin_url):
    dep = _deployment(admin_url, migrate=False)
    yield dep
    asyncio.run(_drop(dep))


@pytest.fixture
def legacy(admin_url):
    """The pre-hardening layout: the application role built the schema and owns it."""
    dep = _deployment(admin_url, migrate=False)
    try:
        asyncio.run(
            _exec(
                dep.dsn(),
                f"ALTER SCHEMA public OWNER TO {dep.app}; "
                f"GRANT CREATE ON SCHEMA public TO {dep.app}",
            )
        )
        _alembic(dep, dep.app, "upgrade", "head")
    except BaseException:
        asyncio.run(_drop(dep))
        raise
    yield dep
    asyncio.run(_drop(dep))


# --- catalog helpers -------------------------------------------------------------------

_PUBLIC_OBJECT_OWNERS = """
SELECT 'relation' AS kind, c.relname::text AS name, pg_get_userbyid(c.relowner)::text AS owner
  FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
 WHERE n.nspname = 'public' AND c.relkind IN ('r', 'p', 'v', 'm', 'S', 'f')
UNION ALL
SELECT 'function', p.oid::regprocedure::text, pg_get_userbyid(p.proowner)::text
  FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace
 WHERE n.nspname = 'public'
   AND NOT EXISTS (SELECT 1 FROM pg_depend d WHERE d.classid = 'pg_proc'::regclass
                    AND d.objid = p.oid AND d.deptype = 'e')
UNION ALL
SELECT 'schema', nspname::text, pg_get_userbyid(nspowner)::text
  FROM pg_namespace WHERE nspname = 'public'
"""

_TABLES = """
SELECT c.relname::text FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
 WHERE n.nspname = 'public' AND c.relkind IN ('r', 'p') AND c.relname <> 'alembic_version'
 ORDER BY 1
"""

_PROTECTIONS = """
SELECT 'rls', c.relname::text, c.relrowsecurity::text || '/' || c.relforcerowsecurity::text
  FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
 WHERE n.nspname = 'public' AND c.relkind IN ('r', 'p')
UNION ALL
SELECT 'trigger', c.relname::text || '.' || t.tgname::text, t.tgenabled::text
  FROM pg_trigger t JOIN pg_class c ON c.oid = t.tgrelid
  JOIN pg_namespace n ON n.oid = c.relnamespace
 WHERE n.nspname = 'public' AND NOT t.tgisinternal
UNION ALL
SELECT 'policy', tablename::text || '.' || policyname::text,
       coalesce(qual, '') || '|' || coalesce(with_check, '')
  FROM pg_policies WHERE schemaname = 'public'
UNION ALL
SELECT 'constraint', conrelid::regclass::text || '.' || conname::text, pg_get_constraintdef(oid)
  FROM pg_constraint WHERE connamespace = 'public'::regnamespace
UNION ALL
SELECT 'index', tablename::text || '.' || indexname::text, indexdef
  FROM pg_indexes WHERE schemaname = 'public'
ORDER BY 1, 2
"""


async def _owners(dep: Deployment) -> dict[tuple[str, str], str]:
    return {
        (r["kind"], r["name"]): r["owner"] for r in await _fetch(dep.dsn(), _PUBLIC_OBJECT_OWNERS)
    }


async def _protections(dep: Deployment) -> list[tuple]:
    return [tuple(r) for r in await _fetch(dep.dsn(), _PROTECTIONS)]


async def _row_counts(dep: Deployment) -> dict[str, int]:
    counts = {}
    for name in [r[0] for r in await _fetch(dep.dsn(), _TABLES)] + ["alembic_version"]:
        counts[name] = await _val(dep.dsn(), f'SELECT count(*) FROM public."{name}"')
    return counts


async def _assert_owned_and_granted_as_designed(dep: Deployment) -> None:
    owners = await _owners(dep)
    assert owners, "no public objects found"
    assert {o for o in owners.values()} == {dep.migrator}, {
        k: v for k, v in owners.items() if v != dep.migrator
    }

    dsn = dep.dsn()
    for table in [r[0] for r in await _fetch(dsn, _TABLES)]:
        for role in (dep.app, dep.system):
            for priv in ("SELECT", "INSERT", "UPDATE", "DELETE"):
                assert await _val(
                    dsn, "SELECT has_table_privilege($1, $2, $3)", role, f"public.{table}", priv
                ), (role, table, priv)
            for priv in ("TRUNCATE", "REFERENCES", "TRIGGER"):
                assert not await _val(
                    dsn, "SELECT has_table_privilege($1, $2, $3)", role, f"public.{table}", priv
                ), (role, table, priv)
    for role in (dep.app, dep.system):
        assert not await _val(
            dsn, "SELECT has_table_privilege($1, 'public.alembic_version', 'SELECT')", role
        )
    for (seq,) in await _fetch(
        dsn,
        "SELECT c.oid::regclass::text FROM pg_class c "
        "WHERE c.relkind = 'S' AND c.relnamespace = 'public'::regnamespace",
    ):
        for role in (dep.app, dep.system):
            assert await _val(dsn, "SELECT has_sequence_privilege($1, $2, 'USAGE')", role, seq)


# --- fresh provisioning ----------------------------------------------------------------


async def test_migrator_owns_the_schema_and_the_app_role_owns_nothing(deployed):
    await _assert_owned_and_granted_as_designed(deployed)
    owned = await _val(
        deployed.dsn(),
        "SELECT count(*) FROM pg_shdepend WHERE refclassid = 'pg_authid'::regclass "
        "AND deptype = 'o' AND refobjid = (SELECT oid FROM pg_roles WHERE rolname = $1)",
        deployed.app,
    )
    assert owned == 0, "the application role owns something in this database"
    assert await _val(
        deployed.dsn(),
        "SELECT pg_get_userbyid(datdba) FROM pg_database WHERE datname = $1",
        deployed.db,
    ) not in (deployed.app, deployed.system)


async def test_role_attributes_and_memberships(deployed):
    rows = {
        r["rolname"]: r
        for r in await _fetch(
            deployed.dsn(),
            "SELECT rolname, rolsuper, rolbypassrls, rolcreatedb, rolcreaterole, "
            "rolreplication, rolcanlogin "
            "FROM pg_roles WHERE rolname = ANY($1)",
            [deployed.migrator, deployed.app, deployed.system],
        )
    }
    for name, role in rows.items():
        assert role["rolcanlogin"] and not (
            role["rolsuper"]
            or role["rolcreatedb"]
            or role["rolcreaterole"]
            or role["rolreplication"]
        ), name
    assert rows[deployed.system]["rolbypassrls"], "nexus_system is the BYPASSRLS maintenance role"
    assert not rows[deployed.app]["rolbypassrls"]
    assert not rows[deployed.migrator]["rolbypassrls"]
    for a in (deployed.migrator, deployed.app, deployed.system):
        for b in (deployed.migrator, deployed.app, deployed.system):
            if a != b:
                assert not await _val(
                    deployed.dsn(), "SELECT pg_has_role($1, $2, 'USAGE')", a, b
                ), (a, b)


async def test_schema_database_and_public_privileges(deployed):
    dsn = deployed.dsn()
    assert await _val(dsn, "SELECT has_schema_privilege($1, 'public', 'CREATE')", deployed.migrator)
    for role in (deployed.app, deployed.system):
        assert await _val(dsn, "SELECT has_schema_privilege($1, 'public', 'USAGE')", role)
        assert not await _val(dsn, "SELECT has_schema_privilege($1, 'public', 'CREATE')", role)
        assert not await _val(
            dsn, "SELECT has_database_privilege($1, $2, 'CREATE')", role, deployed.db
        )
    public_grants = await _fetch(
        dsn,
        """
        SELECT c.relname::text FROM pg_class c
          CROSS JOIN LATERAL aclexplode(c.relacl) a
         WHERE c.relnamespace = 'public'::regnamespace AND c.relkind IN ('r', 'p', 'S', 'v')
           AND a.grantee = 0
        """,
    )
    assert public_grants == [], "PUBLIC holds privileges on relations"
    assert not await _fetch(
        dsn,
        "SELECT 1 FROM pg_namespace n CROSS JOIN LATERAL aclexplode(n.nspacl) a "
        "WHERE n.nspname = 'public' AND a.grantee = 0 AND a.privilege_type = 'CREATE'",
    )
    assert not await _fetch(
        dsn,
        "SELECT 1 FROM pg_database d CROSS JOIN LATERAL aclexplode(d.datacl) a "
        "WHERE d.datname = $1 AND a.grantee = 0 AND a.privilege_type = 'CREATE'",
        deployed.db,
    )


async def test_provisioning_is_idempotent_and_rotates_passwords(deployed):
    before = (await _owners(deployed), await _protections(deployed))
    await _run_script(deployed.dsn(), PROVISION, deployed.role_settings(passwords=False))
    assert (await _owners(deployed), await _protections(deployed)) == before
    await _assert_owned_and_granted_as_designed(deployed)

    new = secrets.token_hex(12)
    old = deployed.passwords[deployed.app]
    await _run_script(
        deployed.dsn(),
        PROVISION,
        {**deployed.role_settings(passwords=False), "nexus.app_password": new},
    )
    with pytest.raises(asyncpg.InvalidPasswordError):
        await asyncpg.connect(deployed.dsn(deployed.app))
    deployed.passwords[deployed.app] = new
    conn = await asyncpg.connect(deployed.dsn(deployed.app))
    await conn.close()
    assert old != new


async def test_provisioning_refuses_bad_input(roles_only):
    other = Deployment(roles_only.admin)
    await _exec(
        roles_only.admin.set(drivername="postgresql").render_as_string(hide_password=False),
        f'CREATE DATABASE "{other.db}"',
    )
    try:
        with pytest.raises(asyncpg.RaiseError, match="is not set"):
            await _run_script(other.dsn(), PROVISION, other.role_settings(passwords=False))
        same = {**other.role_settings(), "nexus.app_role": other.migrator}
        with pytest.raises(asyncpg.RaiseError, match="three different roles"):
            await _run_script(other.dsn(), PROVISION, same)
    finally:
        await _exec(
            roles_only.admin.set(drivername="postgresql").render_as_string(hide_password=False),
            f'DROP DATABASE "{other.db}" WITH (FORCE)',
        )


# --- the application role cannot remove a protection -----------------------------------

ATTACKS = {
    "disable-rls": "ALTER TABLE memory_records DISABLE ROW LEVEL SECURITY",
    "no-force-rls": "ALTER TABLE memory_records NO FORCE ROW LEVEL SECURITY",
    "drop-policy": "DROP POLICY tenant_isolation ON memory_records",
    "alter-policy": "ALTER POLICY tenant_isolation ON memory_records USING (true)",
    "add-open-policy": "CREATE POLICY open_all ON memory_records USING (true)",
    "drop-audit-trigger": "DROP TRIGGER audit_log_append_only ON audit_log",
    "disable-audit-trigger": "ALTER TABLE audit_log DISABLE TRIGGER audit_log_append_only",
    "disable-all-triggers": "ALTER TABLE audit_log DISABLE TRIGGER ALL",
    "alter-table": "ALTER TABLE audit_log ADD COLUMN extra integer",
    "drop-column": "ALTER TABLE companies DROP COLUMN name",
    "drop-constraint": "ALTER TABLE companies DROP CONSTRAINT companies_pkey",
    "drop-table": "DROP TABLE audit_log",
    "drop-table-cascade": "DROP TABLE companies CASCADE",
    "change-owner": "ALTER TABLE audit_log OWNER TO {app}",
    "move-schema": "ALTER SCHEMA public OWNER TO {app}",
    "drop-schema": "DROP SCHEMA public CASCADE",
    "truncate-audit": "TRUNCATE audit_log",
    "truncate-memory": "TRUNCATE memory_records",
    "truncate-cascade": "TRUNCATE companies CASCADE",
    "create-table": "CREATE TABLE public.sneaky (id integer)",
    "create-function": "CREATE FUNCTION public.sneaky() RETURNS integer LANGUAGE sql AS 'SELECT 1'",
    "set-role-migrator": "SET ROLE {migrator}",
    "set-role-system": "SET ROLE {system}",
    "set-session-authorization": "SET SESSION AUTHORIZATION {migrator}",
    "become-superuser": "ALTER ROLE {app} SUPERUSER",
    "bypass-rls": "ALTER ROLE {app} BYPASSRLS",
    "create-role": "CREATE ROLE sneaky_{suffix}",
    "take-database": "ALTER DATABASE {db} OWNER TO {app}",
    "default-privileges": (
        "ALTER DEFAULT PRIVILEGES FOR ROLE {migrator} IN SCHEMA public GRANT ALL ON TABLES TO {app}"
    ),
    "drop-extension": "DROP EXTENSION vector CASCADE",
    "edit-catalog": (
        "UPDATE pg_catalog.pg_class SET relrowsecurity = false WHERE relname = 'memory_records'"
    ),
    "read-migration-version": "SELECT version_num FROM alembic_version",
    "write-migration-version": "UPDATE alembic_version SET version_num = 'x'",
}


@pytest.mark.parametrize("sql", ATTACKS.values(), ids=ATTACKS.keys())
async def test_app_role_cannot_remove_a_protection(deployed, sql):
    stmt = sql.format(
        app=deployed.app,
        migrator=deployed.migrator,
        system=deployed.system,
        db=deployed.db,
        suffix=deployed.suffix,
    )
    conn = await asyncpg.connect(deployed.dsn(deployed.app))
    try:
        with pytest.raises(DENIED):
            await conn.execute(stmt)
    finally:
        await conn.close()


async def test_app_role_cannot_replace_the_audit_trigger_function(deployed):
    fn = await _val(
        deployed.dsn(),
        "SELECT t.tgfoid::regproc::text FROM pg_trigger t WHERE t.tgname = 'audit_log_append_only'",
    )
    assert fn
    conn = await asyncpg.connect(deployed.dsn(deployed.app))
    try:
        for stmt in (
            f"DROP FUNCTION {fn}() CASCADE",
            f"CREATE OR REPLACE FUNCTION {fn}() RETURNS trigger "
            "LANGUAGE plpgsql AS 'BEGIN RETURN NEW; END'",
            f"ALTER FUNCTION {fn}() OWNER TO {deployed.app}",
        ):
            with pytest.raises(DENIED):
                await conn.execute(stmt)
    finally:
        await conn.close()


async def test_granting_itself_privileges_changes_nothing(deployed):
    """A grant by a role without grant option is a warning, not an error: check the effect."""
    conn = await asyncpg.connect(deployed.dsn(deployed.app))
    try:
        for stmt in (
            f"GRANT TRUNCATE, REFERENCES, TRIGGER ON audit_log TO {deployed.app}",
            f"GRANT ALL ON ALL TABLES IN SCHEMA public TO {deployed.app}",
            f"GRANT CREATE ON SCHEMA public TO {deployed.app}",
            f"GRANT {deployed.migrator} TO {deployed.app}",
        ):
            try:
                await conn.execute(stmt)
            except DENIED:
                pass
    finally:
        await conn.close()
    await _assert_owned_and_granted_as_designed(deployed)
    assert not await _val(
        deployed.dsn(), "SELECT has_schema_privilege($1, 'public', 'CREATE')", deployed.app
    )
    assert not await _val(
        deployed.dsn(), "SELECT pg_has_role($1, $2, 'USAGE')", deployed.app, deployed.migrator
    )


async def test_every_protection_is_still_in_place(deployed):
    protections = await _protections(deployed)
    rls = {name: state for kind, name, state in protections if kind == "rls"}
    assert rls["memory_records"] == "true/true"
    assert rls["audit_log"] == "true/true"
    assert ("trigger", "audit_log.audit_log_append_only", "O") in protections
    assert any(k == "policy" and n == "memory_records.tenant_isolation" for k, n, _ in protections)
    await _assert_owned_and_granted_as_designed(deployed)


# --- the application still works -------------------------------------------------------


@asynccontextmanager
async def _session(engine, company_id=None):
    async with AsyncSession(engine, expire_on_commit=False) as session:
        if company_id is not None:
            await session.execute(
                sa.text("SELECT set_config('nexus.company_id', :c, false)"), {"c": str(company_id)}
            )
        yield session


async def test_tenant_bound_work_still_works_and_stays_isolated(deployed):
    engine = create_async_engine(deployed.sa_url(deployed.app), poolclass=NullPool)
    try:
        a, b = uuid.uuid4(), uuid.uuid4()
        async with _session(engine) as s:
            s.add_all([Company(id=a, name="Tenant A"), Company(id=b, name="Tenant B")])
            await s.commit()
        for cid in (a, b):
            async with _session(engine, cid) as s:
                s.add(
                    Task(
                        id=uuid.uuid4(),
                        company_id=cid,
                        title=f"task of {cid}",
                        status="pending",
                        priority=1,
                    )
                )
                s.add(MemoryRecord(company_id=cid, scope="company", content=f"memory of {cid}"))
                await s.commit()

        for cid, other in ((a, b), (b, a)):
            async with _session(engine, cid) as s:
                tasks = (await s.execute(sa.select(Task))).scalars().all()
                memories = (await s.execute(sa.select(MemoryRecord))).scalars().all()
                assert [t.company_id for t in tasks] == [cid]
                assert [m.company_id for m in memories] == [cid]
                for model in (Task, MemoryRecord):
                    upd = await s.execute(
                        sa.update(model).where(model.company_id == other).values(company_id=cid)
                    )
                    dele = await s.execute(sa.delete(model).where(model.company_id == other))
                    assert upd.rowcount == 0 and dele.rowcount == 0

        async with _session(engine) as s:
            assert (await s.execute(sa.select(Task))).scalars().all() == []
            assert (await s.execute(sa.select(MemoryRecord))).scalars().all() == []
        async with _session(engine) as s:
            s.add(
                Task(id=uuid.uuid4(), company_id=a, title="unbound", status="pending", priority=1)
            )
            with pytest.raises(sa.exc.DBAPIError, match="row-level security"):
                await s.commit()
    finally:
        await engine.dispose()

    system = create_async_engine(deployed.sa_url(deployed.system), poolclass=NullPool)
    try:
        async with _session(system) as s:
            seen = {t.company_id for t in (await s.execute(sa.select(Task))).scalars().all()}
        assert {a, b} <= seen, "nexus_system keeps its cross-tenant maintenance reach"
    finally:
        await system.dispose()


async def test_audit_log_stays_append_only_for_the_app_role(deployed):
    from nexus.governance.audit_service import record_audit

    engine = create_async_engine(deployed.sa_url(deployed.app), poolclass=NullPool)
    try:
        cid = uuid.uuid4()
        async with _session(engine) as s:
            s.add(Company(id=cid, name="Audited"))
            await s.commit()
        async with _session(engine, cid) as s:
            await record_audit(
                cid, "role.test", actor_type="user", actor_id="u", db=s, raise_on_error=True
            )
            row_id = (
                await s.execute(sa.select(AuditLog.id).where(AuditLog.company_id == cid))
            ).scalar_one()
            await s.commit()
        for stmt in (
            sa.update(AuditLog).where(AuditLog.id == row_id).values(action="tampered"),
            sa.delete(AuditLog).where(AuditLog.id == row_id),
        ):
            async with _session(engine, cid) as s:
                with pytest.raises(sa.exc.DBAPIError, match="audit_log is append-only"):
                    await s.execute(stmt)
                    await s.commit()
    finally:
        await engine.dispose()


# --- migration lifecycle ---------------------------------------------------------------


async def test_up_down_up_and_new_objects_keep_the_ownership_contract(fresh):
    before = await _owners(fresh)
    protections = await _protections(fresh)

    await asyncio.to_thread(_alembic, fresh, fresh.migrator, "downgrade", "-1")
    await asyncio.to_thread(_alembic, fresh, fresh.migrator, "upgrade", "head")
    assert set(await _owners(fresh)) == set(before)
    assert await _protections(fresh) == protections
    await _assert_owned_and_granted_as_designed(fresh)

    # What a new migration does: create a table with a serial column, as the migrator.
    await _exec(
        fresh.dsn(fresh.migrator), "CREATE TABLE public.zz_probe (id serial PRIMARY KEY, note text)"
    )
    owners = await _owners(fresh)
    assert owners[("relation", "zz_probe")] == fresh.migrator
    assert owners[("relation", "zz_probe_id_seq")] == fresh.migrator
    await _assert_owned_and_granted_as_designed(fresh)
    app = await asyncpg.connect(fresh.dsn(fresh.app))
    try:
        await app.execute("INSERT INTO zz_probe (note) VALUES ('ok')")
        assert await app.fetchval("SELECT count(*) FROM zz_probe") == 1
        for stmt in (
            "TRUNCATE zz_probe",
            "ALTER TABLE zz_probe ADD COLUMN x integer",
            "DROP TABLE zz_probe",
        ):
            with pytest.raises(DENIED):
                await app.execute(stmt)
    finally:
        await app.close()
    await _exec(fresh.dsn(fresh.migrator), "DROP TABLE public.zz_probe")


# --- the tool-effect ledger tables under the real provisioning --------------------------

LEDGER = ("tool_bridge_slots", "tool_effects", "tool_notifications")
BEFORE_LEDGER = "b4d9f2a61c73"  # the revision before the tool-effect ledger migration

LEDGER_ATTACKS = {
    "disable-rls": "ALTER TABLE {t} DISABLE ROW LEVEL SECURITY",
    "no-force-rls": "ALTER TABLE {t} NO FORCE ROW LEVEL SECURITY",
    "drop-policy": "DROP POLICY tenant_isolation ON {t}",
    "alter-policy": "ALTER POLICY tenant_isolation ON {t} USING (true)",
    "add-open-policy": "CREATE POLICY open_all ON {t} USING (true)",
    "truncate": "TRUNCATE {t}",
    "drop-table": "DROP TABLE {t}",
    "alter-table": "ALTER TABLE {t} ADD COLUMN extra integer",
    "change-owner": "ALTER TABLE {t} OWNER TO {app}",
}


async def _ledger_contract(dep: Deployment) -> None:
    """The migrator owns each ledger table; the app role holds DML only, by default privileges."""
    dsn = dep.dsn()
    for table in LEDGER:
        rel = f"public.{table}"
        owner = await _val(
            dsn, "SELECT pg_get_userbyid(relowner) FROM pg_class WHERE oid = $1::regclass", rel
        )
        assert owner == dep.migrator, table
        flags = await _fetch(
            dsn,
            "SELECT relrowsecurity, relforcerowsecurity FROM pg_class WHERE oid = $1::regclass",
            rel,
        )
        assert tuple(flags[0]) == (True, True), table
        assert await _val(
            dsn,
            "SELECT count(*) FROM pg_policies "
            "WHERE tablename = $1 AND policyname = 'tenant_isolation'",
            table,
        ) == 1
        granted = sorted(
            r[0]
            for r in await _fetch(
                dsn,
                "SELECT a.privilege_type FROM pg_class c "
                "CROSS JOIN LATERAL aclexplode(c.relacl) a WHERE c.oid = $1::regclass "
                "AND a.grantee = (SELECT oid FROM pg_roles WHERE rolname = $2)",
                rel, dep.app,
            )
        )
        assert granted == ["DELETE", "INSERT", "SELECT", "UPDATE"], (table, granted)
    owned = await _val(
        dsn,
        "SELECT count(*) FROM pg_class WHERE relname = ANY($1) "
        "AND relowner = (SELECT oid FROM pg_roles WHERE rolname = $2)",
        list(LEDGER), dep.app,
    )
    assert owned == 0


async def test_ledger_tables_follow_the_ownership_and_default_privilege_contract(deployed):
    await _ledger_contract(deployed)
    # The privileges come from the provisioning script's default privileges for the migrator.
    assert await _val(
        deployed.dsn(),
        "SELECT count(*) FROM pg_default_acl d CROSS JOIN LATERAL aclexplode(d.defaclacl) a "
        "WHERE d.defaclrole = (SELECT oid FROM pg_roles WHERE rolname = $1) "
        "AND d.defaclobjtype = 'r' AND a.grantee = (SELECT oid FROM pg_roles WHERE rolname = $2)",
        deployed.migrator, deployed.app,
    ) == 4


def test_the_ledger_migration_names_no_role_and_grants_nothing():
    import re

    path = next((ROOT / "alembic" / "versions").glob("c5e8a3b71d94_*.py"))
    source = path.read_text(encoding="utf-8")
    assert not re.search(r"\bGRANT\b|\bOWNER TO\b|\bnexus_(app|system|migrator)\b", source, re.I)


@pytest.mark.parametrize("sql", LEDGER_ATTACKS.values(), ids=LEDGER_ATTACKS.keys())
@pytest.mark.parametrize("table", LEDGER)
async def test_app_role_cannot_weaken_a_ledger_table(deployed, table, sql):
    conn = await asyncpg.connect(deployed.dsn(deployed.app))
    try:
        with pytest.raises(DENIED):
            await conn.execute(sql.format(t=table, app=deployed.app))
    finally:
        await conn.close()
    await _ledger_contract(deployed)


async def test_a_refused_downgrade_and_a_reupgrade_keep_the_ledger_role_contract(
    fresh, monkeypatch
):
    from nexus.models._time import utcnow
    from nexus.models.tool_effect import ToolEffect

    monkeypatch.delenv("NEXUS_DESTROY_TOOL_EFFECTS", raising=False)
    company = uuid.uuid4()
    url = fresh.admin.set(drivername="postgresql+asyncpg", database=fresh.db)
    admin = create_async_engine(url.render_as_string(hide_password=False), poolclass=NullPool)
    try:
        async with AsyncSession(admin, expire_on_commit=False) as s:
            s.add(Company(id=company, name="Ledgered"))
            await s.flush()
            s.add(
                ToolEffect(
                    company_id=company, turn_id=uuid.uuid4(), round_index=0, invocation_index=0,
                    tool_name="t", effect_class="idempotent_write", invocation_key="k" * 64,
                    arguments_digest="0" * 64, claim_token="tok", lease_expires_at=utcnow(),
                )
            )
            await s.commit()
    finally:
        await admin.dispose()
    with pytest.raises(RuntimeError, match="Refusing to downgrade"):
        await asyncio.to_thread(_alembic, fresh, fresh.migrator, "downgrade", BEFORE_LEDGER)
    await _ledger_contract(fresh)  # the refusal rolled back: ownership, grants, FORCE RLS intact
    monkeypatch.setenv("NEXUS_DESTROY_TOOL_EFFECTS", "destroy-ledger")
    await asyncio.to_thread(_alembic, fresh, fresh.migrator, "downgrade", BEFORE_LEDGER)
    assert await _val(fresh.dsn(), "SELECT to_regclass('public.tool_effects')") is None
    monkeypatch.delenv("NEXUS_DESTROY_TOOL_EFFECTS")
    await asyncio.to_thread(_alembic, fresh, fresh.migrator, "upgrade", "head")
    await _ledger_contract(fresh)  # recreated tables got the same owner and default privileges
    await _assert_owned_and_granted_as_designed(fresh)


# --- the migration entry point's preflight ---------------------------------------------


async def test_preflight_accepts_the_provisioned_roles(deployed):
    problems = await db_migrate.check_roles(
        deployed.sa_url(deployed.migrator), deployed.migrator, deployed.app, deployed.system
    )
    assert problems == []


@pytest.mark.parametrize("identity", ["app", "system"])
async def test_preflight_refuses_an_application_identity_as_migrator(deployed, identity):
    role = getattr(deployed, identity)
    problems = await db_migrate.check_roles(
        deployed.sa_url(role), deployed.migrator, deployed.app, deployed.system
    )
    assert any("migration identity must be" in p for p in problems), problems


async def test_preflight_refuses_a_collapsed_identity(deployed):
    for names in (
        (deployed.migrator, deployed.migrator, deployed.system),
        (deployed.migrator, deployed.app, deployed.app),
        (deployed.app, deployed.app, deployed.system),
    ):
        problems = await db_migrate.check_roles(deployed.sa_url(deployed.migrator), *names)
        assert any("three different roles" in p for p in problems), (names, problems)


async def test_preflight_refuses_a_superuser_and_a_role_that_cannot_create(deployed):
    admin_name = deployed.admin.username
    problems = await db_migrate.check_roles(
        deployed.admin.set(drivername="postgresql+asyncpg", database=deployed.db).render_as_string(
            hide_password=False
        ),
        admin_name,
        deployed.app,
        deployed.system,
    )
    assert any("SUPERUSER" in p for p in problems), problems

    low = f"nexus_low_{deployed.suffix}"
    deployed.extra_roles.append(low)
    pw = secrets.token_hex(8)
    admin = deployed.dsn()
    await _exec(admin, f"CREATE ROLE {low} LOGIN PASSWORD '{pw}'")
    low_url = (
        deployed.url(deployed.migrator)
        .set(username=low, password=pw)
        .render_as_string(hide_password=False)
    )
    problems = await db_migrate.check_roles(low_url, low, deployed.app, deployed.system)
    assert any("cannot CREATE in schema public" in p for p in problems), problems
    await _exec(admin, f"DROP ROLE {low}")


async def test_preflight_names_a_missing_app_role(deployed):
    problems = await db_migrate.check_roles(
        deployed.sa_url(deployed.migrator),
        deployed.migrator,
        f"absent_{deployed.suffix}",
        deployed.system,
    )
    assert any("does not exist" in p for p in problems), problems


# --- legacy remediation ----------------------------------------------------------------


async def _legacy_data(dep: Deployment) -> None:
    engine = create_async_engine(dep.sa_url(dep.app), poolclass=NullPool)
    try:
        cid = uuid.uuid4()
        async with _session(engine) as s:
            s.add(Company(id=cid, name="Legacy tenant"))
            await s.commit()
        async with _session(engine, cid) as s:
            s.add(
                Task(
                    id=uuid.uuid4(),
                    company_id=cid,
                    title="legacy task",
                    status="pending",
                    priority=1,
                )
            )
            s.add(MemoryRecord(company_id=cid, scope="company", content="legacy memory"))
            await s.commit()
    finally:
        await engine.dispose()


def _remediation_settings(dep: Deployment, mode: str) -> dict[str, str]:
    return {**dep.role_settings(passwords=False), "nexus.remediation_mode": mode}


async def test_legacy_layout_is_a_real_weakness_and_the_preflight_names_it(legacy):
    app = await asyncpg.connect(legacy.dsn(legacy.app))
    try:
        tx = app.transaction()
        await tx.start()
        await app.execute("ALTER TABLE memory_records DISABLE ROW LEVEL SECURITY")
        await app.execute("DROP TRIGGER audit_log_append_only ON audit_log")
        await tx.rollback()
    finally:
        await app.close()
    problems = await db_migrate.check_roles(
        legacy.sa_url(legacy.migrator), legacy.migrator, legacy.app, legacy.system
    )
    assert any("owns" in p and "remediation" in p for p in problems), problems
    with pytest.raises(db_migrate.PreflightError, match="remediation"):
        await db_migrate.run(legacy.migrate_env())


async def test_dry_run_reports_and_changes_nothing(legacy):
    await _legacy_data(legacy)
    owners = await _owners(legacy)
    notices = await _run_script(legacy.dsn(), REMEDIATE, _remediation_settings(legacy, "report"))
    assert any(n.startswith("[transfer] table") and "memory_records" in n for n in notices), notices
    assert any(n.startswith("[transfer] schema") for n in notices)
    assert any(n.startswith("[acl]") for n in notices)
    assert any("dry run" in n for n in notices)
    assert await _owners(legacy) == owners
    assert any(o == legacy.app for o in owners.values())


async def test_remediation_moves_ownership_and_keeps_everything_else(legacy):
    await _legacy_data(legacy)
    counts = await _row_counts(legacy)
    protections = await _protections(legacy)
    version = await _val(legacy.dsn(), "SELECT version_num FROM alembic_version")
    assert counts["tasks"] == 1 and counts["memory_records"] == 1

    notices = await _run_script(legacy.dsn(), REMEDIATE, _remediation_settings(legacy, "apply"))
    assert any(n.startswith("applied:") for n in notices), notices

    await _assert_owned_and_granted_as_designed(legacy)
    assert await _row_counts(legacy) == counts
    assert await _protections(legacy) == protections
    assert await _val(legacy.dsn(), "SELECT version_num FROM alembic_version") == version
    assert (
        await _val(
            legacy.dsn(),
            "SELECT count(*) FROM pg_shdepend WHERE refclassid = 'pg_authid'::regclass "
            "AND deptype = 'o' AND refobjid = (SELECT oid FROM pg_roles WHERE rolname = $1)",
            legacy.app,
        )
        == 0
    )

    # The application role can no longer change the protections, and still works.
    conn = await asyncpg.connect(legacy.dsn(legacy.app))
    try:
        for stmt in (
            "ALTER TABLE memory_records DISABLE ROW LEVEL SECURITY",
            "DROP TRIGGER audit_log_append_only ON audit_log",
            "DROP POLICY tenant_isolation ON memory_records",
            "DROP TABLE tasks",
            "TRUNCATE tasks",
        ):
            with pytest.raises(DENIED):
                await conn.execute(stmt)
    finally:
        await conn.close()
    engine = create_async_engine(legacy.sa_url(legacy.app), poolclass=NullPool)
    try:
        cid = await _val(legacy.dsn(), "SELECT company_id FROM tasks")
        async with _session(engine, cid) as s:
            assert len((await s.execute(sa.select(Task))).scalars().all()) == 1
    finally:
        await engine.dispose()

    # The production entry point now accepts the database, and a second apply is a no-op.
    await db_migrate.run(legacy.migrate_env())
    await _run_script(legacy.dsn(), REMEDIATE, _remediation_settings(legacy, "apply"))
    await _assert_owned_and_granted_as_designed(legacy)


async def test_remediation_refuses_what_it_cannot_move_and_rolls_back(legacy):
    await _exec(
        legacy.dsn(),
        f"CREATE SCHEMA other AUTHORIZATION {legacy.app}; CREATE TABLE other.t (i integer)",
    )
    owners = await _owners(legacy)
    notices = await _run_script(legacy.dsn(), REMEDIATE, _remediation_settings(legacy, "report"))
    assert any(n.startswith("[manual]") for n in notices), notices
    with pytest.raises(asyncpg.RaiseError, match="refusing to apply"):
        await _run_script(legacy.dsn(), REMEDIATE, _remediation_settings(legacy, "apply"))
    assert await _owners(legacy) == owners


async def test_remediation_refuses_a_database_that_is_not_nexus(roles_only):
    with pytest.raises(asyncpg.RaiseError, match="not a NEXUS database"):
        await _run_script(roles_only.dsn(), REMEDIATE, _remediation_settings(roles_only, "apply"))
