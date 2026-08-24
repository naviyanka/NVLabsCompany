"""Embedding Provider — pluggable vector embedding generation for RAG.

Supports multiple backends:
- OpenAI text-embedding-3-small/large
- Ollama (local models like nomic-embed-text)
- None (falls back to BM25/token-overlap in RAGPipeline)
"""

import math
import os
from typing import Any, Protocol, runtime_checkable

import httpx


@runtime_checkable
class EmbeddingProvider(Protocol):
    """Protocol for embedding providers used by RAGPipeline."""

    async def embed(self, text_or_texts: Any) -> Any:
        """Generate embeddings for text string(s)."""
        ...

    @property
    def dimension(self) -> int:
        """The dimensionality of the embedding vectors."""
        ...


class OpenAIEmbeddingProvider:
    """Embedding provider using OpenAI's text-embedding API."""

    def __init__(self, model: str = "text-embedding-3-small", api_key: str | None = None) -> None:
        self._model = model
        self._api_key = api_key if api_key is not None else os.environ.get("OPENAI_API_KEY", "")
        self._dimension = 1536 if "small" in model else 3072

    @property
    def dimension(self) -> int:
        return self._dimension

    async def embed(self, text_or_texts: str | list[str]) -> list[float] | list[list[float]]:
        """Call OpenAI embeddings API."""
        if not self._api_key:
            raise ValueError("API key is not configured — cannot generate embeddings")

        is_single = isinstance(text_or_texts, str)
        texts = [text_or_texts] if is_single else text_or_texts
        if not texts:
            return []

        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                "https://api.openai.com/v1/embeddings",
                json={"model": self._model, "input": texts},
                headers={
                    "Authorization": f"Bearer {self._api_key}",
                    "Content-Type": "application/json",
                },
            )
            if response.status_code != 200:
                raise RuntimeError(f"OpenAI embeddings API error {response.status_code}: {response.text[:200]}")

            data = response.json()
            sorted_items = sorted(data["data"], key=lambda x: x.get("index", 0))
            embeddings = [item["embedding"] for item in sorted_items]
            return embeddings[0] if is_single else embeddings

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        res = await self.embed(texts)
        return res if isinstance(res, list) and (not res or isinstance(res[0], list)) else [res]  # type: ignore


class OllamaEmbeddingProvider:
    """Embedding provider using a local Ollama instance."""

    def __init__(
        self,
        model: str | None = None,
        base_url: str | None = None,
    ) -> None:
        self._model = model or os.environ.get("OLLAMA_EMBED_MODEL", "nomic-embed-text")
        self._base_url = base_url or os.environ.get("OLLAMA_EMBED_URL", "http://localhost:11434")
        self._dimension = 768

    @property
    def dimension(self) -> int:
        return self._dimension

    async def embed(self, text_or_texts: str | list[str]) -> list[float] | list[list[float]]:
        is_single = isinstance(text_or_texts, str)
        texts = [text_or_texts] if is_single else text_or_texts

        results = []
        async with httpx.AsyncClient(timeout=30.0) as client:
            for text in texts:
                response = await client.post(
                    f"{self._base_url}/api/embeddings",
                    json={"model": self._model, "prompt": text},
                )
                if response.status_code != 200:
                    raise RuntimeError(f"Ollama embed error: {response.status_code}")
                data = response.json()
                results.append(data["embedding"])
        return results[0] if is_single else results

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        res = await self.embed(texts)
        return res if isinstance(res, list) and (not res or isinstance(res[0], list)) else [res]  # type: ignore


class NullEmbeddingProvider:
    """No-op provider — RAGPipeline will fall back to token-overlap heuristic."""

    def __init__(self, dimension: int = 0, dimensions: int | None = None) -> None:
        self._dimension = dimensions if dimensions is not None else dimension

    @property
    def dimension(self) -> int:
        return self._dimension

    async def embed(self, text_or_texts: str | list[str]) -> list[float] | list[list[float]]:
        if isinstance(text_or_texts, str):
            return [0.0] * self._dimension
        return [[0.0] * self._dimension for _ in text_or_texts]

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        return [[0.0] * self._dimension for _ in texts]


def get_embedding_provider() -> EmbeddingProvider | None:
    provider_type = os.environ.get("EMBEDDING_PROVIDER", "none").lower()

    if provider_type == "openai":
        model = os.environ.get("OPENAI_EMBED_MODEL", "text-embedding-3-small")
        return OpenAIEmbeddingProvider(model=model)
    elif provider_type == "ollama":
        return OllamaEmbeddingProvider()
    elif provider_type == "local":
        return LocalEmbeddingProvider()
    else:
        return None


def cosine_similarity(v1: list[float], v2: list[float]) -> float:
    """Compute cosine similarity between two float vectors."""
    if not v1 or not v2 or len(v1) != len(v2):
        return 0.0
    dot = sum(a * b for a, b in zip(v1, v2))
    norm_a = math.sqrt(sum(a * a for a in v1))
    norm_b = math.sqrt(sum(b * b for b in v2))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


class LocalEmbeddingProvider:
    """Simple deterministic local embedding provider for testing/fallback without API keys."""

    def __init__(self, dimension: int = 256, dimensions: int | None = None) -> None:
        self._dimension = dimensions if dimensions is not None else dimension

    @property
    def dimension(self) -> int:
        return self._dimension

    def _compute_embedding(self, text: str) -> list[float]:
        vec = [0.0] * self._dimension
        words = text.lower().split()
        for w in words:
            idx = abs(hash(w)) % self._dimension
            vec[idx] += 1.0
        norm = math.sqrt(sum(x * x for x in vec)) or 1.0
        return [x / norm for x in vec]

    async def embed(self, text_or_texts: str | list[str]) -> list[float] | list[list[float]]:
        is_single = isinstance(text_or_texts, str)
        texts = [text_or_texts] if is_single else text_or_texts

        results = [self._compute_embedding(text) for text in texts]
        return results[0] if is_single else results

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        res = await self.embed(texts)
        return res if isinstance(res, list) and (not res or isinstance(res[0], list)) else [res]  # type: ignore


FallbackEmbeddingProvider = LocalEmbeddingProvider
