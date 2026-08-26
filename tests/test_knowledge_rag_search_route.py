"""Tests for the /knowledge/search route wiring to RAGPipeline.

The route used to read ORM attributes off RAGPipeline.search() results, but
search() returns dicts ({"chunk": ..., "combined_score": ...}). The resulting
AttributeError was swallowed by a bare except, so every search silently
degraded to a substring match. These tests pin the real pipeline path.
"""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from nexus.api.routes import knowledge as knowledge_routes
from nexus.models.knowledge import KnowledgeChunk

COMPANY_ID = uuid.uuid4()


def _chunk(content: str, index: int = 0) -> KnowledgeChunk:
    return KnowledgeChunk(
        id=uuid.uuid4(),
        company_id=COMPANY_ID,
        page_id=uuid.uuid4(),
        content=content,
        chunk_index=index,
        chunk_metadata={"source": "test"},
    )


@pytest.mark.asyncio
async def test_search_returns_pipeline_results_with_scores():
    """The pipeline result dicts are unpacked, including combined_score."""
    chunk = _chunk("deployment runbook", index=2)
    pipeline = MagicMock()
    pipeline.search = AsyncMock(return_value=[
        {"chunk": chunk, "bm25_score": 0.8, "vector_score": 0.4, "combined_score": 0.68},
    ])

    body = knowledge_routes.RAGSearchRequest(query="deployment", top_k=5)
    session = AsyncMock()

    with patch("nexus.knowledge.rag.RAGPipeline", return_value=pipeline):
        results = await knowledge_routes.rag_search(COMPANY_ID, body, session)

    assert len(results) == 1
    assert results[0].chunk_id == chunk.id
    assert results[0].page_id == chunk.page_id
    assert results[0].content == "deployment runbook"
    assert results[0].chunk_index == 2
    assert results[0].metadata == {"source": "test"}
    assert results[0].score == pytest.approx(0.68)
    pipeline.search.assert_awaited_once()
    # The real path must not touch the substring fallback.
    session.execute.assert_not_called()


@pytest.mark.asyncio
async def test_search_falls_back_when_pipeline_raises():
    """A pipeline failure still answers from the substring fallback."""
    chunk = _chunk("incident postmortem")

    class _Scalars:
        def all(self):
            return [chunk]

    class _Result:
        def scalars(self):
            return _Scalars()

    session = AsyncMock()
    session.execute = AsyncMock(return_value=_Result())

    pipeline = MagicMock()
    pipeline.search = AsyncMock(side_effect=RuntimeError("no embeddings backend"))

    body = knowledge_routes.RAGSearchRequest(query="incident", top_k=3)
    with patch("nexus.knowledge.rag.RAGPipeline", return_value=pipeline):
        results = await knowledge_routes.rag_search(COMPANY_ID, body, session)

    assert len(results) == 1
    assert results[0].chunk_id == chunk.id
    assert results[0].score is None
    session.execute.assert_awaited_once()


@pytest.mark.asyncio
async def test_pipeline_search_uses_exec_available_on_session():
    """RAGPipeline.search() calls db.exec(), which the app session must expose."""
    from nexus.database import async_session_factory

    session = async_session_factory()
    try:
        assert hasattr(session, "exec"), "app sessions must support SQLModel exec()"
        assert hasattr(session, "execute")
    finally:
        await session.close()
