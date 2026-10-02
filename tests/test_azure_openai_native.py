# ruff: noqa: E501
"""Azure OpenAI governed streaming provider against a deterministic local fake server.

No real Azure, model or paid call: the adapter talks to a loopback server that streams
scripted chat completions, with an injected token source instead of a real Entra login.
The CEO, manager, turn and budget fixtures are the existing ones.
"""

from __future__ import annotations

import ast
import asyncio
import json
import logging
import select
import socket
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace

import pytest

from nexus.adapters import azure_openai_native as ao
from nexus.adapters import governed_loop as gl
from nexus.adapters.azure_openai_native import AzureOpenAINativeAdapter
from nexus.adapters.governed_loop import ProviderError
from nexus.adapters.registry import AdapterRegistry
from nexus.adapters.uastl import resolve_provider
from nexus.config import Settings, settings
from nexus.models.agent import Agent
from nexus.models.budget import BudgetPolicy, CostEvent
from nexus.models.governance import AuditLog
from nexus.models.tool import ToolPolicy
from nexus.models.tool_invocation import ToolInvocation
from nexus.services import ceo_service
from nexus.tools.ceo_tools import CEO_TOOLS, WRITE_TOOLS
from tests.test_ceo_control_plane import _appoint, c  # noqa: F401 -- fixtures
from tests.test_employee_work import _rows, db, w  # noqa: F401 -- fixtures
from tests.test_hermes_provider import allow, call_delta, calls, chunk, text_response, tool_response
from tests.test_manager_bridge import _chat_ctx, _turn
from tests.test_manager_core import _staffed, team  # noqa: F401 -- fixtures

pytestmark = pytest.mark.employee_work

KEY = "az-key-not-a-real-key-456"
TOKEN = "entra-token-not-real-789"
# The live-validated scope for *.openai.azure.com, written out so a code change cannot move it silently.
SCOPE = "https://ai.azure.com/.default"
DEPLOYMENT = "ceo-deployment"
MODEL = "gpt-4o"


class Raw:
    """Pre-encoded SSE byte fragments, each written (and flushed) on its own."""

    def __init__(self, *parts: bytes):
        self.parts = parts


class Stall:
    """Send ``chunks`` then hold the stream open for ``hold`` seconds (until the client leaves)."""

    def __init__(self, chunks, hold=10.0):
        self.chunks, self.hold = chunks, hold


class Trickle:
    """Keep sending a harmless comment line forever: defeats any per-read timeout."""


class Status:
    def __init__(self, code, retry_after=None):
        self.code, self.retry_after = code, retry_after


class Fake:
    """Serves ``script`` (one step per request), records requests and client disconnects."""

    def __init__(self, script):
        self.script, self.requests, self.delay = list(script), [], 0.0
        self.client_closed = threading.Event()
        fake = self

        class Handler(BaseHTTPRequestHandler):
            def _gone(self):
                try:
                    ready, _, _ = select.select([self.connection], [], [], 0.02)
                    return bool(ready) and self.connection.recv(1, socket.MSG_PEEK) == b""
                except OSError:
                    return True

            def _send(self, data: bytes):
                self.wfile.write(data)
                self.wfile.flush()

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers["content-length"])))
                fake.requests.append({"body": body, "auth": self.headers.get("Authorization"),
                                      "api_key": self.headers.get("api-key"), "path": self.path})
                try:
                    self._serve()
                except OSError:
                    fake.client_closed.set()

            def _serve(self):
                if fake.delay:  # before the first byte
                    end = time.monotonic() + fake.delay
                    while time.monotonic() < end:
                        if self._gone():
                            fake.client_closed.set()
                            return
                step = fake.script.pop(0) if fake.script else text_response("done")
                if isinstance(step, Status):
                    self.send_response(step.code)
                    if step.retry_after is not None:
                        self.send_header("Retry-After", str(step.retry_after))
                    self.end_headers()
                    return
                self.send_response(200)
                self.send_header("content-type", "text/event-stream")
                self.end_headers()
                if isinstance(step, Raw):
                    for part in step.parts:
                        self._send(part)
                        time.sleep(0.03)
                    return
                if isinstance(step, Trickle):
                    while True:
                        self._send(b": keep-alive\n\n")
                        time.sleep(0.05)
                chunks = step.chunks if isinstance(step, Stall) else step
                for part in chunks:
                    self._send(f"data: {json.dumps(part)}\n\n".encode())
                if isinstance(step, Stall):
                    end = time.monotonic() + step.hold
                    while time.monotonic() < end:
                        if self._gone():
                            fake.client_closed.set()
                            return
                    return
                self._send(b"data: [DONE]\n\n")

            def log_message(self, *a):
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.server.daemon_threads = True
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"

    def offered(self, request=0):
        return [t["function"]["name"] for t in self.requests[request]["body"].get("tools", [])]


@pytest.fixture
def azure(monkeypatch):
    servers, sleeps, scopes = [], [], []

    def start(script):
        fake = Fake(script)
        servers.append(fake)
        monkeypatch.setattr(settings, "azure_openai_endpoint", fake.url)
        return fake

    async def token_source(scope):
        scopes.append(scope)
        return TOKEN

    async def no_sleep(seconds):
        sleeps.append(seconds)

    monkeypatch.setattr(settings, "secret_backend", "env")
    monkeypatch.setattr(settings, "azure_openai_enabled", True)
    monkeypatch.setattr(settings, "azure_openai_deployment", DEPLOYMENT)
    monkeypatch.setattr(settings, "azure_openai_model", MODEL)
    monkeypatch.setattr(settings, "azure_openai_api_version", "v1")
    monkeypatch.setattr(settings, "azure_openai_auth", "entra")
    monkeypatch.setattr(settings, "azure_openai_timeout_seconds", 20.0)
    monkeypatch.setattr(settings, "azure_openai_max_retries", 2)
    monkeypatch.setattr(ao, "_token_source", token_source)
    monkeypatch.setattr(ao, "_sleep", no_sleep)
    start.sleeps, start.scopes = sleeps, scopes
    yield start
    for fake in servers:
        fake.server.shutdown()


