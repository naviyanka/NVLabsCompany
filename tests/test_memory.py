"""Tests for MemoryStore (3-tier system) and BM25 retriever.

Tests actual BM25 scoring logic (pure Python, no dependencies needed)
and validates the MemoryStore hot cache and tier management.
"""

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from nexus.memory.retriever import (
    tokenize,
    bm25_score,
    search,
    _compute_corpus_stats,
    CorpusStats,
)
from nexus.memory.store import MemoryStore, MemoryEntry


# ============================================================
# BM25 Retriever Tests (pure logic, no mocks needed)
# ============================================================


class TestTokenize:
    """Tests for the tokenize function."""

    def test_basic_tokenization(self):
        """Splits text into lowercase tokens."""
        tokens = tokenize("Hello World")
        assert tokens == ["hello", "world"]

    def test_removes_punctuation(self):
        """Strips punctuation from tokens."""
        tokens = tokenize("Hello, world! How are you?")
        assert "hello" in tokens
        assert "world" in tokens
        assert "how" in tokens
        # No punctuation in tokens
        for t in tokens:
            assert "," not in t
            assert "!" not in t
            assert "?" not in t

    def test_filters_single_char_except_allowed(self):
        """Filters out single characters except 'i' and 'a'."""
        tokens = tokenize("I am a big x fan")
        assert "i" in tokens
        assert "a" in tokens
        assert "am" in tokens
        assert "big" in tokens
        assert "fan" in tokens
        # 'x' is single char and not in allowed set
        assert "x" not in tokens

    def test_empty_string(self):
        """Empty string returns empty list."""
        tokens = tokenize("")
        assert tokens == []

    def test_numbers_preserved(self):
        """Numbers are kept as tokens."""
        tokens = tokenize("Model GPT 4o with 128k context")
        assert "model" in tokens
        assert "gpt" in tokens
        assert "4o" in tokens
        assert "128k" in tokens


class TestCorpusStats:
    """Tests for corpus statistics computation."""

    def test_empty_corpus(self):
        """Empty corpus returns zero stats."""
        stats = _compute_corpus_stats([])
        assert stats.total_docs == 0
        assert stats.avg_doc_length == 0.0
        assert stats.doc_frequencies == {}

    def test_single_document(self):
        """Single document corpus has correct stats."""
        docs = [["hello", "world", "hello"]]
        stats = _compute_corpus_stats(docs)
        assert stats.total_docs == 1
        assert stats.avg_doc_length == 3.0
        # "hello" appears in 1 doc, "world" appears in 1 doc
        assert stats.doc_frequencies["hello"] == 1
        assert stats.doc_frequencies["world"] == 1

    def test_multiple_documents(self):
        """Multiple document corpus computes correct doc frequencies."""
        docs = [
            ["python", "programming", "language"],
            ["python", "snake", "animal"],
            ["java", "programming", "language"],
        ]
        stats = _compute_corpus_stats(docs)
        assert stats.total_docs == 3
        assert stats.avg_doc_length == 3.0
        # "python" appears in 2 docs
        assert stats.doc_frequencies["python"] == 2
        # "programming" appears in 2 docs
        assert stats.doc_frequencies["programming"] == 2
        # "snake" appears in 1 doc
        assert stats.doc_frequencies["snake"] == 1


