"""Governance Studio on real PostgreSQL: races, row-level security and read-only simulation.

Runs as the non-superuser ``nexus_app`` role so row-level security applies. Skips without
PostgreSQL (``TEST_DATABASE_URL`` or Docker). Every test makes its own companies, so a second run
on the same database does not collide.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
import sqlalchemy as sa
from fastapi import HTTPException
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from nexus.auth.principal import Principal
from nexus.models.agent import Agent
from nexus.models.company import Company
from nexus.models.governance import AuditLog
from nexus.models.governance_studio import (
    GovernancePolicyDraft,
    GovernancePolicyVersion,
    GovernanceRestriction,
    GovernanceTempAccess,
)
from nexus.models.tool import ToolPolicy
from nexus.services.governance_studio import grants, policies, runtime, simulate
from nexus.tools import governance_overlay as overlay
from nexus.tools.access import check_tool_access
from tests.test_postgres_integration import (  # noqa: F401 -- module fixtures
    app_user_postgres_url,
    migrated_postgres_url,
    postgres_container,
)
from tests.test_tool_access import ctx

pytestmark = [pytest.mark.postgres, pytest.mark.integration]

DENY_WRITES = {"name": "deny writes", "effect": "deny", "conditions": {"risk_level": ["write"]}}
DENY_READS = {"name": "deny reads", "effect": "deny", "conditions": {"risk_level": ["read"]}}
WHY = "concurrency check"


def _now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _admin(company: uuid.UUID, email: str = "gov@example.test") -> Principal:
    return Principal(
        kind="user", company_id=company, role="admin", user_id=uuid.uuid4(), email=email
    )


@pytest.fixture
async def pg(app_user_postgres_url):  # noqa: F811
    """Open a tenant session as the application role; seed a company with one agent."""
    engine = create_async_engine(app_user_postgres_url, pool_size=20)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    def session(company: uuid.UUID) -> Any:
        class _Scope:
            async def __aenter__(self) -> AsyncSession:
                self.db = factory()
                await self.db.execute(
                    sa.text("SELECT set_config('nexus.company_id', :c, false)"), {"c": str(company)}
                )
                return self.db

            async def __aexit__(self, *exc: object) -> None:
                await self.db.close()

        return _Scope()

    async def seed(name: str = "Gov") -> dict[str, uuid.UUID]:
        company = uuid.uuid4()
        async with factory() as db:
            db.add(Company(id=company, name=f"{name} {company}"))
            await db.commit()
        async with session(company) as db:
            agent = Agent(company_id=company, name="A", role="engineer")
            db.add(agent)
            await db.commit()
        return {"company": company, "agent": agent.id}

    async def grant(ids: dict[str, uuid.UUID], **over: Any) -> uuid.UUID:
        row = GovernanceTempAccess(
            company_id=ids["company"], agent_id=ids["agent"], effect="allow",
            tool_name="ceo_request_hire", status="active", expires_at=_now() + timedelta(hours=1),
            requested_by="x", approved_by="y", **over,
        )
        async with session(ids["company"]) as db:
            db.add(row)
            await db.commit()
        return row.id

    yield type("PG", (), {"session": staticmethod(session), "seed": staticmethod(seed),
                          "grant": staticmethod(grant)})
    await engine.dispose()


async def _consume(pg, ids, grant_id) -> bool:  # noqa: ANN001
    async with pg.session(ids["company"]) as db:
        spent = await overlay.consume_temp_grant(db, ids["company"], grant_id)
        await db.commit()
        return spent


async def _grant_row(pg, ids, grant_id) -> GovernanceTempAccess:  # noqa: ANN001
    async with pg.session(ids["company"]) as db:
        return (
            await db.execute(
                sa.select(GovernanceTempAccess).where(GovernanceTempAccess.id == grant_id)
            )
        ).scalar_one()


class TestGrantRaces:
    async def test_a_one_use_grant_is_spent_exactly_once(self, pg):  # noqa: ANN001
        ids = await pg.seed()
        grant_id = await pg.grant(ids, max_uses=1)
        results = await asyncio.gather(*[_consume(pg, ids, grant_id) for _ in range(12)])
        assert results.count(True) == 1
        row = await _grant_row(pg, ids, grant_id)
        assert (row.used_count, row.status) == (1, "used_up")

    async def test_a_limited_grant_never_exceeds_its_uses(self, pg):  # noqa: ANN001
        ids = await pg.seed()
        grant_id = await pg.grant(ids, max_uses=3)
        results = await asyncio.gather(*[_consume(pg, ids, grant_id) for _ in range(12)])
        assert results.count(True) == 3
        assert (await _grant_row(pg, ids, grant_id)).used_count == 3

    async def test_one_invocation_replayed_at_once_is_charged_once(self, pg):  # noqa: ANN001
        ids = await pg.seed()
        grant_id = await pg.grant(ids, max_uses=5)

        async def use(key: str) -> bool:
            async with pg.session(ids["company"]) as db:
                spent = await overlay.consume_temp_grant(db, ids["company"], grant_id, key)
                await db.commit()
                return spent

        same = await asyncio.gather(*[use("inv-a") for _ in range(8)])
        assert all(same)
        assert (await _grant_row(pg, ids, grant_id)).used_count == 1
        assert await use("inv-b")
        assert (await _grant_row(pg, ids, grant_id)).used_count == 2

    async def test_one_use_grant_with_distinct_invocations_has_one_winner(self, pg):  # noqa: ANN001
        ids = await pg.seed()
        grant_id = await pg.grant(ids, max_uses=1)

        async def use(key: str) -> bool:
            async with pg.session(ids["company"]) as db:
                spent = await overlay.consume_temp_grant(db, ids["company"], grant_id, key)
                await db.commit()
                return spent

        results = await asyncio.gather(*[use(f"inv-{i}") for i in range(10)])
        assert results.count(True) == 1
        assert (await _grant_row(pg, ids, grant_id)).used_count == 1

    async def test_revoke_and_use_race_has_one_winner(self, pg):  # noqa: ANN001
        for _ in range(6):
            ids = await pg.seed()
            grant_id = await pg.grant(ids, max_uses=1)

            async def revoke(ids=ids, grant_id=grant_id) -> bool:
                async with pg.session(ids["company"]) as db:
                    try:
                        await grants.revoke(
                            db, ids["company"], _admin(ids["company"]), grant_id,
                            grants.Revoke(reason=WHY),
                        )
                        await db.commit()
                        return True
                    except HTTPException:
                        await db.rollback()
                        return False

            spent, revoked = await asyncio.gather(_consume(pg, ids, grant_id), revoke())
            assert spent != revoked, "one of use and revoke must win, never both or neither"
            row = await _grant_row(pg, ids, grant_id)
            assert row.used_count == (1 if spent else 0)
            assert row.status == ("used_up" if spent else "revoked")

    async def test_an_expired_grant_cannot_be_spent(self, pg):  # noqa: ANN001
        ids = await pg.seed()
        grant_id = await pg.grant(ids, max_uses=None)
        async with pg.session(ids["company"]) as db:
            await db.execute(
                sa.update(GovernanceTempAccess)
                .where(GovernanceTempAccess.id == grant_id)
                .values(expires_at=_now() - timedelta(seconds=1))
            )
            await db.commit()
        assert not await _consume(pg, ids, grant_id)
        assert (await _grant_row(pg, ids, grant_id)).used_count == 0


class TestPublishRace:
    async def test_two_publishes_from_one_base_leave_one_winner_and_no_debris(self, pg):  # noqa: ANN001
        for _ in range(5):
            ids = await pg.seed()
            company, principal = ids["company"], _admin(ids["company"])
            drafts = []
            for rule in (DENY_WRITES, DENY_READS):
                async with pg.session(company) as db:
                    body = policies.DraftBody(rules=[rule], reason="tighten access")
                    drafts.append((await policies.create_draft(db, company, principal, body))["id"])
                    await db.commit()

            async def go(draft_id: str, company=company, principal=principal) -> Any:
                async with pg.session(company) as db:
                    try:
                        out = await policies.publish(
                            db, company, principal, uuid.UUID(draft_id), policies.PublishBody()
                        )
                        await db.commit()
                        return out
                    except HTTPException as exc:
                        await db.rollback()
                        return exc

            out = await asyncio.gather(*(go(d) for d in drafts))
            won = [o for o in out if isinstance(o, dict)]
            lost = [o for o in out if isinstance(o, HTTPException)]
            assert len(won) == 1 and len(lost) == 1
            assert lost[0].status_code == 409
            assert lost[0].detail["code"] in {"STALE_BASE", "VERSION_CONFLICT", "DRAFT_NOT_OPEN"}

            async with pg.session(company) as db:
                numbers = (await db.execute(
                    sa.select(GovernancePolicyVersion.version_number)
                    .order_by(GovernancePolicyVersion.version_number)
                )).scalars().all()
                active = (await db.execute(
                    sa.select(ToolPolicy.name).where(
                        ToolPolicy.company_id == company, ToolPolicy.is_active == True  # noqa: E712
                    )
                )).scalars().all()
                states = (await db.execute(sa.select(GovernancePolicyDraft.status))).scalars().all()
            winner = won[0]["rules"][0]["name"] if "rules" in won[0] else active[0]
            assert numbers == [1, 2]
            assert active == [winner]
            assert sorted(states) == ["draft", "published"]


class TestLockdownAgainstInvocation:
    async def _allowed(self, pg, ids) -> bool:  # noqa: ANN001
        t = {"acme": ids["company"], "a": ids["agent"]}
        async with pg.session(ids["company"]) as db:
            return (await check_tool_access(
                db, ctx(t), tool_name="manager_delegate_task", default_risk="write",
                enforcement="audit",
            )).allowed

    async def test_calls_after_the_lockdown_commits_are_all_denied(self, pg):  # noqa: ANN001
        ids = await pg.seed()
        assert await self._allowed(pg, ids)
        async with pg.session(ids["company"]) as db:
            await runtime.lockdown(
                db, ids["company"], _admin(ids["company"]),
                runtime.LockdownBody(reason="incident drill", confirm="LOCKDOWN"),
            )
            await db.commit()
        results = await asyncio.gather(*[self._allowed(pg, ids) for _ in range(10)])
        assert not any(results)
        async with pg.session(ids["company"]) as db:
            await runtime.release_lockdown(
                db, ids["company"], _admin(ids["company"]),
                runtime.LockdownBody(reason="drill is over", confirm="RELEASE LOCKDOWN"),
            )
            await db.commit()
        assert await self._allowed(pg, ids)

    async def test_two_lockdowns_at_once_both_end_with_one_release(self, pg):  # noqa: ANN001
        ids = await pg.seed()

        async def start() -> int:
            async with pg.session(ids["company"]) as db:
                try:
                    await runtime.lockdown(
                        db, ids["company"], _admin(ids["company"]),
                        runtime.LockdownBody(reason="incident drill", confirm="LOCKDOWN"),
                    )
                    await db.commit()
                    return 201
                except HTTPException as exc:
                    await db.rollback()
                    return exc.status_code

        await asyncio.gather(start(), start())
        async with pg.session(ids["company"]) as db:
            await runtime.release_lockdown(
                db, ids["company"], _admin(ids["company"]),
                runtime.LockdownBody(reason="drill is over", confirm="RELEASE LOCKDOWN"),
            )
            await db.commit()
        assert await self._allowed(pg, ids)


class TestTenantIsolation:
    async def test_each_tenant_sees_and_changes_only_its_own_rows(self, pg):  # noqa: ANN001
        a, b = await pg.seed("A"), await pg.seed("B")
        for ids in (a, b):
            await pg.grant(ids)
            async with pg.session(ids["company"]) as db:
                db.add(GovernanceRestriction(company_id=ids["company"], scope="company",
                                             kind="lockdown", reason="x", created_by="x"))
                db.add(GovernancePolicyDraft(company_id=ids["company"], created_by="x"))
                db.add(GovernancePolicyVersion(company_id=ids["company"], version_number=1,
                                               published_by="x"))
                await db.commit()
        models = (GovernanceTempAccess, GovernanceRestriction, GovernancePolicyDraft,
                  GovernancePolicyVersion)
        async with pg.session(a["company"]) as db:
            for model in models:
                owners = (await db.execute(sa.select(model.company_id))).scalars().all()
                assert owners == [a["company"]], model.__name__
            hit = await db.execute(
                sa.update(GovernanceRestriction)
                .where(GovernanceRestriction.company_id == b["company"])
                .values(active=False)
            )
            assert hit.rowcount == 0
            db.add(GovernanceRestriction(company_id=b["company"], scope="company",
                                         kind="lockdown", reason="forged", created_by="x"))
            with pytest.raises(DBAPIError):
                await db.flush()
            await db.rollback()
        async with pg.session(b["company"]) as db:
            row = (await db.execute(sa.select(GovernanceRestriction))).scalars().one()
            assert row.active and row.reason == "x"


class TestSimulationHasNoEffects:
    async def test_it_writes_nothing_and_spends_nothing(self, pg):  # noqa: ANN001
        ids = await pg.seed()
        grant_id = await pg.grant(ids, max_uses=1)
        tables = (GovernanceTempAccess, AuditLog, ToolPolicy, GovernanceRestriction,
                  GovernancePolicyDraft, GovernancePolicyVersion)

        async def counts() -> list[int]:
            async with pg.session(ids["company"]) as db:
                return [
                    (await db.execute(sa.select(sa.func.count()).select_from(m))).scalar_one()
                    for m in tables
                ]

        before = await counts()
        body = simulate.SimulateBody(
            agent_id=ids["agent"], capability_id="org.ceo_request_hire",
            proposed_rules=[{"name": "allow hire", "effect": "allow",
                             "conditions": {"tool_name": ["ceo_request_hire"]}}],
        )
        for _ in range(3):
            async with pg.session(ids["company"]) as db:
                agent = (await db.execute(sa.select(Agent))).scalars().one()
                out = await simulate.simulate(db, ids["company"], agent, body)
                assert out["simulated"] is True
                await db.rollback()
        assert await counts() == before
        assert (await _grant_row(pg, ids, grant_id)).used_count == 0