async def run(db, agent, *, turn=None, config=None, payload=None, **ctx_kw):  # noqa: F811
    """One Azure turn of ``agent`` on a running durable turn; returns (result, turn)."""
    turn = turn or await _turn(db, agent)
    ctx = _chat_ctx(turn.company_id, agent, **ctx_kw)
    adapter = AzureOpenAINativeAdapter()
    session = await adapter.create_session(agent, config or {})
    session.context = ctx
    result = await adapter.execute_task(
        session, uuid.UUID(turn.execution_id), {"prompt": "status?", **(payload or {})}
    )
    return result, turn


async def budget(db, company, amount):  # noqa: F811
    async with db() as s:
        s.add(BudgetPolicy(company_id=company, scope_type="company", scope_id=company, metric="cost_cents",
                           window_kind="monthly", amount=amount, hard_stop_enabled=True))
        await s.commit()


async def events(db, company):  # noqa: F811
    return sorted(await _rows(db, CostEvent, CostEvent.company_id == company), key=lambda e: e.created_at)


async def wait_for(condition, seconds=5.0):
    end = time.monotonic() + seconds
    while not condition():
        assert time.monotonic() < end, "condition not reached"
        await asyncio.sleep(0.02)


class TestStreaming:
    async def test_text_turn_over_the_v1_route_with_a_bearer_token(self, azure, db, c):  # noqa: F811
        fake = azure([text_response("hello there")])
        result, _ = await run(db, c["acme_agy"])
        assert result.success and result.output == "hello there"
        req = fake.requests[0]
        assert req["path"] == "/openai/v1/chat/completions" and req["auth"] == f"Bearer {TOKEN}"
        assert req["api_key"] is None
        assert req["body"]["model"] == DEPLOYMENT and req["body"]["stream"] is True
        assert req["body"]["stream_options"] == {"include_usage": True}
        assert req["body"]["max_completion_tokens"] == ao.MAX_TOKENS and "max_tokens" not in req["body"]
        assert "tools" not in req["body"]
        assert azure.scopes == [SCOPE]

    async def test_a_split_utf8_character_and_split_json_are_reassembled(self, azure, db, c):  # noqa: F811
        text = "héllo wörld 🙂 ünï"
        line = ("data: " + json.dumps(chunk({"content": text}), ensure_ascii=False) + "\n\n").encode()
        done = ("data: " + json.dumps(chunk(finish="stop", usage={"prompt_tokens": 4, "completion_tokens": 2})) + "\n\n").encode()
        cut = line.index("🙂".encode()) + 2  # inside the four-byte character
        azure([Raw(line[:7], line[7:cut], line[cut:], done, b"data: [DONE]\n\n")])
        result, _ = await run(db, c["acme_agy"])
        assert result.success and result.output == text

    async def test_tool_call_fragments_and_the_round_trip(self, azure, db, c):  # noqa: F811
        await _appoint(c, c["chief"])
        fake = azure([tool_response(("call_1", "ceo_list_managers", {})), text_response("all quiet")])
        result, _ = await run(db, c["chief"], manager_tools_required=True)
        assert result.success and result.output == "all quiet"
        assert set(fake.offered()) == set(CEO_TOOLS) - WRITE_TOOLS
        assert fake.requests[0]["body"]["tool_choice"] == "auto"
        tool_msg = fake.requests[1]["body"]["messages"][-1]
        assert tool_msg["role"] == "tool" and tool_msg["tool_call_id"] == "call_1"
        assistant = fake.requests[1]["body"]["messages"][-2]
        assert assistant["tool_calls"][0]["id"] == "call_1"
        assert calls(result) == [("ceo_list_managers", False)]
        assert len(await _rows(db, ToolInvocation, ToolInvocation.tool_name == "ceo_list_managers")) == 1

    async def test_several_tool_calls_in_one_response_each_run_once_in_order(self, azure, db, c):  # noqa: F811
        await _appoint(c, c["chief"])
        two = tool_response(("a", "ceo_list_managers", {}), ("b", "ceo_get_organization_snapshot", {}))
        fake = azure([two, text_response("done")])
        result, _ = await run(db, c["chief"], manager_tools_required=True)
        assert calls(result) == [("ceo_list_managers", False), ("ceo_get_organization_snapshot", False)]
        followup = [m for m in fake.requests[1]["body"]["messages"] if m["role"] == "tool"]
        assert [m["tool_call_id"] for m in followup] == ["a", "b"]
        assert len(await _rows(db, ToolInvocation)) == 2  # no duplicate execution

    async def test_the_event_contract(self, azure, db, c):  # noqa: F811
        await _appoint(c, c["chief"])
        mixed = [chunk({"content": "let me check "}), *tool_response(("a", "ceo_list_managers", {}))]
        azure([mixed, text_response("all quiet")])
        seen: list[gl.Event] = []
        result, _ = await run(db, c["chief"], payload={"on_event": seen.append}, manager_tools_required=True)
        kinds = [e.type for e in seen]
        assert result.output == "all quiet"
        assert kinds[-1] == gl.COMPLETED and gl.CANCELLED not in kinds and gl.ERROR not in kinds
        order = [k for k in kinds if k in (gl.TOOL_REQUESTED, gl.TOOL_RUNNING, gl.TOOL_COMPLETED, gl.TEXT_DELTA)]
        assert order == [gl.TOOL_REQUESTED, gl.TOOL_RUNNING, gl.TOOL_COMPLETED, gl.TEXT_DELTA, gl.TEXT_DELTA]
        # The tool round's text never reaches a consumer; no arguments are ever carried.
        assert "let me check" not in "".join(e.text for e in seen)
        assert all(not hasattr(e, "arguments") for e in seen)
        assert [e.usage for e in seen if e.type == gl.USAGE_UPDATE][-1] == {"prompt_tokens": 7, "completion_tokens": 3}
        assert seen[-1].usage == {"prompt_tokens": 7, "completion_tokens": 3}
        requested = next(e for e in seen if e.type == gl.TOOL_REQUESTED)
        assert (requested.tool_call_id, requested.name) == ("a", "ceo_list_managers")

    async def test_a_failing_callback_cannot_skip_the_tool_audit_or_budget(self, azure, db, c):  # noqa: F811
        await _appoint(c, c["chief"])
        await budget(db, c["acme"], 1000)
        azure([tool_response(("a", "ceo_list_managers", {})), text_response("fine")])

        def boom(event):
            raise RuntimeError("consumer exploded")

        result, _ = await run(db, c["chief"], payload={"on_event": boom}, manager_tools_required=True)
        assert result.success and result.output == "fine"
        assert len(await _rows(db, ToolInvocation, ToolInvocation.tool_name == "ceo_list_managers")) == 1
        assert {e.status for e in await events(db, c["acme"])} == {"committed"}

    async def test_the_dated_route_names_the_deployment_and_uses_a_key(self, azure, db, c, monkeypatch):  # noqa: F811
        monkeypatch.setattr(settings, "azure_openai_api_version", "2024-10-21")
        monkeypatch.setattr(settings, "azure_openai_auth", "key")
        monkeypatch.setenv("NEXUS_SECRET_AZURE_OPENAI_API_KEY", KEY)
        fake = azure([text_response("ok")])
        result, _ = await run(db, c["acme_agy"])
        req = fake.requests[0]
        assert result.success
        assert req["path"] == f"/openai/deployments/{DEPLOYMENT}/chat/completions?api-version=2024-10-21"
        assert "model" not in req["body"] and req["body"]["max_tokens"] == ao.MAX_TOKENS
        assert req["api_key"] == KEY and req["auth"] is None


