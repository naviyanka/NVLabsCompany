"""Concurrent employee chat: turns of different employees overlap, turns of one
session queue in the database, and cancelling one turn stops only its own CLI
process.

Each fake CLI process blocks until its test releases it, so overlap is shown
by state (both processes spawned, one reply returned while the other is still
running) rather than by timing. No real CLI is spawned.
"""

from __future__ import annotations

import asyncio
import threading
import uuid
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
from fastapi import FastAPI, Request
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlmodel import SQLModel, select

import nexus.adapters.cli_registry as cli_registry_mod
import nexus.models  # noqa: F401 -- registers every table on SQLModel.metadata
import nexus.runtime.orchestrator as orchestrator
from nexus.adapters.cli_registry import CLIRegistry
from nexus.api.routes import chat as chat_routes
from nexus.api.routes import sessions as session_routes
from nexus.auth.principal import Principal
from nexus.governance.bulkhead import TenantBulkhead
from nexus.models.agent import Agent
from nexus.models.chat import ChatMessage
from nexus.models.chat_turn import ChatTurn
from nexus.models.company import Company
from nexus.models.governance import AuditLog
from nexus.runtime import chat_turns

pytestmark = pytest.mark.core_employee

FAKE_PATH = {"claude": "/bin/claude", "agy": "/bin/agy"}
WAIT = 10  # upper bound for a sync point; never reached when the code is right


class FakeCLIs:
    """Spawns fake CLI processes that each wait for their own release."""

    def __init__(self) -> None:
        self.spawned: list[tuple[str, MagicMock]] = []
        self.gates: dict[int, asyncio.Event] = {}
        self.exit_codes: dict[int, int] = {}  # index -> non-zero exit for a failing CLI
        self._changed = asyncio.Event()

    async def spawn(self, *cmd, **kwargs):
        index = len(self.spawned)
        gate = self.gates[index] = asyncio.Event()
        backend = cmd[0].rsplit("/", 1)[-1]
        proc = MagicMock()
        proc.pid = None
        proc.returncode = None
        proc.stdin = MagicMock(write=MagicMock(), drain=AsyncMock(), close=MagicMock())
        code = self.exit_codes.get(index, 0)
        out = [f'{{"employee":"{backend}","turn":{index}}}'.encode(), b""] if code == 0 else [b""]

        async def read_stdout(_n):
            await gate.wait()
            return out.pop(0) if out else b""

        async def wait():
            await gate.wait()
            proc.returncode = code
            return code

        proc.stdout = MagicMock(read=read_stdout)
        proc.stderr = MagicMock(read=AsyncMock(side_effect=[b"model overloaded" if code else b"", b""]))
        proc.wait = wait
        self.spawned.append((backend, proc))
        self._changed.set()
        return proc

    async def until_spawned(self, n: int) -> None:
        async def _wait():
            while len(self.spawned) < n:
                self._changed.clear()
                await self._changed.wait()

        await asyncio.wait_for(_wait(), WAIT)

    def release(self, index: int) -> None:
        self.gates[index].set()


@pytest.fixture
async def world(tmp_path, monkeypatch):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'chat.db'}")
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    import nexus.database as database

    monkeypatch.setattr(database, "async_session_factory", factory)
    monkeypatch.setattr(cli_registry_mod.shutil, "which", lambda name: FAKE_PATH.get(name))
    monkeypatch.setattr(cli_registry_mod, "_shared_registry", None)
    monkeypatch.setattr(CLIRegistry, "probe_version", lambda self, bid, timeout=5: "1.0.0")

    async def fake_prompt(db, agent, company_id, prompt):
        return "system"

    monkeypatch.setattr(chat_routes, "_build_chat_prompt", fake_prompt)
    monkeypatch.setattr(chat_routes, "_resolve_connection", AsyncMock(return_value=None))
    monkeypatch.setattr(chat_routes, "_reserve_budget", AsyncMock(return_value=None))
    monkeypatch.setattr(chat_routes, "_settle_budget", AsyncMock())
    monkeypatch.setattr(chat_routes, "_remember_response", AsyncMock(return_value=0))
    monkeypatch.setattr(chat_routes, "_conversations", {})
    monkeypatch.setattr(chat_routes, "_cache_loaded_at", {})
    monkeypatch.setattr(orchestrator, "_tenant_bulkhead", TenantBulkhead())
    clis = FakeCLIs()
    monkeypatch.setattr("nexus.adapters.cli_adapter.asyncio.create_subprocess_exec", clis.spawn)

    acme = Company(name="Acme")
    async with factory() as db:
        db.add(acme)
        await db.flush()
        claude = Agent(company_id=acme.id, name="Claude Emp", role="engineer",
                       adapter_type="cli", adapter_config={"backend": "claude"}, model="")
        agy = Agent(company_id=acme.id, name="Agy Emp", role="engineer",
                    adapter_type="cli", adapter_config={"backend": "agy"}, model="")
        db.add_all([claude, agy])
        await db.commit()

    principal = Principal(kind="user", company_id=acme.id, role="manager", user_id=uuid.uuid4())
    app = FastAPI()
    app.include_router(chat_routes.router)
    app.include_router(session_routes.router)

    @app.middleware("http")
    async def as_principal(request: Request, call_next):
        request.state.principal = principal
        return await call_next(request)

    client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")
    yield {"client": client, "factory": factory, "acme": acme.id,
           "claude": claude.id, "agy": agy.id, "clis": clis}
    await client.aclose()
    await chat_turns.drain()
    await engine.dispose()


