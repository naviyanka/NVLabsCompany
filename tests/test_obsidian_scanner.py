"""Tests for the Obsidian vault scanner (ADR 0002 §17, Phase 1B-1).

These drive a real SQLite database and a real vault on disk, because the
guarantee under test is reconciliation between the two: a scan must classify
every note correctly and must never leave the registry describing a vault state
that does not exist.
"""

from __future__ import annotations

import uuid
from pathlib import Path
from unittest.mock import patch

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlmodel import SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession

from nexus.models.knowledge import (
    SOURCE_TYPE_KNOWLEDGE_PAGE,
    SOURCE_TYPE_OBSIDIAN_DOCUMENT,
    KnowledgeChunk,
)
from nexus.models.obsidian import INDEX_STATUS_INDEXED, INDEX_STATUS_STALE, ObsidianDocument
from nexus.obsidian import ObsidianReader, VaultScanner

COMPANY_A = uuid.UUID("11111111-1111-1111-1111-111111111111")
COMPANY_B = uuid.UUID("22222222-2222-2222-2222-222222222222")


@pytest.fixture
async def session_factory(tmp_path):
    """A SQLite database holding just the two tables the scanner touches."""
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'vault.db'}")
    async with engine.begin() as conn:
        await conn.run_sync(
            SQLModel.metadata.create_all,
            tables=[ObsidianDocument.__table__, KnowledgeChunk.__table__],
        )
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    yield factory
    await engine.dispose()


@pytest.fixture
def vault(tmp_path):
    """A configured vault root with company A's vault created."""
    root = tmp_path / "vaults"
    (root / str(COMPANY_A) / "Knowledge").mkdir(parents=True)
    with patch("nexus.obsidian.security.settings") as mock_settings:
        mock_settings.obsidian_vault_root = str(root)
        mock_settings.obsidian_max_note_bytes = 1_048_576
        yield root, mock_settings


def write_note(root: Path, company: uuid.UUID, rel: str, body: str) -> Path:
    """Write a note into a company's vault, creating parents as needed."""
    path = root / str(company) / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    return path


async def run_scan(factory, company: uuid.UUID = COMPANY_A):
    """Scan once in its own transaction and return the result."""
    async with factory() as db:
        result = await VaultScanner(db, company).scan()
        await db.commit()
    return result


async def rows_for(factory, company: uuid.UUID = COMPANY_A) -> list[ObsidianDocument]:
    """Load the registry rows for one company, ordered by path."""
    async with factory() as db:
        statement = (
            select(ObsidianDocument)
            .where(ObsidianDocument.company_id == company)
            .order_by(ObsidianDocument.vault_path)
        )
        return list((await db.execute(statement)).scalars().all())


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


async def test_new_notes_are_registered(vault, session_factory) -> None:
    """A first scan registers every note it can read."""
    root, _ = vault
    write_note(root, COMPANY_A, "Knowledge/A.md", "---\ntype: knowledge\n---\nbody a\n")
    write_note(root, COMPANY_A, "Knowledge/Nested/B.md", "plain body\n")

    result = await run_scan(session_factory)

    assert result.created == ["Knowledge/A.md", "Knowledge/Nested/B.md"]
    assert result.counts()["seen"] == 2
    rows = await rows_for(session_factory)
    assert [row.vault_path for row in rows] == [
        "Knowledge/A.md",
        "Knowledge/Nested/B.md",
    ]


async def test_registration_captures_frontmatter_and_hash(vault, session_factory) -> None:
    """Type, title, hash and mtime all land on the row."""
    root, _ = vault
    write_note(
        root,
        COMPANY_A,
        "Knowledge/SSRF.md",
        "---\ntype: knowledge\ntitle: SSRF Protection\n---\nGuard outbound requests.\n",
    )

    await run_scan(session_factory)

    (row,) = await rows_for(session_factory)
    note = ObsidianReader(COMPANY_A).read_note("Knowledge/SSRF.md")
    assert row.doc_type == "knowledge"
    assert row.title == "SSRF Protection"
    assert row.content_hash == note.content_hash
    assert row.mtime == note.mtime
    assert row.index_status == INDEX_STATUS_STALE


async def test_title_falls_back_to_filename(vault, session_factory) -> None:
    """Obsidian titles a note by its filename; match that when frontmatter is silent."""
    root, _ = vault
    write_note(root, COMPANY_A, "Knowledge/Runbook Deploy.md", "no frontmatter\n")

    await run_scan(session_factory)

    (row,) = await rows_for(session_factory)
    assert row.title == "Runbook Deploy"
    assert row.doc_type is None


