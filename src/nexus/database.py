"""Async database engine and session management."""

import logging
import uuid
from collections.abc import AsyncGenerator, AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.sql import Select
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from nexus.config import settings

logger = logging.getLogger(__name__)

# Create async engine with connection pooling
# SQLite doesn't support pool_size/max_overflow, so only add them for other backends
_engine_kwargs: dict = {
    "echo": settings.debug,
}
if not settings.database_url.startswith("sqlite"):
    _engine_kwargs.update({
        "pool_size": 20,
        "max_overflow": 10,
        "pool_pre_ping": True,
        "pool_recycle": 1800,
        "pool_timeout": 10,
        "connect_args": {
            "server_settings": {
                "statement_timeout": "30000",
                "idle_in_transaction_session_timeout": "60000",
                "lock_timeout": "5000",
            },
        },
    })

engine = create_async_engine(settings.database_url, **_engine_kwargs)

# Async session factory for app (nexus_app)
async_session_factory = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)

# Dedicated engine and session factory for privileged system maintenance (nexus_system)
_system_engine = None
_system_session_factory = None

if settings.system_database_url:
    _system_engine = create_async_engine(settings.system_database_url, **_engine_kwargs)
    _system_session_factory = async_sessionmaker(
        _system_engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )


@asynccontextmanager
async def tenant_session(company_id: uuid.UUID) -> AsyncIterator[AsyncSession]:
    """Session with session-level RLS tenant context (WP-7, WP-9) and safe pool reset."""
    async with async_session_factory() as session:
        is_postgres = not settings.database_url.startswith("sqlite")
        if is_postgres:
            await session.execute(
                text("SELECT set_config('nexus.company_id', :cid, false)"),
                {"cid": str(company_id)},
            )
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
        finally:
            if is_postgres:
                try:
                    await session.execute(text("RESET nexus.company_id;"))
                except Exception as exc:
                    logger.debug("tenant_session reset failed: %s", exc)


@asynccontextmanager
async def system_session(reason: str) -> AsyncIterator[AsyncSession]:
    """Cross-tenant session for privileged maintenance holding BYPASSRLS (WP-7)."""
    logger.info("system_session acquired: %s", reason)
    factory = _system_session_factory or async_session_factory
    async with factory() as session:
        is_postgres = not (settings.system_database_url or settings.database_url).startswith("sqlite")
        if is_postgres:
            res = await session.execute(
                text("SELECT rolname, rolbypassrls, rolsuper FROM pg_roles WHERE rolname = current_user;")
            )
            row = res.first()
            if row and not (row[1] or row[2]):
                raise RuntimeError(
                    f"system_session requires role with BYPASSRLS or SUPERUSER. Current role: {row[0]}"
                )
        try:
            yield session
        except Exception:
            await session.rollback()
            raise


async def assert_role_rls_posture() -> None:
    """Validate database role RLS posture on startup (WP-7)."""
    if settings.database_url.startswith("sqlite"):
        return
    try:
        async with async_session_factory() as session:
            result = await session.execute(
                text("SELECT rolname, rolbypassrls, rolsuper FROM pg_roles WHERE rolname = current_user;")
            )
            row = result.first()
            if row and (row[1] or row[2]):
                msg = (
                    f"DATABASE RLS POSTURE FAILURE: Connected app role '{row[0]}' has "
                    f"rolbypassrls={row[1]}, rolsuper={row[2]}! Row Level Security is disabled."
                )
                if not settings.allow_bypassrls_app_role:
                    raise RuntimeError(msg)
                logger.warning("%s (allow_bypassrls_app_role is True)", msg)
    except Exception as exc:
        if not settings.allow_bypassrls_app_role and isinstance(exc, RuntimeError):
            raise
        logger.warning("Could not verify database role RLS posture: %s", exc)


def tenant_scope[M](model: type[M], company_id: uuid.UUID) -> Select[tuple[M]]:
    """A ``SELECT`` over ``model`` already filtered to one tenant (Phase 5.2)."""
    column = getattr(model, "company_id", None)
    if column is None:
        raise AttributeError(
            f"{model.__name__} has no company_id column, so it cannot be "
            "tenant-scoped -- query it directly and say why in a comment"
        )
    return select(model).where(column == company_id)


async def get_session(company_id: uuid.UUID | None = None) -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency that provides an async database session.

    Yields an AsyncSession and ensures it is closed and reset after use.
    """
    async with async_session_factory() as session:
        is_postgres = not settings.database_url.startswith("sqlite")
        if is_postgres and company_id:
            await session.execute(
                text("SELECT set_config('nexus.company_id', :cid, false)"),
                {"cid": str(company_id)},
            )
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            if is_postgres and company_id:
                try:
                    await session.execute(text("RESET nexus.company_id;"))
                except Exception as exc:
                    logger.debug("get_session reset failed: %s", exc)
            await session.close()
