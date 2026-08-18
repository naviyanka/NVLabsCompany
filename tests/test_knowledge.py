"""Tests for the Knowledge System module.

Validates KnowledgePlaza, RAGPipeline, and ExperienceManager functionality.
Tests focus on pure logic methods that don't require database access.
DB-dependent methods are tested with mock sessions.
"""

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from nexus.knowledge.rag import RAGPipeline
from nexus.knowledge.plaza import KnowledgePlaza
from nexus.knowledge.experience import ExperienceManager


@pytest.fixture
def company_id():
    """Provide a fixed company UUID for tests."""
    return uuid.UUID("12345678-1234-1234-1234-123456789abc")


@pytest.fixture
def agent_id():
    """Provide a fixed agent UUID for tests."""
    return uuid.UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")


@pytest.fixture
def task_id():
    """Provide a fixed task UUID for tests."""
    return uuid.UUID("99999999-9999-9999-9999-999999999999")


@pytest.fixture
def page_id():
    """Provide a fixed page UUID for tests."""
    return uuid.UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")


@pytest.fixture
def mock_db():
    """Create a mock async database session."""
    session = AsyncMock()
    session.add = MagicMock()
    session.commit = AsyncMock()
    session.refresh = AsyncMock()
    session.exec = AsyncMock()
    return session


class TestRAGPipelineChunking:
    """Tests for RAGPipeline document chunking (pure logic, no DB)."""

    def test_chunk_by_paragraph(self, mock_db):
        """Paragraph strategy splits on double newlines."""
        rag = RAGPipeline(mock_db)
        content = "First paragraph.\n\nSecond paragraph.\n\nThird paragraph."
        chunks = rag.chunk_document(content, strategy="paragraph")
        assert len(chunks) == 3
        assert chunks[0] == "First paragraph."
        assert chunks[1] == "Second paragraph."
        assert chunks[2] == "Third paragraph."

    def test_chunk_by_paragraph_empty_lines(self, mock_db):
        """Paragraph strategy handles multiple blank lines."""
        rag = RAGPipeline(mock_db)
        content = "First.\n\n\n\nSecond."
        chunks = rag.chunk_document(content, strategy="paragraph")
        assert len(chunks) == 2

    def test_chunk_by_paragraph_single_paragraph(self, mock_db):
        """Paragraph strategy returns single chunk for no double newlines."""
        rag = RAGPipeline(mock_db)
        content = "Just one paragraph with no breaks."
        chunks = rag.chunk_document(content, strategy="paragraph")
        assert len(chunks) == 1
        assert chunks[0] == content

    def test_chunk_by_section(self, mock_db):
        """Section strategy splits on markdown headers."""
        rag = RAGPipeline(mock_db)
        content = "# Introduction\nSome text.\n\n## Details\nMore text.\n\n# Conclusion\nFinal text."
        chunks = rag.chunk_document(content, strategy="section")
        assert len(chunks) == 3
        assert "Introduction" in chunks[0]
        assert "Details" in chunks[1]
        assert "Conclusion" in chunks[2]

    def test_chunk_by_section_no_headers(self, mock_db):
        """Section strategy returns full content if no headers present."""
        rag = RAGPipeline(mock_db)
        content = "No headers in this document. Just plain text."
        chunks = rag.chunk_document(content, strategy="section")
        assert len(chunks) == 1
        assert chunks[0] == content

    def test_chunk_by_fixed_size(self, mock_db):
        """Fixed size strategy creates chunks of specified length."""
        rag = RAGPipeline(mock_db)
        content = "A" * 1000
        chunks = rag.chunk_document(content, strategy="fixed_size", chunk_size=200)
        assert len(chunks) >= 5
        # First chunk should be exactly 200 chars
        assert len(chunks[0]) == 200

    def test_chunk_by_fixed_size_with_overlap(self, mock_db):
        """Fixed size strategy includes overlap between chunks."""
        rag = RAGPipeline(mock_db)
        content = "0123456789" * 20  # 200 chars
        chunks = rag.chunk_document(content, strategy="fixed_size", chunk_size=100)
        # With 10% overlap (10 chars), content from end of chunk 1
        # should appear at start of chunk 2
        assert len(chunks) >= 2
        # Verify overlap exists: last 10 chars of chunk 1 == first 10 of chunk 2
        overlap = chunks[0][-10:]
        assert chunks[1].startswith(overlap)

    def test_chunk_empty_content(self, mock_db):
        """Chunking empty content returns empty list."""
        rag = RAGPipeline(mock_db)
        assert rag.chunk_document("", strategy="paragraph") == []
        assert rag.chunk_document("", strategy="fixed_size") == []

    def test_chunk_invalid_strategy_raises(self, mock_db):
        """Invalid strategy raises ValueError."""
        rag = RAGPipeline(mock_db)
        with pytest.raises(ValueError, match="Unsupported chunking strategy"):
            rag.chunk_document("content", strategy="invalid")


