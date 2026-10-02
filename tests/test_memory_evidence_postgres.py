"""Memory evidence on real PostgreSQL: forced RLS, append-only triggers, races, atomicity.

Migration ``b4d9f2a61c73``. Runs against a disposable PostgreSQL (testcontainers, or
``TEST_DATABASE_URL``); skipped when neither is available. Races use two real sessions and
``asyncio.gather``; there are no sleeps and no polling. Each race asserts what must hold
whichever caller wins: one winner, a stable refusal for the other, and state, evidence and
audit that agree.
"""
# ruff: noqa: F811 -- pytest fixtures imported from test_postgres_integration

import asyncio
import re
import uuid
from pathlib import Path
from types import SimpleNamespace

import alembic.command
import alembic.config
import httpx
import pytest
import sqlalchemy as sa
from fastapi import FastAPI, Request
from sqlalchemy import make_url
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from nexus.api.routes import memory_evidence as routes
from nexus.auth.principal import Principal
from nexus.auth.users import create_user
from nexus.database import tenant_session
from nexus.memory import evidence as ev
from nexus.memory.ingest import MemoryContext, MemoryInput, MemoryOpError, Origin
from nexus.memory.lifecycle import (
    accept_candidate,
    archive_memory,
    assert_trust,
    reject_memory,
    supersede_memory,
    verify_trust,
)
from nexus.models.agent import Agent
from nexus.models.company import Company
from nexus.models.governance import AuditLog
from nexus.models.memory import MemoryRecord
from nexus.models.memory_evidence import MemoryEvidence, MemoryOperation
from nexus.models.task import Task
from nexus.models.task_attempt import TaskAttempt
from tests.test_postgres_integration import (  # noqa: F401 -- fixtures
    app_role,
    app_user_postgres_url,
    migrated_postgres_url,
    postgres_container,
)

pytestmark = [pytest.mark.postgres, pytest.mark.integration]

TABLES = ("memory_evidence", "memory_operations")
PASSED = {"passed": True, "outcome": "completed", "checks": [{"passed": True}]}
RACERS = 6


class World:
    """One company with an admin, plus a second company, seeded as the superuser."""


@pytest.fixture
async def world(migrated_postgres_url, app_role):
    engine = create_async_engine(migrated_postgres_url)
    w = World()
    w.engine = engine
    w.acme, w.other = uuid.uuid4(), uuid.uuid4()
    w.agent, w.other_agent = uuid.uuid4(), uuid.uuid4()
    async with AsyncSession(engine, expire_on_commit=False) as db:
        db.add_all([Company(id=w.acme, name="Acme"), Company(id=w.other, name="Other")])
        await db.flush()
        db.add_all([
            Agent(id=w.agent, company_id=w.acme, name="A", role="engineer"),
            Agent(id=w.other_agent, company_id=w.other, name="F", role="engineer"),
        ])
        await db.flush()
        w.admin = await create_user(db, email=f"a-{w.acme}@example.com", password="x" * 14,
                                    company_id=w.acme, role="admin")
        w.admin2 = await create_user(db, email=f"b-{w.acme}@example.com", password="x" * 14,
                                     company_id=w.acme, role="admin")
        w.outsider = await create_user(db, email=f"o-{w.other}@example.com", password="x" * 14,
                                       company_id=w.other, role="admin")
        await db.commit()
    w.ctx = MemoryContext(w.acme, f"user:{w.admin.id}")

    async def memory(status="candidate", company=None, trust="untrusted"):
        company = company or w.acme
        async with AsyncSession(engine, expire_on_commit=False) as db:
            row = MemoryRecord(company_id=company, scope="company", content=f"c-{uuid.uuid4()}",
                               status=status, trust_state=trust)
            db.add(row)
            await db.commit()
            return row

    async def attempt(passed=True, company=None):
        company = company or w.acme
        async with AsyncSession(engine, expire_on_commit=False) as db:
            task = Task(company_id=company, title="work", status="in_progress")
            db.add(task)
            await db.flush()
            row = TaskAttempt(
                company_id=company, task_id=task.id,
                agent_id=w.agent if company == w.acme else w.other_agent, attempt_number=1,
                idempotency_key=str(uuid.uuid4()), status="completed",
                completion_reason="goal", verification={**PASSED, "passed": passed},
            )
            db.add(row)
            await db.commit()
            return row

    async def one(model, **where):
        async with AsyncSession(engine) as db:
            stmt = sa.select(model)
            for k, v in where.items():
                stmt = stmt.where(getattr(model, k) == v)
            return list((await db.execute(stmt)).scalars())

    async def audits(action):
        return [a for a in await one(AuditLog, company_id=w.acme) if a.action == action]

    w.memory, w.attempt, w.one, w.audits = memory, attempt, one, audits
    yield w
    await engine.dispose()


async def attach_attestation(w, memory, reason="independently_verified_by_admin", key=None):
    async with tenant_session(w.acme) as db:
        out = await ev.attach_evidence(
            db, w.ctx, memory.id, evidence_kind="human_attestation", source_id=None,
            reason_code=reason, idempotency_key=key or f"k-{uuid.uuid4()}",
        )
        await db.commit()
    return uuid.UUID(out["evidence_id"])


async def promoted(w, memory):
    """An active memory asserted by attestation, ready to verify."""
    e = await attach_attestation(w, memory)
    async with tenant_session(w.acme) as db:
        await assert_trust(db, w.ctx, memory.id, e)
        await db.commit()
    return e


async def outcome(coro):
    try:
        return await coro
    except MemoryOpError as exc:
        return exc.code


# --- schema, RLS, triggers -----------------------------------------------------------------


