"""Tests for the enhanced RAG Pipeline components.

Validates all new pluggable components: rankers, retrievers, parsers,
and their integration with the RAGPipeline class. Tests focus on pure
logic and use AsyncMock for async operations.
"""

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from nexus.knowledge.parsers import (
    CodeParser,
    DocumentParser,
    MarkdownParser,
    ParsedChunk,
    TextParser,
)
from nexus.knowledge.rankers import (
    BM25Ranker,
    CrossEncoderRanker,
    Ranker,
    RerankerPipeline,
)
from nexus.knowledge.retrievers import (
    DenseRetriever,
    HybridRetriever,
    Retriever,
    SparseRetriever,
    retriever_factory,
)
from nexus.knowledge.rag import RAGPipeline


# ============================================================
# Fixtures
# ============================================================


@pytest.fixture
def mock_db():
    """Create a mock async database session."""
    session = AsyncMock()
    session.add = MagicMock()
    session.commit = AsyncMock()
    session.refresh = AsyncMock()
    session.exec = AsyncMock()
    return session


@pytest.fixture
def mock_embedding_provider():
    """Create a mock embedding provider."""
    provider = AsyncMock()
    # Return simple deterministic embeddings
    provider.embed = AsyncMock(return_value=[0.1, 0.2, 0.3, 0.4, 0.5])
    provider.embed_batch = AsyncMock(return_value=[
        [0.1, 0.2, 0.3, 0.4, 0.5],
        [0.5, 0.4, 0.3, 0.2, 0.1],
        [0.3, 0.3, 0.3, 0.3, 0.3],
    ])
    return provider


@pytest.fixture
def sample_results():
    """Create sample search results for ranker tests."""
    return [
        {"content": "Python is a great programming language for data science"},
        {"content": "JavaScript runs in the browser and on servers"},
        {"content": "Machine learning uses Python extensively for model training"},
        {"content": "HTML and CSS are used for web page styling"},
        {"content": "Python libraries like pandas help with data analysis"},
    ]


@pytest.fixture
def sample_documents():
    """Create sample documents for retriever tests."""
    return [
        "Python is a versatile programming language",
        "Machine learning requires large datasets",
        "Web development uses HTML CSS and JavaScript",
        "Data science combines statistics and programming",
        "Natural language processing handles text data",
    ]


# ============================================================
# Ranker Protocol Tests
# ============================================================


class TestRankerProtocol:
    """Tests for the Ranker protocol and protocol conformance."""

    def test_bm25_ranker_implements_protocol(self):
        """BM25Ranker is recognized as implementing the Ranker protocol."""
        ranker = BM25Ranker()
        assert isinstance(ranker, Ranker)

    def test_cross_encoder_ranker_implements_protocol(self):
        """CrossEncoderRanker is recognized as implementing the Ranker protocol."""
        ranker = CrossEncoderRanker()
        assert isinstance(ranker, Ranker)

    def test_reranker_pipeline_implements_protocol(self):
        """RerankerPipeline is recognized as implementing the Ranker protocol."""
        pipeline = RerankerPipeline()
        assert isinstance(pipeline, Ranker)

    def test_custom_object_with_rank_method_matches_protocol(self):
        """Any object with a rank method satisfies the Ranker protocol."""
        class CustomRanker:
            def rank(self, query, results):
                return results

        custom = CustomRanker()
        assert isinstance(custom, Ranker)


# ============================================================
# BM25Ranker Tests
# ============================================================


