"""Agent session API: lifecycle, tenant scoping, sequencing, timeline, usage.

Route functions are called directly against a real SQLite database; the
permission dependencies are checked separately, against the route table and
the RBAC roles, so these tests do not need the auth middleware.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta

import pytest
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlmodel import SQLModel, select

import nexus.models  # noqa: F401 -- registers every table on SQLModel.metadata
from nexus.api.routes import adapters as legacy
from nexus.api.routes import chat as chat_routes
from nexus.api.routes import sessions as api
from nexus.governance.rbac import role_allows
from nexus.models.agent import Agent
from nexus.models.agent_session import AgentSessionRecord
from nexus.models.budget import CostEvent
from nexus.models.chat import ChatMessage
from nexus.models.company import Company
from nexus.models.connection import LLMConnection
from nexus.models.governance import AuditLog
from nexus.models.tool_invocation import ToolInvocation
from nexus.models.workspace import Workspace
from nexus.runtime import chat_turns
from nexus.runtime.checkpoint import ExecutionCheckpoint
from nexus.services import session_service


@pytest.fixture
async def db_factory(tmp_path, monkeypatch):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'sessions.db'}")
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)

    import nexus.database as database

    monkeypatch.setattr(database, "async_session_factory", factory)
    # tenant_session() picks its dialect from the URL, not from this factory.
    monkeypatch.setattr("nexus.config.settings.database_url", str(engine.url))

    async def fake_prompt(db, agent, company_id, prompt):
        return "system"

    async def fake_llm(agent, system_prompt, prompt, history, temperature=None, session_id=None, **kw):
        fake_llm.calls.append(
            {
                "prompt": prompt,
                "history": history,
                "session_id": session_id,
                "pin": (agent.adapter_type, agent.model, agent.connection_id),
            }
        )
        return f"echo: {prompt}", "test-model", 7

    fake_llm.calls = []
    monkeypatch.setattr(chat_routes, "_build_chat_prompt", fake_prompt)
    monkeypatch.setattr(chat_routes, "_call_llm", fake_llm)
    factory.llm_calls = fake_llm.calls
    yield factory
    await engine.dispose()


@pytest.fixture
async def tenants(db_factory):
    """Two companies, one agent each, and a workspace in the first."""
    acme, other = Company(name="Acme"), Company(name="Other")
    async with db_factory() as db:
        db.add_all([acme, other])
        await db.flush()
        agent = Agent(
            company_id=acme.id, name="Navi", role="engineer", adapter_type="openai", model="gpt-x"
        )
        foreign = Agent(company_id=other.id, name="Foreign", role="engineer")
        ws = Workspace(company_id=acme.id, name="repo", path="/tmp/repo")
        foreign_ws = Workspace(company_id=other.id, name="theirs", path="/tmp/theirs")
        db.add_all([agent, foreign, ws, foreign_ws])
        await db.commit()
    return {
        "acme": acme.id,
        "other": other.id,
        "agent": agent.id,
        "foreign": foreign.id,
        "ws": ws.id,
        "foreign_ws": foreign_ws.id,
    }


async def _create(factory, t, **body):
    async with factory() as db:
        out = await api.create_session(t["agent"], api.SessionCreate(**body), t["acme"], db)
        await db.commit()
    return out


class TestPermissions:
    def test_every_route_declares_its_permission(self) -> None:
        for route in api.router.routes:
            if route.name == "delete_session":
                continue  # RequireAdmin in the signature
            assert route.dependencies, f"{route.path} {route.methods} has no permission dependency"

    def test_roles(self) -> None:
        assert role_allows("viewer", "read", "session")
        assert not role_allows("viewer", "write", "session")
        assert role_allows("manager", "write", "session")
        assert role_allows("admin", "write", "session")


class TestLifecycle:
    async def test_create_pins_agent_config_and_validates_workspace(
        self, db_factory, tenants
    ) -> None:
        out = await _create(db_factory, tenants, title="t1", workspace_id=tenants["ws"])
        assert (out.status, out.adapter_type, out.model, out.event_seq) == (
            "active",
            "openai",
            "gpt-x",
            0,
        )
        assert out.workspace_id == tenants["ws"] and out.created_by == "api"

        with pytest.raises(HTTPException) as exc:
            await _create(db_factory, tenants, workspace_id=tenants["foreign_ws"])
        assert exc.value.status_code == 404

    async def test_cross_tenant_agent_and_session_are_404(self, db_factory, tenants) -> None:
        async with db_factory() as db:
            with pytest.raises(HTTPException) as exc:
                await api.create_session(
                    tenants["foreign"], api.SessionCreate(), tenants["acme"], db
                )
            assert exc.value.status_code == 404

        out = await _create(db_factory, tenants)
        async with db_factory() as db:
            for call in (
                api.get_session(out.id, tenants["other"], db),
                api.get_timeline(out.id, tenants["other"], db, None, 100),
                api.get_usage(out.id, tenants["other"], db),
                api.terminate_session(out.id, tenants["other"], db),
            ):
                with pytest.raises(HTTPException) as exc:
                    await call
                assert exc.value.status_code == 404

    async def test_update_terminate_delete(self, db_factory, tenants) -> None:
        out = await _create(db_factory, tenants)
        async with db_factory() as db:
            upd = await api.update_session(
                out.id, api.SessionUpdate(title="renamed", status="idle"), tenants["acme"], db
            )
            assert (upd.title, upd.status, upd.ended_at) == ("renamed", "idle", None)
            with pytest.raises(HTTPException) as exc:
                await api.delete_session(out.id, tenants["acme"], db, None)
            assert exc.value.status_code == 409
            term = await api.terminate_session(out.id, tenants["acme"], db)
            assert term.status == "terminated" and term.ended_at is not None
            with pytest.raises(HTTPException) as exc:
                await api.terminate_session(out.id, tenants["acme"], db)
            assert exc.value.status_code == 409
            await db.commit()

        async with db_factory() as db:
            db.add(
                CostEvent(company_id=tenants["acme"], session_id=out.id, provider="p", cost_cents=3)
            )
            await db.commit()
        async with db_factory() as db:
            await api.delete_session(out.id, tenants["acme"], db, None)
            await db.commit()
        async with db_factory() as db:
            assert await db.get(AgentSessionRecord, out.id) is None
            cost = (await db.execute(select(CostEvent))).scalar_one()
            assert cost.session_id is None and cost.cost_cents == 3  # spend history survives

    async def test_list_filters_and_paginates(self, db_factory, tenants) -> None:
        ids = [(await _create(db_factory, tenants, title=f"s{i}")).id for i in range(5)]
        async with db_factory() as db:
            await api.terminate_session(ids[0], tenants["acme"], db)
            await db.commit()

        seen, cursor = [], None
        async with db_factory() as db:
            while True:
                page = await api.list_sessions(tenants["acme"], db, None, None, None, cursor, 2)
                seen += [s.id for s in page["items"]]
                cursor = page["next_cursor"]
                if cursor is None:
                    break
            assert sorted(seen) == sorted(ids) and len(seen) == 5
            active = await api.list_sessions(tenants["acme"], db, None, None, "active", None, 50)
            assert ids[0] not in {s.id for s in active["items"]} and len(active["items"]) == 4
            assert (await api.list_sessions(tenants["other"], db, None, None, None, None, 50))[
                "items"
            ] == []


class TestConversation:
    async def test_turns_get_monotonic_seq_and_session_history(self, db_factory, tenants) -> None:
        out = await _create(db_factory, tenants)
        async with db_factory() as db:
            await api.update_session(out.id, api.SessionUpdate(status="idle"), tenants["acme"], db)
            first = await api.send_message(
                out.id, api.SessionMessageRequest(prompt="hi"), tenants["acme"], db
            )
            await db.commit()
        async with db_factory() as db:
            second = await api.send_message(
                out.id, api.SessionMessageRequest(prompt="again"), tenants["acme"], db
            )
            await db.commit()

        assert (first["seq"], second["seq"]) == (2, 4)
        assert second["message"]["text"] == "echo: again" and second["model_used"] == "test-model"
        # History is this session's transcript, oldest first, without the new prompt.
        assert db_factory.llm_calls[1]["history"] == [
            {"sender": "user", "text": "hi"},
            {"sender": "agent", "text": "echo: hi"},
        ]
        assert db_factory.llm_calls[1]["session_id"] == out.id

        async with db_factory() as db:
            rows = (await db.execute(select(ChatMessage).order_by(ChatMessage.seq))).scalars().all()
            assert [(r.seq, r.sender) for r in rows] == [
                (1, "user"),
                (2, "agent"),
                (3, "user"),
                (4, "agent"),
            ]
            record = await db.get(AgentSessionRecord, out.id)
            assert record.event_seq == 4 and record.status == "active"  # idle woke up

    async def test_ended_session_refuses_messages(self, db_factory, tenants) -> None:
        out = await _create(db_factory, tenants)
        async with db_factory() as db:
            await api.terminate_session(out.id, tenants["acme"], db)
            with pytest.raises(HTTPException) as exc:
                await api.send_message(
                    out.id, api.SessionMessageRequest(prompt="x"), tenants["acme"], db
                )
            assert exc.value.status_code == 409
        assert db_factory.llm_calls == []


class TestTimelineAndUsage:
    async def test_merged_order_cursor_and_committed_only(self, db_factory, tenants) -> None:
        out = await _create(db_factory, tenants)
        t0 = datetime(2026, 1, 1, 12, 0, 0)
        async with db_factory() as db:
            db.add_all(
                [
                    ChatMessage(
                        company_id=tenants["acme"],
                        agent_id=tenants["agent"],
                        sender="user",
                        text="a",
                        session_id=out.id,
                        seq=1,
                        created_at=t0,
                    ),
                    # Same instant as the message: checkpoint ranks first, usage last.
                    ExecutionCheckpoint(task_id=uuid.uuid4(), session_id=out.id, created_at=t0),
                    CostEvent(
                        company_id=tenants["acme"],
                        session_id=out.id,
                        provider="p",
                        cost_cents=5,
                        input_tokens=10,
                        output_tokens=20,
                        occurred_at=t0,
                    ),
                    ToolInvocation(
                        company_id=tenants["acme"],
                        agent_id=tenants["agent"],
                        tool_id=uuid.uuid4(),
                        session_id=out.id,
                        tool_name="grep",
                        status="success",
                        created_at=t0 + timedelta(seconds=1),
                    ),
                    CostEvent(
                        company_id=tenants["acme"],
                        session_id=out.id,
                        provider="p",
                        cost_cents=99,
                        status="reserved",
                        occurred_at=t0 + timedelta(seconds=2),
                    ),
                    CostEvent(
                        company_id=tenants["acme"],
                        session_id=out.id,
                        provider="p",
                        cost_cents=2,
                        output_tokens=4,
                        occurred_at=t0 + timedelta(seconds=3),
                    ),
                ]
            )
            await db.commit()

        async with db_factory() as db:
            full = await api.get_timeline(out.id, tenants["acme"], db, None, 100)
            assert [i["type"] for i in full["items"]] == [
                "checkpoint",
                "message",
                "usage",
                "tool_call",
                "usage",
            ]
            assert full["next_cursor"] is None

            paged, cursor = [], None
            while True:
                page = await api.get_timeline(out.id, tenants["acme"], db, cursor, 2)
                paged += page["items"]
                cursor = page["next_cursor"]
                if cursor is None:
                    break
            assert [i["id"] for i in paged] == [i["id"] for i in full["items"]]

            usage = await api.get_usage(out.id, tenants["acme"], db)
            assert usage == {
                "session_id": str(out.id),
                "events": 2,
                "cost_cents": 7,
                "input_tokens": 10,
                "output_tokens": 24,
            }

    async def test_bad_cursor_is_422(self, db_factory, tenants) -> None:
        out = await _create(db_factory, tenants)
        async with db_factory() as db:
            with pytest.raises(HTTPException) as exc:
                await api.get_timeline(out.id, tenants["acme"], db, "not-a-cursor", 10)
            assert exc.value.status_code == 422


# ---------------------------------------------------------------------------
# P2: lifecycle, pinning, streaming, concurrency, deprecated aliases
# ---------------------------------------------------------------------------


async def _set(factory, table, row_id, **fields):
    async with factory() as db:
        row = await db.get(table, row_id)
        for key, value in fields.items():
            setattr(row, key, value)
        await db.commit()


async def _send(factory, t, session_id, prompt="hi"):
    async with factory() as db:
        out = await api.send_message(
            session_id, api.SessionMessageRequest(prompt=prompt), t["acme"], db
        )
        await db.commit()
    return out


async def _expect(status_code, coro):
    with pytest.raises(HTTPException) as exc:
        await coro
    assert exc.value.status_code == status_code, exc.value.detail
    return exc.value


async def _messages(factory, session_id=None):
    async with factory() as db:
        stmt = select(ChatMessage).order_by(ChatMessage.seq)
        if session_id is not None:
            stmt = stmt.where(ChatMessage.session_id == session_id)
        return (await db.execute(stmt)).scalars().all()


async def _drain(resp, stop_after=None):
    """Read an SSE response; with ``stop_after``, disconnect after that many events."""
    events, body = [], resp.body_iterator
    async for event in body:
        events.append(event)
        if stop_after is not None and len(events) >= stop_after:
            await body.aclose()
            break
    return events


@pytest.fixture
def simulated_stream(monkeypatch):
    """Route _stream_llm through its whole-reply path (no provider key)."""
    monkeypatch.setattr(
        chat_routes, "_resolve_adapter_type", lambda agent, conn=None: ("openai", {})
    )


class TestStateMachine:
    def test_transition_rules(self) -> None:
        record = AgentSessionRecord(company_id=uuid.uuid4(), agent_id=uuid.uuid4())
        session_service.transition(record, "idle")
        session_service.transition(record, "idle")  # same open state: no-op
        session_service.transition(record, "active")
        assert record.status == "active" and record.ended_at is None
        session_service.transition(record, "completed")
        assert record.ended_at is not None
        for to in ("active", "idle", "completed", "failed", "terminated"):
            with pytest.raises(session_service.SessionStateError) as exc:
                session_service.transition(record, to)
            assert exc.value.status_code == 409

    async def test_terminated_session_cannot_resume_by_any_route(self, db_factory, tenants) -> None:
        out = await _create(db_factory, tenants)
        acme, agent = tenants["acme"], tenants["agent"]
        req = api.SessionMessageRequest(prompt="x")
        async with db_factory() as db:
            await api.terminate_session(out.id, acme, db)
            await db.commit()
        async with db_factory() as db:
            await _expect(
                409, api.update_session(out.id, api.SessionUpdate(status="active"), acme, db)
            )
            await _expect(409, api.repin_session(out.id, acme, db))
            await _expect(409, api.send_message(out.id, req, acme, db))
            await _expect(409, api.stream_message(out.id, req, acme, db))
            await _expect(409, legacy.resume_session(agent, out.id, acme, db))
            await _expect(409, legacy.pause_session(agent, out.id, acme, db))
        async with db_factory() as db:
            record = await db.get(AgentSessionRecord, out.id)
            assert record.status == "terminated" and record.event_seq == 0
        assert db_factory.llm_calls == [] and await _messages(db_factory) == []


class TestPinning:
    async def test_turn_runs_on_pin_after_agent_changes(self, db_factory, tenants) -> None:
        out = await _create(db_factory, tenants)
        await _set(db_factory, Agent, tenants["agent"], adapter_type="anthropic", model="claude-z")
        await _send(db_factory, tenants, out.id)
        assert db_factory.llm_calls[-1]["pin"] == ("openai", "gpt-x", None)
        async with db_factory() as db:
            record = await db.get(AgentSessionRecord, out.id)
            assert (record.adapter_type, record.model) == ("openai", "gpt-x")

    async def test_unavailable_connection_refuses_before_storing(self, db_factory, tenants) -> None:
        conn = LLMConnection(
            company_id=tenants["acme"], name="gw", base_url="http://gw", wire_format="openai"
        )
        async with db_factory() as db:
            db.add(conn)
            await db.commit()
        await _set(db_factory, Agent, tenants["agent"], connection_id=conn.id)
        out = await _create(db_factory, tenants)
        assert out.llm_connection_id == conn.id
        await _set(db_factory, LLMConnection, conn.id, is_active=False)

        req = api.SessionMessageRequest(prompt="x")
        async with db_factory() as db:
            exc = await _expect(409, api.send_message(out.id, req, tenants["acme"], db))
            assert "repin" in exc.detail
            await _expect(409, api.stream_message(out.id, req, tenants["acme"], db))
        async with db_factory() as db:
            assert (await db.get(AgentSessionRecord, out.id)).event_seq == 0
        assert db_factory.llm_calls == [] and await _messages(db_factory) == []

    async def test_foreign_connection_pin_is_unavailable(self, db_factory, tenants) -> None:
        foreign = LLMConnection(
            company_id=tenants["other"], name="theirs", base_url="http://x", wire_format="openai"
        )
        async with db_factory() as db:
            db.add(foreign)
            await db.commit()
        out = await _create(db_factory, tenants)
        await _set(db_factory, AgentSessionRecord, out.id, llm_connection_id=foreign.id)
        async with db_factory() as db:
            await _expect(
                409,
                api.send_message(
                    out.id, api.SessionMessageRequest(prompt="x"), tenants["acme"], db
                ),
            )
        assert db_factory.llm_calls == []

    async def test_unknown_adapter_is_not_substituted(self, db_factory, tenants) -> None:
        out = await _create(db_factory, tenants)
        await _set(db_factory, AgentSessionRecord, out.id, adapter_type="no-such-provider")
        async with db_factory() as db:
            await _expect(
                409,
                api.send_message(
                    out.id, api.SessionMessageRequest(prompt="x"), tenants["acme"], db
                ),
            )
        assert db_factory.llm_calls == []

    async def test_create_refuses_unavailable_agent_config(self, db_factory, tenants) -> None:
        await _set(db_factory, Agent, tenants["agent"], adapter_type="no-such-provider")
        await _expect(409, _create(db_factory, tenants))

    async def test_repin_is_explicit_checked_and_audited(self, db_factory, tenants) -> None:
        out = await _create(db_factory, tenants)
        await _set(db_factory, Agent, tenants["agent"], adapter_type="anthropic", model="claude-z")
        async with db_factory() as db:
            await _expect(404, api.repin_session(out.id, tenants["other"], db))
            repinned = await api.repin_session(out.id, tenants["acme"], db)
            await db.commit()
        assert (repinned.adapter_type, repinned.model) == ("anthropic", "claude-z")
        await _send(db_factory, tenants, out.id)
        assert db_factory.llm_calls[-1]["pin"] == ("anthropic", "claude-z", None)
        async with db_factory() as db:
            audit = (
                await db.execute(select(AuditLog).where(AuditLog.action == "session.repinned"))
            ).scalar_one()
            assert audit.details["before"]["model"] == "gpt-x"
            assert audit.details["after"]["model"] == "claude-z"

        # A repin to a config that cannot run is refused and changes nothing.
        await _set(db_factory, Agent, tenants["agent"], adapter_type="no-such-provider")
        async with db_factory() as db:
            await _expect(409, api.repin_session(out.id, tenants["acme"], db))
        async with db_factory() as db:
            assert (await db.get(AgentSessionRecord, out.id)).adapter_type == "anthropic"

    async def test_unpinned_legacy_session_adopts_agent_config(self, db_factory, tenants) -> None:
        async with db_factory() as db:
            backfilled = AgentSessionRecord(
                company_id=tenants["acme"], agent_id=tenants["agent"], status="idle"
            )
            db.add(backfilled)
            await db.commit()
        await _send(db_factory, tenants, backfilled.id)
        assert db_factory.llm_calls[-1]["pin"] == ("openai", "gpt-x", None)
        async with db_factory() as db:
            record = await db.get(AgentSessionRecord, backfilled.id)
            assert (record.adapter_type, record.model, record.status) == (
                "openai",
                "gpt-x",
                "active",
            )


class TestStreaming:
    async def test_commit_then_stream_then_persist(
        self, db_factory, tenants, simulated_stream
    ) -> None:
        out = await _create(db_factory, tenants)
        async with db_factory() as db:
            resp = await api.stream_message(
                out.id, api.SessionMessageRequest(prompt="hi"), tenants["acme"], db
            )
            # The user message is committed before a single event is streamed.
            first = (await _messages(db_factory))[0]
            assert (first.seq, first.sender, first.text) == (1, "user", "hi")
            events = await _drain(resp)
        assert any('"type": "done"' in e for e in events)
        assert events[-1] == "data: [DONE]\n\n"
        rows = await _messages(db_factory)
        assert [(m.seq, m.sender, m.text) for m in rows] == [
            (1, "user", "hi"),
            (2, "agent", "echo: hi"),
        ]
        async with db_factory() as db:
            assert (await db.get(AgentSessionRecord, out.id)).event_seq == 2

    async def test_simulated_stream_disconnect_keeps_reply(
        self, db_factory, tenants, simulated_stream
    ) -> None:
        out = await _create(db_factory, tenants)
        async with db_factory() as db:
            resp = await api.stream_message(
                out.id, api.SessionMessageRequest(prompt="hi"), tenants["acme"], db
            )
            await _drain(resp, stop_after=1)
        # The turn belongs to the worker, not to the connection.
        await chat_turns.drain()
        rows = await _messages(db_factory)
        assert [(m.seq, m.text, m.payload) for m in rows] == [
            (1, "hi", None),
            (2, "echo: hi", None),
        ]

    @staticmethod
    def _fake_stream(monkeypatch, gate=None):
        """A token-streaming adapter; with ``gate``, it holds after the first chunk."""
        from nexus.adapters.registry import AdapterRegistry

        class FakeAdapter:
            terminated = 0

            async def create_session(self, agent_id, config):
                # The route sets .context on it, like on a real AgentSession.
                return type("Session", (), {})()

            async def stream_execute(self, session, task_id, payload):
                yield "a"
                if gate is not None:
                    await gate.wait()
                for chunk in (" b", " c"):
                    yield chunk

            async def terminate(self, session):
                FakeAdapter.terminated += 1

        monkeypatch.setattr(
            chat_routes,
            "_resolve_adapter_type",
            lambda agent, conn=None: ("anthropic", {"api_key": "k", "model": "m"}),
        )
        monkeypatch.setattr(
            AdapterRegistry, "create_adapter", lambda self, key, config=None: FakeAdapter()
        )
        return FakeAdapter

    async def test_true_stream_disconnect_keeps_full_reply(
        self, db_factory, tenants, monkeypatch
    ) -> None:
        adapter = self._fake_stream(monkeypatch)
        cut, full = await _create(db_factory, tenants), await _create(db_factory, tenants)
        async with db_factory() as db:
            resp = await api.stream_message(
                cut.id, api.SessionMessageRequest(prompt="hi"), tenants["acme"], db
            )
            await _drain(resp, stop_after=1)
        async with db_factory() as db:
            resp = await api.stream_message(
                full.id, api.SessionMessageRequest(prompt="hi"), tenants["acme"], db
            )
            events = await _drain(resp)
        await chat_turns.drain()

        assert adapter.terminated == 2
        # Closing the stream is not a cancel: both turns store the whole reply.
        for session_id in (cut.id, full.id):
            rows = await _messages(db_factory, session_id)
            assert [(m.seq, m.text) for m in rows] == [(1, "hi"), (2, "a b c")]
            assert rows[1].payload["execution"]["adapter"] == "anthropic"
            assert "partial" not in rows[1].payload
        assert events[0].startswith("data: ") and '"type": "turn"' in events[0]
        done = next(e for e in events if '"type": "done"' in e)
        assert f'"message_id": "{rows[1].id}"' in done

    async def test_cancel_mid_stream_keeps_partial(
        self, db_factory, tenants, monkeypatch
    ) -> None:
        import asyncio

        gate = asyncio.Event()
        adapter = self._fake_stream(monkeypatch, gate)
        out = await _create(db_factory, tenants)
        acme = tenants["acme"]
        async with db_factory() as db:
            resp = await api.stream_message(out.id, api.SessionMessageRequest(prompt="hi"), acme, db)
        body, events = resp.body_iterator, []
        async for event in body:
            events.append(event)
            if '"type": "chunk"' in event:
                break
        turn_id = uuid.UUID(events[0].split('"turn_id": "')[1].split('"')[0])
        async with db_factory() as db:
            state = await api.cancel_turn(out.id, turn_id, acme, db)
        assert state["cancel_requested"] is True
        events += [e async for e in body]
        await chat_turns.drain()
        gate.set()

        error = next(e for e in events if '"type": "error"' in e)
        assert '"code": "TURN_CANCELLED"' in error and '"turn_status": "cancelled"' in error
        assert adapter.terminated == 1
        rows = await _messages(db_factory, out.id)
        assert [(m.seq, m.text) for m in rows] == [(1, "hi"), (2, "a")]
        assert rows[1].payload["partial"] is True
        async with db_factory() as db:
            turn = await chat_turns.get_turn(acme, turn_id)
            assert (turn.status, turn.response_message_id) == ("cancelled", rows[1].id)
            actions = (
                await db.execute(
                    select(AuditLog.action).where(AuditLog.resource_id == str(turn_id))
                )
            ).scalars().all()
        assert {"chat.turn_cancel_requested", "chat.turn_cancelled"} <= set(actions)


class TestConcurrency:
    async def test_streamed_plain_and_legacy_turns_never_share_a_seq(
        self, db_factory, tenants, simulated_stream, monkeypatch
    ) -> None:
        import asyncio

        monkeypatch.setattr(chat_routes, "_conversations", {})
        monkeypatch.setattr(chat_routes, "_cache_loaded_at", {})
        out = await _create(db_factory, tenants)
        acme = tenants["acme"]

        async def plain(i):
            await _send(db_factory, tenants, out.id, f"plain {i}")

        async def streamed(i):
            async with db_factory() as db:
                resp = await api.stream_message(
                    out.id, api.SessionMessageRequest(prompt=f"stream {i}"), acme, db
                )
                await _drain(resp)

        async def legacy_chat(i):
            # The agent's only open session is ``out``, so the legacy route writes into it.
            async with db_factory() as db:
                await chat_routes.chat_with_agent(
                    tenants["agent"], chat_routes.ChatRequest(prompt=f"legacy {i}"), db, acme
                )
                await db.commit()

        await asyncio.gather(
            *(plain(i) for i in range(4)),
            *(streamed(i) for i in range(4)),
            *(legacy_chat(i) for i in range(3)),
        )
        rows = await _messages(db_factory)
        assert {m.session_id for m in rows} == {out.id}
        assert [m.seq for m in rows] == list(range(1, 23))
        async with db_factory() as db:
            assert (await db.get(AgentSessionRecord, out.id)).event_seq == 22


class TestDeprecatedSessionAliases:
    def test_aliases_are_deprecated_and_permissioned(self) -> None:
        aliases = [r for r in legacy.router.routes if "/sessions" in r.path]
        assert len(aliases) == 4
        for route in aliases:
            assert route.deprecated and route.dependencies, route.path

    async def test_aliases_read_and_write_persistent_sessions(self, db_factory, tenants) -> None:
        out = await _create(db_factory, tenants)
        acme, other, agent = tenants["acme"], tenants["other"], tenants["agent"]
        async with db_factory() as db:
            listed = await legacy.list_agent_sessions(agent, acme, db)
            assert [s["session_id"] for s in listed] == [str(out.id)]
            assert await legacy.list_agent_sessions(agent, other, db) == []
            await _expect(404, legacy.pause_session(agent, out.id, other, db))
            await _expect(404, legacy.pause_session(tenants["foreign"], out.id, acme, db))
            assert (await legacy.pause_session(agent, out.id, acme, db))["status"] == "idle"
            assert (await legacy.resume_session(agent, out.id, acme, db))["status"] == "active"
            terminated = await legacy.terminate_session(agent, out.id, acme, db)
            assert terminated["status"] == "terminated"
            await _expect(409, legacy.terminate_session(agent, out.id, acme, db))
            await db.commit()
        async with db_factory() as db:
            canonical = await api.get_session(out.id, acme, db)
            assert canonical.status == "terminated" and canonical.ended_at is not None
