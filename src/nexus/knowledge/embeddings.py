"""Embedding providers for the RAG pipeline.

Provides a protocol for embedding providers and multiple implementations:
- OpenAIEmbeddingProvider: Uses OpenAI text-embedding-3-small via async httpx
- LocalEmbeddingProvider: Lightweight hash-based bag-of-words embeddings
- FallbackEmbeddingProvider: Zero-dependency fallback wrapping LocalEmbeddingProvider
"""

import hashlib
import math
from typing import Protocol, runtime_checkable

import httpx

from nexus.config import settings
from nexus.memory.retriever import tokenize


# Default embedding dimension for local provider
LOCAL_EMBEDDING_DIM = 256


@runtime_checkable
class EmbeddingProvider(Protocol):
    """Protocol defining the interface for embedding providers.

    All embedding providers must implement async embed() for single texts
    and async embed_batch() for multiple texts.
    """

    async def embed(self, text: str) -> list[float]:
        """Compute an embedding vector for a single text.

        Args:
            text: The input text to embed.

        Returns:
            A list of floats representing the embedding vector.
        """
        ...

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Compute embedding vectors for multiple texts.

        Args:
            texts: List of input texts to embed.

        Returns:
            List of embedding vectors, one per input text.
        """
        ...


class OpenAIEmbeddingProvider:
    """Embedding provider using the OpenAI text-embedding-3-small API.

    Communicates with the OpenAI embeddings endpoint via async httpx.
    Reads the API key from nexus.config.settings.openai_api_key.

    Attributes:
        model: The OpenAI embedding model name.
        api_key: The API key for authentication.
    """

    def __init__(self, model: str = "text-embedding-3-small", api_key: str | None = None) -> None:
        """Initialize the OpenAI embedding provider.

        Args:
            model: The embedding model to use. Defaults to text-embedding-3-small.
            api_key: Optional API key override. If None, reads from settings.
        """
        self.model = model
        self.api_key = api_key or settings.openai_api_key
        self._api_base = "https://api.openai.com/v1"

    async def embed(self, text: str) -> list[float]:
        """Compute an embedding vector for a single text via OpenAI API.

        Args:
            text: The input text to embed.

        Returns:
            Embedding vector as a list of floats.

        Raises:
            httpx.HTTPStatusError: If the API returns an error status.
            ValueError: If the API key is not configured.
        """
        if not self.api_key:
            raise ValueError("OpenAI API key is not configured")

        result = await self._call_api([text])
        return result[0]

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Compute embedding vectors for multiple texts via OpenAI API.

        Args:
            texts: List of input texts to embed.

        Returns:
            List of embedding vectors, one per input text.

        Raises:
            httpx.HTTPStatusError: If the API returns an error status.
            ValueError: If the API key is not configured.
        """
        if not self.api_key:
            raise ValueError("OpenAI API key is not configured")

        if not texts:
            return []

        return await self._call_api(texts)

    async def _call_api(self, texts: list[str]) -> list[list[float]]:
        """Make the actual API call to OpenAI embeddings endpoint.

        Args:
            texts: List of texts to embed.

        Returns:
            List of embedding vectors in input order.
        """
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self.model,
            "input": texts,
        }

        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(
                f"{self._api_base}/embeddings",
                json=payload,
                headers=headers,
            )
            response.raise_for_status()

        data = response.json()
        # Sort by index to ensure correct ordering
        embeddings_data = sorted(data["data"], key=lambda x: x["index"])
        return [item["embedding"] for item in embeddings_data]


class LocalEmbeddingProvider:
    """Lightweight local embedding provider using hash-based bag-of-words.

    Produces fixed-dimension vectors without any external dependencies.
    Uses token hashing to map tokens into a fixed-size vector space,
    producing consistent embeddings for the same input text.

    Attributes:
        dimensions: The fixed dimension of output vectors.
    """

    def __init__(self, dimensions: int = LOCAL_EMBEDDING_DIM) -> None:
        """Initialize the local embedding provider.

        Args:
            dimensions: The dimension of the output embedding vectors.
        """
        self.dimensions = dimensions

    async def embed(self, text: str) -> list[float]:
        """Compute a hash-based embedding vector for a single text.

        Tokenizes the text and maps each token to vector dimensions
        using a deterministic hash function, then normalizes the result.

        Args:
            text: The input text to embed.

        Returns:
            A normalized embedding vector of fixed dimension.
        """
        return self._compute_embedding(text)

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Compute hash-based embedding vectors for multiple texts.

        Args:
            texts: List of input texts to embed.

        Returns:
            List of normalized embedding vectors.
        """
        return [self._compute_embedding(text) for text in texts]

    def _compute_embedding(self, text: str) -> list[float]:
        """Compute a deterministic embedding vector from text.

        Uses MD5 hashing of each token to distribute contributions
        across vector dimensions. The result is L2-normalized.

        Args:
            text: Input text to embed.

        Returns:
            Normalized embedding vector.
        """
        vector = [0.0] * self.dimensions
        tokens = tokenize(text)

        if not tokens:
            return vector

        for token in tokens:
            # Use MD5 hash to get deterministic pseudo-random bytes
            token_hash = hashlib.md5(token.encode("utf-8")).hexdigest()
            # Map hash bytes to dimension indices and values
            for i in range(0, len(token_hash), 4):
                hex_chunk = token_hash[i:i + 4]
                dim_idx = int(hex_chunk[:2], 16) % self.dimensions
                value = (int(hex_chunk[2:4], 16) - 128) / 128.0
                vector[dim_idx] += value

        # L2 normalize the vector
        magnitude = math.sqrt(sum(v * v for v in vector))
        if magnitude > 0:
            vector = [v / magnitude for v in vector]

        return vector


class FallbackEmbeddingProvider:
    """Zero-dependency fallback embedding provider.

    Wraps LocalEmbeddingProvider to provide embeddings without any
    external API key or network access. Suitable for development,
    testing, and environments where no API key is available.

    Attributes:
        _local: The wrapped LocalEmbeddingProvider instance.
    """

    def __init__(self, dimensions: int = LOCAL_EMBEDDING_DIM) -> None:
        """Initialize the fallback embedding provider.

        Args:
            dimensions: The dimension of the output embedding vectors.
        """
        self._local = LocalEmbeddingProvider(dimensions=dimensions)

    async def embed(self, text: str) -> list[float]:
        """Compute an embedding vector using the local provider.

        Args:
            text: The input text to embed.

        Returns:
            A normalized embedding vector of fixed dimension.
        """
        return await self._local.embed(text)

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Compute embedding vectors for multiple texts using the local provider.

        Args:
            texts: List of input texts to embed.

        Returns:
            List of normalized embedding vectors.
        """
        return await self._local.embed_batch(texts)


def cosine_similarity(vec_a: list[float], vec_b: list[float]) -> float:
    """Compute cosine similarity between two vectors.

    Args:
        vec_a: First vector.
        vec_b: Second vector.

    Returns:
        Cosine similarity score between -1.0 and 1.0.
        Returns 0.0 if either vector has zero magnitude.
    """
    if len(vec_a) != len(vec_b):
        return 0.0

    dot_product = sum(a * b for a, b in zip(vec_a, vec_b))
    magnitude_a = math.sqrt(sum(a * a for a in vec_a))
    magnitude_b = math.sqrt(sum(b * b for b in vec_b))

    if magnitude_a == 0.0 or magnitude_b == 0.0:
        return 0.0

    return dot_product / (magnitude_a * magnitude_b)
