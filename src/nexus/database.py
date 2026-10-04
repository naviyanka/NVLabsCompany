"""Async database engine and session management."""

import logging
import uuid
from collections.abc import AsyncGenerator, AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from functools import partial

from sqlalchemy import event, text
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

def _bind_tenant(session: AsyncSession, company_id: uuid.UUID) -> None:
    """Set the RLS tenant (WP-7, WP-9) at the start of every transaction.

    A commit hands the session's connection back to the pool and the next
    transaction may get another one, so the tenant is set per transaction,
    not once per session. ``is_local`` scopes it to that transaction: it
    never goes back to the pool on the connection for the next borrower.
    """
    if settings.database_url.startswith("sqlite"):
        return

    @event.listens_for(session.sync_session, "after_begin")
    def _set_tenant(_session: object, _transaction: object, connection: object) -> None:
        connection.execute(  # type: ignore[attr-defined]
            text("SELECT set_config('nexus.company_id', :cid, true)"), {"cid": str(company_id)}
        )


@asynccontextmanager
async def tenant_session(company_id: uuid.UUID) -> AsyncIterator[AsyncSession]:
    """Session whose every transaction carries the RLS tenant context."""
    async with async_session_factory() as session:
        _bind_tenant(session, company_id)
        try:
            yield session
        except Exception:
            await session.rollback()
            raise


def tenant_session_factory(
    company_id: uuid.UUID,
) -> Callable[[], AbstractAsyncContextManager[AsyncSession]]:
    """A ``session_factory`` for services that open ``async with factory() as s``.

    Every session it opens is a :func:`tenant_session` for ``company_id``, so a
    service built for one tenant's work cannot write without the RLS tenant.
    """
    return partial(tenant_session, company_id)


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
                return

            # Positive control (WP-15e): with no tenant context set, an RLS-covered table
            # must return zero rows. A non-zero count means ENABLE ROW LEVEL SECURITY
            # was never applied, or the policy is permissive.
            await session.execute(text("RESET nexus.company_id;"))
            leaked_res = await session.execute(text("SELECT count(*) FROM tasks;"))
            leaked = leaked_res.scalar_one_or_none() or 0
            if leaked > 0:
                raise RuntimeError(
                    f"DATABASE RLS POSTURE FAILURE: {leaked} rows of 'tasks' are "
                    "visible with no tenant context set - RLS is not enforcing"
                )
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
        if company_id:
            _bind_tenant(session, company_id)
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()
