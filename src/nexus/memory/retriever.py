"""BM25 Retrieval - pure Python implementation of Okapi BM25 for memory search."""

import math
import re
from dataclasses import dataclass


# BM25 parameters (Okapi BM25 standard values)
_K1: float = 1.5
_B: float = 0.75


@dataclass
class CorpusStats:
    """Statistics about the document corpus for BM25 scoring."""

    total_docs: int
    avg_doc_length: float
    doc_frequencies: dict[str, int]


def tokenize(text: str) -> list[str]:
    """Tokenize text into lowercase words, removing punctuation.

    Simple whitespace + alphanumeric tokenizer suitable for BM25.
    Strips common punctuation and converts to lowercase.

    Args:
        text: The input text to tokenize.

    Returns:
        List of lowercase token strings.
    """
    # Remove non-alphanumeric characters (except spaces), lowercase, and split
    cleaned = re.sub(r"[^\w\s]", " ", text.lower())
    tokens = cleaned.split()
    # Filter out very short tokens (single characters except common ones)
    return [t for t in tokens if len(t) > 1 or t in ("i", "a")]


def _compute_corpus_stats(documents: list[list[str]]) -> CorpusStats:
    """Compute corpus-level statistics for BM25.

    Args:
        documents: List of tokenized documents.

    Returns:
        CorpusStats with total docs, average length, and doc frequencies.
    """
    total_docs = len(documents)
    if total_docs == 0:
        return CorpusStats(
            total_docs=0,
            avg_doc_length=0.0,
            doc_frequencies={},
        )

    total_length = sum(len(doc) for doc in documents)
    avg_doc_length = total_length / total_docs

    # Document frequency: number of docs containing each term
    doc_frequencies: dict[str, int] = {}
    for doc in documents:
        unique_terms = set(doc)
        for term in unique_terms:
            doc_frequencies[term] = doc_frequencies.get(term, 0) + 1

    return CorpusStats(
        total_docs=total_docs,
        avg_doc_length=avg_doc_length,
        doc_frequencies=doc_frequencies,
    )


def bm25_score(
    query_tokens: list[str],
    document_tokens: list[str],
    corpus_stats: CorpusStats,
    k1: float = _K1,
    b: float = _B,
) -> float:
    """Compute the Okapi BM25 score for a document given a query.

    BM25 is a ranking function used by search engines to estimate the
    relevance of documents to a given search query.

    Formula per term:
        score += IDF(qi) * (f(qi, D) * (k1 + 1)) / (f(qi, D) + k1 * (1 - b + b * |D| / avgdl))

    Where:
        IDF(qi) = ln((N - n(qi) + 0.5) / (n(qi) + 0.5) + 1)
        f(qi, D) = term frequency of qi in document D
        |D| = length of document D
        avgdl = average document length in corpus
        N = total number of documents
        n(qi) = number of documents containing qi

    Args:
        query_tokens: Tokenized query.
        document_tokens: Tokenized document.
        corpus_stats: Pre-computed corpus statistics.
        k1: Term frequency saturation parameter (default 1.5).
        b: Document length normalization parameter (default 0.75).

    Returns:
        The BM25 relevance score (higher is more relevant).
    """
    if corpus_stats.total_docs == 0 or not document_tokens:
        return 0.0

    score = 0.0
    doc_length = len(document_tokens)
    avg_dl = corpus_stats.avg_doc_length

    # Count term frequencies in document
    term_freq: dict[str, int] = {}
    for token in document_tokens:
        term_freq[token] = term_freq.get(token, 0) + 1

    for term in query_tokens:
        if term not in term_freq:
            continue

        # Document frequency of term
        df = corpus_stats.doc_frequencies.get(term, 0)
        n = corpus_stats.total_docs

        # IDF component with Robertson-Sparck Jones formula
        idf = math.log((n - df + 0.5) / (df + 0.5) + 1.0)

        # Term frequency component with saturation
        tf = term_freq[term]
        tf_normalized = (tf * (k1 + 1)) / (
            tf + k1 * (1 - b + b * doc_length / avg_dl)
        )

        score += idf * tf_normalized

    return score


def search(
    query: str,
    memories: list[str],
    top_k: int = 10,
) -> list[tuple[int, float]]:
    """Search memories using BM25 ranking.

    Tokenizes the query and all memories, computes corpus statistics,
    scores each memory, and returns the top-k results.

    Args:
        query: The search query string.
        memories: List of memory content strings to search.
        top_k: Number of top results to return.

    Returns:
        List of (index, score) tuples sorted by relevance (highest first).
        Index refers to the position in the input memories list.
    """
    if not memories or not query:
        return []

    # Tokenize all documents
    query_tokens = tokenize(query)
    if not query_tokens:
        return []

    document_tokens = [tokenize(mem) for mem in memories]

    # Compute corpus statistics
    corpus_stats = _compute_corpus_stats(document_tokens)

    # Score each document
    scored: list[tuple[int, float]] = []
    for idx, doc_tokens in enumerate(document_tokens):
        score = bm25_score(query_tokens, doc_tokens, corpus_stats)
        if score > 0:
            scored.append((idx, score))

    # Sort by score descending and take top_k
    scored.sort(key=lambda x: x[1], reverse=True)
    return scored[:top_k]