async def _messages(w, agent_id):
    async with w["factory"]() as db:
        rows = (await db.execute(
            select(ChatMessage).where(ChatMessage.agent_id == agent_id).order_by(ChatMessage.seq)
        )).scalars().all()
    return [(r.sender, r.text, r.session_id) for r in rows]


async def test_two_employees_chat_at_the_same_time(world):
    c, clis = world["client"], world["clis"]
    slow = asyncio.create_task(c.post(f"/api/v1/agents/{world['claude']}/chat", json={"prompt": "wait"}))
    await clis.until_spawned(1)
    fast = asyncio.create_task(c.post(f"/api/v1/agents/{world['agy']}/chat", json={"prompt": "now"}))
    # Agy's CLI starts while Claude's is still running: no global lock, and
    # no open write transaction from the first request blocks the second.
    await clis.until_spawned(2)
    assert [b for b, _ in clis.spawned] == ["claude", "agy"]

    clis.release(1)
    agy_resp = await asyncio.wait_for(fast, WAIT)
    assert not slow.done()
    clis.release(0)
    claude_resp = await asyncio.wait_for(slow, WAIT)

    agy_body, claude_body = agy_resp.json(), claude_resp.json()
    assert agy_resp.status_code == claude_resp.status_code == 200
    assert agy_body["backend_used"] == "agy" and '"employee":"agy"' in agy_body["message"]["text"]
    assert claude_body["backend_used"] == "claude"
    assert '"employee":"claude"' in claude_body["message"]["text"]
    assert agy_body["execution_id"] and agy_body["execution_id"] != claude_body["execution_id"]
    # Each transcript holds only its own turn.
    assert [m[:2] for m in await _messages(world, world["agy"])] == [
        ("user", "now"), ("agent", agy_body["message"]["text"])]
    assert [m[:2] for m in await _messages(world, world["claude"])] == [
        ("user", "wait"), ("agent", claude_body["message"]["text"])]
    # The audit trail ties each turn to its agent, session and execution.
    async with world["factory"]() as db:
        audits = (await db.execute(
            select(AuditLog).where(AuditLog.action.like("chat.%"))
        )).scalars().all()
    by_exec = {(a.details["execution_id"], a.action) for a in audits}
    for body in (agy_body, claude_body):
        assert {(body["execution_id"], "chat.message_sent"),
                (body["execution_id"], "chat.response_generated")} <= by_exec


async def test_stream_and_plain_chat_overlap(world):
    c, clis = world["client"], world["clis"]
    stream = asyncio.create_task(
        c.post(f"/api/v1/agents/{world['claude']}/chat/stream", json={"prompt": "wait"}))
    await clis.until_spawned(1)
    plain = asyncio.create_task(c.post(f"/api/v1/agents/{world['agy']}/chat", json={"prompt": "now"}))
    await clis.until_spawned(2)
    clis.release(1)
    assert (await asyncio.wait_for(plain, WAIT)).json()["backend_used"] == "agy"
    assert not stream.done()
    clis.release(0)
    body = (await asyncio.wait_for(stream, WAIT)).text
    assert '"backend_used": "claude"' in body and '"execution_id"' in body


async def test_user_message_is_committed_before_the_cli_runs(world):
    c, clis = world["client"], world["clis"]
    turn = asyncio.create_task(c.post(f"/api/v1/agents/{world['claude']}/chat", json={"prompt": "hi"}))
    await clis.until_spawned(1)
    # Readable from another connection while the CLI is still running.
    assert [m[:2] for m in await _messages(world, world["claude"])] == [("user", "hi")]
    clis.release(0)
    assert (await asyncio.wait_for(turn, WAIT)).status_code == 200


async def test_turns_in_one_session_run_in_order(world):
    c, clis = world["client"], world["clis"]
    resp = await c.post(f"/api/v1/agents/{world['claude']}/sessions", json={})
    assert resp.status_code in (200, 201), resp.text
    sid = resp.json()["id"]
    first = asyncio.create_task(c.post(f"/api/v1/sessions/{sid}/messages", json={"prompt": "one"}))
    await clis.until_spawned(1)
    second = asyncio.create_task(c.post(f"/api/v1/sessions/{sid}/messages", json={"prompt": "two"}))

    async def turns():
        async with world["factory"]() as db:
            return (await db.execute(
                select(ChatTurn).where(ChatTurn.session_id == uuid.UUID(sid))
                .order_by(ChatTurn.turn_seq)
            )).scalars().all()

    async def queued():
        while len(await turns()) < 2:
            await asyncio.sleep(0)

    await asyncio.wait_for(queued(), WAIT)
    running, waiting = await turns()
    assert (running.status, waiting.status) == ("running", "queued")
    assert len(clis.spawned) == 1  # the second turn waits for the first
    # The order lives in the database: no worker, here or elsewhere, may claim
    # the second turn while the first is unfinished.
    assert await chat_turns.claim(waiting.id, world["acme"], "another-worker") is None

    clis.release(0)
    one = (await asyncio.wait_for(first, WAIT)).json()
    await clis.until_spawned(2)
    clis.release(1)
    two = (await asyncio.wait_for(second, WAIT)).json()
    assert one["seq"] < two["seq"]
    assert one["backend_used"] == two["backend_used"] == "claude"
    assert one["execution_id"] != two["execution_id"]
    assert [(t.status, t.attempt_count) for t in await turns()] == [
        ("completed", 1), ("completed", 1)]


