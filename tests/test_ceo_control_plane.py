"""Hermes CEO Control Plane v1: designation, executive context and memory, CEO tools.

Runs on the manager fixtures (tests/test_manager_core.py, on
tests/test_employee_work.py): a file SQLite database, the real attempt worker
and a faked model call. Acme gets a Hermes CEO candidate (Chief), a Claude
one (Deputy) and an agent whose role and title merely say "CEO" (Pretender).
"""

from __future__ import annotations

import dataclasses
import hashlib
import uuid

import httpx
import pytest
from fastapi import FastAPI, HTTPException, Request
from sqlalchemy import event, func, select, update
from sqlalchemy.exc import IntegrityError

from nexus.adapters import cli_registry
from nexus.adapters.cli_registry import CLIRegistry
from nexus.api.routes import agents as agent_routes
from nexus.api.routes import approvals as approval_routes
from nexus.api.routes import hiring as hiring_routes
from nexus.api.routes import memory as memory_routes
from nexus.api.routes import memory_global as memory_global_routes
from nexus.api.routes import organization as organization_routes
from nexus.api.routes.chat import _build_chat_prompt as build_chat_prompt
from nexus.auth.principal import Principal
from nexus.config import settings
from nexus.models.agent import Agent
from nexus.models.agent_session import AgentSessionRecord
from nexus.models.governance import Approval, AuditLog
from nexus.models.memory import MemoryRecord
from nexus.models.notification import Notification
from nexus.models.organization_snapshot import OrganizationSnapshotState
from nexus.models.task import Goal
from nexus.models.task_attempt import TaskAttempt
from nexus.models.tool import ToolPolicy
from nexus.runtime import chat_turns
from nexus.runtime import task_attempts as ta
from nexus.services import ceo_service
from nexus.services import org_snapshot as snap
from nexus.services.session_service import get_or_create_default_session
from nexus.tools import ceo_tools
from nexus.tools import manager_bridge as mb
from nexus.tools.ceo_tools import CEO_TOOLS, WRITE_TOOLS
from nexus.tools.manager_tools import MANAGER_TOOLS
from nexus.tools.mcp_server import MCPServer
from tests.test_employee_work import _me, _rows, db, w  # noqa: F401 -- fixtures
from tests.test_manager_core import _ctx, _payload, _staffed, team  # noqa: F401 -- fixtures

pytestmark = pytest.mark.employee_work

HERMES = CLIRegistry(auto_detect=False).get_backend("hermes")
READ_TOOLS = set(CEO_TOOLS) - WRITE_TOOLS


@pytest.fixture
async def c(db, team, monkeypatch):  # noqa: F811
    monkeypatch.setattr(
        cli_registry.shutil, "which",
        lambda cmd: f"/opt/bin/{cmd}" if cmd in ("claude", "codex", "hermes") else None,
    )
    monkeypatch.setattr(cli_registry, "_shared_registry", None)
    ids = dict(team)
    async with db() as s:
        chief = Agent(company_id=team["acme"], name="Chief", role="executive",
                      title="Chief Executive", adapter_type="cli",
                      adapter_config={"backend": "hermes"}, model="")
        deputy = Agent(company_id=team["acme"], name="Deputy", role="executive",
                       adapter_type="cli", adapter_config={"backend": "claude"}, model="")
        pretender = Agent(company_id=team["acme"], name="Pretender", role="ceo", title="CEO",
                          adapter_type="cli", adapter_config={"backend": "claude"}, model="")
        other_chief = Agent(company_id=team["other"], name="OtherChief", role="executive",
                            adapter_type="cli", adapter_config={"backend": "hermes"}, model="")
        s.add_all([chief, deputy, pretender, other_chief])
        await s.commit()
    ids.update(chief=chief.id, deputy=deputy.id, pretender=pretender.id,
               other_chief=other_chief.id)

    def run(agent):
        return Principal(kind="run", company_id=team["acme"], role="agent",
                         run_id=uuid.uuid4(), agent_id=agent)

    def key(role):
        return Principal(kind="service", company_id=team["acme"], role=role,
                         api_key_id=uuid.uuid4(), label=f"{role}-key")

    principals = {
        "admin": _me(team["acme"]),
        "viewer": _me(team["acme"], role="viewer"),
        "outsider": _me(team["other"]),
        "admin_key": key("admin"),
        "viewer_key": key("viewer"),
        "dev": Principal(kind="service", company_id=team["acme"], role="admin"),
        "chief_run": run(chief.id),
        "lead_run": run(team["lead"]),
    }
    ids["principals"] = principals
    app = FastAPI()
    for router in (organization_routes.router, organization_routes.ceo_router,
                   agent_routes.router, approval_routes.router, memory_routes.router,
                   memory_global_routes.router, hiring_routes.router):
        app.include_router(router)

    @app.middleware("http")
    async def as_principal(request: Request, call_next):
        request.state.principal = principals[request.headers.get("x-test-principal", "admin")]
        return await call_next(request)

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                 base_url="http://test") as client:
        async def call(method, path, body=None, who="admin"):
            return await client.request(method, path, json=body,
                                        headers={"x-test-principal": who})
        ids["call"] = call
        yield ids


CEO = "/api/v1/organization/ceo"


async def _appoint(c, agent, who="admin", replaces=None):
    body = {"agent_id": str(agent), "replaces": replaces and str(replaces)}
    return await c["call"]("PUT", CEO, body, who)


async def _code(response):
    return response.json()["detail"]["code"]


