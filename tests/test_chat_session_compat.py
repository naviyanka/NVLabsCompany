"""The legacy per-agent chat routes keep their contract while writing into sessions.

POST /api/v1/agents/{id}/chat must return the same response shape it always
did; underneath, each turn now lands in the agent's default session with a
timeline seq, and a ws03-backfilled legacy session is continued rather than
replaced.
"""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlmodel import SQLModel, select

import nexus.models  # noqa: F401 -- registers every table on SQLModel.metadata
from nexus.api.routes import chat as chat_routes
from nexus.models.agent import Agent
from nexus.models.agent_session import AgentSessionRecord
from nexus.models.chat import ChatMessage
from nexus.models.company import Company


@pytest.fixture
async def setup(tmp_path, monkeypatch):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'compat.db'}")
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)

    import nexus.database as database

    monkeypatch.setattr(database, "async_session_factory", factory)

    async def fake_prompt(db, agent, company_id, prompt):
        return "system"

    async def fake_llm(agent, system_prompt, prompt, history, temperature=None, session_id=None, **kw):
        return f"echo: {prompt}", "test-model", 3

    monkeypatch.setattr(chat_routes, "_build_chat_prompt", fake_prompt)
    monkeypatch.setattr(chat_routes, "_call_llm", fake_llm)
    monkeypatch.setattr(chat_routes, "_conversations", {})
    monkeypatch.setattr(chat_routes, "_cache_loaded_at", {})

    company = Company(name="Acme")
    async with factory() as db:
        db.add(company)
        await db.flush()
        agent = Agent(company_id=company.id, name="Navi", role="engineer")
        db.add(agent)
        await db.commit()
    yield factory, company.id, agent
    await engine.dispose()


async def _chat(factory, company_id, agent_id, prompt):
    async with factory() as db:
        resp = await chat_routes.chat_with_agent(
            agent_id, chat_routes.ChatRequest(prompt=prompt), db, company_id
        )
        await db.commit()
    return resp


async def test_response_shape_is_unchanged(setup) -> None:
    factory, company_id, agent = setup
    resp = await _chat(factory, company_id, agent.id, "hello")
    assert set(resp.model_dump()) == {"message", "history", "model_used", "tokens_used"}
    assert (
        resp.message.text == "echo: hello"
        and resp.model_used == "test-model"
        and resp.tokens_used == 3
    )
    assert [m.sender for m in resp.history] == ["user", "agent"]


async def test_turns_land_in_one_default_session(setup) -> None:
    factory, company_id, agent = setup
    await _chat(factory, company_id, agent.id, "one")
    await _chat(factory, company_id, agent.id, "two")

    async with factory() as db:
        sessions = (await db.execute(select(AgentSessionRecord))).scalars().all()
        assert (
            len(sessions) == 1 and sessions[0].created_by == "chat" and sessions[0].event_seq == 4
        )
        rows = (await db.execute(select(ChatMessage).order_by(ChatMessage.seq))).scalars().all()
        assert {r.session_id for r in rows} == {sessions[0].id}
        assert [(r.seq, r.sender) for r in rows] == [
            (1, "user"),
            (2, "agent"),
            (3, "user"),
            (4, "agent"),
        ]
        assert rows[1].model_used == "test-model" and rows[1].tokens_used == 3


async def test_backfilled_legacy_session_is_continued(setup) -> None:
    factory, company_id, agent = setup
    async with factory() as db:
        legacy = AgentSessionRecord(
            company_id=company_id,
            agent_id=agent.id,
            status="idle",
            event_seq=2,
            session_metadata={"legacy": True, "backfill": "ws03"},
        )
        db.add(legacy)
        await db.commit()

    await _chat(factory, company_id, agent.id, "resume")

    async with factory() as db:
        assert len((await db.execute(select(AgentSessionRecord))).scalars().all()) == 1
        rows = (await db.execute(select(ChatMessage).order_by(ChatMessage.seq))).scalars().all()
        assert [(r.session_id, r.seq) for r in rows] == [(legacy.id, 3), (legacy.id, 4)]


async def _update(factory, table, row_id, **fields):
    async with factory() as db:
        row = await db.get(table, row_id)
        for key, value in fields.items():
            setattr(row, key, value)
        await db.commit()


async def test_agent_config_change_rolls_over_to_a_new_session(setup) -> None:
    from nexus.models.governance import AuditLog

    factory, company_id, agent = setup
    await _chat(factory, company_id, agent.id, "before")
    await _update(factory, Agent, agent.id, model="another-model")
    await _chat(factory, company_id, agent.id, "after")

    async with factory() as db:
        first, second = (
            (await db.execute(select(AgentSessionRecord).order_by(AgentSessionRecord.started_at)))
            .scalars()
            .all()
        )
        assert first.status == "completed" and first.ended_at is not None
        assert (second.status, second.model, second.event_seq) == ("active", "another-model", 2)
        audit = (
            await db.execute(select(AuditLog).where(AuditLog.action == "session.rolled_over"))
        ).scalar_one()
        assert audit.resource_id == str(first.id)
        assert audit.details["next_session_id"] == str(second.id)


async def test_idle_default_session_wakes(setup) -> None:
    factory, company_id, agent = setup
    await _chat(factory, company_id, agent.id, "one")
    async with factory() as db:
        session = (await db.execute(select(AgentSessionRecord))).scalar_one()
    await _update(factory, AgentSessionRecord, session.id, status="idle")
    await _chat(factory, company_id, agent.id, "two")
    async with factory() as db:
        record = (await db.execute(select(AgentSessionRecord))).scalar_one()
        assert (record.id, record.status, record.event_seq) == (session.id, "active", 4)


async def test_unavailable_pinned_connection_is_409_not_a_fallback(setup) -> None:
    from fastapi import HTTPException

    from nexus.models.connection import LLMConnection

    factory, company_id, agent = setup
    conn = LLMConnection(
        company_id=company_id, name="gw", base_url="http://gw", wire_format="openai"
    )
    async with factory() as db:
        db.add(conn)
        await db.commit()
    await _update(factory, Agent, agent.id, connection_id=conn.id)
    await _chat(factory, company_id, agent.id, "one")
    await _update(factory, LLMConnection, conn.id, is_active=False)

    with pytest.raises(HTTPException) as exc:
        await _chat(factory, company_id, agent.id, "two")
    assert exc.value.status_code == 409
    async with factory() as db:
        assert len((await db.execute(select(ChatMessage))).scalars().all()) == 2