async def test_cancelling_one_turn_stops_only_its_process(world, monkeypatch):
    clis = world["clis"]
    killed = []

    async def fake_kill(proc):
        killed.append(proc)

    monkeypatch.setattr("nexus.adapters.cli_adapter._terminate_tree", fake_kill)
    async with world["factory"]() as db:
        claude = await db.get(Agent, world["claude"])
        agy = await db.get(Agent, world["agy"])
    a = asyncio.create_task(chat_routes._call_llm(claude, "s", "wait", []))
    await clis.until_spawned(1)
    b = asyncio.create_task(chat_routes._call_llm(agy, "s", "now", []))
    await clis.until_spawned(2)

    a.cancel()
    with pytest.raises(asyncio.CancelledError):
        await a
    assert killed == [clis.spawned[0][1]]
    clis.release(1)
    text, _, _ = await asyncio.wait_for(b, WAIT)
    assert '"employee":"agy"' in text
    chat_routes._settle_budget.assert_awaited()  # the cancelled turn still settled


async def test_one_failing_cli_leaves_the_other_turn_intact(world):
    c, clis = world["client"], world["clis"]
    clis.exit_codes[0] = 1
    broken = asyncio.create_task(c.post(f"/api/v1/agents/{world['claude']}/chat", json={"prompt": "fail"}))
    await clis.until_spawned(1)
    fine = asyncio.create_task(c.post(f"/api/v1/agents/{world['agy']}/chat", json={"prompt": "now"}))
    await clis.until_spawned(2)

    clis.release(0)
    failed = await asyncio.wait_for(broken, WAIT)
    assert not fine.done()  # Claude's failure did not cancel or fail Agy's turn
    clis.release(1)
    ok = await asyncio.wait_for(fine, WAIT)

    assert ok.status_code == 200 and ok.json()["backend_used"] == "agy"
    assert '"employee":"agy"' in ok.json()["message"]["text"]
    assert failed.status_code >= 400 or "error" in failed.text.lower(), failed.text
    assert "agy" not in failed.text
    assert [m[:2] for m in await _messages(world, world["agy"])] == [
        ("user", "now"), ("agent", ok.json()["message"]["text"])]


async def test_saturated_tenant_gets_202_and_runs_later(world, monkeypatch):
    monkeypatch.setattr(orchestrator, "_tenant_bulkhead", TenantBulkhead(per_tenant=1))
    c, clis = world["client"], world["clis"]
    busy = asyncio.create_task(c.post(f"/api/v1/agents/{world['claude']}/chat", json={"prompt": "a"}))
    await clis.until_spawned(1)
    resp = await c.post(f"/api/v1/agents/{world['agy']}/chat", json={"prompt": "b"})
    # The prompt is stored and queued, not refused: the answer is 202, not 429.
    assert resp.status_code == 202, resp.text
    pending = resp.json()
    assert pending["status"] == "queued" and pending["retry_after"] >= 1
    assert resp.headers["retry-after"] == str(pending["retry_after"])
    assert [m[:2] for m in await _messages(world, world["agy"])] == [("user", "b")]
    assert len(clis.spawned) == 1

    clis.release(0)
    assert (await asyncio.wait_for(busy, WAIT)).status_code == 200
    # Capacity is free again: the queued turn runs without being resent.
    await clis.until_spawned(2)
    clis.release(1)
    await chat_turns.drain()
    turn = (await c.get(
        f"/api/v1/agent-sessions/{pending['session_id']}/turns/{pending['turn_id']}")).json()
    assert turn["status"] == "completed" and turn["backend_used"] == "agy"
    assert '"employee":"agy"' in turn["message"]["text"]


async def test_version_probe_runs_off_the_event_loop(world, monkeypatch):
    threads = []

    def probe(self, backend_id, timeout=5):
        threads.append(threading.current_thread())
        return "1.0.0"

    monkeypatch.setattr(CLIRegistry, "probe_version", probe)
    c, clis = world["client"], world["clis"]
    turn = asyncio.create_task(c.post(f"/api/v1/agents/{world['agy']}/chat", json={"prompt": "x"}))
    await clis.until_spawned(1)
    clis.release(0)
    assert (await asyncio.wait_for(turn, WAIT)).status_code == 200
    assert threads and threading.main_thread() not in threads
