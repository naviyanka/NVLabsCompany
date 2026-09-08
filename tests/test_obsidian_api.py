"""Tests for the operator-facing Obsidian endpoints (ADR 0002, Phase 1B-2).

Two layers, deliberately:

- The service layer runs against a real SQLite database and a real vault, because
  what matters there is that a failed scan commits nothing and that two scans of
  one company cannot interleave.
- The route layer is called directly with a mocked session, pinning the status
  mapping and that the handler contains no scanning logic of its own.
"""

from __future__ import annotations

import asyncio
import uuid
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlmodel import SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession

from nexus.api.routes import obsidian as obsidian_routes
from nexus.models.knowledge import KnowledgeChunk
from nexus.models.obsidian import INDEX_STATUS_STALE, ObsidianDocument
from nexus.obsidian.security import VaultNotConfiguredError
from nexus.services import obsidian_service
from nexus.services.obsidian_service import (
    STATUS_AVAILABLE,
    STATUS_NOT_CONFIGURED,
    STATUS_UNAVAILABLE,
    ObsidianVaultService,
    ScanInProgressError,
    VaultUnavailableError,
)

COMPANY_A = uuid.UUID("11111111-1111-1111-1111-111111111111")
COMPANY_B = uuid.UUID("22222222-2222-2222-2222-222222222222")


@pytest.fixture(autouse=True)
def clear_scan_locks():
    """Keep per-company locks from leaking between tests."""
    obsidian_service._scan_locks.clear()
    yield
    obsidian_service._scan_locks.clear()


@pytest.fixture(autouse=True)
def synchronous_index_path():
    """Keep these tests on the synchronous index path, off any real Temporal.

    ``POST /index`` submits a durable workflow when Temporal is enabled and
    indexes inline otherwise. This file covers the inline behaviour, so the
    durable branch is switched off here — without this the tests reach whatever
    Temporal server the developer happens to be running and start real workflows
    against it, which is both a hidden dependency and a side effect on a live
    system. The durable branch has its own tests in
    ``tests/test_obsidian_temporal.py``.
    """
    with patch(
        "nexus.temporal.client.start_obsidian_index_workflow",
        AsyncMock(return_value=None),
    ):
        yield


@pytest.fixture
async def session_factory(tmp_path):
    """A SQLite database holding the two tables the scan touches."""
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'api.db'}")
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


@pytest.fixture
def no_vault():
    """The integration disabled, which is the default configuration."""
    with patch("nexus.obsidian.security.settings") as mock_settings:
        mock_settings.obsidian_vault_root = ""
        yield mock_settings


def write_note(root: Path, company: uuid.UUID, rel: str, body: str) -> Path:
    path = root / str(company) / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# Status
# ---------------------------------------------------------------------------


async def test_status_reports_not_configured(no_vault, session_factory) -> None:
    """An unset vault root is a state, not an error."""
    async with session_factory() as db:
        result = await ObsidianVaultService(db, COMPANY_A).status()

    assert result.state == STATUS_NOT_CONFIGURED
    assert result.configured is False
    assert result.vault_present is False


async def test_status_reports_configured_but_missing(vault, session_factory) -> None:
    """A company with no vault directory yet is unavailable, and says why."""
    async with session_factory() as db:
        result = await ObsidianVaultService(db, COMPANY_B).status()

    assert result.state == STATUS_UNAVAILABLE
    assert result.configured is True
    assert result.vault_present is False
    assert result.detail is not None


async def test_status_reports_available(vault, session_factory) -> None:
    """A real vault directory for this company is available."""
    async with session_factory() as db:
        result = await ObsidianVaultService(db, COMPANY_A).status()

    assert result.state == STATUS_AVAILABLE
    assert result.configured is True
    assert result.vault_present is True
    assert result.detail is None


async def test_status_counts_registered_documents(vault, session_factory) -> None:
    """The count comes from the registry, scoped to this company."""
    root, _ = vault
    write_note(root, COMPANY_A, "Knowledge/A.md", "a\n")
    write_note(root, COMPANY_A, "Knowledge/B.md", "b\n")
    async with session_factory() as db:
        await ObsidianVaultService(db, COMPANY_A).scan()
        await db.commit()

    async with session_factory() as db:
        mine = await ObsidianVaultService(db, COMPANY_A).status()
        theirs = await ObsidianVaultService(db, COMPANY_B).status()

    assert mine.indexed_documents == 2
    assert theirs.indexed_documents == 0


