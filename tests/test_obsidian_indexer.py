"""Tests for the Obsidian vault indexing engine (ADR 0002 §13, §21, Phase 1B-3A).

Drives a real SQLite database, a real vault on disk, and the real
``RAGPipeline``, because the guarantees under test are the ones that only exist
end to end: a note's body becomes searchable chunks under the right source type,
a wrong-width embedding provider surfaces as ``partial`` instead of degrading
silently, and a failure never leaves a document claiming to be indexed.
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

from nexus.knowledge.embeddings import LocalEmbeddingProvider, NullEmbeddingProvider
from nexus.knowledge.parsers import MarkdownParser
from nexus.knowledge.rag import RAGPipeline
from nexus.models.knowledge import (
    EMBEDDING_DIM,
    SOURCE_TYPE_KNOWLEDGE_PAGE,
    SOURCE_TYPE_OBSIDIAN_DOCUMENT,
    KnowledgeChunk,
)
from nexus.models.obsidian import (
    INDEX_STATUS_FAILED,
    INDEX_STATUS_INDEXED,
    INDEX_STATUS_PARTIAL,
    INDEX_STATUS_STALE,
    MAX_INDEX_ATTEMPTS,
    ObsidianDocument,
)
from nexus.obsidian import ObsidianReader, VaultIndexer, VaultScanner

COMPANY_A = uuid.UUID("11111111-1111-1111-1111-111111111111")
COMPANY_B = uuid.UUID("22222222-2222-2222-2222-222222222222")


@pytest.fixture
async def session_factory(tmp_path):
    """A SQLite database holding the two tables indexing touches."""
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'index.db'}")
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
    path = root / str(company) / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    return path


def make_pipeline(db, provider) -> RAGPipeline:
    """A pipeline wired the way the indexer wires its own, with a chosen provider."""
    return RAGPipeline(db=db, embedding_provider=provider, parser=MarkdownParser())


async def scan(factory, company: uuid.UUID = COMPANY_A) -> None:
    """Register the vault, so documents exist to index."""
    async with factory() as db:
        await VaultScanner(db, company).scan()
        await db.commit()


async def index(factory, company: uuid.UUID = COMPANY_A, provider=None, **kwargs):
    """Run one indexing pass in its own transaction."""
    async with factory() as db:
        pipeline = make_pipeline(db, provider) if provider is not None else None
        result = await VaultIndexer(db, company, pipeline=pipeline).index_stale(**kwargs)
        await db.commit()
    return result


async def chunks_for(factory, company: uuid.UUID = COMPANY_A) -> list[KnowledgeChunk]:
    """Every chunk for a company, in insertion order per document."""
    async with factory() as db:
        statement = (
            select(KnowledgeChunk)
            .where(KnowledgeChunk.company_id == company)
            .order_by(KnowledgeChunk.source_id, KnowledgeChunk.chunk_index)
        )
        return list((await db.execute(statement)).scalars().all())


async def docs_for(factory, company: uuid.UUID = COMPANY_A) -> list[ObsidianDocument]:
    """Registry rows for a company, ordered by path."""
    async with factory() as db:
        statement = (
            select(ObsidianDocument)
            .where(ObsidianDocument.company_id == company)
            .order_by(ObsidianDocument.vault_path)
        )
        return list((await db.execute(statement)).scalars().all())


# ---------------------------------------------------------------------------
# Chunking the right content, under the right parent
# ---------------------------------------------------------------------------


async def test_stale_document_is_chunked_and_marked_indexed(vault, session_factory) -> None:
    """The happy path: a registered note becomes chunks and flips to indexed."""
    root, _ = vault
    write_note(
        root,
        COMPANY_A,
        "Knowledge/SSRF.md",
        "---\ntype: knowledge\n---\n"
        "# SSRF Protection\n\nValidate outbound hosts.\n\n"
        "## Allowlist\n\nDeny link-local ranges.\n",
    )
    await scan(session_factory)

    result = await index(session_factory, provider=LocalEmbeddingProvider())

    assert result.indexed == ["Knowledge/SSRF.md"]
    assert result.failed == []
    assert result.chunks_written > 0
    (doc,) = await docs_for(session_factory)
    assert doc.index_status == INDEX_STATUS_INDEXED
    assert doc.indexed_at is not None


async def test_chunks_are_owned_by_the_obsidian_document(vault, session_factory) -> None:
    """Chunks hang off the document via the polymorphic source pair (ADR 0002 §12)."""
    root, _ = vault
    write_note(root, COMPANY_A, "Knowledge/A.md", "Body one.\n\nBody two.\n")
    await scan(session_factory)
    await index(session_factory, provider=LocalEmbeddingProvider())

    (doc,) = await docs_for(session_factory)
    stored = await chunks_for(session_factory)
    assert stored, "no chunks were written"
    for chunk in stored:
        assert chunk.source_type == SOURCE_TYPE_OBSIDIAN_DOCUMENT
        assert chunk.source_id == doc.nexus_id
        assert chunk.company_id == COMPANY_A


async def test_frontmatter_is_not_indexed(vault, session_factory) -> None:
    """Metadata must not become retrievable text, or a tag can outrank prose."""
    root, _ = vault
    write_note(
        root,
        COMPANY_A,
        "Knowledge/A.md",
        "---\nnexus_id: 3f2a\ntype: knowledge\ntags:\n  - zebrafish\n---\n"
        "The body mentions only rabbits.\n",
    )
    await scan(session_factory)
    await index(session_factory, provider=LocalEmbeddingProvider())

    text = "\n".join(chunk.content for chunk in await chunks_for(session_factory))
    assert "rabbits" in text
    assert "zebrafish" not in text
    assert "nexus_id" not in text


async def test_markdown_structure_is_preserved_in_chunks(vault, session_factory) -> None:
    """MarkdownParser is the parser, so a code block stays one chunk."""
    root, _ = vault
    write_note(
        root,
        COMPANY_A,
        "Knowledge/A.md",
        "# Title\n\nProse here.\n\n```python\nx = 1\ny = 2\n```\n",
    )
    await scan(session_factory)
    await index(session_factory, provider=LocalEmbeddingProvider())

    contents = [chunk.content for chunk in await chunks_for(session_factory)]
    assert any("x = 1" in c and "y = 2" in c for c in contents), (
        "the code block was split across chunks"
    )


async def test_empty_note_is_indexed_with_no_chunks(vault, session_factory) -> None:
    """A frontmatter-only note has nothing to index, and nothing is wrong."""
    root, _ = vault
    write_note(root, COMPANY_A, "Knowledge/Empty.md", "---\ntype: knowledge\n---\n")
    await scan(session_factory)

    result = await index(session_factory, provider=LocalEmbeddingProvider())

    assert result.skipped == ["Knowledge/Empty.md"]
    assert result.indexed == []
    assert await chunks_for(session_factory) == []
    (doc,) = await docs_for(session_factory)
    assert doc.index_status == INDEX_STATUS_INDEXED


# ---------------------------------------------------------------------------
# Embedding policy: partial vs indexed (ADR 0002 §21)
# ---------------------------------------------------------------------------


async def test_wrong_width_provider_yields_partial_not_silent_degradation(
    vault, session_factory
) -> None:
    """A dropped vector must surface as partial; that is the whole point of §21."""
    root, _ = vault
    write_note(root, COMPANY_A, "Knowledge/A.md", "Body text here.\n")
    await scan(session_factory)

    # 256-dim local provider against a 1536-dim column: index_chunks drops the
    # vectors and returns success, which is the silent degradation §21 forbids.
    narrow = LocalEmbeddingProvider(dimension=256)
    assert narrow.dimension != EMBEDDING_DIM

    with patch.object(RAGPipeline, "index_chunks", autospec=True) as mocked:
        async def drop_vectors(self, company_id, source_id, chunks, source_type=SOURCE_TYPE_KNOWLEDGE_PAGE):
            records = [
                KnowledgeChunk(
                    company_id=company_id,
                    source_type=source_type,
                    source_id=source_id,
                    content=text,
                    chunk_index=idx,
                    embedding_vector=None,  # what a width mismatch produces
                )
                for idx, text in enumerate(chunks)
            ]
            for record in records:
                self.db.add(record)
            await self.db.flush()
            return records

        mocked.side_effect = drop_vectors
        result = await index(session_factory, provider=narrow)

    assert result.partial == ["Knowledge/A.md"]
    assert result.indexed == []
    (doc,) = await docs_for(session_factory)
    assert doc.index_status == INDEX_STATUS_PARTIAL


async def test_no_provider_is_indexed_not_partial(vault, session_factory) -> None:
    """Keyword-only retrieval is a deliberate configuration, not degradation."""
    root, _ = vault
    write_note(root, COMPANY_A, "Knowledge/A.md", "Body text here.\n")
    await scan(session_factory)

    result = await index(session_factory, provider=NullEmbeddingProvider())

    assert result.indexed == ["Knowledge/A.md"]
    assert result.partial == []
    (doc,) = await docs_for(session_factory)
    assert doc.index_status == INDEX_STATUS_INDEXED
    assert await chunks_for(session_factory), "chunks must still be keyword-searchable"


async def test_embedding_model_and_dimension_are_recorded(vault, session_factory) -> None:
    """Recorded per document so a later provider change is detectable on read."""
    root, _ = vault
    write_note(root, COMPANY_A, "Knowledge/A.md", "Body.\n")
    await scan(session_factory)

    await index(session_factory, provider=LocalEmbeddingProvider(dimension=256))

    (doc,) = await docs_for(session_factory)
    assert doc.embedding_dimension == 256
    assert doc.embedding_model


# ---------------------------------------------------------------------------
# Reindex and idempotence
# ---------------------------------------------------------------------------


async def test_indexed_document_is_not_reindexed(vault, session_factory) -> None:
    """Only stale documents are picked up, so a second pass is a no-op."""
    root, _ = vault
    write_note(root, COMPANY_A, "Knowledge/A.md", "Body.\n")
    await scan(session_factory)
    first = await index(session_factory, provider=LocalEmbeddingProvider())

    second = await index(session_factory, provider=LocalEmbeddingProvider())

    assert first.counts()["indexed"] == 1
    assert second.counts() == {
        "indexed": 0,
        "partial": 0,
        "failed": 0,
        "skipped": 0,
        "chunks_written": 0,
    }


async def test_edited_note_replaces_its_chunks_without_duplicating(
    vault, session_factory
) -> None:
    """A reindex must not leave chunks from two versions answering one query."""
    root, _ = vault
    write_note(root, COMPANY_A, "Knowledge/A.md", "First version of the body.\n")
    await scan(session_factory)
    await index(session_factory, provider=LocalEmbeddingProvider())

    write_note(root, COMPANY_A, "Knowledge/A.md", "Second version, entirely new text.\n")
    await scan(session_factory)  # marks it stale again
    await index(session_factory, provider=LocalEmbeddingProvider())

    text = "\n".join(chunk.content for chunk in await chunks_for(session_factory))
    assert "Second version" in text
    assert "First version" not in text, "stale chunks survived the reindex"


async def test_note_emptied_by_an_edit_loses_its_chunks(vault, session_factory) -> None:
    """Deleting a note's body must stop it answering searches."""
    root, _ = vault
    write_note(root, COMPANY_A, "Knowledge/A.md", "Secret body text.\n")
    await scan(session_factory)
    await index(session_factory, provider=LocalEmbeddingProvider())
    assert await chunks_for(session_factory)

    write_note(root, COMPANY_A, "Knowledge/A.md", "---\ntype: knowledge\n---\n")
    await scan(session_factory)
    await index(session_factory, provider=LocalEmbeddingProvider())

    assert await chunks_for(session_factory) == []


