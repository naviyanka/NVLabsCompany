# ruff: noqa: F811
"""Hermes tool turns over ACP: catalogs, credential binding, adapter wiring.

The transport itself is covered in test_hermes_acp.py; here the bridge, the CLI
adapter and the CEO/manager fixtures run against the scripted fake ``hermes acp``.
"""

from __future__ import annotations

import hashlib
import json
import sys
import uuid
from unittest.mock import patch

import jwt
import pytest
from sqlalchemy import update

from nexus.adapters import hermes_acp
from nexus.adapters.cli_adapter import CLIAdapter
from nexus.config import settings
from nexus.models.agent import Agent
from nexus.models.chat_turn import ChatTurn
from nexus.models.tool import ToolPolicy
from nexus.services import ceo_service, org_snapshot
from nexus.tools import manager_bridge as mb
from nexus.tools.ceo_tools import CEO_TOOLS
from nexus.tools.manager_tools import MANAGER_TOOLS
from tests.test_ceo_control_plane import HERMES, _appoint, c  # noqa: F401 -- fixtures
from tests.test_employee_work import _rows, db, w  # noqa: F401 -- fixtures
from tests.test_hermes_acp import FAKE, records
from tests.test_manager_bridge import REGISTRY, _chat_ctx, _execute, _turn
from tests.test_manager_core import _staffed, team  # noqa: F401 -- fixtures

pytestmark = pytest.mark.employee_work


@pytest.fixture
def acp_on(monkeypatch):
    monkeypatch.setattr(settings, "hermes_acp_tools_enabled", True)


def wire(names):
    return frozenset(hermes_acp.tool_wire_name(mb.SERVER_NAME, n) for n in names)


async def _open(db, company, agent, backend=HERMES, **kw):  # noqa: F811
    turn = await _turn(db, agent)
    ctx = _chat_ctx(company, agent, **kw)
    return turn, await mb.open_bridge(ctx, uuid.UUID(turn.execution_id), backend, 3600)


async def _allow(db, company, agent, tool):  # noqa: F811
    async with db() as s:
        s.add(
            ToolPolicy(
                company_id=company,
                name=f"allow-{tool}",
                effect="allow",
                conditions={"tool_name": [tool], "agent_id": [str(agent)]},
            )
        )
        await s.commit()


class TestCatalogsAndCredential:
    async def test_the_gate_is_off_by_default(self, db, c):  # noqa: F811
        assert settings.hermes_acp_tools_enabled is False
        await _appoint(c, c["chief"])
        async with db() as s:
            supported, _ = ceo_service.tool_support(await s.get(Agent, c["chief"]))
        assert not supported

    async def test_ceo_gets_only_the_ceo_catalog_and_a_bound_token(self, acp_on, db, c):  # noqa: F811
        await _appoint(c, c["chief"])
        async with db() as s:
            assert ceo_service.tool_support(await s.get(Agent, c["chief"])) == (True, None)
        turn, bridge = await _open(db, c["acme"], c["chief"], manager_tools_required=True)
        assert bridge.available and bridge.tool_names == wire(CEO_TOOLS)
        # No config file, argv or environment: the credential is only in the session request.
        assert bridge.args == [] and bridge.env == {} and bridge.config_path is None
        (server,) = bridge.acp_servers
        assert server["headers"] == [{"name": "Authorization", "value": f"Bearer {bridge.token}"}]
        claims = jwt.decode(
            bridge.token, settings.secret_key, algorithms=["HS256"], audience=mb.AUDIENCE
        )
        assert (claims["sub"], claims["company_id"], claims["execution_id"]) == (
            str(c["chief"]),
            str(c["acme"]),
            turn.execution_id,
        )
        assert claims["exp"] - claims["iat"] == mb.MAX_TTL_SECONDS
        assert (await mb.authenticate(bridge.token)).turn_id == turn.id

    async def test_manager_gets_only_manager_tools(self, acp_on, db, c):  # noqa: F811
        await _staffed(c)
        _, bridge = await _open(db, c["acme"], c["lead"])
        assert bridge.tool_names == wire(MANAGER_TOOLS)
        assert not wire(CEO_TOOLS) & bridge.tool_names

    async def test_snapshot_only_authorization_offers_only_the_snapshot(self, acp_on, db, c):  # noqa: F811
        await _allow(db, c["acme"], c["lead"], org_snapshot.TOOL)
        _, bridge = await _open(db, c["acme"], c["lead"])
        assert bridge.tool_names == wire([org_snapshot.TOOL])

    async def test_employee_gets_no_bridge_and_required_refuses(self, acp_on, db, c):  # noqa: F811
        _, none = await _open(db, c["acme"], c["acme_agy"])
        assert none is None
        with pytest.raises(mb.BridgeUnavailableError, match="MANAGER_TOOLS_UNAVAILABLE"):
            await _open(db, c["acme"], c["acme_agy"], manager_tools_required=True)

    async def test_a_recovered_turn_invalidates_the_old_token(self, acp_on, db, c):  # noqa: F811
        await _staffed(c)
        turn, bridge = await _open(db, c["acme"], c["lead"])
        await mb.authenticate(bridge.token)
        async with db() as s:  # recovery claims the turn under a new execution ID
            await s.execute(
                update(ChatTurn)
                .where(ChatTurn.id == turn.id)
                .values(execution_id=str(uuid.uuid4()))
            )
            await s.commit()
        with pytest.raises(mb.BridgeDeniedError):
            await mb.authenticate(bridge.token)