async def test_forced_rls_and_migration_round_trip(migrated_postgres_url):
    cfg = alembic.config.Config("alembic.ini")
    cfg.set_main_option("sqlalchemy.url", migrated_postgres_url)
    engine = create_async_engine(migrated_postgres_url)

    async def state():
        async with engine.connect() as conn:
            rls = (await conn.execute(sa.text(
                "SELECT c.relname, c.relrowsecurity, c.relforcerowsecurity, "
                "(SELECT count(*) FROM pg_policies p WHERE p.tablename = c.relname "
                " AND p.policyname = 'tenant_isolation') "
                "FROM pg_class c WHERE c.relname = ANY(:t) ORDER BY 1"), {"t": list(TABLES)}
            )).all()
            triggers = (await conn.execute(sa.text(
                "SELECT count(*) FROM pg_trigger WHERE NOT tgisinternal "
                "AND tgrelid::regclass::text = ANY(:t)"), {"t": list(TABLES)})).scalar_one()
            return [tuple(r) for r in rls], triggers

    try:
        assert await state() == (
            [("memory_evidence", True, True, 1), ("memory_operations", True, True, 1)], 4)
        await asyncio.to_thread(alembic.command.downgrade, cfg, "e7a1c2d3f408")
        try:
            assert await state() == ([], 0)
        finally:
            await asyncio.to_thread(alembic.command.upgrade, cfg, "head")
        assert (await state())[1] == 4
    finally:
        await engine.dispose()


async def test_force_rls_binds_the_table_owner(migrated_postgres_url):
    """A non-superuser owner is subject to the policy because of FORCE; rolled back after."""
    engine = create_async_engine(migrated_postgres_url)
    try:
        async with AsyncSession(engine) as db:
            cid = uuid.uuid4()
            db.add(Company(id=cid, name="Owner Corp"))
            await db.flush()
            mem = MemoryRecord(company_id=cid, scope="company", content="x", status="active")
            db.add(mem)
            await db.flush()
            db.add(MemoryEvidence(
                company_id=cid, memory_id=mem.id, evidence_kind="chat_turn",
                source_type="chat_turn", source_id=str(uuid.uuid4()), grade="none",
                source_digest="0" * 64, policy_version="p", idempotency_key="k" * 8,
                created_by="user:x",
            ))
            await db.flush()
            await db.execute(sa.text("CREATE ROLE tmp_evidence_owner NOSUPERUSER NOBYPASSRLS"))
            for table in TABLES:
                await db.execute(sa.text(f"ALTER TABLE {table} OWNER TO tmp_evidence_owner"))
            await db.execute(sa.text("SET LOCAL ROLE tmp_evidence_owner"))
            count = "SELECT count(*) FROM memory_evidence WHERE company_id = :c"
            assert (await db.execute(sa.text(count), {"c": cid})).scalar_one() == 0
            await db.execute(
                sa.text("SELECT set_config('nexus.company_id', :c, true)"), {"c": str(cid)}
            )
            assert (await db.execute(sa.text(count), {"c": cid})).scalar_one() == 1

            # With the triggers off, the policy alone refuses a row for another company.
            for table in TABLES:
                await db.execute(sa.text(f"ALTER TABLE {table} DISABLE TRIGGER USER"))
            with pytest.raises(DBAPIError, match="row-level security"):
                await db.execute(sa.text(
                    "INSERT INTO memory_evidence (id, company_id, memory_id, evidence_kind, "
                    "source_type, source_id, reason_code, grade, source_digest, "
                    "policy_version, idempotency_key, created_by, created_at) "
                    "VALUES (:i, :c, :m, 'chat_turn', 'chat_turn', 's', '', 'none', :d, "
                    "'p', 'policy-only-key', 'user:x', now())"
                ), {"i": uuid.uuid4(), "c": uuid.uuid4(), "m": mem.id, "d": "0" * 64})
            await db.rollback()
    finally:
        await engine.dispose()


async def test_unbound_session_reads_nothing_and_cannot_insert(world, app_role):
    m = await world.memory("active")
    await attach_attestation(world, m)
    async with app_role() as db:  # no tenant bound
        for model in (MemoryEvidence, MemoryOperation):
            assert (await db.execute(sa.select(model))).scalars().all() == []
        db.add(MemoryEvidence(
            company_id=world.acme, memory_id=m.id, evidence_kind="chat_turn",
            source_type="chat_turn", source_id=str(uuid.uuid4()), grade="none",
            source_digest="0" * 64, policy_version="p", idempotency_key="unbound-key",
            created_by="user:x",
        ))
        with pytest.raises(DBAPIError, match="row-level security|own company"):
            await db.commit()


async def test_tenants_see_only_their_own_rows_and_cannot_write_for_each_other(world):
    mine = await world.memory("active")
    await attach_attestation(world, mine)
    theirs = await world.memory("active", company=world.other)
    async with tenant_session(world.other) as db:
        assert (await db.execute(sa.select(MemoryEvidence))).scalars().all() == []
        assert (await db.execute(sa.select(MemoryOperation))).scalars().all() == []
        # A forged company_id is refused by the policy ...
        db.add(MemoryEvidence(
            company_id=world.acme, memory_id=theirs.id, evidence_kind="chat_turn",
            source_type="chat_turn", source_id=str(uuid.uuid4()), grade="none",
            source_digest="0" * 64, policy_version="p", idempotency_key="forged-company",
            created_by="user:x",
        ))
        with pytest.raises(DBAPIError, match="row-level security|own company"):
            await db.commit()
    async with tenant_session(world.other) as db:
        # ... and so is naming another company's memory under one's own company_id.
        db.add(MemoryEvidence(
            company_id=world.other, memory_id=mine.id, evidence_kind="chat_turn",
            source_type="chat_turn", source_id=str(uuid.uuid4()), grade="none",
            source_digest="0" * 64, policy_version="p", idempotency_key="forged-memory",
            created_by="user:x",
        ))
        with pytest.raises(DBAPIError, match="own company"):
            await db.commit()
    assert len(await world.one(MemoryEvidence, company_id=world.acme)) == 1


async def test_evidence_and_ledger_rows_are_append_only_even_for_the_owner(world):
    m = await world.memory("active")
    async with tenant_session(world.acme) as db:
        await ev.run_once(
            db, world.ctx, key="ledger-key-12345", operation="attach_evidence", memory_id=m.id,
            digest="d" * 64,
            effect=lambda: ev.attach_evidence(
                db, world.ctx, m.id, evidence_kind="human_attestation", source_id=None,
                reason_code="reviewed_by_admin", idempotency_key="ledger-key-12345",
            ),
        )
        await db.commit()
    assert len(await world.one(MemoryOperation, company_id=world.acme)) == 1
    async with AsyncSession(world.engine) as db:  # superuser: only the trigger can stop it
        for stmt in (
            "UPDATE memory_evidence SET grade = 'verify'",
            "DELETE FROM memory_evidence",
            "UPDATE memory_operations SET actor = 'x'",
            "DELETE FROM memory_operations",
        ):
            with pytest.raises(DBAPIError, match="append-only"):
                await db.execute(sa.text(stmt))
            await db.rollback()
        with pytest.raises(DBAPIError):  # the memory cannot be removed from under its evidence
            await db.execute(sa.text("DELETE FROM memory_records WHERE id = :i"), {"i": m.id})
        await db.rollback()
    assert len(await world.one(MemoryEvidence, memory_id=m.id)) == 1


