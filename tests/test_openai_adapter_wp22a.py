"""WP-22a: OpenAI adapter idempotency-key regression + streaming smoke.

Baseline `68144249` fails these:
- `_do_execute` builds an `Idempotency-Key` header with `hashlib.sha256(...)`
  but the module never `import hashlib`, so every non-streaming call raises
  `NameError: name 'hashlib' is not defined` (WP-22a).
- `stream_execute` had no test exercising the SSE `data:`/`[DONE]` path.

R10: gateway/HTTP interaction is mocked via `httpx.MockTransport`; no network.
R1: each test invokes the named public method, not merely imports it.
"""

import uuid

import httpx
import pytest

from nexus.adapters.openai_adapter import OpenAIAdapter


AGENT_ID = uuid.UUID("abcdef01-abcd-abcd-abcd-abcdef012345")
TASK_ID = uuid.UUID("99999999-9999-9999-9999-999999999999")

_COMPLETION = {
    "choices": [{"message": {"role": "assistant", "content": "hi there"}}],
    "usage": {"prompt_tokens": 7, "completion_tokens": 3},
}


def _mock_client(handler):
    """Return a patched httpx.AsyncClient bound to a MockTransport handler."""
    transport = httpx.MockTransport(handler)
    real_init = httpx.AsyncClient.__init__

    def _init(self, *args, **kwargs):
        kwargs["transport"] = transport
        real_init(self, *args, **kwargs)

    return _init


async def _session(adapter):
    return await adapter.create_session(
        AGENT_ID, {"api_key": "sk-test", "model": "gpt-4o"}
    )


async def test_do_execute_sends_idempotency_key_and_returns_result(monkeypatch):
    """execute_task succeeds and sends a sha256 Idempotency-Key header.

    Fails at baseline with NameError (no `import hashlib`).
    """
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["idempotency"] = request.headers.get("Idempotency-Key")
        return httpx.Response(200, json=_COMPLETION)

    monkeypatch.setattr(httpx.AsyncClient, "__init__", _mock_client(handler))

    adapter = OpenAIAdapter()
    session = await _session(adapter)
    result = await adapter.execute_task(session, TASK_ID, {"prompt": "hello"})

    assert result.success is True
    assert result.output == "hi there"
    assert result.input_tokens == 7
    assert result.output_tokens == 3
    # header present and shaped `<session_id>:<16 hex>`
    key = seen["idempotency"]
    assert key is not None
    prefix, _, digest = key.rpartition(":")
    assert prefix == session.session_id
    assert len(digest) == 16
    int(digest, 16)  # valid hex


async def test_stream_execute_yields_chunks_and_stops_on_done(monkeypatch):
    """stream_execute yields SSE content deltas and stops at [DONE]."""

    def handler(request: httpx.Request) -> httpx.Response:
        body = (
            'data: {"choices":[{"delta":{"content":"foo"}}]}\n'
            'data: {"choices":[{"delta":{"content":"bar"}}]}\n'
            "data: [DONE]\n"
        )
        return httpx.Response(200, text=body)

    monkeypatch.setattr(httpx.AsyncClient, "__init__", _mock_client(handler))

    adapter = OpenAIAdapter()
    session = await _session(adapter)

    chunks = [
        c
        async for c in adapter.stream_execute(session, TASK_ID, {"prompt": "hello"})
    ]

    assert chunks == ["foo", "bar"]
