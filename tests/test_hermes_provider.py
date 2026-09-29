# ruff: noqa: E501
"""Hermes native governed tools: a fake OpenAI-compatible server, no paid call.

The adapter runs against a local HTTP server that streams scripted chat
completions. The CEO, manager and turn fixtures are the existing ones.
"""

from __future__ import annotations

import json
import threading
import uuid
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest
from sqlalchemy import update

from nexus.adapters import hermes_provider as hp
from nexus.adapters.hermes_provider import HermesProviderAdapter
from nexus.adapters.registry import AdapterRegistry
from nexus.adapters.uastl import resolve_provider
from nexus.config import settings
from nexus.models.agent import Agent
from nexus.models.chat_turn import ChatTurn
from nexus.models.governance import AuditLog
from nexus.models.task import Goal
from nexus.models.tool import ToolPolicy
from nexus.models.tool_invocation import ToolInvocation
from nexus.services import ceo_service, org_snapshot
from nexus.tools import manager_bridge as mb
from nexus.tools.ceo_tools import CEO_TOOLS, WRITE_TOOLS
from nexus.tools.manager_tools import MANAGER_TOOLS
from tests.test_ceo_control_plane import _appoint, c  # noqa: F401 -- fixtures
from tests.test_employee_work import _rows, db, w  # noqa: F401 -- fixtures
from tests.test_manager_bridge import _chat_ctx, _turn
from tests.test_manager_core import _staffed, team  # noqa: F401 -- fixtures

pytestmark = pytest.mark.employee_work

KEY = "sk-test-not-a-real-key-123"
MODEL = "test-hermes-model"


def chunk(delta=None, finish=None, usage=None):
    return {"choices": [{"index": 0, "delta": delta or {}, "finish_reason": finish}], "usage": usage}


def call_delta(index, call_id="", name="", args=""):
    return {"tool_calls": [{"index": index, "id": call_id, "function": {"name": name, "arguments": args}}]}


def tool_response(*calls):
    """One response calling ``(id, name, args)`` tools, arguments split into fragments."""
    chunks = []
    for i, (cid, name, args) in enumerate(calls):
        raw = json.dumps(args)
        mid = len(raw) // 2
        chunks += [chunk(call_delta(i, cid, name, raw[:mid])), chunk(call_delta(i, "", "", raw[mid:]))]
    return [*chunks, chunk(finish="tool_calls")]


def text_response(text):
    return [chunk({"content": text[: len(text) // 2]}), chunk({"content": text[len(text) // 2 :]}),
            chunk(finish="stop", usage={"prompt_tokens": 7, "completion_tokens": 3})]


class Fake:
    """Serves ``script`` (one entry per request) and records every request."""

    def __init__(self, script):
        self.script, self.requests, self.delay = list(script), [], 0.0
        fake = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers["content-length"])))
                fake.requests.append({"body": body, "auth": self.headers.get("Authorization"),
                                      "path": self.path})
                if fake.delay:
                    import time
                    time.sleep(fake.delay)
                step = fake.script.pop(0) if fake.script else text_response("done")
                if isinstance(step, int):
                    self.send_response(step)
                    if 300 <= step < 400:
                        self.send_header("Location", "http://127.0.0.1:1/elsewhere")
                    self.end_headers()
                    return
                self.send_response(200)
                self.send_header("content-type", "text/event-stream")
                self.end_headers()
                for part in step:
                    self.wfile.write(f"data: {json.dumps(part)}\n\n".encode())
                self.wfile.write(b"data: [DONE]\n\n")

            def do_GET(self):
                fake.requests.append({"path": self.path, "auth": self.headers.get("Authorization")})
                self.send_response(200)
                self.end_headers()

            def log_message(self, *a):
                pass

        self.server = HTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}/v1"

    def offered(self, request=0):
        return [t["function"]["name"] for t in self.requests[request]["body"].get("tools", [])]