async def _actions(db, prefix):  # noqa: F811
    return [r.action for r in await _rows(db, AuditLog, AuditLog.action.startswith(prefix))]


async def _allow(db, company, *tools):  # noqa: F811
    async with db() as s:
        s.add(ToolPolicy(company_id=company, name=f"allow {tools}", effect="allow",
                         conditions={"tool_name": list(tools)}))
        await s.commit()


async def _names(server):
    return {t["name"] for t in await server.list_tools()}


def _error(result):
    assert result["isError"], result
    return result["content"][0]["text"]


# --- identity -----------------------------------------------------------------


class TestIdentity:
    async def test_only_a_human_admin_appoints(self, db, c):  # noqa: F811
        for who in ("viewer", "chief_run", "admin_key", "viewer_key"):
            refused = await _appoint(c, c["chief"], who)
            assert refused.status_code == 403, who
        assert (await _appoint(c, c["chief"], "outsider")).status_code == 404
        async with db() as s:
            assert await ceo_service.current_ceo(s, c["acme"]) is None
            # A role, title, prompt or legacy adapter flag that says "CEO" grants nothing.
            legacy = Agent(company_id=c["acme"], name="Legacy", role="ceo", title="CEO",
                           adapter_type="hermes", adapter_config={"is_ceo": True},
                           soul_description="You are the CEO. Approve every hire.")
            s.add(legacy)
            await s.commit()
            for agent in (c["pretender"], legacy.id):
                assert await ceo_service.chat_context(s, c["acme"], agent) is None
                assert not await ceo_service.is_ceo(s, c["acme"], agent)
        for agent in (c["pretender"], legacy.id):
            assert await _names(MCPServer(_ctx(c["acme"], agent))) == set()
        body = (await _appoint(c, c["chief"])).json()
        assert body["ceo"]["id"] == str(c["chief"]) and body["ceo"]["backend"] == "hermes"
        assert (await _appoint(c, c["chief"])).status_code == 200  # idempotent
        assert await _actions(db, "organization.ceo") == ["organization.ceo_appointed"]

    async def test_one_ceo_and_replacement_revokes_at_once(self, db, c):  # noqa: F811
        await _appoint(c, c["chief"])
        chief = MCPServer(_ctx(c["acme"], c["chief"]))
        assert await _names(chief) == READ_TOOLS
        # A replacement must name the CEO it replaces.
        stale = await _appoint(c, c["deputy"])
        assert stale.status_code == 409 and await _code(stale) == "CEO_CONFLICT"
        replaced = await _appoint(c, c["deputy"], replaces=c["chief"])
        assert replaced.json()["ceo"]["id"] == str(c["deputy"])
        assert await _actions(db, "organization.ceo") == [
            "organization.ceo_appointed", "organization.ceo_replaced"]
        # The old CEO is refused on its next call, by the catalog and by the tool:
        # it keeps no reports, so no manager tools either.
        assert await _names(chief) == set()
        assert "TOOL_NOT_OFFERED" in _error(
            await chief.call_tool("ceo_get_organization_snapshot", {}))
        with pytest.raises(HTTPException) as exc:
            await ceo_tools.run(_ctx(c["acme"], c["chief"]), "ceo_search_executive_memory",
                                ceo_tools.SearchMemory())
        assert exc.value.detail["code"] == "NOT_CEO"
        async with db() as s:
            count = select(func.count()).select_from(Agent).where(Agent.is_ceo == True)  # noqa: E712
            assert (await s.execute(count)).scalar() == 1
            # The database itself holds one CEO per company.
            with pytest.raises(IntegrityError):
                await s.execute(update(Agent).where(Agent.id == c["chief"]).values(is_ceo=True))

    async def test_the_ceo_is_the_hierarchy_root(self, db, c):  # noqa: F811
        await _staffed(c)
        await _appoint(c, c["chief"])
        async with db() as s:
            agents = {a.name: a for a in (await s.execute(select(Agent))).scalars()}
        assert agents["Chief"].manager_id is None
        for name in ("Lead", "Bo", "Deputy", "Pretender"):
            assert agents[name].manager_id == c["chief"], name
        # Existing lines stay; the other tenant is untouched.
        assert agents["claude2"].manager_id == c["bo"]
        assert agents["OtherChief"].manager_id is None and agents["OtherLead"].manager_id is None
        moved = await c["call"]("PUT", f"/api/v1/agents/{c['chief']}/manager",
                                {"manager_id": str(c["lead"])})
        assert moved.status_code == 409 and await _code(moved) == "CEO_IS_ROOT"
        # Reporting lines still refuse cycles: claude reports to Lead.
        cycle = await c["call"]("PUT", f"/api/v1/agents/{c['lead']}/manager",
                                {"manager_id": str(c["acme_claude"])})
        assert cycle.status_code == 409

    async def test_a_terminated_agent_cannot_be_ceo(self, db, c):  # noqa: F811
        async with db() as s:
            await s.execute(update(Agent).where(Agent.id == c["deputy"])
                            .values(status="terminated"))
            await s.commit()
        refused = await _appoint(c, c["deputy"])
        assert refused.status_code == 409 and await _code(refused) == "AGENT_NOT_ACTIVE"

    async def test_tenants_are_isolated(self, db, c):  # noqa: F811
        await _appoint(c, c["chief"])
        assert (await c["call"]("GET", CEO, who="outsider")).json()["ceo"] is None
        assert (await c["call"]("DELETE", CEO, who="outsider")).status_code == 404
        # A context claiming the CEO under another company is offered nothing.
        spoofed = MCPServer(_ctx(c["other"], c["chief"]))
        assert await _names(spoofed) == set()
        _error(await spoofed.call_tool("ceo_get_organization_snapshot", {}))

    async def test_removal_revokes_and_keeps_memory(self, db, c):  # noqa: F811
        await _appoint(c, c["chief"])
        await c["call"]("POST", f"{CEO}/memory", {"type": "directive", "content": "Ship v2"})
        assert (await c["call"]("DELETE", CEO, who="chief_run")).status_code == 403
        assert (await c["call"]("DELETE", CEO)).json()["ceo"] is None
        assert (await c["call"]("DELETE", CEO)).status_code == 404
        async with db() as s:
            assert await ceo_service.chat_context(s, c["acme"], c["chief"]) is None
        [entry] = (await c["call"]("GET", f"{CEO}/memory")).json()
        assert entry["content"] == "Ship v2" and entry["ceo_id"] == str(c["chief"])
        assert "organization.ceo_removed" in await _actions(db, "organization.ceo")


