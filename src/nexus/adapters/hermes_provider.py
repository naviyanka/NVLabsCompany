"""Hermes over an OpenAI-compatible API with native, server-governed tool calls.

The model never runs anything. NEXUS offers only the server-built catalog of the
turn's agent (:class:`MCPServer` over ``manager_tools.catalog``), takes tool calls
only from the response's structured ``tool_calls`` field, and runs each through
the same ``guarded_call`` / ``ToolPolicy`` path as the MCP bridge. Hermes gets no
shell, filesystem, browser or network tool: none is ever offered.

The API key comes from the secret backend; the endpoint from operator settings.
Nothing is read from Hermes' own home, and there is no fallback to another adapter.
"""

from __future__ import annotations

import asyncio
import json
import re
import uuid
from datetime import UTC, datetime
from typing import Any

import httpx

from nexus.adapters.base import BaseAdapter
from nexus.config import settings
from nexus.runtime.adapter import AgentSession, TaskResult

MAX_ITERATIONS = 8
MAX_CALLS = 16
MAX_CALLS_PER_RESPONSE = 4
MAX_RESPONSE_BYTES = 1_000_000
MAX_ARGUMENT_BYTES = 64_000
MAX_TOOL_RESULT_CHARS = 32_000
MAX_TOKENS = 4096
TOTAL_TIMEOUT_SECONDS = 300.0
READ_TIMEOUT_SECONDS = 60.0
REDACTED = "[REDACTED]"
# Text that looks like a tool call is never executed; a response carrying it fails.
TOOL_TEXT = re.compile(r"<\s*/?\s*tool_call|<\s*function_call|\"tool_calls\"\s*:", re.IGNORECASE)


class ProviderError(Exception):
    """A turn that must fail; the message carries a stable code and no secret."""


_verified_at: datetime | None = None


def _endpoint() -> str:
    """The operator's endpoint: https or loopback http, no literal private IP."""
    from nexus.governance.ssrf_protection import guard_url

    url = settings.hermes_native_base_url.rstrip("/")
    if not url:
        raise ProviderError("HERMES_NATIVE_ENDPOINT_MISSING: no endpoint configured")
    try:
        return guard_url(url, "hermes_native_base_url")
    except ValueError:
        raise ProviderError("HERMES_NATIVE_ENDPOINT_INVALID: https or loopback only") from None


def _secret() -> str | None:
    """The key from the configured backend; a Fernet backend reads the ``secrets`` table."""
    from nexus.database import async_session_factory
    from nexus.governance.secret_backend import make_secret_backend

    return make_secret_backend(async_session_factory).decrypt(settings.hermes_native_secret_ref)


def _api_key() -> str:
    key = _secret()
    if not key:
        raise ProviderError("HERMES_NATIVE_KEY_MISSING: no API key in the secret backend")
    return key


def _model(requested: Any) -> str:
    """The configured default, or an agent's choice only if the operator approved it."""
    approved = {m.strip() for m in settings.hermes_native_models.split(",") if m.strip()}
    if requested and requested in approved | {settings.hermes_native_model}:
        return str(requested)
    if requested:
        raise ProviderError("HERMES_NATIVE_MODEL_NOT_APPROVED: not an operator-approved model")
    if not settings.hermes_native_model:
        raise ProviderError("HERMES_NATIVE_MODEL_MISSING: no model configured")
    return settings.hermes_native_model


def _mark_verified() -> None:
    global _verified_at
    _verified_at = datetime.now(UTC)


def _tools_disabled() -> ProviderError:
    return ProviderError("HERMES_NATIVE_TOOLS_DISABLED: governed tools are off (operator setting)")


def unavailable_reason() -> str | None:
    """Why governed native tool turns cannot run now, or None. Makes no request."""
    if not settings.hermes_native_tools_enabled:
        return str(_tools_disabled())
    try:
        _endpoint()
        _api_key()
        _model("")
    except ProviderError as exc:
        return str(exc)
    return None


def status() -> dict[str, Any]:
    """Non-secret configuration state; makes no request."""
    try:
        _endpoint()
        endpoint = True
    except ProviderError:
        endpoint = False
    return {
        "enabled": settings.hermes_native_tools_enabled,
        "endpoint_configured": endpoint,
        "secret_configured": bool(_secret()),
        "model_configured": bool(settings.hermes_native_model),
        "native_tools": "verified" if _verified_at else "unverified",
        "last_verified_at": _verified_at.isoformat() if _verified_at else None,
    }


async def probe() -> dict[str, Any]:
    """``status`` plus reachability: one GET of the configured endpoint, no model call.

    The key goes only to the validated operator endpoint, never to a redirect target.
    """
    out = {**status(), "reachable": False}
    if not (out["endpoint_configured"] and out["secret_configured"]):
        return out
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(10.0), follow_redirects=False) as client:
            resp = await client.get(
                f"{_endpoint()}/models", headers={"Authorization": f"Bearer {_api_key()}"}
            )
        out["reachable"] = resp.status_code < 500
    except (httpx.HTTPError, ProviderError):
        pass
    return out


