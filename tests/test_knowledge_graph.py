"""Comprehensive tests for the Knowledge Graph (KnowledgeManager) module."""

import json
from pathlib import Path

from nexus.knowledge.graph import KnowledgeManager
from nexus.knowledge.graph_types import (
    IngestResult,
    KgHit,
    KgMeta,
    KnowledgeStatus,
)

# ── Test: ingest_text ────────────────────────────────────────────────────────


class TestIngestText:
    """Tests for ingest_text creating index.json and chunk files."""

    def test_creates_index_and_chunks(self, tmp_path: Path):
        """ingest_text creates index.json and chunk files on disk."""
        km = KnowledgeManager(str(tmp_path / "kg"))
        result = km.ingest_text("Hello world. This is a test document.", title="Test Doc")

        assert isinstance(result, IngestResult)
        assert result.chunk_count >= 1
        assert result.doc_id

        # Check index.json exists and has one entry
        index_path = tmp_path / "kg" / "index.json"
        assert index_path.exists()
        index = json.loads(index_path.read_text())
        assert len(index) == 1
        assert index[0]["id"] == result.doc_id
        assert index[0]["title"] == "Test Doc"

        # Check chunks directory
        chunks_dir = tmp_path / "kg" / "chunks" / result.doc_id
        assert chunks_dir.exists()
        assert (chunks_dir / "0.txt").exists()

    def test_default_title_is_untitled(self, tmp_path: Path):
        """ingest_text with no title defaults to 'Untitled'."""
        km = KnowledgeManager(str(tmp_path / "kg"))
        result = km.ingest_text("Some content here.")

        assert result.meta.title == "Untitled"

    def test_stores_tags(self, tmp_path: Path):
        """ingest_text stores the provided tags."""
        km = KnowledgeManager(str(tmp_path / "kg"))
        result = km.ingest_text("Content.", title="Tagged", tags=["python", "docs"])

        assert result.meta.tags == ["python", "docs"]

    def test_source_is_inline(self, tmp_path: Path):
        """ingest_text sets source to 'inline'."""
        km = KnowledgeManager(str(tmp_path / "kg"))
        result = km.ingest_text("Content.", title="Test")

        assert result.meta.source == "inline"

    def test_multiple_chunks_for_large_content(self, tmp_path: Path):
        """Large content is split into multiple chunks."""
        km = KnowledgeManager(str(tmp_path / "kg"))
        # Create content with multiple paragraphs exceeding chunk_size
        paragraphs = ["Paragraph number {}. " * 20 + "\n\n" for i in range(10)]
        content = "".join(paragraphs)
        result = km.ingest_text(content, title="Large Doc")

        assert result.chunk_count > 1
        chunks_dir = tmp_path / "kg" / "chunks" / result.doc_id
        chunk_files = list(chunks_dir.glob("*.txt"))
        assert len(chunk_files) == result.chunk_count

    def test_bytes_field_correct(self, tmp_path: Path):
        """bytes_ field matches UTF-8 byte length of content."""
        km = KnowledgeManager(str(tmp_path / "kg"))
        content = "Hello world"
        result = km.ingest_text(content, title="Test")

        assert result.meta.bytes_ == len(content.encode("utf-8"))


# ── Test: ingest_file ────────────────────────────────────────────────────────


