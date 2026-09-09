"""WP-22g / M10: Tier 2 per-agent budgets via reserve_chain.

A call must fit under every scope that governs it: the company wall AND the
agent's own cap, most-restrictive-wins. If any scope denies, every partial hold
already taken is rolled back so a refusal leaves no orphaned reserved rows.

R1: tests invoke reserve_chain. R10: no network. Uses an in-memory SQLite DB
with the real BudgetPolicy/CostEvent tables.
"""

import uuid

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlmodel import SQLModel, select

from nexus.models.budget import BudgetPolicy, CostEvent
from nexus.services.budget_service import BudgetService


@pytest_asyncio.fixture
async def db():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        # Only the two tables this test touches, so unrelated models needn't import.
        await conn.run_sync(
            lambda c: SQLModel.metadata.create_all(
                c, tables=[BudgetPolicy.__table__, CostEvent.__table__]
            )
        )
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        yield session
    await engine.dispose()


def _policy(company_id, scope_type, scope_id, amount):
    return BudgetPolicy(
        company_id=company_id,
        scope_type=scope_type,
        scope_id=scope_id,
        metric="cost_cents",
        window_kind="monthly",
        amount=amount,
        hard_stop_enabled=True,
    )


async def test_agent_policy_denies_when_company_policy_would_allow(db):
    """The inner (agent) wall stops a call the company wall alone would pass."""
    company_id, agent_id = uuid.uuid4(), uuid.uuid4()
    db.add(_policy(company_id, "company", company_id, 10_000))  # $100 company
    db.add(_policy(company_id, "agent", agent_id, 50))  # $0.50 agent cap
    await db.commit()

    svc = BudgetService(db)
    allowed, ids, check = await svc.reserve_chain(
        company_id=company_id, estimate_cents=100, agent_id=agent_id
    )
    assert allowed is False
    assert ids == []

    # Rollback: no reserved holds left behind on the company policy either.
    rows = (await db.execute(select(BudgetPolicy))).scalars().all()
    assert all(p.reserved_cents == 0 for p in rows)
    # No stray reserved CostEvent rows.
    evts = (await db.execute(select(CostEvent))).scalars().all()
    assert all(e.status != "reserved" for e in evts)


async def test_chain_allows_and_holds_both_scopes(db):
    """When both scopes allow, a hold lands on each."""
    company_id, agent_id = uuid.uuid4(), uuid.uuid4()
    db.add(_policy(company_id, "company", company_id, 10_000))
    db.add(_policy(company_id, "agent", agent_id, 500))
    await db.commit()

    svc = BudgetService(db)
    allowed, ids, check = await svc.reserve_chain(
        company_id=company_id, estimate_cents=100, agent_id=agent_id
    )
    assert allowed is True
    assert len(ids) == 2  # company + agent

    rows = {p.scope_type: p for p in (await db.execute(select(BudgetPolicy))).scalars()}
    assert rows["company"].reserved_cents == 100
    assert rows["agent"].reserved_cents == 100


async def test_chain_unlimited_when_no_policies(db):
    """No policy anywhere -> allowed, no holds, caller still proceeds."""
    company_id, agent_id = uuid.uuid4(), uuid.uuid4()
    svc = BudgetService(db)
    allowed, ids, check = await svc.reserve_chain(
        company_id=company_id, estimate_cents=100, agent_id=agent_id
    )
    assert allowed is True
    assert ids == []