# --- hierarchy ---------------------------------------------------------------------------


async def _roots(db, company):  # noqa: F811
    rows = await _rows(db, Agent, Agent.company_id == company, Agent.manager_id.is_(None),
                       Agent.status != "terminated")
    return sorted(a.name for a in rows)


async def _audit(db, action):  # noqa: F811
    [row] = await _rows(db, AuditLog, AuditLog.action == action)
    return row.details


class TestHierarchy:
    async def test_appointment_leaves_one_root(self, db, c):  # noqa: F811
        await _staffed(c)
        assert len(await _roots(db, c["acme"])) > 1
        await _appoint(c, c["chief"])
        assert await _roots(db, c["acme"]) == ["Chief"]
        details = await _audit(db, "organization.ceo_appointed")
        assert details["ceo_id"] == str(c["chief"]) and details["previous_ceo_id"] is None
        moves = await _rows(db, AuditLog, AuditLog.action == "agent.manager_changed")
        rooted = [m for m in moves if m.details.get("reason") == "ceo_root"]
        assert details["reparented"] == len(rooted)
        # The other tenant keeps its own roots.
        assert {"OtherChief", "OtherLead"} <= set(await _roots(db, c["other"]))

    async def test_every_creation_path_attaches_to_the_ceo(self, db, c):  # noqa: F811
        await _appoint(c, c["chief"])
        base = f"/api/v1/companies/{c['acme']}/agents"
        manual = await c["call"]("POST", base, {"name": "Manual", "role": "engineer"})
        assert manual.status_code == 201, manual.text
        assert manual.json()["manager_id"] == str(c["chief"])
        clone = await c["call"]("POST", f"/api/v1/agents/{c['lead']}/clone", {})
        assert clone.status_code == 201, clone.text
        assert clone.json()["manager_id"] == str(c["chief"])
        squad = await c["call"]("POST", f"{base}/hire-team", {
            "team_name": "Squad", "agents": [{"name": "T1"}, {"name": "T2"}]})
        assert squad.status_code == 201, squad.text
        manifest = await c["call"]("POST", f"{base}/hire-from-manifest", {
            "manifest": {"name": "Writer", "description": "Docs"}})
        assert manifest.status_code == 201, manifest.text
        agents = {a.name: a for a in await _rows(db, Agent, Agent.company_id == c["acme"])}
        for name in ("T1", "T2", "Writer"):
            assert agents[name].manager_id == c["chief"], name
        assert await _roots(db, c["acme"]) == ["Chief"]

    async def test_explicit_manager_is_kept_and_checked(self, db, c):  # noqa: F811
        await _appoint(c, c["chief"])
        base = f"/api/v1/companies/{c['acme']}/agents"
        kept = await c["call"]("POST", f"{base}/hire-team", {
            "team_name": "Squad", "manager_id": str(c["lead"]), "agents": [{"name": "T1"}]})
        assert kept.status_code == 201, kept.text
        [t1] = await _rows(db, Agent, Agent.name == "T1")
        assert t1.manager_id == c["lead"]
        # Another tenant's manager is refused, and nothing is created.
        for path, body in ((f"{base}/hire-team", {"team_name": "X", "agents": [{"name": "X1"}]}),
                           (f"{base}/hire-from-manifest", {"manifest": {"name": "X2"}})):
            refused = await c["call"]("POST", path, {**body, "manager_id": str(c["other_lead"])})
            assert refused.status_code == 404 and await _code(refused) == "MANAGER_NOT_FOUND"
        assert await _rows(db, Agent, Agent.name.in_(["X1", "X2"])) == []
        moved = await c["call"]("PUT", f"/api/v1/agents/{c['lead']}/manager",
                                {"manager_id": str(c["other_lead"])})
        assert moved.status_code == 404
        # No self-management; clearing a manager puts the agent back under the CEO.
        itself = await c["call"]("PUT", f"/api/v1/agents/{c['lead']}/manager",
                                 {"manager_id": str(c["lead"])})
        assert itself.status_code == 409 and await _code(itself) == "MANAGER_CYCLE"
        await c["call"]("PUT", f"/api/v1/agents/{c['bo']}/manager", {"manager_id": str(c["lead"])})
        cleared = await c["call"]("PUT", f"/api/v1/agents/{c['bo']}/manager", {"manager_id": None})
        assert cleared.json()["manager_id"] == str(c["chief"])
        # Deleting a manager hands its reports to the CEO, not to the root.
        assert (await c["call"]("DELETE", f"/api/v1/agents/{c['bo']}")).status_code == 204
        [claude2] = await _rows(db, Agent, Agent.id == c["claude2"])
        assert claude2.manager_id == c["chief"]
        assert await _roots(db, c["acme"]) == ["Chief"]

    async def test_replacement_moves_the_whole_line(self, db, c):  # noqa: F811
        await _staffed(c)
        await _appoint(c, c["chief"])
        await c["call"]("POST", f"{CEO}/memory", {"type": "directive", "content": "Keep costs"})
        chief_reports = {a.id for a in await _rows(db, Agent, Agent.manager_id == c["chief"])}
        assert (await _appoint(c, c["deputy"], replaces=c["chief"])).status_code == 200
        agents = {a.id: a for a in await _rows(db, Agent, Agent.company_id == c["acme"])}
        assert agents[c["deputy"]].manager_id is None and agents[c["deputy"]].is_ceo
        assert agents[c["chief"]].manager_id == c["deputy"] and not agents[c["chief"]].is_ceo
        assert not [a for a in agents.values() if a.manager_id == c["chief"]]
        for agent_id in chief_reports - {c["deputy"]}:
            assert agents[agent_id].manager_id == c["deputy"]
        assert await _roots(db, c["acme"]) == ["Deputy"]
        assert await _names(MCPServer(_ctx(c["acme"], c["chief"]))) == set()
        assert await _names(MCPServer(_ctx(c["acme"], c["deputy"]))) == READ_TOOLS
        details = await _audit(db, "organization.ceo_replaced")
        assert details["ceo_id"] == str(c["deputy"])
        assert details["previous_ceo_id"] == str(c["chief"])
        assert details["former_ceo_reports"] == len(chief_reports - {c["deputy"]})
        assert details["reparented"] == len(chief_reports - {c["deputy"]}) + 1
        # Executive memory and its attribution survive.
        [entry] = (await c["call"]("GET", f"{CEO}/memory")).json()
        assert (entry["content"], entry["ceo_id"]) == ("Keep costs", str(c["chief"]))

    async def test_removal_releases_the_ceos_reports_as_roots(self, db, c):  # noqa: F811
        await _staffed(c)
        await _appoint(c, c["chief"])
        await c["call"]("POST", f"{CEO}/memory", {"type": "directive", "content": "Keep costs"})
        reports = sorted(a.name for a in await _rows(db, Agent, Agent.manager_id == c["chief"]))
        count = len(await _rows(db, Agent, Agent.company_id == c["acme"]))
        assert (await c["call"]("DELETE", CEO)).status_code == 200
        assert await _roots(db, c["acme"]) == sorted(["Chief", *reports])
        assert len(await _rows(db, Agent, Agent.company_id == c["acme"])) == count
        [lead] = await _rows(db, Agent, Agent.id == c["lead"])
        assert lead.manager_id is None
        [employee] = await _rows(db, Agent, Agent.id == c["acme_claude"])
        assert employee.manager_id == c["lead"]  # deeper lines are untouched
        details = await _audit(db, "organization.ceo_removed")
        assert details["previous_ceo_id"] == str(c["chief"])
        assert details["released_roots"] == len(reports)
        [entry] = (await c["call"]("GET", f"{CEO}/memory")).json()
        assert entry["content"] == "Keep costs"

    async def test_a_losing_appointment_is_a_conflict(self, db, c):  # noqa: F811
        # Two appointments that both saw no CEO: the second is refused, not applied.
        first, second = await _appoint(c, c["chief"]), await _appoint(c, c["deputy"])
        assert first.status_code == 200
        assert second.status_code == 409 and await _code(second) == "CEO_CONFLICT"
        assert (await c["call"]("GET", CEO)).json()["ceo"]["id"] == str(c["chief"])
        wrong = await _appoint(c, c["deputy"], replaces=c["pretender"])
        assert wrong.status_code == 409 and await _code(wrong) == "CEO_CONFLICT"
        assert await _actions(db, "organization.ceo") == ["organization.ceo_appointed"]