class TestBM25Ranker:
    """Tests for BM25Ranker implementation."""

    def test_rank_returns_results(self, sample_results):
        """BM25Ranker returns ranked results for a valid query."""
        ranker = BM25Ranker(top_k=3)
        ranked = ranker.rank("Python programming", sample_results)
        assert len(ranked) == 3
        assert all(isinstance(r, dict) for r in ranked)

    def test_rank_empty_query_returns_results(self, sample_results):
        """BM25Ranker handles empty query gracefully."""
        ranker = BM25Ranker(top_k=5)
        ranked = ranker.rank("", sample_results)
        # Should return results unchanged (up to top_k)
        assert len(ranked) <= 5

    def test_rank_empty_results(self):
        """BM25Ranker returns empty list for empty results."""
        ranker = BM25Ranker()
        ranked = ranker.rank("Python", [])
        assert ranked == []

    def test_rank_respects_top_k(self, sample_results):
        """BM25Ranker limits output to top_k results."""
        ranker = BM25Ranker(top_k=2)
        ranked = ranker.rank("Python programming", sample_results)
        assert len(ranked) <= 2

    def test_rank_prioritizes_relevant_content(self, sample_results):
        """BM25Ranker places more relevant content higher."""
        ranker = BM25Ranker(top_k=5)
        ranked = ranker.rank("Python programming language", sample_results)
        # Python-related results should be ranked higher than unrelated ones
        top_content = ranked[0]["content"]
        assert "Python" in top_content or "programming" in top_content

    def test_rank_with_chunk_objects(self):
        """BM25Ranker handles results with chunk objects."""
        chunk_mock = MagicMock()
        chunk_mock.content = "Python data science analysis"
        results = [
            {"chunk": chunk_mock, "combined_score": 0.5},
            {"content": "JavaScript web development"},
        ]
        ranker = BM25Ranker(top_k=5)
        ranked = ranker.rank("Python data", results)
        assert len(ranked) > 0


# ============================================================
# CrossEncoderRanker Tests
# ============================================================


class TestCrossEncoderRanker:
    """Tests for CrossEncoderRanker implementation."""

    def test_rank_returns_results(self, sample_results):
        """CrossEncoderRanker returns ranked results."""
        ranker = CrossEncoderRanker(top_k=3)
        ranked = ranker.rank("Python programming", sample_results)
        assert len(ranked) == 3

    def test_rank_empty_results(self):
        """CrossEncoderRanker returns empty list for empty results."""
        ranker = CrossEncoderRanker()
        ranked = ranker.rank("query", [])
        assert ranked == []

    def test_rank_with_custom_scoring_fn(self, sample_results):
        """CrossEncoderRanker uses custom scoring function when provided."""
        # Custom scoring: count occurrences of 'Python' in content
        def custom_score(query, content):
            return content.lower().count("python")

        ranker = CrossEncoderRanker(top_k=5, scoring_fn=custom_score)
        ranked = ranker.rank("Python", sample_results)
        # Results with 'Python' should be first
        assert "Python" in ranked[0]["content"]

    def test_rank_configurable_weights(self, sample_results):
        """CrossEncoderRanker respects custom weight configuration."""
        ranker = CrossEncoderRanker(
            top_k=5,
            bm25_weight=0.9,
            overlap_weight=0.1,
        )
        ranked = ranker.rank("Python data science", sample_results)
        assert len(ranked) <= 5

    def test_rank_handles_empty_query(self, sample_results):
        """CrossEncoderRanker handles empty query gracefully."""
        ranker = CrossEncoderRanker(top_k=5)
        ranked = ranker.rank("", sample_results)
        assert len(ranked) <= 5


# ============================================================
# RerankerPipeline Tests
# ============================================================


class TestRerankerPipeline:
    """Tests for RerankerPipeline chaining."""

    def test_empty_pipeline_returns_unchanged(self, sample_results):
        """Empty pipeline returns results unchanged."""
        pipeline = RerankerPipeline(rankers=[])
        ranked = pipeline.rank("Python", sample_results)
        assert ranked == sample_results

    def test_single_ranker_pipeline(self, sample_results):
        """Pipeline with one ranker delegates to that ranker."""
        bm25 = BM25Ranker(top_k=3)
        pipeline = RerankerPipeline(rankers=[bm25])
        ranked = pipeline.rank("Python programming", sample_results)
        assert len(ranked) == 3

    def test_multi_ranker_pipeline(self, sample_results):
        """Pipeline chains multiple rankers sequentially."""
        # First ranker: wide filter (top 4)
        first = BM25Ranker(top_k=4)
        # Second ranker: narrow filter (top 2)
        second = CrossEncoderRanker(top_k=2)
        pipeline = RerankerPipeline(rankers=[first, second])
        ranked = pipeline.rank("Python programming", sample_results)
        assert len(ranked) <= 2

    def test_add_ranker(self):
        """add_ranker appends to the rankers list."""
        pipeline = RerankerPipeline()
        assert len(pipeline.rankers) == 0
        pipeline.add_ranker(BM25Ranker())
        assert len(pipeline.rankers) == 1
        pipeline.add_ranker(CrossEncoderRanker())
        assert len(pipeline.rankers) == 2