@pytest.fixture
def provider(monkeypatch):
    servers = []

    def start(script):
        fake = Fake(script)
        servers.append(fake)
        monkeypatch.setattr(settings, "hermes_native_base_url", fake.url)
        return fake

    monkeypatch.setattr(settings, "secret_backend", "env")
    monkeypatch.setattr(settings, "hermes_native_tools_enabled", True)
    monkeypatch.setattr(settings, "hermes_native_model", MODEL)
    monkeypatch.setattr(hp, "_verified_at", None)
    monkeypatch.setenv("NEXUS_SECRET_HERMES_NATIVE_API_KEY", KEY)
    yield start
    for fake in servers:
        fake.server.shutdown()


async def run(db, agent, ctx_agent=None, *, turn=None, config=None, **ctx_kw):  # noqa: F811
    """One Hermes turn of ``agent`` on a running durable turn; returns (result, turn)."""
    turn = turn or await _turn(db, agent)
    ctx = _chat_ctx(turn.company_id, agent, **ctx_kw)
    adapter = HermesProviderAdapter()
    session = await adapter.create_session(agent, config or {})
    session.context = ctx
    result = await adapter.execute_task(session, uuid.UUID(turn.execution_id), {"prompt": "status?"})
    return result, turn


def calls(result):
    return [(a["name"], a["is_error"]) for a in result.artifacts if a["type"] == "tool_call"]


async def allow(db, company, agent, tool):  # noqa: F811
    async with db() as s:
        s.add(ToolPolicy(company_id=company, name=f"allow-{tool}", effect="allow",
                         conditions={"tool_name": [tool], "agent_id": [str(agent)]}))
        await s.commit()


class TestCatalogs:
    async def test_ceo_native_tool_call_runs_and_the_answer_returns(self, provider, db, c):  # noqa: F811
        await _appoint(c, c["chief"])
        fake = provider([tool_response(("call_1", "ceo_list_managers", {})), text_response("all quiet")])
        result, _ = await run(db, c["chief"], manager_tools_required=True)
        assert result.success and result.output == "all quiet"
        assert set(fake.offered()) == set(CEO_TOOLS) - WRITE_TOOLS  # writes need a ToolPolicy allow
        assert calls(result) == [("ceo_list_managers", False)]
        # The tool result went back as a role=tool message with the same ID.
        tool_msg = fake.requests[1]["body"]["messages"][-1]
        assert tool_msg["role"] == "tool" and tool_msg["tool_call_id"] == "call_1"
        assert (result.input_tokens, result.output_tokens) == (7, 3)
        assert fake.requests[0]["path"] == "/v1/chat/completions"
        assert fake.requests[0]["auth"] == f"Bearer {KEY}"

    async def test_manager_gets_only_manager_tools(self, provider, db, c):  # noqa: F811
        await _staffed(c)
        fake = provider([text_response("ok")])
        await run(db, c["lead"])
        offered = set(fake.offered())
        assert "manager_list_reports" in offered <= set(MANAGER_TOOLS) and not offered & set(CEO_TOOLS)

    async def test_snapshot_only_authorization_offers_only_the_snapshot(self, provider, db, c):  # noqa: F811
        await allow(db, c["acme"], c["lead"], org_snapshot.TOOL)
        fake = provider([text_response("ok")])
        await run(db, c["lead"])
        assert fake.offered() == [org_snapshot.TOOL]

    async def test_ordinary_employee_gets_no_tools_and_no_shell_tools_ever(self, provider, db, c):  # noqa: F811
        fake = provider([text_response("just text")])
        result, _ = await run(db, c["acme_agy"])
        assert result.output == "just text"
        assert "tools" not in fake.requests[0]["body"] and "tool_choice" not in fake.requests[0]["body"]

    async def test_offered_tools_are_never_host_tools(self, provider, db, c):  # noqa: F811
        await _appoint(c, c["chief"])
        fake = provider([text_response("ok")])
        await run(db, c["chief"], manager_tools_required=True)
        assert all(n.startswith(("ceo_", "manager_", "organization_")) for n in fake.offered())