class TestFailClosed:
    async def _fails(self, azure, db, c, script, code, ran=False, **kw):  # noqa: F811
        await _appoint(c, c["chief"])
        fake = azure(script)
        result, _ = await run(db, c["chief"], manager_tools_required=True, **kw)
        assert not result.success and code in result.error
        assert ran or not await _rows(db, ToolInvocation)
        return fake, result

    async def test_text_form_tool_instructions_are_rejected(self, azure, db, c):  # noqa: F811
        text = '<tool_call>{"name": "ceo_list_managers", "arguments": {}}</tool_call>'
        await self._fails(azure, db, c, [text_response(text)], "AZURE_OPENAI_TOOL_TEXT")

    async def test_tool_json_in_text_is_rejected(self, azure, db, c):  # noqa: F811
        text = '{"tool_calls": [{"name": "ceo_list_managers"}]}'
        await self._fails(azure, db, c, [text_response(text)], "AZURE_OPENAI_TOOL_TEXT")

    async def test_a_text_mention_is_not_a_tool_call(self, azure, db, c):  # noqa: F811
        await _appoint(c, c["chief"])
        azure([text_response("I will call ceo_list_managers now")])
        result, _ = await run(db, c["chief"], manager_tools_required=True)
        assert result.success and calls(result) == []

    async def test_malformed_arguments_fail_closed(self, azure, db, c):  # noqa: F811
        bad = [chunk(call_delta(0, "a", "ceo_list_managers", "{not json")), chunk(finish="tool_calls")]
        await self._fails(azure, db, c, [bad], "not JSON")

    async def test_unexpected_arguments_are_rejected_by_the_tool(self, azure, db, c):  # noqa: F811
        await _appoint(c, c["chief"])
        azure([tool_response(("a", "ceo_get_manager_status", {"company_id": str(uuid.uuid4()), "extra": 1})),
               text_response("x")])
        result, _ = await run(db, c["chief"], manager_tools_required=True)
        assert calls(result) == [("ceo_get_manager_status", True)]

    async def test_unknown_tool_fails_closed(self, azure, db, c):  # noqa: F811
        await self._fails(azure, db, c, [tool_response(("a", "terminal", {"cmd": "id"}))], "tool not offered")

    async def test_the_loop_is_capped(self, azure, db, c, monkeypatch):  # noqa: F811
        monkeypatch.setattr(ao, "MAX_ITERATIONS", 2)
        script = [tool_response((f"c{i}", "ceo_list_managers", {})) for i in range(3)]
        fake, _ = await self._fails(azure, db, c, script, "too many model iterations", ran=True)
        assert len(fake.requests) == 2

    async def test_the_call_count_is_capped(self, azure, db, c, monkeypatch):  # noqa: F811
        monkeypatch.setattr(ao, "MAX_CALLS", 2)
        script = [tool_response((f"c{i}", "ceo_list_managers", {})) for i in range(3)]
        await self._fails(azure, db, c, script, "too many tool calls", ran=True)

    async def test_tool_policy_deny_blocks_the_tool(self, azure, db, c):  # noqa: F811
        await _appoint(c, c["chief"])
        async with db() as s:
            s.add(ToolPolicy(company_id=c["acme"], name="deny-list", effect="deny",
                             conditions={"tool_name": ["ceo_list_managers"], "agent_id": [str(c["chief"])]}))
            await s.commit()
        azure([tool_response(("a", "ceo_list_managers", {})), text_response("x")])
        result, _ = await run(db, c["chief"], manager_tools_required=True)
        executed = [a for a in calls(result) if a == ("ceo_list_managers", False)]
        assert not executed  # either never offered or refused: never run
        assert not [r for r in await _rows(db, ToolInvocation) if r.tool_name == "ceo_list_managers" and r.status == "success"]

    async def test_a_write_tool_needs_an_exact_allow(self, azure, db, c):  # noqa: F811
        await _appoint(c, c["chief"])
        args = {"kind": "goal", "title": "Azure", "idempotency_key": "k1"}
        azure([tool_response(("a", "ceo_create_goal_or_work_order", args)), text_response("x")])
        result, _ = await run(db, c["chief"], manager_tools_required=True)
        assert "tool not offered" in result.error
        await allow(db, c["acme"], c["chief"], "ceo_create_goal_or_work_order")
        azure([tool_response(("a", "ceo_create_goal_or_work_order", args)), text_response("x")])
        result, _ = await run(db, c["chief"], manager_tools_required=True)
        assert calls(result) == [("ceo_create_goal_or_work_order", False)]

    async def test_audit_and_invocation_carry_the_turn_identity(self, azure, db, c):  # noqa: F811
        await _appoint(c, c["chief"])
        azure([tool_response(("a", "ceo_list_managers", {})), text_response("x")])
        result, turn = await run(db, c["chief"], manager_tools_required=True)
        (row,) = await _rows(db, ToolInvocation, ToolInvocation.tool_name == "ceo_list_managers")
        assert row.agent_id == c["chief"] and row.session_id == turn.session_id
        assert row.authorization_detail["turn_id"] == str(turn.id)
        assert row.authorization_detail["principal_id"] == f"run:{turn.execution_id}"

    async def test_model_supplied_identity_is_rejected(self, azure, db, c):  # noqa: F811
        await _appoint(c, c["chief"])
        forged = {"manager_id": str(c["lead"]), "company_id": str(c["other"]), "agent_id": str(c["deputy"])}
        azure([tool_response(("a", "ceo_get_manager_status", forged)), text_response("x")])
        result, _ = await run(db, c["chief"], manager_tools_required=True)
        assert calls(result) == [("ceo_get_manager_status", True)]


