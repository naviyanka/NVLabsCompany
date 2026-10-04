"""The manager tool bridge: a CLI manager's manager tools during its own chat turn.

Runs on the Manager Core fixtures (tests/test_manager_core.py): a file SQLite
database, a manager Lead over the claude and agy employees, and the real
TaskAttempt worker behind delegation. The bridge endpoint is exercised over
ASGI with credentials minted by ``open_bridge`` for real running chat turns;
the CLI adapter runs with a faked subprocess.
"""

from __future__ import annotations

import asyncio
import itertools
import json
import os
import uuid
from datetime import timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import jwt
import pytest
from fastapi import FastAPI
from sqlalchemy import update

from nexus.adapters.cli_adapter import CLIAdapter
from nexus.adapters.cli_registry import CLIRegistry
from nexus.api.routes import managers as manager_routes
from nexus.auth.middleware import rejection_for
from nexus.auth.run_tokens import mint_run_token
from nexus.config import settings
from nexus.models._time import utcnow
from nexus.models.agent import Agent
from nexus.models.chat import ChatMessage
from nexus.models.chat_turn import ChatTurn
from nexus.models.governance import AuditLog
from nexus.models.task_attempt import TaskAttempt
from nexus.models.tool import ToolPolicy
from nexus.models.tool_invocation import ToolInvocation
from nexus.runtime import chat_turns
from nexus.runtime import task_attempts as ta
from nexus.services.session_service import get_or_create_default_session
from nexus.tools import manager_bridge as mb
from nexus.tools.context import ExecutionContext
from tests.test_employee_work import _me, _rows, db, w  # noqa: F401 -- fixtures
from tests.test_manager_core import _payload, _staffed, team  # noqa: F401 -- fixtures

pytestmark = pytest.mark.employee_work

MANAGER_TOOLS = {"manager_list_reports", "manager_employee_status", "manager_delegate_task",
                 "manager_task_evidence", "manager_rollup", "manager_list_hiring_requests",
                 "manager_get_hiring_request", "organization_get_snapshot"}
REGISTRY = CLIRegistry(auto_detect=False)
CLAUDE, AGY = REGISTRY.get_backend("claude"), REGISTRY.get_backend("agy")
_SEQ = itertools.count(1000)


def _chat_ctx(company, agent, **kw):
    return ExecutionContext(company_id=company, principal_id=f"user:{uuid.uuid4()}",
                            principal_role="admin", source="chat", agent_id=agent, **kw)


async def _turn(db, agent_id, *, status="running", lease=60, cancelled=False):  # noqa: F811
    """A chat turn of ``agent_id`` in ``status``, with a fresh execution ID."""
    async with db() as s:
        agent = await s.get(Agent, agent_id)
        record = await get_or_create_default_session(s, agent)
        turn = ChatTurn(company_id=agent.company_id, agent_id=agent.id, session_id=record.id,
                        idempotency_key=uuid.uuid4().hex, turn_seq=next(_SEQ), status=status,
                        execution_id=str(uuid.uuid4()),
                        lease_expires_at=utcnow() + timedelta(seconds=lease),
                        cancel_requested_at=utcnow() if cancelled else None)
        s.add(turn)
        await s.commit()
        return turn


async def _token(turn, backend=CLAUDE, timeout=600):
    """The credential ``open_bridge`` mints for ``turn``'s execution; config removed."""
    bridge = await mb.open_bridge(_chat_ctx(turn.company_id, turn.agent_id),
                                  uuid.UUID(turn.execution_id), backend, timeout)
    bridge.close()
    return bridge.env[mb.TOKEN_ENV]


@pytest.fixture
async def rpc(team):  # noqa: F811
    """POST one JSON-RPC message to the bridge; returns the httpx response."""
    app = FastAPI()
    app.include_router(manager_routes.router)
    client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")

    async def call(token, method, params=None, *, headers=None, content=None):
        body = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params or {}}
        sent = {"authorization": f"Bearer {token}", "content-type": "application/json",
                **(headers or {})}
        return await client.post(mb.PATH, headers=sent,
                                 content=json.dumps(body) if content is None else content)

    yield call
    await client.aclose()


async def _tools(rpc, token):
    response = await rpc(token, "tools/list")
    assert response.status_code == 200, response.text
    return {t["name"] for t in response.json()["result"]["tools"]}


