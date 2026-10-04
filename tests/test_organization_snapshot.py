"""Organization Snapshot v1: payload, persistence, refresh model, freshness and access.

Functional tests on a file SQLite database. The PostgreSQL race and row-level
security tests live in tests/test_postgres_integration.py.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import timedelta
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI, Request
from sqlalchemy import event, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlmodel import SQLModel

from nexus.api.routes import organization as organization_routes
from nexus.auth.principal import Principal
from nexus.config import settings
from nexus.models.agent import Agent
from nexus.models.budget import BudgetPolicy
from nexus.models.company import Company
from nexus.models.governance import Approval, AuditLog
from nexus.models.incident import Incident
from nexus.models.organization_snapshot import OrganizationSnapshot, OrganizationSnapshotState
from nexus.models.task import Task
from nexus.models.task_attempt import TaskAttempt
from nexus.models.tool import ToolPolicy
from nexus.realtime.publish import publish_event
from nexus.services import hiring_service
from nexus.services import org_snapshot as snap
from nexus.tools.context import INBOUND_MCP, ExecutionContext
from nexus.tools.mcp_server import MCPServer


@pytest.fixture
async def db(tmp_path, monkeypatch):
    engine = create_async_engine(f"sqlite+aiosqlite:///{(tmp_path / 'org.db').as_posix()}")
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    import nexus.database as database

    monkeypatch.setattr(database, "async_session_factory", factory)
    monkeypatch.setattr(settings, "database_url", str(engine.url))
    factory.engine = engine
    yield factory
    await engine.dispose()


@pytest.fixture
async def org(db):
    """Acme: Lead manages e1, e2 and a hired employee; one done, one running, one blocked task.

    Hiring: one hired request, one awaiting approval. Other is a second tenant.
    """
    now = snap._now()
    async with db() as s:
        acme = Company(name="Acme", budget_monthly_cents=100_000, spent_monthly_cents=2_500)
        other = Company(name="Other")
        s.add_all([acme, other])
        await s.flush()
        lead = Agent(company_id=acme.id, name="Lead", role="manager", adapter_type="cli",
                     adapter_config={"backend": "claude"}, model="")
        s.add(lead)
        await s.flush()
        e1 = Agent(company_id=acme.id, name="e1", role="engineer", adapter_type="cli",
                   adapter_config={"backend": "claude"}, model="", manager_id=lead.id,
                   budget_monthly_cents=1_000)
        e2 = Agent(company_id=acme.id, name="e2", role="reviewer", adapter_type="cli",
                   adapter_config={"backend": "codex"}, model="", manager_id=lead.id)
        hired = Approval(company_id=acme.id, type=hiring_service.HIRE, status="approved",
                         requested_by_agent_id=lead.id,
                         payload={"amount_cents": 1_200, "request": {
                             "role": "engineer", "backend": "claude",
                             "estimated_monthly_cents": 100},
                             "policy": {"outcome": "auto_approved"}})
        pending = Approval(company_id=acme.id, type=hiring_service.HIRE, status="pending",
                           requested_by_agent_id=lead.id,
                           payload={"amount_cents": 2_400, "request": {
                               "role": "reviewer", "backend": "codex",
                               "estimated_monthly_cents": 200},
                               "policy": {"outcome": "approval_required"}})
        s.add_all([e1, e2, hired, pending])
        await s.flush()
        e3 = Agent(id=hiring_service.employee_id_for(hired.id), company_id=acme.id, name="e3",
                   role="engineer", adapter_type="cli", adapter_config={"backend": "claude"},
                   model="", manager_id=lead.id)
        done = Task(company_id=acme.id, title="Done", status="completed", assigned_agent_id=e1.id)
        running = Task(company_id=acme.id, title="Running", status="in_progress",
                       assigned_agent_id=e2.id)
        blocked = Task(company_id=acme.id, title="Blocked", status="blocked",
                       assigned_agent_id=e1.id)
        s.add_all([
            e3, done, running, blocked,
            BudgetPolicy(company_id=acme.id, scope_type="company", scope_id=acme.id,
                         metric="cost_cents", window_kind="monthly", amount=5_000,
                         spent_cents=700, reserved_cents=300),
            Incident(company_id=acme.id, title="Build red", severity="high"),
        ])
        await s.flush()

        def attempt(task, agent, status, **kw):
            return TaskAttempt(company_id=acme.id, task_id=task.id, agent_id=agent.id,
                               attempt_number=1, idempotency_key=str(uuid.uuid4()),
                               status=status, **kw)

        s.add_all([
            attempt(done, e1, "completed", output_summary="Added calculator", completed_at=now,
                    verification={"passed": True},
                    artifacts=[{"path": "calc.py", "sha256": "ab" * 32, "commit": "c0ffee"}]),
            attempt(running, e2, "running", started_at=now,
                    lease_expires_at=now + timedelta(hours=1)),
            attempt(blocked, e1, "blocked", error_code="MISSING_INPUT", completed_at=now),
        ])
        await s.commit()
    return SimpleNamespace(
        acme=acme.id, other=other.id, lead=lead.id, e1=e1.id, e2=e2.id, e3=e3.id,
        hired=hired.id, pending=pending.id, running=running.id, now=now,
    )


def _run(company, agent):
    return Principal(kind="run", company_id=company, role="agent", run_id=uuid.uuid4(),
                     agent_id=agent)


def _user(company, role="admin"):
    return Principal(kind="user", company_id=company, role=role, user_id=uuid.uuid4(),
                     email="owner@example.test")


@pytest.fixture
async def api(org):
    principals = {
        "admin": _user(org.acme),
        "outsider": _user(org.other),
        "lead_run": _run(org.acme, org.lead),
        "e1_run": _run(org.acme, org.e1),
    }
    app = FastAPI()
    app.include_router(organization_routes.router)

    @app.middleware("http")
    async def as_principal(request: Request, call_next):
        request.state.principal = principals[request.headers.get("x-test-principal", "admin")]
        return await call_next(request)

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                 base_url="http://test") as client:
        async def call(method, path, who="admin"):
            return await client.request(
                method, f"/api/v1/organization/snapshot{path}", headers={"x-test-principal": who}
            )
        yield call


async def _versions(db, company):
    async with db() as s:
        rows = await s.execute(
            select(OrganizationSnapshot).where(OrganizationSnapshot.company_id == company)
            .order_by(OrganizationSnapshot.version)
        )
        return list(rows.scalars())


async def _state(db, company):
    async with db() as s:
        return await s.get(OrganizationSnapshotState, company)


async def _build(db, company, now=None):
    async with db() as s:
        return await snap.build(s, company, now or snap._now())


# --- payload ----------------------------------------------------------------


class TestPayload:
    async def test_payload_and_hash_are_deterministic(self, db, org):
        first, second = await _build(db, org.acme, org.now), await _build(db, org.acme, org.now)
        assert snap.canonical(first) == snap.canonical(second)
        assert snap.payload_hash(first) == snap.payload_hash(second)
        assert snap.canonical({"b": 1, "a": [2]}) == '{"a":[2],"b":1}'
        assert (await snap.generate(org.acme, org.now))["outcome"] == "created"
        assert (await snap.generate(org.acme, org.now))["outcome"] == "unchanged"
        [row] = await _versions(db, org.acme)
        assert row.version == 1 and row.payload_hash == snap.payload_hash(row.payload)
        assert row.generation_key == f"1:{row.payload_hash}:0"

    async def test_hierarchy_and_workforce(self, db, org):
        p = await _build(db, org.acme)
        assert p["company"] == {"id": str(org.acme), "name": "Acme", "status": "active"}
        assert p["hierarchy"]["roots"] == [str(org.lead)] and p["hierarchy"]["depth"] == 2
        [lead] = p["hierarchy"]["managers"]
        assert lead["report_ids"] == sorted(str(i) for i in (org.e1, org.e2, org.e3))
        assert p["employees"]["total"] == 4
        assert p["employees"]["by_role"] == {"manager": 1, "engineer": 2, "reviewer": 1}
        assert p["employees"]["by_backend"] == {"claude": 3, "codex": 1}
        assert sum(p["employees"]["by_status"].values()) == 4
        assert p["sources"]["agents"]["count"] == 4 and p["sources"]["tasks"]["count"] == 3
        assert p["data_as_of"] == max(s["latest"] for s in p["sources"].values() if s["latest"])

    async def test_work_results_and_summary(self, db, org):
        p = await _build(db, org.acme)
        assert p["work"]["counts"] == {"active": 1, "queued": 0, "stale": 0, "completed": 1,
                                       "failed": 0, "blocked": 1, "cancelled": 0}
        assert [i["title"] for i in p["work"]["items"]["active"]] == ["Running"]
        assert p["work"]["items"]["blocked"][0]["error_code"] == "MISSING_INPUT"
        done = next(r for r in p["work"]["latest_results"] if r["status"] == "completed")
        assert done["verified"] is True and done["evidence"][0]["path"] == "calc.py"
        assert "1 active" in p["summary"]["text"] and "1 blocked" in p["summary"]["text"]
        assert p["summary"]["attention"] == ["e1: Blocked"]
        # A running attempt whose lease lapsed is stale, not active.
        later = await _build(db, org.acme, org.now + timedelta(hours=2))
        assert later["work"]["counts"]["stale"] == 1 and later["work"]["counts"]["active"] == 0

    async def test_hiring_approvals_budget_and_incidents(self, db, org):
        p = await _build(db, org.acme)
        assert p["hiring"]["counts"] == {"pending": 1, "approved": 1, "rejected": 0, "failed": 0}
        assert p["approvals"]["pending"] == 1
        assert p["approvals"]["items"][0]["id"] == str(org.pending)
        b = p["budget"]
        assert b["company_remaining_cents"] == 97_500 and b["employees_monthly_cents"] == 1_000
        assert b["policies"] == {"active": 1, "limit_cents": 5_000, "spent_cents": 700,
                                 "reserved_cents": 300}
        assert b["hiring_pending_cents"] == 2_400 and b["hiring_pending_monthly_cents"] == 200
        assert b["hiring_reserved_cents"] == 0
        assert p["incidents"]["open"] == 1 and p["incidents"]["by_severity"] == {"high": 1}
        # An approved request whose employee was never created is a failed hire that
        # still holds its reservation.
        async with db() as s:
            await s.delete(await s.get(Agent, org.e3))
            await s.commit()
        p = await _build(db, org.acme)
        assert p["hiring"]["counts"]["failed"] == 1
        assert p["budget"]["hiring_reserved_cents"] == 1_200

    async def test_manager_projection_is_team_only(self, db, org):
        p = await _build(db, org.acme)
        view = snap.manager_view(p, org.lead)
        assert {e["id"] for e in view["employees"]["list"]} == {str(org.e1), str(org.e2),
                                                                str(org.e3)}
        assert view["work"]["counts"]["active"] == 1 and view["work"]["counts"]["blocked"] == 1
        assert {"budget", "approvals", "incidents", "sources", "hierarchy"}.isdisjoint(view)
        assert snap.manager_view(p, org.e1)["employees"]["total"] == 0


# --- refresh model ----------------------------------------------------------


async def _wait_dirty(db, company):
    for _ in range(100):
        state = await _state(db, company)
        if state is not None and state.dirty_since is not None:
            return state
        await asyncio.sleep(0.01)
    raise AssertionError("company was never marked dirty")


class TestRefresh:
    async def test_commits_and_events_mark_the_company_dirty(self, db, org):
        await snap.start_listener()
        try:
            async with db() as s:
                await s.execute(update(Task).where(Task.company_id == org.acme,
                                                   Task.id == org.running)
                                .values(status="completed"))
                await s.commit()
            assert (await _wait_dirty(db, org.acme)).last_dirty_at is not None
            assert await _state(db, org.other) is None
            # A rolled-back write marks nothing.
            async with db() as s:
                s.add(Incident(company_id=org.other, title="x"))
                await s.flush()
                await s.rollback()
            await asyncio.sleep(0.05)
            assert await _state(db, org.other) is None
            # Existing realtime events count too.
            await publish_event("tasks", "task.attempt", org.other, {})
            await _wait_dirty(db, org.other)
        finally:
            await snap.stop_listener()

    async def test_debounced_regeneration_and_reconciliation(self, db, org):
        t0 = org.now
        ticked = await snap.tick(t0, discovery=db)
        assert sorted(ticked, key=str) == sorted([org.acme, org.other], key=str)
        async with db() as s:
            await s.execute(update(Task).where(Task.id == org.running).values(title="Renamed"))
            await s.commit()
        await snap.mark_dirty({org.acme}, t0 + timedelta(seconds=60))
        assert await snap.tick(t0 + timedelta(seconds=70), discovery=db) == []  # still settling
        assert await snap.tick(t0 + timedelta(seconds=95), discovery=db) == [org.acme]
        assert [r.version for r in await _versions(db, org.acme)] == [1, 2]
        assert (await _state(db, org.acme)).dirty_since is None
        # Reconciliation: every company, changed or not, and no new version when unchanged.
        later = t0 + timedelta(seconds=95) + snap.RECONCILE_EVERY
        assert set(await snap.tick(later, discovery=db)) == {org.acme, org.other}
        assert [r.version for r in await _versions(db, org.other)] == [1]
        assert (await _state(db, org.other)).verified_at == later

    def test_due_rules(self):
        now = snap._now()
        s = lambda **kw: SimpleNamespace(**{  # noqa: E731
            "dirty_since": None, "last_dirty_at": None, "generating_until": None,
            "attempted_at": now - timedelta(minutes=1), **kw})
        assert not snap._due(s(), now)
        assert snap._due(s(attempted_at=None), now)
        assert not snap._due(s(dirty_since=now, last_dirty_at=now), now)
        # Continuous changes still regenerate once MAX_WAIT has passed.
        assert snap._due(s(dirty_since=now - snap.MAX_WAIT, last_dirty_at=now), now)
        assert not snap._due(s(attempted_at=None, generating_until=now + snap.LEASE), now)

    async def test_refresh_is_idempotent_and_single_flight(self, db, org, api):
        first = (await api("POST", "/refresh")).json()
        assert first["refresh"] == {"outcome": "created", "version": 1}
        second = (await api("POST", "/refresh")).json()
        assert second["refresh"] == {"outcome": "unchanged", "version": 1}
        assert second["freshness"]["status"] == "fresh"
        async with db() as s:
            await s.execute(update(OrganizationSnapshotState)
                            .where(OrganizationSnapshotState.company_id == org.acme)
                            .values(generating_until=snap._now() + snap.LEASE, generating_by="x"))
            await s.commit()
        busy = (await api("POST", "/refresh")).json()
        assert busy["refresh"]["outcome"] == "in_progress"
        assert busy["freshness"]["status"] == "rebuilding" and busy["version"] == 1
        async with db() as s:
            actions = (await s.execute(select(AuditLog.action).where(
                AuditLog.action == "organization.snapshot_refreshed"))).scalars().all()
        assert len(actions) == 3

    async def test_concurrent_generations_create_one_version(self, db, org):
        results = await asyncio.gather(*(snap.generate(org.acme) for _ in range(4)))
        assert sorted(r["outcome"] for r in results).count("created") == 1
        assert [r.version for r in await _versions(db, org.acme)] == [1]

    async def test_failure_keeps_the_previous_snapshot(self, db, org, api, monkeypatch):
        await snap.generate(org.acme)

        async def broken(*a, **kw):
            raise RuntimeError("database went away")

        build = snap.build
        monkeypatch.setattr(snap, "build", broken)
        assert (await snap.generate(org.acme))["outcome"] == "failed"
        body = (await api("GET", "")).json()
        assert body["version"] == 1 and body["snapshot"]["company"]["name"] == "Acme"
        assert body["freshness"]["status"] == "failed_refresh"
        assert body["last_refresh_error"]["message"] == "RuntimeError: database went away"
        assert (await _state(db, org.acme)).generating_until is None
        monkeypatch.setattr(snap, "build", build)
        await snap.generate(org.acme)
        body = (await api("GET", "")).json()
        assert body["freshness"]["status"] == "fresh" and body["last_refresh_error"] is None


class TestFreshness:
    def test_transitions(self):
        now = snap._now()
        row = SimpleNamespace(generated_at=now - timedelta(minutes=1))
        state = lambda **kw: SimpleNamespace(**{  # noqa: E731
            "verified_at": None, "generating_until": None, "last_error": None,
            "last_error_at": None, "dirty_since": None, **kw})
        status = lambda r, s: snap.freshness(r, s, now)["status"]  # noqa: E731
        assert status(None, None) == "stale"
        assert status(row, None) == "fresh"
        assert snap.freshness(row, None, now)["age_seconds"] == 60
        assert status(row, state(dirty_since=now)) == "stale"
        assert status(SimpleNamespace(generated_at=now - snap.STALE_AFTER - timedelta(1)),
                      state()) == "stale"
        # A later unchanged verification keeps an old version fresh.
        assert status(SimpleNamespace(generated_at=now - timedelta(days=1)),
                      state(verified_at=now)) == "fresh"
        assert status(row, state(generating_until=now + snap.LEASE)) == "rebuilding"
        assert status(row, state(last_error="E: x", last_error_at=now)) == "failed_refresh"
        # Only a success clears the error, so its timestamp is not compared: a
        # worker whose clock lags still reports its failure.
        assert status(row, state(last_error="E: x", verified_at=now,
                                 last_error_at=now - timedelta(minutes=2))) == "failed_refresh"


# --- access -----------------------------------------------------------------


def _ctx(company, agent):
    return ExecutionContext(company_id=company, principal_id=f"run:{uuid.uuid4()}",
                            principal_role="agent", source=INBOUND_MCP, agent_id=agent)


class TestAccess:
    async def test_tenants_see_only_their_own_snapshot(self, db, org, api):
        await snap.generate(org.acme)
        body = (await api("GET", "", who="outsider")).json()
        assert body["company_id"] == str(org.other) and body["snapshot"] is None
        assert body["freshness"]["status"] == "stale"
        assert (await api("GET", "/history", who="outsider")).json() == []
        assert len((await api("GET", "/history")).json()) == 1

    async def test_employees_are_denied_and_managers_get_their_team(self, db, org, api):
        await snap.generate(org.acme)
        denied = await api("GET", "", who="e1_run")
        assert denied.status_code == 403 and denied.json()["detail"]["code"] == "SNAPSHOT_FORBIDDEN"
        team = (await api("GET", "", who="lead_run")).json()
        assert team["scope"] == "manager" and team["sources"] is None
        assert team["snapshot"]["employees"]["total"] == 3 and "budget" not in team["snapshot"]
        for path, method in (("/history", "GET"), ("/refresh", "POST")):
            assert (await api(method, path, who="lead_run")).status_code == 403
        async with db() as s:
            reads = (await s.execute(select(AuditLog).where(
                AuditLog.action == "organization.snapshot_read"))).scalars().all()
        assert [r.details["scope"] for r in reads] == ["manager"]

    async def test_org_wide_reporting_needs_a_pinned_named_allow(self, db, org, api):
        await snap.generate(org.acme)
        async with db() as s:
            s.add(ToolPolicy(company_id=org.acme, name="broad", effect="allow",
                             conditions={"tool_name": ["*"], "agent_id": [str(org.e1)]}))
            await s.commit()
        assert (await api("GET", "", who="e1_run")).status_code == 403
        async with db() as s:
            s.add(ToolPolicy(company_id=org.acme, name="report", effect="allow",
                             conditions={"tool_name": snap.TOOL, "agent_id": [str(org.e1)]}))
            await s.commit()
        body = (await api("GET", "", who="e1_run")).json()
        assert body["scope"] == "organization" and body["snapshot"]["budget"]
        async with db() as s:
            s.add(ToolPolicy(company_id=org.acme, name="no", effect="deny", priority=-1,
                             conditions={"tool_name": snap.TOOL}))
            await s.commit()
        assert (await api("GET", "", who="e1_run")).status_code == 403

    async def test_governed_tool(self, db, org):
        await snap.generate(org.acme)
        lead = MCPServer(_ctx(org.acme, org.lead))
        assert snap.TOOL in {t["name"] for t in await lead.list_tools()}
        result = await lead.call_tool(snap.TOOL, {})
        assert not result["isError"] and '"scope": "manager"' in result["content"][0]["text"]
        # An employee is not offered the tool, so calling it is refused before it runs.
        refused = await MCPServer(_ctx(org.acme, org.e1)).call_tool(snap.TOOL, {})
        assert refused["isError"] and "TOOL_NOT_OFFERED" in refused["content"][0]["text"]
        outsider = await MCPServer(_ctx(org.other, org.lead)).call_tool(snap.TOOL, {})
        assert outsider["isError"]


# --- performance ------------------------------------------------------------


class TestReadPath:
    async def test_latest_reads_only_the_stored_snapshot(self, db, org, api):
        await snap.generate(org.acme)
        statements = []

        def record(conn, cursor, statement, *args):
            statements.append(statement)

        event.listen(db.engine.sync_engine, "before_cursor_execute", record)
        try:
            body = (await api("GET", "")).json()
        finally:
            event.remove(db.engine.sync_engine, "before_cursor_execute", record)
        assert body["version"] == 1 and body["snapshot"]["employees"]["total"] == 4
        selects = [s for s in statements if s.lstrip().upper().startswith("SELECT")]
        assert len(selects) == 2, selects
        assert all("organization_snapshot" in s for s in selects)