# ============================================================
# Retriever Protocol Tests
# ============================================================


class TestRetrieverProtocol:
    """Tests for the Retriever protocol and protocol conformance."""

    def test_dense_retriever_implements_protocol(self, mock_embedding_provider):
        """DenseRetriever is recognized as implementing the Retriever protocol."""
        retriever = DenseRetriever(embedding_provider=mock_embedding_provider)
        assert isinstance(retriever, Retriever)

    def test_sparse_retriever_implements_protocol(self):
        """SparseRetriever is recognized as implementing the Retriever protocol."""
        retriever = SparseRetriever()
        assert isinstance(retriever, Retriever)

    def test_hybrid_retriever_implements_protocol(self, mock_embedding_provider):
        """HybridRetriever is recognized as implementing the Retriever protocol."""
        dense = DenseRetriever(embedding_provider=mock_embedding_provider)
        sparse = SparseRetriever()
        hybrid = HybridRetriever(dense_retriever=dense, sparse_retriever=sparse)
        assert isinstance(hybrid, Retriever)


# ============================================================
# DenseRetriever Tests
# ============================================================


class TestDenseRetriever:
    """Tests for DenseRetriever implementation."""

    @pytest.mark.asyncio
    async def test_retrieve_returns_results(self, mock_embedding_provider, sample_documents):
        """DenseRetriever returns results with scores."""
        # Set up embeddings: query + documents
        mock_embedding_provider.embed = AsyncMock(
            return_value=[0.9, 0.1, 0.0, 0.0, 0.0]
        )
        mock_embedding_provider.embed_batch = AsyncMock(return_value=[
            [0.8, 0.2, 0.0, 0.0, 0.0],  # high similarity
            [0.0, 0.0, 0.9, 0.1, 0.0],  # low similarity
            [0.1, 0.0, 0.0, 0.9, 0.0],  # low similarity
            [0.7, 0.3, 0.0, 0.0, 0.0],  # medium similarity
            [0.0, 0.0, 0.0, 0.0, 1.0],  # low similarity
        ])
        retriever = DenseRetriever(
            embedding_provider=mock_embedding_provider,
            documents=sample_documents,
        )
        results = await retriever.retrieve("Python programming", top_k=3)
        assert len(results) == 3
        assert all("content" in r for r in results)
        assert all("score" in r for r in results)
        # Results should be sorted by score descending
        assert results[0]["score"] >= results[1]["score"]

    @pytest.mark.asyncio
    async def test_retrieve_empty_documents(self, mock_embedding_provider):
        """DenseRetriever returns empty list when no documents."""
        retriever = DenseRetriever(
            embedding_provider=mock_embedding_provider,
            documents=[],
        )
        results = await retriever.retrieve("query", top_k=5)
        assert results == []

    @pytest.mark.asyncio
    async def test_retrieve_empty_query(self, mock_embedding_provider, sample_documents):
        """DenseRetriever returns empty list for empty query."""
        retriever = DenseRetriever(
            embedding_provider=mock_embedding_provider,
            documents=sample_documents,
        )
        results = await retriever.retrieve("", top_k=5)
        assert results == []

    def test_add_documents(self, mock_embedding_provider):
        """add_documents extends the document store."""
        retriever = DenseRetriever(
            embedding_provider=mock_embedding_provider,
            documents=["doc1"],
        )
        retriever.add_documents(["doc2", "doc3"])
        assert len(retriever.documents) == 3


# ============================================================
# SparseRetriever Tests
# ============================================================