async def test_index_document_forces_a_reindex_of_one_note(vault, session_factory) -> None:
    """Targeted reindex works regardless of current status."""
    root, _ = vault
    write_note(root, COMPANY_A, "Knowledge/A.md", "Body.\n")
    await scan(session_factory)
    await index(session_factory, provider=LocalEmbeddingProvider())
    (doc,) = await docs_for(session_factory)

    async with session_factory() as db:
        result = await VaultIndexer(
            db, COMPANY_A, pipeline=make_pipeline(db, LocalEmbeddingProvider())
        ).index_document(doc.nexus_id)
        await db.commit()

    assert result.indexed == ["Knowledge/A.md"]


async def test_index_document_ignores_another_companys_document(
    vault, session_factory
) -> None:
    """A document that is not this company's does not exist to this caller."""
    root, _ = vault
    write_note(root, COMPANY_A, "Knowledge/A.md", "Body.\n")
    await scan(session_factory)
    (doc,) = await docs_for(session_factory)

    async with session_factory() as db:
        result = await VaultIndexer(
            db, COMPANY_B, pipeline=make_pipeline(db, LocalEmbeddingProvider())
        ).index_document(doc.nexus_id)

    assert result.counts()["indexed"] == 0
    assert result.counts()["failed"] == 0


async def test_limit_batches_a_large_first_index(vault, session_factory) -> None:
    """A cap lets a big vault be indexed without one long transaction."""
    root, _ = vault
    for name in ("A", "B", "C"):
        write_note(root, COMPANY_A, f"Knowledge/{name}.md", f"Body {name}.\n")
    await scan(session_factory)

    first = await index(session_factory, provider=LocalEmbeddingProvider(), limit=2)
    second = await index(session_factory, provider=LocalEmbeddingProvider(), limit=2)

    assert len(first.indexed) == 2
    assert len(second.indexed) == 1
    assert all(doc.index_status == INDEX_STATUS_INDEXED for doc in await docs_for(session_factory))