# --- one effect per request under concurrency ----------------------------------------------


def _app(world, as_user):
    app = FastAPI()
    app.include_router(routes.router)

    @app.middleware("http")
    async def principal(request: Request, call_next):
        who = request.headers.get("x-test-user")
        request.state.principal = Principal(
            kind="user", company_id=world.acme, role="admin", user_id=as_user[who],
            email="x@example.com",
        )
        return await call_next(request)

    return app


@pytest.fixture
async def client(world):
    app = _app(world, {"admin": world.admin.id, "admin2": world.admin2.id})
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                 base_url="http://test") as c:
        yield c


def url(world, memory, path):
    return f"/api/v1/companies/{world.acme}/memory/{memory.id}/{path}"


async def test_identical_concurrent_attach_has_one_effect(world, client):
    m = await world.memory("active")
    headers = {"x-test-user": "admin", "Idempotency-Key": "same-key-12345"}
    body = {"evidence_kind": "human_attestation", "reason_code": "reviewed_by_admin"}
    rs = await asyncio.gather(*(
        client.post(url(world, m, "evidence"), json=body, headers=headers)
        for _ in range(RACERS)
    ))
    assert {r.status_code for r in rs} == {201}
    assert len({r.json()["evidence_id"] for r in rs}) == 1
    assert sum(r.headers.get("idempotency-replayed") != "true" for r in rs) == 1
    assert len(await world.one(MemoryEvidence, memory_id=m.id)) == 1
    assert len(await world.one(MemoryOperation, memory_id=m.id)) == 1
    assert len(await world.audits("memory.evidence_attached")) == 1


async def test_same_key_with_conflicting_payloads_has_one_winner(world, client):
    m = await world.memory("active")
    headers = {"x-test-user": "admin", "Idempotency-Key": "clash-key-12345"}
    bodies = [{"evidence_kind": "human_attestation", "reason_code": r}
              for r in ("reviewed_by_admin", "independently_verified_by_admin")] * 3
    rs = await asyncio.gather(*(
        client.post(url(world, m, "evidence"), json=b, headers=headers) for b in bodies
    ))
    winners = [r for r in rs if r.status_code == 201 and "idempotency-replayed" not in r.headers]
    assert len(winners) == 1
    for r in rs:
        if r in winners:
            continue
        if r.status_code == 201:  # an identical retry of the winner's body
            assert r.headers["idempotency-replayed"] == "true"
            assert r.json() == winners[0].json()
        else:
            assert r.status_code == 409
            assert r.json()["detail"]["code"] == "MEMORY_IDEMPOTENCY_CONFLICT"
    assert len(await world.one(MemoryEvidence, memory_id=m.id)) == 1


async def test_concurrent_identical_accept_has_one_effect(world, client):
    m = await world.memory("candidate")
    headers = {"x-test-user": "admin", "Idempotency-Key": "accept-key-12345"}
    rs = await asyncio.gather(*(
        client.post(url(world, m, "accept"), headers=headers) for _ in range(RACERS)
    ))
    assert {r.status_code for r in rs} == {200}
    assert len({str(r.json()) for r in rs}) == 1
    assert len(await world.audits("memory.accepted")) == 1
    assert (await world.one(MemoryRecord, id=m.id))[0].status == "active"


# --- races between transitions -------------------------------------------------------------


async def _run(world, fn, *args, **kw):
    async with tenant_session(world.acme) as db:
        try:
            result = await fn(db, world.ctx, *args, **kw)
            await db.commit()
            return result
        except MemoryOpError as exc:
            await db.rollback()
            return exc.code


async def test_accept_against_reject_has_one_winner(world):
    m = await world.memory("candidate")
    got = await asyncio.gather(
        _run(world, accept_candidate, m.id), _run(world, reject_memory, m.id)
    )
    final = (await world.one(MemoryRecord, id=m.id))[0]
    assert sum(isinstance(g, MemoryRecord) for g in got) == 1
    assert [g for g in got if isinstance(g, str)] == ["MEMORY_INVALID_TRANSITION"]
    assert final.status in ("active", "rejected")
    expected = {"active": "memory.accepted", "rejected": "memory.rejected"}[final.status]
    assert len(await world.audits(expected)) == 1
    both = [*await world.audits("memory.accepted"), *await world.audits("memory.rejected")]
    assert len(both) == 1


async def test_accept_against_supersede_has_one_consistent_outcome(world):
    m = await world.memory("candidate")
    new = MemoryInput(scope="company", content="replacement")
    got = await asyncio.gather(
        _run(world, accept_candidate, m.id),
        _run(world, supersede_memory, m.id, new, Origin.API),
    )
    final = (await world.one(MemoryRecord, id=m.id))[0]
    successors = [r for r in await world.one(MemoryRecord, company_id=world.acme)
                  if r.supersedes_id == m.id]
    if final.status == "superseded":  # supersede won, or ran after accept
        assert len(successors) == 1
        assert sum(isinstance(g, str) for g in got) <= 1
    else:  # accept won and supersede then lost: no orphan successor
        assert final.status == "active" and successors == []
        assert got[0].status == "active" and isinstance(got[1], str)
    assert not (final.status == "candidate")


async def test_assert_against_assert_has_one_winner(world):
    m = await world.memory("active")
    e = await attach_attestation(world, m)
    got = await asyncio.gather(*(_run(world, assert_trust, m.id, e,
                                      idempotency_key=f"assert-{i}") for i in range(RACERS)))
    assert sum(isinstance(g, MemoryRecord) for g in got) == 1
    assert {g for g in got if isinstance(g, str)} == {"MEMORY_INVALID_TRANSITION"}
    assert (await world.one(MemoryRecord, id=m.id))[0].trust_state == "asserted"
    assert len(await world.audits("memory.trust_asserted")) == 1