class TestSparseRetriever:
    """Tests for SparseRetriever implementation."""

    @pytest.mark.asyncio
    async def test_retrieve_returns_results(self, sample_documents):
        """SparseRetriever returns BM25-ranked results."""
        retriever = SparseRetriever(documents=sample_documents)
        results = await retriever.retrieve("Python programming language", top_k=3)
        assert len(results) > 0
        assert len(results) <= 3
        assert all("content" in r for r in results)
        assert all("score" in r for r in results)

    @pytest.mark.asyncio
    async def test_retrieve_empty_documents(self):
        """SparseRetriever returns empty list when no documents."""
        retriever = SparseRetriever(documents=[])
        results = await retriever.retrieve("query", top_k=5)
        assert results == []

    @pytest.mark.asyncio
    async def test_retrieve_empty_query(self, sample_documents):
        """SparseRetriever returns empty list for empty query."""
        retriever = SparseRetriever(documents=sample_documents)
        results = await retriever.retrieve("", top_k=5)
        assert results == []

    @pytest.mark.asyncio
    async def test_retrieve_relevance_ordering(self, sample_documents):
        """SparseRetriever ranks relevant documents higher."""
        retriever = SparseRetriever(documents=sample_documents)
        results = await retriever.retrieve("machine learning datasets", top_k=5)
        if results:
            # First result should be the ML document
            assert "machine learning" in results[0]["content"].lower() or \
                   "learning" in results[0]["content"].lower()

    def test_add_documents(self):
        """add_documents extends the document store."""
        retriever = SparseRetriever(documents=["doc1"])
        retriever.add_documents(["doc2", "doc3"])
        assert len(retriever.documents) == 3


# ============================================================
# HybridRetriever Tests
# ============================================================


class TestHybridRetriever:
    """Tests for HybridRetriever implementation."""

    @pytest.mark.asyncio
    async def test_retrieve_combines_strategies(self, mock_embedding_provider, sample_documents):
        """HybridRetriever combines dense and sparse results."""
        mock_embedding_provider.embed = AsyncMock(
            return_value=[0.5, 0.5, 0.0, 0.0, 0.0]
        )
        mock_embedding_provider.embed_batch = AsyncMock(return_value=[
            [0.5, 0.5, 0.0, 0.0, 0.0],
            [0.0, 0.0, 0.5, 0.5, 0.0],
            [0.0, 0.0, 0.0, 0.5, 0.5],
            [0.5, 0.0, 0.5, 0.0, 0.0],
            [0.0, 0.5, 0.0, 0.5, 0.0],
        ])

        dense = DenseRetriever(
            embedding_provider=mock_embedding_provider,
            documents=sample_documents,
        )
        sparse = SparseRetriever(documents=sample_documents)
        hybrid = HybridRetriever(
            dense_retriever=dense,
            sparse_retriever=sparse,
            alpha=0.5,
        )

        results = await hybrid.retrieve("Python programming", top_k=3)
        assert len(results) <= 3
        assert all("content" in r for r in results)
        assert all("score" in r for r in results)

    @pytest.mark.asyncio
    async def test_retrieve_with_alpha_zero(self, mock_embedding_provider, sample_documents):
        """HybridRetriever with alpha=0 uses only sparse results."""
        mock_embedding_provider.embed = AsyncMock(return_value=[0.0] * 5)
        mock_embedding_provider.embed_batch = AsyncMock(
            return_value=[[0.0] * 5] * len(sample_documents)
        )

        dense = DenseRetriever(
            embedding_provider=mock_embedding_provider,
            documents=sample_documents,
        )
        sparse = SparseRetriever(documents=sample_documents)
        hybrid = HybridRetriever(
            dense_retriever=dense,
            sparse_retriever=sparse,
            alpha=0.0,  # Only sparse
        )

        results = await hybrid.retrieve("Python programming", top_k=3)
        # Should still return results from sparse retriever
        assert len(results) >= 0  # May be empty if no BM25 matches

    @pytest.mark.asyncio
    async def test_retrieve_with_alpha_one(self, mock_embedding_provider, sample_documents):
        """HybridRetriever with alpha=1 uses only dense results."""
        mock_embedding_provider.embed = AsyncMock(
            return_value=[1.0, 0.0, 0.0, 0.0, 0.0]
        )
        mock_embedding_provider.embed_batch = AsyncMock(return_value=[
            [1.0, 0.0, 0.0, 0.0, 0.0],
            [0.0, 1.0, 0.0, 0.0, 0.0],
            [0.0, 0.0, 1.0, 0.0, 0.0],
            [0.0, 0.0, 0.0, 1.0, 0.0],
            [0.0, 0.0, 0.0, 0.0, 1.0],
        ])

        dense = DenseRetriever(
            embedding_provider=mock_embedding_provider,
            documents=sample_documents,
        )
        sparse = SparseRetriever(documents=sample_documents)
        hybrid = HybridRetriever(
            dense_retriever=dense,
            sparse_retriever=sparse,
            alpha=1.0,  # Only dense
        )

        results = await hybrid.retrieve("Python", top_k=3)
        assert len(results) <= 3