class TestIngestFile:
    """Tests for ingest_file reading from disk."""

    def test_reads_file_and_ingests(self, tmp_path: Path):
        """ingest_file reads content from a file on disk."""
        km = KnowledgeManager(str(tmp_path / "kg"))
        doc_file = tmp_path / "document.txt"
        doc_file.write_text("This is file content for ingestion testing.")

        result = km.ingest_file(str(doc_file), title="File Doc")

        assert isinstance(result, IngestResult)
        assert result.meta.title == "File Doc"
        assert result.meta.source == str(doc_file)
        assert result.chunk_count >= 1

    def test_defaults_title_to_filename(self, tmp_path: Path):
        """ingest_file uses the filename as title when none is provided."""
        km = KnowledgeManager(str(tmp_path / "kg"))
        doc_file = tmp_path / "my_document.md"
        doc_file.write_text("# Heading\n\nSome content here.")

        result = km.ingest_file(str(doc_file))

        assert result.meta.title == "my_document.md"

    def test_detects_mime_type(self, tmp_path: Path):
        """ingest_file guesses MIME type from file extension."""
        km = KnowledgeManager(str(tmp_path / "kg"))
        doc_file = tmp_path / "readme.md"
        doc_file.write_text("# README\n\nProject readme.")

        result = km.ingest_file(str(doc_file))

        # .md may resolve to text/markdown or text/x-markdown depending on system
        assert result.meta.mime is not None

    def test_file_not_found_raises(self, tmp_path: Path):
        """ingest_file raises FileNotFoundError for missing files."""
        km = KnowledgeManager(str(tmp_path / "kg"))
        import pytest

        with pytest.raises(FileNotFoundError):
            km.ingest_file(str(tmp_path / "nonexistent.txt"))

    def test_stores_tags_and_caption(self, tmp_path: Path):
        """ingest_file stores tags and caption."""
        km = KnowledgeManager(str(tmp_path / "kg"))
        doc_file = tmp_path / "notes.txt"
        doc_file.write_text("Meeting notes from today.")

        result = km.ingest_file(
            str(doc_file), title="Notes", tags=["meeting"], caption="Daily standup"
        )

        assert result.meta.tags == ["meeting"]
        assert result.meta.caption == "Daily standup"


# ── Test: search ─────────────────────────────────────────────────────────────


class TestSearch:
    """Tests for BM25-powered search functionality."""

    def test_returns_relevant_hits(self, tmp_path: Path):
        """search returns hits scored by BM25 relevance."""
        km = KnowledgeManager(str(tmp_path / "kg"))
        km.ingest_text(
            "Python is a programming language used for web development.",
            title="Python Intro",
        )
        km.ingest_text(
            "JavaScript is used for frontend web development and Node.js.",
            title="JS Intro",
        )

        results = km.search("Python programming")

        assert len(results) >= 1
        assert isinstance(results[0], KgHit)
        assert results[0].score > 0
        # Python doc should rank higher for "Python programming" query
        python_hits = [h for h in results if "Python" in h.title]
        assert len(python_hits) > 0

    def test_empty_results_for_no_match(self, tmp_path: Path):
        """search returns empty list when no documents match."""
        km = KnowledgeManager(str(tmp_path / "kg"))
        km.ingest_text("Cats are wonderful pets.", title="Cats")

        results = km.search("quantum physics thermodynamics")

        assert results == []

    def test_respects_limit(self, tmp_path: Path):
        """search returns at most 'limit' results."""
        km = KnowledgeManager(str(tmp_path / "kg"))
        for i in range(20):
            km.ingest_text(
                f"Document {i} about software engineering practices.",
                title=f"Doc {i}",
            )

        results = km.search("software engineering", limit=5)

        assert len(results) <= 5

    def test_empty_store_returns_empty(self, tmp_path: Path):
        """search on empty store returns empty list."""
        km = KnowledgeManager(str(tmp_path / "kg"))
        results = km.search("anything")

        assert results == []

    def test_hit_fields_populated(self, tmp_path: Path):
        """search results have all expected fields populated."""
        km = KnowledgeManager(str(tmp_path / "kg"))
        km.ingest_text("Machine learning and deep learning.", title="ML Doc")

        results = km.search("machine learning")

        assert len(results) >= 1
        hit = results[0]
        assert hit.doc_id
        assert hit.title == "ML Doc"
        assert hit.source == "inline"
        assert hit.chunk_idx >= 0
        assert hit.score > 0
        assert hit.snippet


# ── Test: list_docs ──────────────────────────────────────────────────────────


