"""A failed provider or registry call must not put the failure's own text anywhere.

The reply, turn row, audit rows, logs, ledger records and stream events carry a stable server-owned
message and code. Only the exception class reaches the logs. Also pins the budget behavior of a
registry that cannot be built, through the real ``chat._call_llm``.
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from contextlib import asynccontextmanager
from types import SimpleNamespace

import anyio
import httpx
import pytest
from fastapi import HTTPException

import nexus.adapters.registry as registry_module
import nexus.database as database
import nexus.services.budget_service as budget_service
from nexus.api.routes import chat
from nexus.api.routes import sessions as api
from nexus.models.agent import Agent
from nexus.models.chat import ChatMessage
from nexus.models.chat_turn import ChatTurn
from nexus.models.governance import AuditLog
from nexus.models.notification import Notification
from nexus.runtime import chat_turns
from nexus.runtime.adapter import TaskResult
from tests.test_durable_chat_turns import _new_session, _rows, _send, _stream, db, t  # noqa: F401

pytestmark = pytest.mark.core_employee

MESSAGE = chat.PROVIDER_UNAVAILABLE_MESSAGE
CODE = chat.PROVIDER_UNAVAILABLE_CODE
SECRETS = [
    "super-secret-token",
    "secret-value",
    "sk-fake-secret-material",
    "qs-secret-value",
    "hunter2-pw",
    "SENTINEL-7f3a91",
]
HOSTILE_TEXT = (
    "Bearer super-secret-token api-key=secret-value sk-fake-secret-material "
    "https://res.openai.azure.com/openai/v1/chat/completions?key=qs-secret-value&sig=z "
    '{"error": {"password": "hunter2-pw"}} SENTINEL-7f3a91'
)


class ProviderBoomError(RuntimeError):
    """Carries hostile text; its class name is the one thing a log may repeat."""


def _boom() -> ProviderBoomError:
    return ProviderBoomError(HOSTILE_TEXT)


def _assert_clean(blob: str) -> None:
    for secret in SECRETS:
        assert secret not in blob, secret


class _Logs(logging.Handler):
    def __init__(self):
        super().__init__(logging.DEBUG)
        self.lines: list[str] = []
        self._format = logging.Formatter()

    def emit(self, record):
        self.lines.append(self._format.format(record))  # includes any traceback

    @property
    def text(self) -> str:
        return "\n".join(self.lines)


@pytest.fixture
def logs(monkeypatch):
    handler = _Logs()
    for logger in (chat.logger, chat_turns.logger):
        monkeypatch.setattr(logger, "disabled", False)
        monkeypatch.setattr(logger, "level", logging.DEBUG)
        logger.addHandler(handler)
    yield handler
    for logger in (chat.logger, chat_turns.logger):
        logger.removeHandler(handler)


@pytest.fixture(autouse=True)
def no_outbound_http(monkeypatch):
    def refuse(*a, **kw):
        raise AssertionError("an outbound HTTP client was built")

    monkeypatch.setattr(httpx.AsyncClient, "__init__", refuse)


class Ledger:
    """Replaces the budget service one level below ``_reserve_budget``/``_settle_budget``."""

    def __init__(self):
        self.reserved: list[tuple] = []  # (company_id, agent_id, session_id)
        self.holds: list[str] = []
        self.settle_calls: list[tuple] = []  # what _call_llm passed to _settle_budget
        self.committed: list[str] = []
        self.released: list[tuple] = []  # (hold, company_id)
        self.release_started = asyncio.Event()
        self.on_release = None

    @property
    def open_holds(self) -> list[str]:
        done = set(self.committed) | {hold for hold, _ in self.released}
        return [h for h in self.holds if h not in done]

    def blob(self) -> str:
        return json.dumps(
            [self.reserved, self.holds, self.settle_calls, self.committed, self.released],
            default=str,
        )


def _install_ledger(monkeypatch, fake_database: bool) -> Ledger:
    ledger = Ledger()
    count = iter(range(1, 100))

    async def reserve(agent, system_prompt, user_message, history, config, session_id=None):
        n = next(count)
        ledger.reserved.append((agent.company_id, agent.id, session_id))
        holds = [f"hold-{n}-company", f"hold-{n}-agent"]  # one per policy scope, like the real one
        ledger.holds.extend(holds)
        return holds

    real_settle = chat._settle_budget

    async def settle(rid, cost_cents, **kw):
        ledger.settle_calls.append((rid, cost_cents, {k: kw[k] for k in sorted(kw)}))
        await real_settle(rid, cost_cents, **kw)

    class Service:
        def __init__(self, session):
            self.company_id = getattr(session, "company_id", None)

        async def commit_reservation(self, hold, **kw):
            ledger.committed.append(hold)

        async def release_reservation(self, hold):
            ledger.release_started.set()
            if ledger.on_release is not None:
                await ledger.on_release()
            ledger.released.append((hold, self.company_id))

    @asynccontextmanager
    async def tenant_session(company_id):
        yield SimpleNamespace(company_id=company_id)

    async def connection(agent):
        return None

    async def remember(*a, **kw):
        return None

    monkeypatch.setattr(chat, "_reserve_budget", reserve)
    monkeypatch.setattr(chat, "_settle_budget", settle)
    monkeypatch.setattr(chat, "_resolve_connection", connection)
    monkeypatch.setattr(chat, "_remember_response", remember)
    if fake_database:  # the turn tests keep the real (SQLite) tenant session
        monkeypatch.setattr(database, "tenant_session", tenant_session)
    monkeypatch.setattr(budget_service, "BudgetService", Service)
    return ledger


@pytest.fixture
def ledger(monkeypatch):
    return _install_ledger(monkeypatch, fake_database=True)


@pytest.fixture
def turn_ledger(monkeypatch):
    return _install_ledger(monkeypatch, fake_database=False)


class _Adapter:
    """Stands in for any adapter that can be built; fails the way ``outcome`` says."""

    meters_budget = True  # forged on purpose; it must change nothing

    def __init__(self, spy, outcome=None):
        self.spy, self.outcome = spy, outcome

    async def create_session(self, agent_id, config):
        return SimpleNamespace(context=None, session_id=uuid.uuid4())

    async def execute_task(self, session, task_id, payload):
        self.spy.outbound += 1
        if isinstance(self.outcome, BaseException):
            raise self.outcome
        if isinstance(self.outcome, TaskResult):
            return self.outcome
        if isinstance(self.outcome, str):
            return TaskResult(
                task_id=task_id, agent_id=uuid.uuid4(), success=False, error=self.outcome
            )
        return TaskResult(task_id=task_id, agent_id=uuid.uuid4(), success=True, output="ok")

    async def terminate(self, session):
        pass


def _wire(monkeypatch, key="openai", construct=None, create=None, run=None, config=None):
    """Make the registry/adapter fail as given; returns a spy counting outbound work.

    ``construct`` is a list of exceptions, one per ``AdapterRegistry()`` call (the last repeats).
    """
    spy = SimpleNamespace(outbound=0, constructed=0, created=0)
    cfg = {"model": "gpt-4o", "api_key": "k", **(config or {})}
    monkeypatch.setattr(chat, "_resolve_adapter_type", lambda agent, conn: (key, cfg))

    class Registry:
        def __init__(self):
            spy.constructed += 1
            if construct:
                raise construct[min(spy.constructed, len(construct)) - 1]

        def is_self_metered(self, name):
            return False

        def create_adapter(self, name, config=None):
            spy.created += 1
            if create is not None:
                raise create
            return _Adapter(spy, run)

    monkeypatch.setattr(registry_module, "AdapterRegistry", Registry)
    return spy


def _agent(key="openai"):
    return Agent(company_id=uuid.uuid4(), name="A", role="engineer", adapter_type=key)


async def _call(agent, execution=None, turn_id=None):
    return await chat._call_llm(agent, "sys", "hi", [], turn_id=turn_id, execution=execution)


# --- registry construction failure: budget behavior ------------------------------------------


@pytest.mark.parametrize(
    "key,forged",
    [
        ("openai", {}),
        ("azure_openai_native", {}),
        ("azure_openai_native", {"meters_budget": True, "self_metered": True}),
    ],
)
async def test_registry_construction_failure_reserves_once_and_releases_once(
    monkeypatch, ledger, logs, key, forged
):
    spy = _wire(monkeypatch, key=key, construct=[_boom()], config=forged)
    agent, turn_id = _agent(key), uuid.uuid4()
    execution = {"execution_id": str(uuid.uuid4())}

    result = await _call(agent, execution, turn_id)

    assert result == (MESSAGE, "fallback", 0)  # the stable reply, the existing fallback model
    assert ledger.reserved == [(agent.company_id, agent.id, None)]  # exactly one reservation
    assert spy.created == spy.outbound == 0  # no adapter was built, no provider called
    assert ledger.committed == []  # nothing was billed
    assert [h for h, _ in ledger.released] == ledger.holds  # every hold released once, none twice
    assert {c for _, c in ledger.released} == {agent.company_id}  # in the agent's own tenant
    assert ledger.open_holds == []
    ((rid, cents, kw),) = ledger.settle_calls  # one settlement call, never two
    assert rid == ledger.holds and cents == 0 and kw["model"] is None
    assert kw["input_tokens"] == kw["output_tokens"] == 0 and kw["company_id"] == agent.company_id
    assert execution["adapter"] == key  # identity recorded before the failure
    line = next(entry for entry in logs.lines if "LLM call failed" in entry)
    for part in (CODE, f"adapter={key}", "exc_class=ProviderBoomError", str(agent.id), str(turn_id),
                 execution["execution_id"]):
        assert part in line


async def test_a_second_request_gets_its_own_reservation(monkeypatch, ledger):
    _wire(monkeypatch, construct=[_boom()])
    agent = _agent()
    await _call(agent)
    await _call(agent)
    assert len(ledger.reserved) == 2 and len(set(ledger.holds)) == 4
    assert sorted(h for h, _ in ledger.released) == sorted(ledger.holds)  # each exactly once
    assert ledger.open_holds == []


async def test_a_failure_after_billed_rounds_settles_their_cost(monkeypatch, ledger):
    # A tool loop that hit its iteration cap: the provider billed every finished round.
    failed = TaskResult(task_id=uuid.uuid4(), agent_id=uuid.uuid4(), success=False,
                        error="HERMES_NATIVE_LIMIT: too many model iterations",
                        input_tokens=40_000, output_tokens=800)
    _wire(monkeypatch, run=failed)
    text, _, tokens = await _call(_agent())
    assert text == MESSAGE and tokens == 0  # the reply is still the stable fallback
    ((rid, cents, kw),) = ledger.settle_calls
    assert cents >= 1 and kw["input_tokens"] == 40_000 and kw["output_tokens"] == 800
    assert kw["model"] == "gpt-4o"
    assert ledger.committed == ledger.holds and ledger.released == []  # billed, not released
    assert ledger.open_holds == []


async def test_cancellation_before_the_hold_leaves_nothing_to_leak(monkeypatch, ledger):
    _wire(monkeypatch, construct=[asyncio.CancelledError()])
    with pytest.raises(asyncio.CancelledError):
        await _call(_agent())
    assert ledger.reserved == [] and ledger.holds == [] and ledger.released == []


async def test_cancellation_after_the_hold_releases_it(monkeypatch, ledger):
    _wire(monkeypatch, construct=[_boom(), asyncio.CancelledError()])
    with pytest.raises(asyncio.CancelledError):
        await _call(_agent())
    assert len(ledger.reserved) == 1
    assert sorted(h for h, _ in ledger.released) == sorted(ledger.holds)
    assert ledger.open_holds == []


async def test_cancellation_while_the_release_runs_cannot_leak_the_hold(monkeypatch, ledger):
    _wire(monkeypatch, construct=[_boom()])
    scope = anyio.CancelScope()

    async def slow_release():
        scope.cancel()  # the request is cancelled while its hold is being released
        await anyio.sleep(0.01)  # an unshielded await would raise Cancelled here

    ledger.on_release = slow_release

    with scope:
        await _call(_agent())
    assert scope.cancel_called
    assert sorted(h for h, _ in ledger.released) == sorted(ledger.holds)  # finished, once each
    assert ledger.open_holds == []


# --- hostile failure text stays out of every user-visible and operational record --------------

FAILURES = {
    "registry construction": dict(construct=[_boom()]),
    "adapter construction": dict(create=_boom()),
    "provider call": dict(run=_boom()),
    "provider-reported error": dict(run=HOSTILE_TEXT),
}


@pytest.mark.parametrize("name", FAILURES)
async def test_a_failed_call_answers_with_the_stable_message_and_leaks_nothing(
    monkeypatch, ledger, logs, name
):
    _wire(monkeypatch, **FAILURES[name])
    text, model, tokens = await _call(_agent())
    assert text == MESSAGE and tokens == 0
    assert model == ("gpt-4o" if name == "provider-reported error" else "fallback")
    assert "ProviderBoom" not in text and "RuntimeError" not in text
    _assert_clean(json.dumps([text, model]) + logs.text + ledger.blob())
    assert CODE in logs.text  # operators still get the stable code
    if name != "provider-reported error":
        assert "exc_class=ProviderBoomError" in logs.text
    assert ledger.open_holds == []


async def test_a_failure_with_a_traceback_logs_no_message(monkeypatch, ledger, logs):
    _wire(monkeypatch, run=_boom())
    await _call(_agent())
    assert "Traceback" not in logs.text  # class-only diagnostics, not exc_info


# --- the durable turn: streaming failures, plain failures, callbacks --------------------------


class _Stream:
    """Yields ``chunks`` then raises ``exc``."""

    def __init__(self, chunks, exc):
        self.chunks, self.exc, self.terminated = chunks, exc, 0

    async def create_session(self, agent_id, config):
        return SimpleNamespace(context=None)

    async def stream_execute(self, session, task_id, request):
        for part in self.chunks:
            yield part
        raise self.exc

    async def terminate(self, session):
        self.terminated += 1


def _stream_wire(monkeypatch, adapter):
    monkeypatch.setattr(
        chat, "_resolve_adapter_type",
        lambda agent, conn=None: ("openai", {"model": "gpt-4o", "api_key": "k"}),
    )
    monkeypatch.setattr(registry_module.AdapterRegistry, "create_adapter", lambda self, k: adapter)


async def _stored(factory) -> str:
    rows = []
    for model in (ChatTurn, AuditLog, ChatMessage, Notification):
        rows += [r.model_dump() for r in await _rows(factory, model)]
    return json.dumps(rows, default=str)


@pytest.mark.parametrize(
    "chunks", [[], ["partial ", "text"]], ids=["before-first-delta", "after-partial"]
)
async def test_a_streaming_failure_is_sanitized_in_every_record(
    db, t, monkeypatch, turn_ledger, logs, chunks  # noqa: F811
):
    adapter = _Stream(chunks, _boom())
    _stream_wire(monkeypatch, adapter)

    async with db() as s:
        resp = await api.stream_message(
            t["acme_session"], api.SessionMessageRequest(prompt="hi"), t["acme"], s
        )
    events = await _stream(resp)
    await chat_turns.drain()

    failure = json.loads(next(e for e in events if '"type": "error"' in e).split("data: ", 1)[1])
    assert failure["text"] == MESSAGE and failure["turn_status"] == "failed"
    turn = (await _rows(db, ChatTurn))[0]
    assert (turn.status, turn.error_code, turn.error_message) == (
        "failed", "EXECUTION_ERROR", MESSAGE
    )
    assert [c for c in chunks if c not in "".join(events)] == []  # partial deltas still delivered
    blob = "".join(events) + await _stored(db) + logs.text + turn_ledger.blob()
    _assert_clean(blob)
    assert "ProviderBoom" not in "".join(events) + await _stored(db)  # no type in user-visible data
    assert "exc_class=ProviderBoomError" in logs.text and "EXECUTION_ERROR" in logs.text
    assert adapter.terminated == 1 and turn_ledger.open_holds == []
    assert len(turn_ledger.reserved) == 1  # one hold, settled once: billed only if text arrived
    billed = bool(chunks)
    assert bool(turn_ledger.committed) is billed and bool(turn_ledger.released) is not billed


async def test_a_plain_turn_failure_is_sanitized(db, t, monkeypatch, logs):  # noqa: F811
    async def failing(*a, **kw):
        raise _boom()

    monkeypatch.setattr(chat, "_call_llm", failing)
    with pytest.raises(HTTPException) as err:
        await _send(db, t["acme"], t["acme_session"])
    assert err.value.status_code == 500
    assert err.value.detail["code"] == "EXECUTION_ERROR" and err.value.detail["message"] == MESSAGE
    _assert_clean(json.dumps(err.value.detail) + await _stored(db) + logs.text)
    assert "ProviderBoom" not in json.dumps(err.value.detail) + await _stored(db)


async def test_a_callback_failure_reaches_the_same_sanitized_boundary(monkeypatch, ledger, logs):
    adapter = _Stream(["first"], _boom())
    _stream_wire(monkeypatch, adapter)
    agent = _agent()

    def callback(chunk):
        raise _boom()

    with pytest.raises(ProviderBoomError) as err:
        await chat._stream_llm(
            agent, "sys", "hi", [], session_id=uuid.uuid4(), context=None, execution={},
            on_chunk=callback,
        )
    stored = chat_turns._failure(err.value)
    assert stored["error_code"] == "EXECUTION_ERROR" and stored["error_message"] == MESSAGE
    _assert_clean(json.dumps(stored, default=str) + logs.text + ledger.blob())
    assert adapter.terminated == 1 and ledger.open_holds == []


async def test_a_budget_refusal_is_not_reported_as_a_provider_outage(db, t, monkeypatch):  # noqa: F811
    from nexus.models_router.preflight import BudgetExceededError

    async def refused(*a, **kw):
        raise BudgetExceededError("m", 0.01, 5.0, 5.0)

    monkeypatch.setattr(chat, "_call_llm", refused)
    with pytest.raises(HTTPException) as err:
        await _send(db, t["acme"], t["acme_session"])
    assert err.value.status_code == 429
    assert err.value.detail["code"] == "BUDGET_EXCEEDED"
    assert err.value.detail["message"] != MESSAGE
