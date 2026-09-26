"""Embedding dimension policy for the vault corpus (ADR 0002 §21).

The vault corpus is 1536-dimensional only. ``RAGPipeline.index_chunks`` already
detects a width mismatch on PostgreSQL, but it drops the vectors, logs a
warning, and returns success — retrieval silently degrades to keyword-only and
nothing surfaces. That is acceptable for the existing corpus and is not
acceptable for the vault.

So the gate moves to configuration load: a vault enabled alongside a provider of
the wrong width refuses to start. The ``index_status`` failure state on
``obsidian_documents`` remains the backstop for a provider that changes width
underneath a running system.
"""

from __future__ import annotations

from nexus.models.knowledge import EMBEDDING_DIM
from nexus.obsidian.security import is_vault_enabled


class EmbeddingPolicyError(Exception):
    """The configured embedding provider cannot serve the vault corpus."""


def validate_embedding_policy(*, on_postgres: bool = False) -> None:
    """Refuse a wrong-width embedding provider at startup (WP-22j).

    On PostgreSQL the check is unconditional: ``knowledge_chunks.embedding_vector``
    is ``vector(1536)`` (migration d5b1f7a3c210), and a provider of any other
    width has its vectors silently dropped by ``RAGPipeline.index_chunks`` —
    retrieval degrades to keyword-only with no operator-visible signal.

    Without PostgreSQL the column is the SQLite JSON variant and any width
    inserts fine, so only the vault constraint applies: a vault configured
    against a wrong-width provider refuses to start (ADR 0002 §21), and no
    provider at all — or the null provider — is a visible, deliberate
    keyword-only state rather than a silent degradation.

    Args:
        on_postgres: Whether the application database is PostgreSQL.

    Raises:
        EmbeddingPolicyError: If the provider's dimension is neither
            ``EMBEDDING_DIM`` nor 0 (the null provider) on PostgreSQL, or if a
            vault is configured and the provider is not exactly
            ``EMBEDDING_DIM``.
    """
    vault_enabled = is_vault_enabled()
    if not on_postgres and not vault_enabled:
        return

    from nexus.knowledge.embeddings import get_embedding_provider

    provider = get_embedding_provider()
    if provider is None:
        return

    dimension = provider.dimension
    if dimension == 0:
        # NullEmbeddingProvider: no vectors at all, keyword search only.
        return

    if dimension != EMBEDDING_DIM:
        what = (
            f"knowledge_chunks.embedding_vector (vector({EMBEDDING_DIM}))"
            if on_postgres
            else "the Obsidian vault corpus"
        )
        raise EmbeddingPolicyError(
            f"EMBEDDING_PROVIDER yields {dimension}-dimensional vectors but {what} "
            f"requires {EMBEDDING_DIM}. Configure a {EMBEDDING_DIM}-dimensional "
            f"provider (EMBEDDING_PROVIDER=openai with "
            f"OPENAI_EMBED_MODEL=text-embedding-3-small)"
            + (
                ", or unset obsidian_vault_root to disable the integration."
                if vault_enabled
                else "."
            )
        )