@pytest.mark.parametrize("closer", ("archive", "supersede"))
async def test_verify_against_close_agrees_with_its_audit(world, closer):
    m = await world.memory("active")
    e = await promoted(world, m)
    close = (_run(world, archive_memory, m.id) if closer == "archive" else
             _run(world, supersede_memory, m.id, MemoryInput(scope="company", content="new"),
                  Origin.API))
    verified, closed = await asyncio.gather(_run(world, verify_trust, m.id, e), close)
    final = (await world.one(MemoryRecord, id=m.id))[0]
    assert final.status == ("archived" if closer == "archive" else "superseded")
    audit = await world.audits("memory.trust_verified")
    if isinstance(verified, MemoryRecord):
        assert final.trust_state == "verified" and len(audit) == 1
    else:  # the close won: verification is refused and leaves nothing behind
        assert verified == "MEMORY_INVALID_TRANSITION"
        assert final.trust_state == "asserted" and audit == []
    assert not isinstance(closed, str)  # closing a verified or asserted memory never fails


# --- stale evidence, atomicity, rollback ---------------------------------------------------


async def test_a_stale_transaction_cannot_verify_with_invalidated_evidence(world):
    m = await world.memory("active")
    await promoted(world, m)
    attempt = await world.attempt(passed=True)
    async with tenant_session(world.acme) as db:
        out = await ev.attach_evidence(
            db, world.ctx, m.id, evidence_kind="task_attempt", source_id=str(attempt.id),
            reason_code=None, idempotency_key="attempt-evidence",
        )
        await db.commit()
    evidence_id = uuid.UUID(out["evidence_id"])
    assert out["grade"] == "verify"

    stale = tenant_session(world.acme)
    db = await stale.__aenter__()
    try:
        # The verifier is already inside its transaction when the source stops qualifying.
        await db.execute(sa.select(MemoryRecord).where(MemoryRecord.id == m.id))
        async with AsyncSession(world.engine) as other:
            await other.execute(
                sa.update(TaskAttempt).where(TaskAttempt.id == attempt.id)
                .values(verification={**PASSED, "passed": False})
            )
            await other.commit()
        with pytest.raises(MemoryOpError) as err:
            await verify_trust(db, world.ctx, m.id, evidence_id)
        assert err.value.code == "MEMORY_EVIDENCE_STALE"
        await db.rollback()
    finally:
        await stale.__aexit__(None, None, None)
    assert (await world.one(MemoryRecord, id=m.id))[0].trust_state == "asserted"
    assert await world.audits("memory.trust_verified") == []


async def test_verification_holds_the_source_lock_until_it_commits(world):
    m = await world.memory("active")
    await promoted(world, m)
    attempt = await world.attempt(passed=True)
    async with tenant_session(world.acme) as db:
        out = await ev.attach_evidence(
            db, world.ctx, m.id, evidence_kind="task_attempt", source_id=str(attempt.id),
            reason_code=None, idempotency_key="lock-evidence",
        )
        await db.commit()
    async with tenant_session(world.acme) as db:
        await verify_trust(db, world.ctx, m.id, uuid.UUID(out["evidence_id"]))
        async with AsyncSession(world.engine) as other:  # a competing writer cannot slip in
            with pytest.raises(DBAPIError, match="could not obtain lock"):
                await other.execute(
                    sa.select(TaskAttempt.id).where(TaskAttempt.id == attempt.id)
                    .with_for_update(nowait=True)
                )
        await db.commit()
    assert (await world.one(MemoryRecord, id=m.id))[0].trust_state == "verified"


async def test_transition_and_audit_commit_together_and_roll_back_together(world):
    m = await world.memory("candidate")
    async with tenant_session(world.acme) as db:
        await accept_candidate(db, world.ctx, m.id)
        await db.rollback()
    assert (await world.one(MemoryRecord, id=m.id))[0].status == "candidate"
    assert await world.audits("memory.accepted") == []

    async with tenant_session(world.acme) as db:
        await accept_candidate(db, world.ctx, m.id)
        await db.commit()
    assert (await world.one(MemoryRecord, id=m.id))[0].status == "active"
    [audit] = await world.audits("memory.accepted")
    assert audit.resource_id == str(m.id) and "c-" not in str(audit.details)


async def test_a_failed_request_leaves_no_evidence_ledger_or_audit_residue(world):
    m = await world.memory("active")
    with pytest.raises(RuntimeError):
        async with tenant_session(world.acme) as db:

            async def effect():
                await ev.attach_evidence(
                    db, world.ctx, m.id, evidence_kind="human_attestation", source_id=None,
                    reason_code="reviewed_by_admin", idempotency_key="boom-key-12345",
                )
                raise RuntimeError("after the effect, before the commit")

            await ev.run_once(
                db, world.ctx, key="boom-key-12345", operation="attach_evidence",
                memory_id=m.id, digest="d" * 64, effect=effect,
            )
    assert await world.one(MemoryEvidence, company_id=world.acme) == []
    assert await world.one(MemoryOperation, company_id=world.acme) == []
    assert await world.audits("memory.evidence_attached") == []


async def test_cross_tenant_forged_ids_are_refused_and_leave_nothing(world, client):
    theirs = await world.memory("active", company=world.other)
    foreign_attempt = await world.attempt(company=world.other)
    mine = await world.memory("active")
    h = {"x-test-user": "admin"}
    attest = {"evidence_kind": "human_attestation", "reason_code": "reviewed_by_admin"}
    r = await client.post(url(world, theirs, "evidence"), json=attest,
                          headers={**h, "Idempotency-Key": "forge-1-12345"})
    gone = await client.post(url(world, MemoryRecord(id=uuid.uuid4()), "evidence"), json=attest,
                             headers={**h, "Idempotency-Key": "forge-2-12345"})
    assert (r.status_code, r.json()) == (gone.status_code, gone.json()) and r.status_code == 404
    forged = await client.post(
        url(world, mine, "evidence"), headers={**h, "Idempotency-Key": "forge-3-12345"},
        json={"evidence_kind": "task_attempt", "source_id": str(foreign_attempt.id)},
    )
    assert forged.status_code == 404
    assert forged.json()["detail"]["code"] == "MEMORY_EVIDENCE_SOURCE_NOT_FOUND"
    assert await world.one(MemoryEvidence, company_id=world.acme) == []
    assert await world.one(MemoryOperation, company_id=world.acme) == []