class TestListDocs:
    """Tests for list_docs returning all ingested documents."""

    def test_returns_all_docs(self, tmp_path: Path):
        """list_docs returns metadata for all ingested documents."""
        km = KnowledgeManager(str(tmp_path / "kg"))
        km.ingest_text("First document.", title="Doc 1")
        km.ingest_text("Second document.", title="Doc 2")
        km.ingest_text("Third document.", title="Doc 3")

        docs = km.list_docs()

        assert len(docs) == 3
        titles = {d.title for d in docs}
        assert titles == {"Doc 1", "Doc 2", "Doc 3"}

    def test_empty_store(self, tmp_path: Path):
        """list_docs returns empty list for empty store."""
        km = KnowledgeManager(str(tmp_path / "kg"))
        docs = km.list_docs()

        assert docs == []

    def test_returns_kgmeta_instances(self, tmp_path: Path):
        """list_docs returns proper KgMeta instances."""
        km = KnowledgeManager(str(tmp_path / "kg"))
        km.ingest_text("Content here.", title="My Doc", tags=["test"])

        docs = km.list_docs()

        assert len(docs) == 1
        assert isinstance(docs[0], KgMeta)
        assert docs[0].title == "My Doc"
        assert docs[0].tags == ["test"]


# ── Test: get_doc ────────────────────────────────────────────────────────────


class TestGetDoc:
    """Tests for get_doc returning meta and full text."""

    def test_returns_full_text(self, tmp_path: Path):
        """get_doc returns reconstructed full text from chunks."""
        km = KnowledgeManager(str(tmp_path / "kg"))
        original = "First paragraph.\n\nSecond paragraph.\n\nThird paragraph."
        result = km.ingest_text(original, title="Full Text")

        doc = km.get_doc(result.doc_id)

        assert doc is not None
        assert isinstance(doc["meta"], KgMeta)
        assert doc["meta"].title == "Full Text"
        # The text should contain all original content (possibly reformatted)
        assert "First paragraph" in doc["text"]
        assert "Second paragraph" in doc["text"]
        assert "Third paragraph" in doc["text"]

    def test_unknown_doc_returns_none(self, tmp_path: Path):
        """get_doc returns None for a non-existent doc_id."""
        km = KnowledgeManager(str(tmp_path / "kg"))
        doc = km.get_doc("nonexistent_id_12345")

        assert doc is None

    def test_single_chunk_doc(self, tmp_path: Path):
        """get_doc works for a document with a single chunk."""
        km = KnowledgeManager(str(tmp_path / "kg"))
        result = km.ingest_text("Short content.", title="Short")

        doc = km.get_doc(result.doc_id)

        assert doc is not None
        assert "Short content" in doc["text"]


# ── Test: remove_doc ─────────────────────────────────────────────────────────


class TestRemoveDoc:
    """Tests for remove_doc removing from index and disk."""

    def test_removes_from_index_and_disk(self, tmp_path: Path):
        """remove_doc removes metadata from index and chunk files from disk."""
        km = KnowledgeManager(str(tmp_path / "kg"))
        result = km.ingest_text("Document to remove.", title="Removable")

        success = km.remove_doc(result.doc_id)

        assert success is True
        # Verify removed from index
        docs = km.list_docs()
        assert len(docs) == 0
        # Verify chunks directory removed
        chunks_dir = tmp_path / "kg" / "chunks" / result.doc_id
        assert not chunks_dir.exists()

    def test_unknown_doc_returns_false(self, tmp_path: Path):
        """remove_doc returns False for a non-existent doc_id."""
        km = KnowledgeManager(str(tmp_path / "kg"))
        result = km.remove_doc("nonexistent_id_12345")

        assert result is False

    def test_other_docs_unaffected(self, tmp_path: Path):
        """Removing one doc does not affect other documents."""
        km = KnowledgeManager(str(tmp_path / "kg"))
        r1 = km.ingest_text("Keep this one.", title="Keep")
        r2 = km.ingest_text("Remove this one.", title="Remove")

        km.remove_doc(r2.doc_id)

        docs = km.list_docs()
        assert len(docs) == 1
        assert docs[0].title == "Keep"
        # Kept doc is still retrievable
        doc = km.get_doc(r1.doc_id)
        assert doc is not None


