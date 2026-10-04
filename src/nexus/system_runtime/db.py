"""Connections and role validation for the system runtime.

The system engine is created only by :func:`bootstrap`, which only the system runtime
entry point calls. Nothing creates it at import time, so importing this module in the API
or a worker opens no connection and reads no credential. The identity is checked against
the live PostgreSQL role attributes, never against the username in a URL.
"""

from __future__ import annotations

import logging
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, create_async_engine
from sqlmodel.ext.asyncio.session import AsyncSession

logger = logging.getLogger(__name__)

SYSTEM_URL_VARIABLE = "SYSTEM_DATABASE_URL"

_ROLE = text(
    "SELECT current_user AS name, rolsuper, rolbypassrls, rolcreaterole, rolcreatedb, "
    "has_schema_privilege(current_user, 'public', 'CREATE') AS can_create "
    "FROM pg_roles WHERE rolname = current_user"
)

_engine: AsyncEngine | None = None


class SystemRuntimeError(RuntimeError):
    """A refusal with a stable ``code``. The message never contains a connection string."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code


async def check_system_role(conn: AsyncConnection) -> list[str]:
    """Stable codes for every way the connected role is wrong for the system runtime."""
    from nexus.db_migrate import _OWNED_BY

    role = (await conn.execute(_ROLE)).one()
    problems: list[str] = []
    if not role.rolbypassrls:
        problems.append("SYSTEM_ROLE_NOT_BYPASSRLS")
    if role.rolsuper or role.rolcreaterole or role.rolcreatedb:
        problems.append("SYSTEM_ROLE_TOO_POWERFUL")
    if role.can_create:
        problems.append("SYSTEM_ROLE_CAN_CREATE")
    owned = (await conn.execute(_OWNED_BY, {"r": role.name})).scalar_one()
    if owned:
        problems.append("SYSTEM_ROLE_OWNS_OBJECTS")
    return problems


async def check_app_role(conn: AsyncConnection) -> list[str]:
    """Stable codes for a ``DATABASE_URL`` identity that is not the tenant-bound role."""
    role = (await conn.execute(_ROLE)).one()
    if role.rolbypassrls or role.rolsuper:
        return ["APP_ROLE_BYPASSES_RLS"]
    return []


async def validate_roles(app_engine: AsyncEngine, system_engine: AsyncEngine) -> list[str]:
    """Validate both identities against PostgreSQL. An empty list means both are correct."""
    async with app_engine.connect() as conn:
        problems = await check_app_role(conn)
        app_name = (await conn.execute(text("SELECT current_user"))).scalar_one()
    async with system_engine.connect() as conn:
        problems += await check_system_role(conn)
        system_name = (await conn.execute(text("SELECT current_user"))).scalar_one()
    if app_name == system_name:
        problems.append("APP_AND_SYSTEM_ROLE_IDENTICAL")
    return problems


def bootstrap() -> AsyncEngine:
    """Create the system engine. Only the system runtime entry point calls this."""
    global _engine
    url = os.environ.get(SYSTEM_URL_VARIABLE, "")
    if not url:
        raise SystemRuntimeError(
            "SYSTEM_CREDENTIAL_MISSING", f"{SYSTEM_URL_VARIABLE} is not set for the system runtime."
        )
    if _engine is None:
        kwargs: dict = {}
        if not url.startswith("sqlite"):
            # Discovery is a handful of short queries, so the pool stays tiny.
            kwargs = {
                "pool_size": 2,
                "max_overflow": 1,
                "pool_pre_ping": True,
                "pool_timeout": 10,
                "connect_args": {
                    "server_settings": {
                        "statement_timeout": "30000",
                        "idle_in_transaction_session_timeout": "60000",
                        "lock_timeout": "5000",
                    }
                },
            }
        _engine = create_async_engine(url, **kwargs)
    return _engine


async def dispose() -> None:
    """Close the system engine at shutdown."""
    global _engine
    if _engine is not None:
        await _engine.dispose()
        _engine = None


@asynccontextmanager
async def discovery_session(operation: str) -> AsyncIterator[AsyncSession]:
    """A cross-tenant read session for one catalogued operation.

    Refused for a name outside the catalogue and in any process that did not call
    :func:`bootstrap`, so an API or worker process cannot get a privileged session even
    by importing this module.
    """
    from nexus.system_runtime.ops import OPERATIONS

    if operation not in OPERATIONS:
        raise SystemRuntimeError(
            "OPERATION_NOT_ALLOWED", f"{operation!r} is not a catalogued operation."
        )
    if _engine is None:
        raise SystemRuntimeError(
            "SYSTEM_RUNTIME_NOT_BOOTSTRAPPED", "No system engine in this process."
        )
    async with AsyncSession(_engine, expire_on_commit=False) as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