async def _tool(rpc, token, name, arguments=None):
    response = await rpc(token, "tools/call", {"name": name, "arguments": arguments or {}})
    assert response.status_code == 200, response.text
    return response.json()["result"]


async def _allow_delegation(db, company):  # noqa: F811
    async with db() as s:
        s.add_all([
            ToolPolicy(company_id=company, name="reads", effect="allow",
                       conditions={"risk_level": ["read"]}),
            ToolPolicy(company_id=company, name="delegation", effect="allow",
                       conditions={"tool_name": ["manager_delegate_task"]}),
        ])
        await s.commit()


class TestEndpoint:
    async def test_manager_gets_the_manager_tools_and_nothing_else(self, db, team, rpc):  # noqa: F811
        await _staffed(team)
        await _allow_delegation(db, team["acme"])
        token = await _token(await _turn(db, team["lead"]))
        assert (await rpc(token, "initialize")).json()["result"]["serverInfo"]["name"]
        # Node tools are not served here, even under an allow-all read policy;
        # hiring (write) is not served without its own explicit allow.
        assert await _tools(rpc, token) == MANAGER_TOOLS
        notified = await rpc(token, "notifications/initialized", content=json.dumps(
            {"jsonrpc": "2.0", "method": "notifications/initialized"}))
        assert notified.status_code == 202

    async def test_read_tool_succeeds_under_the_default_policy(self, db, team, rpc):  # noqa: F811
        await _staffed(team)
        turn = await _turn(db, team["lead"])
        token = await _token(turn)
        names = await _tools(rpc, token)
        assert "manager_delegate_task" not in names and "manager_list_reports" in names
        reports = _payload(await _tool(rpc, token, "manager_list_reports"))
        assert {r["name"] for r in reports} == {"claude", "agy"}
        # Recorded through the ToolInvocation path, as the turn's execution.
        (row,) = await _rows(db, ToolInvocation, ToolInvocation.tool_name == "manager_list_reports")
        assert row.agent_id == team["lead"] and row.session_id == turn.session_id
        assert row.authorization_detail["turn_id"] == str(turn.id)
        assert row.authorization_detail["principal_id"] == f"run:{turn.execution_id}"
        assert row.authorization_detail["request_source"] == "mcp_inbound"

    async def test_delegation_is_denied_without_a_tool_policy(self, db, team, rpc):  # noqa: F811
        await _staffed(team)
        token = await _token(await _turn(db, team["lead"]))
        denied = await _tool(rpc, token, "manager_delegate_task", {
            "task_id": str(team["task2"]), "employee_id": str(team["acme_agy"])})
        assert denied["isError"] and "Denied by access policy" in denied["content"][0]["text"]
        assert await _rows(db, TaskAttempt, TaskAttempt.task_id == team["task2"]) == []

    async def test_delegation_with_a_policy_survives_a_retry_once(self, db, team, rpc):  # noqa: F811
        await _staffed(team)
        await _allow_delegation(db, team["acme"])
        turn = await _turn(db, team["lead"])
        first_token = await _token(turn)
        args = {"task_id": str(team["task2"]), "employee_id": str(team["acme_agy"])}
        first = _payload(await _tool(rpc, first_token, "manager_delegate_task", args))
        await ta.drain()
        # The turn is recovered and claimed again under a new execution ID:
        # the old credential dies, the retry's own delegates nothing new.
        async with db() as s:
            await s.execute(update(ChatTurn).where(ChatTurn.id == turn.id)
                            .values(execution_id=str(uuid.uuid4())))
            await s.commit()
            turn = await s.get(ChatTurn, turn.id)
        assert (await rpc(first_token, "tools/list")).status_code == 401
        again = _payload(await _tool(rpc, await _token(turn), "manager_delegate_task", args))
        # The retry replays the call recorded by the effect ledger instead of reaching the
        # tool again, so it reports the original result; the single attempt row proves that
        # nothing was delegated twice.
        assert (first["created"], again["created"]) == (True, True)
        assert first["attempt"]["id"] == again["attempt"]["id"]
        assert len(await _rows(db, TaskAttempt, TaskAttempt.task_id == team["task2"])) == 1
        (queued,) = [r for r in await _rows(db, AuditLog, AuditLog.action == "task.attempt_queued")]
        assert queued.details["delegated_by"] == str(team["lead"])

    async def test_an_employee_gets_no_manager_tools(self, db, team, rpc):  # noqa: F811
        await _staffed(team)
        turn = await _turn(db, team["acme_agy"])
        # Not a manager: no bridge is opened at all.
        assert await mb.open_bridge(_chat_ctx(team["acme"], team["acme_agy"]),
                                    uuid.UUID(turn.execution_id), CLAUDE, 600) is None
        # Even with a credential for its own running turn, it sees nothing.
        token = jwt.encode(
            {"sub": str(team["acme_agy"]), "company_id": str(team["acme"]),
             "execution_id": turn.execution_id, "aud": mb.AUDIENCE,
             "exp": utcnow() + timedelta(minutes=5)},
            settings.secret_key, algorithm="HS256")
        assert await _tools(rpc, token) == set()

    async def test_cross_tenant_and_spoofed_identities_fail(self, db, team, rpc):  # noqa: F811
        await _staffed(team)
        turn = await _turn(db, team["lead"])
        token = await _token(turn)

        def forged(**claims):
            base = {"sub": str(team["lead"]), "company_id": str(team["acme"]),
                    "execution_id": turn.execution_id, "aud": mb.AUDIENCE,
                    "exp": utcnow() + timedelta(minutes=5)}
            return jwt.encode({**base, **claims}, settings.secret_key, algorithm="HS256")

        for bad in (
            forged(company_id=str(team["other"])),  # Lead's turn is not in that tenant
            forged(sub=str(team["bo"])),  # Bo has no turn running this execution
            forged(sub=str(team["other_lead"]), company_id=str(team["other"])),
            forged(aud="nexus:run"),
            jwt.encode(jwt.decode(token, options={"verify_signature": False}), "wrong-key",
                       algorithm="HS256"),
            token[:-4] + ("AAAA" if not token.endswith("AAAA") else "BBBB"),
            mint_run_token(uuid.UUID(turn.execution_id), team["lead"], team["acme"]),
        ):
            response = await rpc(bad, "tools/list")
            assert response.status_code == 401 and response.json()["code"] == "BRIDGE_DENIED"
            assert bad not in response.text

        # Identifiers in the call are refused, not trusted.
        spoof = await _tool(rpc, token, "manager_rollup", {"manager_id": str(team["bo"])})
        assert spoof["isError"] and "unexpected arguments" in spoof["content"][0]["text"]
        spoof = await _tool(rpc, token, "manager_list_reports",
                            {"company_id": str(team["other"])})
        assert spoof["isError"] and "unexpected arguments" in spoof["content"][0]["text"]
        foreign = await _tool(rpc, token, "manager_employee_status",
                              {"employee_id": str(team["other_claude"])})
        assert foreign["isError"] and "AGENT_NOT_FOUND" in foreign["content"][0]["text"]
        others = await _tool(rpc, token, "manager_employee_status",
                             {"employee_id": str(team["claude2"])})
        assert others["isError"] and "NOT_A_DIRECT_REPORT" in others["content"][0]["text"]
        # Request headers name no identity either.
        reports = _payload(await _tool(rpc, token, "manager_list_reports"))
        assert {r["name"] for r in reports} == {"claude", "agy"}

    async def test_expired_ended_and_cancelled_executions_fail(self, db, team, rpc):  # noqa: F811
        await _staffed(team)
        for turn in (
            await _turn(db, team["lead"], status="completed"),
            await _turn(db, team["lead"], status="claimed"),
            await _turn(db, team["lead"], status="cancelled"),
            await _turn(db, team["lead"], cancelled=True),
            await _turn(db, team["lead"], lease=-1),
        ):
            assert (await rpc(await _token(turn), "tools/list")).status_code == 401
        live = await _turn(db, team["lead"])
        expired = jwt.encode(
            {"sub": str(team["lead"]), "company_id": str(team["acme"]),
             "execution_id": live.execution_id, "aud": mb.AUDIENCE,
             "exp": utcnow() - timedelta(seconds=1)},
            settings.secret_key, algorithm="HS256")
        assert (await rpc(expired, "tools/list")).status_code == 401
        # The same credential stops working once its turn completes.
        token = await _token(live)
        assert (await rpc(token, "tools/list")).status_code == 200
        async with db() as s:
            await s.execute(update(ChatTurn).where(ChatTurn.id == live.id)
                            .values(status="completed"))
            await s.commit()
        assert (await rpc(token, "tools/list")).status_code == 401

    async def test_malformed_requests_fail_closed(self, db, team, rpc):  # noqa: F811
        await _staffed(team)
        token = await _token(await _turn(db, team["lead"]))
        assert (await rpc("", "tools/list")).status_code == 401
        assert (await rpc(token, "tools/list", headers={"authorization": f"Basic {token}"})
                ).status_code == 401
        assert (await rpc(token, "tools/list", headers={"content-type": "text/plain"})
                ).status_code == 415
        big = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "ping",
                          "params": {"x": "a" * (manager_routes.BRIDGE_MAX_BODY + 1)}})
        assert (await rpc(token, "ping", content=big)).status_code == 413
        assert (await rpc(token, "ping", content="{nope")).status_code == 400
        assert (await rpc(token, "ping", content="[]")).status_code == 400
        # The auth middleware leaves the route to authenticate itself.
        assert rejection_for(mb.PATH, None) is None