class TestHttpAndRetries:
    @pytest.mark.parametrize("code", [401, 403])
    async def test_auth_failures_are_not_retried(self, azure, db, c, code):  # noqa: F811
        fake = azure([Status(code), text_response("never")])
        result, _ = await run(db, c["acme_agy"])
        assert result.error == f"AZURE_OPENAI_HTTP_{code}" and len(fake.requests) == 1
        assert TOKEN not in result.error

    async def test_a_429_is_retried_then_succeeds(self, azure, db, c):  # noqa: F811
        fake = azure([Status(429, retry_after=1), Status(429, retry_after=99), text_response("ok")])
        result, _ = await run(db, c["acme_agy"])
        assert result.success and len(fake.requests) == 3
        assert azure.sleeps == [1.0, ao.RETRY_AFTER_CAP_SECONDS]  # Retry-After is honored but capped

    async def test_retries_are_bounded(self, azure, db, c):  # noqa: F811
        fake = azure([Status(429)] * 10)
        result, _ = await run(db, c["acme_agy"])
        assert result.error == "AZURE_OPENAI_HTTP_429" and len(fake.requests) == 3  # 1 + 2 retries

    async def test_a_5xx_is_retried_once_then_succeeds_and_a_persistent_one_fails(self, azure, db, c):  # noqa: F811
        fake = azure([Status(503), text_response("ok")])
        assert (await run(db, c["acme_agy"]))[0].success and len(fake.requests) == 2
        fake = azure([Status(500)] * 5)
        result, _ = await run(db, c["acme_agy"])
        assert result.error == "AZURE_OPENAI_HTTP_500" and len(fake.requests) == 3

    async def test_a_4xx_other_than_429_is_final(self, azure, db, c):  # noqa: F811
        fake = azure([Status(400), text_response("never")])
        result, _ = await run(db, c["acme_agy"])
        assert result.error == "AZURE_OPENAI_HTTP_400" and len(fake.requests) == 1

    async def test_a_redirect_is_not_followed(self, azure, db, c):  # noqa: F811
        fake = azure([Status(302)])
        result, _ = await run(db, c["acme_agy"])
        assert result.error == "AZURE_OPENAI_HTTP_302" and len(fake.requests) == 1

    async def test_malformed_sse_fails_the_turn(self, azure, db, c):  # noqa: F811
        azure([Raw(b"data: {not json\n\n")])
        result, _ = await run(db, c["acme_agy"])
        assert "AZURE_OPENAI_BAD_RESPONSE" in result.error

    async def test_no_fallback_to_another_provider(self, azure, db, c):  # noqa: F811
        from nexus.adapters import hermes_provider

        azure([Status(500)] * 5)
        result, _ = await run(db, c["acme_agy"])
        assert not result.success and not result.output
        names = {n.id for n in ast.walk(ast.parse(Path(ao.__file__).read_text(encoding="utf-8"))) if isinstance(n, ast.Name)}
        assert not names & {"hermes_provider", "azure_adapter", "AzureOpenAIAdapter", "HermesProviderAdapter"}
        assert hermes_provider.status()["endpoint_configured"] is False  # untouched