async def test_status_does_not_scan(vault, session_factory) -> None:
    """Status must stay cheap enough to poll: it registers nothing."""
    root, _ = vault
    write_note(root, COMPANY_A, "Knowledge/A.md", "a\n")

    async with session_factory() as db:
        result = await ObsidianVaultService(db, COMPANY_A).status()
        await db.commit()

    assert result.indexed_documents == 0
    async with session_factory() as db:
        rows = list((await db.execute(select(ObsidianDocument))).scalars().all())
    assert rows == []


# ---------------------------------------------------------------------------
# Scan
# ---------------------------------------------------------------------------


async def test_scan_delegates_to_the_scanner(vault, session_factory) -> None:
    """The service reuses VaultScanner rather than reimplementing it."""
    root, _ = vault
    write_note(root, COMPANY_A, "Knowledge/A.md", "---\ntype: knowledge\n---\nbody\n")

    async with session_factory() as db:
        result = await ObsidianVaultService(db, COMPANY_A).scan()
        await db.commit()

    assert result.created == ["Knowledge/A.md"]
    async with session_factory() as db:
        (row,) = list((await db.execute(select(ObsidianDocument))).scalars().all())
    assert row.vault_path == "Knowledge/A.md"
    assert row.doc_type == "knowledge"


async def test_scan_without_a_configured_vault_is_refused(no_vault, session_factory) -> None:
    """No configuration means no scan, with a distinguishable error."""
    async with session_factory() as db:
        with pytest.raises(VaultNotConfiguredError):
            await ObsidianVaultService(db, COMPANY_A).scan()


async def test_scan_is_scoped_to_the_authorized_company(vault, session_factory) -> None:
    """Company A's scan neither reads nor deregisters company B's notes."""
    root, _ = vault
    write_note(root, COMPANY_A, "Knowledge/A.md", "a\n")
    write_note(root, COMPANY_B, "Knowledge/B.md", "b\n")

    async with session_factory() as db:
        await ObsidianVaultService(db, COMPANY_B).scan()
        await db.commit()
    async with session_factory() as db:
        result = await ObsidianVaultService(db, COMPANY_A).scan()
        await db.commit()

    assert result.created == ["Knowledge/A.md"]
    assert result.deleted == []
    async with session_factory() as db:
        rows = list((await db.execute(select(ObsidianDocument))).scalars().all())
    assert {row.company_id for row in rows} == {COMPANY_A, COMPANY_B}


async def test_concurrent_same_company_scan_is_refused(vault, session_factory) -> None:
    """Two operators cannot interleave scans of one vault."""
    root, _ = vault
    write_note(root, COMPANY_A, "Knowledge/A.md", "a\n")

    started = asyncio.Event()
    release = asyncio.Event()

    async def slow_scan(self):  # noqa: ANN001 - patched bound method
        started.set()
        await release.wait()
        return obsidian_service.ScanResult()

    async with session_factory() as db_one, session_factory() as db_two:
        with patch(
            "nexus.obsidian.scanner.VaultScanner.scan", slow_scan, create=False
        ):
            first = asyncio.create_task(ObsidianVaultService(db_one, COMPANY_A).scan())
            await started.wait()

            with pytest.raises(ScanInProgressError):
                await ObsidianVaultService(db_two, COMPANY_A).scan()

            release.set()
            await first


async def test_different_companies_scan_concurrently(vault, session_factory) -> None:
    """The lock is per company, so one tenant cannot block another."""
    root, _ = vault
    write_note(root, COMPANY_A, "Knowledge/A.md", "a\n")
    write_note(root, COMPANY_B, "Knowledge/B.md", "b\n")

    started = asyncio.Event()
    release = asyncio.Event()

    async def slow_scan(self):  # noqa: ANN001 - patched bound method
        started.set()
        await release.wait()
        return obsidian_service.ScanResult()

    async with session_factory() as db_one, session_factory() as db_two:
        with patch("nexus.obsidian.scanner.VaultScanner.scan", slow_scan, create=False):
            first = asyncio.create_task(ObsidianVaultService(db_one, COMPANY_A).scan())
            await started.wait()
            release.set()
            # B is not blocked by A's in-flight scan.
            await ObsidianVaultService(db_two, COMPANY_B).scan()
            await first


