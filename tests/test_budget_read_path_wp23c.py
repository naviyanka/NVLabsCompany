"""WP-23c / B5: budget usage read path must exclude released and expired holds.

At baseline the three budget GETs in
``src/nexus/api/routes/budgets.py`` summed **all** CostEvent rows with no
status filter — released holds and expired reservations were reported as
spend — and hard-coded a monthly window regardless of the policy's
window_kind. ``BudgetService._get_window_usage`` already filters status
correctly; these tests pin the read path to the same semantics.

R1: endpoint functions are invoked directly against a real SQLite
session — no HTTP, no mocks for the data path.
"""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlmodel import SQLModel

import nexus.models  # noqa: F401 — register all tables
from nexus.api.routes.budgets import (
    cost_trend,
    get_agent_budget_usage,
    get_company_budget_usage,
)
from nexus.models.budget import CostEvent
from nexus.models.company import Company
from nexus.services.budget_service import BudgetService


@pytest.fixture
async def db():
    engine = create_async_engine("sqlite+aiosqlite://")
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)
    session = async_sessionmaker(engine, class_=AsyncSession)()
    yield session
    await session.close()
    await engine.dispose()


def _utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


async def _seed(db: AsyncSession) -> tuple[uuid.UUID, uuid.UUID, uuid.UUID]:
    company_id, agent_id, other_agent_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    db.add(Company(id=company_id, name="Acme"))
    db.add(
        CostEvent(
            company_id=company_id,
            agent_id=agent_id,
            provider="anthropic",
            cost_cents=100,
            input_tokens=10,
            output_tokens=20,
            status="committed",
            occurred_at=_utcnow(),
        )
    )
    # Released hold: must NOT count as spend.
    db.add(
        CostEvent(
            company_id=company_id,
            agent_id=agent_id,
            provider="anthropic",
            cost_cents=500,
            status="released",
            occurred_at=_utcnow(),
        )
    )
    # Live reservation: DOES count (same as settled spend).
    db.add(
        CostEvent(
            company_id=company_id,
            agent_id=agent_id,
            provider="anthropic",
            cost_cents=30,
            status="reserved",
            occurred_at=_utcnow(),
        )
    )
    # Expired reservation: must NOT count.
    db.add(
        CostEvent(
            company_id=company_id,
            agent_id=agent_id,
            provider="anthropic",
            cost_cents=70,
            status="reserved",
            expires_at=_utcnow() - timedelta(seconds=1),
            occurred_at=_utcnow(),
        )
    )
    # Last month's committed spend: outside every current window.
    last_month = _utcnow().replace(day=1) - timedelta(days=1)
    db.add(
        CostEvent(
            company_id=company_id,
            agent_id=other_agent_id,
            provider="anthropic",
            cost_cents=900,
            status="committed",
            occurred_at=last_month,
        )
    )
    await db.commit()
    return company_id, agent_id, other_agent_id


async def test_company_usage_excludes_released_and_expired_holds(db):
    company_id, agent_id, _ = await _seed(db)
    resp = await get_company_budget_usage(company_id, db, window="monthly")
    # 100 committed + 30 live reservation; released 500 and expired 70 excluded.
    assert resp.total_cost_cents == 130
    assert resp.event_count == 2


async def test_agent_usage_excludes_released_and_expired_holds(db):
    company_id, agent_id, _ = await _seed(db)
    resp = await get_agent_budget_usage(agent_id, db, company_id, window="monthly")
    assert resp.total_cost_cents == 130
    assert resp.event_count == 2


async def test_agent_usage_scoped_to_calling_company(db):
    """An agent from another company must not be visible through this endpoint."""
    company_id, _, other_agent_id = await _seed(db)
    # other_agent belongs to a different company — its spend must not show.
    resp = await get_agent_budget_usage(other_agent_id, db, company_id, window="monthly")
    assert resp.total_cost_cents == 0
    assert resp.event_count == 0


async def test_usage_honors_window_kind(db):
    """B5 second half: the window is not hard-coded monthly."""
    company_id, agent_id, _ = await _seed(db)
    yesterday = _utcnow() - timedelta(days=1)
    db.add(
        CostEvent(
            company_id=company_id,
            agent_id=agent_id,
            provider="anthropic",
            cost_cents=25,
            status="committed",
            occurred_at=yesterday,
        )
    )
    await db.commit()

    monthly = await get_company_budget_usage(company_id, db, window="monthly")
    daily = await get_company_budget_usage(company_id, db, window="daily")
    assert monthly.total_cost_cents == 155  # 130 + yesterday's 25
    assert daily.total_cost_cents == 130  # yesterday outside the daily window


async def test_cost_trend_excludes_released_holds(db):
    company_id, _, _ = await _seed(db)
    trend = await cost_trend(company_id, db, days=1)
    assert trend[-1]["cost_cents"] == 130


async def test_service_and_endpoint_agree(db):
    """The read path must match BudgetService._get_window_usage exactly (R13)."""
    company_id, _, _ = await _seed(db)
    endpoint = await get_company_budget_usage(company_id, db, window="monthly")
    svc = BudgetService(db)
    summary = await svc.get_usage("company", company_id, "monthly")
    assert summary is not None
    assert endpoint.total_cost_cents == summary.total_cost_cents
    assert endpoint.event_count == summary.event_count
