"""Memory evidence, candidate acceptance and governed trust promotion (M3-2), over HTTP.

Real sessions go through the real cookie resolver (active user, live membership, role read
from the membership row on every request); run principals are injected the way the
middleware would build them. Every mutation is checked for who may call it, what it
refuses, what a retry returns and what the audit trail holds (ids and states, never
content).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import httpx
import pytest
from fastapi import FastAPI, Request
from sqlalchemy import select

from nexus.api.routes import memory_evidence as routes
from nexus.auth.middleware import AuthenticationMiddleware
from nexus.auth.principal import Principal
from nexus.auth.sessions import create_session
from nexus.auth.users import create_user
from nexus.models.chat_turn import ChatTurn
from nexus.models.governance import AuditLog
from nexus.models.memory import MemoryRecord
from nexus.models.memory_evidence import MemoryEvidence, MemoryOperation
from nexus.models.task import Task
from nexus.models.task_attempt import TaskAttempt
from nexus.models.tool_invocation import ToolInvocation
from nexus.models.user_profile import UserProfile
from tests.test_tool_access import factory, t  # noqa: F401 -- fixtures

SECRET = "never-in-an-audit-row"
PASSED = {"passed": True, "outcome": "completed", "checks": [{"passed": True}]}


def key() -> dict[str, str]:
    return {"Idempotency-Key": f"test-{uuid.uuid4()}"}


def _now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


@pytest.fixture
async def w(factory, t):  # noqa: F811
    ids: dict[str, uuid.UUID] = {}
    tokens: dict[str, str] = {}
    async with factory() as db:
        for name, company, role in (
            ("admin", t["acme"], "admin"), ("viewer", t["acme"], "viewer"),
            ("gone", t["acme"], "admin"), ("second", t["acme"], "admin"),
            ("outsider", t["other"], "admin"),
        ):
            user = await create_user(db, email=f"{name}@example.com", password="x" * 14,
                                     company_id=company, role=role)
            ids[name] = user.id
            tokens[name], _ = await create_session(db, user_id=user.id, company_id=company)
        await db.commit()

    agent = uuid.uuid4()
    mem = {
        name: MemoryRecord(company_id=t["acme"], agent_id=agent, scope="l2_agent",
                           content=f"{SECRET} {name}", status=status)
        for name, status in (
            ("candidate", "candidate"), ("active", "active"), ("active2", "active"),
            ("archived", "archived"),
        )
    }
    foreign = MemoryRecord(company_id=t["other"], agent_id=uuid.uuid4(), scope="l2_agent",
                           content="theirs", status="active")
    async with factory() as db:
        task = Task(company_id=t["acme"], title="work", status="in_progress")
        ftask = Task(company_id=t["other"], title="theirs", status="in_progress")
        db.add_all([*mem.values(), foreign, task, ftask])
        await db.flush()

        def attempt(company, task_id, agent_id, n, **kw):
            return TaskAttempt(company_id=company, task_id=task_id, agent_id=agent_id,
                               attempt_number=n, idempotency_key=str(uuid.uuid4()), **kw)

        src = {
            "turn": ChatTurn(company_id=t["acme"], agent_id=t["a"], session_id=t["s1"],
                             turn_seq=1, idempotency_key=str(uuid.uuid4())),
            "foreign_turn": ChatTurn(company_id=t["other"], agent_id=uuid.uuid4(),
                                     session_id=uuid.uuid4(), turn_seq=1,
                                     idempotency_key=str(uuid.uuid4())),
            "tool_ok": ToolInvocation(company_id=t["acme"], tool_name="x", status="success",
                                      approval_state="approved", authorization="allowed",
                                      completed_at=_now()),
            "tool_bad": ToolInvocation(company_id=t["acme"], tool_name="x", status="error",
                                       approval_state="approved", authorization="allowed",
                                       completed_at=_now()),
            "done": attempt(t["acme"], task.id, t["a"], 1, status="completed",
                            completion_reason="goal", verification=PASSED),
            "unverified": attempt(t["acme"], task.id, t["a"], 2, status="completed",
                                  completion_reason="goal", verification=None),
            "failed": attempt(t["acme"], task.id, t["a"], 3, status="completed",
                              completion_reason="goal",
                              verification={**PASSED, "passed": False}),
            "foreign_done": attempt(t["other"], ftask.id, uuid.uuid4(), 1, status="completed",
                                    completion_reason="goal", verification=PASSED),
        }
        db.add_all(src.values())
        await db.commit()

    run = Principal(kind="run", company_id=t["acme"], role="agent", run_id=uuid.uuid4(),
                    agent_id=agent)
    resolver = AuthenticationMiddleware(None)  # type: ignore[arg-type]
    app = FastAPI()
    app.include_router(routes.router)

    @app.middleware("http")
    async def authenticate(request: Request, call_next):
        if request.headers.get("x-test-principal") == "run":
            request.state.principal = run
        elif token := request.cookies.get("nv_session", ""):
            async with factory() as db:
                principal = await resolver._principal_from_cookie(db, token)
                await db.commit()
            if principal is not None:
                request.state.principal = principal
        return await call_next(request)

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                 base_url="http://test") as client:
        async def call(who, method, path, *, company=None, idem=True, **kw):
            client.cookies.clear()
            if who in tokens:
                client.cookies.set("nv_session", tokens[who])
            headers = {**kw.pop("headers", {}),
                       **({"x-test-principal": "run"} if who == "run" else {})}
            if method == "POST" and idem is True:
                headers = {**key(), **headers}
            return await client.request(
                method, f"/api/v1/companies/{company or t['acme']}/memory/{path}",
                headers=headers, **kw,
            )

        async def rows(model):
            async with factory() as db:
                return list((await db.execute(select(model))).scalars())

        async def audits(prefix="memory."):
            async with factory() as db:
                found = (await db.execute(select(AuditLog))).scalars()
                return [a for a in found if a.action.startswith(prefix)]

        async def deactivate(name):
            async with factory() as db:
                (await db.get(UserProfile, ids[name])).is_active = False
                await db.commit()

        async def record(row):
            async with factory() as db:
                return await db.get(type(row), row.id)

        call.mem, call.foreign, call.src, call.ids = mem, foreign, src, ids
        call.rows, call.audits, call.deactivate, call.record = rows, audits, deactivate, record
        call.factory, call.acme, call.other = factory, t["acme"], t["other"]
        yield call


async def attach(w, who, memory, **body):
    return await w(who, "POST", f"{memory.id}/evidence", json=body)


def attest(reason="reviewed_by_admin"):
    return {"evidence_kind": "human_attestation", "reason_code": reason}


async def evidence_id(w, memory, **body) -> str:
    r = await attach(w, "admin", memory, **body)
    assert r.status_code == 201, r.text
    return r.json()["evidence_id"]


# --- the happy path, and what each step does and does not change ---------------------------


async def test_accept_assert_verify_each_change_one_thing(w):
    m = w.mem["candidate"]
    r = await w("admin", "POST", f"{m.id}/accept")
    assert r.status_code == 200
    assert (r.json()["status"], r.json()["trust_state"]) == ("active", "untrusted")

    e1 = await evidence_id(w, m, **attest())
    r = await w("admin", "POST", f"{m.id}/trust/assert", json={"evidence_id": e1})
    assert (r.status_code, r.json()["status"], r.json()["trust_state"]) == (
        200, "active", "asserted")

    e2 = await evidence_id(w, m, evidence_kind="task_attempt",
                           source_id=str(w.src["done"].id))
    r = await w("admin", "POST", f"{m.id}/trust/verify", json={"evidence_id": e2})
    assert (r.status_code, r.json()["trust_state"]) == (200, "verified")

    row = await w.record(m)
    assert row.status == "active" and row.trust_state == "verified"
    assert row.content == f"{SECRET} candidate"  # content never touched
    assert [a.action for a in await w.audits()] == [
        "memory.accepted", "memory.evidence_attached", "memory.trust_asserted",
        "memory.evidence_attached", "memory.trust_verified",
    ]


async def test_a_verified_memory_can_still_be_archived(w):
    from nexus.memory.ingest import MemoryContext
    from nexus.memory.lifecycle import archive_memory

    m = w.mem["active"]
    e1 = await evidence_id(w, m, **attest("independently_verified_by_admin"))
    for step in ("assert", "verify"):
        assert (await w("admin", "POST", f"{m.id}/trust/{step}",
                        json={"evidence_id": e1})).status_code == 200
    async with w.factory() as db:
        await archive_memory(db, MemoryContext(w.acme, f"user:{w.ids['admin']}"), m.id)
        await db.commit()
    row = await w.record(m)
    assert (row.status, row.trust_state) == ("archived", "verified")


# --- qualification -------------------------------------------------------------------------


async def test_attestation_reason_sets_the_ceiling(w):
    m = w.mem["active"]
    weak = await evidence_id(w, m, **attest("reviewed_by_admin"))
    strong = await evidence_id(w, m, **attest("independently_verified_by_admin"))
    assert (await w("admin", "POST", f"{m.id}/trust/assert",
                    json={"evidence_id": weak})).status_code == 200
    r = await w("admin", "POST", f"{m.id}/trust/verify", json={"evidence_id": weak})
    assert r.status_code == 409 and r.json()["detail"]["code"] == "MEMORY_EVIDENCE_NOT_QUALIFYING"
    assert (await w("admin", "POST", f"{m.id}/trust/verify",
                    json={"evidence_id": strong})).status_code == 200


async def test_chat_turn_is_provenance_and_never_qualifies(w):
    m = w.mem["active"]
    r = await attach(w, "admin", m, evidence_kind="chat_turn", source_id=str(w.src["turn"].id))
    assert r.status_code == 201 and r.json()["grade"] == "none"
    eid = r.json()["evidence_id"]
    for step in ("assert", "verify"):
        r = await w("admin", "POST", f"{m.id}/trust/{step}", json={"evidence_id": eid})
        assert r.status_code == 409
        assert (await w.record(m)).trust_state == "untrusted"


@pytest.mark.parametrize(("name", "grade"), [("tool_ok", "assert"), ("tool_bad", "none")])
async def test_tool_invocation_can_at_most_assert(w, name, grade):
    m = w.mem["active"]
    r = await attach(w, "admin", m, evidence_kind="tool_invocation",
                     source_id=str(w.src[name].id))
    assert r.status_code == 201 and r.json()["grade"] == grade
    asserted = await w("admin", "POST", f"{m.id}/trust/assert",
                       json={"evidence_id": r.json()["evidence_id"]})
    assert asserted.status_code == (200 if grade == "assert" else 409)
    if grade == "assert":
        verified = await w("admin", "POST", f"{m.id}/trust/verify",
                           json={"evidence_id": r.json()["evidence_id"]})
        assert verified.status_code == 409


@pytest.mark.parametrize(("name", "grade"), [
    ("done", "verify"), ("unverified", "none"), ("failed", "none"),
])
async def test_task_attempt_needs_durable_passed_verification(w, name, grade):
    r = await attach(w, "admin", w.mem["active"], evidence_kind="task_attempt",
                     source_id=str(w.src[name].id))
    assert r.status_code == 201 and r.json()["grade"] == grade


async def test_evidence_that_stopped_qualifying_cannot_promote(w):
    m = w.mem["active"]
    e = await evidence_id(w, m, evidence_kind="tool_invocation",
                          source_id=str(w.src["tool_ok"].id))
    async with w.factory() as db:
        (await db.get(ToolInvocation, w.src["tool_ok"].id)).status = "error"
        await db.commit()
    r = await w("admin", "POST", f"{m.id}/trust/assert", json={"evidence_id": e})
    assert r.status_code == 409 and r.json()["detail"]["code"] == "MEMORY_EVIDENCE_STALE"
    assert (await w.record(m)).trust_state == "untrusted"
    assert [a.action for a in await w.audits("memory.trust")] == []


async def test_attestation_of_a_since_deactivated_admin_is_stale(w):
    m = w.mem["active"]
    r = await w("second", "POST", f"{m.id}/evidence", json=attest("reviewed_by_admin"))
    assert r.status_code == 201
    await w.deactivate("second")
    r = await w("admin", "POST", f"{m.id}/trust/assert",
                json={"evidence_id": r.json()["evidence_id"]})
    assert r.status_code == 409 and r.json()["detail"]["code"] == "MEMORY_EVIDENCE_STALE"
    assert (await w.record(m)).trust_state == "untrusted"


# --- fail closed ---------------------------------------------------------------------------


async def test_invalid_transitions_are_stable_409s(w):
    c, a = w.mem["candidate"], w.mem["active"]
    e = await evidence_id(w, c, **attest())
    cases = [
        ("assert on a candidate", c, "trust/assert", {"evidence_id": e}),
        ("verify before assert", a, "trust/verify",
         {"evidence_id": await evidence_id(w, a, **attest("independently_verified_by_admin"))}),
        ("accept an active memory", a, "accept", None),
        ("accept an archived memory", w.mem["archived"], "accept", None),
    ]
    for name, memory, path, body in cases:
        r = await w("admin", "POST", f"{memory.id}/{path}", json=body)
        assert r.status_code == 409, name
        assert r.json()["detail"]["code"] in (
            "MEMORY_INVALID_TRANSITION", "MEMORY_ALREADY_ARCHIVED"), name
    assert (await w.record(c)).status == "candidate"


async def test_a_closed_memory_takes_no_evidence(w):
    r = await attach(w, "admin", w.mem["archived"], **attest())
    assert r.status_code == 409 and r.json()["detail"]["code"] == "MEMORY_INVALID_TRANSITION"
    assert await w.rows(MemoryEvidence) == []


async def test_evidence_of_another_memory_cannot_promote(w):
    a, b = w.mem["active"], w.mem["active2"]
    e = await evidence_id(w, b, **attest())
    r = await w("admin", "POST", f"{a.id}/trust/assert", json={"evidence_id": e})
    assert r.status_code == 404 and r.json()["detail"]["code"] == "MEMORY_EVIDENCE_NOT_FOUND"


@pytest.mark.parametrize("who", ("viewer", "run", "outsider", "gone"))
async def test_only_a_human_admin_of_the_company_can_use_any_route(w, who):
    if who == "gone":
        await w.deactivate("gone")
    m = w.mem["active"]
    fake = {"evidence_id": str(uuid.uuid4())}
    calls = [
        ("POST", f"{m.id}/evidence", {"json": attest()}),
        ("GET", f"{m.id}/evidence", {}),
        ("POST", f"{m.id}/accept", {}),
        ("POST", f"{m.id}/trust/assert", {"json": fake}),
        ("POST", f"{m.id}/trust/verify", {"json": fake}),
    ]
    for method, path, kw in calls:
        r = await w(who, method, path, **kw)
        # Another company's admin addressing this company gets the fixed company 404.
        assert r.status_code in ((404,) if who == "outsider" else (401, 403)), (who, path)
        assert SECRET not in r.text
    assert await w.rows(MemoryEvidence) == [] and await w.audits() == []


async def test_forbidden_is_answered_before_any_lookup(w):
    """A viewer learns nothing about whether a memory exists."""
    known = await w("viewer", "GET", f"{w.mem['active'].id}/evidence")
    unknown = await w("viewer", "GET", f"{uuid.uuid4()}/evidence")
    assert known.status_code == unknown.status_code == 403
    assert known.json() == unknown.json()


async def test_a_foreign_company_path_is_the_fixed_404(w):
    r = await w("admin", "GET", f"{w.foreign.id}/evidence", company=w.other)
    nowhere = await w("admin", "GET", f"{w.foreign.id}/evidence", company=uuid.uuid4())
    assert r.status_code == nowhere.status_code == 404
    assert r.json() == nowhere.json()


async def test_foreign_and_nonexistent_ids_are_indistinguishable(w):
    foreign_mem = await w("admin", "GET", f"{w.foreign.id}/evidence")
    missing_mem = await w("admin", "GET", f"{uuid.uuid4()}/evidence")
    assert foreign_mem.status_code == missing_mem.status_code == 404
    assert foreign_mem.json() == missing_mem.json()

    m = w.mem["active"]
    for kind, theirs in (("chat_turn", "foreign_turn"), ("task_attempt", "foreign_done")):
        foreign_src = await attach(w, "admin", m, evidence_kind=kind,
                                   source_id=str(w.src[theirs].id))
        missing_src = await attach(w, "admin", m, evidence_kind=kind,
                                   source_id=str(uuid.uuid4()))
        assert foreign_src.status_code == missing_src.status_code == 404, kind
        assert foreign_src.json() == missing_src.json(), kind

    fake = {"evidence_id": str(uuid.uuid4())}
    one = await w("admin", "POST", f"{w.foreign.id}/trust/assert", json=fake)
    two = await w("admin", "POST", f"{uuid.uuid4()}/trust/assert", json=fake)
    assert one.status_code == two.status_code == 404 and one.json() == two.json()
    assert await w.rows(MemoryEvidence) == []


async def test_a_users_attestation_cannot_name_another_user(w):
    r = await attach(w, "admin", w.mem["active"], evidence_kind="human_attestation",
                     reason_code="reviewed_by_admin", source_id=str(w.ids["viewer"]))
    assert r.status_code == 422 and r.json()["detail"]["code"] == "MEMORY_EVIDENCE_INVALID"


@pytest.mark.parametrize("body", [
    {"evidence_kind": "human_attestation", "reason_code": "because"},
    {"evidence_kind": "human_attestation"},
    {"evidence_kind": "chat_turn"},
    {"evidence_kind": "chat_turn", "source_id": str(uuid.uuid4()), "reason_code": "x"},
])
async def test_malformed_evidence_is_a_422(w, body):
    r = await attach(w, "admin", w.mem["active"], **body)
    assert r.status_code == 422
    assert r.json()["detail"]["code"] == "MEMORY_EVIDENCE_INVALID"


@pytest.mark.parametrize("extra", [
    {"company_id": str(uuid.uuid4())}, {"grade": "verify"}, {"verified": True},
    {"trust_state": "verified"}, {"source_digest": "0" * 64}, {"created_by": "user:x"},
    {"trust_score": 1.0},
])
async def test_callers_cannot_supply_server_derived_fields(w, extra):
    r = await attach(w, "admin", w.mem["active"], **attest(), **extra)
    assert r.status_code == 422
    e = await evidence_id(w, w.mem["active"], **attest())
    r = await w("admin", "POST", f"{w.mem['active'].id}/trust/assert",
                json={"evidence_id": e, **extra})
    assert r.status_code == 422
    assert (await w.record(w.mem["active"])).trust_state == "untrusted"


async def test_unknown_fields_on_accept_are_rejected(w):
    r = await w("admin", "POST", f"{w.mem['candidate'].id}/accept", json={"status": "verified"})
    assert r.status_code == 422
    assert (await w.record(w.mem["candidate"])).status == "candidate"


# --- idempotency ---------------------------------------------------------------------------


async def test_a_mutation_needs_a_valid_key(w):
    m = w.mem["candidate"]
    r = await w("admin", "POST", f"{m.id}/accept", idem=False)
    assert r.status_code == 422 and r.json()["detail"]["code"] == "IDEMPOTENCY_KEY_REQUIRED"
    r = await w("admin", "POST", f"{m.id}/accept", headers={"Idempotency-Key": "short"})
    assert r.status_code == 422 and r.json()["detail"]["code"] == "IDEMPOTENCY_KEY_INVALID"
    assert (await w.record(m)).status == "candidate"


@pytest.mark.parametrize("shape", ("attach", "accept", "assert"))
async def test_a_retry_returns_the_original_result_with_one_effect(w, shape):
    k = {"Idempotency-Key": "replay-key-12345"}
    m = w.mem["candidate"] if shape == "accept" else w.mem["active"]
    path, body = {
        "attach": (f"{m.id}/evidence", attest()),
        "accept": (f"{m.id}/accept", None),
        "assert": (f"{m.id}/trust/assert", None),
    }[shape]
    if shape == "assert":
        body = {"evidence_id": await evidence_id(w, m, **attest())}
    first = await w("admin", "POST", path, json=body, headers=k)
    again = await w("admin", "POST", path, json=body, headers=k)
    assert first.status_code in (200, 201) and again.status_code == first.status_code
    assert again.json() == first.json()
    assert "idempotency-replayed" not in first.headers
    assert again.headers["idempotency-replayed"] == "true"
    expected = {"attach": 1, "accept": 0, "assert": 1}[shape]
    assert len(await w.rows(MemoryEvidence)) == expected
    action = {"attach": "memory.evidence_attached", "accept": "memory.accepted",
              "assert": "memory.trust_asserted"}[shape]
    assert [a.action for a in await w.audits()].count(action) == 1


async def test_the_same_key_for_another_request_is_a_stable_409(w):
    k = {"Idempotency-Key": "conflict-key-12345"}
    m = w.mem["active"]
    assert (await w("admin", "POST", f"{m.id}/evidence", json=attest(),
                    headers=k)).status_code == 201
    other_body = await w("admin", "POST", f"{m.id}/evidence",
                         json=attest("independently_verified_by_admin"), headers=k)
    other_memory = await w("admin", "POST", f"{w.mem['active2'].id}/evidence",
                           json=attest(), headers=k)
    other_op = await w("admin", "POST", f"{m.id}/accept", headers=k)
    for r in (other_body, other_memory, other_op):
        assert r.status_code == 409
        assert r.json()["detail"]["code"] == "MEMORY_IDEMPOTENCY_CONFLICT"
    assert len(await w.rows(MemoryEvidence)) == 1


async def test_a_second_key_for_the_same_evidence_is_a_conflict_not_a_second_row(w):
    m = w.mem["active"]
    assert (await attach(w, "admin", m, **attest())).status_code == 201
    r = await attach(w, "admin", m, **attest())
    assert r.status_code == 409 and r.json()["detail"]["code"] == "MEMORY_EVIDENCE_DUPLICATE"
    assert len(await w.rows(MemoryEvidence)) == 1


async def test_a_refused_request_leaves_no_ledger_row_or_audit(w):
    r = await w("admin", "POST", f"{w.mem['archived'].id}/accept")
    assert r.status_code == 409
    assert await w.rows(MemoryOperation) == [] and await w.audits() == []


# --- reads, audit and immutability ---------------------------------------------------------


async def test_listing_evidence_is_audited_and_content_free(w):
    m = w.mem["active"]
    e = await evidence_id(w, m, **attest())
    r = await w("admin", "GET", f"{m.id}/evidence")
    assert r.status_code == 200
    [item] = r.json()["evidence"]
    assert item["evidence_id"] == e and item["grade"] == "assert"
    assert item["created_by"] == f"user:{w.ids['admin']}"
    assert item["source_id"] == str(w.ids["admin"])
    assert SECRET not in r.text
    [reviewed] = await w.audits("memory.evidence_reviewed")
    assert reviewed.company_id == w.acme and reviewed.actor_id == f"user:{w.ids['admin']}"


async def test_no_audit_row_or_response_holds_content(w):
    m = w.mem["candidate"]
    await w("admin", "POST", f"{m.id}/accept")
    e = await evidence_id(w, m, evidence_kind="task_attempt",
                          source_id=str(w.src["done"].id))
    await w("admin", "POST", f"{m.id}/trust/assert", json={"evidence_id": e})
    await w("admin", "GET", f"{m.id}/evidence")
    for a in await w.audits():
        assert SECRET not in str(a.details) and SECRET not in str(a.resource_id)
        assert a.actor_id == f"user:{w.ids['admin']}"
    for e_row in await w.rows(MemoryEvidence):
        assert SECRET not in str(e_row.model_dump(mode="json"))
        assert len(e_row.source_digest) == 64 and e_row.policy_version == "memory-evidence-v1"


async def test_evidence_rows_are_immutable_through_the_orm(w):
    m = w.mem["active"]
    await attach(w, "admin", m, **attest())
    async with w.factory() as db:
        row = (await db.execute(select(MemoryEvidence))).scalars().one()
        row.grade = "verify"
        with pytest.raises(ValueError, match="append-only"):
            await db.flush()
        await db.rollback()
    assert len(await w.rows(MemoryEvidence)) == 1


async def test_evidence_cannot_cross_companies(w):
    """The composite checks live in the service; the FK keeps a row from naming a stranger."""
    m = w.mem["active"]
    await attach(w, "admin", m, **attest())
    [row] = await w.rows(MemoryEvidence)
    assert row.company_id == w.acme and row.memory_id == m.id