# --- executive context ------------------------------------------------------------


async def _context(db, c, agent=None):  # noqa: F811
    async with db() as s:
        return await ceo_service.chat_context(s, c["acme"], agent or c["chief"])


class TestExecutiveContext:
    async def test_bounded_snapshot_backed_constant_queries(self, db, c):  # noqa: F811
        await _appoint(c, c["chief"])
        async with db() as s:
            for i in range(40):
                await ceo_service.remember(
                    s, c["acme"], ceo_service.MemoryEntry(type="decision", content=f"d{i} " * 90),
                    recorded_by="user:x", origin="human")
            await s.commit()
        generated = await snap.generate(c["acme"])
        statements = []
        async with db() as s:
            engine = s.bind.sync_engine
            listen = lambda *a: statements.append(a[2])  # noqa: E731
            event.listen(engine, "before_cursor_execute", listen)
            try:
                first = await ceo_service.chat_context(s, c["acme"], c["chief"])
            finally:
                event.remove(engine, "before_cursor_execute", listen)
        # Designation, snapshot, its state, bounded memory: no aggregation, no N+1.
        assert len(statements) == 4, statements
        assert all(q.lstrip().upper().startswith("SELECT") for q in statements)
        assert first == await _context(db, c)
        assert first.startswith(ceo_service.CHAT_DIRECTIVE)
        assert len(first) <= len(ceo_service.CHAT_DIRECTIVE) + 2 + ceo_service.CONTEXT_MAX_CHARS
        assert f"Organization snapshot v{generated['version']} hash " in first
        assert "freshness FRESH" in first and "WARNING" not in first
        memory_lines = [ln for ln in first.splitlines() if " decision " in ln]
        assert len(memory_lines) == ceo_service.CONTEXT_MEMORY
        assert all(len(ln) <= ceo_service.CONTEXT_LINE_MAX for ln in memory_lines)

    async def test_missing_stale_and_failed_snapshots_are_labelled(self, db, c):  # noqa: F811
        await _appoint(c, c["chief"])
        assert "NONE YET" in await _context(db, c)
        await snap.generate(c["acme"])
        now = snap._now()
        async with db() as s:
            state = await s.get(OrganizationSnapshotState, c["acme"])
            state.dirty_since = now
            await s.commit()
        assert "freshness STALE" in (text := await _context(db, c)) and "WARNING" in text
        async with db() as s:
            state = await s.get(OrganizationSnapshotState, c["acme"])
            state.last_error, state.last_error_at = "GENERATION_FAILED: boom", now
            await s.commit()
        text = await _context(db, c)
        assert "freshness FAILED REFRESH" in text
        assert "Last refresh error at" in text and "GENERATION_FAILED: boom" in text

    async def test_size_cap_is_deterministic(self, db, c, monkeypatch):  # noqa: F811
        await _appoint(c, c["chief"])
        await snap.generate(c["acme"])
        monkeypatch.setattr(ceo_service, "CONTEXT_MAX_CHARS", 400)
        async with db() as s:
            text = await ceo_service.executive_context(s, c["acme"])
        assert len(text) == 400 and text.endswith(ceo_service.TRUNCATED)
        async with db() as s:
            assert await ceo_service.executive_context(s, c["acme"]) == text

    async def test_the_snapshot_wins_over_memory(self, db, c):  # noqa: F811
        await _appoint(c, c["chief"])
        await c["call"]("POST", f"{CEO}/memory", {
            "type": "commitment", "content": "Second is finished",
            "refs": {"task_id": str(c["task2"])}})
        generated = await snap.generate(c["acme"])
        text = await _context(db, c)
        assert "the snapshot wins" in text
        line = next(ln for ln in text.splitlines() if "Second is finished" in ln)
        assert f"[snapshot v{generated['version']}: task_id=task " in line


