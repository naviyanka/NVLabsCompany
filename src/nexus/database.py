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

# Async session factory
async_session_factory = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


@asynccontextmanager
async def tenant_session(company_id: uuid.UUID) -> AsyncIterator[AsyncSession]:
    """Session with transaction-local RLS tenant context (WP-2). Use in all non-HTTP paths."""
    async with async_session_factory() as session:
        if not settings.database_url.startswith("sqlite"):
            await session.execute(
                text("SELECT set_config('nexus.company_id', :cid, true)"),
                {"cid": str(company_id)},
            )
        try:
            yield session
        except Exception:
            await session.rollback()
            raise


@asynccontextmanager
async def system_session(reason: str) -> AsyncIterator[AsyncSession]:
    """Cross-tenant session for privileged maintenance roles holding BYPASSRLS (WP-2)."""
    logger.info("system_session acquired: %s", reason)
    async with async_session_factory() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise


async def assert_role_rls_posture() -> None:
    """Warn loudly if connecting to PostgreSQL with a BYPASSRLS role in standard runtime."""
    if settings.database_url.startswith("sqlite"):
        return
    try:
        async with async_session_factory() as session:
            result = await session.execute(
                text("SELECT rolname, rolbypassrls, rolsuper FROM pg_roles WHERE rolname = current_user;")
            )
            row = result.first()
            if row and (row[1] or row[2]):
                logger.warning(
                    "DATABASE RLS WARNING: Connected role '%s' has rolbypassrls=%s, rolsuper=%s! "
                    "Row Level Security (RLS) is bypassed in this connection.",
                    row[0],
                    row[1],
                    row[2],
                )
    except Exception as exc:
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


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency that provides an async database session.

    Yields an AsyncSession and ensures it is closed after use.
    """
    async with async_session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()
