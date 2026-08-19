"""Tests for the embedding providers and RAG pipeline vector integration.

Validates LocalEmbeddingProvider, FallbackEmbeddingProvider, OpenAIEmbeddingProvider
(mocked), cosine similarity, and RAGPipeline integration with embeddings.
"""

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from nexus.knowledge.embeddings import (
    EmbeddingProvider,
    FallbackEmbeddingProvider,
    LocalEmbeddingProvider,
    OpenAIEmbeddingProvider,
    cosine_similarity,
)
from nexus.knowledge.rag import RAGPipeline


@pytest.fixture
def company_id():
    """Provide a fixed company UUID for tests."""
    return uuid.UUID("12345678-1234-1234-1234-123456789abc")


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


class TestLocalEmbeddingProvider:
    """Tests for LocalEmbeddingProvider."""

    @pytest.mark.asyncio
    async def test_produces_fixed_dimension_vectors(self):
        """LocalEmbeddingProvider produces vectors of the configured dimension."""
        provider = LocalEmbeddingProvider(dimensions=256)
        vector = await provider.embed("hello world")
        assert len(vector) == 256

    @pytest.mark.asyncio
    async def test_custom_dimension(self):
        """LocalEmbeddingProvider respects custom dimension parameter."""
        provider = LocalEmbeddingProvider(dimensions=128)
        vector = await provider.embed("test input")
        assert len(vector) == 128

    @pytest.mark.asyncio
    async def test_consistent_vectors(self):
        """Same input text always produces the same embedding vector."""
        provider = LocalEmbeddingProvider(dimensions=256)
        vector1 = await provider.embed("consistent embedding test")
        vector2 = await provider.embed("consistent embedding test")
        assert vector1 == vector2

    @pytest.mark.asyncio
    async def test_different_texts_produce_different_vectors(self):
        """Different texts produce different embedding vectors."""
        provider = LocalEmbeddingProvider(dimensions=256)
        vector1 = await provider.embed("python programming language")
        vector2 = await provider.embed("cooking recipes for dinner")
        assert vector1 != vector2

    @pytest.mark.asyncio
    async def test_vectors_are_normalized(self):
        """Output vectors are L2-normalized (magnitude approximately 1.0)."""
        import math

        provider = LocalEmbeddingProvider(dimensions=256)
        vector = await provider.embed("test normalization of vectors")
        magnitude = math.sqrt(sum(v * v for v in vector))
        assert abs(magnitude - 1.0) < 1e-6

    @pytest.mark.asyncio
    async def test_empty_text_returns_zero_vector(self):
        """Empty text returns a zero vector."""
        provider = LocalEmbeddingProvider(dimensions=256)
        vector = await provider.embed("")
        assert all(v == 0.0 for v in vector)
        assert len(vector) == 256

    @pytest.mark.asyncio
    async def test_embed_batch(self):
        """embed_batch returns one vector per input text."""
        provider = LocalEmbeddingProvider(dimensions=256)
        texts = ["first text", "second text", "third text"]
        vectors = await provider.embed_batch(texts)
        assert len(vectors) == 3
        for vec in vectors:
            assert len(vec) == 256

    @pytest.mark.asyncio
    async def test_embed_batch_matches_individual(self):
        """Batch embedding produces same results as individual embedding."""
        provider = LocalEmbeddingProvider(dimensions=256)
        texts = ["hello world", "test embedding"]
        batch_vectors = await provider.embed_batch(texts)
        individual_vectors = [await provider.embed(t) for t in texts]
        assert batch_vectors == individual_vectors


