"""Async database engine and session management."""

import uuid
from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.sql import Select
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from nexus.config import settings

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
    })

engine = create_async_engine(settings.database_url, **_engine_kwargs)

# Async session factory
async_session_factory = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


def tenant_scope[M](model: type[M], company_id: uuid.UUID) -> Select[tuple[M]]:
    """A ``SELECT`` over ``model`` already filtered to one tenant (Phase 5.2).

    The alternative to a helper is what the codebase had: every route writing
    ``select(Task).where(Task.company_id == company_id, ...)`` by hand, and a
    handful of them forgetting the first clause — which is not a visible bug,
    because an unfiltered query returns a longer valid list rather than an
    error, and in single-tenant development it looks exactly right.

    Starting from here makes the filter the default rather than something to
    remember::

        stmt = tenant_scope(Task, company_id).where(Task.status == "open")

    ``company_id`` is looked up on the model rather than assumed, so passing a
    model without the column is an :class:`AttributeError` at the call site
    instead of a query that silently reads across tenants. Rule R5 in
    ``scripts/arch_guard.py`` is what keeps new routes from skipping it.
    """
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
