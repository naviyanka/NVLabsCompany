"""The chat layer must not reserve budget a second time for a self-metering adapter.

Separate from test_azure_openai_native.py because the employee-work fixtures there replace
``chat._call_llm``; here the real function runs with its collaborators stubbed.
"""

import asyncio
import uuid
from types import SimpleNamespace

import pytest

from nexus.adapters.base import BaseAdapter
from nexus.adapters.registry import AdapterRegistry
from nexus.api.routes import chat
from nexus.models.agent import Agent
from nexus.runtime.adapter import TaskResult

SELF_METERING = ["azure_openai_native"]
# Every other default adapter type: the chat layer reserves for these, exactly once.
METERED_BY_CHAT = [
    k for k in AdapterRegistry().get_adapter_types() if k not in SELF_METERING
]


class _Adapter:
    """Stands in for any adapter. ``meters_budget`` is forged on purpose: it must change nothing."""

    meters_budget = True

    def __init__(self, outcome):
        self.outcome = outcome

    async def create_session(self, agent_id, config):
        return SimpleNamespace(context=None, session_id=uuid.uuid4())

    async def execute_task(self, session, task_id, payload):
        if isinstance(self.outcome, BaseException):
            raise self.outcome
        return TaskResult(
            task_id=task_id, agent_id=uuid.uuid4(), success=True, output="hi",
            input_tokens=3, output_tokens=2,
        )

    async def terminate(self, session):
        pass


def _call(monkeypatch, key, outcome, config=None):
    """Run the real ``chat._call_llm``; returns the reservation and settlement logs."""
    log = {"reserved": 0, "settled": []}

    async def reserve(*a, **kw):
        log["reserved"] += 1
        return "hold"

    async def settle(rid, cost_cents, **kw):
        log["settled"].append((rid, cost_cents))

    async def connection(agent):
        return None

    async def remember(*a, **kw):
        return None

    monkeypatch.setattr(chat, "_reserve_budget", reserve)
    monkeypatch.setattr(chat, "_settle_budget", settle)
    monkeypatch.setattr(chat, "_resolve_connection", connection)
    monkeypatch.setattr(chat, "_remember_response", remember)
    cfg = {"model": "gpt-4o", "api_key": "k", **(config or {})}
    monkeypatch.setattr(chat, "_resolve_adapter_type", lambda agent, conn: (key, cfg))
    monkeypatch.setattr(
        AdapterRegistry, "create_adapter", lambda self, k, config=None: _Adapter(outcome)
    )
    agent = Agent(company_id=uuid.uuid4(), name="A", role="engineer", adapter_type=key)
    return log, chat._call_llm(agent, "sys", "hi", [])


@pytest.mark.parametrize("key", SELF_METERING)
async def test_a_self_metering_adapter_gets_no_chat_reservation(monkeypatch, key):
    log, call = _call(monkeypatch, key, None)
    text, _, tokens = await call
    assert text == "hi" and tokens == 5
    assert log["reserved"] == 0  # the adapter reserves and settles every round itself


@pytest.mark.parametrize("key", METERED_BY_CHAT)
@pytest.mark.parametrize("outcome", [None, RuntimeError("provider down"), asyncio.CancelledError()])
async def test_every_other_adapter_reserves_once_and_always_settles_once(monkeypatch, key, outcome):
    log, call = _call(monkeypatch, key, outcome)
    if isinstance(outcome, asyncio.CancelledError):
        with pytest.raises(asyncio.CancelledError):
            await call
    else:
        await call  # a provider error is answered in character, not raised
    assert log["reserved"] == 1
    ((rid, cents),) = log["settled"]  # settled or released exactly once: never left open
    assert rid == "hold" and (cents > 0) is (outcome is None)


@pytest.mark.parametrize("key", METERED_BY_CHAT)
async def test_a_forged_capability_cannot_skip_budgeting(monkeypatch, key):
    # The adapter class claims meters_budget and the agent's config claims it too.
    forged = {"meters_budget": True, "self_metered": True, "adapter_config": {"meters_budget": 1}}
    log, call = _call(monkeypatch, key, None, config=forged)
    await call
    assert log["reserved"] == 1 and len(log["settled"]) == 1


def test_self_metering_is_only_an_internal_registration():
    registry = AdapterRegistry()
    assert [k for k in registry.get_adapter_types() if registry.is_self_metered(k)] == SELF_METERING
    assert registry.is_self_metered("unknown") is False

    class Claims(BaseAdapter):  # claims the attribute but is registered without the capability
        meters_budget = True

    class Silent(BaseAdapter):
        pass

    registry.register_adapter("claims", Claims)
    assert registry.is_self_metered("claims") is False
    with pytest.raises(TypeError):  # the capability needs the class to meter, not just a flag
        registry.register_adapter("silent", Silent, self_metered=True)
    registry.register_adapter("claims", Claims, self_metered=True)
    assert registry.is_self_metered("claims") is True
    registry.register_adapter("claims", Silent)  # re-registering drops the capability
    assert registry.is_self_metered("claims") is False


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