# --- retention: what deletion and downgrade do to evidence ---------------------------------

FK_VIOLATION = "23503"
EVIDENCE_FUNCTIONS = ("memory_evidence_append_only", "memory_evidence_same_company")
CATALOG = {
    "tables": "SELECT tablename FROM pg_tables WHERE schemaname = 'public'",
    "indexes": "SELECT tablename, indexname FROM pg_indexes WHERE schemaname = 'public'",
    "constraints": (
        "SELECT conrelid::regclass::text, conname FROM pg_constraint "
        "WHERE connamespace = 'public'::regnamespace"
    ),
    "triggers": "SELECT tgrelid::regclass::text, tgname FROM pg_trigger WHERE NOT tgisinternal",
    "policies": "SELECT tablename, policyname FROM pg_policies WHERE schemaname = 'public'",
    "functions": "SELECT proname FROM pg_proc WHERE pronamespace = 'public'::regnamespace",
    "rls": (
        "SELECT relname, relrowsecurity, relforcerowsecurity FROM pg_class "
        "WHERE relnamespace = 'public'::regnamespace AND relkind = 'r'"
    ),
}


def refusal(exc: DBAPIError) -> tuple[str, str | None]:
    """The stable (SQLSTATE, constraint) of a refused statement; message text is not matched."""
    return exc.orig.sqlstate, getattr(exc.orig.__cause__, "constraint_name", None)


async def rows(engine, sql, **params):
    async with engine.connect() as conn:
        return [tuple(r) for r in (await conn.execute(sa.text(sql), params))]


async def evidence_row(engine, evidence_id):
    """The row with its physical identity (xmin, ctid): a rewrite would change it."""
    return await rows(
        engine, "SELECT xmin::text, ctid::text, * FROM memory_evidence WHERE id = :i",
        i=evidence_id,
    )


async def residue(w):
    """Evidence, ledger and audit rows of the main company."""
    return [
        (await rows(w.engine, f"SELECT count(*) FROM {t} WHERE company_id = :c", c=w.acme))[0][0]
        for t in ("memory_evidence", "memory_operations", "audit_log")
    ]


def _session(w, as_role):
    return AsyncSession(w.engine) if as_role == "owner" else tenant_session(w.acme)


@pytest.mark.parametrize("as_role", ("owner", "tenant"))
@pytest.mark.parametrize(
    "statement",
    (
        "UPDATE memory_evidence SET grade = 'verify' WHERE id = :e",
        "UPDATE memory_evidence SET created_by = 'user:forged' WHERE id = :e",
        "DELETE FROM memory_evidence WHERE id = :e",
    ),
)
async def test_direct_update_and_delete_of_evidence_are_refused_and_change_nothing(
    world, app_role, statement, as_role
):
    m = await world.memory("active")
    e = await attach_attestation(world, m)
    before, base = await evidence_row(world.engine, e), await residue(world)
    async with _session(world, as_role) as db:
        # Work done earlier in the same transaction goes with the refused statement.
        await ev.attach_evidence(
            db, world.ctx, m.id, evidence_kind="human_attestation", source_id=None,
            reason_code="reviewed_by_admin", idempotency_key=f"k-{uuid.uuid4()}",
        )
        with pytest.raises(DBAPIError, match="append-only"):
            await db.execute(sa.text(statement), {"e": e})
        await db.rollback()
    assert await evidence_row(world.engine, e) == before
    assert await residue(world) == base


@pytest.mark.parametrize("as_role", ("owner", "tenant"))
async def test_deleting_a_memory_with_evidence_is_refused_by_the_restrict_foreign_key(
    world, app_role, as_role
):
    m = await world.memory("active")
    e = await attach_attestation(world, m)
    memory_before = await rows(world.engine, "SELECT * FROM memory_records WHERE id = :i", i=m.id)
    evidence_before = await evidence_row(world.engine, e)
    async with _session(world, as_role) as db:
        with pytest.raises(DBAPIError) as refused:
            await db.execute(sa.text("DELETE FROM memory_records WHERE id = :i"), {"i": m.id})
        assert refusal(refused.value) == (FK_VIOLATION, "memory_evidence_memory_id_fkey")
        await db.rollback()
    assert await rows(world.engine, "SELECT * FROM memory_records WHERE id = :i", i=m.id) == (
        memory_before
    )
    assert await evidence_row(world.engine, e) == evidence_before


async def test_every_evidence_foreign_key_is_restrict(world):
    keys = await rows(
        world.engine,
        "SELECT conrelid::regclass::text, conname, confrelid::regclass::text, confdeltype::text "
        "FROM pg_constraint WHERE contype = 'f' AND conrelid::regclass::text = ANY(:t) "
        "ORDER BY 1, 2", t=list(TABLES),
    )
    assert keys == [
        ("memory_evidence", "memory_evidence_company_id_fkey", "companies", "r"),
        ("memory_evidence", "memory_evidence_memory_id_fkey", "memory_records", "r"),
        ("memory_operations", "memory_operations_company_id_fkey", "companies", "r"),
        ("memory_operations", "memory_operations_memory_id_fkey", "memory_records", "r"),
    ]


async def _delete_company(w, company, as_role):
    """Try to delete ``company``; return what the database refused with."""
    async with _session(w, as_role) as db:
        with pytest.raises(DBAPIError) as refused:
            await db.execute(sa.text("DELETE FROM companies WHERE id = :c"), {"c": company})
        await db.rollback()
    return refusal(refused.value)


async def _company_rows(w, company):
    """Every row of ``company`` in the three tables a delete would have to remove."""
    return {
        t: await rows(w.engine, f"SELECT * FROM {t} WHERE {key} = :c ORDER BY id", c=company)
        for t, key in (
            ("companies", "id"), ("memory_records", "company_id"), ("memory_evidence", "company_id")
        )
    }


