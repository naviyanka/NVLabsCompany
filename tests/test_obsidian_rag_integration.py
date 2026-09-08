"""End-to-end proof that an Obsidian note is retrievable through existing RAG.

Every other Obsidian test checks one stage. This one checks that the stages
compose, driving the whole path with no hand-inserted rows:

    .md file -> VaultScanner -> obsidian_documents -> VaultIndexer
             -> MarkdownParser -> RAGPipeline chunking -> embedding provider
             -> KnowledgeChunk -> RAGPipeline.search()

Nothing here constructs a KnowledgeChunk or an embedding vector directly: if the
integration is broken, these tests fail rather than passing against fixtures that
paper over the gap.

Retrieval runs on SQLite with ``LocalEmbeddingProvider``, so the suite needs no
network and no API key. That does mean the pgvector ``<=>`` candidate path is not
exercised — ``RAGPipeline._vector_candidates`` returns None unless the bind is
PostgreSQL and the query width equals ``EMBEDDING_DIM`` — so what runs here is the
Python cosine fallback. See the module note at ``test_vector_hybrid_retrieval``.
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

from nexus.api.routes import knowledge as knowledge_routes
from nexus.knowledge.embeddings import LocalEmbeddingProvider, NullEmbeddingProvider
from nexus.knowledge.parsers import MarkdownParser
from nexus.knowledge.rag import RAGPipeline
from nexus.models.knowledge import (
    EMBEDDING_DIM,
    SOURCE_TYPE_KNOWLEDGE_PAGE,
    SOURCE_TYPE_OBSIDIAN_DOCUMENT,
    KnowledgeChunk,
    KnowledgePage,
)
from nexus.models.obsidian import (
    INDEX_STATUS_FAILED,
    INDEX_STATUS_INDEXED,
    INDEX_STATUS_STALE,
    ObsidianDocument,
)
from nexus.obsidian import VaultIndexer, VaultScanner

COMPANY_A = uuid.UUID("11111111-1111-1111-1111-111111111111")
COMPANY_B = uuid.UUID("22222222-2222-2222-2222-222222222222")

# Distinctive enough that a hit cannot come from anywhere else in the corpus.
SENTINEL = "NEXUS_OBSIDIAN_RAG_SENTINEL_7F42"
SENTINEL_B = "NEXUS_OBSIDIAN_RAG_SENTINEL_B913"
FRONTMATTER_SENTINEL = "FRONTMATTER_SHOULD_NOT_BE_SEARCHABLE"

NOTE_BODY = (
    f"---\ntitle: {FRONTMATTER_SENTINEL}\ntype: knowledge\ntags:\n  - sentinel\n---\n"
    f"# Retrieval Sentinel\n\n"
    f"This document contains {SENTINEL}, a unique phrase that should only be\n"
    f"retrievable from this Obsidian note.\n\n"
    f"## Context\n\nSecond section, ordinary prose about deployment runbooks.\n"
)


@pytest.fixture
async def session_factory(tmp_path):
    """A SQLite database with the tables the whole path touches."""
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'rag.db'}")
    async with engine.begin() as conn:
        await conn.run_sync(
            SQLModel.metadata.create_all,
            tables=[
                ObsidianDocument.__table__,
                KnowledgeChunk.__table__,
                KnowledgePage.__table__,
            ],
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


def pipeline_for(db, provider) -> RAGPipeline:
    """A pipeline wired the way VaultIndexer wires its own."""
    return RAGPipeline(db=db, embedding_provider=provider, parser=MarkdownParser())


async def ingest(factory, company: uuid.UUID = COMPANY_A, provider=None) -> None:
    """Run the real scan-then-index path. No rows are hand-inserted."""
    provider = provider if provider is not None else LocalEmbeddingProvider()
    async with factory() as db:
        await VaultScanner(db, company).scan()
        await db.commit()
    async with factory() as db:
        indexer = VaultIndexer(db, company, pipeline=pipeline_for(db, provider))
        await indexer.index_stale()
        await db.commit()


async def search(factory, query: str, company: uuid.UUID = COMPANY_A, provider=None):
    """Search through the existing RAGPipeline, returning its result dicts."""
    provider = provider if provider is not None else LocalEmbeddingProvider()
    async with factory() as db:
        return await pipeline_for(db, provider).search(
            company_id=company, query=query, top_k=5
        )


def hits_containing(results, needle: str) -> list:
    """Result entries whose chunk text contains ``needle``."""
    return [r for r in results if needle in r["chunk"].content]


# ---------------------------------------------------------------------------
# The end-to-end path
# ---------------------------------------------------------------------------


async def test_obsidian_note_is_retrievable_through_existing_rag(
    vault, session_factory
) -> None:
    """The headline assertion: a .md file becomes a RAG search hit."""
    root, _ = vault
    write_note(root, COMPANY_A, "Knowledge/Sentinel.md", NOTE_BODY)

    await ingest(session_factory)
    results = await search(session_factory, SENTINEL)

    assert results, "RAGPipeline.search returned nothing for the sentinel"
    matches = hits_containing(results, SENTINEL)
    assert matches, (
        f"the sentinel was not retrievable; got "
        f"{[r['chunk'].content[:60] for r in results]}"
    )


async def test_scanner_hands_the_indexer_a_registered_document(
    vault, session_factory
) -> None:
    """Stage boundary: scan registers, index consumes what scan registered."""
    root, _ = vault
    write_note(root, COMPANY_A, "Knowledge/Sentinel.md", NOTE_BODY)

    async with session_factory() as db:
        scan_result = await VaultScanner(db, COMPANY_A).scan()
        await db.commit()
    assert scan_result.created == ["Knowledge/Sentinel.md"]

    async with session_factory() as db:
        row = (await db.execute(select(ObsidianDocument))).scalars().one()
        assert row.index_status == INDEX_STATUS_STALE

    async with session_factory() as db:
        index_result = await VaultIndexer(
            db, COMPANY_A, pipeline=pipeline_for(db, LocalEmbeddingProvider())
        ).index_stale()
        await db.commit()

    assert index_result.indexed == ["Knowledge/Sentinel.md"]
    assert index_result.chunks_written > 0
    async with session_factory() as db:
        row = (await db.execute(select(ObsidianDocument))).scalars().one()
        assert row.index_status == INDEX_STATUS_INDEXED


async def test_indexer_produces_chunks_with_embeddings(vault, session_factory) -> None:
    """Stage boundary: chunks exist, carry text, and carry vectors."""
    root, _ = vault
    write_note(root, COMPANY_A, "Knowledge/Sentinel.md", NOTE_BODY)

    await ingest(session_factory)

    async with session_factory() as db:
        chunks = list((await db.execute(select(KnowledgeChunk))).scalars().all())

    assert chunks, "no chunks were produced"
    assert any(SENTINEL in chunk.content for chunk in chunks)
    assert all(chunk.embedding_vector is not None for chunk in chunks), (
        "the deterministic provider produced no vectors"
    )


# ---------------------------------------------------------------------------
# Retrieval modes
# ---------------------------------------------------------------------------


async def test_keyword_only_retrieval(vault, session_factory) -> None:
    """With no embedding provider at all, BM25 alone still finds the note."""
    root, _ = vault
    write_note(root, COMPANY_A, "Knowledge/Sentinel.md", NOTE_BODY)

    await ingest(session_factory, provider=NullEmbeddingProvider())

    async with session_factory() as db:
        chunks = list((await db.execute(select(KnowledgeChunk))).scalars().all())
    assert chunks, "keyword-only indexing produced no chunks"

    results = await search(session_factory, SENTINEL, provider=NullEmbeddingProvider())
    assert hits_containing(results, SENTINEL)


async def test_vector_hybrid_retrieval(vault, session_factory) -> None:
    """Hybrid scoring retrieves the note, and the vector term participates.

    On SQLite this exercises ``RAGPipeline``'s Python cosine path rather than
    pgvector's ``<=>`` operator: ``_vector_candidates`` bails out unless the bind
    is PostgreSQL and the query embedding is exactly ``EMBEDDING_DIM`` wide. The
    hybrid *scoring* is the same code either way; only candidate selection
    differs, so what a PostgreSQL deployment adds is index-assisted narrowing,
    not different ranking.
    """
    root, _ = vault
    write_note(root, COMPANY_A, "Knowledge/Sentinel.md", NOTE_BODY)

    provider = LocalEmbeddingProvider()
    assert provider.dimension != EMBEDDING_DIM, (
        "this test documents the SQLite fallback; a 1536-wide local provider "
        "would change which path runs"
    )

    await ingest(session_factory, provider=provider)
    results = await search(session_factory, SENTINEL, provider=provider)

    matches = hits_containing(results, SENTINEL)
    assert matches
    hit = matches[0]
    assert hit["combined_score"] > 0
    assert "vector_score" in hit and "bm25_score" in hit


async def test_prose_query_retrieves_the_note(vault, session_factory) -> None:
    """Retrieval is not sentinel-only: ordinary wording finds the note too."""
    root, _ = vault
    write_note(root, COMPANY_A, "Knowledge/Sentinel.md", NOTE_BODY)

    await ingest(session_factory)
    results = await search(session_factory, "deployment runbooks")

    assert results, "a plain prose query retrieved nothing"


# ---------------------------------------------------------------------------
# Provenance
# ---------------------------------------------------------------------------


async def test_retrieved_chunk_carries_obsidian_provenance(
    vault, session_factory
) -> None:
    """A hit identifies its Obsidian source, not a KnowledgePage."""
    root, _ = vault
    write_note(root, COMPANY_A, "Knowledge/Sentinel.md", NOTE_BODY)

    await ingest(session_factory)
    async with session_factory() as db:
        document = (await db.execute(select(ObsidianDocument))).scalars().one()

    (hit,) = hits_containing(await search(session_factory, SENTINEL), SENTINEL)[:1]
    chunk = hit["chunk"]

    assert chunk.source_type == SOURCE_TYPE_OBSIDIAN_DOCUMENT
    assert chunk.source_id == document.nexus_id
    assert chunk.company_id == COMPANY_A
    assert chunk.source_type != SOURCE_TYPE_KNOWLEDGE_PAGE


async def test_search_response_declares_obsidian_provenance(
    vault, session_factory
) -> None:
    """The API result says which store a hit came from, explicitly."""
    root, _ = vault
    write_note(root, COMPANY_A, "Knowledge/Sentinel.md", NOTE_BODY)
    await ingest(session_factory)
    async with session_factory() as db:
        document = (await db.execute(select(ObsidianDocument))).scalars().one()

    body = knowledge_routes.RAGSearchRequest(query=SENTINEL, top_k=5)
    async with session_factory() as db:
        with patch(
            "nexus.knowledge.embeddings.get_embedding_provider",
            return_value=LocalEmbeddingProvider(),
        ):
            results = await knowledge_routes.rag_search(COMPANY_A, body, db)

    hits = [r for r in results if SENTINEL in r.content]
    assert hits, "the sentinel was not retrievable through the route"
    hit = hits[0]
    assert hit.source_type == SOURCE_TYPE_OBSIDIAN_DOCUMENT
    assert hit.source_id == document.nexus_id
    # page_id is retained for existing consumers and mirrors source_id; it is
    # NOT resolvable against /api/v1/knowledge/{page_id} for a vault hit.
    assert hit.page_id == hit.source_id


async def test_search_response_declares_knowledge_page_provenance(
    vault, session_factory
) -> None:
    """A page hit keeps its existing identity and is labelled as such."""
    async with session_factory() as db:
        page = KnowledgePage(
            company_id=COMPANY_A,
            title="Runbook",
            content="x",
            status="published",
        )
        db.add(page)
        await db.flush()
        page_id = page.id
        await pipeline_for(db, LocalEmbeddingProvider()).index_chunks(
            COMPANY_A, page_id, [f"A knowledge page holding {SENTINEL_B}."]
        )
        await db.commit()

    body = knowledge_routes.RAGSearchRequest(query=SENTINEL_B, top_k=5)
    async with session_factory() as db:
        with patch(
            "nexus.knowledge.embeddings.get_embedding_provider",
            return_value=LocalEmbeddingProvider(),
        ):
            results = await knowledge_routes.rag_search(COMPANY_A, body, db)

    hits = [r for r in results if SENTINEL_B in r.content]
    assert hits
    hit = hits[0]
    assert hit.source_type == SOURCE_TYPE_KNOWLEDGE_PAGE
    assert hit.source_id == page_id
    assert hit.page_id == page_id, "existing consumers must keep working"


async def test_mixed_corpus_results_are_individually_labelled(
    vault, session_factory
) -> None:
    """One query spanning both stores yields correctly attributed hits."""
    root, _ = vault
    write_note(
        root,
        COMPANY_A,
        "Knowledge/Shared.md",
        "A vault note about shared terminology.\n",
    )
    await ingest(session_factory)
    async with session_factory() as db:
        document = (await db.execute(select(ObsidianDocument))).scalars().one()
        page = KnowledgePage(
            company_id=COMPANY_A, title="Shared", content="x", status="published"
        )
        db.add(page)
        await db.flush()
        page_id = page.id
        await pipeline_for(db, LocalEmbeddingProvider()).index_chunks(
            COMPANY_A, page_id, ["A knowledge page about shared terminology."]
        )
        await db.commit()

    body = knowledge_routes.RAGSearchRequest(query="shared terminology", top_k=10)
    async with session_factory() as db:
        with patch(
            "nexus.knowledge.embeddings.get_embedding_provider",
            return_value=LocalEmbeddingProvider(),
        ):
            results = await knowledge_routes.rag_search(COMPANY_A, body, db)

    by_type = {r.source_type: r for r in results}
    assert set(by_type) == {SOURCE_TYPE_OBSIDIAN_DOCUMENT, SOURCE_TYPE_KNOWLEDGE_PAGE}
    assert by_type[SOURCE_TYPE_OBSIDIAN_DOCUMENT].source_id == document.nexus_id
    assert by_type[SOURCE_TYPE_KNOWLEDGE_PAGE].source_id == page_id
    # Every hit's page_id mirrors its own source_id, so no result attributes a
    # vault document to a page or the reverse.
    for hit in results:
        assert hit.page_id == hit.source_id


async def test_obsidian_and_page_chunks_are_distinguishable_in_one_corpus(
    vault, session_factory
) -> None:
    """Search spans both sources (ADR 0002 §13), and each hit says which it is.

    ``RAGPipeline.search`` filters on company_id only — deliberately, since the
    ADR makes existing RAG search the single query surface for vault content. So
    a caller must read ``source_type`` to know what it got; nothing about the
    query distinguishes them.
    """
    root, _ = vault
    write_note(root, COMPANY_A, "Knowledge/Sentinel.md", NOTE_BODY)
    await ingest(session_factory)

    # A knowledge-page chunk through the same pipeline, not hand-built.
    async with session_factory() as db:
        page = KnowledgePage(
            company_id=COMPANY_A, title="Page", content="x", status="published"
        )
        db.add(page)
        await db.flush()
        await pipeline_for(db, LocalEmbeddingProvider()).index_chunks(
            COMPANY_A, page.id, [f"A knowledge page mentioning {SENTINEL} as well."]
        )
        await db.commit()

    results = await search(session_factory, SENTINEL)
    sources = {r["chunk"].source_type for r in hits_containing(results, SENTINEL)}

    assert SOURCE_TYPE_OBSIDIAN_DOCUMENT in sources, "the vault chunk fell out of search"
    assert sources <= {SOURCE_TYPE_OBSIDIAN_DOCUMENT, SOURCE_TYPE_KNOWLEDGE_PAGE}


# ---------------------------------------------------------------------------
# Frontmatter exclusion
# ---------------------------------------------------------------------------


async def test_frontmatter_is_not_retrievable(vault, session_factory) -> None:
    """A title in frontmatter must not become a searchable chunk."""
    root, _ = vault
    write_note(root, COMPANY_A, "Knowledge/Sentinel.md", NOTE_BODY)

    await ingest(session_factory)

    async with session_factory() as db:
        chunks = list((await db.execute(select(KnowledgeChunk))).scalars().all())
    assert not any(FRONTMATTER_SENTINEL in chunk.content for chunk in chunks)

    results = await search(session_factory, FRONTMATTER_SENTINEL)
    assert hits_containing(results, FRONTMATTER_SENTINEL) == []


async def test_frontmatter_title_still_reaches_the_registry(
    vault, session_factory
) -> None:
    """Excluded from retrieval, not discarded: the row keeps the title."""
    root, _ = vault
    write_note(root, COMPANY_A, "Knowledge/Sentinel.md", NOTE_BODY)

    await ingest(session_factory)

    async with session_factory() as db:
        row = (await db.execute(select(ObsidianDocument))).scalars().one()
    assert row.title == FRONTMATTER_SENTINEL
    assert row.doc_type == "knowledge"


# ---------------------------------------------------------------------------
# Update replacement
# ---------------------------------------------------------------------------


async def test_edited_note_replaces_what_is_retrievable(vault, session_factory) -> None:
    """After an edit the old sentinel is gone from search and the new one is in."""
    root, _ = vault
    write_note(root, COMPANY_A, "Knowledge/Sentinel.md", NOTE_BODY)
    await ingest(session_factory)
    assert hits_containing(await search(session_factory, SENTINEL), SENTINEL)

    new_body = (
        f"---\ntitle: {FRONTMATTER_SENTINEL}\ntype: knowledge\n---\n"
        f"# Rewritten\n\nThe note now contains {SENTINEL_B} instead.\n"
    )
    write_note(root, COMPANY_A, "Knowledge/Sentinel.md", new_body)
    await ingest(session_factory)  # scan marks it stale, index replaces its chunks

    assert hits_containing(await search(session_factory, SENTINEL_B), SENTINEL_B)
    assert hits_containing(await search(session_factory, SENTINEL), SENTINEL) == [], (
        "the superseded sentinel is still retrievable"
    )


async def test_deleted_note_stops_being_retrievable(vault, session_factory) -> None:
    """Removing the file removes its content from the corpus."""
    root, _ = vault
    note = write_note(root, COMPANY_A, "Knowledge/Sentinel.md", NOTE_BODY)
    await ingest(session_factory)
    assert hits_containing(await search(session_factory, SENTINEL), SENTINEL)

    note.unlink()
    async with session_factory() as db:
        await VaultScanner(db, COMPANY_A).scan()
        await db.commit()

    assert hits_containing(await search(session_factory, SENTINEL), SENTINEL) == []


# ---------------------------------------------------------------------------
# Failure preservation, seen from the retrieval layer
# ---------------------------------------------------------------------------


async def test_failed_reindex_leaves_the_note_retrievable(vault, session_factory) -> None:
    """The 1B-3A savepoint fix, judged by what a user can still find.

    Without it, ``reindex_page``'s delete commits while the insert never happens,
    so a working note silently drops out of search with status ``failed``.
    """
    root, _ = vault
    write_note(root, COMPANY_A, "Knowledge/Sentinel.md", NOTE_BODY)
    await ingest(session_factory)
    assert hits_containing(await search(session_factory, SENTINEL), SENTINEL)

    async with session_factory() as db:
        row = (await db.execute(select(ObsidianDocument))).scalars().one()
        row.index_status = INDEX_STATUS_STALE
        db.add(row)
        await db.commit()

    class Exploding:
        dimension = EMBEDDING_DIM

        async def embed(self, text_or_texts):
            raise RuntimeError("embedding API unreachable")

        async def embed_batch(self, texts):
            raise RuntimeError("embedding API unreachable")

    async with session_factory() as db:
        result = await VaultIndexer(
            db, COMPANY_A, pipeline=pipeline_for(db, Exploding())
        ).index_stale()
        await db.commit()
    assert [path for path, _ in result.failed] == ["Knowledge/Sentinel.md"]

    assert hits_containing(await search(session_factory, SENTINEL), SENTINEL), (
        "a failed reindex made the note unretrievable"
    )
    async with session_factory() as db:
        row = (await db.execute(select(ObsidianDocument))).scalars().one()
    assert row.index_status == INDEX_STATUS_FAILED


# ---------------------------------------------------------------------------
# Tenant isolation
# ---------------------------------------------------------------------------


async def test_neither_company_can_retrieve_the_others_note(
    vault, session_factory
) -> None:
    """Two vaults, two sentinels: each company sees only its own."""
    root, _ = vault
    write_note(root, COMPANY_A, "Knowledge/A.md", f"Company A holds {SENTINEL}.\n")
    write_note(root, COMPANY_B, "Knowledge/B.md", f"Company B holds {SENTINEL_B}.\n")

    await ingest(session_factory, COMPANY_A)
    await ingest(session_factory, COMPANY_B)

    a_own = await search(session_factory, SENTINEL, COMPANY_A)
    b_own = await search(session_factory, SENTINEL_B, COMPANY_B)
    a_probing_b = await search(session_factory, SENTINEL_B, COMPANY_A)
    b_probing_a = await search(session_factory, SENTINEL, COMPANY_B)

    assert hits_containing(a_own, SENTINEL)
    assert hits_containing(b_own, SENTINEL_B)
    assert hits_containing(a_probing_b, SENTINEL_B) == [], "A retrieved B's content"
    assert hits_containing(b_probing_a, SENTINEL) == [], "B retrieved A's content"


async def test_every_retrieved_chunk_belongs_to_the_searching_company(
    vault, session_factory
) -> None:
    """Not just the sentinel: no result of any kind crosses the tenant boundary."""
    root, _ = vault
    write_note(root, COMPANY_A, "Knowledge/A.md", f"Company A holds {SENTINEL}.\n")
    write_note(root, COMPANY_B, "Knowledge/B.md", f"Company B holds {SENTINEL_B}.\n")

    await ingest(session_factory, COMPANY_A)
    await ingest(session_factory, COMPANY_B)

    for company in (COMPANY_A, COMPANY_B):
        results = await search(session_factory, "company holds", company)
        assert results, f"no results at all for {company}"
        assert {r["chunk"].company_id for r in results} == {company}
