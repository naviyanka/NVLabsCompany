"""Jaccard similarity deduplication for memory facts.

Provides tokenization, similarity computation, and duplicate detection
used by the layered memory system to prevent redundant fact storage.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from nexus.memory.layered import Fact

# Common English stopwords to filter during tokenization
_STOPWORDS: set[str] = {
    "a", "an", "the", "is", "are", "was", "were", "be", "been", "being",
    "have", "has", "had", "do", "does", "did", "will", "would", "could",
    "should", "may", "might", "shall", "can", "need", "dare", "ought",
    "used", "to", "of", "in", "for", "on", "with", "at", "by", "from",
    "as", "into", "through", "during", "before", "after", "above", "below",
    "between", "out", "off", "over", "under", "again", "further", "then",
    "once", "here", "there", "when", "where", "why", "how", "all", "each",
    "every", "both", "few", "more", "most", "other", "some", "such", "no",
    "nor", "not", "only", "own", "same", "so", "than", "too", "very",
    "just", "because", "but", "and", "or", "if", "while", "about", "up",
    "it", "its", "this", "that", "these", "those", "i", "me", "my",
    "we", "our", "you", "your", "he", "him", "his", "she", "her",
    "they", "them", "their", "what", "which", "who", "whom",
}


def tokenize(text: str) -> set[str]:
    """Tokenize text into a set of lowercase words, filtering stopwords.

    Splits on whitespace and punctuation, converts to lowercase, and
    removes common English stopwords to produce meaningful token sets
    for similarity comparison.

    Args:
        text: The input text to tokenize.

    Returns:
        A set of unique lowercase token strings (stopwords excluded).
    """
    # Split on whitespace and punctuation
    tokens = re.split(r"[\s\W]+", text.lower())
    # Filter empty strings and stopwords; keep single-char tokens that are meaningful
    return {t for t in tokens if t and t not in _STOPWORDS}


def jaccard_similarity(set_a: set[str], set_b: set[str]) -> float:
    """Compute Jaccard similarity coefficient between two token sets.

    Jaccard similarity is defined as |A intersection B| / |A union B|.
    Returns 0.0 if both sets are empty.

    Args:
        set_a: First set of tokens.
        set_b: Second set of tokens.

    Returns:
        Similarity score between 0.0 (no overlap) and 1.0 (identical).
    """
    if not set_a and not set_b:
        return 0.0
    intersection = set_a & set_b
    union = set_a | set_b
    return len(intersection) / len(union)


def is_duplicate(
    existing_facts: list[Fact],
    new_fact_content: str,
    threshold: float = 0.8,
) -> bool:
    """Check if a new fact is a duplicate of any existing fact.

    Compares the new fact content against all existing facts using
    Jaccard similarity. If any existing fact exceeds the threshold,
    the new fact is considered a duplicate.

    Args:
        existing_facts: List of existing Fact instances to compare against.
        new_fact_content: The content string of the new fact to check.
        threshold: Similarity threshold above which facts are duplicates.

    Returns:
        True if the new fact is a duplicate, False otherwise.
    """
    new_tokens = tokenize(new_fact_content)
    if not new_tokens:
        return False

    for fact in existing_facts:
        existing_tokens = tokenize(fact.content)
        if jaccard_similarity(existing_tokens, new_tokens) >= threshold:
            return True
    return False


def find_duplicates(
    facts: list[Fact],
    threshold: float = 0.8,
) -> list[tuple[int, int]]:
    """Find all pairs of duplicate facts within a list.

    Performs pairwise Jaccard similarity comparison and returns
    index pairs where similarity meets or exceeds the threshold.

    Args:
        facts: List of Fact instances to check for duplicates.
        threshold: Similarity threshold for duplicate detection.

    Returns:
        List of (index_i, index_j) tuples identifying duplicate pairs,
        where index_i < index_j.
    """
    duplicates: list[tuple[int, int]] = []
    token_cache: list[set[str]] = [tokenize(f.content) for f in facts]

    for i in range(len(facts)):
        for j in range(i + 1, len(facts)):
            if jaccard_similarity(token_cache[i], token_cache[j]) >= threshold:
                duplicates.append((i, j))

    return duplicates