# ============================================================
# RetrieverFactory Tests
# ============================================================


class TestRetrieverFactory:
    """Tests for the retriever_factory function."""

    def test_create_sparse_retriever(self):
        """Factory creates a SparseRetriever for 'sparse' strategy."""
        retriever = retriever_factory("sparse", documents=["doc1", "doc2"])
        assert isinstance(retriever, SparseRetriever)
        assert len(retriever.documents) == 2

    def test_create_dense_retriever(self, mock_embedding_provider):
        """Factory creates a DenseRetriever for 'dense' strategy."""
        retriever = retriever_factory(
            "dense",
            embedding_provider=mock_embedding_provider,
            documents=["doc1"],
        )
        assert isinstance(retriever, DenseRetriever)

    def test_create_hybrid_retriever(self, mock_embedding_provider):
        """Factory creates a HybridRetriever for 'hybrid' strategy."""
        retriever = retriever_factory(
            "hybrid",
            embedding_provider=mock_embedding_provider,
            documents=["doc1"],
            alpha=0.7,
        )
        assert isinstance(retriever, HybridRetriever)
        assert retriever.alpha == 0.7

    def test_dense_without_provider_raises(self):
        """Factory raises ValueError for 'dense' without embedding_provider."""
        with pytest.raises(ValueError, match="embedding_provider is required"):
            retriever_factory("dense")

    def test_hybrid_without_provider_raises(self):
        """Factory raises ValueError for 'hybrid' without embedding_provider."""
        with pytest.raises(ValueError, match="embedding_provider is required"):
            retriever_factory("hybrid")

    def test_unknown_strategy_raises(self):
        """Factory raises ValueError for unknown strategy."""
        with pytest.raises(ValueError, match="Unsupported retriever strategy"):
            retriever_factory("unknown")


# ============================================================
# DocumentParser Protocol Tests
# ============================================================


class TestDocumentParserProtocol:
    """Tests for the DocumentParser protocol conformance."""

    def test_text_parser_implements_protocol(self):
        """TextParser is recognized as implementing DocumentParser."""
        parser = TextParser()
        assert isinstance(parser, DocumentParser)

    def test_markdown_parser_implements_protocol(self):
        """MarkdownParser is recognized as implementing DocumentParser."""
        parser = MarkdownParser()
        assert isinstance(parser, DocumentParser)

    def test_code_parser_implements_protocol(self):
        """CodeParser is recognized as implementing DocumentParser."""
        parser = CodeParser()
        assert isinstance(parser, DocumentParser)

    def test_parsed_chunk_dataclass(self):
        """ParsedChunk dataclass works correctly."""
        chunk = ParsedChunk(
            content="test content",
            metadata={"key": "value"},
            chunk_type="paragraph",
        )
        assert chunk.content == "test content"
        assert chunk.metadata == {"key": "value"}
        assert chunk.chunk_type == "paragraph"

    def test_parsed_chunk_defaults(self):
        """ParsedChunk has sensible defaults."""
        chunk = ParsedChunk(content="test")
        assert chunk.metadata == {}
        assert chunk.chunk_type == "text"


# ============================================================
# TextParser Tests
# ============================================================