# ---------------------------------------------------------------------------
# Failure handling
# ---------------------------------------------------------------------------


class _TransientProvider:
    """Fails the first N embed calls, then works. Models a provider outage."""

    dimension = 256

    def __init__(self, failures: int) -> None:
        self.remaining = failures
        self.calls = 0

    async def embed(self, text_or_texts):
        return await self.embed_batch(
            [text_or_texts] if isinstance(text_or_texts, str) else text_or_texts
        )

    async def embed_batch(self, texts):
        self.calls += 1
        if self.remaining > 0:
            self.remaining -= 1
            raise ConnectionError("embedding provider temporarily unreachable")
        return await LocalEmbeddingProvider(dimension=256).embed_batch(texts)


async def test_retryable_failure_is_retried_and_then_succeeds(
    vault, session_factory
) -> None:
    """transient failure -> failed -> retry -> success -> indexed."""
    root, _ = vault
    write_note(root, COMPANY_A, "Knowledge/A.md", "Body text.\n")
    await scan(session_factory)

    provider = _TransientProvider(failures=1)
    first = await index(session_factory, provider=provider)
    assert [path for path, _ in first.failed] == ["Knowledge/A.md"]
    (doc,) = await docs_for(session_factory)
    assert doc.index_status == INDEX_STATUS_FAILED
    assert doc.attempt_count == 1
    assert doc.last_error

    # The failed document is picked up again without any scan in between.
    second = await index(session_factory, provider=provider)

    assert second.indexed == ["Knowledge/A.md"]
    (doc,) = await docs_for(session_factory)
    assert doc.index_status == INDEX_STATUS_INDEXED
    assert doc.attempt_count == 0, "a success must clear the failure count"
    assert doc.last_error is None
    assert await chunks_for(session_factory)