class TestRAGPipelineRerank:
    """Tests for RAGPipeline reranking (pure logic)."""

    def test_rerank_returns_top_k(self, mock_db):
        """Rerank returns at most top_k results."""
        rag = RAGPipeline(mock_db)

        # Create mock chunks
        results = []
        for i in range(5):
            mock_chunk = MagicMock()
            mock_chunk.content = f"chunk {i} about python programming"
            mock_chunk.chunk_index = i
            mock_chunk.created_at = datetime.now(timezone.utc)
            results.append({
                "chunk": mock_chunk,
                "bm25_score": 1.0 - i * 0.1,
                "vector_score": 0.5,
                "combined_score": 0.8 - i * 0.1,
            })

        reranked = rag.rerank("python programming", results, top_k=3)
        assert len(reranked) == 3

    def test_rerank_empty_results(self, mock_db):
        """Rerank returns empty list for empty input."""
        rag = RAGPipeline(mock_db)
        assert rag.rerank("query", [], top_k=3) == []

    def test_rerank_considers_term_overlap(self, mock_db):
        """Results with higher query term overlap rank higher."""
        rag = RAGPipeline(mock_db)

        chunk_relevant = MagicMock()
        chunk_relevant.content = "python machine learning deep learning neural networks"
        chunk_relevant.chunk_index = 0
        chunk_relevant.created_at = datetime.now(timezone.utc)

        chunk_irrelevant = MagicMock()
        chunk_irrelevant.content = "cooking recipes for dinner tonight salad"
        chunk_irrelevant.chunk_index = 1
        chunk_irrelevant.created_at = datetime.now(timezone.utc)

        results = [
            {"chunk": chunk_irrelevant, "bm25_score": 0.5, "vector_score": 0.5, "combined_score": 0.5},
            {"chunk": chunk_relevant, "bm25_score": 0.5, "vector_score": 0.5, "combined_score": 0.5},
        ]

        reranked = rag.rerank("python machine learning", results, top_k=2)
        # The relevant chunk should rank first
        assert reranked[0]["chunk"] == chunk_relevant


class TestRAGPipelineAssembleContext:
    """Tests for RAGPipeline context assembly (pure logic)."""

    def test_assemble_context_basic(self, mock_db):
        """Assemble context joins chunks with source labels."""
        rag = RAGPipeline(mock_db)

        chunk1 = MagicMock()
        chunk1.content = "First chunk content"
        chunk2 = MagicMock()
        chunk2.content = "Second chunk content"

        results = [
            {"chunk": chunk1},
            {"chunk": chunk2},
        ]

        context = rag.assemble_context(results, max_tokens=4000)
        assert "[Source 1]" in context
        assert "[Source 2]" in context
        assert "First chunk content" in context
        assert "Second chunk content" in context

    def test_assemble_context_respects_token_budget(self, mock_db):
        """Context assembly stops when token budget is exhausted."""
        rag = RAGPipeline(mock_db)

        # Create chunks that exceed budget
        results = []
        for i in range(20):
            chunk = MagicMock()
            chunk.content = "X" * 1000  # Each chunk is ~250 tokens
            results.append({"chunk": chunk})

        # 100 tokens = 400 chars budget
        context = rag.assemble_context(results, max_tokens=100)
        assert len(context) <= 500  # Some overhead for labels

    def test_assemble_context_empty_results(self, mock_db):
        """Empty results produce empty context."""
        rag = RAGPipeline(mock_db)
        context = rag.assemble_context([], max_tokens=4000)
        assert context == ""