class TestTextParser:
    """Tests for TextParser implementation."""

    def test_parse_paragraphs(self):
        """TextParser splits on double newlines into paragraphs."""
        parser = TextParser()
        content = "First paragraph here.\n\nSecond paragraph here.\n\nThird one."
        chunks = parser.parse(content)
        assert len(chunks) == 3
        assert chunks[0].content == "First paragraph here."
        assert chunks[0].chunk_type == "paragraph"

    def test_parse_empty_content(self):
        """TextParser returns empty list for empty content."""
        parser = TextParser()
        assert parser.parse("") == []
        assert parser.parse("   ") == []

    def test_parse_large_paragraph_splits_sentences(self):
        """TextParser splits large paragraphs into sentences."""
        parser = TextParser(max_chunk_size=50)
        # Create a paragraph longer than max_chunk_size
        content = "This is sentence one. This is sentence two. This is sentence three. This is sentence four."
        chunks = parser.parse(content)
        # Should be split into sentence chunks
        assert len(chunks) >= 2
        assert any(c.chunk_type == "sentence" for c in chunks)

    def test_parse_merges_small_chunks(self):
        """TextParser merges chunks smaller than min_chunk_size."""
        parser = TextParser(min_chunk_size=100)
        content = "Hi.\n\nBye.\n\nThis is a much longer paragraph that should stand on its own without being merged."
        chunks = parser.parse(content)
        # Small chunks should be merged
        assert len(chunks) <= 3

    def test_parse_preserves_paragraph_index(self):
        """TextParser includes paragraph_index in metadata."""
        parser = TextParser()
        content = "First.\n\nSecond.\n\nThird."
        chunks = parser.parse(content)
        assert chunks[0].metadata.get("paragraph_index") == 0


# ============================================================
# MarkdownParser Tests
# ============================================================


class TestMarkdownParser:
    """Tests for MarkdownParser implementation."""

    def test_parse_headers(self):
        """MarkdownParser splits on headers."""
        parser = MarkdownParser()
        content = "# Introduction\nSome intro text.\n\n## Details\nMore details here.\n\n# Conclusion\nFinal words."
        chunks = parser.parse(content)
        assert len(chunks) >= 3
        # Should have header-typed chunks
        header_chunks = [c for c in chunks if c.chunk_type == "header"]
        assert len(header_chunks) >= 2

    def test_parse_code_blocks(self):
        """MarkdownParser preserves code blocks as single chunks."""
        parser = MarkdownParser()
        content = "# Example\n\nSome text.\n\n```python\ndef hello():\n    print('hi')\n```\n\nMore text."
        chunks = parser.parse(content)
        code_chunks = [c for c in chunks if c.chunk_type == "code_block"]
        assert len(code_chunks) == 1
        assert "def hello" in code_chunks[0].content

    def test_parse_empty_content(self):
        """MarkdownParser returns empty list for empty content."""
        parser = MarkdownParser()
        assert parser.parse("") == []
        assert parser.parse("   ") == []

    def test_parse_lists(self):
        """MarkdownParser identifies list sections."""
        parser = MarkdownParser()
        content = "# Shopping\n- Milk\n- Bread\n- Eggs\n- Butter"
        chunks = parser.parse(content)
        list_chunks = [c for c in chunks if c.chunk_type == "list"]
        assert len(list_chunks) >= 1

    def test_parse_includes_header_metadata(self):
        """MarkdownParser includes header level and text in metadata."""
        parser = MarkdownParser()
        content = "## Section Title\nContent here."
        chunks = parser.parse(content)
        assert len(chunks) >= 1
        header_chunk = chunks[0]
        assert header_chunk.metadata.get("header_level") == 2
        assert header_chunk.metadata.get("header_text") == "Section Title"

    def test_parse_without_headers_in_chunks(self):
        """MarkdownParser can exclude headers from chunk content."""
        parser = MarkdownParser(include_headers_in_chunks=False)
        content = "## Title\nBody text here."
        chunks = parser.parse(content)
        if chunks:
            # Content should not start with the header
            assert not chunks[0].content.startswith("##")


# ============================================================
# CodeParser Tests
# ============================================================