async def test_retries_are_bounded(vault, session_factory) -> None:
    """A permanently failing document stops being retried; no infinite loop."""
    root, _ = vault
    write_note(root, COMPANY_A, "Knowledge/A.md", "Body text.\n")
    await scan(session_factory)

    provider = _TransientProvider(failures=99)  # never recovers
    attempts_seen = []
    for _ in range(MAX_INDEX_ATTEMPTS + 3):
        result = await index(session_factory, provider=provider)
        (doc,) = await docs_for(session_factory)
        attempts_seen.append((len(result.failed), doc.attempt_count))

    assert doc.attempt_count == MAX_INDEX_ATTEMPTS
    # Exactly MAX_INDEX_ATTEMPTS passes did work; the rest found nothing to do.
    working_passes = sum(1 for failed, _ in attempts_seen if failed)
    assert working_passes == MAX_INDEX_ATTEMPTS
    assert attempts_seen[-1][0] == 0, "an exhausted document was picked up again"


async def test_non_retryable_failure_is_not_retried(vault, session_factory) -> None:
    """A deterministic failure spends the whole budget on its first attempt."""
    root, _ = vault
    write_note(root, COMPANY_A, "Knowledge/A.md", "Body text.\n")
    await scan(session_factory)
    (root / str(COMPANY_A) / "Knowledge" / "A.md").unlink()  # unreadable, forever

    first = await index(session_factory, provider=LocalEmbeddingProvider())
    assert [path for path, _ in first.failed] == ["Knowledge/A.md"]
    (doc,) = await docs_for(session_factory)
    assert doc.attempt_count == MAX_INDEX_ATTEMPTS

    second = await index(session_factory, provider=LocalEmbeddingProvider())
    assert second.counts()["failed"] == 0, "a non-retryable failure was retried"


