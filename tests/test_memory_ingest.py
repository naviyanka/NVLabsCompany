"""Canonical memory ingest and lifecycle (SQLite; PostgreSQL races live in the PG suite)."""

from __future__ import annotations

import asyncio
import uuid

import pytest
from sqlalchemy import event, func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlmodel import SQLModel

import nexus.models  # noqa: F401
from nexus.memory.ingest import MemoryContext, MemoryInput, MemoryOpError, Origin, ingest_memory
from nexus.memory.lifecycle import archive_memory, reject_memory, supersede_memory
from nexus.memory.safety import MemoryRejected
from nexus.models.agent import Agent
from nexus.models.company import Company
from nexus.models.governance import AuditLog
from nexus.models.memory import MemoryRecord

SECRET = "sk-abcdefghijklmnopqrstuvwx"


@pytest.fixture
async def env(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{(tmp_path / 'm.db').as_posix()}")

    @event.listens_for(engine.sync_engine, "connect")
    def _fk_on(conn, _record):
        cur = conn.cursor()
        cur.execute("PRAGMA foreign_keys=ON")
        cur.close()

    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    ids: dict = {}
    async with factory() as s:
        for key in ("acme", "other"):
            company = Company(name=key)
            s.add(company)
            await s.flush()
            agent = Agent(company_id=company.id, name=key, role="engineer", model="m")
            s.add(agent)
            await s.flush()
            ids[key], ids[f"{key}_agent"] = company.id, agent.id
        await s.commit()
    yield factory, ids
    await engine.dispose()


def _ctx(ids, key="acme", actor="user:tester"):
    return MemoryContext(company_id=ids[key], actor=actor)


def _item(ids, content="Deploys go out on Tuesdays", **kw):
    kw.setdefault("scope", "l2_agent")
    kw.setdefault("agent_id", ids["acme_agent"])
    kw.setdefault("scope_id", ids["acme_agent"])
    return MemoryInput(content=content, **kw)


async def _count(s, **where):
    q = select(func.count()).select_from(MemoryRecord)
    for col, val in where.items():
        q = q.where(getattr(MemoryRecord, col) == val)
    return (await s.execute(q)).scalar_one()


# --- trust defaults -------------------------------------------------------------------


@pytest.mark.parametrize(
    ("origin", "status", "trust"),
    [
        (Origin.API, "active", "asserted"),
        (Origin.HUMAN, "active", "asserted"),
        (Origin.CHAT_EXTRACTION, "candidate", "untrusted"),
        (Origin.SEED, "active", "asserted"),
        (Origin.TOOL, "active", "untrusted"),
        (Origin.SYSTEM, "active", "untrusted"),
    ],
)
async def test_origin_owns_status_and_trust(env, origin, status, trust):
    factory, ids = env
    async with factory() as s:
        res = await ingest_memory(s, _ctx(ids), _item(ids), origin)
    assert (res.record.status, res.record.trust_state) == (status, trust)
    assert res.record.record_metadata["origin"] == origin.value
    assert res.record.record_metadata["recorded_by"] == "user:tester"


async def test_no_origin_can_produce_verified(env):
    factory, ids = env
    async with factory() as s:
        for origin in Origin:
            if origin is Origin.PROMOTION:
                continue
            res = await ingest_memory(s, _ctx(ids), _item(ids, content=f"x {origin}"), origin)
            assert res.record.trust_state != "verified"


async def test_callers_cannot_smuggle_server_fields_through_metadata(env):
    factory, ids = env
    async with factory() as s:
        for key in ("trust", "status", "content_hash", "origin", "recorded_by", "supersedes"):
            with pytest.raises(MemoryRejected):
                await ingest_memory(
                    s, _ctx(ids), _item(ids, metadata={key: "x"}), Origin.API
                )


# --- content and provenance -----------------------------------------------------------


async def test_content_is_redacted_normalized_and_hashed(env):
    import hashlib

    factory, ids = env
    async with factory() as s:
        res = await ingest_memory(
            s, _ctx(ids), _item(ids, content=f"  key {SECRET}  \r\nline two   \n"), Origin.API
        )
    rec = res.record
    assert SECRET not in rec.content and "\r" not in rec.content
    assert rec.content == rec.content.strip()
    assert rec.content_hash == hashlib.sha256(rec.content.encode()).hexdigest()
    assert rec.record_metadata["redacted"] is True


async def test_empty_content_is_refused_without_echo(env):
    factory, ids = env
    async with factory() as s:
        with pytest.raises(MemoryOpError) as err:
            await ingest_memory(s, _ctx(ids), _item(ids, content="  \n "), Origin.API)
    assert err.value.code == "MEMORY_EMPTY"


async def test_audit_carries_no_content(env):
    factory, ids = env
    async with factory() as s:
        await ingest_memory(s, _ctx(ids), _item(ids, content=f"private {SECRET} text"), Origin.API)
        await s.commit()
        rows = (await s.execute(select(AuditLog).where(AuditLog.action == "memory.recorded"))).scalars().all()
    assert len(rows) == 1
    blob = str(rows[0].details)
    assert "private" not in blob and SECRET not in blob
    assert "content_hash" in blob


async def test_bad_scope_and_foreign_agent_are_refused(env):
    factory, ids = env
    async with factory() as s:
        with pytest.raises(MemoryOpError) as bad:
            await ingest_memory(s, _ctx(ids), _item(ids, scope="Bad Scope!"), Origin.API)
        assert bad.value.code == "MEMORY_SCOPE_INVALID"
        with pytest.raises(MemoryOpError) as foreign:
            await ingest_memory(
                s, _ctx(ids), _item(ids, agent_id=ids["other_agent"], scope_id=None), Origin.API
            )
        assert foreign.value.code == "MEMORY_AGENT_NOT_FOUND"
        with pytest.raises(MemoryOpError) as owner:
            await ingest_memory(s, _ctx(ids), _item(ids, scope_id=uuid.uuid4()), Origin.API)
        assert owner.value.code == "MEMORY_SCOPE_MISMATCH"
        assert await _count(s) == 0


async def test_source_reference_cannot_cross_tenants(env):
    factory, ids = env
    async with factory() as s:
        other = await ingest_memory(
            s, _ctx(ids, "other"),
            MemoryInput(scope="company", content="theirs", scope_id=ids["other"]),
            Origin.API,
        )
        await s.commit()
        with pytest.raises(MemoryOpError) as err:
            await ingest_memory(
                s, _ctx(ids),
                _item(ids, source_type="memory_record", source_id=str(other.record.id)),
                Origin.API,
            )
    assert err.value.code == "MEMORY_SOURCE_INVALID"
    assert str(other.record.id) not in str(err.value)


# --- idempotency ----------------------------------------------------------------------


async def test_same_source_event_returns_the_existing_row(env):
    factory, ids = env
    kw = dict(source_type="api_request", source_id="req-1", extractor_version="v1", item_key="0")
    async with factory() as s:
        a = await ingest_memory(s, _ctx(ids), _item(ids, **kw), Origin.API)
        b = await ingest_memory(s, _ctx(ids), _item(ids, **kw), Origin.API)
        assert (a.created, b.created) == (True, False)
        assert a.record.id == b.record.id
        assert await _count(s) == 1


async def test_identical_text_from_different_sources_stays_separate(env):
    factory, ids = env
    async with factory() as s:
        a = await ingest_memory(
            s, _ctx(ids), _item(ids, source_type="api_request", source_id="r1"), Origin.API
        )
        b = await ingest_memory(
            s, _ctx(ids), _item(ids, source_type="api_request", source_id="r2"), Origin.API
        )
        assert a.record.id != b.record.id
        assert a.record.content_hash == b.record.content_hash
        assert a.record.ingestion_key != b.record.ingestion_key


async def test_same_text_in_two_companies_is_two_rows(env):
    factory, ids = env
    kw = dict(source_type="api_request", source_id="same", scope="company")
    async with factory() as s:
        a = await ingest_memory(
            s, _ctx(ids), MemoryInput(content="x", scope_id=ids["acme"], **kw), Origin.API
        )
        b = await ingest_memory(
            s, _ctx(ids, "other"),
            MemoryInput(content="x", scope_id=ids["other"], **kw), Origin.API,
        )
        assert a.record.id != b.record.id


async def test_idempotency_key_reuse_with_different_payload_conflicts(env):
    factory, ids = env
    kw = dict(source_type="api_request", source_id="idem-1", extractor_version="api-v1")
    async with factory() as s:
        first = await ingest_memory(
            s, _ctx(ids), _item(ids, **kw), Origin.API, payload_conflict_409=True
        )
        same = await ingest_memory(
            s, _ctx(ids), _item(ids, **kw), Origin.API, payload_conflict_409=True
        )
        assert same.record.id == first.record.id and not same.created
        with pytest.raises(MemoryOpError) as err:
            await ingest_memory(
                s, _ctx(ids), _item(ids, content="something else", **kw), Origin.API,
                payload_conflict_409=True,
            )
        assert (err.value.code, err.value.status_code) == ("MEMORY_IDEMPOTENCY_CONFLICT", 409)
        assert await _count(s) == 1


async def test_concurrent_identical_ingest_yields_one_row(env):
    factory, ids = env
    kw = dict(source_type="api_request", source_id="race", extractor_version="v1")

    async def one():
        async with factory() as s:
            res = await ingest_memory(s, _ctx(ids), _item(ids, **kw), Origin.API)
            await s.commit()
            return res.record.id

    got = await asyncio.gather(*(one() for _ in range(6)), return_exceptions=True)
    ok = [g for g in got if isinstance(g, uuid.UUID)]
    assert ok and len(set(ok)) == 1
    async with factory() as s:
        assert await _count(s) == 1


# --- append-only ----------------------------------------------------------------------


async def test_orm_cannot_rewrite_content_or_provenance(env):
    factory, ids = env
    async with factory() as s:
        rec_id = (await ingest_memory(s, _ctx(ids), _item(ids), Origin.API)).record.id
        await s.commit()
    for field, value in (
        ("content", "changed"), ("content_hash", "0" * 64), ("ingestion_key", "k"),
        ("source_id", "other"),
    ):
        async with factory() as s:
            rec = await s.get(MemoryRecord, rec_id)
            setattr(rec, field, value)
            with pytest.raises(ValueError, match="immutable"):
                await s.flush()


# --- lifecycle ------------------------------------------------------------------------


async def test_archive_keeps_content_and_is_idempotent(env):
    factory, ids = env
    async with factory() as s:
        rec = (await ingest_memory(s, _ctx(ids), _item(ids), Origin.API)).record
        again = await archive_memory(s, _ctx(ids, actor="user:boss"), rec.id, reason="stale")
        assert again.status == "archived"
        assert again.content == rec.content and again.content_hash == rec.content_hash
        assert again.lifecycle_changed_by == "user:boss" and again.lifecycle_changed_at
        second = await archive_memory(s, _ctx(ids), rec.id)
        assert second.status == "archived"
        assert await _count(s) == 1
        n = (await s.execute(select(func.count()).select_from(AuditLog).where(
            AuditLog.action == "memory.archived"))).scalar_one()
        assert n == 1  # the repeat is not a second event


async def test_lifecycle_is_tenant_scoped(env):
    factory, ids = env
    async with factory() as s:
        rec = (await ingest_memory(s, _ctx(ids), _item(ids), Origin.API)).record
        with pytest.raises(MemoryOpError) as err:
            await archive_memory(s, _ctx(ids, "other"), rec.id)
        assert err.value.code == "MEMORY_NOT_FOUND"
        with pytest.raises(MemoryOpError) as none:
            await archive_memory(s, _ctx(ids), uuid.uuid4())
        assert none.value.code == "MEMORY_NOT_FOUND"
        assert (await s.get(MemoryRecord, rec.id)).status == "active"


async def test_invalid_transitions_have_stable_codes(env):
    factory, ids = env
    async with factory() as s:
        active = (await ingest_memory(s, _ctx(ids), _item(ids), Origin.API)).record
        with pytest.raises(MemoryOpError) as e1:
            await reject_memory(s, _ctx(ids), active.id)  # only candidates can be rejected
        assert e1.value.code == "MEMORY_INVALID_TRANSITION"
        await archive_memory(s, _ctx(ids), active.id)
        with pytest.raises(MemoryOpError) as e2:
            await reject_memory(s, _ctx(ids), active.id)
        assert e2.value.code == "MEMORY_ALREADY_ARCHIVED"


async def test_reject_candidate_then_repeat(env):
    factory, ids = env
    async with factory() as s:
        cand = (await ingest_memory(s, _ctx(ids), _item(ids), Origin.CHAT_EXTRACTION)).record
        assert (await reject_memory(s, _ctx(ids), cand.id)).status == "rejected"
        assert (await reject_memory(s, _ctx(ids), cand.id)).status == "rejected"
        with pytest.raises(MemoryOpError) as err:
            await archive_memory(s, _ctx(ids), cand.id)
        assert err.value.code == "MEMORY_INVALID_TRANSITION"


async def test_supersede_links_and_preserves_the_old_row(env):
    factory, ids = env
    async with factory() as s:
        old = (await ingest_memory(s, _ctx(ids), _item(ids), Origin.API)).record
        res = await supersede_memory(
            s, _ctx(ids), old.id, _item(ids, content="Deploys go out on Wednesdays"), Origin.API
        )
        await s.commit()
        assert res.created and res.record.supersedes_id == old.id
        assert res.record.status == "active"
        fresh = await s.get(MemoryRecord, old.id, populate_existing=True)
        assert fresh.status == "superseded" and fresh.content == "Deploys go out on Tuesdays"
        assert fresh.record_metadata["superseded_by"] == str(res.record.id)
        # identical repeat -> same successor, no new row
        again = await supersede_memory(
            s, _ctx(ids), old.id, _item(ids, content="Deploys go out on Wednesdays"), Origin.API
        )
        assert again.record.id == res.record.id and not again.created
        # a different replacement conflicts
        with pytest.raises(MemoryOpError) as err:
            await supersede_memory(
                s, _ctx(ids), old.id, _item(ids, content="Thursdays"), Origin.API
            )
        assert err.value.code == "MEMORY_SUPERSESSION_CONFLICT"
        assert await _count(s) == 2


async def test_supersede_rejects_cross_company_target(env):
    factory, ids = env
    async with factory() as s:
        theirs = (await ingest_memory(
            s, _ctx(ids, "other"),
            MemoryInput(scope="company", content="theirs", scope_id=ids["other"]), Origin.API,
        )).record
        with pytest.raises(MemoryOpError) as err:
            await supersede_memory(s, _ctx(ids), theirs.id, _item(ids, content="mine"), Origin.API)
        assert err.value.code == "MEMORY_NOT_FOUND"
        assert await _count(s, company_id=ids["acme"]) == 0


async def test_supersede_of_archived_row_is_refused(env):
    factory, ids = env
    async with factory() as s:
        old = (await ingest_memory(s, _ctx(ids), _item(ids), Origin.API)).record
        await archive_memory(s, _ctx(ids), old.id)
        with pytest.raises(MemoryOpError) as err:
            await supersede_memory(s, _ctx(ids), old.id, _item(ids, content="new"), Origin.API)
        assert err.value.code == "MEMORY_ALREADY_ARCHIVED"
        assert await _count(s) == 1


async def test_concurrent_archive_is_deterministic(env):
    factory, ids = env
    async with factory() as s:
        rec = (await ingest_memory(s, _ctx(ids), _item(ids), Origin.API)).record
        await s.commit()

    async def go():
        async with factory() as s:
            out = await archive_memory(s, _ctx(ids), rec.id)
            await s.commit()
            return out.status

    got = await asyncio.gather(*(go() for _ in range(5)), return_exceptions=True)
    assert got == ["archived"] * 5