class TestGovernance:
    async def test_write_tool_needs_an_exact_allow(self, provider, db, c):  # noqa: F811
        await _appoint(c, c["chief"])
        args = {"kind": "goal", "title": "Grow", "idempotency_key": "k1"}
        provider([tool_response(("a", "ceo_create_goal_or_work_order", args)), text_response("x")])
        result, _ = await run(db, c["chief"], manager_tools_required=True)
        assert "tool not offered" in result.error  # never offered, so never run
        assert not await _rows(db, Goal, Goal.title == "Grow")
        await allow(db, c["acme"], c["chief"], "ceo_create_goal_or_work_order")
        provider([tool_response(("a", "ceo_create_goal_or_work_order", args)), text_response("x")])
        result, _ = await run(db, c["chief"], manager_tools_required=True)
        assert calls(result) == [("ceo_create_goal_or_work_order", False)]
        assert len(await _rows(db, Goal, Goal.title == "Grow")) == 1

    async def test_a_retried_turn_does_not_duplicate_the_write(self, provider, db, c):  # noqa: F811
        await _appoint(c, c["chief"])
        await allow(db, c["acme"], c["chief"], "ceo_create_goal_or_work_order")
        args = {"kind": "goal", "title": "Once", "idempotency_key": "same"}
        for _ in range(2):  # recovery: a new execution of the same request
            provider([tool_response(("a", "ceo_create_goal_or_work_order", args)), text_response("x")])
            result, _ = await run(db, c["chief"], manager_tools_required=True)
            assert calls(result) == [("ceo_create_goal_or_work_order", False)]
        assert len(await _rows(db, Goal, Goal.title == "Once")) == 1

    async def test_model_supplied_identity_is_rejected(self, provider, db, c):  # noqa: F811
        await _appoint(c, c["chief"])
        forged = {"manager_id": str(c["lead"]), "company_id": str(c["other"]), "agent_id": str(c["deputy"])}
        provider([tool_response(("a", "ceo_get_manager_status", forged)), text_response("x")])
        result, _ = await run(db, c["chief"], manager_tools_required=True)
        assert calls(result) == [("ceo_get_manager_status", True)]

    async def test_audit_and_invocation_carry_the_turn_identity(self, provider, db, c):  # noqa: F811
        await _appoint(c, c["chief"])
        provider([tool_response(("a", "ceo_list_managers", {})), text_response("x")])
        result, turn = await run(db, c["chief"], manager_tools_required=True)
        (row,) = await _rows(db, ToolInvocation, ToolInvocation.tool_name == "ceo_list_managers")
        assert row.agent_id == c["chief"] and row.session_id == turn.session_id
        assert row.authorization_detail["turn_id"] == str(turn.id)
        assert row.authorization_detail["principal_id"] == f"run:{turn.execution_id}"

    async def test_executive_context_stays_snapshot_backed(self, provider, db, c):  # noqa: F811
        await _appoint(c, c["chief"])
        provider([tool_response(("a", "ceo_get_organization_snapshot", {})), text_response("x")])
        result, _ = await run(db, c["chief"], manager_tools_required=True)
        assert calls(result) == [("ceo_get_organization_snapshot", False)]