class TestOpenBridge:
    async def test_credential_is_short_lived_and_config_names_only_the_variable(self, db, team):  # noqa: F811
        await _staffed(team)
        turn = await _turn(db, team["lead"])
        ctx = _chat_ctx(team["acme"], team["lead"])
        bridge = await mb.open_bridge(ctx, uuid.UUID(turn.execution_id), CLAUDE, 3600)
        try:
            token = bridge.env[mb.TOKEN_ENV]
            claims = jwt.decode(token, settings.secret_key, algorithms=["HS256"],
                                audience=mb.AUDIENCE)
            assert claims["exp"] - claims["iat"] == mb.MAX_TTL_SECONDS
            assert (claims["sub"], claims["company_id"], claims["execution_id"]) == (
                str(team["lead"]), str(team["acme"]), turn.execution_id)
            with open(bridge.config_path, encoding="utf-8") as f:
                config = f.read()
            assert token not in config and "${NEXUS_MANAGER_BRIDGE_TOKEN}" in config
            assert bridge.args == ["--mcp-config", bridge.config_path, "--strict-mcp-config",
                                   "--allowedTools=mcp__nexus__*"]
        finally:
            bridge.close()
        assert not os.path.exists(bridge.config_path or "gone")
        short = await mb.open_bridge(ctx, uuid.UUID(turn.execution_id), CLAUDE, 30)
        short.close()
        claims = jwt.decode(short.env[mb.TOKEN_ENV], settings.secret_key, algorithms=["HS256"],
                            audience=mb.AUDIENCE)
        assert claims["exp"] - claims["iat"] == 30

    async def test_only_plain_manager_chat_turns_are_eligible(self, db, team):  # noqa: F811
        await _staffed(team)
        execution = uuid.uuid4()
        attempt = _chat_ctx(team["acme"], team["lead"], work_mode="write")
        assert await mb.open_bridge(attempt, execution, CLAUDE, 600) is None
        assert await mb.open_bridge(None, execution, CLAUDE, 600) is None
        background = ExecutionContext.for_agent(
            type("A", (), {"company_id": team["acme"], "id": team["lead"]})(), source="background")
        assert await mb.open_bridge(background, execution, CLAUDE, 600) is None
        # Agy: runs, without tools, unless the turn requires them.
        manager = _chat_ctx(team["acme"], team["lead"])
        assert (await mb.open_bridge(manager, execution, AGY, 600)).available is False
        required = _chat_ctx(team["acme"], team["lead"], manager_tools_required=True)
        with pytest.raises(mb.BridgeUnavailableError, match="MANAGER_TOOLS_UNSUPPORTED"):
            await mb.open_bridge(required, execution, AGY, 600)
        employee = _chat_ctx(team["acme"], team["acme_agy"], manager_tools_required=True)
        with pytest.raises(mb.BridgeUnavailableError, match="MANAGER_TOOLS_UNAVAILABLE"):
            await mb.open_bridge(employee, execution, CLAUDE, 600)

    async def test_streaming_and_plain_turns_get_the_same_tool_access(self, db, team):  # noqa: F811
        await _staffed(team)
        contexts = []
        async with db() as s:
            lead = await s.get(Agent, team["lead"])
            record = await get_or_create_default_session(s, lead)
            for stream, key in ((False, "plain"), (True, "stream")):
                queued = await chat_turns.create_turn(
                    s, record, lead, "hi", principal=_me(team["acme"]), idempotency_key=key,
                    stream=stream, require_manager_tools=stream)
                contexts.append(ExecutionContext.from_dict(queued.turn.execution_context))
        plain, streamed = contexts
        assert streamed.manager_tools_required and not plain.manager_tools_required
        for ctx in contexts:
            bridge = await mb.open_bridge(ctx, uuid.uuid4(), CLAUDE, 600)
            bridge.close()
            assert bridge.available and bridge.args[0] == "--mcp-config"