async def _run(tmp_path, ctx, scenario, monkeypatch, extra_env=None):
    """One hermes turn through the CLI adapter, with the fake in place of ``hermes acp``."""
    rec = tmp_path / "rec.jsonl"
    for k, v in (extra_env or {}).items():
        monkeypatch.setenv(k, v)
    real = hermes_acp.HermesACPTransport

    def fake(cmd, **kw):
        assert cmd[1:] == ["acp"]
        kw["env"] = {**kw["env"], "FAKE_ACP_SCENARIO": scenario, "FAKE_ACP_RECORD": str(rec)}
        return real([sys.executable, FAKE], **kw)

    adapter = CLIAdapter()
    session = await adapter.create_session(
        ctx.agent_id, {"backend": "hermes", "workspace": str(tmp_path)}
    )
    session.context = ctx
    with (
        patch("nexus.adapters.cli_adapter.get_cli_registry", return_value=REGISTRY),
        patch("nexus.adapters.hermes_acp.HermesACPTransport", side_effect=fake),
    ):
        return await adapter.execute_task(session, uuid.uuid4(), {"prompt": "status?"}), rec


class TestAdapter:
    async def test_tool_turn_runs_over_acp_and_the_token_never_leaks(
        self,
        acp_on,
        db,
        c,
        tmp_path,
        monkeypatch,  # noqa: F811
    ):
        await _appoint(c, c["chief"])
        ctx = _chat_ctx(c["acme"], c["chief"], manager_tools_required=True)
        result, rec = await _run(tmp_path, ctx, "echo_token", monkeypatch)
        (new,) = [r for r in records(rec) if r.get("method") == "session/new"]
        token = new["servers"][0]["headers"][0]["value"].removeprefix("Bearer ")
        assert new["cwd"] == str(tmp_path) and result.success
        dumped = json.dumps(
            [result.output, result.error, result.logs, result.artifacts], default=str
        )
        assert token not in dumped and mb.REDACTED in dumped
        meta = next(a for a in result.artifacts if a.get("type") == "cli_execution")
        assert meta["transport"] == "acp" and meta["manager_tools_available"] is True

    async def test_a_forbidden_tool_fails_the_turn_without_fallback(
        self,
        acp_on,
        db,
        c,
        tmp_path,
        monkeypatch,  # noqa: F811
    ):
        await _appoint(c, c["chief"])
        ctx = _chat_ctx(c["acme"], c["chief"], manager_tools_required=True)
        result, rec = await _run(tmp_path, ctx, "tool_bad", monkeypatch)
        assert not result.success and result.error.startswith("ACP_POLICY_VIOLATION")
        assert "should never be read" not in (result.output or "")
        assert [r.get("method") for r in records(rec)].count("session/prompt") == 1

    async def test_free_form_tool_text_executes_nothing(
        self,
        acp_on,
        db,
        c,
        tmp_path,
        monkeypatch,  # noqa: F811
    ):
        await _appoint(c, c["chief"])
        ctx = _chat_ctx(c["acme"], c["chief"], manager_tools_required=True)
        result, _ = await _run(tmp_path, ctx, "free_form", monkeypatch)
        meta = next(a for a in result.artifacts if a.get("type") == "cli_execution")
        assert result.success and meta["acp_tool_calls"] == []

    async def test_ordinary_hermes_chat_is_unchanged(self, acp_on, db, c, tmp_path):  # noqa: F811
        _, seen = await _execute(tmp_path, _chat_ctx(c["acme"], c["acme_agy"]), backend="hermes")
        assert seen["cmd"][:2] == ["hermes", "-z"] and "acp" not in seen["cmd"]
        assert mb.TOKEN_ENV not in seen["env"]

    async def test_global_hermes_files_are_untouched(
        self,
        acp_on,
        db,
        c,
        tmp_path,
        monkeypatch,  # noqa: F811
    ):
        await _appoint(c, c["chief"])
        home = tmp_path / "hermes-home"
        home.mkdir()
        for name in ("config.yaml", "auth.json", ".env"):
            (home / name).write_text(f"{name} original")
        before = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in home.iterdir()}
        ctx = _chat_ctx(c["acme"], c["chief"], manager_tools_required=True)
        work = tmp_path / "work"
        work.mkdir()
        await _run(work, ctx, "ok", monkeypatch, {"HERMES_HOME": str(home)})
        after = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in home.iterdir()}
        assert before == after