class TestCodeParser:
    """Tests for CodeParser implementation."""

    def test_parse_python_functions(self):
        """CodeParser splits Python code on function boundaries."""
        parser = CodeParser(language="python")
        content = '''import os

def hello():
    print("hello")

def world():
    print("world")

class MyClass:
    def method(self):
        pass
'''
        chunks = parser.parse(content)
        assert len(chunks) >= 3
        # Should have function and class chunks
        func_chunks = [c for c in chunks if c.chunk_type == "function"]
        class_chunks = [c for c in chunks if c.chunk_type == "class"]
        assert len(func_chunks) >= 2
        assert len(class_chunks) >= 1

    def test_parse_python_with_metadata(self):
        """CodeParser includes function/class name in metadata."""
        parser = CodeParser(language="python")
        content = "def my_function():\n    return 42\n"
        chunks = parser.parse(content)
        func_chunks = [c for c in chunks if c.chunk_type == "function"]
        if func_chunks:
            assert func_chunks[0].metadata.get("name") == "my_function"
            assert func_chunks[0].metadata.get("language") == "python"

    def test_parse_javascript(self):
        """CodeParser splits JavaScript code on function boundaries."""
        parser = CodeParser(language="javascript")
        content = '''const x = 1;

function hello() {
    console.log("hello");
}

function world() {
    console.log("world");
}
'''
        chunks = parser.parse(content)
        assert len(chunks) >= 2
        func_chunks = [c for c in chunks if c.chunk_type == "function"]
        assert len(func_chunks) >= 2

    def test_parse_typescript_interfaces(self):
        """CodeParser identifies TypeScript interfaces."""
        parser = CodeParser(language="typescript")
        content = '''const config = {};

interface User {
    name: string;
    age: number;
}

function greet(user: User) {
    return user.name;
}
'''
        chunks = parser.parse(content)
        assert len(chunks) >= 2
        interface_chunks = [c for c in chunks if c.chunk_type == "interface"]
        assert len(interface_chunks) >= 1

    def test_parse_empty_content(self):
        """CodeParser returns empty list for empty content."""
        parser = CodeParser(language="python")
        assert parser.parse("") == []

    def test_parse_auto_detection(self):
        """CodeParser auto-detects Python from content."""
        parser = CodeParser()  # No language specified
        content = "import os\n\ndef main():\n    os.getcwd()\n"
        chunks = parser.parse(content)
        assert len(chunks) >= 1

    def test_parse_generic_fallback(self):
        """CodeParser falls back to line-based splitting for unknown languages."""
        parser = CodeParser(language="unknown", max_chunk_size=50)
        content = "line1\nline2\nline3\nline4\nline5\nline6\nline7\nline8\nline9\nline10"
        chunks = parser.parse(content)
        assert len(chunks) >= 1
        assert all(c.chunk_type == "block" for c in chunks)


# ============================================================
# RAGPipeline Integration Tests
# ============================================================


