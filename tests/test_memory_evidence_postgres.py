"""Memory evidence on real PostgreSQL: forced RLS, append-only triggers, races, atomicity.

Migration ``b4d9f2a61c73``. Runs against a disposable PostgreSQL (testcontainers, or
``TEST_DATABASE_URL``); skipped when neither is available. Races use two real sessions and
``asyncio.gather``; there are no sleeps and no polling. Each race asserts what must hold
whichever caller wins: one winner, a stable refusal for the other, and state, evidence and
audit that agree.
"""
# ruff: noqa: F811 -- pytest fixtures imported from test_postgres_integration

import asyncio
import uuid

import alembic.command
import alembic.config
import httpx
import pytest
import sqlalchemy as sa
from fastapi import FastAPI, Request
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

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