async def test_lock_is_released_after_a_failed_scan(vault, session_factory) -> None:
    """A crashed scan must not wedge the company out of scanning forever."""
    root, _ = vault
    write_note(root, COMPANY_A, "Knowledge/A.md", "a\n")

    async def boom(self):  # noqa: ANN001 - patched bound method
        raise OSError("volume unmounted")

    async with session_factory() as db:
        with patch("nexus.obsidian.scanner.VaultScanner.scan", boom, create=False):
            with pytest.raises(VaultUnavailableError):
                await ObsidianVaultService(db, COMPANY_A).scan()

    async with session_factory() as db:
        result = await ObsidianVaultService(db, COMPANY_A).scan()
    assert result.created == ["Knowledge/A.md"]


async def test_filesystem_failure_becomes_vault_unavailable(vault, session_factory) -> None:
    """An OSError mid-scan is reported as unavailable, not as a bare crash."""
    async def boom(self):  # noqa: ANN001 - patched bound method
        raise OSError("permission denied on /srv/vaults")

    async with session_factory() as db:
        with patch("nexus.obsidian.scanner.VaultScanner.scan", boom, create=False):
            with pytest.raises(VaultUnavailableError) as excinfo:
                await ObsidianVaultService(db, COMPANY_A).scan()

    # The host path must not travel to the caller.
    assert "/srv/vaults" not in str(excinfo.value)


async def test_index_delegates_to_the_indexer(vault, session_factory) -> None:
    """The service reuses VaultIndexer rather than reimplementing it."""
    root, _ = vault
    write_note(root, COMPANY_A, "Knowledge/A.md", "Body text to index.\n")
    async with session_factory() as db:
        await ObsidianVaultService(db, COMPANY_A).scan()
        await db.commit()

    async with session_factory() as db:
        result = await ObsidianVaultService(db, COMPANY_A).index()
        await db.commit()

    assert result.indexed == ["Knowledge/A.md"]
    async with session_factory() as db:
        chunks = list((await db.execute(select(KnowledgeChunk))).scalars().all())
    assert chunks, "indexing produced no chunks"


async def test_index_without_a_prior_scan_finds_nothing(vault, session_factory) -> None:
    """No registered documents means nothing to index — not an error."""
    root, _ = vault
    write_note(root, COMPANY_A, "Knowledge/A.md", "Body.\n")

    async with session_factory() as db:
        result = await ObsidianVaultService(db, COMPANY_A).index()
        await db.commit()

    assert result.counts()["indexed"] == 0
    assert result.counts()["failed"] == 0


async def test_index_without_a_configured_vault_is_refused(
    no_vault, session_factory
) -> None:
    """No configuration means no index pass, with a distinguishable error."""
    async with session_factory() as db:
        with pytest.raises(VaultNotConfiguredError):
            await ObsidianVaultService(db, COMPANY_A).index()


async def test_index_honours_the_limit(vault, session_factory) -> None:
    """A cap lets a large first index run in batches."""
    root, _ = vault
    for name in ("A", "B", "C"):
        write_note(root, COMPANY_A, f"Knowledge/{name}.md", f"Body {name}.\n")
    async with session_factory() as db:
        await ObsidianVaultService(db, COMPANY_A).scan()
        await db.commit()

    async with session_factory() as db:
        first = await ObsidianVaultService(db, COMPANY_A).index(limit=2)
        await db.commit()
    async with session_factory() as db:
        second = await ObsidianVaultService(db, COMPANY_A).index(limit=2)
        await db.commit()

    assert len(first.indexed) == 2
    assert len(second.indexed) == 1


