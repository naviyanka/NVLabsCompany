"""WP-22b: Connection abstraction acceptance tests (non-Postgres subset).

Runnable without a database:
- dispatch: an agent with a Connection resolves to the connection's base_url
  and wire-format registry key (was the chat.py:725 refusal path at baseline).
- anthropic per-session api_base override.
- key-leak: the connection response never carries a key value.
- SSRF: private hosts are rejected unless allowlisted.

The RLS isolation test (`test_connection_rls_isolates_companies`) requires a
real Postgres and lives in tests/test_postgres_integration.py (R10).
"""

import asyncio
import uuid

import httpx
import pytest

from nexus.adapters.anthropic_adapter import AnthropicAdapter
from nexus.api.routes.chat import _resolve_adapter_type
from nexus.api.routes.connections import ConnectionCreate, _host_allowlisted, _to_response
from nexus.models.connection import LLMConnection


def _run(coro):
    return asyncio.run(coro)


class _FakeAgent:
    def __init__(self, adapter_type=None, model=None):
        self.adapter_type = adapter_type
        self.model = model


def test_agent_with_connection_dispatches_to_connection_base_url():
    """A resolved Connection forces wire_format + base_url + api_key.

    At baseline resolve_provider took no connection and chat.py returned the
    'provider API key is not set' refusal when OPENAI_API_KEY was empty.
    """
    connection = {
        "wire_format": "openai",
        "base_url": "http://gateway.internal:20128/v1",
        "api_key": "sk-from-connection",
    }
    key, config = _resolve_adapter_type(_FakeAgent("anthropic", "gpt-4o"), connection)

    assert key == "openai"  # wire_format wins over the agent's adapter_type
    assert config["api_base"] == "http://gateway.internal:20128/v1"
    assert config["api_key"] == "sk-from-connection"
    assert config["model"] == "gpt-4o"


def test_anthropic_adapter_honours_session_api_base():
    """anthropic_adapter POSTs to the per-session api_base, not the hard-coded one.

    Fails at baseline (self._api_base hard-coded at L35, used at L121/L315).
    """
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        return httpx.Response(
            200,
            json={
                "content": [{"type": "text", "text": "ok"}],
                "usage": {"input_tokens": 1, "output_tokens": 1},
                "model": "claude-x",
            },
        )

    transport = httpx.MockTransport(handler)
    real_init = httpx.AsyncClient.__init__

    def _init(self, *a, **k):
        k["transport"] = transport
        real_init(self, *a, **k)

    async def go():
        adapter = AnthropicAdapter()
        session = await adapter.create_session(
            uuid.uuid4(),
            {
                "api_key": "sk-x",
                "model": "claude-x",
                "api_base": "http://gateway.internal:20128/v1",
            },
        )
        await adapter.execute_task(session, uuid.uuid4(), {"prompt": "hi"})

    import unittest.mock as m

    with m.patch.object(httpx.AsyncClient, "__init__", _init):
        _run(go())

    assert seen["url"].startswith("http://gateway.internal:20128/v1/messages")


def test_connection_response_never_leaks_api_key():
    """The response model exposes only presence flags, never key material."""
    conn = LLMConnection(
        company_id=uuid.uuid4(),
        name="gw",
        base_url="https://example.com/v1",
        wire_format="openai",
        api_key_ref="my-secret-name",
        mgmt_key_ref=None,
    )
    resp = _to_response(conn)
    dumped = resp.model_dump()

    assert dumped["has_api_key"] is True
    assert dumped["has_mgmt_key"] is False
    assert "api_key_ref" not in dumped
    assert "my-secret-name" not in str(dumped)


def test_connection_create_rejects_private_host_by_default(monkeypatch):
    """A private-IP base_url is rejected by SSRF guard unless allowlisted."""
    from fastapi import HTTPException
    from nexus.api.routes import connections as conn_mod

    # allowlist empty -> guard runs; a literal private IP must be blocked
    monkeypatch.setattr(conn_mod.settings, "llm_connection_host_allowlist", "")
    assert _host_allowlisted("http://10.0.0.5:20128/v1") is False

    body = ConnectionCreate(
        name="gw", base_url="http://10.0.0.5:20128/v1", wire_format="openai"
    )

    async def go():
        return await conn_mod.create_connection(
            company_id=uuid.uuid4(), body=body, db=None, principal=None
        )

    with pytest.raises(HTTPException) as exc:
        _run(go())
    assert exc.value.status_code == 400

    # allowlisting the host makes the guard pass for that host
    monkeypatch.setattr(
        conn_mod.settings, "llm_connection_host_allowlist", "10.0.0.5"
    )
    assert _host_allowlisted("http://10.0.0.5:20128/v1") is True
