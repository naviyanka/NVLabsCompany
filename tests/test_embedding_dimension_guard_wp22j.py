"""WP-22j / M13: refuse a wrong-width embedding provider at startup.

``knowledge_chunks.embedding_vector`` is ``vector(1536)`` on PostgreSQL
(migration d5b1f7a3c210). At baseline a 768/1024/3072-dimensional provider
passed startup cleanly and every vector was silently dropped at INSERT by
RAGPipeline.index_chunks' PostgreSQL guard -- retrieval degraded to
keyword-only with nothing surfacing but a log line. The startup policy now
refuses that configuration. On SQLite the column is a JSON variant that
takes any width, so a mismatch is only an error there when the Obsidian
vault is configured (existing ADR 0002 §21 rule).
"""

import pytest

from nexus.models.knowledge import EMBEDDING_DIM
from nexus.obsidian.embedding_policy import (
    EmbeddingPolicyError,
    validate_embedding_policy,
)


class _WidthProvider:
    """Minimal provider double: only `dimension` is consulted at startup."""

    def __init__(self, dimension: int) -> None:
        self._dimension = dimension

    @property
    def dimension(self) -> int:
        return self._dimension

    async def embed(self, text_or_texts):  # pragma: no cover - never called
        raise NotImplementedError


def test_embedding_dimension_mismatch_fails_fast_on_postgres(monkeypatch):
    """768-wide provider + vector(1536) column must refuse to start."""
    monkeypatch.setattr(
        "nexus.knowledge.embeddings.get_embedding_provider",
        lambda: _WidthProvider(768),
    )
    with pytest.raises(EmbeddingPolicyError, match="768"):
        validate_embedding_policy(on_postgres=True)


def test_matching_dimension_on_postgres_passes(monkeypatch):
    monkeypatch.setattr(
        "nexus.knowledge.embeddings.get_embedding_provider",
        lambda: _WidthProvider(EMBEDDING_DIM),
    )
    validate_embedding_policy(on_postgres=True)


def test_null_provider_passes_on_postgres(monkeypatch):
    monkeypatch.setattr(
        "nexus.knowledge.embeddings.get_embedding_provider",
        lambda: _WidthProvider(0),
    )
    validate_embedding_policy(on_postgres=True)


def test_no_provider_passes_on_postgres(monkeypatch):
    monkeypatch.setattr(
        "nexus.knowledge.embeddings.get_embedding_provider",
        lambda: None,
    )
    validate_embedding_policy(on_postgres=True)


def test_sqlite_wrong_width_without_vault_is_not_a_startup_error(
    monkeypatch, tmp_path
):
    """JSON column on SQLite takes any width; without a vault nothing breaks."""
    from nexus.obsidian import security as obsidian_security

    monkeypatch.setattr(
        "nexus.knowledge.embeddings.get_embedding_provider",
        lambda: _WidthProvider(768),
    )
    monkeypatch.setattr(
        obsidian_security.settings, "obsidian_vault_root", "", raising=False
    )
    validate_embedding_policy(on_postgres=False)
