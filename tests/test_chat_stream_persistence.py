"""A streamed conversation has to survive a restart, same as a plain one.

The non-streaming chat endpoint writes both messages to ``chat_messages``. The
streaming endpoint wrote only to the in-process cache, so a streamed exchange was
gone on restart and invisible to a second worker. The reply is written from inside
the SSE generator, which runs after the request's session is closed, so it needs a
session of its own -- that is what these tests pin.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlmodel import SQLModel, select

import nexus.models  # noqa: F401 -- registers every table on SQLModel.metadata
from nexus.api.routes import chat as chat_routes
from nexus.models.chat import ChatMessage


@pytest.fixture
async def chat_db(tmp_path, monkeypatch):
    """Real SQLite, with the module's session factory pointed at it."""
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'chat.db'}")
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)

    import nexus.database as database

    monkeypatch.setattr(database, "async_session_factory", factory)
    yield factory
    await engine.dispose()


async def stored_messages(factory) -> list[ChatMessage]:
    """Every persisted chat message, oldest first."""
    async with factory() as session:
        result = await session.execute(select(ChatMessage).order_by(ChatMessage.created_at))
        return list(result.scalars())


class TestGeneratorPersistence:
    """`_persist_from_generator` opens its own session on purpose."""

    async def test_message_is_written_without_a_request_session(self, chat_db) -> None:
        agent_id, company_id = uuid.uuid4(), uuid.uuid4()

        await chat_routes._persist_from_generator(
            agent_id, company_id, "agent", "streamed reply"
        )

        rows = await stored_messages(chat_db)
        assert len(rows) == 1
        assert rows[0].sender == "agent"
        assert rows[0].text == "streamed reply"
        assert rows[0].agent_id == agent_id
        assert rows[0].company_id == company_id

    async def test_both_sides_of_an_exchange_are_stored(self, chat_db) -> None:
        agent_id, company_id = uuid.uuid4(), uuid.uuid4()

        async with chat_db() as session:
            await chat_routes._persist_message_to_db(
                session, agent_id, company_id, "user", "what is the status"
            )
            await session.commit()
        await chat_routes._persist_from_generator(
            agent_id, company_id, "agent", "all green"
        )

        rows = await stored_messages(chat_db)
        assert [row.sender for row in rows] == ["user", "agent"]

    async def test_a_failure_does_not_propagate_into_the_stream(
        self, chat_db, monkeypatch
    ) -> None:
        """A persistence problem must not break a response already streaming."""
        import nexus.database as database

        def explode(*a: object, **k: object) -> None:
            raise RuntimeError("database is gone")

        monkeypatch.setattr(database, "async_session_factory", explode)

        # Must not raise.
        await chat_routes._persist_from_generator(
            uuid.uuid4(), uuid.uuid4(), "agent", "reply"
        )

    async def test_long_text_is_truncated_not_rejected(self, chat_db) -> None:
        agent_id, company_id = uuid.uuid4(), uuid.uuid4()

        await chat_routes._persist_from_generator(
            agent_id, company_id, "agent", "x" * 20_000
        )

        rows = await stored_messages(chat_db)
        assert len(rows) == 1
        assert len(rows[0].text) == 10_000