async def _companys_foreign_keys(w):
    """Every foreign key into ``companies``, as ``{name: (table, column)}``."""
    return {
        r[0]: (r[1], r[2]) for r in await rows(
            w.engine,
            "SELECT c.conname, c.conrelid::regclass::text, a.attname FROM pg_constraint c "
            "JOIN pg_attribute a ON a.attrelid = c.conrelid AND a.attnum = c.conkey[1] "
            "WHERE c.contype = 'f' AND c.confrelid = 'companies'::regclass",
        )
    }


async def _foreign_keys_with_rows(w, company):
    """The foreign keys into ``companies`` that actually have a row for ``company``."""
    return {
        name for name, (table, column) in (await _companys_foreign_keys(w)).items()
        if await rows(w.engine, f"SELECT 1 FROM {table} WHERE {column} = :c LIMIT 1", c=company)
    }


@pytest.mark.parametrize("as_role", ("owner", "tenant"))
async def test_deleting_a_company_with_a_memory_and_evidence_is_refused(world, app_role, as_role):
    """A company holding only a memory and its evidence cannot be deleted; nothing is lost.

    ``blocker`` is whichever foreign key PostgreSQL fires first, and it need not be the
    evidence one: the memory row, and the audit rows that creating the admin and the evidence
    write, reference the company too. Observed on a freshly migrated database: it is
    ``audit_log_company_id_fkey``. The test asserts only that the blocker is a foreign key
    with a row for this company; the evidence foreign keys are RESTRICT in their own right
    (``test_every_evidence_foreign_key_is_restrict``).
    """
    company = uuid.uuid4()
    async with AsyncSession(world.engine) as db:
        db.add(Company(id=company, name="Retained"))
        await db.flush()
        admin = await create_user(
            db, email=f"r-{company}@example.com", password="x" * 14, company_id=company,
            role="admin",
        )
        admin_id = admin.id
        await db.commit()
    m = await world.memory("active", company=company)
    async with tenant_session(company) as db:
        out = await ev.attach_evidence(
            db, MemoryContext(company, f"user:{admin_id}"), m.id,
            evidence_kind="human_attestation", source_id=None,
            reason_code="reviewed_by_admin", idempotency_key=f"k-{uuid.uuid4()}",
        )
        await db.commit()
    before = await _company_rows(world, company)
    assert len(before["memory_evidence"]) == 1

    sqlstate, blocker = await _delete_company(world, company, as_role)

    assert sqlstate == FK_VIOLATION
    holding = await _foreign_keys_with_rows(world, company)
    assert {"memory_records_company_id_fkey", "memory_evidence_company_id_fkey"} <= holding
    assert blocker in holding, (blocker, holding)
    assert await _company_rows(world, company) == before
    assert out["evidence_id"]


async def test_deleting_the_main_company_is_refused_whatever_else_depends_on_it(world, app_role):
    """The seeded company has agents, users and audit rows besides its memory and evidence."""
    m = await world.memory("active")
    await attach_attestation(world, m)
    sqlstate, blocker = await _delete_company(world, world.acme, "owner")
    assert sqlstate == FK_VIOLATION
    assert (blocker is not None) and blocker.endswith("_fkey"), blocker
    assert len(await world.one(MemoryEvidence, memory_id=m.id)) == 1
    assert len(await rows(world.engine, "SELECT 1 FROM companies WHERE id = :c", c=world.acme)) == 1


async def test_other_and_unbound_sessions_cannot_see_update_or_delete_evidence(world, app_role):
    m = await world.memory("active")
    e = await attach_attestation(world, m)
    before = await evidence_row(world.engine, e)
    memory_before = await rows(world.engine, "SELECT * FROM memory_records WHERE id = :i", i=m.id)
    for session, unbound in ((tenant_session(world.other), False), (app_role(), True)):
        async with session as db:
            if unbound:  # no tenant bound: the policy hides every row
                everything = await db.execute(sa.text("SELECT count(*) FROM memory_evidence"))
                assert everything.scalar_one() == 0
            mine = await db.execute(
                sa.text("SELECT count(*) FROM memory_evidence WHERE id = :e"), {"e": e}
            )
            assert mine.scalar_one() == 0
            for statement in (
                "UPDATE memory_evidence SET grade = 'verify' WHERE id = :e",
                "DELETE FROM memory_evidence WHERE id = :e",
                "DELETE FROM memory_records WHERE id = :m",
            ):
                result = await db.execute(sa.text(statement), {"e": e, "m": m.id})
                assert result.rowcount == 0, statement
            await db.rollback()
    assert await evidence_row(world.engine, e) == before
    assert await rows(world.engine, "SELECT * FROM memory_records WHERE id = :i", i=m.id) == (
        memory_before
    )
    flags = await rows(
        world.engine,
        "SELECT relname, relrowsecurity, relforcerowsecurity FROM pg_class "
        "WHERE relname = ANY(:t) ORDER BY 1", t=list(TABLES),
    )
    assert flags == [("memory_evidence", True, True), ("memory_operations", True, True)]


async def _catalog(engine):
    return {key: set(await rows(engine, sql)) for key, sql in CATALOG.items()}


def _belongs_to_evidence(row) -> bool:
    return row[0] in TABLES or row[0] in EVIDENCE_FUNCTIONS


