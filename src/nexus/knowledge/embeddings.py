"""Embedding Provider — pluggable vector embedding generation for RAG.

Supports multiple backends:
- OpenAI text-embedding-3-small/large
- Ollama (local models like nomic-embed-text)
- None (falls back to BM25/token-overlap in RAGPipeline)

Configuration via environment variables:
- EMBEDDING_PROVIDER: "openai" | "ollama" | "none" (default: "none")
- OPENAI_API_KEY: required when provider is "openai"
- OLLAMA_EMBED_MODEL: model name for Ollama (default: "nomic-embed-text")
- OLLAMA_EMBED_URL: Ollama API URL (default: "http://localhost:11434")
"""

import os
from typing import Protocol


class EmbeddingProvider(Protocol):
    """Protocol for embedding providers used by RAGPipeline."""

    async def embed(self, texts: list[str]) -> list[list[float]]:
        """Generate embeddings for a list of text strings.

        Args:
            texts: List of text strings to embed.

        Returns:
            List of embedding vectors (one per input text).
        """
        ...

    @property
    def dimension(self) -> int:
        """The dimensionality of the embedding vectors."""
        ...


class OpenAIEmbeddingProvider:
    """Embedding provider using OpenAI's text-embedding API.

    Requires OPENAI_API_KEY environment variable.
    Uses text-embedding-3-small by default (1536 dimensions).
    """

    def __init__(self, model: str = "text-embedding-3-small") -> None:
        self._model = model
        self._api_key = os.environ.get("OPENAI_API_KEY", "")
        self._dimension = 1536 if "small" in model else 3072

    @property
    def dimension(self) -> int:
        return self._dimension

    async def embed(self, texts: list[str]) -> list[list[float]]:
        """Call OpenAI embeddings API."""
        import httpx

        if not self._api_key:
            raise RuntimeError("OPENAI_API_KEY not set — cannot generate embeddings")

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
            return [item["embedding"] for item in data["data"]]


class OllamaEmbeddingProvider:
    """Embedding provider using a local Ollama instance.

    Uses nomic-embed-text by default (768 dimensions).
    """

    def __init__(
        self,
        model: str | None = None,
        base_url: str | None = None,
    ) -> None:
        self._model = model or os.environ.get("OLLAMA_EMBED_MODEL", "nomic-embed-text")
        self._base_url = base_url or os.environ.get("OLLAMA_EMBED_URL", "http://localhost:11434")
        self._dimension = 768  # nomic-embed-text default

    @property
    def dimension(self) -> int:
        return self._dimension

    async def embed(self, texts: list[str]) -> list[list[float]]:
        """Call Ollama embeddings endpoint."""
        import httpx

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
        return results


class NullEmbeddingProvider:
    """No-op provider — RAGPipeline will fall back to token-overlap heuristic."""

    @property
    def dimension(self) -> int:
        return 0

    async def embed(self, texts: list[str]) -> list[list[float]]:
        return []


def get_embedding_provider() -> EmbeddingProvider | None:
    """Factory function to create the configured embedding provider.

    Reads EMBEDDING_PROVIDER env var:
    - "openai" → OpenAIEmbeddingProvider
    - "ollama" → OllamaEmbeddingProvider
    - "none" or unset → None (BM25/token-overlap fallback)

    Returns:
        An EmbeddingProvider instance, or None for fallback mode.
    """
    provider_type = os.environ.get("EMBEDDING_PROVIDER", "none").lower()

    if provider_type == "openai":
        model = os.environ.get("OPENAI_EMBED_MODEL", "text-embedding-3-small")
        return OpenAIEmbeddingProvider(model=model)
    elif provider_type == "ollama":
        return OllamaEmbeddingProvider()
    else:
        return None