class TestFailClosed:
    async def _fails(self, provider, db, c, script, code, ran=False, **kw):  # noqa: F811
        await _appoint(c, c["chief"])
        fake = provider(script)
        result, _ = await run(db, c["chief"], manager_tools_required=True, **kw)
        assert not result.success and code in result.error
        assert ran or not await _rows(db, ToolInvocation)
        return fake, result

    async def test_tool_like_text_executes_nothing(self, provider, db, c):  # noqa: F811
        text = '<tool_call>{"name": "ceo_list_managers", "arguments": {}}</tool_call>'
        await self._fails(provider, db, c, [text_response(text)], "HERMES_NATIVE_TOOL_TEXT")

    async def test_unknown_tool_fails_closed(self, provider, db, c):  # noqa: F811
        await self._fails(provider, db, c, [tool_response(("a", "terminal", {"cmd": "id"}))],
                          "tool not offered")

    async def test_malformed_arguments_fail_closed(self, provider, db, c):  # noqa: F811
        bad = [chunk(call_delta(0, "a", "ceo_list_managers", "{not json")), chunk(finish="tool_calls")]
        await self._fails(provider, db, c, [bad], "not JSON")

    async def test_incomplete_call_fails_closed(self, provider, db, c):  # noqa: F811
        bad = [chunk(call_delta(0, "", "ceo_list_managers", "{}")), chunk(finish="tool_calls")]
        await self._fails(provider, db, c, [bad], "incomplete call")

    async def test_call_in_a_truncated_response_fails_closed(self, provider, db, c):  # noqa: F811
        bad = [chunk(call_delta(0, "a", "ceo_list_managers", "{}")), chunk(finish="length")]
        await self._fails(provider, db, c, [bad], "unfinished response")

    async def test_duplicate_call_id_fails_closed(self, provider, db, c):  # noqa: F811
        two = tool_response(("dup", "ceo_list_managers", {}), ("dup", "ceo_list_managers", {}))
        await self._fails(provider, db, c, [two], "duplicate call id")

    async def test_call_count_is_bounded(self, provider, db, c, monkeypatch):  # noqa: F811
        monkeypatch.setattr(hp, "MAX_CALLS", 2)
        script = [tool_response((f"c{i}", "ceo_list_managers", {})) for i in range(3)]
        await self._fails(provider, db, c, script, "too many tool calls", ran=True)

    async def test_iterations_are_bounded(self, provider, db, c, monkeypatch):  # noqa: F811
        monkeypatch.setattr(hp, "MAX_ITERATIONS", 2)
        script = [tool_response((f"c{i}", "ceo_list_managers", {})) for i in range(3)]
        fake, _ = await self._fails(provider, db, c, script, "too many model iterations", ran=True)
        assert len(fake.requests) == 2

    async def test_a_cancelled_turn_runs_no_tool(self, provider, db, c):  # noqa: F811
        await _appoint(c, c["chief"])
        turn = await _turn(db, c["chief"], cancelled=True)
        provider([tool_response(("a", "ceo_list_managers", {}))])
        result, _ = await run(db, c["chief"], turn=turn, manager_tools_required=True)
        assert not result.success and "HERMES_NATIVE_CANCELLED" in result.error
        assert not await _rows(db, ToolInvocation)

    async def test_a_turn_cancelled_mid_run_stops_before_the_next_tool(self, provider, db, c, monkeypatch):  # noqa: F811
        await _appoint(c, c["chief"])
        real, n = mb.bind, []

        async def bind(*a):
            n.append(1)
            if len(n) > 1:
                raise mb.BridgeDeniedError("cancelled")
            return await real(*a)

        monkeypatch.setattr(mb, "bind", bind)
        provider([tool_response(("a", "ceo_list_managers", {}))])
        result, _ = await run(db, c["chief"], manager_tools_required=True)
        assert "HERMES_NATIVE_CANCELLED" in result.error and not await _rows(db, ToolInvocation)

    async def test_a_lost_execution_runs_no_tool(self, provider, db, c):  # noqa: F811
        await _appoint(c, c["chief"])
        turn = await _turn(db, c["chief"])
        async with db() as s:  # recovery claimed the turn under another execution
            await s.execute(update(ChatTurn).where(ChatTurn.id == turn.id)
                            .values(execution_id=str(uuid.uuid4())))
            await s.commit()
        provider([tool_response(("a", "ceo_list_managers", {}))])
        result, _ = await run(db, c["chief"], turn=turn, manager_tools_required=True)
        assert "HERMES_NATIVE_CANCELLED" in result.error

    async def test_timeout_fails_the_turn(self, provider, db, c, monkeypatch):  # noqa: F811
        monkeypatch.setattr(hp, "TOTAL_TIMEOUT_SECONDS", 0.2)
        await _appoint(c, c["chief"])
        provider([text_response("late")]).delay = 1.0
        result, _ = await run(db, c["chief"], manager_tools_required=True)
        assert result.error == "HERMES_NATIVE_TIMEOUT"

    async def test_http_error_fails_without_fallback(self, provider, db, c):  # noqa: F811
        fake, result = await self._fails(provider, db, c, [500], "HERMES_NATIVE_HTTP_500")
        assert len(fake.requests) == 1

    async def test_a_missing_key_fails_without_a_request(self, provider, db, c, monkeypatch):  # noqa: F811
        monkeypatch.delenv("NEXUS_SECRET_HERMES_NATIVE_API_KEY")
        fake, result = await self._fails(provider, db, c, [text_response("x")], "HERMES_NATIVE_KEY_MISSING")
        assert fake.requests == []

    async def test_plain_http_to_a_remote_host_is_refused(self, provider, db, c, monkeypatch):  # noqa: F811
        provider([text_response("x")])
        monkeypatch.setattr(settings, "hermes_native_base_url", "http://example.com/v1")
        result, _ = await run(db, c["acme_agy"])
        assert "HERMES_NATIVE_ENDPOINT_INVALID" in result.error