async def test_downgrading_one_revision_drops_only_the_evidence_tables_and_their_history(
    world, migrated_postgres_url
):
    """Evidence is not exported or kept: downgrading destroys it, with only M3-2's objects."""
    m = await world.memory("active")
    await attach_attestation(world, m)
    async with tenant_session(world.acme) as db:
        await ev.run_once(
            db, world.ctx, key="downgrade-key-12345", operation="attach_evidence",
            memory_id=m.id, digest="d" * 64,
            effect=lambda: ev.attach_evidence(
                db, world.ctx, m.id, evidence_kind="human_attestation", source_id=None,
                reason_code="reviewed_by_admin", idempotency_key="downgrade-key-12345",
            ),
        )
        await db.commit()
    assert await rows(world.engine, "SELECT count(*) FROM memory_evidence WHERE company_id = :c",
                      c=world.acme) == [(2,)]
    assert await rows(world.engine, "SELECT count(*) FROM memory_operations WHERE company_id = :c",
                      c=world.acme) == [(1,)]

    kept = {t: await rows(world.engine, f"SELECT * FROM {t} ORDER BY id")
            for t in ("companies", "memory_records", "audit_log")}
    before = await _catalog(world.engine)
    cfg = alembic.config.Config("alembic.ini")
    cfg.set_main_option("sqlalchemy.url", migrated_postgres_url)
    version = "SELECT version_num FROM alembic_version"
    assert await rows(world.engine, version) == [("b4d9f2a61c73",)]

    await asyncio.to_thread(alembic.command.downgrade, cfg, "-1")
    try:
        assert await rows(world.engine, version) == [("e7a1c2d3f408",)]
        after = await _catalog(world.engine)
        for key in CATALOG:
            assert not after[key] - before[key], key  # nothing new appears
            assert before[key] - after[key] == {
                r for r in before[key] if _belongs_to_evidence(r)
            }, key
        removed = {key: before[key] - after[key] for key in CATALOG}
        assert len(removed["tables"]) == 2
        assert len(removed["policies"]) == 2
        assert len(removed["triggers"]) == 4
        assert len(removed["functions"]) == 2
        assert {n for _, n in removed["indexes"]} >= {
            "ix_memory_evidence_company_memory",
            "ix_memory_evidence_company_source",
            "ix_memory_operations_company_memory",
            "uq_memory_evidence_source",
            "uq_memory_evidence_idempotency",
            "uq_memory_operations_key",
        }
        assert {n for _, n in removed["constraints"]} >= {
            "ck_memory_evidence_kind",
            "ck_memory_evidence_source_type",
            "ck_memory_evidence_grade",
            "ck_memory_operations_operation",
            "memory_evidence_memory_id_fkey",
            "memory_operations_company_id_fkey",
        }
        for t, snapshot in kept.items():  # everything that pre-dates M3-2 is untouched
            assert await rows(world.engine, f"SELECT * FROM {t} ORDER BY id") == snapshot, t
        gone = await rows(
            world.engine,
            "SELECT to_regclass('memory_evidence') IS NULL, "
            "to_regclass('memory_operations') IS NULL",
        )
        assert gone == [(True, True)]  # the evidence history went with its tables
    finally:
        await asyncio.to_thread(alembic.command.upgrade, cfg, "head")

    # This database was migrated as the superuser, so the recreated tables get no privileges
    # for the fixture's application role. That is the fixture's setup, which grants once when it
    # creates the role, not the deployment path: there the migrator role's default privileges
    # grant them (see ``test_the_provisioned_application_role_reads_and_writes_evidence...``).
    async with world.engine.begin() as conn:
        await conn.execute(sa.text("GRANT ALL ON ALL TABLES IN SCHEMA public TO nexus_app"))
    assert await rows(world.engine, version) == [("b4d9f2a61c73",)]
    assert await _catalog(world.engine) == before  # triggers, policies, FORCE RLS all return
    for t in TABLES:  # the upgrade does not bring the history back
        assert await rows(world.engine, f"SELECT count(*) FROM {t}") == [(0,)]
    for t, snapshot in kept.items():
        assert await rows(world.engine, f"SELECT * FROM {t} ORDER BY id") == snapshot, t
    fresh = await attach_attestation(world, m)  # and the rebuilt tables are append-only again
    async with AsyncSession(world.engine) as db:
        with pytest.raises(DBAPIError, match="append-only"):
            await db.execute(
                sa.text("UPDATE memory_evidence SET grade = 'none' WHERE id = :e"), {"e": fresh}
            )

# --- grant path: the application role through the real provisioning and migration path ---------

INIT_ROLES = Path(__file__).parents[1] / "docker" / "postgres-init" / "01-init-roles.sql"
PROVISIONED_ROLES = re.compile(r"CREATE ROLE (\w+) LOGIN PASSWORD '(\w+)'")


@pytest.fixture
async def provisioned(migrated_postgres_url, monkeypatch):
    """A throwaway database set up the way ``docker-compose.yml`` does it.

    The unmodified ``docker/postgres-init/01-init-roles.sql`` creates the roles and the
    default privileges, and ``alembic upgrade head`` runs as its migrator role, as the
    ``migrate`` service does. Only the role names get a random suffix, because roles are
    shared by the whole server and the shared test database already owns ``nexus_app``.
    Nothing here grants anything by hand.
    """
    suffix = uuid.uuid4().hex[:8]
    base = make_url(migrated_postgres_url)
    database = f"grantpath_{suffix}"
    script = re.sub(
        r"\bnexus_(migrator|app|system)\b", rf"nexus_\1_{suffix}",
        INIT_ROLES.read_text(encoding="utf-8"),
    )
    passwords = dict(PROVISIONED_ROLES.findall(script))
    migrator, app, system = (f"nexus_{r}_{suffix}" for r in ("migrator", "app", "system"))
    uncommented = "\n".join(
        line for line in script.splitlines() if not line.lstrip().startswith("--")
    )
    statements = [part.strip() for part in uncommented.split(";") if part.strip()]

    def url(role=None):
        u = base.set(database=database)
        return u.set(username=role, password=passwords[role]) if role else u

    server = create_async_engine(base, isolation_level="AUTOCOMMIT")
    async with server.connect() as conn:
        await conn.execute(sa.text(f'CREATE DATABASE "{database}"'))
    owner = create_async_engine(url(), isolation_level="AUTOCOMMIT")
    engines = [owner]
    try:
        async with owner.connect() as conn:
            for statement in statements:
                await conn.execute(sa.text(statement))
        cfg = alembic.config.Config("alembic.ini")
        cfg.set_main_option("sqlalchemy.url", url(migrator).render_as_string(hide_password=False))
        await asyncio.to_thread(alembic.command.upgrade, cfg, "head")
        engine = create_async_engine(url(app))
        engines.append(engine)
        monkeypatch.setattr(
            "nexus.config.settings.database_url", url(app).render_as_string(hide_password=False)
        )
        monkeypatch.setattr(
            "nexus.database.async_session_factory",
            async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False),
        )
        yield SimpleNamespace(
            cfg=cfg, owner=owner, app=app, migrator=migrator, system=system, engine=engine
        )
    finally:
        for e in engines:
            await e.dispose()
        async with server.connect() as conn:
            await conn.execute(sa.text(f'DROP DATABASE IF EXISTS "{database}" WITH (FORCE)'))
            for role in (app, system, migrator):
                await conn.execute(sa.text(f'DROP ROLE IF EXISTS "{role}"'))
        await server.dispose()