async def test_deterministic_pipeline_error_is_not_retried(
    vault, session_factory
) -> None:
    """A ValueError from the pipeline is the note's fault, not the network's."""
    root, _ = vault
    write_note(root, COMPANY_A, "Knowledge/A.md", "Body text.\n")
    await scan(session_factory)

    class BadInput:
        dimension = 256

        async def embed(self, text_or_texts):
            raise ValueError("unsupported content")

        async def embed_batch(self, texts):
            raise ValueError("unsupported content")

    await index(session_factory, provider=BadInput())

    (doc,) = await docs_for(session_factory)
    assert doc.attempt_count == MAX_INDEX_ATTEMPTS
    assert doc.index_status == INDEX_STATUS_FAILED


async def test_editing_a_note_restores_its_retry_budget(vault, session_factory) -> None:
    """A human fixing the note must get it indexed again."""
    root, _ = vault
    write_note(root, COMPANY_A, "Knowledge/A.md", "Original body.\n")
    await scan(session_factory)
    await index(session_factory, provider=_TransientProvider(failures=99))
    async with session_factory() as db:
        doc = (await db.execute(select(ObsidianDocument))).scalars().one()
        doc.attempt_count = MAX_INDEX_ATTEMPTS  # exhausted
        db.add(doc)
        await db.commit()

    write_note(root, COMPANY_A, "Knowledge/A.md", "Corrected body, quite different.\n")
    await scan(session_factory)

    (doc,) = await docs_for(session_factory)
    assert doc.attempt_count == 0
    assert doc.last_error is None
    result = await index(session_factory, provider=LocalEmbeddingProvider())
    assert result.indexed == ["Knowledge/A.md"]


async def test_retry_does_not_duplicate_chunks(vault, session_factory) -> None:
    """A retried document ends with exactly one set of chunks."""
    root, _ = vault
    write_note(root, COMPANY_A, "Knowledge/A.md", "Body one.\n\nBody two.\n")
    await scan(session_factory)

    provider = _TransientProvider(failures=1)
    await index(session_factory, provider=provider)
    await index(session_factory, provider=provider)

    chunks = await chunks_for(session_factory)
    contents = [chunk.content for chunk in chunks]
    assert len(contents) == len(set(contents)), f"duplicate chunks: {contents}"
    indices = [chunk.chunk_index for chunk in chunks]
    assert indices == sorted(set(indices)), "chunk_index sequence is not clean"


async def test_stale_documents_are_indexed_before_retries(vault, session_factory) -> None:
    """A fresh edit must not starve behind failures working through their budget."""
    root, _ = vault
    write_note(root, COMPANY_A, "Knowledge/Failing.md", "Doomed.\n")
    await scan(session_factory)
    await index(session_factory, provider=_TransientProvider(failures=99))

    write_note(root, COMPANY_A, "Knowledge/Fresh.md", "Newly written.\n")
    await scan(session_factory)

    # limit=1 forces the ordering question: which document does the pass pick?
    result = await index(session_factory, provider=LocalEmbeddingProvider(), limit=1)

    assert result.indexed == ["Knowledge/Fresh.md"]


