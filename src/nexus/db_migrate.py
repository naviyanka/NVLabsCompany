"""Production migration entry point: ``python -m nexus.db_migrate``.

Runs ``alembic upgrade head`` as the migrator role and nothing else. It reads only
``MIGRATION_DATABASE_URL``. It never falls back to ``DATABASE_URL``: the application role
must not own the schema, because an owner can drop triggers, disable row level security
and alter policies.

Before and after the upgrade it checks the identities and the ownership of the schema.
Messages name roles, never connection strings or passwords.
"""

from __future__ import annotations

import asyncio
import os
import sys

from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine

MIGRATION_URL_VARIABLE = "MIGRATION_DATABASE_URL"
DEFAULT_MIGRATOR = "nexus_migrator"
DEFAULT_APP = "nexus_app"
DEFAULT_SYSTEM = "nexus_system"

_ROLE = text(
    "SELECT rolsuper, rolbypassrls, rolcreaterole, rolcreatedb FROM pg_roles WHERE rolname = :r"
)
_OWNED_BY = text(
    """
    SELECT count(*) FROM (
        SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
         WHERE n.nspname = 'public' AND pg_get_userbyid(c.relowner) = :r
           AND c.relkind NOT IN ('i', 'I', 't')
        UNION ALL
        SELECT 1 FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace
         WHERE n.nspname = 'public' AND pg_get_userbyid(p.proowner) = :r
        UNION ALL
        SELECT 1 FROM pg_namespace WHERE nspname = 'public' AND pg_get_userbyid(nspowner) = :r
        UNION ALL
        SELECT 1 FROM pg_database
         WHERE datname = current_database() AND pg_get_userbyid(datdba) = :r
    ) owned
    """
)


class PreflightError(RuntimeError):
    """The migration must not run: the database is not set up as the contract requires."""


async def check_roles(
    url: str, migrator: str, app: str, system: str, *, after: bool = False
) -> list[str]:
    """Return every reason the migration must not run, or the schema is not as required."""
    problems: list[str] = []
    if len({migrator, app, system}) != 3:
        return ["the migrator, application and system roles must be three different roles"]
    engine = create_async_engine(url)
    try:
        async with engine.connect() as conn:
            who = (await conn.execute(text("SELECT current_user"))).scalar_one()
            if who != migrator:
                problems.append(
                    f"connected as {who!r}, but the migration identity must be {migrator!r}"
                )
            if who in (DEFAULT_APP, DEFAULT_SYSTEM, app, system):
                problems.append(f"{who!r} is an application or system identity, not a migrator")

            mine = (await conn.execute(_ROLE, {"r": who})).one()
            if mine.rolsuper or mine.rolbypassrls:
                problems.append(f"migration role {who!r} must not be SUPERUSER or BYPASSRLS")
            can_create = (
                await conn.execute(
                    text("SELECT has_schema_privilege(current_user, 'public', 'CREATE')")
                )
            ).scalar_one()
            if not can_create:
                problems.append(f"migration role {who!r} cannot CREATE in schema public")
            version_owner = (
                await conn.execute(
                    text(
                        "SELECT pg_get_userbyid(relowner) FROM pg_class "
                        "WHERE oid = to_regclass('public.alembic_version')"
                    )
                )
            ).scalar_one_or_none()
            if version_owner not in (None, who):
                problems.append(
                    f"public.alembic_version is owned by {version_owner!r}, not {who!r}: "
                    "an existing installation needs the ownership remediation "
                    "(docs/runbooks/database-roles.md)"
                )

            theirs = (await conn.execute(_ROLE, {"r": app})).one_or_none()
            if theirs is None:
                problems.append(
                    f"application role {app!r} does not exist: provision the roles first"
                )
            else:
                bad = [
                    name
                    for name, value in zip(
                        ("SUPERUSER", "BYPASSRLS", "CREATEROLE", "CREATEDB"), theirs, strict=True
                    )
                    if value
                ]
                if bad:
                    problems.append(f"application role {app!r} must not have {', '.join(bad)}")
                if (
                    await conn.execute(
                        text("SELECT pg_has_role(:a, :m, 'MEMBER')"), {"a": app, "m": who}
                    )
                ).scalar_one():
                    problems.append(f"application role {app!r} must not be a member of {who!r}")
                owned = (await conn.execute(_OWNED_BY, {"r": app})).scalar_one()
                if owned:
                    where = "after the upgrade" if after else "before the upgrade"
                    problems.append(
                        f"application role {app!r} owns {owned} schema object(s) {where}: "
                        "run the ownership remediation (docs/runbooks/database-roles.md)"
                    )
    finally:
        await engine.dispose()
    return problems


def _upgrade(url: str) -> None:
    from alembic.config import Config

    from alembic import command

    cfg = Config("alembic.ini")
    # configparser treats % as interpolation, and a URL-encoded password has them.
    cfg.set_main_option("sqlalchemy.url", url.replace("%", "%%"))
    command.upgrade(cfg, "head")


async def seal_version_table(url: str, app: str, system: str) -> None:
    """Take every privilege on ``alembic_version`` away from the runtime roles.

    Default privileges would give them DML on it. The runtime never reads it on PostgreSQL,
    and a runtime role that could rewrite it could make the next migration skip or repeat work.
    """
    engine = create_async_engine(url)
    try:
        quote = engine.dialect.identifier_preparer.quote
        async with engine.begin() as conn:
            await conn.execute(
                text(
                    f"REVOKE ALL ON TABLE public.alembic_version "
                    f"FROM PUBLIC, {quote(app)}, {quote(system)}"
                )
            )
    finally:
        await engine.dispose()


async def run(environ: dict[str, str] | None = None) -> None:
    env = os.environ if environ is None else environ
    url = env.get(MIGRATION_URL_VARIABLE, "").strip()
    if not url:
        raise PreflightError(
            f"{MIGRATION_URL_VARIABLE} is not set. Migrations never use DATABASE_URL: "
            "supply the migrator credential."
        )
    try:
        driver = make_url(url).drivername
    except Exception:  # the parser's message can quote the URL, and with it the password
        raise PreflightError(f"{MIGRATION_URL_VARIABLE} is not a valid database URL") from None
    if driver != "postgresql+asyncpg":
        raise PreflightError(f"{MIGRATION_URL_VARIABLE} must use the postgresql+asyncpg driver")

    roles = (
        env.get("NEXUS_MIGRATION_ROLE") or DEFAULT_MIGRATOR,
        env.get("DATABASE_USER") or DEFAULT_APP,
        env.get("DATABASE_SYSTEM_USER") or DEFAULT_SYSTEM,
    )
    problems = await check_roles(url, *roles)
    if problems:
        raise PreflightError("; ".join(problems))
    await asyncio.to_thread(_upgrade, url)
    await seal_version_table(url, roles[1], roles[2])
    problems = await check_roles(url, *roles, after=True)
    if problems:
        raise PreflightError("; ".join(problems))
    print(f"migrated to head as {roles[0]}; {roles[1]} owns nothing")


def main() -> int:
    try:
        asyncio.run(run())
    except PreflightError as exc:
        print(f"migration refused: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