class TestBudget:
    async def test_a_round_reserves_then_settles_on_authoritative_usage(self, azure, db, c):  # noqa: F811
        await budget(db, c["acme"], 1000)
        azure([[chunk({"content": "hi"}), chunk(finish="stop", usage={"prompt_tokens": 1000, "completion_tokens": 500})]])
        result, turn = await run(db, c["acme_agy"], session_id=None)
        rows = await events(db, c["acme"])
        assert result.success and {r.status for r in rows} == {"committed"}
        assert {(r.input_tokens, r.output_tokens) for r in rows} == {(1000, 500)}
        assert all(r.company_id == c["acme"] and r.agent_id == c["acme_agy"] for r in rows)

    async def test_missing_usage_settles_a_conservative_nonzero_estimate(self, azure, db, c):  # noqa: F811
        await budget(db, c["acme"], 1000)
        azure([[chunk({"content": "x" * 900}), chunk(finish="stop")]])
        result, _ = await run(db, c["acme_agy"])
        rows = await events(db, c["acme"])
        assert result.success and {r.status for r in rows} == {"committed"}
        assert all(r.cost_cents >= 1 and r.input_tokens > 0 and r.output_tokens >= 300 for r in rows)

    async def test_every_tool_round_is_metered_separately(self, azure, db, c):  # noqa: F811
        await _appoint(c, c["chief"])
        await budget(db, c["acme"], 1000)
        azure([tool_response(("a", "ceo_list_managers", {})), text_response("done")])
        result, _ = await run(db, c["chief"], manager_tools_required=True)
        rows = [r for r in await events(db, c["acme"]) if r.agent_id == c["chief"]]
        assert result.success and len(rows) == 2 and {r.status for r in rows} == {"committed"}

    async def test_streaming_cannot_bypass_an_exhausted_budget(self, azure, db, c):  # noqa: F811
        await budget(db, c["acme"], 1)
        await budget(db, c["acme"], 1)
        fake = azure([text_response("never")])
        async with db() as s:  # spend the whole cap already
            policy = (await s.execute(__import__("sqlalchemy").select(BudgetPolicy))).scalars().first()
            policy.spent_cents = 1
            await s.commit()
        result, _ = await run(db, c["acme_agy"])
        assert result.error == "AZURE_OPENAI_BUDGET_EXCEEDED" and fake.requests == []

    async def test_a_later_round_is_refused_once_an_earlier_one_used_the_budget(self, azure, db, c):  # noqa: F811
        await _appoint(c, c["chief"])
        await budget(db, c["acme"], 100)  # roomy enough for round one's reservation
        heavy = [*tool_response(("a", "ceo_list_managers", {})),
                 chunk(usage={"prompt_tokens": 5_000_000, "completion_tokens": 1000})]  # then spends it all
        fake = azure([heavy, text_response("never")])
        result, _ = await run(db, c["chief"], manager_tools_required=True)
        assert result.error == "AZURE_OPENAI_BUDGET_EXCEEDED" and len(fake.requests) == 1
        rows = await events(db, c["acme"])
        assert [r.status for r in rows] == ["committed"]  # round one's spend is not lost

    async def test_a_ledger_outage_fails_closed(self, azure, db, c, monkeypatch):  # noqa: F811
        from nexus.services import budget_service

        async def down(*a, **kw):
            raise ConnectionError("ledger down")

        monkeypatch.setattr(budget_service.BudgetService, "reserve_chain", down)
        monkeypatch.setattr(settings, "budget_fail_open", False)
        fake = azure([text_response("never")])
        result, _ = await run(db, c["acme_agy"])
        assert result.error == "AZURE_OPENAI_BUDGET_UNAVAILABLE" and fake.requests == []

    async def test_a_refused_request_releases_the_hold(self, azure, db, c):  # noqa: F811
        await budget(db, c["acme"], 1000)
        azure([Status(401)])
        result, _ = await run(db, c["acme_agy"])
        rows = await events(db, c["acme"])
        assert not result.success and rows and {r.status for r in rows} == {"released"}
        assert all(r.cost_cents == 0 for r in rows)

    async def test_cost_events_link_to_the_session_and_settlement_logs_the_full_identity(self, azure, db, c, caplog):  # noqa: F811
        await budget(db, c["acme"], 1000)
        turn = await _turn(db, c["acme_agy"])
        azure([text_response("ok")])
        with caplog.at_level(logging.INFO, logger="nexus.services.streaming_budget"):
            await run(db, c["acme_agy"], turn=turn, session_id=turn.session_id, payload={"turn_id": str(turn.id)})
        rows = await events(db, c["acme"])
        assert rows and {r.session_id for r in rows} == {turn.session_id}
        line = next(m for m in caplog.messages if "streamed round settled" in m)
        for ident in (turn.company_id, turn.agent_id, turn.id, turn.execution_id):
            assert str(ident) in line