async def test_partial_documents_are_not_retried(vault, session_factory) -> None:
    """Partial text is already searchable; re-running the same provider is pointless."""
    root, _ = vault
    write_note(root, COMPANY_A, "Knowledge/A.md", "Body.\n")
    await scan(session_factory)
    async with session_factory() as db:
        doc = (await db.execute(select(ObsidianDocument))).scalars().one()
        doc.index_status = INDEX_STATUS_PARTIAL
        db.add(doc)
        await db.commit()

    result = await index(session_factory, provider=LocalEmbeddingProvider())

    assert result.counts() == {
        "indexed": 0,
        "partial": 0,
        "failed": 0,
        "skipped": 0,
        "chunks_written": 0,
    }


async def test_last_error_carries_no_absolute_path(vault, session_factory) -> None:
    """The stored reason reaches operators and clients; it must stay path-free."""
    root, _ = vault
    write_note(root, COMPANY_A, "Knowledge/A.md", "Body.\n")
    await scan(session_factory)
    (root / str(COMPANY_A) / "Knowledge" / "A.md").unlink()

    await index(session_factory, provider=LocalEmbeddingProvider())

    (doc,) = await docs_for(session_factory)
    assert doc.last_error == "FileNotFoundError"
    assert str(root) not in doc.last_error


async def test_indexed_at_reflects_searchability_not_activity(
    vault, session_factory
) -> None:
    """A failed attempt updates last_attempt_at, not indexed_at."""
    root, _ = vault
    write_note(root, COMPANY_A, "Knowledge/A.md", "Body.\n")
    await scan(session_factory)
    await index(session_factory, provider=LocalEmbeddingProvider())
    (doc,) = await docs_for(session_factory)
    indexed_at = doc.indexed_at
    assert indexed_at is not None

    async with session_factory() as db:
        row = (await db.execute(select(ObsidianDocument))).scalars().one()
        row.index_status = INDEX_STATUS_STALE
        db.add(row)
        await db.commit()
    await index(session_factory, provider=_TransientProvider(failures=99))

    (doc,) = await docs_for(session_factory)
    assert doc.index_status == INDEX_STATUS_FAILED
    assert doc.indexed_at == indexed_at, "indexed_at moved on a failed attempt"
    assert doc.last_attempt_at is not None
    assert doc.last_attempt_at >= indexed_at


async def test_failure_reason_does_not_leak_the_absolute_vault_path(
    vault, session_factory
) -> None:
    """Index failure reasons reach API clients; they must carry no host path."""
    root, _ = vault
    write_note(root, COMPANY_A, "Knowledge/A.md", "Body.\n")
    await scan(session_factory)
    (root / str(COMPANY_A) / "Knowledge" / "A.md").unlink()

    result = await index(session_factory, provider=LocalEmbeddingProvider())

    reason = result.failed[0][1]
    assert str(root) not in reason
    assert "C:\\" not in reason and "/Users/" not in reason
    assert reason == "FileNotFoundError"


async def test_unreadable_note_is_marked_failed(vault, session_factory) -> None:
    """A note gone between scan and index fails visibly, not silently."""
    root, _ = vault
    write_note(root, COMPANY_A, "Knowledge/A.md", "Body.\n")
    await scan(session_factory)
    (root / str(COMPANY_A) / "Knowledge" / "A.md").unlink()

    result = await index(session_factory, provider=LocalEmbeddingProvider())

    assert [path for path, _ in result.failed] == ["Knowledge/A.md"]
    assert result.indexed == []
    (doc,) = await docs_for(session_factory)
    assert doc.index_status == INDEX_STATUS_FAILED


async def test_failure_keeps_existing_chunks(vault, session_factory) -> None:
    """A failed reindex must not leave a note with no chunks at all."""
    root, _ = vault
    write_note(root, COMPANY_A, "Knowledge/A.md", "Original body.\n")
    await scan(session_factory)
    await index(session_factory, provider=LocalEmbeddingProvider())
    before = len(await chunks_for(session_factory))
    assert before > 0

    # Force a stale re-pass, then make the note unreadable.
    async with session_factory() as db:
        doc = (await db.execute(select(ObsidianDocument))).scalars().one()
        doc.index_status = INDEX_STATUS_STALE
        db.add(doc)
        await db.commit()
    (root / str(COMPANY_A) / "Knowledge" / "A.md").unlink()

    await index(session_factory, provider=LocalEmbeddingProvider())

    assert len(await chunks_for(session_factory)) == before
    (doc,) = await docs_for(session_factory)
    assert doc.index_status == INDEX_STATUS_FAILED


