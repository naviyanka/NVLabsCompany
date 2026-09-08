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


def validate_embedding_policy() -> None:
    """Refuse a vault configured against a wrong-width embedding provider.

    Does nothing when the vault is disabled (no ``obsidian_vault_root``), so
    existing deployments are unaffected, or when no provider is configured — a
    vault indexed without vectors still supports keyword search, and that is a
    visible, deliberate state rather than a silent degradation.

    Raises:
        EmbeddingPolicyError: If a vault is configured and the provider's
            dimension is neither ``EMBEDDING_DIM`` nor 0 (the null provider).
    """
    if not is_vault_enabled():
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
        raise EmbeddingPolicyError(
            f"EMBEDDING_PROVIDER yields {dimension}-dimensional vectors but the "
            f"Obsidian vault corpus requires {EMBEDDING_DIM}. Configure a "
            f"{EMBEDDING_DIM}-dimensional provider (EMBEDDING_PROVIDER=openai "
            f"with OPENAI_EMBED_MODEL=text-embedding-3-small), or unset "
            f"obsidian_vault_root to disable the integration."
        )
