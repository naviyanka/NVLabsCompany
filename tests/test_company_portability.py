"""Tests for company export/import (Phase 5.3).

The plan's acceptance test is a round-trip (5.3.4), and that is what the first
class does against a real SQLite database rather than a mock: the thing being
guarded against is a table or a foreign key the walker fails to follow, and a
mocked session returns whatever the test tells it to.

Two properties matter beyond "it ran". Secret columns must be absent from the
archive and named in the manifest (5.3.2), and the import must mint fresh IDs so
an archive restores into the database it came from without colliding with the
original rows (5.3.3) -- which also proves the remap is complete, since a
half-remapped graph would point children back at the original parents.
"""

import uuid

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlmodel import SQLModel

import nexus.models  # noqa: F401 -- registers every table on SQLModel.metadata
from nexus.models.agent import Agent
from nexus.models.company import Company, Department, Team
from nexus.models.secret import Secret, SecretVersion
from nexus.models.skill import AgentSkill, Skill
from nexus.models.task import Project, Task
from nexus.services.portability_service import (
    ARCHIVE_VERSION,
    CompanyPortabilityService,
    dump_archive,
    load_archive,
)


@pytest.fixture
async def populated(tmp_path):
    """One company with a multi-level graph, plus a second company as a control.

    The second company exists so the export is provably scoped: every assertion
    about row counts would also pass on an export that ignored ``company_id``
    if there were only one tenant in the database.
    """
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'portability.db'}")
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)

    alpha, beta = uuid.uuid4(), uuid.uuid4()
    dept_id, team_id = uuid.uuid4(), uuid.uuid4()
    agent_id, skill_id = uuid.uuid4(), uuid.uuid4()
    project_id, secret_id = uuid.uuid4(), uuid.uuid4()

    async with factory() as session:
        session.add(Company(id=alpha, name="Alpha", issue_prefix="ALP"))
        session.add(Company(id=beta, name="Beta"))
        session.add(Department(id=dept_id, company_id=alpha, name="Engineering",
                               head_agent_id=agent_id))
        session.add(Team(id=team_id, company_id=alpha, department_id=dept_id,
                         name="Platform"))
        session.add(Agent(id=agent_id, company_id=alpha, name="Ada",
                          role="engineer", department_id=dept_id, team_id=team_id))
        session.add(Skill(id=skill_id, company_id=alpha, name="python"))
        session.add(Project(id=project_id, company_id=alpha, name="Nexus"))
        session.add(Task(company_id=alpha, title="alpha-one",
                         project_id=project_id, assigned_agent_id=agent_id))
        session.add(Task(company_id=alpha, title="alpha-two"))
        session.add(Secret(id=secret_id, company_id=alpha, name="api-token",
                           encrypted_value="ENCRYPTED-DO-NOT-LEAK"))
        # Children with no company_id of their own -- reachable only via FK.
        session.add(AgentSkill(agent_id=agent_id, skill_id=skill_id))
        session.add(SecretVersion(secret_id=secret_id, version_number=1,
                                  encrypted_value="ENCRYPTED-V1"))
        # Control tenant.
        session.add(Agent(company_id=beta, name="Grace", role="engineer"))
        session.add(Task(company_id=beta, title="beta-secret"))
        await session.commit()

    yield factory, alpha, beta
    await engine.dispose()


async def _export(factory, company_id):
    async with factory() as session:
        return await CompanyPortabilityService(session).export_company(company_id)


class TestExport:
    """5.3.1 -- the archive holds the whole graph and nothing from other tenants."""

    async def test_exports_scoped_and_child_rows(self, populated):
        factory, alpha, _ = populated
        archive = await _export(factory, alpha)
        tables = archive["tables"]

        assert [row["name"] for row in tables["companies"]] == ["Alpha"]
        assert len(tables["agents"]) == 1
        assert len(tables["tasks"]) == 2
        assert {row["title"] for row in tables["tasks"]} == {"alpha-one", "alpha-two"}
        # Child tables carry no company_id; they are reachable only by FK.
        assert len(tables["agent_skills"]) == 1
        assert len(tables["secret_versions"]) == 1

    async def test_excludes_other_tenants_rows(self, populated):
        factory, alpha, _ = populated
        archive = await _export(factory, alpha)
        titles = {row["title"] for row in archive["tables"]["tasks"]}
        assert "beta-secret" not in titles
        names = {row["name"] for row in archive["tables"]["agents"]}
        assert "Grace" not in names

    async def test_manifest_is_versioned(self, populated):
        factory, alpha, _ = populated
        archive = await _export(factory, alpha)
        manifest = archive["manifest"]
        assert manifest["archive_version"] == ARCHIVE_VERSION
        assert manifest["company_id"] == str(alpha)
        assert manifest["company_name"] == "Alpha"
        assert manifest["row_counts"]["tasks"] == 2

    async def test_archive_is_json_serializable(self, populated):
        factory, alpha, _ = populated
        archive = await _export(factory, alpha)
        assert load_archive(dump_archive(archive)) == archive

    async def test_unknown_company_raises(self, populated):
        factory, _, _ = populated
        async with factory() as session:
            service = CompanyPortabilityService(session)
            with pytest.raises(ValueError, match="not found"):
                await service.export_company(uuid.uuid4())