async def test_overlong_frontmatter_values_are_clipped(vault, session_factory) -> None:
    """Human-authored metadata must not overflow the 500/50-char columns."""
    root, _ = vault
    write_note(
        root,
        COMPANY_A,
        "Knowledge/Long.md",
        f"---\ntitle: {'t' * 900}\ntype: {'k' * 90}\n---\nbody\n",
    )

    await run_scan(session_factory)

    (row,) = await rows_for(session_factory)
    assert len(row.title) == 500
    assert len(row.doc_type) == 50


# ---------------------------------------------------------------------------
# Change detection
# ---------------------------------------------------------------------------


async def test_unchanged_note_is_not_rewritten(vault, session_factory) -> None:
    """A second scan over an untouched vault reports unchanged and updates nothing."""
    root, _ = vault
    write_note(root, COMPANY_A, "Knowledge/A.md", "body\n")

    await run_scan(session_factory)
    (before,) = await rows_for(session_factory)

    result = await run_scan(session_factory)

    assert result.unchanged == ["Knowledge/A.md"]
    assert result.created == []
    (after,) = await rows_for(session_factory)
    assert after.nexus_id == before.nexus_id
    assert after.updated_at is None, "an unchanged note must not be written"


async def test_changed_note_is_updated_and_marked_stale(vault, session_factory) -> None:
    """A content change updates the hash and invalidates any derived index."""
    root, _ = vault
    write_note(root, COMPANY_A, "Knowledge/A.md", "first\n")
    await run_scan(session_factory)

    # Pretend the note had been indexed, so the stale transition is observable.
    async with session_factory() as db:
        row = (await db.execute(select(ObsidianDocument))).scalars().one()
        row.index_status = INDEX_STATUS_INDEXED
        db.add(row)
        await db.commit()
        original_id = row.nexus_id
        first_hash = row.content_hash

    write_note(root, COMPANY_A, "Knowledge/A.md", "second, quite different\n")
    result = await run_scan(session_factory)

    assert result.updated == ["Knowledge/A.md"]
    (row,) = await rows_for(session_factory)
    assert row.nexus_id == original_id, "identity must survive an edit"
    assert row.content_hash != first_hash
    assert row.index_status == INDEX_STATUS_STALE
    assert row.updated_at is not None


async def test_line_ending_change_alone_is_not_a_change(vault, session_factory) -> None:
    """Hashing normalized text means a CRLF rewrite is not a content change."""
    root, _ = vault
    path = root / str(COMPANY_A) / "Knowledge" / "A.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"line one\nline two\n")
    await run_scan(session_factory)

    path.write_bytes(b"line one\r\nline two\r\n")
    result = await run_scan(session_factory)

    assert result.unchanged == ["Knowledge/A.md"]
    assert result.updated == []


# ---------------------------------------------------------------------------
# Deletion
# ---------------------------------------------------------------------------


async def test_deleted_note_is_deregistered(vault, session_factory) -> None:
    """A note gone from the vault loses its registry row."""
    root, _ = vault
    write_note(root, COMPANY_A, "Knowledge/A.md", "body\n")
    write_note(root, COMPANY_A, "Knowledge/B.md", "body\n")
    await run_scan(session_factory)

    (root / str(COMPANY_A) / "Knowledge" / "A.md").unlink()
    result = await run_scan(session_factory)

    assert result.deleted == ["Knowledge/A.md"]
    assert [row.vault_path for row in await rows_for(session_factory)] == ["Knowledge/B.md"]


async def test_deregistration_drops_derived_chunks(vault, session_factory) -> None:
    """An orphaned chunk keeps deleted note content answerable through RAG search."""
    root, _ = vault
    write_note(root, COMPANY_A, "Knowledge/A.md", "secret body\n")
    await run_scan(session_factory)

    async with session_factory() as db:
        row = (await db.execute(select(ObsidianDocument))).scalars().one()
        db.add(
            KnowledgeChunk(
                company_id=COMPANY_A,
                source_type=SOURCE_TYPE_OBSIDIAN_DOCUMENT,
                source_id=row.nexus_id,
                content="secret body",
                chunk_index=0,
            )
        )
        # A page chunk that happens to share the document's UUID must survive:
        # the two id spaces are independent, so source_type is what disambiguates.
        db.add(
            KnowledgeChunk(
                company_id=COMPANY_A,
                source_type=SOURCE_TYPE_KNOWLEDGE_PAGE,
                source_id=row.nexus_id,
                content="unrelated page chunk",
                chunk_index=0,
            )
        )
        await db.commit()

    (root / str(COMPANY_A) / "Knowledge" / "A.md").unlink()
    await run_scan(session_factory)

    async with session_factory() as db:
        remaining = list((await db.execute(select(KnowledgeChunk))).scalars().all())
    assert [chunk.source_type for chunk in remaining] == [SOURCE_TYPE_KNOWLEDGE_PAGE]