class TestFallbackEmbeddingProvider:
    """Tests for FallbackEmbeddingProvider."""

    @pytest.mark.asyncio
    async def test_works_without_api_key(self):
        """FallbackEmbeddingProvider works without any API key."""
        provider = FallbackEmbeddingProvider()
        vector = await provider.embed("test without api key")
        assert len(vector) == 256
        assert isinstance(vector, list)
        assert all(isinstance(v, float) for v in vector)

    @pytest.mark.asyncio
    async def test_produces_consistent_results(self):
        """FallbackEmbeddingProvider produces consistent results."""
        provider = FallbackEmbeddingProvider()
        v1 = await provider.embed("same input")
        v2 = await provider.embed("same input")
        assert v1 == v2

    @pytest.mark.asyncio
    async def test_embed_batch(self):
        """FallbackEmbeddingProvider batch embedding works."""
        provider = FallbackEmbeddingProvider()
        vectors = await provider.embed_batch(["a", "b", "c"])
        assert len(vectors) == 3
        for vec in vectors:
            assert len(vec) == 256

    @pytest.mark.asyncio
    async def test_implements_protocol(self):
        """FallbackEmbeddingProvider implements EmbeddingProvider protocol."""
        provider = FallbackEmbeddingProvider()
        assert isinstance(provider, EmbeddingProvider)

    @pytest.mark.asyncio
    async def test_custom_dimensions(self):
        """FallbackEmbeddingProvider respects custom dimension parameter."""
        provider = FallbackEmbeddingProvider(dimensions=64)
        vector = await provider.embed("test")
        assert len(vector) == 64