class TestSecretScrubbing:
    """5.3.2 -- secret material never reaches the archive, and the loss is recorded."""

    async def test_secret_values_are_removed(self, populated):
        factory, alpha, _ = populated
        archive = await _export(factory, alpha)
        assert archive["tables"]["secrets"][0]["encrypted_value"] in (None, "")
        assert archive["tables"]["secret_versions"][0]["encrypted_value"] in (None, "")
        assert "DO-NOT-LEAK" not in dump_archive(archive)
        assert "ENCRYPTED-V1" not in dump_archive(archive)

    async def test_manifest_records_what_was_scrubbed(self, populated):
        factory, alpha, _ = populated
        scrubbed = (await _export(factory, alpha))["manifest"]["scrubbed"]
        assert scrubbed["secrets.encrypted_value"] == 1
        assert scrubbed["secret_versions.encrypted_value"] == 1

    async def test_non_secret_metadata_survives(self, populated):
        """Scrubbing is by column, not by table -- the secret's name still exports."""
        factory, alpha, _ = populated
        archive = await _export(factory, alpha)
        assert archive["tables"]["secrets"][0]["name"] == "api-token"


class TestRoundTrip:
    """5.3.3 / 5.3.4 -- import remaps every ID, so a restore into the source
    database duplicates the graph instead of colliding with it."""

    async def test_import_creates_a_new_company(self, populated):
        factory, alpha, _ = populated
        archive = await _export(factory, alpha)
        async with factory() as session:
            new_id = await CompanyPortabilityService(session).import_company(
                archive, new_name="Alpha Clone"
            )
        assert new_id != alpha
        async with factory() as session:
            clone = await session.get(Company, new_id)
            original = await session.get(Company, alpha)
        assert clone is not None and clone.name == "Alpha Clone"
        assert original is not None and original.name == "Alpha"

    async def test_round_trip_preserves_row_counts(self, populated):
        factory, alpha, _ = populated
        archive = await _export(factory, alpha)
        async with factory() as session:
            new_id = await CompanyPortabilityService(session).import_company(archive)
        clone = await _export(factory, new_id)
        assert clone["manifest"]["row_counts"] == archive["manifest"]["row_counts"]

    async def test_child_rows_point_at_imported_parents(self, populated):
        """A half-remapped graph would leave children attached to the original."""
        factory, alpha, _ = populated
        archive = await _export(factory, alpha)
        async with factory() as session:
            new_id = await CompanyPortabilityService(session).import_company(archive)

        async with factory() as session:
            agent = (
                await session.execute(
                    select(Agent).where(Agent.company_id == new_id)
                )
            ).scalars().one()
            team = (
                await session.execute(
                    select(Team).where(Team.company_id == new_id)
                )
            ).scalars().one()
            dept = (
                await session.execute(
                    select(Department).where(Department.company_id == new_id)
                )
            ).scalars().one()
            secret = (
                await session.execute(
                    select(Secret).where(Secret.company_id == new_id)
                )
            ).scalars().one()
            version = (
                await session.execute(
                    select(SecretVersion).where(SecretVersion.secret_id == secret.id)
                )
            ).scalars().one()

        assert agent.department_id == dept.id
        assert agent.team_id == team.id
        assert team.department_id == dept.id
        # head_agent_id carries no FK constraint, so it is remapped by value.
        assert dept.head_agent_id == agent.id
        assert version.secret_id == secret.id

    async def test_import_leaves_other_tenants_alone(self, populated):
        factory, alpha, beta = populated
        archive = await _export(factory, alpha)
        async with factory() as session:
            await CompanyPortabilityService(session).import_company(archive)
        async with factory() as session:
            count = await session.execute(
                select(func.count()).select_from(Task.__table__).where(
                    Task.company_id == beta
                )
            )
        assert count.scalar_one() == 1

    async def test_version_mismatch_is_rejected(self, populated):
        factory, alpha, _ = populated
        archive = await _export(factory, alpha)
        archive["manifest"]["archive_version"] = ARCHIVE_VERSION + 1
        async with factory() as session:
            service = CompanyPortabilityService(session)
            with pytest.raises(ValueError, match="unsupported archive version"):
                await service.import_company(archive)

    async def test_archive_without_company_is_rejected(self, populated):
        factory, alpha, _ = populated
        archive = await _export(factory, alpha)
        archive["tables"]["companies"] = []
        async with factory() as session:
            service = CompanyPortabilityService(session)
            with pytest.raises(ValueError, match="no company row"):
                await service.import_company(archive)