class TestSecretsAndWiring:
    async def test_the_key_never_reaches_the_result_or_the_prompt(self, provider, db, c):  # noqa: F811
        fake = provider([text_response("fine")])
        result, _ = await run(db, c["acme_agy"])
        assert KEY not in json.dumps([result.output, result.error, result.logs, result.artifacts])
        assert KEY not in json.dumps(fake.requests[0]["body"])
        rows = [*(await _rows(db, AuditLog)), *(await _rows(db, ToolInvocation)), *(await _rows(db, ChatTurn))]
        assert KEY not in json.dumps([r.model_dump() for r in rows], default=str)

    async def test_an_error_carrying_the_key_is_redacted(self, provider, db, c):  # noqa: F811
        adapter = HermesProviderAdapter()
        session = await adapter.create_session(c["acme_agy"], {})
        failed = adapter._fail(session, uuid.uuid4(), f"boom {KEY}", KEY)
        assert KEY not in failed.error and hp.REDACTED in failed.error

    async def test_normal_text_response(self, provider, db, c):  # noqa: F811
        provider([text_response("hello there")])
        result, _ = await run(db, c["acme_agy"])
        assert result.success and result.output == "hello there" and calls(result) == []

    async def test_free_form_text_is_not_a_fallback_path(self, provider, db, c):  # noqa: F811
        await _appoint(c, c["chief"])
        provider([text_response("I will call ceo_list_managers now")])
        result, _ = await run(db, c["chief"], manager_tools_required=True)
        assert result.success and calls(result) == []

    def test_registration_and_no_register_tool(self):
        key, config = resolve_provider("hermes-native")
        assert key == "hermes_native" and config["model"] == ""
        adapter = AdapterRegistry().create_adapter(key)
        assert isinstance(adapter, HermesProviderAdapter) and not hasattr(adapter, "register_tool")



