"""SQLModel compatibility with the naive-UTC timestamp contract.

Every ``datetime`` column stores naive UTC (see ``nexus.models._time``).
SQLModel 0.0.45 maps ``datetime`` fields to a timezone-aware type that refuses
naive values, so pyproject.toml bounds SQLModel below it until the columns are
migrated deliberately. See docs/CI_BASELINE.md.
"""

from datetime import datetime
from importlib.metadata import requires, version

from packaging.requirements import Requirement
from sqlalchemy.ext.asyncio import create_async_engine
from sqlmodel import SQLModel, select
from sqlmodel.ext.asyncio.session import AsyncSession

from nexus.models.company import Company
from nexus.models.task import Goal


def test_installed_sqlmodel_is_within_the_declared_range() -> None:
    declared = next(
        Requirement(r) for r in requires("nexus") if Requirement(r).name == "sqlmodel"
    )
    assert any(s.operator == "<" for s in declared.specifier), declared
    assert declared.specifier.contains(version("sqlmodel")), (
        f"sqlmodel {version('sqlmodel')} is outside the supported range {declared}"
    )


def test_datetime_columns_stay_naive() -> None:
    for model in (Company, Goal):
        for name in ("created_at", "updated_at"):
            assert model.__table__.c[name].type.timezone is False, (model, name)


async def test_naive_timestamps_round_trip() -> None:
    engine = create_async_engine("sqlite+aiosqlite://")
    async with engine.begin() as conn:
        await conn.run_sync(
            SQLModel.metadata.create_all, tables=[Company.__table__, Goal.__table__]
        )
    stamp = datetime(2026, 1, 2, 3, 4, 5, 678901)
    async with AsyncSession(engine, expire_on_commit=False) as db:
        company = Company(name="compat")
        goal = Goal(company_id=company.id, title="compat", created_at=stamp, updated_at=stamp)
        db.add_all([company, goal])
        await db.commit()

    async with AsyncSession(engine) as db:
        loaded_company = (await db.exec(select(Company))).one()
        loaded_goal = (await db.exec(select(Goal))).one()
    await engine.dispose()

    assert loaded_company.created_at.tzinfo is None
    assert loaded_company.created_at == company.created_at
    assert (loaded_goal.created_at, loaded_goal.updated_at) == (stamp, stamp)