# --- the CLI adapter --------------------------------------------------------


def _process(stdout=b"", stderr=b"", returncode=0, hang=None):
    """As tests/test_cli_adapter.py's; ``hang``: "timeout" or "forever"."""
    proc = MagicMock()
    proc.pid = None
    proc.returncode = None if hang else returncode
    proc.stdin = None
    if hang == "timeout":
        read = AsyncMock(side_effect=TimeoutError())
    elif hang:
        async def forever(*_):
            await asyncio.Event().wait()

        read = AsyncMock(side_effect=forever)
    else:
        read = AsyncMock(side_effect=[stdout, b""])
    proc.stdout = MagicMock(read=read)
    proc.stderr = MagicMock(read=AsyncMock(side_effect=[stderr, b""]))
    proc.wait = AsyncMock(return_value=returncode)
    proc.send_signal = MagicMock()
    proc.kill = MagicMock()
    return proc


async def _execute(tmp_path, ctx, *, backend="claude", timeout=None, hang=None, echo=False):
    """Run one CLI execution under ``ctx``; returns (result, spawn record)."""
    seen: dict = {}

    async def spawn(*cmd, **kw):
        seen["cmd"], seen["env"] = list(cmd), kw["env"]
        if "--mcp-config" in cmd:
            path = cmd[cmd.index("--mcp-config") + 1]
            seen["config_path"] = path
            with open(path, encoding="utf-8") as f:
                seen["config"] = f.read()
        token = kw["env"].get(mb.TOKEN_ENV, "")
        out = f"answer {token}".encode() if echo else b"answer"
        return _process(out, f"warn Bearer {token}".encode() if echo else b"", hang=hang)

    adapter = CLIAdapter()
    session = await adapter.create_session(ctx.agent_id if ctx else uuid.uuid4(),
                                           {"backend": backend, "workspace": str(tmp_path)})
    session.context = ctx
    payload = {"prompt": "status?"}
    if timeout is not None:
        payload["timeout"] = timeout
    with patch("nexus.adapters.cli_adapter.get_cli_registry", return_value=REGISTRY), \
            patch("asyncio.create_subprocess_exec", new=AsyncMock(side_effect=spawn)):
        if hang == "forever":
            task = asyncio.create_task(adapter.execute_task(session, uuid.uuid4(), payload))
            while "cmd" not in seen:
                await asyncio.sleep(0.01)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            return None, seen
        return await adapter.execute_task(session, uuid.uuid4(), payload), seen