class TestGateAndConfiguration:
    async def test_gate_off_fails_a_tool_turn_before_any_request(self, provider, db, c, monkeypatch):  # noqa: F811
        await _appoint(c, c["chief"])
        fake = provider([text_response("x")])
        monkeypatch.setattr(settings, "hermes_native_tools_enabled", False)
        result, _ = await run(db, c["chief"], manager_tools_required=True)
        assert "HERMES_NATIVE_TOOLS_DISABLED" in result.error and fake.requests == []

    async def test_the_gate_cannot_come_from_agent_config(self, provider, db, c, monkeypatch):  # noqa: F811
        await _appoint(c, c["chief"])
        fake = provider([text_response("x")])
        monkeypatch.setattr(settings, "hermes_native_tools_enabled", False)
        forged = {"hermes_native_tools_enabled": True, "enabled": True, "base_url": "http://evil"}
        result, _ = await run(db, c["chief"], config=forged, manager_tools_required=True)
        assert "HERMES_NATIVE_TOOLS_DISABLED" in result.error and fake.requests == []

    async def test_a_gate_off_employee_chat_without_tools_still_answers(self, provider, db, c, monkeypatch):  # noqa: F811
        provider([text_response("hi")])
        monkeypatch.setattr(settings, "hermes_native_tools_enabled", False)
        result, _ = await run(db, c["acme_agy"])
        assert result.success

    async def test_tool_support_needs_gate_endpoint_secret_and_model(self, provider, db, c, monkeypatch):  # noqa: F811
        provider([])
        async with db() as s:
            agent = await s.get(Agent, c["chief"])
            agent.adapter_type = "hermes-native"
            assert ceo_service.tool_support(agent) == (True, None)
            for name, value, code in [
                ("hermes_native_tools_enabled", False, "HERMES_NATIVE_TOOLS_DISABLED"),
                ("hermes_native_base_url", "", "HERMES_NATIVE_ENDPOINT_MISSING"),
                ("hermes_native_model", "", "HERMES_NATIVE_MODEL_MISSING"),
                ("hermes_native_secret_ref", "absent-ref", "HERMES_NATIVE_KEY_MISSING"),
            ]:
                with monkeypatch.context() as m:
                    m.setattr(settings, name, value)
                    ok, reason = ceo_service.tool_support(agent)
                    assert not ok and reason.startswith("CEO_TOOLS_UNSUPPORTED") and code in reason

    async def test_legacy_hermes_never_satisfies_ceo_tools(self, provider, db, c):  # noqa: F811
        provider([])  # the native gate is fully on: legacy hermes still gets no fallback
        async with db() as s:
            agent = await s.get(Agent, c["chief"])  # cli backend hermes
            assert ceo_service.tool_support(agent)[1].startswith("CEO_TOOLS_UNSUPPORTED")
            for legacy in ("hermes", "hermes-cli"):
                agent.adapter_type = legacy
                ok, reason = ceo_service.tool_support(agent)
                assert not ok and reason.startswith("CEO_TOOLS_UNSUPPORTED")

    async def test_only_an_approved_model_is_used(self, provider, db, c, monkeypatch):  # noqa: F811
        fake = provider([text_response("a"), text_response("b")])
        monkeypatch.setattr(settings, "hermes_native_models", "alias-two")
        ok, _ = await run(db, c["acme_agy"], config={"model": "alias-two"})
        assert ok.success and fake.requests[0]["body"]["model"] == "alias-two"
        bad, _ = await run(db, c["acme_agy"], config={"model": "https://evil/x"})
        assert "HERMES_NATIVE_MODEL_NOT_APPROVED" in bad.error and len(fake.requests) == 1

    async def test_a_redirect_is_not_followed(self, provider, db, c):  # noqa: F811
        fake = provider([302])
        result, _ = await run(db, c["acme_agy"])
        assert "HERMES_NATIVE_HTTP_302" in result.error and len(fake.requests) == 1

    async def test_private_literal_and_plain_remote_endpoints_are_refused(self, provider, db, c, monkeypatch):  # noqa: F811
        fake = provider([text_response("x")])
        for url in ("https://10.0.0.5/v1", "http://example.com/v1", "ftp://x/v1"):
            monkeypatch.setattr(settings, "hermes_native_base_url", url)
            result, _ = await run(db, c["acme_agy"])
            assert "HERMES_NATIVE_ENDPOINT_INVALID" in result.error
        assert fake.requests == []

    async def test_no_endpoint_configured_fails_before_any_request(self, provider, db, c, monkeypatch):  # noqa: F811
        provider([])
        monkeypatch.setattr(settings, "hermes_native_base_url", "")
        result, _ = await run(db, c["acme_agy"])
        assert "HERMES_NATIVE_ENDPOINT_MISSING" in result.error

    async def test_status_and_probe_reveal_no_secret_and_send_the_key_only_to_the_endpoint(self, provider):  # noqa: F811
        fake = provider([])
        before = hp.status()
        assert before == {"enabled": True, "endpoint_configured": True, "secret_configured": True,
                          "model_configured": True, "native_tools": "unverified",
                          "last_verified_at": None}
        assert KEY not in json.dumps(before)
        probed = await hp.probe()
        assert probed["reachable"] is True and KEY not in json.dumps(probed)
        assert fake.requests == [{"path": "/v1/models", "auth": f"Bearer {KEY}"}]

    async def test_probe_without_a_secret_makes_no_request(self, provider, monkeypatch):  # noqa: F811
        fake = provider([])
        monkeypatch.delenv("NEXUS_SECRET_HERMES_NATIVE_API_KEY")
        assert (await hp.probe())["reachable"] is False and fake.requests == []

    async def test_a_native_tool_call_marks_the_provider_verified(self, provider, db, c):  # noqa: F811
        await _appoint(c, c["chief"])
        provider([tool_response(("a", "ceo_list_managers", {})), text_response("x")])
        await run(db, c["chief"], manager_tools_required=True)
        assert hp.status()["native_tools"] == "verified" and hp.status()["last_verified_at"]