class TestCancellationAndTimeout:
    async def _start(self, db, agent, **kw):  # noqa: F811
        turn = await _turn(db, agent)
        task = asyncio.ensure_future(run(db, agent, turn=turn, **kw))
        return turn, task

    async def test_cancelling_before_the_first_byte_closes_the_stream_and_releases_the_hold(self, azure, db, c):  # noqa: F811
        await budget(db, c["acme"], 1000)
        fake = azure([text_response("late")])
        fake.delay = 10.0
        _, task = await self._start(db, c["acme_agy"])
        await wait_for(lambda: fake.requests)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        await wait_for(fake.client_closed.is_set)
        rows = await events(db, c["acme"])
        assert rows and {r.status for r in rows} == {"released"}

    async def test_cancelling_midstream_closes_the_stream_and_settles_a_nonzero_estimate(self, azure, db, c):  # noqa: F811
        await budget(db, c["acme"], 1000)
        fake = azure([Stall([chunk({"content": "partial answer "})])])
        seen: list[gl.Event] = []
        _, task = await self._start(db, c["acme_agy"], payload={"on_event": seen.append})
        await wait_for(lambda: fake.requests)
        await asyncio.sleep(0.3)  # the first chunk is in flight
        before = asyncio.all_tasks()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        await wait_for(fake.client_closed.is_set)
        rows = await events(db, c["acme"])
        assert rows and {r.status for r in rows} == {"committed"} and all(r.cost_cents >= 1 for r in rows)
        assert seen[-1].type == gl.CANCELLED
        assert not [t for t in asyncio.all_tasks() - before if not t.done()]  # nothing survives

    async def test_cancel_is_checked_before_the_first_request(self, azure, db, c):  # noqa: F811
        fake = azure([text_response("never")])
        result, _ = await run(db, c["acme_agy"], payload={"cancelled": lambda: True})
        assert "AZURE_OPENAI_CANCELLED" in result.error and fake.requests == []

    async def test_cancel_between_deltas_stops_the_stream(self, azure, db, c):  # noqa: F811
        await budget(db, c["acme"], 1000)
        flag = []
        fake = azure([Stall([chunk({"content": "a"}), chunk({"content": "b"})])])
        seen: list[gl.Event] = []

        def on_event(event):
            seen.append(event)

        turn = await _turn(db, c["acme_agy"])
        task = asyncio.ensure_future(run(db, c["acme_agy"], turn=turn,
                                         payload={"on_event": on_event, "cancelled": lambda: bool(flag)}))
        await wait_for(lambda: fake.requests)
        await asyncio.sleep(0.3)
        flag.append(1)
        fake.script.clear()
        # no further chunk arrives; the Stall holds the stream, so cancel the task as the supervisor would
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        # A tool-free call releases text as it arrives; the cancel ends the turn with no completion.
        assert [e.text for e in seen if e.type == gl.TEXT_DELTA] == ["a", "b"]
        assert seen[-1].type == gl.CANCELLED and gl.COMPLETED not in [e.type for e in seen]

    async def test_cancel_before_a_tool_runs_no_tool(self, azure, db, c):  # noqa: F811
        await _appoint(c, c["chief"])
        await budget(db, c["acme"], 1000)
        azure([tool_response(("a", "ceo_list_managers", {})), text_response("never")])
        flag, seen = [], []

        def on_event(event):
            seen.append(event)
            if event.type == gl.TOOL_REQUESTED:
                flag.append(1)

        result, _ = await run(db, c["chief"], payload={"on_event": on_event, "cancelled": lambda: bool(flag)},
                              manager_tools_required=True)
        assert "AZURE_OPENAI_CANCELLED" in result.error and not await _rows(db, ToolInvocation)
        assert seen[-1].type == gl.CANCELLED and gl.TOOL_RUNNING not in [e.type for e in seen]
        assert {e.status for e in await events(db, c["acme"])} == {"committed"}  # round one still billed

    async def test_a_cancelled_obsolete_generation_emits_no_final_text(self, azure, db, c, monkeypatch):  # noqa: F811
        await _appoint(c, c["chief"])
        from nexus.tools import manager_bridge as mb

        real, n = mb.bind, []

        async def bind(*a):
            n.append(1)
            if len(n) > 1:
                raise mb.BridgeDeniedError("cancelled")
            return await real(*a)

        monkeypatch.setattr(mb, "bind", bind)
        azure([tool_response(("a", "ceo_list_managers", {})), text_response("stale")])
        seen: list[gl.Event] = []
        result, _ = await run(db, c["chief"], payload={"on_event": seen.append}, manager_tools_required=True)
        assert "AZURE_OPENAI_CANCELLED" in result.error and not await _rows(db, ToolInvocation)
        assert "stale" not in "".join(e.text for e in seen)

    async def test_the_timeout_is_a_hard_outer_limit_even_when_bytes_keep_arriving(self, azure, db, c, monkeypatch):  # noqa: F811
        monkeypatch.setattr(settings, "azure_openai_timeout_seconds", 0.5)
        await budget(db, c["acme"], 1000)
        fake = azure([Trickle()])
        seen: list[gl.Event] = []
        started = time.monotonic()
        result, _ = await run(db, c["acme_agy"], payload={"on_event": seen.append})
        assert result.error == "AZURE_OPENAI_TIMEOUT" and time.monotonic() - started < 5
        assert seen[-1].type == gl.ERROR and seen[-1].error == "AZURE_OPENAI_TIMEOUT"
        await wait_for(fake.client_closed.is_set)
        rows = await events(db, c["acme"])
        assert rows and "reserved" not in {r.status for r in rows}  # settled in the protected cleanup

    async def test_the_timeout_applies_before_the_first_byte(self, azure, db, c, monkeypatch):  # noqa: F811
        monkeypatch.setattr(settings, "azure_openai_timeout_seconds", 0.3)
        fake = azure([text_response("late")])
        fake.delay = 5.0
        result, _ = await run(db, c["acme_agy"])
        assert result.error == "AZURE_OPENAI_TIMEOUT"