async def _grants(p, table):
    return {
        r[0] for r in await rows(
            p.owner,
            "SELECT privilege_type FROM information_schema.role_table_grants "
            "WHERE grantee = :a AND table_name = :t",
            a=p.app, t=table,
        )
    }


async def _application_role_works_and_stays_confined(p, label):
    """What ``nexus_app`` may and may not do with evidence, once the schema is provisioned."""
    acme, other = uuid.uuid4(), uuid.uuid4()
    async with AsyncSession(p.owner, expire_on_commit=False) as db:
        db.add_all([Company(id=acme, name="Acme"), Company(id=other, name="Other")])
        await db.flush()
        admin = await create_user(
            db, email=f"g-{acme}@example.com", password="x" * 14, company_id=acme, role="admin"
        )
        memory = MemoryRecord(
            company_id=acme, scope="company", content=f"c-{uuid.uuid4()}", status="active"
        )
        db.add(memory)
        await db.commit()
    ctx = MemoryContext(acme, f"user:{admin.id}")
    key = f"grant-path-{label}-{uuid.uuid4()}"

    # The bound tenant writes canonical evidence and its ledger row, and reads them back.
    async with tenant_session(acme) as db:
        await ev.run_once(
            db, ctx, key=key, operation="attach_evidence", memory_id=memory.id, digest="d" * 64,
            effect=lambda: ev.attach_evidence(
                db, ctx, memory.id, evidence_kind="human_attestation", source_id=None,
                reason_code="reviewed_by_admin", idempotency_key=key,
            ),
        )
        await db.commit()
    async with tenant_session(acme) as db:
        found = (await db.execute(sa.select(MemoryEvidence.id))).scalars().all()
        ledger = (await db.execute(sa.select(MemoryOperation.idempotency_key))).scalars().all()
    assert len(found) == 1 and ledger == [key], label
    evidence_id = found[0]
    before = await evidence_row(p.owner, evidence_id)

    # Another tenant sees nothing and cannot write into this one.
    async with tenant_session(other) as db:
        for table in TABLES:
            assert (await db.execute(sa.text(f"SELECT count(*) FROM {table}"))).scalar_one() == 0
    insert = sa.text(
        "INSERT INTO memory_evidence (id, company_id, memory_id, evidence_kind, source_type,"
        " source_id, reason_code, grade, source_digest, policy_version, idempotency_key,"
        " created_by, created_at) VALUES (:id, :c, :m, 'human_attestation', 'user', 'u',"
        " 'reviewed_by_admin', 'assert', 'd', 'memory-evidence-v1', :k, 'user:u', now())"
    )
    params = {"c": acme, "m": memory.id}
    # A forged row is refused by the row policy or by the same-company trigger (which cannot see
    # a memory outside the bound tenant), never by a missing privilege, which would say
    # "permission denied".
    refused = "row-level security|memory of its own company"
    async with tenant_session(other) as db:
        with pytest.raises(DBAPIError, match=refused) as forged:
            await db.execute(insert, {**params, "id": uuid.uuid4(), "k": "forged-by-other"})
    assert "permission denied" not in str(forged.value)

    # With no tenant bound the role reads nothing and cannot insert.
    async with AsyncSession(p.engine) as db:
        for table in TABLES:
            assert (await db.execute(sa.text(f"SELECT count(*) FROM {table}"))).scalar_one() == 0
        with pytest.raises(DBAPIError, match=refused) as forged:
            await db.execute(insert, {**params, "id": uuid.uuid4(), "k": "forged-unbound"})
    assert "permission denied" not in str(forged.value)

    # The bound tenant still cannot change or remove what it wrote: the trigger fires, which
    # also shows the role does hold the UPDATE and DELETE privileges.
    for statement in (
        "UPDATE memory_evidence SET grade = 'verify' WHERE id = :e",
        "DELETE FROM memory_evidence WHERE id = :e",
    ):
        async with tenant_session(acme) as db:
            with pytest.raises(DBAPIError, match="append-only"):
                await db.execute(sa.text(statement), {"e": evidence_id})
    assert await evidence_row(p.owner, evidence_id) == before

    # The role is neither privileged nor an owner and is bound by FORCE RLS. It holds exactly
    # the privileges that every other tenant table (memory_records) gets from the defaults.
    attrs = await rows(
        p.owner,
        "SELECT rolbypassrls, rolsuper, rolcreaterole, rolcreatedb, "
        "pg_has_role(rolname, :m, 'MEMBER') FROM pg_roles WHERE rolname = :a",
        a=p.app, m=p.migrator,
    )
    assert attrs == [(False, False, False, False, False)]
    owners = await rows(
        p.owner,
        "SELECT relname, relowner::regrole::text, relforcerowsecurity FROM pg_class "
        "WHERE relname IN ('memory_evidence', 'memory_operations') ORDER BY relname",
    )
    assert owners == [(t, p.migrator, True) for t in TABLES]
    canonical = await _grants(p, "memory_records")
    assert canonical == {"SELECT", "INSERT", "UPDATE", "DELETE"}
    for table in TABLES:
        assert await _grants(p, table) == canonical, (label, table)


async def test_the_provisioned_application_role_reads_and_writes_evidence_and_stays_confined(
    provisioned,
):
    """Fresh deployment, then an upgrade from the previous revision, with real grants.

    The second pass is downgrade one revision then upgrade, which is what upgrading from the
    previous release does to these tables. The recreated tables get their privileges from
    ``ALTER DEFAULT PRIVILEGES FOR ROLE nexus_migrator`` in the provisioning script, so
    nothing is granted by hand between the passes.
    """
    p = provisioned
    await _application_role_works_and_stays_confined(p, "fresh")
    await asyncio.to_thread(alembic.command.downgrade, p.cfg, "-1")
    assert await rows(p.owner, "SELECT to_regclass('memory_evidence') IS NULL") == [(True,)]
    await asyncio.to_thread(alembic.command.upgrade, p.cfg, "head")
    await _application_role_works_and_stays_confined(p, "upgraded")