async def test_index_and_scan_share_one_lock(vault, session_factory) -> None:
    """A scan must not deregister documents while an index pass is mid-reindex."""
    root, _ = vault
    write_note(root, COMPANY_A, "Knowledge/A.md", "Body.\n")

    started = asyncio.Event()
    release = asyncio.Event()

    async def slow_index(self, limit=None):  # noqa: ANN001 - patched bound method
        started.set()
        await release.wait()
        return obsidian_service.IndexResult()

    async with session_factory() as db_one, session_factory() as db_two:
        with patch("nexus.obsidian.indexer.VaultIndexer.index_stale", slow_index):
            running = asyncio.create_task(
                ObsidianVaultService(db_one, COMPANY_A).index()
            )
            await started.wait()

            # The sibling operation is refused while the index holds the lock.
            with pytest.raises(ScanInProgressError):
                await ObsidianVaultService(db_two, COMPANY_A).scan()

            release.set()
            await running


async def test_index_is_scoped_to_the_authorized_company(vault, session_factory) -> None:
    """Company A's index pass leaves company B's documents untouched."""
    root, _ = vault
    write_note(root, COMPANY_A, "Knowledge/A.md", "A body.\n")
    write_note(root, COMPANY_B, "Knowledge/B.md", "B body.\n")
    for company in (COMPANY_A, COMPANY_B):
        async with session_factory() as db:
            await ObsidianVaultService(db, company).scan()
            await db.commit()

    async with session_factory() as db:
        await ObsidianVaultService(db, COMPANY_A).index()
        await db.commit()

    async with session_factory() as db:
        chunks = list((await db.execute(select(KnowledgeChunk))).scalars().all())
    assert chunks
    assert {chunk.company_id for chunk in chunks} == {COMPANY_A}


async def test_index_writes_nothing_into_the_vault(vault, session_factory) -> None:
    """Indexing through the HTTP path is read-only (ADR 0002 §23)."""
    root, _ = vault
    note = write_note(root, COMPANY_A, "Knowledge/A.md", "---\ntype: knowledge\n---\nBody.\n")
    async with session_factory() as db:
        await ObsidianVaultService(db, COMPANY_A).scan()
        await db.commit()
    before_bytes = note.read_bytes()
    before_mtime = note.stat().st_mtime
    before_tree = sorted(p.relative_to(root).as_posix() for p in root.rglob("*"))

    async with session_factory() as db:
        await ObsidianVaultService(db, COMPANY_A).index()
        await db.commit()

    assert note.read_bytes() == before_bytes
    assert note.stat().st_mtime == before_mtime
    assert sorted(p.relative_to(root).as_posix() for p in root.rglob("*")) == before_tree


async def test_scan_writes_nothing_into_the_vault(vault, session_factory) -> None:
    """The HTTP path is read-only with respect to the vault (ADR 0002 §23)."""
    root, _ = vault
    note = write_note(root, COMPANY_A, "Knowledge/A.md", "---\ntype: knowledge\n---\nbody\n")
    before_bytes = note.read_bytes()
    before_mtime = note.stat().st_mtime
    before_tree = sorted(p.relative_to(root).as_posix() for p in root.rglob("*"))

    async with session_factory() as db:
        await ObsidianVaultService(db, COMPANY_A).scan()
        await db.commit()

    assert note.read_bytes() == before_bytes
    assert note.stat().st_mtime == before_mtime
    assert sorted(p.relative_to(root).as_posix() for p in root.rglob("*")) == before_tree


# ---------------------------------------------------------------------------
# Route adapter
# ---------------------------------------------------------------------------


async def test_status_route_shapes_the_service_result(vault, session_factory) -> None:
    """The handler maps the service's status onto the response model."""
    async with session_factory() as db:
        response = await obsidian_routes.get_obsidian_status(db, COMPANY_A)

    assert response.state == STATUS_AVAILABLE
    assert response.configured is True
    assert response.indexed_documents == 0
    # The absolute vault root is never disclosed.
    assert "vault_root" not in response.model_dump()


async def test_scan_route_returns_counts_and_paths(vault, session_factory) -> None:
    """A successful scan answers with per-classification counts and relative paths."""
    root, _ = vault
    write_note(root, COMPANY_A, "Knowledge/A.md", "a\n")
    write_note(root, COMPANY_A, "Knowledge/B.md", "b\n")

    async with session_factory() as db:
        response = await obsidian_routes.scan_obsidian_vault(db, COMPANY_A)

    assert response.counts.created == 2
    assert response.counts.seen == 2
    assert response.created == ["Knowledge/A.md", "Knowledge/B.md"]
    assert response.skipped == []
    for path in response.created:
        assert not Path(path).is_absolute()