class TestSecretsAndEndpoint:
    async def test_no_secret_reaches_results_rows_or_the_request_body(self, azure, db, c, monkeypatch):  # noqa: F811
        monkeypatch.setattr(settings, "azure_openai_auth", "key")
        monkeypatch.setenv("NEXUS_SECRET_AZURE_OPENAI_API_KEY", KEY)
        fake = azure([text_response("fine")])
        result, _ = await run(db, c["acme_agy"])
        assert KEY not in json.dumps([result.output, result.error, result.logs, result.artifacts])
        assert KEY not in json.dumps(fake.requests[0]["body"])
        rows = [*(await _rows(db, AuditLog)), *(await _rows(db, ToolInvocation)), *(await _rows(db, CostEvent))]
        assert KEY not in json.dumps([r.model_dump() for r in rows], default=str)

    async def test_an_error_carrying_a_key_or_token_is_redacted(self, azure, db, c):  # noqa: F811
        adapter = AzureOpenAINativeAdapter()
        session = await adapter.create_session(c["acme_agy"], {})
        failed = adapter._fail(session, uuid.uuid4(), f"boom {KEY} and {TOKEN}", [KEY, TOKEN])
        assert KEY not in failed.error and TOKEN not in failed.error and ao.REDACTED in failed.error

    async def test_an_agent_cannot_supply_the_endpoint_the_key_or_the_gate(self, azure, db, c, monkeypatch):  # noqa: F811
        fake = azure([text_response("x")])
        monkeypatch.setattr(settings, "azure_openai_enabled", False)
        forged = {"azure_openai_enabled": True, "endpoint": "http://evil", "api_key": "stolen", "deployment": "x"}
        result, _ = await run(db, c["acme_agy"], config=forged)
        assert "AZURE_OPENAI_DISABLED" in result.error and fake.requests == []

    @pytest.mark.parametrize("endpoint", [
        "http://res.openai.azure.com", "https://evil.example.com", "https://10.0.0.5", "ftp://res.openai.azure.com",
        "https://res.openai.azure.com/openai", "https://res.openai.azure.com?x=1", "https://u:p@res.openai.azure.com",
        "https://openai.azure.com", "https://res.openai.azure.com.evil.com", "https://res.openai.azure.com:8443",
        "http://example.com",
    ])
    async def test_invalid_endpoints_fail_before_any_request_or_token(self, azure, db, c, monkeypatch, endpoint):  # noqa: F811
        fake = azure([text_response("x")])
        monkeypatch.setattr(settings, "azure_openai_endpoint", endpoint)
        result, _ = await run(db, c["acme_agy"])
        assert "AZURE_OPENAI_ENDPOINT_INVALID" in result.error and fake.requests == [] and azure.scopes == []

    def test_the_azure_openai_resource_endpoint_is_accepted(self, azure, monkeypatch):
        monkeypatch.setattr(settings, "azure_openai_endpoint", "https://res.openai.azure.com/")
        assert ao._classify() == ("https://res.openai.azure.com", ao.RESOURCE)

    @pytest.mark.parametrize("endpoint", ["https://res.services.ai.azure.com", "https://res.services.ai.azure.com/"])
    async def test_a_foundry_project_endpoint_is_disabled_with_a_stable_reason(self, azure, db, c, monkeypatch, endpoint):  # noqa: F811
        fake = azure([text_response("x")])
        monkeypatch.setattr(settings, "azure_openai_endpoint", endpoint)
        assert ao._family_of("res.services.ai.azure.com") == ao.FOUNDRY
        assert ao.unavailable_reason().startswith("AZURE_OPENAI_ENDPOINT_FAMILY_UNSUPPORTED")
        result, _ = await run(db, c["acme_agy"])
        assert "AZURE_OPENAI_ENDPOINT_FAMILY_UNSUPPORTED" in result.error
        assert fake.requests == [] and azure.scopes == []

    def test_a_cognitiveservices_host_is_not_a_known_endpoint_family(self, azure, monkeypatch):
        monkeypatch.setattr(settings, "azure_openai_endpoint", "https://res.cognitiveservices.azure.com")
        assert ao.unavailable_reason().startswith("AZURE_OPENAI_ENDPOINT_INVALID")


class TestTokenScope:
    """The Entra scope is derived from the endpoint family; it is never operator text."""

    def test_there_is_no_scope_setting_to_choose_from(self):
        assert not [n for n in Settings.model_fields if n.startswith("azure") and "scope" in n]

    def test_the_resource_family_derives_exactly_the_live_validated_scope(self):
        assert ao.ENTRA_SCOPES == {ao.RESOURCE: SCOPE}
        assert ao.SUPPORTED_FAMILIES == (ao.RESOURCE,)
        assert ao.ENTRA_SCOPE_BASIS == "live_validated"

    @pytest.mark.parametrize("endpoint", ["https://res.openai.azure.com", "https://res.openai.azure.com/"])
    def test_a_supported_endpoint_derives_the_scope_and_is_available(self, azure, monkeypatch, endpoint):
        azure([])
        monkeypatch.setattr(settings, "azure_openai_endpoint", endpoint)
        assert ao._scope() == SCOPE and ao.unavailable_reason() is None

    @pytest.mark.parametrize("endpoint", [
        "https://res.services.ai.azure.com", "https://res.cognitiveservices.azure.com", "https://evil.example.com",
    ])
    def test_unsupported_families_never_derive_a_scope(self, azure, monkeypatch, endpoint):
        azure([])
        monkeypatch.setattr(settings, "azure_openai_endpoint", endpoint)
        with pytest.raises(ProviderError):
            ao._scope()
        assert ao.status()["entra_scope"] is None and ao.status()["available"] is False

    async def test_the_scope_never_comes_from_the_environment_or_the_agent(self, azure, db, c, monkeypatch):  # noqa: F811
        monkeypatch.setenv("AZURE_OPENAI_TOKEN_SCOPE", "https://cognitiveservices.azure.com/.default")
        fake = azure([text_response("ok")])
        result, _ = await run(db, c["acme_agy"], config={"scope": "https://cognitiveservices.azure.com/.default"})
        assert result.success and azure.scopes == [SCOPE] and len(fake.requests) == 1

    def test_the_default_state_is_disabled_even_though_a_scope_is_known(self, monkeypatch):
        monkeypatch.delenv("AZURE_OPENAI_ENABLED", raising=False)
        assert Settings.model_fields["azure_openai_enabled"].default is False
        monkeypatch.setattr(settings, "azure_openai_enabled", False)
        assert ao.unavailable_reason().startswith("AZURE_OPENAI_DISABLED")

    async def test_key_mode_requests_no_token_and_leaves_the_scope_alone(self, azure, db, c, monkeypatch):  # noqa: F811
        monkeypatch.setattr(settings, "azure_openai_auth", "key")
        monkeypatch.setenv("NEXUS_SECRET_AZURE_OPENAI_API_KEY", KEY)
        fake = azure([text_response("dev ok")])
        result, _ = await run(db, c["acme_agy"])
        assert result.success and fake.requests[0]["api_key"] == KEY and azure.scopes == []

    async def test_only_the_derived_scope_is_requested_with_no_fallback(self, azure, db, c, monkeypatch):  # noqa: F811
        asked = []

        async def failing(scope):
            asked.append(scope)
            raise RuntimeError("AADSTS500011 tenant detail that must not leak")

        monkeypatch.setattr(ao, "_token_source", failing)
        fake = azure([text_response("x")])
        result, _ = await run(db, c["acme_agy"])
        assert asked == [SCOPE] and fake.requests == []  # no second scope is tried
        assert result.error.startswith("AZURE_OPENAI_AUTH_FAILED") and "AADSTS" not in result.error

    async def test_an_inference_failure_does_not_retry_with_another_scope(self, azure, db, c):  # noqa: F811
        fake = azure([Status(401)])
        result, _ = await run(db, c["acme_agy"])
        assert not result.success and len(fake.requests) == 1
        assert azure.scopes == [SCOPE]  # one token for the one scope, nothing else


