"""Chat-extracted memory has stable, server-owned provenance, so a replay never duplicates.

The source of a chat fact is the durable ChatTurn (or, with no turn, a digest of the
reply), never a random id. Replays are checked after archiving the first row, so the
result comes from the ingestion key and not from the L2 near-duplicate check.
"""
# ruff: noqa: F811 -- pytest fixtures imported from test_chat_durable_memory

from __future__ import annotations

import uuid

from sqlalchemy import select

from nexus.api.routes import chat as chat_module
from nexus.memory.ingest import MemoryContext, MemoryInput, Origin, ingest_memory
from nexus.memory.lifecycle import archive_memory
from nexus.models.memory import MemoryRecord
from tests.test_chat_durable_memory import (  # noqa: F401 -- fixtures
    company_and_agents,
    patched_db,
    session_factory,
)
from tests.test_durable_chat_turns import _send, db, t  # noqa: F401 -- fixtures and helper

REPLY = (
    "I learned that deploys go out on Tuesdays. I learned that the cache key includes the tenant."
)


async def _rows(factory) -> list[MemoryRecord]:
    async with factory() as s:
        return list((await s.execute(select(MemoryRecord).order_by(MemoryRecord.id))).scalars())


async def _archive_all(factory, company_id) -> None:
    async with factory() as s:
        for row in (await s.execute(select(MemoryRecord))).scalars().all():
            await archive_memory(s, MemoryContext(company_id, "test"), row.id)
        await s.commit()


async def test_retrying_a_turn_returns_the_existing_records(patched_db, company_and_agents):
    _, alpha, _ = company_and_agents
    turn = uuid.uuid4()

    assert await chat_module._remember_response(alpha, REPLY, turn_id=turn) == 2
    first = await _rows(patched_db)
    assert await chat_module._remember_response(alpha, REPLY, turn_id=turn) == 0

    # Archive them so the L2 duplicate check cannot hide a key mismatch: the replay must
    # derive the same ingestion keys and find these rows.
    await _archive_all(patched_db, alpha.company_id)
    assert await chat_module._remember_response(alpha, REPLY, turn_id=turn) == 0
    rows = await _rows(patched_db)
    assert len(rows) == 2
    assert {r.ingestion_key for r in rows} == {r.ingestion_key for r in first}
    assert all(r.source_type == "chat_reply" and r.source_id == str(turn) for r in rows)
    assert not any(str(r.source_id).startswith("evt:") for r in rows)


async def test_two_facts_from_one_reply_stay_distinct(patched_db, company_and_agents):
    _, alpha, _ = company_and_agents
    await chat_module._remember_response(alpha, REPLY, turn_id=uuid.uuid4())
    rows = await _rows(patched_db)
    assert len(rows) == 2 and len({r.ingestion_key for r in rows}) == 2
    assert len({r.content_hash for r in rows}) == 2


async def test_same_fact_twice_in_one_reply_is_one_row(patched_db, company_and_agents):
    _, alpha, _ = company_and_agents
    text = "I learned that the cache key includes the tenant. " * 2
    assert await chat_module._remember_response(alpha, text, turn_id=uuid.uuid4()) == 1
    assert len(await _rows(patched_db)) == 1


async def test_identical_text_from_different_turns_keeps_separate_provenance(
    patched_db, company_and_agents
):
    # Straight to ingest: store_fact's near-duplicate check would drop the second live copy.
    _, alpha, _ = company_and_agents
    ctx = MemoryContext(alpha.company_id, f"agent:{alpha.id}")
    turns = [str(uuid.uuid4()), str(uuid.uuid4())]
    async with patched_db() as s:
        for turn in turns:
            item = MemoryInput(
                scope="l2_agent",
                content="the cache key includes the tenant",
                agent_id=alpha.id,
                scope_id=alpha.id,
                source_type="chat_reply",
                source_id=turn,
                extractor_version=chat_module.FACT_EXTRACTOR_VERSION,
                item_key="learned:0",
            )
            await ingest_memory(s, ctx, item, Origin.CHAT_EXTRACTION)
        await s.commit()
    rows = await _rows(patched_db)
    assert len(rows) == 2 and {r.source_id for r in rows} == set(turns)
    assert len({r.ingestion_key for r in rows}) == 2


async def test_a_genuinely_new_reply_on_the_same_turn_gets_its_own_row(
    patched_db, company_and_agents
):
    _, alpha, _ = company_and_agents
    turn = uuid.uuid4()
    await chat_module._remember_response(
        alpha, "I learned that deploys go out on Tuesdays.", turn_id=turn
    )
    await chat_module._remember_response(
        alpha, "I learned that rollbacks need a ticket.", turn_id=turn
    )
    rows = await _rows(patched_db)
    assert len(rows) == 2 and {r.source_id for r in rows} == {str(turn)}


async def test_reply_without_a_turn_has_a_stable_derived_source(patched_db, company_and_agents):
    _, alpha, _ = company_and_agents
    assert await chat_module._remember_response(alpha, REPLY) == 2
    await _archive_all(patched_db, alpha.company_id)
    assert await chat_module._remember_response(alpha, REPLY) == 0
    rows = await _rows(patched_db)
    assert len(rows) == 2
    assert all(r.source_id.startswith("reply:") and "evt:" not in r.source_id for r in rows)
    assert len({r.source_id for r in rows}) == 1


async def test_turn_worker_passes_the_durable_turn_id(db, t, monkeypatch):
    seen = []

    async def llm(agent, system_prompt, prompt, history, **kw):
        seen.append(kw.get("turn_id"))
        return "ok", "m", 1

    monkeypatch.setattr(chat_module, "_call_llm", llm)
    out = await _send(db, t["acme"], t["acme_session"], key="k1")
    assert seen == [uuid.UUID(out["turn_id"])]


async def test_public_write_cannot_set_source_identity(db, t):
    from nexus.api.routes import memory as memory_routes

    body = memory_routes.MemoryCreate.model_validate(
        {
            "scope": "company",
            "content": "ship on tuesday",
            "source_id": "forged",
            "source_type": "seed",
            "ingestion_key": "forged",
            "status": "verified",
        }
    )
    assert not {"source_id", "source_type", "ingestion_key", "status"} & set(body.model_dump())