# ---------------------------------------------------------------------------
# Move / rename via frontmatter nexus_id
# ---------------------------------------------------------------------------


async def test_move_is_tracked_when_the_note_declares_a_nexus_id(
    vault, session_factory
) -> None:
    """A tagged note keeps its identity, history and chunks across a move."""
    root, _ = vault
    declared = uuid.uuid4()
    body = f"---\nnexus_id: {declared}\ntype: knowledge\n---\nstable body\n"
    write_note(root, COMPANY_A, "Knowledge/Old.md", body)
    await run_scan(session_factory)

    (row,) = await rows_for(session_factory)
    assert row.nexus_id == declared, "a declared id becomes the row's identity"

    (root / str(COMPANY_A) / "Knowledge" / "Old.md").unlink()
    write_note(root, COMPANY_A, "Knowledge/New Name.md", body)
    result = await run_scan(session_factory)

    assert result.moved == ["Knowledge/New Name.md"]
    assert result.created == []
    assert result.deleted == []
    (row,) = await rows_for(session_factory)
    assert row.nexus_id == declared
    assert row.vault_path == "Knowledge/New Name.md"


async def test_move_leaves_a_valid_index_alone(vault, session_factory) -> None:
    """A pure move does not change the body, so its chunks stay current."""
    root, _ = vault
    declared = uuid.uuid4()
    body = f"---\nnexus_id: {declared}\n---\nbody\n"
    write_note(root, COMPANY_A, "Knowledge/Old.md", body)
    await run_scan(session_factory)

    async with session_factory() as db:
        row = (await db.execute(select(ObsidianDocument))).scalars().one()
        row.index_status = INDEX_STATUS_INDEXED
        db.add(row)
        await db.commit()

    (root / str(COMPANY_A) / "Knowledge" / "Old.md").unlink()
    write_note(root, COMPANY_A, "Knowledge/New.md", body)
    await run_scan(session_factory)

    (row,) = await rows_for(session_factory)
    assert row.index_status == INDEX_STATUS_INDEXED


async def test_untagged_move_is_delete_plus_create(vault, session_factory) -> None:
    """The documented Phase 1 limit: no id in frontmatter, no move detection.

    The registry stays correct — one row at the new path — but the document's
    continuous history is lost. Writing ids into notes is a later phase.
    """
    root, _ = vault
    write_note(root, COMPANY_A, "Knowledge/Old.md", "body\n")
    await run_scan(session_factory)
    (before,) = await rows_for(session_factory)

    (root / str(COMPANY_A) / "Knowledge" / "Old.md").unlink()
    write_note(root, COMPANY_A, "Knowledge/New.md", "body\n")
    result = await run_scan(session_factory)

    assert result.created == ["Knowledge/New.md"]
    assert result.deleted == ["Knowledge/Old.md"]
    assert result.moved == []
    (after,) = await rows_for(session_factory)
    assert after.vault_path == "Knowledge/New.md"
    assert after.nexus_id != before.nexus_id


async def test_unparseable_nexus_id_falls_back_to_path_identity(
    vault, session_factory
) -> None:
    """Hand-typed metadata must not stop a note from being indexed."""
    root, _ = vault
    write_note(root, COMPANY_A, "Knowledge/A.md", "---\nnexus_id: not-a-uuid\n---\nbody\n")

    result = await run_scan(session_factory)

    assert result.created == ["Knowledge/A.md"]
    (row,) = await rows_for(session_factory)
    assert row.vault_path == "Knowledge/A.md"


async def test_duplicate_nexus_id_does_not_hijack_the_first_row(
    vault, session_factory
) -> None:
    """A copy-pasted note must not steal the original's identity."""
    root, _ = vault
    declared = uuid.uuid4()
    body = f"---\nnexus_id: {declared}\n---\nbody\n"
    write_note(root, COMPANY_A, "Knowledge/A.md", body)
    write_note(root, COMPANY_A, "Knowledge/Copy.md", body)

    result = await run_scan(session_factory)

    assert result.created == ["Knowledge/A.md"]
    assert [path for path, _ in result.skipped] == ["Knowledge/Copy.md"]
    assert "duplicate nexus_id" in result.skipped[0][1]
    assert [row.vault_path for row in await rows_for(session_factory)] == ["Knowledge/A.md"]


# ---------------------------------------------------------------------------
# Resilience and isolation
# ---------------------------------------------------------------------------