class TestDoctor:
    def test_the_provider_is_off_by_default_and_nothing_is_assumed(self):
        fields = Settings.model_fields
        assert fields["azure_openai_enabled"].default is False
        for name in ("azure_openai_endpoint", "azure_openai_deployment", "azure_openai_model"):
            assert fields[name].default == ""

    @pytest.mark.parametrize("name,value,code", [
        ("azure_openai_enabled", False, "AZURE_OPENAI_DISABLED"),
        ("azure_openai_endpoint", "", "AZURE_OPENAI_ENDPOINT_MISSING"),
        ("azure_openai_endpoint", "https://evil.example.com", "AZURE_OPENAI_ENDPOINT_INVALID"),
        ("azure_openai_deployment", "", "AZURE_OPENAI_DEPLOYMENT_MISSING"),
        ("azure_openai_deployment", "bad name/../x", "AZURE_OPENAI_DEPLOYMENT_INVALID"),
        ("azure_openai_model", "", "AZURE_OPENAI_MODEL_MISSING"),
        ("azure_openai_api_version", "a b", "AZURE_OPENAI_API_VERSION_INVALID"),
        ("azure_openai_auth", "password", "AZURE_OPENAI_AUTH_INVALID"),
        ("azure_openai_endpoint", "https://res.services.ai.azure.com", "AZURE_OPENAI_ENDPOINT_FAMILY_UNSUPPORTED"),
        ("azure_openai_timeout_seconds", 0.0, "AZURE_OPENAI_TIMEOUT_INVALID"),
        ("azure_openai_timeout_seconds", 99999.0, "AZURE_OPENAI_TIMEOUT_INVALID"),
    ])
    def test_every_missing_or_invalid_setting_fails_closed_with_a_stable_reason(self, azure, monkeypatch, name, value, code):
        azure([])
        assert ao.unavailable_reason() is None
        monkeypatch.setattr(settings, name, value)
        assert ao.unavailable_reason().startswith(code)

    def test_key_mode_needs_a_credential_reference_and_never_shows_it(self, azure, monkeypatch):
        azure([])
        monkeypatch.setattr(settings, "azure_openai_auth", "key")
        assert ao.unavailable_reason().startswith("AZURE_OPENAI_KEY_MISSING")
        monkeypatch.setenv("NEXUS_SECRET_AZURE_OPENAI_API_KEY", KEY)
        assert ao.unavailable_reason() is None
        shown = ao.status()
        assert shown["credential_reference_present"] is True and KEY not in json.dumps(shown)

    def test_entra_mode_reports_a_missing_identity_sdk(self, azure, monkeypatch):
        azure([])
        monkeypatch.setattr(ao, "_token_source", None)
        monkeypatch.setattr(ao.importlib.util, "find_spec", lambda name: None)
        assert ao.unavailable_reason().startswith("AZURE_OPENAI_IDENTITY_SDK_MISSING")

    async def test_the_doctor_makes_no_request_asks_for_no_token_and_writes_nothing(self, azure, db, c):  # noqa: F811
        fake = azure([])
        before = len(await _rows(db, CostEvent)), len(await _rows(db, ToolInvocation)), len(await _rows(db, AuditLog))
        shown = ao.status()
        assert shown["available"] is True and shown["auth"] == "entra" and shown["entra_scope"] == SCOPE
        assert shown["endpoint_family"] == ao.RESOURCE and shown["entra_scope_basis"] == "live_validated"
        assert shown["endpoint_valid"] and shown["deployment_configured"] and shown["model_configured"]
        assert TOKEN not in json.dumps(shown) and fake.requests == [] and azure.scopes == []
        assert (len(await _rows(db, CostEvent)), len(await _rows(db, ToolInvocation)), len(await _rows(db, AuditLog))) == before

    async def test_tool_support_follows_the_provider(self, azure, db, c, monkeypatch):  # noqa: F811
        azure([])
        async with db() as s:
            agent = await s.get(Agent, c["chief"])
            agent.adapter_type = "azure-openai-native"
            assert ceo_service.tool_support(agent) == (True, None)
            monkeypatch.setattr(settings, "azure_openai_enabled", False)
            ok, reason = ceo_service.tool_support(agent)
            assert not ok and reason.startswith("CEO_TOOLS_UNSUPPORTED") and "AZURE_OPENAI_DISABLED" in reason

    def test_the_legacy_azure_adapter_never_satisfies_ceo_tools(self):
        legacy = SimpleNamespace(adapter_type="azure_openai", adapter_config={})
        ok, reason = ceo_service.tool_support(legacy)  # type: ignore[arg-type]
        assert not ok and reason.startswith("CEO_TOOLS_UNSUPPORTED")


class TestWiring:
    def test_registration_selection_is_explicit_and_there_is_no_register_tool(self):
        key, config = resolve_provider("azure-openai-native")
        assert key == "azure_openai_native" and config["model"] == ""
        registry = AdapterRegistry()
        adapter = registry.create_adapter(key)
        assert isinstance(adapter, AzureOpenAINativeAdapter) and not hasattr(adapter, "register_tool")
        assert type(registry.create_adapter("azure_openai")).__name__ == "AzureOpenAIAdapter"
        assert type(registry.create_adapter("hermes_native")).__name__ == "HermesProviderAdapter"

    def test_hermes_native_still_resolves_and_nothing_switches_automatically(self):
        assert resolve_provider("hermes-native")[0] == "hermes_native"
        assert resolve_provider("azure-openai-native")[0] == "azure_openai_native"