class TestBM25Score:
    """Tests for the BM25 scoring function."""

    def test_relevant_doc_scores_higher(self):
        """A document matching the query scores higher than one that does not."""
        docs = [
            ["python", "machine", "learning", "ai"],
            ["cooking", "recipes", "food", "kitchen"],
            ["python", "deep", "learning", "neural", "network"],
        ]
        stats = _compute_corpus_stats(docs)
        query = ["python", "learning"]

        score_relevant = bm25_score(query, docs[0], stats)
        score_irrelevant = bm25_score(query, docs[1], stats)
        score_more_relevant = bm25_score(query, docs[2], stats)

        # Relevant docs should score higher than irrelevant
        assert score_relevant > score_irrelevant
        assert score_more_relevant > score_irrelevant
        # Irrelevant doc should score 0
        assert score_irrelevant == 0.0

    def test_empty_document_scores_zero(self):
        """Empty document always scores zero."""
        stats = CorpusStats(total_docs=3, avg_doc_length=5.0, doc_frequencies={"hello": 2})
        score = bm25_score(["hello"], [], stats)
        assert score == 0.0

    def test_empty_corpus_scores_zero(self):
        """Score is zero when corpus has no documents."""
        stats = CorpusStats(total_docs=0, avg_doc_length=0.0, doc_frequencies={})
        score = bm25_score(["hello"], ["hello", "world"], stats)
        assert score == 0.0

    def test_term_frequency_affects_score(self):
        """Higher term frequency in a document increases score (with saturation)."""
        docs = [
            ["python", "python", "python", "code"],
            ["python", "java", "rust", "go"],
        ]
        stats = _compute_corpus_stats(docs)
        query = ["python"]

        score_high_tf = bm25_score(query, docs[0], stats)
        score_low_tf = bm25_score(query, docs[1], stats)

        # Higher TF should give higher score (before saturation)
        assert score_high_tf > score_low_tf

    def test_idf_rare_term_scores_higher(self):
        """Rare terms (lower document frequency) contribute more to score."""
        docs = [
            ["common", "rare", "word"],
            ["common", "other", "stuff"],
            ["common", "more", "things"],
        ]
        stats = _compute_corpus_stats(docs)

        # Query with rare term should score higher for the doc containing it
        score_rare = bm25_score(["rare"], docs[0], stats)
        score_common = bm25_score(["common"], docs[0], stats)

        # "rare" appears in 1/3 docs (high IDF), "common" in 3/3 (low IDF)
        assert score_rare > score_common


class TestSearch:
    """Tests for the search function."""

    def test_search_returns_top_k(self):
        """Search returns at most top_k results."""
        memories = [
            "Python is a programming language",
            "Java is also a programming language",
            "Cooking is an art form",
            "Python machine learning is popular",
            "Deep learning with Python and TensorFlow",
        ]

        results = search("Python programming", memories, top_k=2)
        assert len(results) <= 2
        # Results are (index, score) tuples
        assert all(isinstance(r, tuple) and len(r) == 2 for r in results)

    def test_search_relevance_ordering(self):
        """Search results are sorted by relevance (highest score first)."""
        memories = [
            "The weather is nice today",
            "Python programming language tutorial",
            "Advanced Python programming techniques and patterns",
            "Cooking dinner recipes",
        ]

        results = search("Python programming", memories, top_k=5)

        # Should return at least the Python-related docs
        assert len(results) >= 2
        # Scores should be in descending order
        scores = [score for _, score in results]
        assert scores == sorted(scores, reverse=True)

    def test_search_empty_query(self):
        """Empty query returns no results."""
        memories = ["Hello world", "Foo bar"]
        results = search("", memories)
        assert results == []

    def test_search_empty_memories(self):
        """Empty memories list returns no results."""
        results = search("test query", [])
        assert results == []

    def test_search_no_matching_docs(self):
        """Query with no matching terms returns empty results."""
        memories = [
            "The cat sat on the mat",
            "Dogs are loyal companions",
        ]
        results = search("quantum physics relativity", memories)
        assert results == []

    def test_search_returns_correct_indices(self):
        """Search returns correct indices into the memories list."""
        memories = [
            "Irrelevant document about cooking",
            "Python machine learning deep neural networks",
            "Another unrelated document about sports",
        ]

        results = search("Python machine learning", memories, top_k=5)

        # Index 1 should be in results (the relevant document)
        indices = [idx for idx, _ in results]
        assert 1 in indices


# ============================================================
# MemoryStore Tests (uses mocked DB session)
# ============================================================


