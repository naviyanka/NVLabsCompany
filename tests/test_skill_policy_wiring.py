"""The skill policy has to be consulted where skills are actually assigned.

``skill_policy.decision()`` is a pure function with its own unit tests. Those
tests pass whether or not anything calls it, which is the failure mode this file
exists to close: the check runs inside ``SkillService.assign_skill_to_agent``,
against a policy document read from the company's settings row.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlmodel import SQLModel, select

import nexus.models  # noqa: F401 -- registers every table on SQLModel.metadata
from nexus.models.agent import Agent
from nexus.models.company import Company
from nexus.models.settings import CompanySettings
from nexus.models.skill import AgentSkill, Skill
from nexus.services.skill_service import SkillAccessDeniedError, SkillService

DENY_SHELL = {
    "schemaVersion": 1,
    "revision": 7,
    "defaultEffect": "allow",
    "rules": [
        {
            "id": "no-shell-for-juniors",
            "subject": {"roles": ["junior"]},
            "resource": {"keys": ["shell*"]},
            "effect": "deny",
            "remediation": "Ask an administrator to grant shell access.",
        }
    ],
}


@pytest.fixture
async def company_db(tmp_path):
    """A company with two agents and two skills, on real SQLite."""
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'skills.db'}")
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)

    company = Company(name="Acme")
    junior = Agent(company_id=company.id, name="Junior", role="junior", model="m")
    senior = Agent(company_id=company.id, name="Senior", role="staff", model="m")
    shell = Skill(company_id=company.id, name="shell_exec", category="local")
    docs = Skill(company_id=company.id, name="read_docs", category="catalog")

    async with factory() as session:
        session.add_all([company, junior, senior, shell, docs])
        await session.commit()

    yield factory, company, junior, senior, shell, docs
    await engine.dispose()


async def set_policy(factory, company_id: uuid.UUID, policy: dict | None) -> None:
    """Write (or clear) the company's skill policy document."""
    async with factory() as session:
        row = (
            await session.execute(
                select(CompanySettings).where(CompanySettings.company_id == company_id)
            )
        ).scalar_one_or_none()
        if row is None:
            row = CompanySettings(company_id=company_id)
            session.add(row)
        row.settings_json = {"skill_policy": policy} if policy else {}
        await session.commit()


class TestPolicyIsEnforcedOnAssignment:
    """A denial has to stop the write, not merely be computable."""

    async def test_denied_pairing_is_refused(self, company_db) -> None:
        factory, company, junior, _senior, shell, _docs = company_db
        await set_policy(factory, company.id, DENY_SHELL)

        async with factory() as session:
            with pytest.raises(SkillAccessDeniedError) as exc:
                await SkillService(session).assign_skill_to_agent(junior.id, shell.id)

        assert "Ask an administrator" in exc.value.remediation

        # The refusal must leave no AgentSkill row behind.
        async with factory() as session:
            rows = list((await session.execute(select(AgentSkill))).scalars())
        assert rows == []

    async def test_allowed_pairing_still_assigns(self, company_db) -> None:
        """The same policy must not block a skill it does not name."""
        factory, company, junior, _senior, _shell, docs = company_db
        await set_policy(factory, company.id, DENY_SHELL)

        async with factory() as session:
            await SkillService(session).assign_skill_to_agent(junior.id, docs.id)
            await session.commit()

        async with factory() as session:
            rows = list((await session.execute(select(AgentSkill))).scalars())
        assert len(rows) == 1
        assert rows[0].skill_id == docs.id

    async def test_rule_is_scoped_to_the_named_role(self, company_db) -> None:
        factory, company, _junior, senior, shell, _docs = company_db
        await set_policy(factory, company.id, DENY_SHELL)

        async with factory() as session:
            await SkillService(session).assign_skill_to_agent(senior.id, shell.id)
            await session.commit()

        async with factory() as session:
            rows = list((await session.execute(select(AgentSkill))).scalars())
        assert len(rows) == 1

    async def test_no_policy_allows_everything(self, company_db) -> None:
        """Open by default: a company without a document is unaffected."""
        factory, company, junior, _senior, shell, _docs = company_db
        await set_policy(factory, company.id, None)

        async with factory() as session:
            await SkillService(session).assign_skill_to_agent(junior.id, shell.id)
            await session.commit()

        async with factory() as session:
            rows = list((await session.execute(select(AgentSkill))).scalars())
        assert len(rows) == 1

    async def test_denial_is_recorded_in_the_audit_log(self, company_db) -> None:
        """A refusal an operator cannot see later is not much of a control."""
        from nexus.models.governance import AuditLog

        factory, company, junior, _senior, shell, _docs = company_db
        await set_policy(factory, company.id, DENY_SHELL)

        async with factory() as session:
            with pytest.raises(SkillAccessDeniedError):
                await SkillService(session).assign_skill_to_agent(junior.id, shell.id)
            await session.commit()

        async with factory() as session:
            rows = list((await session.execute(select(AuditLog))).scalars())

        denials = [row for row in rows if row.action == "skill.access_denied"]
        assert len(denials) == 1
        assert denials[0].details["policy_revision"] == 7
