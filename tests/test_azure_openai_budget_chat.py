"""The chat layer must not reserve budget a second time for a self-metering adapter.

Separate from test_azure_openai_native.py because the employee-work fixtures there replace
``chat._call_llm``; here the real function runs with its collaborators stubbed.
"""

import uuid

import pytest

from nexus.api.routes import chat
from nexus.models.agent import Agent
from nexus.services.streaming_budget import SELF_METERED


@pytest.mark.parametrize("key,reserves", [("azure_openai_native", False), ("anthropic", True)])
async def test_self_metered_adapters_skip_the_chat_reservation(monkeypatch, key, reserves):
    assert "azure_openai_native" in SELF_METERED and "anthropic" not in SELF_METERED
    reserved = []

    async def spy(*a, **kw):
        reserved.append(1)

    async def connection(agent):
        return None

    monkeypatch.setattr(chat, "_reserve_budget", spy)
    monkeypatch.setattr(chat, "_resolve_connection", connection)
    config = {"model": "m", "api_key": "k"}
    monkeypatch.setattr(chat, "_resolve_adapter_type", lambda agent, conn: (key, config))
    agent = Agent(company_id=uuid.uuid4(), name="A", role="engineer", adapter_type=key)
    try:
        await chat._call_llm(agent, "sys", "hi", [])
    except Exception:  # noqa: BLE001 -- only the reservation decision is under test
        pass
    assert bool(reserved) is reserves


class _Stream:
    """Stands in for an anthropic/openai adapter: yields ``chunks`` then raises ``then``."""

    def __init__(self, chunks, then=None):
        self.chunks, self.then, self.started, self.terminated = chunks, then, False, 0

    async def create_session(self, agent_id, config):
        self.started = True
        return type("S", (), {"context": None})()

    async def stream_execute(self, session, task_id, request):
        for part in self.chunks:
            yield part
        if self.then:
            raise self.then

    async def terminate(self, session):
        self.terminated += 1


def _wire(monkeypatch, adapter, refuse=False):
    from fastapi import HTTPException

    from nexus.adapters.registry import AdapterRegistry

    log = {"reserved": 0, "settled": []}

    async def reserve(*a, **kw):
        log["reserved"] += 1
        if refuse:
            raise HTTPException(status_code=402, detail="budget")
        return "hold"

    async def settle(rid, cost_cents, **kw):
        log["settled"].append((rid, cost_cents, kw))

    async def connection(agent):
        return None

    monkeypatch.setattr(chat, "_reserve_budget", reserve)
    monkeypatch.setattr(chat, "_settle_budget", settle)
    monkeypatch.setattr(chat, "_resolve_connection", connection)
    config = {"model": "gpt-4o", "api_key": "k"}
    monkeypatch.setattr(chat, "_resolve_adapter_type", lambda agent, conn: ("openai", config))
    monkeypatch.setattr(AdapterRegistry, "create_adapter", lambda self, key: adapter)
    return log


async def _stream(adapter_agent=None):
    agent = Agent(company_id=uuid.uuid4(), name="A", role="engineer", adapter_type="openai")
    got = []
    out = await chat._stream_llm(agent, "sys", "hi", [], session_id=uuid.uuid4(), context=None,
                                 execution={}, on_chunk=got.append)
    return out, got


async def test_a_streamed_reply_is_refused_before_any_outbound_work_when_over_budget(monkeypatch):
    from fastapi import HTTPException

    adapter = _Stream(["never"])
    log = _wire(monkeypatch, adapter, refuse=True)
    with pytest.raises(HTTPException):
        await _stream()
    assert log["reserved"] == 1 and not adapter.started and log["settled"] == []


async def test_a_streamed_reply_settles_a_nonzero_estimate(monkeypatch):
    adapter = _Stream(["hello ", "there"])
    log = _wire(monkeypatch, adapter)
    (text, _, _), got = await _stream()
    assert text == "hello there" and got == ["hello ", "there"] and adapter.terminated == 1
    ((rid, cents, kw),) = log["settled"]
    assert rid == "hold" and cents >= 1 and kw["output_tokens"] >= 1


async def test_a_failed_or_cancelled_stream_still_settles_what_arrived(monkeypatch):
    adapter = _Stream(["partial"], then=RuntimeError("boom"))
    log = _wire(monkeypatch, adapter)
    with pytest.raises(RuntimeError):
        await _stream()
    ((_, cents, _),) = log["settled"]
    assert cents >= 1 and adapter.terminated == 1


async def test_a_stream_that_produced_nothing_releases_the_hold(monkeypatch):
    adapter = _Stream([], then=RuntimeError("refused"))
    log = _wire(monkeypatch, adapter)
    with pytest.raises(RuntimeError):
        await _stream()
    ((_, cents, _),) = log["settled"]
    assert cents == 0