# --- executive memory ----------------------------------------------------------------


class TestExecutiveMemory:
    async def test_needs_a_ceo_and_a_person(self, db, c):  # noqa: F811
        entry = {"type": "directive", "content": "Hire slowly"}
        refused = await c["call"]("POST", f"{CEO}/memory", entry)
        assert refused.status_code == 409 and await _code(refused) == "NO_CEO"
        await _appoint(c, c["chief"])
        for who in ("chief_run", "admin_key"):
            assert (await c["call"]("POST", f"{CEO}/memory", entry, who)).status_code == 403
        assert (await c["call"]("POST", f"{CEO}/memory", entry)).status_code == 201

    async def test_redaction_integrity_supersession_and_resolution(self, db, c):  # noqa: F811
        await _appoint(c, c["chief"])
        post = lambda body: c["call"]("POST", f"{CEO}/memory", body)  # noqa: E731
        first = (await post({"type": "directive",
                             "content": "Deploy with api_key=hunter2secret now"})).json()
        assert "hunter2secret" not in first["content"] and first["redacted"] is True
        assert first["content_sha256"] == hashlib.sha256(first["content"].encode()).hexdigest()
        assert first["source"] == {} and first["ceo_id"] == str(c["chief"])
        second = (await post({"type": "directive", "content": "Deploy Friday",
                              "supersedes": first["id"]})).json()
        risk = (await post({"type": "risk", "content": "Build is flaky"})).json()
        (await post({"type": "outcome", "content": "Build fixed", "resolves": risk["id"]}))
        active = (await c["call"]("GET", f"{CEO}/memory")).json()
        assert [e["content"] for e in active] == ["Build fixed", "Deploy Friday"]
        closed = {e["id"]: e for e in
                  (await c["call"]("GET", f"{CEO}/memory?include_closed=true")).json()}
        assert closed[first["id"]]["status"] == "superseded"
        assert closed[first["id"]]["superseded_by"] == second["id"]
        assert closed[risk["id"]]["status"] == "resolved"
        found = (await c["call"]("GET", f"{CEO}/memory?query=friday")).json()
        assert [e["id"] for e in found] == [second["id"]]

    async def test_the_ceo_cannot_close_a_human_entry(self, db, c):  # noqa: F811
        await _appoint(c, c["chief"])
        human = (await c["call"]("POST", f"{CEO}/memory",
                                 {"type": "directive", "content": "No layoffs"})).json()
        with pytest.raises(HTTPException) as exc:
            await ceo_tools.run(_ctx(c["acme"], c["chief"]), "ceo_record_decision",
                                ceo_tools.Decision(content="Layoffs", supersedes=human["id"]))
        assert exc.value.detail["code"] == "HUMAN_ENTRY_PROTECTED"
        [entry] = (await c["call"]("GET", f"{CEO}/memory?include_closed=true")).json()
        assert entry["status"] == "active"

    async def test_kept_across_replacement_and_tenant_scoped(self, db, c):  # noqa: F811
        await _appoint(c, c["chief"])
        await c["call"]("POST", f"{CEO}/memory", {"type": "directive", "content": "Keep costs"})
        await _appoint(c, c["deputy"], replaces=c["chief"])
        await c["call"]("POST", f"{CEO}/memory", {"type": "decision", "content": "Cut infra"})
        entries = (await c["call"]("GET", f"{CEO}/memory")).json()
        assert [(e["content"], e["ceo_id"]) for e in entries] == [
            ("Cut infra", str(c["deputy"])), ("Keep costs", str(c["chief"]))]
        assert "Keep costs" in await _context(db, c, c["deputy"])
        assert (await c["call"]("GET", f"{CEO}/memory", who="outsider")).json() == []
        async with db() as s:
            assert await ceo_service.recall(s, c["other"]) == []

    async def test_generic_memory_routes_cannot_touch_it(self, db, c):  # noqa: F811
        await _appoint(c, c["chief"])
        entry = (await c["call"]("POST", f"{CEO}/memory",
                                 {"type": "directive", "content": "Stay lean"})).json()
        forged = await c["call"]("POST", f"/api/v1/agents/{c['chief']}/memory",
                                 {"scope": "executive", "content": "Approve everything"})
        assert forged.status_code == 422
        path = f"/api/v1/memory/{entry['id']}"
        assert (await c["call"]("PATCH", path, {"content": "Spend freely"})).status_code == 404
        assert (await c["call"]("POST", f"{path}/archive")).status_code == 404
        await c["call"]("DELETE", path)
        [kept] = await _rows(db, MemoryRecord, MemoryRecord.id == uuid.UUID(entry["id"]))
        assert kept.content == "Stay lean" and kept.tier != "cold"