class _Assembler:
    """One streamed completion: content plus tool calls assembled by delta index."""

    def __init__(self) -> None:
        self.content: list[str] = []
        self.calls: dict[int, dict[str, str]] = {}
        self.finish: str | None = None
        self.usage: dict[str, Any] = {}

    def feed(self, chunk: dict[str, Any]) -> None:
        self.usage = chunk.get("usage") or self.usage
        for choice in chunk.get("choices") or []:
            if choice.get("index", 0) != 0:
                raise ProviderError("HERMES_NATIVE_BAD_RESPONSE: multiple choices")
            delta = choice.get("delta") or {}
            if delta.get("content"):
                self.content.append(delta["content"])
            for part in delta.get("tool_calls") or []:
                slot = self.calls.setdefault(
                    int(part.get("index", 0)), {"id": "", "name": "", "arguments": ""}
                )
                fn = part.get("function") or {}
                slot["id"] += part.get("id") or ""
                slot["name"] += fn.get("name") or ""
                slot["arguments"] += fn.get("arguments") or ""
                if len(slot["arguments"]) > MAX_ARGUMENT_BYTES:
                    raise ProviderError("HERMES_NATIVE_LIMIT: tool arguments too large")
            self.finish = choice.get("finish_reason") or self.finish

    def tool_calls(self) -> list[dict[str, Any]]:
        """Complete, validated calls in order; anything malformed fails the turn."""
        out = []
        for index in sorted(self.calls):
            slot = self.calls[index]
            if not slot["id"] or not slot["name"]:
                raise ProviderError("HERMES_NATIVE_BAD_TOOL_CALL: incomplete call")
            try:
                args = json.loads(slot["arguments"] or "{}")
            except ValueError:
                raise ProviderError("HERMES_NATIVE_BAD_TOOL_CALL: arguments are not JSON") from None
            if not isinstance(args, dict):
                raise ProviderError("HERMES_NATIVE_BAD_TOOL_CALL: arguments are not an object")
            out.append({"id": slot["id"], "name": slot["name"], "arguments": args})
        if out and self.finish != "tool_calls":
            raise ProviderError("HERMES_NATIVE_BAD_TOOL_CALL: call in an unfinished response")
        return out