async def test_scan_route_commits_on_success(vault, session_factory) -> None:
    """The registry survives the request that wrote it."""
    root, _ = vault
    write_note(root, COMPANY_A, "Knowledge/A.md", "a\n")

    async with session_factory() as db:
        await obsidian_routes.scan_obsidian_vault(db, COMPANY_A)

    async with session_factory() as db:
        rows = list((await db.execute(select(ObsidianDocument))).scalars().all())
    assert [row.vault_path for row in rows] == ["Knowledge/A.md"]


async def test_scan_route_rolls_back_on_failure(vault, session_factory) -> None:
    """A failed scan must not leave registry rows committed."""
    root, _ = vault
    write_note(root, COMPANY_A, "Knowledge/A.md", "a\n")

    real_scan = obsidian_service.VaultScanner.scan

    async def register_then_fail(self):  # noqa: ANN001 - patched bound method
        await real_scan(self)
        raise OSError("vault vanished mid-scan")

    async with session_factory() as db:
        with patch(
            "nexus.obsidian.scanner.VaultScanner.scan", register_then_fail, create=False
        ):
            with pytest.raises(HTTPException) as excinfo:
                await obsidian_routes.scan_obsidian_vault(db, COMPANY_A)

    assert excinfo.value.status_code == 503
    async with session_factory() as db:
        rows = list((await db.execute(select(ObsidianDocument))).scalars().all())
    assert rows == [], "a failed scan committed registry rows"


async def test_scan_route_returns_409_when_not_configured(no_vault) -> None:
    """An unconfigured integration is a conflict, not a 500."""
    db = AsyncMock()
    with pytest.raises(HTTPException) as excinfo:
        await obsidian_routes.scan_obsidian_vault(db, COMPANY_A)

    assert excinfo.value.status_code == 409
    assert "not configured" in excinfo.value.detail
    db.rollback.assert_awaited()


async def test_scan_route_returns_409_when_already_running(vault) -> None:
    """A concurrent scan is reported as a conflict."""
    db = AsyncMock()

    async def already_running(self):  # noqa: ANN001 - patched bound method
        raise ScanInProgressError("busy")

    with patch.object(ObsidianVaultService, "scan", already_running):
        with pytest.raises(HTTPException) as excinfo:
            await obsidian_routes.scan_obsidian_vault(db, COMPANY_A)

    assert excinfo.value.status_code == 409
    assert "already running" in excinfo.value.detail


async def test_scan_route_returns_503_when_vault_unavailable(vault) -> None:
    """A vault that cannot be read is a service-availability problem."""
    db = AsyncMock()

    async def unavailable(self):  # noqa: ANN001 - patched bound method
        raise VaultUnavailableError("The vault could not be read.")

    with patch.object(ObsidianVaultService, "scan", unavailable):
        with pytest.raises(HTTPException) as excinfo:
            await obsidian_routes.scan_obsidian_vault(db, COMPANY_A)

    assert excinfo.value.status_code == 503


async def test_scan_route_hides_internal_detail_on_unexpected_failure(vault) -> None:
    """An unexpected error yields a 500 with no stack trace or host path."""
    db = AsyncMock()

    async def kaboom(self):  # noqa: ANN001 - patched bound method
        raise RuntimeError("psycopg: connection refused at /var/run/postgres")

    with patch.object(ObsidianVaultService, "scan", kaboom):
        with pytest.raises(HTTPException) as excinfo:
            await obsidian_routes.scan_obsidian_vault(db, COMPANY_A)

    assert excinfo.value.status_code == 500
    assert "psycopg" not in excinfo.value.detail
    assert "/var/run" not in excinfo.value.detail
    db.rollback.assert_awaited()


async def test_index_route_returns_counts_and_paths(vault, session_factory) -> None:
    """A successful pass answers with per-outcome counts and relative paths."""
    root, _ = vault
    write_note(root, COMPANY_A, "Knowledge/A.md", "Body one.\n")
    write_note(root, COMPANY_A, "Knowledge/B.md", "Body two.\n")
    async with session_factory() as db:
        await obsidian_routes.scan_obsidian_vault(db, COMPANY_A)

    async with session_factory() as db:
        response = await obsidian_routes.index_obsidian_vault(db, COMPANY_A)

    assert response.counts.indexed == 2
    assert response.counts.chunks_written > 0
    assert response.indexed == ["Knowledge/A.md", "Knowledge/B.md"]
    assert response.failed == []
    for path in response.indexed:
        assert not Path(path).is_absolute()