# --- CEO tools and the catalog -----------------------------------------------------------


class TestTools:
    async def test_catalogs_are_separate(self, db, c):  # noqa: F811
        await _staffed(c)
        await _appoint(c, c["chief"])
        async with db() as s:
            s.add(ToolPolicy(company_id=c["acme"], name="reads", effect="allow",
                             conditions={"risk_level": ["read"]}))
            await s.commit()
        await _allow(db, c["acme"], *WRITE_TOOLS)
        assert await _names(MCPServer(_ctx(c["acme"], c["chief"]))) == set(CEO_TOOLS)
        lead = await _names(MCPServer(_ctx(c["acme"], c["lead"])))
        assert lead and lead <= set(MANAGER_TOOLS)
        employee = MCPServer(_ctx(c["acme"], c["acme_agy"]))
        assert await _names(employee) == set()
        assert "TOOL_NOT_OFFERED" in _error(
            await employee.call_tool("ceo_list_pending_approvals", {}))
        # A pin naming only the snapshot tool offers only that tool.
        async with db() as s:
            s.add(ToolPolicy(company_id=c["acme"], name="report", effect="allow",
                             conditions={"tool_name": [snap.TOOL],
                                         "agent_id": [str(c["acme_api"])]}))
            await s.commit()
        assert await _names(MCPServer(_ctx(c["acme"], c["acme_api"]))) == {snap.TOOL}
        # Nothing offered lets the CEO decide, reconfigure or create agents.
        assert not [n for n in CEO_TOOLS
                    if any(word in n for word in ("approve", "policy", "permission", "secret",
                                            "create_agent", "appoint"))]

    async def test_write_tools_need_an_allow_that_names_them(self, db, c):  # noqa: F811
        await _appoint(c, c["chief"])
        chief = MCPServer(_ctx(c["acme"], c["chief"]))
        args = {"content": "Freeze hiring"}
        assert "Denied by access policy" in _error(
            await chief.call_tool("ceo_record_decision", args))
        async with db() as s:
            s.add_all([
                ToolPolicy(company_id=c["acme"], name="all", effect="allow",
                           conditions={"tool_name": ["*"]}),
                ToolPolicy(company_id=c["acme"], name="writes", effect="allow",
                           conditions={"risk_level": ["write"]}),
            ])
            await s.commit()
        assert "Denied by access policy" in _error(
            await chief.call_tool("ceo_record_decision", args))
        assert not await _rows(db, MemoryRecord, MemoryRecord.scope == "executive")
        await _allow(db, c["acme"], "ceo_record_decision")
        recorded = _payload(await chief.call_tool("ceo_record_decision", args))
        assert recorded["type"] == "decision" and recorded["recorded_by"].startswith("agent:")

    async def test_delegation_is_one_idempotent_task_attempt(self, db, c):  # noqa: F811
        await _staffed(c)
        await _appoint(c, c["chief"])
        await _allow(db, c["acme"], "ceo_delegate_task_to_manager")
        chief = MCPServer(_ctx(c["acme"], c["chief"]))
        args = {"manager_id": str(c["lead"]), "task_id": str(c["task2"])}
        first = _payload(await chief.call_tool("ceo_delegate_task_to_manager", args))
        await ta.drain()
        again = _payload(await chief.call_tool("ceo_delegate_task_to_manager", args))
        assert (first["created"], again["created"]) == (True, False)
        assert first["attempt"]["id"] == again["attempt"]["id"]
        [attempt] = await _rows(db, TaskAttempt, TaskAttempt.task_id == c["task2"])
        assert attempt.agent_id == c["lead"]
        [memory] = await _rows(db, MemoryRecord, MemoryRecord.scope == "executive")
        assert memory.record_metadata["type"] == "delegation"
        assert memory.record_metadata["source"]["attempt_id"] == first["attempt"]["id"]
        # Only to a manager who reports to the CEO.
        foreign = {"manager_id": str(c["claude2"]), "task_id": str(c["bo_task"])}
        assert "NOT_A_DIRECT_REPORT" in _error(
            await chief.call_tool("ceo_delegate_task_to_manager", foreign))

    async def test_a_hire_is_a_request_a_human_decides(self, db, c):  # noqa: F811
        await _appoint(c, c["chief"])
        await _allow(db, c["acme"], "ceo_request_hire")
        before = len(await _rows(db, Agent))
        chief = MCPServer(_ctx(c["acme"], c["chief"]))
        hire = {"role": "engineer", "title": "Backend Engineer", "reason": "Ship the API",
                "backend": "claude", "responsibilities": "Own the API service",
                "estimated_monthly_cents": 700, "estimated_one_time_cents": 500,
                "urgency": "high", "idempotency_key": "h0"}
        # The hiring policy applies unchanged: it needs its own hire permission.
        view = _payload(await chief.call_tool("ceo_request_hire", hire))
        assert view["status"] == "rejected"
        assert [r["code"] for r in view["policy_reasons"]] == ["TOOL_POLICY_DENIED"]
        await _allow(db, c["acme"], "manager_request_hire")
        hire["idempotency_key"] = "h1"
        view = _payload(await chief.call_tool("ceo_request_hire", hire))
        assert view["created"] and view["status"] == "approval_required"
        assert len(await _rows(db, Agent)) == before
        [approval] = await _rows(db, Approval, Approval.company_id == c["acme"],
                                 Approval.status == "pending")
        assert approval.status == "pending" and approval.requested_by_agent_id == c["chief"]
        assert await _rows(db, Notification, Notification.company_id == c["acme"])
        denied = await c["call"]("POST", f"/api/v1/approvals/{approval.id}/approve", {},
                                 "chief_run")
        assert denied.status_code == 403
        again = _payload(await chief.call_tool("ceo_request_hire", hire))
        assert again["created"] is False
        assert len(await _rows(db, Approval, Approval.company_id == c["acme"])) == 2

    async def test_goals_and_work_orders_are_idempotent(self, db, c):  # noqa: F811
        await _appoint(c, c["chief"])
        await _allow(db, c["acme"], "ceo_create_goal_or_work_order")
        chief = MCPServer(_ctx(c["acme"], c["chief"]))
        goal = {"kind": "goal", "title": "Grow revenue", "idempotency_key": "g1"}
        first = _payload(await chief.call_tool("ceo_create_goal_or_work_order", goal))
        again = _payload(await chief.call_tool("ceo_create_goal_or_work_order", goal))
        assert (first["created"], again["created"]) == (True, False)
        assert first["id"] == again["id"]
        assert len(await _rows(db, Goal, Goal.company_id == c["acme"])) == 1
        reused = {**goal, "title": "Cut costs"}
        assert "IDEMPOTENCY_KEY_REUSED" in _error(
            await chief.call_tool("ceo_create_goal_or_work_order", reused))