class TestMemoryStoreHotCache:
    """Tests for MemoryStore hot cache operations."""

    @pytest.mark.asyncio
    async def test_store_adds_to_hot_cache(self, mock_db_session):
        """Storing a memory adds it to the hot cache."""
        store = MemoryStore(mock_db_session)

        scope = "agent"
        scope_id = uuid.uuid4()
        memory_id = await store.store(
            scope=scope,
            scope_id=scope_id,
            content="Test memory content",
            importance=0.8,
        )

        assert memory_id is not None
        # Verify it is in the hot cache
        key = store._cache_key(scope, scope_id)
        assert key in store._hot
        assert len(store._hot[key]) == 1
        assert store._hot[key][0].content == "Test memory content"
        assert store._hot[key][0].importance == 0.8

    @pytest.mark.asyncio
    async def test_store_persists_to_db(self, mock_db_session):
        """Storing a memory calls db.add and db.flush."""
        store = MemoryStore(mock_db_session)

        await store.store(
            scope="company",
            scope_id=uuid.uuid4(),
            content="Persistent memory",
        )

        mock_db_session.add.assert_called_once()
        mock_db_session.flush.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_retrieve_from_hot_cache(self, mock_db_session):
        """Retrieve finds memories in the hot cache first."""
        store = MemoryStore(mock_db_session)
        scope = "agent"
        scope_id = uuid.uuid4()

        # Store a memory (goes to hot cache)
        await store.store(
            scope=scope, scope_id=scope_id, content="Hot memory"
        )

        # Mock execute to return empty (simulating no warm records needed)
        mock_result = MagicMock()
        mock_scalars = MagicMock()
        mock_scalars.all.return_value = []
        mock_result.scalars.return_value = mock_scalars
        mock_db_session.execute.return_value = mock_result

        results = await store.retrieve(scope=scope, scope_id=scope_id)

        assert len(results) >= 1
        assert results[0].content == "Hot memory"
        assert results[0].tier == "hot"


class TestMemoryStorePromoteDemote:
    """Tests for MemoryStore promote/demote tier transitions."""

    @pytest.mark.asyncio
    async def test_promote_warm_to_hot(self, mock_db_session):
        """Promoting a warm memory moves it to hot cache."""
        from nexus.models.memory import MemoryRecord

        store = MemoryStore(mock_db_session)
        memory_id = uuid.uuid4()

        # Mock: memory exists in warm tier
        mock_record = MagicMock(spec=MemoryRecord)
        mock_record.id = memory_id
        mock_record.scope = "agent"
        mock_record.scope_id = uuid.uuid4()
        mock_record.content = "Warm memory content"
        mock_record.metadata = None
        mock_record.importance = 0.6
        mock_record.access_count = 3
        mock_record.tier = "warm"
        mock_record.created_at = datetime.now(timezone.utc)

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_record
        mock_db_session.execute.return_value = mock_result

        new_tier = await store.promote(memory_id)

        assert new_tier == "hot"
        # Verify it was added to hot cache
        key = store._cache_key(mock_record.scope, mock_record.scope_id)
        assert key in store._hot
        assert any(e.id == memory_id for e in store._hot[key])

    @pytest.mark.asyncio
    async def test_demote_hot_to_warm(self, mock_db_session):
        """Demoting a hot memory removes it from hot cache."""
        store = MemoryStore(mock_db_session)
        scope = "team"
        scope_id = uuid.uuid4()

        # First store to hot cache
        memory_id_str = await store.store(
            scope=scope, scope_id=scope_id, content="Hot content"
        )
        memory_id = uuid.UUID(memory_id_str)

        # Verify it is in hot cache
        key = store._cache_key(scope, scope_id)
        assert len(store._hot[key]) == 1

        # Demote it
        new_tier = await store.demote(memory_id)

        assert new_tier == "warm"
        # Hot cache should be empty for this key now
        assert key not in store._hot or len(store._hot.get(key, [])) == 0


class TestMemoryStoreScopeFiltering:
    """Tests for MemoryStore scope-based filtering."""

    @pytest.mark.asyncio
    async def test_different_scopes_isolated(self, mock_db_session):
        """Memories in different scopes are isolated."""
        store = MemoryStore(mock_db_session)
        scope_id_1 = uuid.uuid4()
        scope_id_2 = uuid.uuid4()

        await store.store(scope="agent", scope_id=scope_id_1, content="Agent memory 1")
        await store.store(scope="team", scope_id=scope_id_2, content="Team memory")

        # Hot cache keys should be different
        key1 = store._cache_key("agent", scope_id_1)
        key2 = store._cache_key("team", scope_id_2)
        assert key1 != key2
        assert len(store._hot[key1]) == 1
        assert len(store._hot[key2]) == 1
        assert store._hot[key1][0].content == "Agent memory 1"
        assert store._hot[key2][0].content == "Team memory"
