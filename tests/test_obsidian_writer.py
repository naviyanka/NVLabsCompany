"""Controlled Obsidian writer tests."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlmodel import SQLModel, select

from nexus.models.agent import Agent
from nexus.models.company import Company
from nexus.models.governance import Approval
from nexus.models.obsidian import ObsidianDocument
from nexus.models.tool import Tool
from nexus.governance.audit_service import AuditPersistenceError
from nexus.models.governance import AuditLog
from nexus.obsidian import (
    ObsidianWriter,
    ObsidianWriteError,
    WriteConflictError,
    WriteContentError,
    WriteActor,
    VaultWriteAuthorizer,
)
from nexus.tools.registry import ToolRegistry

COMPANY = uuid.UUID("11111111-1111-1111-1111-111111111111")
AGENT = uuid.UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
TOOL = uuid.UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")


@pytest.fixture
def vault(tmp_path: Path):
    root = tmp_path / "vaults"
    (root / str(COMPANY)).mkdir(parents=True)
    with patch("nexus.obsidian.security.settings") as settings:
        settings.obsidian_vault_root = str(root)
        settings.obsidian_max_note_bytes = 1_048_576
        yield root


@pytest_asyncio.fixture
async def db_factory(tmp_path):
    import nexus.models  # noqa: F401

    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'writer.db'}")
    async with engine.begin() as connection:
        await connection.run_sync(SQLModel.metadata.create_all)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as db:
        db.add(Company(id=COMPANY, name="Test"))
        db.add(Agent(id=AGENT, company_id=COMPANY, name="agent", role="writer"))
        db.add(Tool(id=TOOL, company_id=COMPANY, name="obsidian.write", tool_type="function"))
        await db.commit()
    yield factory
    await engine.dispose()


async def writer_for(factory, *, registry=None):
    db = factory()
    return db, ObsidianWriter(
        db,
        authorizer=VaultWriteAuthorizer(registry or ToolRegistry(factory)),
    )


@pytest.mark.asyncio
async def test_replaces_existing_note_atomically(vault, db_factory):
    path = vault / str(COMPANY) / "Knowledge" / "A.md"
    path.parent.mkdir()
    path.write_text("# old\n", encoding="utf-8")
    async with db_factory() as db:
        db.add(ObsidianDocument(
            company_id=COMPANY,
            vault_path="Knowledge/A.md",
            content_hash="",
            mtime=datetime.now(timezone.utc).replace(tzinfo=None),
        ))
        await db.commit()
        from nexus.obsidian.provider import content_hash
        row = (await db.execute(
            select(ObsidianDocument).where(ObsidianDocument.company_id == COMPANY)
        )).scalar_one()
        row.content_hash = content_hash("# old\n")
        await db.commit()
        registry = ToolRegistry(db_factory)
        await registry.grant_access(COMPANY, AGENT, TOOL)
        authorizer = VaultWriteAuthorizer(registry, db_factory)
        await authorizer.grant_async(COMPANY, AGENT, TOOL, "Knowledge")
        result = await ObsidianWriter(db, authorizer=authorizer, approval_required=False).replace_note(
            COMPANY, "Knowledge/A.md", "# new\n", WriteActor.agent(AGENT), tool_id=TOOL
        )
        assert result.previous_hash != result.content_hash
        assert path.read_text(encoding="utf-8") == "# new\n"


@pytest.mark.asyncio
async def test_replacement_persists_audit_with_hashes(vault, db_factory):
    path = vault / str(COMPANY) / "Audit.md"
    path.write_text("old\n", encoding="utf-8")
    async with db_factory() as db:
        from nexus.obsidian.provider import content_hash
        db.add(ObsidianDocument(company_id=COMPANY, vault_path="Audit.md", content_hash=content_hash("old\n"), mtime=datetime.now(timezone.utc).replace(tzinfo=None)))
        await db.commit()
        registry = ToolRegistry(db_factory)
        await registry.grant_access(COMPANY, AGENT, TOOL)
        authorizer = VaultWriteAuthorizer(registry, db_factory)
        await authorizer.grant_async(COMPANY, AGENT, TOOL, "*")
        result = await ObsidianWriter(db, authorizer=authorizer, approval_required=False).replace_note(COMPANY, "Audit.md", "new\n", WriteActor.agent(AGENT), tool_id=TOOL)
        audit = (await db.execute(select(AuditLog))).scalars().one()
        assert audit.action == "obsidian.note_replaced"
        assert audit.company_id == COMPANY
        assert audit.details["previous_hash"] == result.previous_hash
        assert audit.details["content_hash"] == result.content_hash
        assert audit.details["tool_id"] == str(TOOL)


@pytest.mark.asyncio
async def test_audit_failure_is_distinguished_after_file_replacement(vault, db_factory):
    path = vault / str(COMPANY) / "AuditFailure.md"
    path.write_text("old\n", encoding="utf-8")
    async with db_factory() as db:
        from nexus.obsidian.provider import content_hash
        db.add(ObsidianDocument(company_id=COMPANY, vault_path="AuditFailure.md", content_hash=content_hash("old\n"), mtime=datetime.now(timezone.utc).replace(tzinfo=None)))
        await db.commit()
        registry = ToolRegistry(db_factory)
        await registry.grant_access(COMPANY, AGENT, TOOL)
        authorizer = VaultWriteAuthorizer(registry, db_factory)
        await authorizer.grant_async(COMPANY, AGENT, TOOL, "*")
        with patch("nexus.obsidian.writer.record_audit", side_effect=AuditPersistenceError("down")):
            with pytest.raises(ObsidianWriteError, match="audit persistence failed"):
                await ObsidianWriter(db, authorizer=authorizer, approval_required=False).replace_note(COMPANY, "AuditFailure.md", "new\n", WriteActor.agent(AGENT), tool_id=TOOL)
    assert path.read_text(encoding="utf-8") == "new\n"


@pytest.mark.asyncio
async def test_changed_note_is_refused(vault, db_factory):
    path = vault / str(COMPANY) / "A.md"
    path.write_text("human edit\n", encoding="utf-8")
    async with db_factory() as db:
        from nexus.obsidian.provider import content_hash
        db.add(ObsidianDocument(
            company_id=COMPANY,
            vault_path="A.md",
            content_hash=content_hash("old\n"),
            mtime=datetime.now(timezone.utc).replace(tzinfo=None),
        ))
        await db.commit()
        registry = ToolRegistry(db_factory)
        await registry.grant_access(COMPANY, AGENT, TOOL)
        authorizer = VaultWriteAuthorizer(registry, db_factory)
        await authorizer.grant_async(COMPANY, AGENT, TOOL, "*")
        with pytest.raises(WriteConflictError):
            await ObsidianWriter(
                db, authorizer=authorizer, approval_required=False
            ).replace_note(COMPANY, "A.md", "new\n", WriteActor.agent(AGENT), tool_id=TOOL)


@pytest.mark.asyncio
async def test_oversize_note_is_refused_before_filesystem_change(vault, db_factory):
    path = vault / str(COMPANY) / "A.md"
    path.write_text("old\n", encoding="utf-8")
    async with db_factory() as db:
        registry = ToolRegistry(db_factory)
        await registry.grant_access(COMPANY, AGENT, TOOL)
        authorizer = VaultWriteAuthorizer(registry, db_factory)
        await authorizer.grant_async(COMPANY, AGENT, TOOL, "*")
        with patch("nexus.obsidian.security.settings") as settings:
            settings.obsidian_max_note_bytes = 4
            with pytest.raises(WriteContentError):
                await ObsidianWriter(db, authorizer=authorizer, approval_required=False).replace_note(
                    COMPANY, "A.md", "12345", WriteActor.agent(AGENT), tool_id=TOOL
                )
    assert path.read_text(encoding="utf-8") == "old\n"


@pytest.mark.asyncio
async def test_secret_is_refused_before_filesystem_change(vault, db_factory):
    path = vault / str(COMPANY) / "A.md"
    path.write_text("old\n", encoding="utf-8")
    async with db_factory() as db:
        from nexus.obsidian.provider import content_hash
        db.add(ObsidianDocument(
            company_id=COMPANY,
            vault_path="A.md",
            content_hash=content_hash("old\n"),
            mtime=datetime.now(timezone.utc).replace(tzinfo=None),
        ))
        await db.commit()
        registry = ToolRegistry(db_factory)
        await registry.grant_access(COMPANY, AGENT, TOOL)
        authorizer = VaultWriteAuthorizer(registry, db_factory)
        await authorizer.grant_async(COMPANY, AGENT, TOOL, "*")
        with pytest.raises(WriteContentError):
            await ObsidianWriter(
                db, authorizer=authorizer, approval_required=False
            ).replace_note(COMPANY, "A.md", "password: hunter2!!\n", WriteActor.agent(AGENT), tool_id=TOOL)
    assert path.read_text(encoding="utf-8") == "old\n"