class TestKnowledgePlaza:
    """Tests for KnowledgePlaza with mock database."""

    @pytest.mark.asyncio
    async def test_publish_page_creates_record(self, mock_db, company_id, agent_id):
        """publish_page creates a KnowledgePage with version=1."""
        plaza = KnowledgePlaza(mock_db)

        page = await plaza.publish_page(
            company_id=company_id,
            title="Test Page",
            content="Page content here.",
            category="engineering",
            tags=["python", "testing"],
            author_agent_id=agent_id,
        )

        mock_db.add.assert_called_once()
        mock_db.commit.assert_awaited_once()
        assert page.title == "Test Page"
        assert page.version == 1
        assert page.status == "published"
        assert page.company_id == company_id

    @pytest.mark.asyncio
    async def test_update_page_increments_version(self, mock_db, company_id, agent_id, page_id):
        """update_page increments the version number."""
        plaza = KnowledgePlaza(mock_db)

        # Mock the existing page
        existing_page = MagicMock()
        existing_page.id = page_id
        existing_page.content = "Old content"
        existing_page.version = 2
        existing_page.author_agent_id = agent_id

        mock_result = MagicMock()
        mock_result.first.return_value = existing_page
        mock_db.exec.return_value = mock_result

        page = await plaza.update_page(
            page_id=page_id,
            content="New content",
            editor_agent_id=agent_id,
        )

        assert page.content == "New content"
        assert page.version == 3
        mock_db.commit.assert_awaited()

    @pytest.mark.asyncio
    async def test_update_page_not_found_raises(self, mock_db, page_id, agent_id):
        """update_page raises ValueError for non-existent page."""
        plaza = KnowledgePlaza(mock_db)

        mock_result = MagicMock()
        mock_result.first.return_value = None
        mock_db.exec.return_value = mock_result

        with pytest.raises(ValueError, match="Knowledge page not found"):
            await plaza.update_page(page_id, "content", agent_id)

    @pytest.mark.asyncio
    async def test_search_pages_uses_bm25(self, mock_db, company_id):
        """search_pages returns pages ranked by BM25 relevance."""
        plaza = KnowledgePlaza(mock_db)

        # Create mock pages
        page1 = MagicMock()
        page1.title = "Python Guide"
        page1.content = "Python is a programming language"
        page1.tags = ["python"]

        page2 = MagicMock()
        page2.title = "Java Guide"
        page2.content = "Java is an enterprise language"
        page2.tags = ["java"]

        mock_result = MagicMock()
        mock_result.all.return_value = [page1, page2]
        mock_db.exec.return_value = mock_result

        results = await plaza.search_pages(company_id, "Python programming")
        # BM25 should rank Python page higher
        assert len(results) > 0
        assert results[0].title == "Python Guide"

    @pytest.mark.asyncio
    async def test_list_categories(self, mock_db, company_id):
        """list_categories returns distinct category values."""
        plaza = KnowledgePlaza(mock_db)

        mock_result = MagicMock()
        mock_result.all.return_value = ["engineering", "policy", "engineering"]
        mock_db.exec.return_value = mock_result

        categories = await plaza.list_categories(company_id)
        # Should be deduplicated
        assert "engineering" in categories
        assert "policy" in categories