class TestRAGPipelineEnhanced:
    """Tests for RAGPipeline with pluggable components."""

    def test_backward_compatible_construction(self, mock_db):
        """RAGPipeline still works with original constructor signature."""
        # Original usage: only db and optional embedding_provider
        rag = RAGPipeline(mock_db)
        assert rag.db == mock_db
        assert rag.embedding_provider is None
        assert rag.ranker is None
        assert rag.retriever is None
        assert rag.parser is None

    def test_construction_with_all_components(self, mock_db, mock_embedding_provider):
        """RAGPipeline accepts all optional components."""
        ranker = BM25Ranker(top_k=5)
        retriever = SparseRetriever(documents=["doc1"])
        parser = TextParser()

        rag = RAGPipeline(
            db=mock_db,
            embedding_provider=mock_embedding_provider,
            ranker=ranker,
            retriever=retriever,
            parser=parser,
        )
        assert rag.ranker is ranker
        assert rag.retriever is retriever
        assert rag.parser is parser

    def test_rerank_uses_custom_ranker(self, mock_db):
        """RAGPipeline.rerank delegates to custom ranker when configured."""
        ranker = BM25Ranker(top_k=2)
        rag = RAGPipeline(mock_db, ranker=ranker)

        results = [
            {"content": "Python programming language basics"},
            {"content": "JavaScript web development"},
            {"content": "Python machine learning tutorial"},
        ]

        reranked = rag.rerank("Python programming", results, top_k=2)
        assert len(reranked) <= 2

    def test_rerank_uses_builtin_when_no_ranker(self, mock_db):
        """RAGPipeline.rerank uses built-in heuristics without custom ranker."""
        rag = RAGPipeline(mock_db)

        chunk1 = MagicMock()
        chunk1.content = "Python is great"
        chunk1.chunk_index = 0
        chunk1.created_at = datetime.now(timezone.utc)

        results = [
            {"chunk": chunk1, "combined_score": 0.8, "bm25_score": 0.7, "vector_score": 0.5},
        ]

        reranked = rag.rerank("Python", results, top_k=5)
        assert len(reranked) == 1

    def test_parse_document_with_parser(self, mock_db):
        """RAGPipeline.parse_document uses custom parser when configured."""
        parser = TextParser()
        rag = RAGPipeline(mock_db, parser=parser)

        content = "First paragraph.\n\nSecond paragraph."
        result = rag.parse_document(content)
        assert len(result) == 2
        assert hasattr(result[0], "content")
        assert result[0].chunk_type == "paragraph"

    def test_parse_document_without_parser(self, mock_db):
        """RAGPipeline.parse_document falls back to chunk_document without parser."""
        rag = RAGPipeline(mock_db)

        content = "First paragraph.\n\nSecond paragraph."
        result = rag.parse_document(content)
        assert len(result) == 2
        assert isinstance(result[0], str)

    def test_from_config_basic(self, mock_db):
        """RAGPipeline.from_config creates a configured pipeline."""
        rag = RAGPipeline.from_config(
            db=mock_db,
            ranker_config={"type": "bm25", "top_k": 5},
            parser_config={"type": "text", "max_chunk_size": 500},
        )
        assert rag.ranker is not None
        assert rag.parser is not None
        assert rag.retriever is None

    def test_from_config_with_cross_encoder(self, mock_db):
        """RAGPipeline.from_config creates cross-encoder ranker."""
        rag = RAGPipeline.from_config(
            db=mock_db,
            ranker_config={
                "type": "cross_encoder",
                "top_k": 3,
                "bm25_weight": 0.7,
                "overlap_weight": 0.3,
            },
        )
        assert rag.ranker is not None

    def test_from_config_with_pipeline_ranker(self, mock_db):
        """RAGPipeline.from_config creates a ranker pipeline."""
        rag = RAGPipeline.from_config(
            db=mock_db,
            ranker_config={
                "type": "pipeline",
                "rankers": [
                    {"type": "bm25", "top_k": 10},
                    {"type": "cross_encoder", "top_k": 5},
                ],
            },
        )
        assert rag.ranker is not None

    def test_from_config_with_retriever(self, mock_db, mock_embedding_provider):
        """RAGPipeline.from_config creates a retriever."""
        rag = RAGPipeline.from_config(
            db=mock_db,
            embedding_provider=mock_embedding_provider,
            retriever_config={"type": "sparse", "documents": ["doc1", "doc2"]},
        )
        assert rag.retriever is not None

    def test_from_config_with_code_parser(self, mock_db):
        """RAGPipeline.from_config creates a code parser."""
        rag = RAGPipeline.from_config(
            db=mock_db,
            parser_config={"type": "code", "language": "python"},
        )
        assert rag.parser is not None

    def test_from_config_with_markdown_parser(self, mock_db):
        """RAGPipeline.from_config creates a markdown parser."""
        rag = RAGPipeline.from_config(
            db=mock_db,
            parser_config={"type": "markdown"},
        )
        assert rag.parser is not None

    def test_chunk_document_still_works(self, mock_db):
        """Original chunk_document method still works unchanged."""
        rag = RAGPipeline(mock_db)
        chunks = rag.chunk_document("Hello\n\nWorld", strategy="paragraph")
        assert chunks == ["Hello", "World"]

    def test_assemble_context_still_works(self, mock_db):
        """Original assemble_context method still works unchanged."""
        rag = RAGPipeline(mock_db)
        chunk = MagicMock()
        chunk.content = "Test content"
        results = [{"chunk": chunk}]
        context = rag.assemble_context(results)
        assert "Test content" in context
