"""Durable employee chat turns (nexus.runtime.chat_turns).

Covers what makes a turn survive a refresh, a dropped connection or a worker
restart: idempotent creation, the conditional claim, lease recovery,
durable cancellation, and one finalizer for every entry point. Route
functions run directly against a real SQLite database; the model call is a
fake that can be held open with an event, so nothing here depends on timing.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from datetime import timedelta

import pytest
from fastapi import HTTPException
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlmodel import SQLModel, select

import nexus.models  # noqa: F401 -- registers every table on SQLModel.metadata
from nexus.api.routes import chat as chat_routes
from nexus.api.routes import sessions as api
from nexus.config import settings
from nexus.models.agent import Agent
from nexus.models.agent_session import AgentSessionRecord
from nexus.models.chat import ChatMessage
from nexus.models.chat_turn import ChatTurn
from nexus.models.company import Company
from nexus.models.governance import AuditLog
from nexus.models.notification import Notification
from nexus.runtime import chat_turns

pytestmark = pytest.mark.core_employee

LATER = timedelta(minutes=5)  # past any lease, well inside the queue TTL


@pytest.fixture
async def db(tmp_path, monkeypatch):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'turns.db'}")
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)

    import nexus.database as database

    monkeypatch.setattr(database, "async_session_factory", factory)
    # tenant_session() picks its dialect from the URL, not from this factory.
    monkeypatch.setattr("nexus.config.settings.database_url", str(engine.url))

    async def fake_prompt(db, agent, company_id, prompt):
        return "system"

    async def fake_llm(agent, system_prompt, prompt, history, **kw):
        fake_llm.calls.append({"prompt": prompt, "history": history})
        fake_llm.started.set()
        if fake_llm.gate is not None:
            await fake_llm.gate.wait()
        return f"echo: {prompt}", "test-model", 7

    fake_llm.calls, fake_llm.gate, fake_llm.started = [], None, asyncio.Event()
    monkeypatch.setattr(chat_routes, "_build_chat_prompt", fake_prompt)
    monkeypatch.setattr(chat_routes, "_call_llm", fake_llm)
    # Streamed turns take _stream_llm's whole-reply path (no provider key).
    monkeypatch.setattr(
        chat_routes, "_resolve_adapter_type", lambda agent, conn=None: ("openai", {})
    )
    factory.llm = fake_llm
    yield factory
    await chat_turns.drain()
    await engine.dispose()


@pytest.fixture
async def t(db):
    """Two companies, each with one agent and one session."""
    ids = {}
    for name in ("acme", "other"):
        async with db() as s:
            company = Company(name=name)
            s.add(company)
            await s.flush()
            agent = Agent(
                company_id=company.id, name=f"{name} emp", role="engineer",
                adapter_type="openai", model="gpt-x",
            )
            s.add(agent)
            await s.commit()
        ids[name], ids[f"{name}_agent"] = company.id, agent.id
        ids[f"{name}_session"] = await _new_session(db, company.id, agent.id)
    return ids


async def _new_session(db, company_id, agent_id):
    async with db() as s:
        out = await api.create_session(agent_id, api.SessionCreate(), company_id, s)
        await s.commit()
    return out.id


async def _queue(db, company_id, session_id, prompt="hi", key=None):
    """Store a queued turn without waking the worker."""
    async with db() as s:
        record = await s.get(AgentSessionRecord, session_id)
        agent = await chat_routes._load_agent(s, record.agent_id, company_id)
        return (
            await chat_turns.create_turn(s, record, agent, prompt, idempotency_key=key)
        ).turn


async def _send(db, company_id, session_id, prompt="hi", key=None):
    async with db() as s:
        return await api.send_message(
            session_id, api.SessionMessageRequest(prompt=prompt), company_id, s,
            idempotency_key=key,
        )


async def _rows(db, model, *where, order=None):
    async with db() as s:
        stmt = select(model).where(*where)
        if order is not None:
            stmt = stmt.order_by(order)
        return (await s.execute(stmt)).scalars().all()


async def _actions(db, turn_id):
    rows = await _rows(
        db, AuditLog, AuditLog.resource_id == str(turn_id), order=AuditLog.sequence_number
    )
    return [r.action for r in rows]


def _event(events, kind):
    for e in events:
        if f'"type": "{kind}"' in e:
            return json.loads(e[e.index("data: ") + 6:])
    raise AssertionError(f"no {kind} event in {events}")


async def _stream(resp, stop_after=None):
    events, body = [], resp.body_iterator
    async for event in body:
        events.append(event)
        if stop_after is not None and len(events) >= stop_after:
            await body.aclose()
            break
    return events


class TestIdempotency:
    async def test_retry_with_same_key_attaches_to_the_turn(self, db, t) -> None:
        first = await _send(db, t["acme"], t["acme_session"], key="req-1")
        again = await _send(db, t["acme"], t["acme_session"], key="req-1")
        assert again["turn_id"] == first["turn_id"]
        assert again["message_id"] == first["message_id"]
        assert len(db.llm.calls) == 1
        msgs = await _rows(db, ChatMessage, order=ChatMessage.seq)
        assert [(m.seq, m.sender) for m in msgs] == [(1, "user"), (2, "agent")]
        assert len(await _rows(db, ChatTurn)) == 1

    async def test_body_request_id_is_the_key_too(self, db, t) -> None:
        body = api.SessionMessageRequest(prompt="hi", request_id="req-body")
        async with db() as s:
            first = await api.send_message(t["acme_session"], body, t["acme"], s)
        async with db() as s:
            again = await api.send_message(t["acme_session"], body, t["acme"], s)
        assert again["turn_id"] == first["turn_id"] and len(db.llm.calls) == 1

    async def test_same_key_in_another_tenant_is_a_different_turn(self, db, t) -> None:
        mine = await _send(db, t["acme"], t["acme_session"], key="shared")
        theirs = await _send(db, t["other"], t["other_session"], key="shared")
        assert mine["turn_id"] != theirs["turn_id"] and len(db.llm.calls) == 2
        # Neither tenant can read or cancel the other's turn.
        async with db() as s:
            for coro in (
                api.get_turn(t["acme_session"], uuid.UUID(mine["turn_id"]), t["other"], s),
                api.cancel_turn(t["other_session"], uuid.UUID(mine["turn_id"]), t["other"], s),
            ):
                with pytest.raises(HTTPException) as exc:
                    await coro
                assert exc.value.status_code == 404


class TestClaim:
    async def test_racing_claims_have_one_winner(self, db, t) -> None:
        turn = await _queue(db, t["acme"], t["acme_session"])
        won = await asyncio.gather(
            *(chat_turns.claim(turn.id, t["acme"], f"worker-{i}") for i in range(5))
        )
        winners = [w for w in won if w is not None]
        assert len(winners) == 1
        stored = (await _rows(db, ChatTurn))[0]
        assert (stored.status, stored.attempt_count) == ("claimed", 1)
        assert stored.claimed_by == winners[0].claimed_by and stored.execution_id
        assert (await _actions(db, turn.id)).count("chat.turn_claimed") == 1

    async def test_claim_is_tenant_scoped(self, db, t) -> None:
        turn = await _queue(db, t["acme"], t["acme_session"])
        assert await chat_turns.claim(turn.id, t["other"], "w") is None

    async def test_a_session_runs_its_turns_in_order(self, db, t) -> None:
        first = await _queue(db, t["acme"], t["acme_session"], "one")
        second = await _queue(db, t["acme"], t["acme_session"], "two")
        assert await chat_turns.claim(second.id, t["acme"], "w") is None
        held = await chat_turns.claim(first.id, t["acme"], "w")
        assert held is not None
        assert await chat_turns.claim(second.id, t["acme"], "w2") is None
        await chat_turns.finalize(held, "w", "completed", prompt="one", text="done")
        assert await chat_turns.claim(second.id, t["acme"], "w2") is not None

    async def test_next_turn_sees_the_previous_reply(self, db, t) -> None:
        # Both turns are queued before either runs; history is read when the
        # turn runs, so the second turn still sees the first turn's reply.
        await _queue(db, t["acme"], t["acme_session"], "one")
        await _queue(db, t["acme"], t["acme_session"], "two")
        chat_turns.get_worker().wake(t["acme"])
        await chat_turns.drain()
        assert [c["prompt"] for c in db.llm.calls] == ["one", "two"]
        assert db.llm.calls[1]["history"] == [
            {"sender": "user", "text": "one"},
            {"sender": "agent", "text": "echo: one"},
        ]


class TestRecovery:
    async def test_expired_lease_requeues_then_fails_and_notifies(self, db, t) -> None:
        turn = await _queue(db, t["acme"], t["acme_session"])
        for attempt in range(1, turn.max_attempts + 1):
            assert await chat_turns.claim(turn.id, t["acme"], f"dead-{attempt}") is not None
            outcome = await chat_turns.recover_company(t["acme"], now=chat_turns._now() + LATER)
            expected = "failed" if attempt == turn.max_attempts else "recovered"
            assert outcome[expected] == 1, outcome
        stored = (await _rows(db, ChatTurn))[0]
        assert (stored.status, stored.error_code, stored.attempt_count) == (
            "failed", "ATTEMPTS_EXHAUSTED", 3
        )
        [note] = await _rows(db, Notification)
        assert note.priority == "high" and note.notification_metadata["turn_id"] == str(turn.id)
        actions = await _actions(db, turn.id)
        assert actions.count("chat.turn_recovered") == 2 and "chat.turn_failed" in actions
        # Idempotent: another pass changes nothing.
        again = await chat_turns.recover_company(t["acme"], now=chat_turns._now() + LATER)
        assert not (again["failed"] or again["recovered"])
        assert len(await _rows(db, Notification)) == 1

    async def test_stored_reply_completes_instead_of_rerunning(self, db, t) -> None:
        turn = await _queue(db, t["acme"], t["acme_session"])
        await chat_turns.claim(turn.id, t["acme"], "dead")
        async with db() as s:
            reply = await chat_routes._persist_message_to_db(
                s, t["acme_agent"], t["acme"], "agent", "stored", session_id=t["acme_session"]
            )
            stored = await s.get(ChatTurn, turn.id)
            stored.response_message_id = reply.id
            await s.commit()
        outcome = await chat_turns.recover_company(t["acme"], now=chat_turns._now() + LATER)
        assert outcome["completed"] == 1
        assert (await _rows(db, ChatTurn))[0].status == "completed"

    async def test_restarted_worker_runs_the_turn_once(self, db, t) -> None:
        turn = await _queue(db, t["acme"], t["acme_session"])
        # A worker claimed it, then its process died before calling the model.
        await chat_turns.claim(turn.id, t["acme"], "crashed-worker")
        outcome = await chat_turns.recover_company(t["acme"], now=chat_turns._now() + LATER)
        assert outcome["recovered"] == 1
        chat_turns.get_worker().wake(t["acme"])
        await chat_turns.drain()
        stored = (await _rows(db, ChatTurn))[0]
        assert (stored.status, stored.attempt_count) == ("completed", 2)
        assert len(db.llm.calls) == 1
        replies = await _rows(db, ChatMessage, ChatMessage.sender == "agent")
        assert [r.id for r in replies] == [stored.response_message_id]

    async def test_worker_that_lost_its_lease_stores_nothing(self, db, t) -> None:
        turn = await _queue(db, t["acme"], t["acme_session"])
        held = await chat_turns.claim(turn.id, t["acme"], "slow")
        await chat_turns.recover_company(t["acme"], now=chat_turns._now() + LATER)
        late = await chat_turns.finalize(held, "slow", "completed", prompt="hi", text="late")
        assert late is None
        assert await _rows(db, ChatMessage, ChatMessage.sender == "agent") == []
        assert (await _rows(db, ChatTurn))[0].status == "queued"

    async def test_racing_recovery_workers_leave_one_current_epoch(self, db, t) -> None:
        from nexus.tools.effects import Epoch, is_current_execution

        turn = await _queue(db, t["acme"], t["acme_session"])
        slow = await chat_turns.claim(turn.id, t["acme"], "slow")
        old = Epoch(slow.execution_id, slow.attempt_count)
        await chat_turns.recover_company(t["acme"], now=chat_turns._now() + LATER)
        won = await asyncio.gather(
            *(chat_turns.claim(turn.id, t["acme"], f"recovery-{i}") for i in range(5))
        )
        [winner] = [w for w in won if w is not None]
        new = Epoch(winner.execution_id, winner.attempt_count)
        assert (old.attempt, new.attempt) == (1, 2) and old.execution_id != new.execution_id
        # Only the winner is the turn's current execution; the replaced worker is not, whatever
        # it does next, and it cannot make itself current by asking again.
        assert await is_current_execution(t["acme"], turn.id, new) == ""
        assert await is_current_execution(t["acme"], turn.id, old) != ""
        assert await is_current_execution(t["acme"], turn.id, old) != ""
        assert await is_current_execution(t["acme"], turn.id, None) != ""

    async def test_the_worker_hands_the_epoch_it_claimed_to_the_model_call(
        self, db, t, monkeypatch
    ) -> None:
        epochs: list = []
        inner = chat_routes._call_llm

        async def spy(*args, **kw):
            epochs.append((kw.get("turn_id"), kw.get("turn_epoch")))
            return await inner(*args, **kw)

        monkeypatch.setattr(chat_routes, "_call_llm", spy)
        turn = await _queue(db, t["acme"], t["acme_session"])
        await chat_turns.claim(turn.id, t["acme"], "crashed-worker")
        await chat_turns.recover_company(t["acme"], now=chat_turns._now() + LATER)
        chat_turns.get_worker().wake(t["acme"])
        await chat_turns.drain()
        stored = (await _rows(db, ChatTurn))[0]
        assert epochs == [(turn.id, (stored.execution_id, 2))]

    async def test_stale_queued_turn_expires(self, db, t) -> None:
        turn = await _queue(db, t["acme"], t["acme_session"])
        ttl = timedelta(seconds=settings.chat_turn_queue_ttl_seconds + 1)
        outcome = await chat_turns.recover_company(t["acme"], now=chat_turns._now() + ttl)
        assert outcome["expired"] == 1
        assert (await _rows(db, ChatTurn))[0].error_code == "QUEUE_TTL_EXPIRED"
        assert "chat.turn_expired" in await _actions(db, turn.id)


class TestCancel:
    async def test_cancelled_queued_turn_never_runs_and_retry_does_not_revive_it(
        self, db, t
    ) -> None:
        turn = await _queue(db, t["acme"], t["acme_session"], key="k")
        async with db() as s:
            state = await api.cancel_turn(t["acme_session"], turn.id, t["acme"], s)
        assert state["status"] == "cancelled"
        chat_turns.get_worker().wake(t["acme"])
        await chat_turns.drain()
        assert db.llm.calls == []
        with pytest.raises(HTTPException) as exc:
            await _send(db, t["acme"], t["acme_session"], key="k")
        assert exc.value.status_code == 409 and exc.value.detail["code"] == "TURN_CANCELLED"
        assert await _actions(db, turn.id) == [
            "chat.turn_queued", "chat.turn_cancel_requested", "chat.turn_cancelled"
        ]

    async def test_cancel_running_turn_stops_it(self, db, t, monkeypatch) -> None:
        monkeypatch.setattr(settings, "chat_turn_wait_seconds", 0.01)
        db.llm.gate = asyncio.Event()
        pending = await _send(db, t["acme"], t["acme_session"])
        assert isinstance(pending, JSONResponse) and pending.status_code == 202
        turn_id = uuid.UUID(json.loads(pending.body)["turn_id"])
        await db.llm.started.wait()
        async with db() as s:
            await api.cancel_turn(t["acme_session"], turn_id, t["acme"], s)
        await chat_turns.drain()
        stored = (await _rows(db, ChatTurn))[0]
        assert (stored.status, stored.error_code, stored.cancelled_by) == (
            "cancelled", "CANCELLED", "anonymous"
        )
        assert await _rows(db, ChatMessage, ChatMessage.sender == "agent") == []


class TestEntryPointParity:
    async def test_plain_and_stream_store_and_report_the_same(self, db, t) -> None:
        second = await _new_session(db, t["acme"], t["acme_agent"])
        plain = await _send(db, t["acme"], t["acme_session"])
        async with db() as s:
            resp = await api.stream_message(
                second, api.SessionMessageRequest(prompt="hi"), t["acme"], s
            )
        done = _event(await _stream(resp), "done")
        keys = {
            "turn_id", "execution_id", "session_id", "agent_id", "adapter_used",
            "backend_used", "model_used", "status", "message_id", "message", "seq",
        }
        assert keys <= set(plain) and keys <= set(done)
        assert plain["status"] == done["status"] == "completed"
        assert plain["model_used"] == done["model_used"] == "test-model"
        for reply in (plain, done):
            actions = await _actions(db, reply["turn_id"])
            assert actions == [
                "chat.turn_queued", "chat.turn_claimed", "chat.turn_started",
                "chat.turn_completed",
            ]
            sides = await _rows(
                db, AuditLog,
                AuditLog.action.in_(("chat.message_sent", "chat.response_generated")),
            )
            assert sorted(
                a.action for a in sides if a.details["execution_id"] == reply["execution_id"]
            ) == ["chat.message_sent", "chat.response_generated"]

    async def test_reconnect_resumes_without_rerunning(self, db, t) -> None:
        async with db() as s:
            resp = await api.stream_message(
                t["acme_session"], api.SessionMessageRequest(prompt="a b c"), t["acme"], s
            )
        first = await _stream(resp, stop_after=1)
        turn_id = uuid.UUID(_event(first, "turn")["turn_id"])
        await chat_turns.drain()
        async with db() as s:
            again = await api.turn_events(
                t["acme_session"], turn_id, t["acme"], s, last_event_id="6"
            )
        events = await _stream(again)
        chunks = "".join(json.loads(e[e.index("data: ") + 6:])["text"]
                         for e in events if '"type": "chunk"' in e)
        assert chunks == "a b c"  # the client already had "echo: " (6 characters)
        assert _event(events, "done")["message"]["text"] == "echo: a b c"
        assert len(db.llm.calls) == 1


class TestPending:
    async def test_slow_turn_answers_202_and_finishes_on_its_own(
        self, db, t, monkeypatch
    ) -> None:
        monkeypatch.setattr(settings, "chat_turn_wait_seconds", 0.01)
        db.llm.gate = asyncio.Event()
        pending = await _send(db, t["acme"], t["acme_session"])
        assert pending.status_code == 202 and pending.headers["retry-after"]
        body = json.loads(pending.body)
        async with db() as s:
            listed = await api.list_turns(t["acme_session"], t["acme"], s, pending=True, limit=50)
        assert [x["turn_id"] for x in listed] == [body["turn_id"]]
        db.llm.gate.set()
        await chat_turns.drain()
        async with db() as s:
            done = await api.get_turn(t["acme_session"], uuid.UUID(body["turn_id"]), t["acme"], s)
            left = await api.list_turns(t["acme_session"], t["acme"], s, pending=True, limit=50)
        assert left == []
        assert done["status"] == "completed" and done["message"]["text"] == "echo: hi"

    async def test_budget_denial_is_terminal_and_audited(self, db, t, monkeypatch) -> None:
        async def denied(*a, **kw):
            raise HTTPException(402, detail={"code": "BUDGET_EXCEEDED", "message": "over"})

        monkeypatch.setattr(chat_routes, "_call_llm", denied)
        with pytest.raises(HTTPException) as exc:
            await _send(db, t["acme"], t["acme_session"])
        assert exc.value.status_code == 402 and exc.value.detail["code"] == "BUDGET_EXCEEDED"
        stored = (await _rows(db, ChatTurn))[0]
        assert (stored.status, stored.error_code, stored.attempt_count) == (
            "failed", "BUDGET_EXCEEDED", 1
        )
        assert "chat.turn_failed" in await _actions(db, stored.id)


class TestRefreshRebuild:
    async def test_history_is_in_turn_order_with_labels_and_pending_turns(self, db, t) -> None:
        one = await _queue(db, t["acme"], t["acme_session"], "one")
        two = await _queue(db, t["acme"], t["acme_session"], "two")
        async with db() as s:
            waiting = await chat_routes.list_agent_chat_turns(
                t["acme_agent"], s, t["acme"], pending=True, limit=50
            )
        # A refreshed page sees both prompts pending, and the IDs of the
        # prompt messages it already shows.
        assert [(w["turn_id"], w["status"]) for w in waiting] == [
            (str(one.id), "queued"), (str(two.id), "queued")
        ]
        assert waiting[0]["prompt_message_id"] == str(one.prompt_message_id)

        chat_turns.get_worker().wake(t["acme"])
        await chat_turns.drain()
        async with db() as s:
            history = await chat_routes.get_chat_history(t["acme_agent"], s, t["acme"])
            assert await chat_routes.list_agent_chat_turns(
                t["acme_agent"], s, t["acme"], pending=True, limit=50
            ) == []
            # Another tenant sees no turns of this agent.
            with pytest.raises(HTTPException) as exc:
                await chat_routes.list_agent_chat_turns(
                    t["acme_agent"], s, t["other"], pending=False, limit=50
                )
            assert exc.value.status_code == 404
        # Replies follow their prompts, though "two" was stored before "echo: one".
        assert [(m["sender"], m["text"]) for m in history] == [
            ("user", "one"), ("agent", "echo: one"), ("user", "two"), ("agent", "echo: two")
        ]
        assert [m["seq"] for m in history] == [1, 3, 2, 4]
        assert history[1]["model_used"] == "test-model" and not history[1]["partial"]
        assert history[0]["id"] == str(one.prompt_message_id)