async def test_index_route_commits_on_success(vault, session_factory) -> None:
    """The chunks survive the request that wrote them."""
    root, _ = vault
    write_note(root, COMPANY_A, "Knowledge/A.md", "Body.\n")
    async with session_factory() as db:
        await obsidian_routes.scan_obsidian_vault(db, COMPANY_A)

    async with session_factory() as db:
        await obsidian_routes.index_obsidian_vault(db, COMPANY_A)

    async with session_factory() as db:
        chunks = list((await db.execute(select(KnowledgeChunk))).scalars().all())
    assert chunks


async def test_index_route_rolls_back_on_failure(vault, session_factory) -> None:
    """A failed pass reports 503 and does not advance the document's status.

    Scope note on what this can assert. The indexer wraps each document's
    reindex in ``begin_nested()`` (the 1B-3A failure-preservation fix). Under
    aiosqlite/pysqlite the DBAPI does not emit ``BEGIN``, so ``RELEASE
    SAVEPOINT`` effectively commits that savepoint's work and a later outer
    ``rollback()`` cannot undo it — verified directly, and fixed by SQLAlchemy's
    documented explicit-BEGIN recipe, which this project does not install.

    Production runs PostgreSQL/asyncpg, where a released savepoint stays inside
    the enclosing transaction and the rollback is complete. So the chunk-level
    rollback is a real production guarantee that SQLite cannot demonstrate; what
    is portable, and what this test pins, is that the failure surfaces as 503 and
    that ``index_status`` is not advanced to ``indexed`` on a failed pass.
    """
    root, _ = vault
    write_note(root, COMPANY_A, "Knowledge/A.md", "Body.\n")
    async with session_factory() as db:
        await obsidian_routes.scan_obsidian_vault(db, COMPANY_A)

    real_index = obsidian_service.VaultIndexer.index_stale

    async def index_then_fail(self, limit=None):  # noqa: ANN001 - patched bound method
        await real_index(self, limit=limit)
        raise OSError("vault vanished mid-pass")

    async with session_factory() as db:
        with patch("nexus.obsidian.indexer.VaultIndexer.index_stale", index_then_fail):
            with pytest.raises(HTTPException) as excinfo:
                await obsidian_routes.index_obsidian_vault(db, COMPANY_A)

    assert excinfo.value.status_code == 503
    async with session_factory() as db:
        row = (await db.execute(select(ObsidianDocument))).scalars().one()
    assert row.index_status == INDEX_STATUS_STALE, "status advanced despite failure"


async def test_released_savepoint_escapes_rollback_on_sqlite_only(
    session_factory,
) -> None:
    """Pins the driver divergence the test above works around.

    If this ever starts returning 0 rows, aiosqlite has gained real transactional
    savepoints (or someone installed the explicit-BEGIN recipe) and the scope note
    on ``test_index_route_rolls_back_on_failure`` can be dropped along with this
    test. Production PostgreSQL already behaves as the 0-row case.
    """
    async with session_factory() as db:
        async with db.begin_nested():
            db.add(
                KnowledgeChunk(
                    company_id=COMPANY_A,
                    source_type="obsidian_document",
                    source_id=uuid.uuid4(),
                    content="written inside a savepoint",
                    chunk_index=0,
                )
            )
            await db.flush()
        await db.rollback()

    async with session_factory() as db:
        rows = list((await db.execute(select(KnowledgeChunk))).scalars().all())
    assert len(rows) == 1, (
        "aiosqlite now honours released savepoints under rollback — simplify "
        "test_index_route_rolls_back_on_failure and delete this test"
    )


async def test_index_route_returns_409_when_not_configured(no_vault) -> None:
    """An unconfigured integration is a conflict, not a 500."""
    db = AsyncMock()
    with pytest.raises(HTTPException) as excinfo:
        await obsidian_routes.index_obsidian_vault(db, COMPANY_A)

    assert excinfo.value.status_code == 409
    assert "not configured" in excinfo.value.detail
    db.rollback.assert_awaited()


