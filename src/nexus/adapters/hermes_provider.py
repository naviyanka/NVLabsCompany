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
import uuid
from contextlib import aclosing
from datetime import UTC, datetime
from typing import Any

import httpx

from nexus.adapters import governed_loop
from nexus.adapters.base import BaseAdapter
from nexus.adapters.governed_loop import TOOL_TEXT, ProviderError  # noqa: F401 -- re-exported
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
            return self._fail(session, task_id, str(exc), key, exc.usage)
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
    def _fail(
        session: AgentSession, task_id: uuid.UUID, error: str, key: str,
        usage: dict[str, int] | None = None,
    ) -> TaskResult:
        if key:
            error = error.replace(key, REDACTED)
        # Rounds finished before the failure were billed; report them so they are metered.
        # ponytail: a timeout cancels the loop and its usage is lost; meter per round
        # (as azure_openai_native does) if that becomes material.
        usage = usage or {}
        return TaskResult(
            task_id=task_id, agent_id=session.agent_id, success=False, error=error,
            input_tokens=int(usage.get("prompt_tokens") or 0),
            output_tokens=int(usage.get("completion_tokens") or 0),
        )

    async def _run(
        self, session: AgentSession, task_id: uuid.UUID, payload: dict[str, Any], key: str
    ) -> tuple[str, list[dict[str, Any]], dict[str, Any]]:
        prepared = await governed_loop.prepare(session.context, task_id, "HERMES_NATIVE")
        if prepared.offered and not settings.hermes_native_tools_enabled:
            raise _tools_disabled()
        messages = list(self._conversation_history.get(session.session_id, []))
        messages.append({"role": "user", "content": payload.get("prompt", "")})
        url = f"{_endpoint()}/chat/completions"
        model = _model(session.config.get("model"))
        headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
        # Read at call time so the module constants stay the single, patchable source.
        limits = governed_loop.Limits(
            "HERMES_NATIVE",
            max_iterations=MAX_ITERATIONS,
            max_calls=MAX_CALLS,
            max_calls_per_response=MAX_CALLS_PER_RESPONSE,
            max_argument_bytes=MAX_ARGUMENT_BYTES,
            max_tool_result_chars=MAX_TOOL_RESULT_CHARS,
        )
        timeout = httpx.Timeout(READ_TIMEOUT_SECONDS, connect=10.0)
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=False) as client:

            def transport(msgs: list[dict[str, Any]], tools: list[dict[str, Any]]):
                body: dict[str, Any] = {
                    "model": model,
                    "messages": msgs,
                    "max_tokens": MAX_TOKENS,
                    "stream": True,
                }
                if tools:
                    body["tools"] = tools
                    body["tool_choice"] = "auto"
                return self._stream(client, url, headers, body)

            done = await governed_loop.run(
                prepared, task_id, messages, transport, limits, on_tool_verified=_mark_verified
            )
        self._conversation_history[session.session_id] = done.messages
        return done.text, done.artifacts, done.usage

    @staticmethod
    async def _stream(
        client: httpx.AsyncClient, url: str, headers: dict[str, str], body: dict[str, Any]
    ):
        async with client.stream("POST", url, json=body, headers=headers) as resp:
            if resp.status_code != 200:
                raise ProviderError(f"HERMES_NATIVE_HTTP_{resp.status_code}")
            async with aclosing(
                governed_loop.sse_chunks(resp.aiter_lines(), "HERMES_NATIVE", MAX_RESPONSE_BYTES)
            ) as chunks:
                async for chunk in chunks:
                    yield chunk

    async def _do_heartbeat(self, session: AgentSession) -> bool:
        return True

    async def _do_terminate(self, session: AgentSession) -> None:
        self._conversation_history.pop(session.session_id, None)