async def test_unreadable_note_is_skipped_without_failing_the_scan(
    vault, session_factory
) -> None:
    """One bad note must not hide the rest of the vault."""
    root, mock_settings = vault
    write_note(root, COMPANY_A, "Knowledge/Small.md", "ok\n")
    write_note(root, COMPANY_A, "Knowledge/Big.md", "x" * 500)
    mock_settings.obsidian_max_note_bytes = 64

    result = await run_scan(session_factory)

    assert result.created == ["Knowledge/Small.md"]
    assert [path for path, _ in result.skipped] == ["Knowledge/Big.md"]
    assert "VaultFileTooLarge" in result.skipped[0][1]


async def test_skip_reason_does_not_leak_the_absolute_vault_path(
    vault, session_factory
) -> None:
    """Skip reasons reach API clients, so they must carry no host path.

    An OSError stringifies to the full path it tried — ``FileNotFoundError:
    [Errno 2] ... 'C:\\\\Users\\\\...'`` — which would disclose the server's
    filesystem layout through the scan response.
    """
    root, _ = vault
    note = write_note(root, COMPANY_A, "Knowledge/Vanishes.md", "body\n")

    real_read = ObsidianReader.read_note

    def read_then_vanish(self, vault_path):
        note.unlink(missing_ok=True)
        return real_read(self, vault_path)

    with patch.object(ObsidianReader, "read_note", read_then_vanish):
        result = await run_scan(session_factory)

    assert [path for path, _ in result.skipped] == ["Knowledge/Vanishes.md"]
    reason = result.skipped[0][1]
    assert str(root) not in reason
    assert "C:\\" not in reason and "/Users/" not in reason
    assert reason == "FileNotFoundError"


async def test_scan_of_an_absent_vault_is_empty_not_an_error(
    vault, session_factory
) -> None:
    """A company with no vault directory yet is a normal state."""
    result = await run_scan(session_factory, COMPANY_B)

    assert result.counts()["seen"] == 0
    assert result.deleted == []


async def test_scan_never_touches_another_companys_rows(vault, session_factory) -> None:
    """Company A's scan leaves company B's registry entirely alone."""
    root, _ = vault
    write_note(root, COMPANY_A, "Knowledge/A.md", "a\n")
    write_note(root, COMPANY_B, "Knowledge/B.md", "b\n")

    await run_scan(session_factory, COMPANY_B)
    assert [row.vault_path for row in await rows_for(session_factory, COMPANY_B)] == [
        "Knowledge/B.md"
    ]

    # A's scan must not deregister B's row just because A cannot see that note.
    await run_scan(session_factory, COMPANY_A)

    assert [row.vault_path for row in await rows_for(session_factory, COMPANY_B)] == [
        "Knowledge/B.md"
    ]
    assert [row.vault_path for row in await rows_for(session_factory, COMPANY_A)] == [
        "Knowledge/A.md"
    ]


async def test_scanner_writes_nothing_into_the_vault(vault, session_factory) -> None:
    """Phase 1 is read-only: a scan must not create, modify, or delete a file."""
    root, _ = vault
    note = write_note(root, COMPANY_A, "Knowledge/A.md", "---\ntype: knowledge\n---\nbody\n")
    before_bytes = note.read_bytes()
    before_mtime = note.stat().st_mtime
    before_tree = sorted(p.relative_to(root).as_posix() for p in root.rglob("*"))

    await run_scan(session_factory)

    assert note.read_bytes() == before_bytes, "note content was modified"
    assert note.stat().st_mtime == before_mtime, "note mtime changed"
    assert sorted(p.relative_to(root).as_posix() for p in root.rglob("*")) == before_tree


async def test_scanner_does_not_mint_ids_into_frontmatter(vault, session_factory) -> None:
    """The row gets an id; the file does not (ADR 0002 §17, read-only phase)."""
    root, _ = vault
    note = write_note(root, COMPANY_A, "Knowledge/A.md", "plain body\n")

    await run_scan(session_factory)

    (row,) = await rows_for(session_factory)
    assert row.nexus_id is not None
    assert "nexus_id" not in note.read_text(encoding="utf-8")


async def test_repeated_scans_are_idempotent(vault, session_factory) -> None:
    """Scanning three times over a static vault changes nothing after the first."""
    root, _ = vault
    write_note(root, COMPANY_A, "Knowledge/A.md", "a\n")
    write_note(root, COMPANY_A, "Knowledge/B.md", "b\n")

    first = await run_scan(session_factory)
    second = await run_scan(session_factory)
    third = await run_scan(session_factory)

    assert first.counts()["created"] == 2
    for result in (second, third):
        assert result.counts()["created"] == 0
        assert result.counts()["updated"] == 0
        assert result.counts()["deleted"] == 0
        assert result.counts()["unchanged"] == 2
    assert len(await rows_for(session_factory)) == 2
