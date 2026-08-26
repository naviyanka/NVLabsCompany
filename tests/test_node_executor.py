"""Tests for the node execution layer (W-02 spine)."""

import json
from unittest.mock import AsyncMock, patch

import pytest

from nexus.nodes.executor import (
    ExecutorRegistry,
    NodeExecutor,
    execute_node,
    get_default_registry,
)


def test_default_registry_binds_real_node_ids():
    registry = get_default_registry()
    node_ids = set(registry.executable_node_ids)
    for expected in (
        "ai-chat",
        "ai-summarize",
        "ai-translate",
        "ai-sentiment",
        "http-request",
        "msg-webhook-notify",
        "file-json-parse",
        "file-csv-parse",
    ):
        assert expected in node_ids
        # Every executable id must exist in the catalog too
        from nexus.nodes.registry import NodeRegistry

        assert NodeRegistry().get(expected) is not None


@pytest.mark.asyncio
async def test_json_parse_node():
    result = await execute_node("file-json-parse", {"text": '{"a": 1}'})
    assert result.success is True
    assert result.outputs["data"] == {"a": 1}


@pytest.mark.asyncio
async def test_csv_parse_node():
    result = await execute_node(
        "file-csv-parse", {"content": "name,age\nAda,36\nAlan,41"}
    )
    assert result.success is True
    assert result.outputs["headers"] == ["name", "age"]
    assert result.outputs["rows"][0] == {"name": "Ada", "age": "36"}


@pytest.mark.asyncio
async def test_missing_required_param_reports_error():
    result = await execute_node("file-json-parse", {})
    assert result.success is False
    assert "text" in result.error


@pytest.mark.asyncio
async def test_unregistered_node_returns_error():
    result = await execute_node("db-postgres-query", {"query": "select 1"})
    assert result.success is False
    assert "No executor registered" in result.error


@pytest.mark.asyncio
async def test_timeout_enforced():
    slow_registry = ExecutorRegistry()

    async def slow(params):
        import asyncio

        await asyncio.sleep(5)

    slow_registry.register(NodeExecutor(node_ids=["slow-node"], run=slow))
    result = await execute_node("slow-node", {}, registry=slow_registry, timeout_seconds=0.05)
    assert result.success is False
    assert "timed out" in result.error


@pytest.mark.asyncio
async def test_http_request_blocks_private_urls(monkeypatch):
    called = {"httpx": False}

    def _boom(*args, **kwargs):
        called["httpx"] = True

    monkeypatch.setattr("httpx.AsyncClient.request", _boom)

    result = await execute_node(
        "http-request", {"url": "http://169.254.169.254/latest/meta-data"}
    )
    assert result.success is False
    assert "SSRF" in result.error
    assert called["httpx"] is False


@pytest.mark.asyncio
async def test_http_request_success(monkeypatch):
    class _Resp:
        status_code = 200
        headers = {"content-type": "application/json"}

        def json(self):
            return {"ok": True}

    class _Client:
        def __init__(self, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def request(self, method, url, **kwargs):
            return _Resp()

    monkeypatch.setattr("httpx.AsyncClient", _Client)

    result = await execute_node(
        "http-request",
        {"url": "https://example.com/api", "method": "GET"},
    )
    assert result.success is True
    assert result.outputs["status"] == 200
    assert result.outputs["body"] == {"ok": True}


@pytest.mark.asyncio
async def test_ai_chat_requires_api_key(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    result = await execute_node("ai-chat", {"prompt": "hi"})
    assert result.success is False
    assert "API key" in result.error


@pytest.mark.asyncio
async def test_sentiment_parses_llm_word(monkeypatch):
    from nexus.nodes import executor as ex

    async def fake_llm(prompt, model=None):
        return "POSITIVE.", 12

    monkeypatch.setattr(ex, "_llm_prompt", fake_llm)
    result = await execute_node("ai-sentiment", {"text": "I love this"})
    assert result.success is True
    assert result.outputs["sentiment"] == "positive"