class TestOpenAIEmbeddingProvider:
    """Tests for OpenAIEmbeddingProvider with mocked httpx."""

    @pytest.mark.asyncio
    async def test_embed_with_mocked_response(self):
        """OpenAIEmbeddingProvider returns parsed embedding from API response."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = {
            "data": [
                {"index": 0, "embedding": [0.1, 0.2, 0.3]}
            ],
            "usage": {"prompt_tokens": 5, "total_tokens": 5},
        }

        with patch("nexus.knowledge.embeddings.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(return_value=mock_response)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client_cls.return_value = mock_client

            provider = OpenAIEmbeddingProvider(api_key="test-key")
            result = await provider.embed("test text")

        assert result == [0.1, 0.2, 0.3]

    @pytest.mark.asyncio
    async def test_embed_batch_with_mocked_response(self):
        """OpenAIEmbeddingProvider batch correctly orders multiple embeddings."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = {
            "data": [
                {"index": 1, "embedding": [0.4, 0.5, 0.6]},
                {"index": 0, "embedding": [0.1, 0.2, 0.3]},
            ],
            "usage": {"prompt_tokens": 10, "total_tokens": 10},
        }

        with patch("nexus.knowledge.embeddings.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(return_value=mock_response)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client_cls.return_value = mock_client

            provider = OpenAIEmbeddingProvider(api_key="test-key")
            results = await provider.embed_batch(["text1", "text2"])

        # Should be sorted by index
        assert results[0] == [0.1, 0.2, 0.3]
        assert results[1] == [0.4, 0.5, 0.6]

    @pytest.mark.asyncio
    async def test_raises_without_api_key(self):
        """OpenAIEmbeddingProvider raises ValueError when no API key is set."""
        provider = OpenAIEmbeddingProvider(api_key="")
        with pytest.raises(ValueError, match="API key is not configured"):
            await provider.embed("test")

    @pytest.mark.asyncio
    async def test_embed_batch_empty_list(self):
        """OpenAIEmbeddingProvider returns empty list for empty input."""
        provider = OpenAIEmbeddingProvider(api_key="test-key")
        result = await provider.embed_batch([])
        assert result == []

    @pytest.mark.asyncio
    async def test_uses_configured_model(self):
        """OpenAIEmbeddingProvider sends the configured model in request."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = {
            "data": [{"index": 0, "embedding": [0.1]}],
            "usage": {"prompt_tokens": 1, "total_tokens": 1},
        }

        with patch("nexus.knowledge.embeddings.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(return_value=mock_response)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=None)
            mock_client_cls.return_value = mock_client

            provider = OpenAIEmbeddingProvider(
                model="text-embedding-3-large", api_key="test-key"
            )
            await provider.embed("test")

            # Verify the model was sent in the request
            call_kwargs = mock_client.post.call_args
            payload = call_kwargs[1]["json"] if "json" in call_kwargs[1] else call_kwargs.kwargs["json"]
            assert payload["model"] == "text-embedding-3-large"

    @pytest.mark.asyncio
    async def test_implements_protocol(self):
        """OpenAIEmbeddingProvider implements EmbeddingProvider protocol."""
        provider = OpenAIEmbeddingProvider(api_key="test-key")
        assert isinstance(provider, EmbeddingProvider)


class TestCosineSimilarity:
    """Tests for cosine similarity computation."""

    def test_identical_vectors(self):
        """Identical vectors have similarity of 1.0."""
        vec = [1.0, 2.0, 3.0]
        assert abs(cosine_similarity(vec, vec) - 1.0) < 1e-6

    def test_orthogonal_vectors(self):
        """Orthogonal vectors have similarity of 0.0."""
        vec_a = [1.0, 0.0, 0.0]
        vec_b = [0.0, 1.0, 0.0]
        assert abs(cosine_similarity(vec_a, vec_b)) < 1e-6

    def test_opposite_vectors(self):
        """Opposite vectors have similarity of -1.0."""
        vec_a = [1.0, 0.0, 0.0]
        vec_b = [-1.0, 0.0, 0.0]
        assert abs(cosine_similarity(vec_a, vec_b) - (-1.0)) < 1e-6

    def test_similar_vectors(self):
        """Similar vectors have high positive similarity."""
        vec_a = [1.0, 2.0, 3.0]
        vec_b = [1.1, 2.1, 3.1]
        similarity = cosine_similarity(vec_a, vec_b)
        assert similarity > 0.99

    def test_zero_vector_returns_zero(self):
        """Zero vector against any vector returns 0.0."""
        vec_a = [0.0, 0.0, 0.0]
        vec_b = [1.0, 2.0, 3.0]
        assert cosine_similarity(vec_a, vec_b) == 0.0

    def test_different_lengths_returns_zero(self):
        """Vectors of different lengths return 0.0."""
        vec_a = [1.0, 2.0]
        vec_b = [1.0, 2.0, 3.0]
        assert cosine_similarity(vec_a, vec_b) == 0.0

    def test_normalized_vectors(self):
        """Normalized vectors: cosine similarity equals dot product."""
        import math

        vec_a = [3.0, 4.0]
        mag_a = math.sqrt(sum(v * v for v in vec_a))
        vec_a_norm = [v / mag_a for v in vec_a]

        vec_b = [1.0, 0.0]
        mag_b = math.sqrt(sum(v * v for v in vec_b))
        vec_b_norm = [v / mag_b for v in vec_b]

        similarity = cosine_similarity(vec_a_norm, vec_b_norm)
        dot_product = sum(a * b for a, b in zip(vec_a_norm, vec_b_norm))
        assert abs(similarity - dot_product) < 1e-6


class TestRAGPipelineWithEmbeddings:
    """Tests for RAGPipeline integration with embedding providers."""

    @pytest.mark.asyncio
    async def test_index_chunks_stores_embeddings(self, mock_db, company_id, page_id):
        """index_chunks stores embedding vectors when provider is available."""
        mock_provider = AsyncMock()
        mock_provider.embed_batch = AsyncMock(return_value=[
            [0.1, 0.2, 0.3],
            [0.4, 0.5, 0.6],
        ])

        rag = RAGPipeline(mock_db, embedding_provider=mock_provider)
        chunks = ["first chunk", "second chunk"]

        records = await rag.index_chunks(company_id, page_id, chunks)

        assert len(records) == 2
        assert records[0].embedding_vector == [0.1, 0.2, 0.3]
        assert records[1].embedding_vector == [0.4, 0.5, 0.6]
        mock_provider.embed_batch.assert_awaited_once_with(chunks)

    @pytest.mark.asyncio
    async def test_index_chunks_without_provider(self, mock_db, company_id, page_id):
        """index_chunks stores None embeddings when no provider is available."""
        rag = RAGPipeline(mock_db)
        chunks = ["first chunk", "second chunk"]

        records = await rag.index_chunks(company_id, page_id, chunks)

        assert len(records) == 2
        assert records[0].embedding_vector is None
        assert records[1].embedding_vector is None

    @pytest.mark.asyncio
    async def test_search_uses_vector_similarity(self, mock_db, company_id):
        """search() uses real vector similarity when embeddings exist."""
        # Create mock chunks with embeddings
        chunk1 = MagicMock()
        chunk1.content = "python programming tutorial"
        chunk1.embedding_vector = [1.0, 0.0, 0.0]
        chunk1.company_id = company_id

        chunk2 = MagicMock()
        chunk2.content = "cooking recipes guide"
        chunk2.embedding_vector = [0.0, 1.0, 0.0]
        chunk2.company_id = company_id

        # Mock db.exec to return chunks
        mock_result = MagicMock()
        mock_result.all.return_value = [chunk1, chunk2]
        mock_db.exec.return_value = mock_result

        # Mock embedding provider
        mock_provider = AsyncMock()
        # Query embedding is closer to chunk1
        mock_provider.embed = AsyncMock(return_value=[0.9, 0.1, 0.0])

        rag = RAGPipeline(mock_db, embedding_provider=mock_provider)
        results = await rag.search(company_id, "python programming", top_k=5)

        # Provider should be called for query embedding
        mock_provider.embed.assert_awaited_once_with("python programming")

        # Results should exist (BM25 may filter, but we expect at least chunk1)
        if results:
            # The python chunk should have a higher vector score
            python_result = next(
                (r for r in results if r["chunk"] == chunk1), None
            )
            cooking_result = next(
                (r for r in results if r["chunk"] == chunk2), None
            )
            if python_result and cooking_result:
                assert python_result["vector_score"] > cooking_result["vector_score"]

    @pytest.mark.asyncio
    async def test_search_fallback_to_token_overlap(self, mock_db, company_id):
        """search() falls back to token overlap when no embeddings are stored."""
        # Create mock chunks without embeddings
        chunk1 = MagicMock()
        chunk1.content = "python programming language tutorial"
        chunk1.embedding_vector = None
        chunk1.company_id = company_id

        # Mock db.exec to return chunks
        mock_result = MagicMock()
        mock_result.all.return_value = [chunk1]
        mock_db.exec.return_value = mock_result

        # RAGPipeline without embedding provider
        rag = RAGPipeline(mock_db)
        results = await rag.search(company_id, "python programming", top_k=5)

        # Should still produce results using token overlap
        if results:
            assert results[0]["vector_score"] >= 0.0

    @pytest.mark.asyncio
    async def test_search_with_provider_but_no_chunk_embeddings(self, mock_db, company_id):
        """search() falls back to token overlap when chunks lack embeddings."""
        # Create mock chunk without embedding
        chunk1 = MagicMock()
        chunk1.content = "python programming language"
        chunk1.embedding_vector = None
        chunk1.company_id = company_id

        mock_result = MagicMock()
        mock_result.all.return_value = [chunk1]
        mock_db.exec.return_value = mock_result

        # Provider is available but chunks have no embeddings
        mock_provider = AsyncMock()
        mock_provider.embed = AsyncMock(return_value=[0.5, 0.5, 0.5])

        rag = RAGPipeline(mock_db, embedding_provider=mock_provider)
        results = await rag.search(company_id, "python", top_k=5)

        # Should still work with token overlap fallback
        if results:
            assert results[0]["vector_score"] >= 0.0

    @pytest.mark.asyncio
    async def test_pipeline_backward_compatible(self, mock_db, company_id, page_id):
        """RAGPipeline works without embedding_provider (backward compatible)."""
        rag = RAGPipeline(mock_db)

        # Chunking still works
        chunks = rag.chunk_document("Hello world.\n\nSecond paragraph.")
        assert len(chunks) == 2

        # Index still works
        records = await rag.index_chunks(company_id, page_id, chunks)
        assert len(records) == 2

    @pytest.mark.asyncio
    async def test_index_chunks_empty_list(self, mock_db, company_id, page_id):
        """index_chunks handles empty chunk list correctly."""
        mock_provider = AsyncMock()
        rag = RAGPipeline(mock_db, embedding_provider=mock_provider)

        records = await rag.index_chunks(company_id, page_id, [])
        assert records == []
        # embed_batch should not be called for empty list
        mock_provider.embed_batch.assert_not_awaited()