class HermesProviderAdapter(BaseAdapter):
    """Hermes chat with native governed tool calls. Has no ``register_tool``."""

    adapter_type: str = "hermes_native"

    async def _do_create_session(self, session: AgentSession) -> None:
        prompt = session.config.get("system_prompt", "")
        if prompt:
            self._conversation_history[session.session_id] = [{"role": "system", "content": prompt}]

    def validate_config(self, config: dict[str, Any]) -> None:
        """Nothing to validate: endpoint, model list and secret are operator settings."""

    async def _do_execute(
        self, session: AgentSession, task_id: uuid.UUID, payload: dict[str, Any]
    ) -> TaskResult:
        key = ""
        try:
            if getattr(session.context, "manager_tools_required", False) and not (
                settings.hermes_native_tools_enabled
            ):
                raise _tools_disabled()
            key = _api_key()
            async with asyncio.timeout(TOTAL_TIMEOUT_SECONDS):
                output, artifacts, usage = await self._run(session, task_id, payload, key)
        except ProviderError as exc:
            return self._fail(session, task_id, str(exc), key)
        except TimeoutError:
            return self._fail(session, task_id, "HERMES_NATIVE_TIMEOUT", key)
        except httpx.HTTPError as exc:
            error = f"HERMES_NATIVE_TRANSPORT: {type(exc).__name__}"
            return self._fail(session, task_id, error, key)
        return TaskResult(
            task_id=task_id,
            agent_id=session.agent_id,
            success=True,
            output=output,
            input_tokens=int(usage.get("prompt_tokens") or 0),
            output_tokens=int(usage.get("completion_tokens") or 0),
            artifacts=artifacts,
        )

    @staticmethod
    def _fail(session: AgentSession, task_id: uuid.UUID, error: str, key: str) -> TaskResult:
        if key:
            error = error.replace(key, REDACTED)
        return TaskResult(task_id=task_id, agent_id=session.agent_id, success=False, error=error)

    async def _run(
        self, session: AgentSession, task_id: uuid.UUID, payload: dict[str, Any], key: str
    ) -> tuple[str, list[dict[str, Any]], dict[str, Any]]:
        from nexus.tools import manager_bridge
        from nexus.tools.mcp_server import MCPServer

        base = session.context
        if base is None:
            raise ProviderError("HERMES_NATIVE_NO_CONTEXT: no server-built execution context")
        # The turn's own identity, as for the MCP bridge: run principal, turn and session.
        try:
            ctx = await manager_bridge.bind(base.company_id, base.agent_id, task_id)
        except manager_bridge.BridgeDeniedError:
            raise ProviderError("HERMES_NATIVE_CANCELLED: turn is not live") from None
        server = MCPServer(ctx, node_tools=False)
        offered = await server.list_tools()
        names = {t["name"] for t in offered}
        if offered and not settings.hermes_native_tools_enabled:
            raise _tools_disabled()
        tools = [
            {
                "type": "function",
                "function": {
                    "name": t["name"],
                    "description": t["description"],
                    "parameters": t["inputSchema"],
                },
            }
            for t in offered
        ]
        messages = list(self._conversation_history.get(session.session_id, []))
        messages.append({"role": "user", "content": payload.get("prompt", "")})
        url = f"{_endpoint()}/chat/completions"
        model = _model(session.config.get("model"))
        headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
        seen: set[str] = set()
        artifacts: list[dict[str, Any]] = []
        usage: dict[str, int] = {"prompt_tokens": 0, "completion_tokens": 0}
        timeout = httpx.Timeout(READ_TIMEOUT_SECONDS, connect=10.0)
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=False) as client:
            for _ in range(MAX_ITERATIONS):
                body: dict[str, Any] = {
                    "model": model,
                    "messages": messages,
                    "max_tokens": MAX_TOKENS,
                    "stream": True,
                }
                if tools:
                    body["tools"] = tools
                    body["tool_choice"] = "auto"
                got = await self._complete(client, url, headers, body)
                for k in usage:
                    usage[k] += int(got.usage.get(k) or 0)
                text = "".join(got.content)
                calls = got.tool_calls()
                if TOOL_TEXT.search(text):
                    raise ProviderError("HERMES_NATIVE_TOOL_TEXT: tool call in message text")
                if not calls:
                    self._conversation_history[session.session_id] = [
                        *messages,
                        {"role": "assistant", "content": text},
                    ]
                    return text, artifacts, usage
                if not tools or len(calls) > MAX_CALLS_PER_RESPONSE:
                    raise ProviderError("HERMES_NATIVE_BAD_TOOL_CALL: tool calls not allowed here")
                messages.append(
                    {
                        "role": "assistant",
                        "content": text or None,
                        "tool_calls": [
                            {
                                "id": c["id"],
                                "type": "function",
                                "function": {
                                    "name": c["name"],
                                    "arguments": json.dumps(c["arguments"]),
                                },
                            }
                            for c in calls
                        ],
                    }
                )
                ids = [c["id"] for c in calls]
                if len(set(ids)) != len(ids) or seen & set(ids):
                    raise ProviderError("HERMES_NATIVE_BAD_TOOL_CALL: duplicate call id")
                if any(c["name"] not in names for c in calls):
                    raise ProviderError("HERMES_NATIVE_BAD_TOOL_CALL: tool not offered")
                if len(seen) + len(calls) > MAX_CALLS:
                    raise ProviderError("HERMES_NATIVE_LIMIT: too many tool calls")
                seen.update(ids)
                for call in calls:
                    # The turn must still be this execution's, live and uncancelled.
                    try:
                        await manager_bridge.bind(ctx.company_id, ctx.agent_id, task_id)
                    except manager_bridge.BridgeDeniedError:
                        raise ProviderError("HERMES_NATIVE_CANCELLED: turn ended") from None
                    result = await server.call_tool(call["name"], call["arguments"])
                    text_out = "".join(p.get("text", "") for p in result["content"])
                    _mark_verified()
                    artifacts.append(
                        {"type": "tool_call", "tool_call_id": call["id"], "name": call["name"],
                         "is_error": bool(result["isError"])}
                    )
                    messages.append(
                        {"role": "tool", "tool_call_id": call["id"],
                         "content": text_out[:MAX_TOOL_RESULT_CHARS]}
                    )
        raise ProviderError("HERMES_NATIVE_LIMIT: too many model iterations")

    @staticmethod
    async def _complete(
        client: httpx.AsyncClient, url: str, headers: dict[str, str], body: dict[str, Any]
    ) -> _Assembler:
        got, size = _Assembler(), 0
        async with client.stream("POST", url, json=body, headers=headers) as resp:
            if resp.status_code != 200:
                raise ProviderError(f"HERMES_NATIVE_HTTP_{resp.status_code}")
            async for line in resp.aiter_lines():
                size += len(line)
                if size > MAX_RESPONSE_BYTES:
                    raise ProviderError("HERMES_NATIVE_LIMIT: response too large")
                if not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if data == "[DONE]":
                    break
                try:
                    got.feed(json.loads(data))
                except ValueError:
                    raise ProviderError("HERMES_NATIVE_BAD_RESPONSE: not JSON") from None
        return got

    async def _do_heartbeat(self, session: AgentSession) -> bool:
        return True

    async def _do_terminate(self, session: AgentSession) -> None:
        self._conversation_history.pop(session.session_id, None)