async def test_pipeline_failure_after_delete_keeps_existing_chunks(
    vault, session_factory
) -> None:
    """The failure-preservation invariant, on the path that actually threatens it.

    ``reindex_page`` deletes the old chunks before inserting the new ones. A
    provider that raises during the insert leaves that DELETE pending in the
    session; without a savepoint the caller's commit destroys a working index
    while the row records ``failed``. ``test_failure_keeps_existing_chunks``
    below does NOT cover this: it fails in ``read_note``, before any delete.
    """
    root, _ = vault
    write_note(root, COMPANY_A, "Knowledge/A.md", "Original body.\n\nSecond paragraph.\n")
    await scan(session_factory)
    await index(session_factory, provider=LocalEmbeddingProvider())
    before = [chunk.content for chunk in await chunks_for(session_factory)]
    assert before, "nothing was indexed, so the test proves nothing"

    async with session_factory() as db:
        doc = (await db.execute(select(ObsidianDocument))).scalars().one()
        doc.index_status = INDEX_STATUS_STALE
        db.add(doc)
        await db.commit()

    class Exploding:
        dimension = EMBEDDING_DIM

        async def embed(self, text_or_texts):
            raise RuntimeError("embedding API unreachable")

        async def embed_batch(self, texts):
            raise RuntimeError("embedding API unreachable")

    result = await index(session_factory, provider=Exploding())

    assert [path for path, _ in result.failed] == ["Knowledge/A.md"]
    after = [chunk.content for chunk in await chunks_for(session_factory)]
    assert after == before, "a failed reindex destroyed the previous index"
    (doc,) = await docs_for(session_factory)
    assert doc.index_status == INDEX_STATUS_FAILED


async def test_failure_does_not_discard_an_earlier_documents_index(
    vault, session_factory
) -> None:
    """Rolling back one document's savepoint must not undo the whole pass."""
    root, _ = vault
    write_note(root, COMPANY_A, "Knowledge/Good.md", "Good body text.\n")
    write_note(root, COMPANY_A, "Knowledge/Bad.md", "Bad body text.\n")
    await scan(session_factory)

    calls = {"n": 0}
    real_embed = LocalEmbeddingProvider.embed_batch

    class FailsSecond:
        dimension = 256

        async def embed(self, text_or_texts):
            return await LocalEmbeddingProvider(dimension=256).embed(text_or_texts)

        async def embed_batch(self, texts):
            calls["n"] += 1
            if calls["n"] > 1:
                raise RuntimeError("provider died partway through the pass")
            return await real_embed(LocalEmbeddingProvider(dimension=256), texts)

    result = await index(session_factory, provider=FailsSecond())

    assert result.indexed == ["Knowledge/Bad.md"] or result.indexed == ["Knowledge/Good.md"]
    assert len(result.failed) == 1
    # The document that succeeded keeps its chunks despite the sibling failure.
    assert await chunks_for(session_factory)


async def test_one_failure_does_not_stop_the_pass(vault, session_factory) -> None:
    """A bad note must not hide the rest of the vault."""
    root, _ = vault
    write_note(root, COMPANY_A, "Knowledge/Good.md", "Good body.\n")
    write_note(root, COMPANY_A, "Knowledge/Gone.md", "Doomed body.\n")
    await scan(session_factory)
    (root / str(COMPANY_A) / "Knowledge" / "Gone.md").unlink()

    result = await index(session_factory, provider=LocalEmbeddingProvider())

    assert result.indexed == ["Knowledge/Good.md"]
    assert [path for path, _ in result.failed] == ["Knowledge/Gone.md"]


async def test_pipeline_failure_is_recorded_as_failed(vault, session_factory) -> None:
    """An embedding provider outage is a document-level failure, not a crash."""
    root, _ = vault
    write_note(root, COMPANY_A, "Knowledge/A.md", "Body.\n")
    await scan(session_factory)

    class BrokenProvider:
        dimension = EMBEDDING_DIM

        async def embed(self, text_or_texts):
            raise RuntimeError("embedding API unreachable")

        async def embed_batch(self, texts):
            raise RuntimeError("embedding API unreachable")

    result = await index(session_factory, provider=BrokenProvider())

    assert [path for path, _ in result.failed] == ["Knowledge/A.md"]
    (doc,) = await docs_for(session_factory)
    assert doc.index_status == INDEX_STATUS_FAILED