async def test_index_route_returns_409_when_a_sibling_operation_runs(vault) -> None:
    """Scan and index share a lock, so the second caller gets a conflict."""
    db = AsyncMock()

    async def busy(self, limit=None):  # noqa: ANN001 - patched bound method
        raise ScanInProgressError("busy")

    with patch.object(ObsidianVaultService, "index", busy):
        with pytest.raises(HTTPException) as excinfo:
            await obsidian_routes.index_obsidian_vault(db, COMPANY_A)

    assert excinfo.value.status_code == 409
    assert "already running" in excinfo.value.detail


async def test_index_route_hides_internal_detail_on_unexpected_failure(vault) -> None:
    """An unexpected error yields a 500 with no stack trace or host path."""
    db = AsyncMock()

    async def kaboom(self, limit=None):  # noqa: ANN001 - patched bound method
        raise RuntimeError("psycopg: connection refused at /var/run/postgres")

    with patch.object(ObsidianVaultService, "index", kaboom):
        with pytest.raises(HTTPException) as excinfo:
            await obsidian_routes.index_obsidian_vault(db, COMPANY_A)

    assert excinfo.value.status_code == 500
    assert "psycopg" not in excinfo.value.detail
    assert "/var/run" not in excinfo.value.detail
    db.rollback.assert_awaited()


async def test_index_route_reports_failures_without_leaking_paths(
    vault, session_factory
) -> None:
    """A per-note failure is reported with a reason carrying no host path."""
    root, _ = vault
    write_note(root, COMPANY_A, "Knowledge/A.md", "Body.\n")
    async with session_factory() as db:
        await obsidian_routes.scan_obsidian_vault(db, COMPANY_A)
    (root / str(COMPANY_A) / "Knowledge" / "A.md").unlink()

    async with session_factory() as db:
        response = await obsidian_routes.index_obsidian_vault(db, COMPANY_A)

    assert response.counts.failed == 1
    reason = response.failed[0].reason
    assert str(root) not in reason
    assert "C:\\" not in reason and "/Users/" not in reason


async def test_index_route_takes_only_an_optional_limit() -> None:
    """The company and vault root are not client-selectable; limit is the only knob."""
    import inspect

    params = inspect.signature(obsidian_routes.index_obsidian_vault).parameters
    assert set(params) == {"db", "company_id", "limit"}
    for forbidden in ("body", "vault_path", "vault_root", "source_type", "request"):
        assert forbidden not in params


async def test_scan_route_takes_no_request_body() -> None:
    """The company and the vault root are not client-selectable."""
    import inspect

    params = inspect.signature(obsidian_routes.scan_obsidian_vault).parameters
    assert set(params) == {"db", "company_id"}
    for forbidden in ("body", "vault_path", "vault_root", "request"):
        assert forbidden not in params


async def test_routes_use_the_authenticated_company_dependency() -> None:
    """Tenant scope comes from CurrentCompanyId, never from the path or body."""
    import inspect

    from nexus.api.deps import CurrentCompanyId

    for handler in (
        obsidian_routes.get_obsidian_status,
        obsidian_routes.scan_obsidian_vault,
        obsidian_routes.index_obsidian_vault,
        obsidian_routes.get_obsidian_index_progress,
    ):
        annotation = inspect.signature(handler).parameters["company_id"].annotation
        assert annotation is CurrentCompanyId


async def test_no_write_operations_are_exposed() -> None:
    """The vault surface is status, scan and index only (ADR 0002 §23-§24)."""
    paths = {route.path for route in obsidian_routes.router.routes}
    assert paths == {
        "/api/v1/integrations/obsidian/status",
        "/api/v1/integrations/obsidian/scan",
        "/api/v1/integrations/obsidian/index",
        # Reads the progress of a run already submitted; writes nothing.
        "/api/v1/integrations/obsidian/index/{workflow_id}",
    }

    methods: set[str] = set()
    for route in obsidian_routes.router.routes:
        methods |= route.methods
    assert methods == {"GET", "POST"}

    forbidden = {"sync", "reindex", "write", "register", "create", "update", "delete"}
    for path in paths:
        assert not (forbidden & set(path.rsplit("/", 1)[-1].split("_")))