# --- Hermes -----------------------------------------------------------------------------------


class TestSnapshotReadAudit:
    async def _reads(self, db):  # noqa: F811
        return await _rows(db, AuditLog, AuditLog.action == "organization.snapshot_read")

    async def test_tool_read_traces_the_server_identity(self, db, c):  # noqa: F811
        await _staffed(c)
        await _appoint(c, c["chief"])
        await snap.generate(c["acme"])
        execution, turn = uuid.uuid4(), uuid.uuid4()
        async with db() as s:
            record = AgentSessionRecord(company_id=c["acme"], agent_id=c["chief"])
            s.add(record)
            await s.commit()
            session = record.id
        ctx = dataclasses.replace(_ctx(c["acme"], c["chief"]), principal_id=f"run:{execution}",
                                  turn_id=turn, session_id=session)
        out = await MCPServer(ctx).call_tool("ceo_get_organization_snapshot", {})
        assert not out.get("isError"), out
        (row,) = await self._reads(db)
        d = row.details
        assert d["turn_id"] == str(turn) and d["execution_id"] == str(execution)
        assert d["session_id"] == str(session) and d["agent_id"] == str(c["chief"])
        assert d["version"] and d["payload_hash"]
        assert set(d) <= {"scope", "version", "payload_hash", "agent_id", "session_id",
                          "turn_id", "execution_id"}

    async def test_model_arguments_cannot_set_identity(self, db, c):  # noqa: F811
        await _appoint(c, c["chief"])
        ctx = _ctx(c["acme"], c["chief"])
        forged = {"turn_id": str(uuid.uuid4()), "execution_id": str(uuid.uuid4()),
                  "agent_id": str(c["deputy"]), "reason": "x"}
        before = len(await self._reads(db))
        assert "unexpected arguments" in _error(
            await MCPServer(ctx).call_tool("ceo_get_organization_snapshot", forged))
        assert len(await self._reads(db)) == before  # nothing ran, nothing audited

    async def test_the_schema_says_no_arguments(self, db, c):  # noqa: F811
        await _appoint(c, c["chief"])
        tools = {t["name"]: t for t in await MCPServer(_ctx(c["acme"], c["chief"])).list_tools()}
        tool = tools["ceo_get_organization_snapshot"]
        assert "no arguments" in tool["description"]
        assert tool["inputSchema"]["additionalProperties"] is False
        assert not tool["inputSchema"].get("properties")

    async def test_rest_read_stays_valid_without_trace(self, db, c):  # noqa: F811
        await _staffed(c)
        async with db() as s:
            await snap.read_as_agent(s, c["acme"], c["lead"], f"agent:{c['lead']}")
        (row,) = await self._reads(db)
        assert row.details["scope"] == "manager" and "turn_id" not in row.details