def _meta(result):
    return next(a for a in result.artifacts if a.get("type") == "cli_execution")


class TestCLIAdapter:
    async def test_manager_run_gets_the_bridge_and_the_credential_never_leaks(
        self, db, team, tmp_path  # noqa: F811
    ):
        await _staffed(team)
        result, seen = await _execute(tmp_path, _chat_ctx(team["acme"], team["lead"]), echo=True)
        token = seen["env"][mb.TOKEN_ENV]
        cmd = seen["cmd"]
        assert cmd[:2] == ["claude", "-p"] and cmd[-1] == "status?"
        assert cmd[2:6] == ["--mcp-config", seen["config_path"], "--strict-mcp-config",
                            "--allowedTools=mcp__nexus__*"]
        assert token not in " ".join(cmd) and token not in seen["config"]
        assert not os.path.exists(seen["config_path"])
        assert result.success and _meta(result)["manager_tools_available"] is True
        dumped = json.dumps([result.output, result.error, result.logs, result.artifacts],
                            default=str)
        assert token not in dumped and mb.REDACTED in dumped
        # Nor in anything persisted for the company.
        rows = [*(await _rows(db, AuditLog)), *(await _rows(db, ToolInvocation)),
                *(await _rows(db, ChatMessage)), *(await _rows(db, ChatTurn))]
        assert token not in json.dumps([r.model_dump() for r in rows], default=str)

    async def test_non_manager_and_no_context_runs_are_unchanged(self, db, team, tmp_path):  # noqa: F811
        await _staffed(team)
        baseline, plain = await _execute(tmp_path, None)
        result, employee = await _execute(tmp_path, _chat_ctx(team["acme"], team["acme_agy"]))
        for seen, res in ((plain, baseline), (employee, result)):
            assert seen["cmd"] == ["claude", "-p", "status?"]
            assert mb.TOKEN_ENV not in seen["env"]
            assert "manager_tools_available" not in _meta(res)

    async def test_agy_manager_chats_without_tools_unless_required(self, db, team, tmp_path):  # noqa: F811
        await _staffed(team)
        result, seen = await _execute(tmp_path, _chat_ctx(team["acme"], team["lead"]),
                                      backend="agy")
        assert result.success and _meta(result)["manager_tools_available"] is False
        assert "--mcp-config" not in seen["cmd"] and mb.TOKEN_ENV not in seen["env"]

        required = _chat_ctx(team["acme"], team["lead"], manager_tools_required=True)
        result, seen = await _execute(tmp_path, required, backend="agy")
        assert not result.success and result.error.startswith("MANAGER_TOOLS_UNSUPPORTED")
        assert seen == {}  # nothing was spawned

    async def test_timeout_and_cancellation_remove_the_bridge(self, db, team, tmp_path):  # noqa: F811
        await _staffed(team)
        ctx = _chat_ctx(team["acme"], team["lead"])
        result, seen = await _execute(tmp_path, ctx, timeout=1, hang="timeout")
        assert not result.success and "timed out" in result.error
        assert not os.path.exists(seen["config_path"])
        _, seen = await _execute(tmp_path, ctx, hang="forever")
        assert not os.path.exists(seen["config_path"])


