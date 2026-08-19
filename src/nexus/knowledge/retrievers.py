"""Pluggable retriever components for the RAG pipeline.

Provides a Retriever Protocol and multiple implementations:
- DenseRetriever: Uses embedding provider for vector similarity search
- SparseRetriever: Uses BM25 scoring from nexus.memory.retriever
- HybridRetriever: Combines dense and sparse with configurable alpha weight
- RetrieverFactory: Factory function to create retrievers by name
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional, Protocol, runtime_checkable

from nexus.knowledge.embeddings import EmbeddingProvider, cosine_similarity
from nexus.memory.retriever import search as bm25_search, tokenize


@runtime_checkable
class Retriever(Protocol):
    """Protocol defining the interface for document retrievers.

    All retrievers must implement an async retrieve() method that
    returns the most relevant documents for a given query.
    """

    async def retrieve(self, query: str, top_k: int = 5) -> list[dict[str, Any]]:
        """Retrieve the most relevant documents for a query.

        Args:
            query: The search query string.
            top_k: Maximum number of results to return.

        Returns:
            List of result dicts, each containing at minimum 'content'
            and 'score' keys.
        """
        ...


@dataclass
class DenseRetriever:
    """Retriever using embedding provider for vector similarity search.

    Computes embeddings for the query and all documents, then ranks
    by cosine similarity between query and document vectors.

    Attributes:
        embedding_provider: Provider for computing text embeddings.
        documents: List of document strings to search over.
    """

    embedding_provider: Any  # EmbeddingProvider
    documents: list[str] = field(default_factory=list)

    async def retrieve(self, query: str, top_k: int = 5) -> list[dict[str, Any]]:
        """Retrieve documents by vector similarity.

        Embeds the query and all documents, then computes cosine similarity
        to rank results.

        Args:
            query: The search query string.
            top_k: Maximum number of results to return.

        Returns:
            List of result dicts with 'content', 'score', and 'index' keys,
            sorted by cosine similarity (highest first).
        """
        if not self.documents or not query:
            return []

        # Embed query
        query_embedding = await self.embedding_provider.embed(query)

        # Embed all documents
        doc_embeddings = await self.embedding_provider.embed_batch(self.documents)

        # Score each document by cosine similarity
        scored: list[tuple[float, int]] = []
        for idx, doc_emb in enumerate(doc_embeddings):
            score = cosine_similarity(query_embedding, doc_emb)
            scored.append((score, idx))

        # Sort by score descending
        scored.sort(key=lambda x: x[0], reverse=True)

        # Build result dicts
        results: list[dict[str, Any]] = []
        for score, idx in scored[:top_k]:
            results.append({
                "content": self.documents[idx],
                "score": score,
                "index": idx,
            })

        return results

    def add_documents(self, docs: list[str]) -> None:
        """Add documents to the retriever's document store.

        Args:
            docs: List of document strings to add.
        """
        self.documents.extend(docs)


@dataclass
class SparseRetriever:
    """Retriever using BM25 scoring from nexus.memory.retriever.

    Uses the existing BM25 implementation for keyword-based retrieval.
    Best for exact term matching and precise keyword queries.

    Attributes:
        documents: List of document strings to search over.
    """

    documents: list[str] = field(default_factory=list)

    async def retrieve(self, query: str, top_k: int = 5) -> list[dict[str, Any]]:
        """Retrieve documents using BM25 scoring.

        Delegates to the BM25 search function from nexus.memory.retriever.

        Args:
            query: The search query string.
            top_k: Maximum number of results to return.

        Returns:
            List of result dicts with 'content', 'score', and 'index' keys,
            sorted by BM25 relevance (highest first).
        """
        if not self.documents or not query:
            return []

        # Use BM25 search from memory.retriever
        bm25_results = bm25_search(query, self.documents, top_k=top_k)

        # Build result dicts
        results: list[dict[str, Any]] = []
        for idx, score in bm25_results:
            results.append({
                "content": self.documents[idx],
                "score": score,
                "index": idx,
            })

        return results

    def add_documents(self, docs: list[str]) -> None:
        """Add documents to the retriever's document store.

        Args:
            docs: List of document strings to add.
        """
        self.documents.extend(docs)


@dataclass
class HybridRetriever:
    """Retriever combining dense and sparse strategies with configurable weighting.

    Merges results from a DenseRetriever and a SparseRetriever using
    a linear interpolation controlled by the alpha parameter.

    Final score = alpha * dense_score + (1 - alpha) * sparse_score

    Attributes:
        dense_retriever: The dense (embedding-based) retriever.
        sparse_retriever: The sparse (BM25-based) retriever.
        alpha: Weight for dense scores (0.0 = all sparse, 1.0 = all dense).
            Defaults to 0.5 (equal weighting).
    """

    dense_retriever: Any  # DenseRetriever
    sparse_retriever: Any  # SparseRetriever
    alpha: float = 0.5

    async def retrieve(self, query: str, top_k: int = 5) -> list[dict[str, Any]]:
        """Retrieve documents using hybrid dense + sparse scoring.

        Retrieves from both dense and sparse retrievers, then merges
        results using weighted combination. Documents found by both
        retrievers have their scores combined.

        Args:
            query: The search query string.
            top_k: Maximum number of results to return.

        Returns:
            List of result dicts with 'content', 'score', 'dense_score',
            and 'sparse_score' keys, sorted by combined score.
        """
        # Retrieve from both strategies (fetch more than top_k for better merging)
        fetch_k = top_k * 2
        dense_results = await self.dense_retriever.retrieve(query, top_k=fetch_k)
        sparse_results = await self.sparse_retriever.retrieve(query, top_k=fetch_k)

        # Normalize scores to 0-1 range
        dense_scores = self._normalize_scores(dense_results)
        sparse_scores = self._normalize_scores(sparse_results)

        # Merge results by content
        merged: dict[str, dict[str, Any]] = {}

        for result in dense_results:
            content = result["content"]
            normalized_dense = dense_scores.get(content, 0.0)
            merged[content] = {
                "content": content,
                "dense_score": normalized_dense,
                "sparse_score": 0.0,
                "index": result.get("index", -1),
            }

        for result in sparse_results:
            content = result["content"]
            normalized_sparse = sparse_scores.get(content, 0.0)
            if content in merged:
                merged[content]["sparse_score"] = normalized_sparse
            else:
                merged[content] = {
                    "content": content,
                    "dense_score": 0.0,
                    "sparse_score": normalized_sparse,
                    "index": result.get("index", -1),
                }

        # Compute combined scores
        results: list[dict[str, Any]] = []
        for entry in merged.values():
            combined = (
                self.alpha * entry["dense_score"]
                + (1.0 - self.alpha) * entry["sparse_score"]
            )
            entry["score"] = combined
            results.append(entry)

        # Sort by combined score descending
        results.sort(key=lambda x: x["score"], reverse=True)
        return results[:top_k]

    def _normalize_scores(self, results: list[dict[str, Any]]) -> dict[str, float]:
        """Normalize scores to 0-1 range using min-max normalization.

        Args:
            results: List of result dicts with 'score' key.

        Returns:
            Dict mapping content to normalized score.
        """
        if not results:
            return {}

        scores = [r["score"] for r in results]
        min_score = min(scores)
        max_score = max(scores)
        score_range = max_score - min_score

        normalized: dict[str, float] = {}
        for result in results:
            if score_range > 0:
                normalized[result["content"]] = (
                    (result["score"] - min_score) / score_range
                )
            else:
                normalized[result["content"]] = 1.0 if max_score > 0 else 0.0

        return normalized


def retriever_factory(
    strategy: str,
    embedding_provider: Optional[Any] = None,
    documents: Optional[list[str]] = None,
    alpha: float = 0.5,
) -> Any:
    """Factory function to create retrievers by strategy name.

    Creates and returns a retriever instance based on the specified strategy.
    Provides a convenient way to instantiate retrievers without importing
    individual classes.

    Args:
        strategy: Retriever strategy name - 'dense', 'sparse', or 'hybrid'.
        embedding_provider: Required for 'dense' and 'hybrid' strategies.
            Must implement the EmbeddingProvider protocol.
        documents: Optional initial list of documents to search over.
        alpha: Weight for dense scores in hybrid strategy (default 0.5).

    Returns:
        A retriever instance implementing the Retriever protocol.

    Raises:
        ValueError: If strategy is unsupported or required parameters are missing.
    """
    docs = documents or []

    if strategy == "dense":
        if embedding_provider is None:
            raise ValueError(
                "embedding_provider is required for 'dense' retriever strategy"
            )
        return DenseRetriever(embedding_provider=embedding_provider, documents=docs)

    elif strategy == "sparse":
        return SparseRetriever(documents=docs)

    elif strategy == "hybrid":
        if embedding_provider is None:
            raise ValueError(
                "embedding_provider is required for 'hybrid' retriever strategy"
            )
        dense = DenseRetriever(embedding_provider=embedding_provider, documents=docs)
        sparse = SparseRetriever(documents=docs)
        return HybridRetriever(
            dense_retriever=dense,
            sparse_retriever=sparse,
            alpha=alpha,
        )

    else:
        raise ValueError(
            f"Unsupported retriever strategy: {strategy}. "
            f"Use 'dense', 'sparse', or 'hybrid'."
        )