# ── Test: stats ──────────────────────────────────────────────────────────────


class TestStats:
    """Tests for stats counting documents and modalities."""

    def test_counts_correctly(self, tmp_path: Path):
        """stats returns correct doc_count and chunk_count."""
        km = KnowledgeManager(str(tmp_path / "kg"))
        r1 = km.ingest_text("First document content.", title="Doc 1")
        r2 = km.ingest_text("Second document content.", title="Doc 2")

        status = km.stats()

        assert isinstance(status, KnowledgeStatus)
        assert status.enabled is True
        assert status.root == str(tmp_path / "kg")
        assert status.doc_count == 2
        assert status.chunk_count == r1.chunk_count + r2.chunk_count

    def test_empty_store_stats(self, tmp_path: Path):
        """stats on empty store returns zeros."""
        km = KnowledgeManager(str(tmp_path / "kg"))
        status = km.stats()

        assert status.doc_count == 0
        assert status.chunk_count == 0
        assert status.by_modality == {}

    def test_by_modality_counts(self, tmp_path: Path):
        """stats counts documents by modality correctly."""
        km = KnowledgeManager(str(tmp_path / "kg"))
        # Ingest with default modality (text)
        km.ingest_text("Text content.", title="Text Doc")
        km.ingest_text("More text.", title="Text Doc 2")
        # Manually ingest with different modality
        km._ingest_content(
            content="Code content",
            title="Code Doc",
            source="inline",
            tags=None,
            mime=None,
            modality="code",
        )

        status = km.stats()

        assert status.by_modality["text"] == 2
        assert status.by_modality["code"] == 1

    def test_stats_after_removal(self, tmp_path: Path):
        """stats updates after document removal."""
        km = KnowledgeManager(str(tmp_path / "kg"))
        r1 = km.ingest_text("Content one.", title="Doc 1")
        km.ingest_text("Content two.", title="Doc 2")

        km.remove_doc(r1.doc_id)
        status = km.stats()

        assert status.doc_count == 1


# ── Test: types importability ────────────────────────────────────────────────


class TestTypesImportable:
    """Verify all types are importable from nexus.knowledge.graph_types."""

    def test_all_types_importable(self):
        """All expected types can be imported and constructed."""
        from nexus.knowledge.graph_types import (
            IngestResult,
            KgHit,
            KgMeta,
            KnowledgeStatus,
        )

        meta = KgMeta(
            id="abc123",
            title="Test",
            source="test",
            bytes=42,
            chunk_count=1,
            added_at="2024-01-01T00:00:00Z",
        )
        assert meta.id == "abc123"
        assert meta.bytes_ == 42

        hit = KgHit(
            doc_id="abc", title="T", source="s", chunk_idx=0, score=1.0, snippet="x"
        )
        assert hit.score == 1.0

        result = IngestResult(doc_id="abc", chunk_count=1, meta=meta)
        assert result.chunk_count == 1

        status = KnowledgeStatus(
            enabled=True, root="/tmp", doc_count=1, chunk_count=1, by_modality={}
        )
        assert status.enabled is True

    def test_kgmeta_bytes_alias(self):
        """KgMeta bytes_ field is aliased from 'bytes' for serialization."""
        from nexus.knowledge.graph_types import KgMeta

        meta = KgMeta(
            id="test",
            title="Test",
            source="s",
            bytes=100,
            chunk_count=1,
            added_at="2024-01-01T00:00:00Z",
        )
        assert meta.bytes_ == 100
        # Serialized form should use 'bytes' key
        data = meta.model_dump(by_alias=True)
        assert "bytes" in data
        assert data["bytes"] == 100