class TestZeroReportBootstrap:
    """A manager with no reports yet gets the bridge only by explicit ToolPolicy."""

    @staticmethod
    async def _bridge(db, company, agent):  # noqa: F811
        turn = await _turn(db, agent)
        bridge = await mb.open_bridge(_chat_ctx(company, agent), uuid.UUID(turn.execution_id),
                                      CLAUDE, 600)
        if bridge is not None:
            bridge.close()
        return bridge

    @staticmethod
    async def _policy(db, company, effect, agent=None, tool="manager_request_hire"):  # noqa: F811
        conditions = {"tool_name": [tool]}
        if agent is not None:
            conditions["agent_id"] = [str(agent)]
        async with db() as s:
            s.add(ToolPolicy(company_id=company, name=f"{effect}-{tool}", effect=effect,
                             conditions=conditions))
            await s.commit()

    async def test_an_authorized_manager_with_no_reports_gets_the_bridge(self, db, team, rpc):  # noqa: F811
        # Lead has no reports yet (no _staffed); its role text alone grants nothing.
        assert await self._bridge(db, team["acme"], team["lead"]) is None
        # Nor does a company-wide allow, or a read allow, make every agent a manager.
        await self._policy(db, team["acme"], "allow")
        await _allow_delegation(db, team["acme"])
        assert await self._bridge(db, team["acme"], team["lead"]) is None
        await self._policy(db, team["acme"], "allow", team["lead"])
        token = await _token(await _turn(db, team["lead"]))
        assert "manager_request_hire" in await _tools(rpc, token)
        # No reports yet: the report and request lists are simply empty.
        assert _payload(await _tool(rpc, token, "manager_list_reports")) == []
        assert _payload(await _tool(rpc, token, "manager_list_hiring_requests")) == []
        # A deny on the tool withdraws the bootstrap.
        await self._policy(db, team["acme"], "deny", team["lead"])
        assert await self._bridge(db, team["acme"], team["lead"]) is None

    async def test_an_ordinary_employee_with_no_reports_gets_nothing(self, db, team):  # noqa: F811
        await self._policy(db, team["acme"], "allow")
        await self._policy(db, team["acme"], "allow", team["lead"])
        # A pinned allow for another agent, or a pinned non-manager tool, grants nothing.
        await self._policy(db, team["acme"], "allow", team["acme_agy"], tool="read_file")
        assert await self._bridge(db, team["acme"], team["acme_agy"]) is None

    async def test_another_tenants_policy_grants_nothing(self, db, team):  # noqa: F811
        # A policy written in "other" naming acme's Lead does not reach acme.
        await self._policy(db, team["other"], "allow", team["lead"])
        assert await self._bridge(db, team["acme"], team["lead"]) is None
        # Nor does acme's pinned allow reach the other tenant's manager.
        await self._policy(db, team["acme"], "allow", team["other_lead"])
        assert await self._bridge(db, team["other"], team["other_lead"]) is None
