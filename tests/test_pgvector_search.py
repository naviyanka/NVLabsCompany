"""pgvector search path for RAGPipeline.

Verifies that on PostgreSQL the vector search is pushed into SQL (`<=>` with
ORDER BY / LIMIT rather than a full-table scan scored in Python), that scores
match the Python cosine implementation on a fixture set, and that non-Postgres
sessions keep the JSON/Python fallback.
"""

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.dialects import postgresql

from nexus.knowledge.embeddings import cosine_similarity
from nexus.knowledge.rag import RAGPipeline
from nexus.models.knowledge import EMBEDDING_DIM, KnowledgeChunk

COMPANY_ID = uuid.UUID("12345678-1234-1234-1234-123456789abc")
PAGE_ID = uuid.UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")


def _vec(seed: float) -> list[float]:
    v = [0.0] * EMBEDDING_DIM
    v[0] = seed
    v[1] = 1.0 - seed
    return v


FIXTURES = [
    ("python programming tutorial", _vec(0.9)),
    ("python cookbook recipes", _vec(0.5)),
    ("cooking recipes guide", _vec(0.1)),
]
QUERY_EMBEDDING = _vec(1.0)


class FakePGSession:
    """Async session double that reports a postgresql dialect and records SQL."""

    def __init__(self, rows):
        self._rows = rows
        self.compiled = ""
        self.add = MagicMock()
        self.commit = AsyncMock()

    def get_bind(self):
        bind = MagicMock()
        bind.dialect.name = "postgresql"
        return bind

    async def exec(self, statement):
        self.compiled = str(statement.compile(dialect=postgresql.dialect()))
        result = MagicMock()
        result.all.return_value = self._rows
        return result


def _chunk(content: str, vector: list[float], idx: int) -> KnowledgeChunk:
    return KnowledgeChunk(
        company_id=COMPANY_ID,
        page_id=PAGE_ID,
        content=content,
        chunk_index=idx,
        embedding_vector=vector,
    )


@pytest.mark.asyncio
async def test_search_pushes_distance_into_sql():
    """The Postgres path emits a `<=>` ordered, limited query, not a full scan."""
    rows = [
        (_chunk(content, vector, i), 1.0 - cosine_similarity(QUERY_EMBEDDING, vector))
        for i, (content, vector) in enumerate(FIXTURES)
    ]
    db = FakePGSession(rows)
    provider = AsyncMock()
    provider.embed = AsyncMock(return_value=QUERY_EMBEDDING)

    results = await RAGPipeline(db, embedding_provider=provider).search(
        COMPANY_ID, "python programming", top_k=2
    )

    assert "<=>" in db.compiled
    assert "ORDER BY" in db.compiled
    assert "LIMIT" in db.compiled
    assert results, "expected at least one hit"

    # Scores derived from the SQL distance match Python cosine on the fixtures.
    for result in results:
        expected = cosine_similarity(QUERY_EMBEDDING, result["chunk"].embedding_vector)
        assert result["vector_score"] == pytest.approx(expected, abs=1e-9)

    # And the nearest fixture still ranks above the far one.
    scores = {r["chunk"].content: r["vector_score"] for r in results}
    if "cooking recipes guide" in scores:
        assert scores["python programming tutorial"] > scores["cooking recipes guide"]


@pytest.mark.asyncio
async def test_search_falls_back_off_postgres():
    """Non-Postgres sessions load chunks and score with Python cosine."""
    chunks = [_chunk(content, vector, i) for i, (content, vector) in enumerate(FIXTURES)]
    db = AsyncMock()
    db.add = MagicMock()
    result = MagicMock()
    result.all.return_value = chunks
    db.exec.return_value = result
    db.get_bind = MagicMock(side_effect=Exception("unbound"))

    provider = AsyncMock()
    provider.embed = AsyncMock(return_value=QUERY_EMBEDDING)

    results = await RAGPipeline(db, embedding_provider=provider).search(
        COMPANY_ID, "python programming", top_k=3
    )

    assert results
    for r in results:
        expected = cosine_similarity(QUERY_EMBEDDING, r["chunk"].embedding_vector)
        assert r["vector_score"] == pytest.approx(max(0.0, expected), abs=1e-9)


@pytest.mark.asyncio
async def test_dimension_mismatch_skips_sql_path():
    """A provider whose width differs from the column falls back instead of erroring."""
    chunks = [_chunk("python programming tutorial", [1.0, 0.0, 0.0], 0)]
    db = FakePGSession([])
    db.exec = AsyncMock(return_value=MagicMock(all=MagicMock(return_value=chunks)))

    provider = AsyncMock()
    provider.embed = AsyncMock(return_value=[1.0, 0.0, 0.0])

    results = await RAGPipeline(db, embedding_provider=provider).search(
        COMPANY_ID, "python programming", top_k=3
    )

    assert results
    assert results[0]["vector_score"] == pytest.approx(1.0, abs=1e-9)