class TestExperienceManager:
    """Tests for ExperienceManager with mock database."""

    @pytest.mark.asyncio
    async def test_record_experience(self, mock_db, company_id, agent_id, task_id):
        """record_experience creates an ExperienceRecord."""
        mgr = ExperienceManager(mock_db)

        record = await mgr.record_experience(
            company_id=company_id,
            agent_id=agent_id,
            task_id=task_id,
            outcome="success",
            approach="Used BFS algorithm",
            result_quality=0.9,
            lessons_learned="BFS works well for shortest path",
            tags=["algorithms", "graphs"],
        )

        mock_db.add.assert_called_once()
        mock_db.commit.assert_awaited_once()
        assert record.outcome == "success"
        assert record.result_quality == 0.9
        assert record.company_id == company_id

    @pytest.mark.asyncio
    async def test_find_similar_experiences(self, mock_db, company_id, agent_id, task_id):
        """find_similar_experiences uses BM25 on approach+lessons."""
        mgr = ExperienceManager(mock_db)

        # Mock experiences
        exp1 = MagicMock()
        exp1.approach = "Used machine learning for classification"
        exp1.lessons_learned = "Random forest worked best"

        exp2 = MagicMock()
        exp2.approach = "Used SQL queries for data extraction"
        exp2.lessons_learned = "Indexing improved performance"

        mock_result = MagicMock()
        mock_result.all.return_value = [exp1, exp2]
        mock_db.exec.return_value = mock_result

        results = await mgr.find_similar_experiences(
            company_id=company_id,
            description="machine learning classification task",
            top_k=5,
        )

        # BM25 should rank ML experience higher
        assert len(results) > 0
        assert results[0].approach == "Used machine learning for classification"

    @pytest.mark.asyncio
    async def test_get_success_patterns_groups_by_tag(self, mock_db, company_id):
        """get_success_patterns groups experiences by tags."""
        mgr = ExperienceManager(mock_db)

        # Mock successful experiences
        exp1 = MagicMock()
        exp1.tags = ["python", "api"]
        exp1.approach = "FastAPI approach"
        exp1.lessons_learned = "Async helps"
        exp1.result_quality = 0.9

        exp2 = MagicMock()
        exp2.tags = ["python"]
        exp2.approach = "Flask approach"
        exp2.lessons_learned = "Simple is better"
        exp2.result_quality = 0.8

        mock_result = MagicMock()
        mock_result.all.return_value = [exp1, exp2]
        mock_db.exec.return_value = mock_result

        patterns = await mgr.get_success_patterns(company_id)
        assert len(patterns) > 0
        # Python tag should have 2 experiences
        python_pattern = next((p for p in patterns if p["tag"] == "python"), None)
        assert python_pattern is not None
        assert python_pattern["count"] == 2

    @pytest.mark.asyncio
    async def test_share_experience(self, mock_db):
        """share_experience adds team sharing tag."""
        mgr = ExperienceManager(mock_db)

        experience_id = uuid.uuid4()
        target_team_id = uuid.uuid4()

        # Mock existing experience
        existing_record = MagicMock()
        existing_record.id = experience_id
        existing_record.tags = ["existing_tag"]

        mock_result = MagicMock()
        mock_result.first.return_value = existing_record
        mock_db.exec.return_value = mock_result

        record = await mgr.share_experience(experience_id, target_team_id)

        assert f"shared:team:{target_team_id}" in record.tags
        assert "existing_tag" in record.tags
        mock_db.commit.assert_awaited()

    @pytest.mark.asyncio
    async def test_share_experience_not_found_raises(self, mock_db):
        """share_experience raises ValueError for non-existent record."""
        mgr = ExperienceManager(mock_db)

        mock_result = MagicMock()
        mock_result.first.return_value = None
        mock_db.exec.return_value = mock_result

        with pytest.raises(ValueError, match="Experience record not found"):
            await mgr.share_experience(uuid.uuid4(), uuid.uuid4())