# ---------------------------------------------------------------------------
# Isolation and the read-only guarantee
# ---------------------------------------------------------------------------


async def test_indexing_is_scoped_to_one_company(vault, session_factory) -> None:
    """Company A's index pass leaves company B's documents stale and untouched."""
    root, _ = vault
    write_note(root, COMPANY_A, "Knowledge/A.md", "A body.\n")
    write_note(root, COMPANY_B, "Knowledge/B.md", "B body.\n")
    await scan(session_factory, COMPANY_A)
    await scan(session_factory, COMPANY_B)

    await index(session_factory, COMPANY_A, provider=LocalEmbeddingProvider())

    (a,) = await docs_for(session_factory, COMPANY_A)
    (b,) = await docs_for(session_factory, COMPANY_B)
    assert a.index_status == INDEX_STATUS_INDEXED
    assert b.index_status == INDEX_STATUS_STALE
    assert await chunks_for(session_factory, COMPANY_B) == []


async def test_page_chunks_sharing_a_uuid_are_untouched(vault, session_factory) -> None:
    """source_type disambiguates two independent UUID spaces."""
    root, _ = vault
    write_note(root, COMPANY_A, "Knowledge/A.md", "New body.\n")
    await scan(session_factory)
    (doc,) = await docs_for(session_factory)

    async with session_factory() as db:
        db.add(
            KnowledgeChunk(
                company_id=COMPANY_A,
                source_type=SOURCE_TYPE_KNOWLEDGE_PAGE,
                source_id=doc.nexus_id,  # same UUID, different parent table
                content="unrelated knowledge page chunk",
                chunk_index=0,
            )
        )
        await db.commit()

    await index(session_factory, provider=LocalEmbeddingProvider())

    page_chunks = [
        chunk
        for chunk in await chunks_for(session_factory)
        if chunk.source_type == SOURCE_TYPE_KNOWLEDGE_PAGE
    ]
    assert [chunk.content for chunk in page_chunks] == ["unrelated knowledge page chunk"]


async def test_indexing_writes_nothing_into_the_vault(vault, session_factory) -> None:
    """Phase 1 is read-only: indexing must not touch a file (ADR 0002 §23)."""
    root, _ = vault
    note = write_note(root, COMPANY_A, "Knowledge/A.md", "---\ntype: knowledge\n---\nBody.\n")
    await scan(session_factory)
    before_bytes = note.read_bytes()
    before_mtime = note.stat().st_mtime
    before_tree = sorted(p.relative_to(root).as_posix() for p in root.rglob("*"))

    await index(session_factory, provider=LocalEmbeddingProvider())

    assert note.read_bytes() == before_bytes
    assert note.stat().st_mtime == before_mtime
    assert sorted(p.relative_to(root).as_posix() for p in root.rglob("*")) == before_tree


async def test_indexer_exposes_no_vault_write_surface() -> None:
    """No create/update/append/move/delete of vault files anywhere on the class."""
    forbidden = {
        "write", "write_note", "create", "create_note", "append", "append_note",
        "move", "move_note", "delete_note", "save", "mint_id",
    }
    assert forbidden.isdisjoint(dir(VaultIndexer))


async def test_content_hash_matches_the_indexed_body(vault, session_factory) -> None:
    """A note edited between scan and index must not leave a lying hash."""
    root, _ = vault
    write_note(root, COMPANY_A, "Knowledge/A.md", "Version one.\n")
    await scan(session_factory)

    # Edit after registration but before indexing.
    write_note(root, COMPANY_A, "Knowledge/A.md", "Version two, edited late.\n")
    await index(session_factory, provider=LocalEmbeddingProvider())

    (doc,) = await docs_for(session_factory)
    note = ObsidianReader(COMPANY_A).read_note("Knowledge/A.md")
    assert doc.content_hash == note.content_hash
    text = "\n".join(chunk.content for chunk in await chunks_for(session_factory))
    assert "Version two" in text
