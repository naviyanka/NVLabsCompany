"""Pluggable ranker components for the RAG pipeline.

Provides a Ranker Protocol and multiple implementations:
- BM25Ranker: Uses BM25 scoring from nexus.memory.retriever for re-ranking
- CrossEncoderRanker: Combined BM25 + token overlap scoring as a cross-encoder proxy
- RerankerPipeline: Chains multiple rankers sequentially
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from nexus.knowledge.embeddings import cosine_similarity
from nexus.memory.retriever import (
    CorpusStats,
    bm25_score,
    tokenize,
)


@runtime_checkable
class Ranker(Protocol):
    """Protocol defining the interface for result rankers.

    All rankers must implement rank() to reorder search results
    based on their relevance scoring strategy.
    """

    def rank(self, query: str, results: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Rank search results by relevance to the query.

        Args:
            query: The search query string.
            results: List of result dicts, each containing at minimum
                a 'content' key with the text content to rank.

        Returns:
            Reordered list of result dicts, sorted by relevance (highest first).
        """
        ...


@dataclass
class BM25Ranker:
    """Ranker using BM25 scoring from nexus.memory.retriever.

    Re-ranks results based on BM25 relevance between the query
    and the content of each result. Uses corpus statistics computed
    from all results in the batch.

    Attributes:
        top_k: Maximum number of results to return. Defaults to 10.
    """

    top_k: int = 10

    def rank(self, query: str, results: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Rank results using BM25 scoring.

        Tokenizes query and all result contents, computes corpus stats,
        then scores and sorts by BM25 relevance.

        Args:
            query: The search query string.
            results: List of result dicts with 'content' key.

        Returns:
            Reordered list of result dicts, limited to top_k.
        """
        if not results or not query:
            return results[:self.top_k] if results else []

        query_tokens = tokenize(query)
        if not query_tokens:
            return results[:self.top_k]

        # Tokenize all result contents
        doc_tokens_list = []
        for result in results:
            content = self._get_content(result)
            doc_tokens_list.append(tokenize(content))

        # Compute corpus statistics
        corpus_stats = self._compute_stats(doc_tokens_list)

        # Score each result
        scored: list[tuple[float, dict[str, Any]]] = []
        for idx, result in enumerate(results):
            score = bm25_score(query_tokens, doc_tokens_list[idx], corpus_stats)
            scored.append((score, result))

        # Sort by score descending
        scored.sort(key=lambda x: x[0], reverse=True)
        return [r for _, r in scored[:self.top_k]]

    def _get_content(self, result: dict[str, Any]) -> str:
        """Extract text content from a result dict.

        Supports multiple result formats: direct 'content' key,
        'chunk' object with content attribute, or string representation.

        Args:
            result: A result dictionary.

        Returns:
            Text content string.
        """
        if "content" in result:
            return str(result["content"])
        chunk = result.get("chunk")
        if chunk is not None and hasattr(chunk, "content"):
            return str(chunk.content)
        return str(result)

    def _compute_stats(self, doc_tokens_list: list[list[str]]) -> CorpusStats:
        """Compute corpus statistics for BM25 scoring.

        Args:
            doc_tokens_list: List of tokenized documents.

        Returns:
            CorpusStats instance.
        """
        total_docs = len(doc_tokens_list)
        if total_docs == 0:
            return CorpusStats(total_docs=0, avg_doc_length=0.0, doc_frequencies={})

        total_length = sum(len(doc) for doc in doc_tokens_list)
        avg_doc_length = total_length / total_docs

        doc_frequencies: dict[str, int] = {}
        for doc in doc_tokens_list:
            unique_terms = set(doc)
            for term in unique_terms:
                doc_frequencies[term] = doc_frequencies.get(term, 0) + 1

        return CorpusStats(
            total_docs=total_docs,
            avg_doc_length=avg_doc_length,
            doc_frequencies=doc_frequencies,
        )


@dataclass
class CrossEncoderRanker:
    """Cross-encoder proxy ranker using combined BM25 + token overlap.

    Since no external dependencies are allowed, this simulates a
    cross-encoder by combining BM25 scoring with token overlap as
    a joint relevance signal. A configurable scoring function can
    be provided for custom scoring logic.

    Attributes:
        top_k: Maximum number of results to return. Defaults to 10.
        bm25_weight: Weight for the BM25 component (0.0 to 1.0). Defaults to 0.6.
        overlap_weight: Weight for the token overlap component. Defaults to 0.4.
        scoring_fn: Optional custom scoring function(query, content) -> float.
    """

    top_k: int = 10
    bm25_weight: float = 0.6
    overlap_weight: float = 0.4
    scoring_fn: Any = field(default=None, repr=False)

    def rank(self, query: str, results: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Rank results using combined BM25 + token overlap scoring.

        If a custom scoring_fn is provided, it is used instead of the
        default combined scoring approach.

        Args:
            query: The search query string.
            results: List of result dicts with 'content' key.

        Returns:
            Reordered list of result dicts, limited to top_k.
        """
        if not results or not query:
            return results[:self.top_k] if results else []

        query_tokens = tokenize(query)
        if not query_tokens:
            return results[:self.top_k]

        # Tokenize all result contents
        doc_tokens_list = []
        contents: list[str] = []
        for result in results:
            content = self._get_content(result)
            contents.append(content)
            doc_tokens_list.append(tokenize(content))

        # Compute corpus statistics for BM25
        corpus_stats = self._compute_stats(doc_tokens_list)

        # Score each result
        scored: list[tuple[float, dict[str, Any]]] = []
        for idx, result in enumerate(results):
            if self.scoring_fn is not None:
                score = float(self.scoring_fn(query, contents[idx]))
            else:
                # BM25 component
                bm25 = bm25_score(query_tokens, doc_tokens_list[idx], corpus_stats)
                # Normalize BM25 to 0-1 range approximately
                bm25_normalized = min(bm25 / (bm25 + 1.0), 1.0) if bm25 > 0 else 0.0

                # Token overlap component (Jaccard similarity)
                overlap = self._token_overlap(query_tokens, doc_tokens_list[idx])

                # Combined score
                score = self.bm25_weight * bm25_normalized + self.overlap_weight * overlap

            scored.append((score, result))

        # Sort by score descending
        scored.sort(key=lambda x: x[0], reverse=True)
        return [r for _, r in scored[:self.top_k]]

    def _get_content(self, result: dict[str, Any]) -> str:
        """Extract text content from a result dict.

        Args:
            result: A result dictionary.

        Returns:
            Text content string.
        """
        if "content" in result:
            return str(result["content"])
        chunk = result.get("chunk")
        if chunk is not None and hasattr(chunk, "content"):
            return str(chunk.content)
        return str(result)

    def _token_overlap(self, query_tokens: list[str], doc_tokens: list[str]) -> float:
        """Compute Jaccard token overlap between query and document.

        Args:
            query_tokens: Tokenized query.
            doc_tokens: Tokenized document.

        Returns:
            Jaccard similarity score between 0.0 and 1.0.
        """
        if not query_tokens or not doc_tokens:
            return 0.0
        query_set = set(query_tokens)
        doc_set = set(doc_tokens)
        intersection = query_set & doc_set
        union = query_set | doc_set
        return len(intersection) / len(union) if union else 0.0

    def _compute_stats(self, doc_tokens_list: list[list[str]]) -> CorpusStats:
        """Compute corpus statistics for BM25 scoring.

        Args:
            doc_tokens_list: List of tokenized documents.

        Returns:
            CorpusStats instance.
        """
        total_docs = len(doc_tokens_list)
        if total_docs == 0:
            return CorpusStats(total_docs=0, avg_doc_length=0.0, doc_frequencies={})

        total_length = sum(len(doc) for doc in doc_tokens_list)
        avg_doc_length = total_length / total_docs

        doc_frequencies: dict[str, int] = {}
        for doc in doc_tokens_list:
            unique_terms = set(doc)
            for term in unique_terms:
                doc_frequencies[term] = doc_frequencies.get(term, 0) + 1

        return CorpusStats(
            total_docs=total_docs,
            avg_doc_length=avg_doc_length,
            doc_frequencies=doc_frequencies,
        )


@dataclass
class RerankerPipeline:
    """Chains multiple rankers sequentially for multi-stage reranking.

    Each ranker in the pipeline processes the output of the previous ranker,
    allowing for increasingly precise filtering and scoring stages.

    Attributes:
        rankers: Ordered list of rankers to apply sequentially.
    """

    rankers: list[Any] = field(default_factory=list)

    def rank(self, query: str, results: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Apply all rankers in sequence to the results.

        Each ranker receives the output of the previous ranker as input.
        If the rankers list is empty, returns results unchanged.

        Args:
            query: The search query string.
            results: Initial list of result dicts.

        Returns:
            Final reordered list after all rankers have been applied.
        """
        current_results = results
        for ranker in self.rankers:
            current_results = ranker.rank(query, current_results)
        return current_results

    def add_ranker(self, ranker: Any) -> None:
        """Add a ranker to the end of the pipeline.

        Args:
            ranker: A ranker instance implementing the Ranker protocol.
        """
        self.rankers.append(ranker)