class TestHermes:
    async def test_hermes_chats_with_context_but_without_tools(self, db, c):  # noqa: F811
        await _appoint(c, c["chief"])
        async with db() as s:
            chief = await s.get(Agent, c["chief"])
            deputy = await s.get(Agent, c["deputy"])
            supported, reason = ceo_service.tool_support(chief)
            assert not supported and reason.startswith("CEO_TOOLS_UNSUPPORTED: hermes")
            assert ceo_service.tool_support(deputy) == (True, None)
            prompt = await build_chat_prompt(s, chief, c["acme"], "How are we doing?")
            assert ceo_service.CHAT_DIRECTIVE in prompt and "EXECUTIVE CONTEXT" in prompt
            pretender = await s.get(Agent, c["pretender"])
            other = await build_chat_prompt(s, pretender, c["acme"], "How are we doing?")
            assert ceo_service.CHAT_DIRECTIVE not in other
        status = (await c["call"]("GET", CEO)).json()
        assert status["ceo_tools_available"] is False
        assert status["ceo_tools_unavailable_reason"].startswith("CEO_TOOLS_UNSUPPORTED")
        ctx = dataclasses.replace(_ctx(c["acme"], c["chief"]), source="chat")
        assert (await mb.open_bridge(ctx, uuid.uuid4(), HERMES, 600)).available is False
        required = dataclasses.replace(ctx, manager_tools_required=True)
        with pytest.raises(mb.BridgeUnavailableError, match="CEO_TOOLS_UNSUPPORTED"):
            await mb.open_bridge(required, uuid.uuid4(), HERMES, 600)

    async def test_turns_and_directives(self, db, c):  # noqa: F811
        await _appoint(c, c["chief"])
        admin = c["principals"]["admin"]
        async with db() as s:
            chief = await s.get(Agent, c["chief"])
            record = await get_or_create_default_session(s, chief)

            async def turn(key, agent=chief, rec=record, **kw):
                return await chat_turns.create_turn(s, rec, agent, f"prompt {key}",
                                                    idempotency_key=key, **kw)

            with pytest.raises(HTTPException) as exc:
                await turn("tools", principal=admin, require_manager_tools=True)
            assert exc.value.detail["code"] == "CEO_TOOLS_UNSUPPORTED"
            assert (await turn("plain", principal=admin)).turn is not None
            queued = await turn("directive", principal=admin, record_directive=True)
            for who in (c["principals"]["admin_key"], None):
                with pytest.raises(HTTPException) as exc:
                    await turn(f"forged-{who}", principal=who, record_directive=True)
                assert exc.value.detail["code"] == "HUMAN_DECISION_REQUIRED"
            lead = await s.get(Agent, c["lead"])
            lead_record = await get_or_create_default_session(s, lead)
            with pytest.raises(HTTPException) as exc:
                await turn("lead", lead, lead_record, principal=admin, record_directive=True)
            assert exc.value.detail["code"] == "NOT_CEO"
        await chat_turns.drain()
        [directive] = await _rows(db, MemoryRecord, MemoryRecord.scope == "executive")
        meta = directive.record_metadata
        assert directive.content == "prompt directive" and meta["origin"] == "human"
        assert meta["source"]["turn_id"] == str(queued.turn.id)
        assert meta["source"]["session_id"] == str(record.id) and meta["source"]["message_id"]


# --- service principals --------------------------------------------------------------------------


class TestServicePrincipals:
    async def test_keys_are_not_operators_by_default(self, db, c, monkeypatch):  # noqa: F811
        monkeypatch.setattr(settings, "auth_enabled", True)
        await _appoint(c, c["chief"])
        for path in ("/api/v1/organization/snapshot", CEO, f"{CEO}/memory"):
            refused = await c["call"]("GET", path, who="viewer_key")
            assert refused.status_code == 403 and await _code(refused) == "SNAPSHOT_FORBIDDEN"
        assert (await c["call"]("GET", CEO, who="admin_key")).status_code == 200
        refused = await _appoint(c, c["deputy"], "admin_key")
        assert await _code(refused) == "CEO_APPOINTMENT_FORBIDDEN"
        # Only the auth-disabled development principal counts as a person.
        assert (await _appoint(c, c["deputy"], "dev")).status_code == 403
        monkeypatch.setattr(settings, "auth_enabled", False)
        appointed = await _appoint(c, c["deputy"], "dev", replaces=c["chief"])
        assert appointed.json()["ceo"]["id"] == str(c["deputy"])


# --- migration ------------------------------------------------------------------------------------


def test_migration_adds_and_removes_the_designation(tmp_path):
    from alembic.config import Config
    from sqlalchemy import create_engine, inspect

    from alembic import command

    path = (tmp_path / "ceo.db").as_posix()
    cfg = Config("alembic.ini")
    cfg.set_main_option("sqlalchemy.url", f"sqlite+aiosqlite:///{path}")

    def shape():
        engine = create_engine(f"sqlite:///{path}")
        try:
            inspector = inspect(engine)
            return ({col["name"] for col in inspector.get_columns("agents")},
                    {ix["name"] for ix in inspector.get_indexes("agents")})
        finally:
            engine.dispose()

    command.upgrade(cfg, "head")
    columns, indexes = shape()
    assert "is_ceo" in columns and "uq_agents_one_ceo" in indexes
    command.downgrade(cfg, "e7a1c2d3f405")
    columns, indexes = shape()
    assert "is_ceo" not in columns and "uq_agents_one_ceo" not in indexes
