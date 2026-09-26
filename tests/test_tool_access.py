"""MCP/tool binding enforcement (ws05): the access matrix and every adapter path.

``check_tool_access`` is exercised directly against a real SQLite database for
the decision matrix. The adapter tests then go through each adapter's own
dispatch entry point, because the failure mode being guarded against is a
correct check with no caller: each must refuse what the check refuses and
leave a ``tool_invocations`` row (plus an ``audit_log`` entry for anything
other than ``allowed``).
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlmodel import SQLModel, select

import nexus.models  # noqa: F401 -- registers every table on SQLModel.metadata
from nexus.adapters.hermes_adapter import HermesAdapter
from nexus.adapters.mcp_adapter import MCPAgentAdapter
from nexus.config import settings
from nexus.models.agent import Agent
from nexus.models.agent_session import AgentSessionRecord
from nexus.models.company import Company
from nexus.models.governance import AuditLog
from nexus.models.mcp_binding import McpBinding
from nexus.models.tool import (
    ToolCatalogEntry,
    ToolConnection,
    ToolPolicy,
    ToolProfile,
    ToolProfileBinding,
)
from nexus.models.tool_invocation import ToolInvocation
from nexus.runtime.adapter import AgentSession
from nexus.tools.access import ALLOWED, DENIED, WOULD_DENY, check_tool_access
from nexus.tools.context import ExecutionContext
from nexus.tools.mcp_client import MCPResult

URL = "https://mcp.acme.test/rpc"
FOREIGN_URL = "https://mcp.other.test/rpc"


@pytest.fixture
async def factory(tmp_path, monkeypatch):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'access.db'}")
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)
    maker = async_sessionmaker(engine, expire_on_commit=False)

    import nexus.database as database

    monkeypatch.setattr(database, "async_session_factory", maker)
    monkeypatch.setattr(settings, "tool_binding_enforcement", "audit")
    yield maker
    await engine.dispose()


@pytest.fixture
async def t(factory):
    """Two companies. Acme: agents A and B, sessions S1/S2 of A, connections C
    and C2 with catalogs. Other: an agent and connection FC."""
    acme, other = Company(name="Acme"), Company(name="Other")
    async with factory() as db:
        db.add_all([acme, other])
        await db.flush()
        a = Agent(company_id=acme.id, name="A", role="engineer")
        b = Agent(company_id=acme.id, name="B", role="engineer")
        foreign = Agent(company_id=other.id, name="F", role="engineer")
        db.add_all([a, b, foreign])
        await db.flush()
        s1 = AgentSessionRecord(company_id=acme.id, agent_id=a.id)
        s2 = AgentSessionRecord(company_id=acme.id, agent_id=a.id)
        c = ToolConnection(company_id=acme.id, name="c", transport_type="mcp_remote",
                           endpoint_url=URL)
        c2 = ToolConnection(company_id=acme.id, name="c2", transport_type="mcp_remote",
                            endpoint_url="https://mcp2.acme.test/rpc")
        fc = ToolConnection(company_id=other.id, name="fc", transport_type="mcp_remote",
                            endpoint_url=FOREIGN_URL)
        db.add_all([s1, s2, c, c2, fc])
        await db.flush()
        for conn in (c, c2, fc):
            db.add_all([
                ToolCatalogEntry(company_id=conn.company_id, connection_id=conn.id,
                                 tool_name="search", risk_level="read"),
                ToolCatalogEntry(company_id=conn.company_id, connection_id=conn.id,
                                 tool_name="delete_repo", risk_level="destructive"),
            ])
        await db.commit()
    return {
        "acme": acme.id, "other": other.id, "a": a.id, "b": b.id, "foreign": foreign.id,
        "s1": s1.id, "s2": s2.id, "c": c.id, "c2": c2.id, "fc": fc.id,
    }


async def bind(factory, t, *, connection="c", company="acme", **fields: Any) -> uuid.UUID:
    target = {"target_type": "session"} if "session_id" in fields else {
        "target_type": "agent", "agent_id": fields.pop("agent_id", t["a"])
    }
    async with factory() as db:
        binding = McpBinding(company_id=t[company], connection_id=t[connection], **target, **fields)
        db.add(binding)
        await db.commit()
    return binding.id


def ctx(t, *, company="acme", agent="a", session=None, role="agent", source="test"):
    """A server-built context for agent ``agent`` of ``company``."""
    return ExecutionContext(
        company_id=t[company],
        principal_id=f"agent:{t[agent]}",
        principal_role=role,
        source=source,
        agent_id=t[agent],
        session_id=t[session] if session else None,
    )


async def check(factory, t, **kw: Any):
    context = ExecutionContext(
        company_id=kw.pop("company_id", t["acme"]),
        principal_id="test",
        principal_role=kw.pop("principal_role", "agent"),
        source=kw.pop("source", "test"),
        agent_id=kw.pop("agent_id", t["a"]),
        session_id=kw.pop("session_id", None),
    )
    kw.setdefault("tool_name", "search")
    if "endpoint_url" not in kw:
        kw.setdefault("connection_id", t["c"])
    kw.setdefault("enforcement", "audit")
    async with factory() as db:
        return await check_tool_access(db, context, **kw)


def stages(decision) -> set[str]:
    return {p["stage"] for p in decision.problems}


class TestMatrix:
    async def test_valid_agent_binding(self, factory, t) -> None:
        binding = await bind(factory, t)
        d = await check(factory, t)
        assert d.outcome == ALLOWED and d.problems == []
        assert d.binding_ids == [str(binding)] and d.connection_id == t["c"]
        assert d.risk_level == "read" and d.company_id == t["acme"]

    async def test_valid_session_binding(self, factory, t) -> None:
        await bind(factory, t, session_id=t["s1"])
        assert (await check(factory, t, session_id=t["s1"])).outcome == ALLOWED

    async def test_missing_binding(self, factory, t) -> None:
        d = await check(factory, t)
        assert d.outcome == WOULD_DENY and stages(d) == {"binding"}
        assert d.allowed  # audit mode: the call still runs
        d = await check(factory, t, enforcement="enforce")
        assert d.outcome == DENIED and not d.allowed

    async def test_disabled_binding(self, factory, t) -> None:
        await bind(factory, t, status="disabled")
        assert (await check(factory, t)).outcome == WOULD_DENY
        assert (await check(factory, t, enforcement="enforce")).outcome == DENIED

    async def test_pending_approval_grants_nothing(self, factory, t) -> None:
        await bind(factory, t, status="pending_approval")
        assert (await check(factory, t, enforcement="enforce")).outcome == DENIED

    async def test_disabled_individual_tool(self, factory, t) -> None:
        await bind(factory, t, disabled_tools=["delete_repo"])
        assert (await check(factory, t)).outcome == ALLOWED
        d = await check(factory, t, tool_name="delete_repo", enforcement="enforce")
        assert d.outcome == DENIED and "disabled by a binding" in d.reason

    async def test_catalog_disabled_tool(self, factory, t) -> None:
        await bind(factory, t)
        async with factory() as db:
            entry = (await db.execute(select(ToolCatalogEntry).where(
                ToolCatalogEntry.connection_id == t["c"], ToolCatalogEntry.tool_name == "search"
            ))).scalar_one()
            entry.is_active = False
            await db.commit()
        d = await check(factory, t, enforcement="enforce")
        assert d.outcome == DENIED and stages(d) == {"catalog"}

    async def test_policy_deny_is_hard_even_with_active_binding(self, factory, t) -> None:
        await bind(factory, t)
        async with factory() as db:
            db.add(ToolPolicy(company_id=t["acme"], name="no destructive", effect="deny",
                              priority=10, conditions={"risk_level": ["destructive"]}))
            await db.commit()
        d = await check(factory, t, tool_name="delete_repo")  # audit mode
        assert d.outcome == DENIED and stages(d) == {"policy"}
        assert (await check(factory, t)).outcome == ALLOWED

    async def test_profile_default_deny(self, factory, t) -> None:
        await bind(factory, t)
        async with factory() as db:
            profile = ToolProfile(company_id=t["acme"], name="locked", default_action="deny")
            db.add(profile)
            await db.flush()
            db.add(ToolProfileBinding(company_id=t["acme"], profile_id=profile.id,
                                      target_type="agent", target_id=t["a"]))
            await db.commit()
        d = await check(factory, t)
        assert d.outcome == DENIED and stages(d) == {"policy"}

    async def test_rbac_deny_is_hard(self, factory, t) -> None:
        await bind(factory, t)
        d = await check(factory, t, principal_role="viewer")
        assert d.outcome == DENIED and stages(d) == {"rbac"}

    async def test_cross_company_binding_grants_nothing(self, factory, t) -> None:
        # A row claiming Other's company on Acme's connection is never in scope.
        await bind(factory, t, company="other")
        d = await check(factory, t, enforcement="enforce")
        assert d.outcome == DENIED and d.binding_ids == []

    async def test_cross_company_connection_is_hard(self, factory, t) -> None:
        await bind(factory, t, connection="fc")
        d = await check(factory, t, connection_id=t["fc"])
        assert d.outcome == DENIED and "another company" in d.reason

    async def test_foreign_endpoint_url_does_not_resolve(self, factory, t) -> None:
        d = await check(factory, t, endpoint_url=FOREIGN_URL)
        assert d.outcome == WOULD_DENY and d.connection_id is None

    async def test_endpoint_url_resolves_own_connection(self, factory, t) -> None:
        await bind(factory, t)
        d = await check(factory, t, endpoint_url=URL)
        assert d.outcome == ALLOWED and d.connection_id == t["c"]

    async def test_forged_company_is_hard(self, factory, t) -> None:
        await bind(factory, t)
        d = await check(factory, t, company_id=t["other"])
        assert d.outcome == DENIED and "agent" in stages(d)

    async def test_session_of_another_agent_is_hard(self, factory, t) -> None:
        await bind(factory, t, agent_id=t["b"])
        d = await check(factory, t, agent_id=t["b"], session_id=t["s1"])
        assert d.outcome == DENIED and "session" in stages(d)

    async def test_inactive_connection(self, factory, t) -> None:
        await bind(factory, t)
        async with factory() as db:
            (await db.get(ToolConnection, t["c"])).is_active = False
            await db.commit()
        assert (await check(factory, t)).outcome == WOULD_DENY
        assert (await check(factory, t, enforcement="enforce")).outcome == DENIED

    async def test_deleted_connection(self, factory, t) -> None:
        d = await check(factory, t, connection_id=uuid.uuid4())
        assert d.outcome == WOULD_DENY and "not a registered" in d.reason

    async def test_unknown_tool_is_unclassified_write(self, factory, t) -> None:
        await bind(factory, t)
        d = await check(factory, t, tool_name="mystery")
        assert d.outcome == WOULD_DENY and d.risk_level == "write" and stages(d) == {"catalog"}

    async def test_unknown_tool_meets_write_policy(self, factory, t) -> None:
        await bind(factory, t)
        async with factory() as db:
            db.add(ToolPolicy(company_id=t["acme"], name="no writes", effect="deny",
                              conditions={"risk_level": ["write", "destructive"]}))
            await db.commit()
        assert (await check(factory, t, tool_name="mystery")).outcome == DENIED

    async def test_multiple_bindings(self, factory, t) -> None:
        agent_binding = await bind(factory, t)
        session_binding = await bind(factory, t, session_id=t["s1"])
        await bind(factory, t, connection="c2")
        d = await check(factory, t, session_id=t["s1"])
        assert d.outcome == ALLOWED
        assert set(d.binding_ids) == {str(agent_binding), str(session_binding)}
        assert (await check(factory, t, connection_id=t["c2"])).outcome == ALLOWED

    async def test_agent_binding_inherited_by_session(self, factory, t) -> None:
        await bind(factory, t)
        assert (await check(factory, t, session_id=t["s1"])).outcome == ALLOWED

    async def test_session_binding_is_scoped_to_its_session(self, factory, t) -> None:
        await bind(factory, t, session_id=t["s1"])
        assert (await check(factory, t, session_id=t["s2"])).outcome == WOULD_DENY
        assert (await check(factory, t)).outcome == WOULD_DENY

    async def test_conflict_disabled_session_binding_wins(self, factory, t) -> None:
        await bind(factory, t)
        await bind(factory, t, session_id=t["s1"], status="disabled")
        d = await check(factory, t, session_id=t["s1"], enforcement="enforce")
        assert d.outcome == DENIED and "disables this connection" in d.reason
        # Other sessions of the agent keep the agent grant.
        assert (await check(factory, t, session_id=t["s2"])).outcome == ALLOWED

    async def test_conflict_disabled_tools_are_a_union(self, factory, t) -> None:
        await bind(factory, t, disabled_tools=["delete_repo"])
        await bind(factory, t, session_id=t["s1"])
        d = await check(factory, t, session_id=t["s1"], tool_name="delete_repo")
        assert d.outcome == WOULD_DENY and "disabled by a binding" in d.reason

    async def test_soft_problem_never_hides_a_hard_one(self, factory, t) -> None:
        # No binding (soft) and a viewer role (hard): hard wins in audit mode.
        d = await check(factory, t, principal_role="viewer")
        assert d.outcome == DENIED and stages(d) == {"binding", "rbac"}


# ---------------------------------------------------------------------------
# Adapter paths
# ---------------------------------------------------------------------------


class FakeMCPClient:
    is_connected = True

    def __init__(self) -> None:
        self.calls: list[str] = []

    async def call_tool(self, tool_name: str, arguments: dict[str, Any]) -> MCPResult:
        self.calls.append(tool_name)
        return MCPResult(content="secret output", is_error=False, metadata={})


def session_for(t, *, company="acme", session="s1", **config: Any) -> AgentSession:
    return AgentSession(
        session_id=str(uuid.uuid4()),
        agent_id=t["a"],
        adapter_type="mcp",
        config={"server_url": URL, **config},
        context=ctx(t, company=company, session=session, source="mcp"),
    )


async def run_mcp(t, tool: str = "search", args: dict | None = None, **kw: Any):
    adapter, client = MCPAgentAdapter(), FakeMCPClient()
    session = session_for(t, **kw)
    adapter._logs = {session.session_id: []}
    adapter._clients = {session.session_id: client}
    await adapter._do_execute(session, uuid.uuid4(), {"tool_name": tool, "arguments": args or {}})
    return client


async def invocations(factory) -> list[ToolInvocation]:
    async with factory() as db:
        return list((await db.execute(select(ToolInvocation))).scalars())


async def audit_actions(factory) -> list[str]:
    async with factory() as db:
        return [a.action for a in (await db.execute(select(AuditLog))).scalars()]


class TestMCPAdapterPath:
    async def test_bound_call_runs_and_is_recorded(self, factory, t) -> None:
        await bind(factory, t)
        client = await run_mcp(t)
        assert client.calls == ["search"]
        [row] = await invocations(factory)
        assert (row.authorization, row.status) == ("allowed", "success")
        assert (row.company_id, row.agent_id, row.session_id) == (t["acme"], t["a"], t["s1"])
        assert row.connection_id == t["c"] and row.tool_id is None
        assert row.authorization_detail["source"] == "mcp"
        assert row.result_summary is None  # tool output is never copied into the audit store
        assert await audit_actions(factory) == []

    async def test_unbound_call_in_audit_mode_runs_as_would_deny(self, factory, t) -> None:
        client = await run_mcp(t)
        assert client.calls == ["search"]
        [row] = await invocations(factory)
        assert (row.authorization, row.status) == ("would_deny", "success")
        assert await audit_actions(factory) == ["tool.access_would_deny"]

    async def test_unbound_call_in_enforce_mode_is_blocked(
        self, factory, t, monkeypatch
    ) -> None:
        monkeypatch.setattr(settings, "tool_binding_enforcement", "enforce")
        client = await run_mcp(t)
        assert client.calls == []
        [row] = await invocations(factory)
        assert (row.authorization, row.status) == ("denied", "denied")
        assert await audit_actions(factory) == ["tool.access_denied"]

    async def test_enforce_mode_bound_call_runs(self, factory, t, monkeypatch) -> None:
        monkeypatch.setattr(settings, "tool_binding_enforcement", "enforce")
        await bind(factory, t)
        assert (await run_mcp(t)).calls == ["search"]

    async def test_policy_deny_blocks_in_audit_mode(self, factory, t) -> None:
        await bind(factory, t)
        async with factory() as db:
            db.add(ToolPolicy(company_id=t["acme"], name="no destructive", effect="deny",
                              conditions={"risk_level": ["destructive"]}))
            await db.commit()
        client = await run_mcp(t, tool="delete_repo")
        assert client.calls == []
        [row] = await invocations(factory)
        assert (row.authorization, row.status) == ("denied", "denied")

    async def test_forged_company_in_config_is_blocked(self, factory, t) -> None:
        await bind(factory, t)
        client = await run_mcp(t, company="other", session=None)
        assert client.calls == []

    async def test_foreign_session_in_config_is_blocked(self, factory, t) -> None:
        await bind(factory, t)
        async with factory() as db:
            other_session = AgentSessionRecord(company_id=t["acme"], agent_id=t["b"])
            db.add(other_session)
            await db.commit()
        t = {**t, "sb": other_session.id}
        client = await run_mcp(t, session="sb")
        assert client.calls == []

    async def test_guardrail_still_blocks_a_bound_call(self, factory, t) -> None:
        await bind(factory, t)
        client = await run_mcp(t, args={"cmd": "rm -rf /"})
        assert client.calls == []
        [row] = await invocations(factory)
        assert (row.authorization, row.status) == ("allowed", "guardrail_blocked")

    async def test_autonomy_still_blocks_a_bound_call(self, factory, t, monkeypatch) -> None:
        import nexus.tools.factory as tool_factory

        class BlockingGate:
            async def check(self, **kwargs: Any) -> Any:
                class Decision:
                    allowed = False
                    reason = "level 3 requires approval"
                    action_type = "search"
                    correlation_id = uuid.uuid4()

                return Decision()

        monkeypatch.setattr(tool_factory, "build_autonomy_gate", lambda db, **k: BlockingGate())
        await bind(factory, t)
        client = await run_mcp(t)
        assert client.calls == []
        [row] = await invocations(factory)
        assert (row.authorization, row.status) == ("allowed", "autonomy_blocked")


class TestHermesAdapterPath:
    @staticmethod
    def adapter(calls: list) -> HermesAdapter:
        adapter = HermesAdapter()
        adapter.register_tool("search", lambda **kw: calls.append(kw) or "ok")
        return adapter

    def context(self, t, agent="a") -> ExecutionContext:
        return ctx(t, agent=agent, session="s1", source="hermes")

    async def test_call_runs_and_is_recorded(self, factory, t) -> None:
        calls: list = []
        out = await self.adapter(calls)._execute_tool(
            "search", {"q": "x"}, agent_id=t["a"], context=self.context(t)
        )
        assert out == {"status": "success", "result": "ok"} and calls == [{"q": "x"}]
        [row] = await invocations(factory)
        assert (row.authorization, row.status, row.connection_id) == ("allowed", "success", None)
        assert row.session_id == t["s1"] and row.authorization_detail["source"] == "hermes"

    async def test_policy_deny_blocks(self, factory, t) -> None:
        async with factory() as db:
            db.add(ToolPolicy(company_id=t["acme"], name="no search", effect="deny",
                              conditions={"tool_name": ["search"]}))
            await db.commit()
        calls: list = []
        out = await self.adapter(calls)._execute_tool(
            "search", {}, agent_id=t["a"], context=self.context(t)
        )
        assert out["status"] == "denied" and calls == []
        assert await audit_actions(factory) == ["tool.access_denied"]

    async def test_foreign_session_blocks(self, factory, t) -> None:
        # Agent B claiming session S1, which is agent A's.
        calls: list = []
        out = await self.adapter(calls)._execute_tool(
            "search", {}, agent_id=t["b"], context=self.context(t, agent="b")
        )
        assert out["status"] == "denied" and calls == []

    async def test_unknown_agent_legacy_path(self, factory, t, monkeypatch) -> None:
        """No company claim and no agent row: soft, so audit runs and enforce refuses."""
        calls: list = []
        adapter = self.adapter(calls)
        out = await adapter._execute_tool("search", {}, agent_id=uuid.uuid4())
        assert out["status"] == "success"
        assert await invocations(factory) == []  # no tenant to attribute a row to
        monkeypatch.setattr(settings, "tool_binding_enforcement", "enforce")
        out = await adapter._execute_tool("search", {}, agent_id=uuid.uuid4())
        assert out["status"] == "denied" and len(calls) == 1
