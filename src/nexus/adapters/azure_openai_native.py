"""Azure OpenAI streaming chat with native, server-governed tool calls (ADR 0006).

The Azure sibling of ``hermes_provider``: the same governed loop
(``governed_loop.run``), a different transport. The model never runs anything; tool
calls are taken only from the streamed ``tool_calls`` deltas and executed through
``MCPServer.call_tool`` -> ``guarded_call`` -> ``ToolPolicy`` under the durable
turn's identity.

This is *not* the legacy ``azure_adapter.AzureOpenAIAdapter`` (``azure_openai``):
that one is non-streaming, takes its key from the agent's config and has no governed
tool path, so governed CEO traffic must never use it.

Operator settings only (``azure_openai_*``), never agent config. Disabled by default;
every missing or invalid value fails closed with a stable, sanitized reason. There is
no fallback to another provider. Every outbound round is metered: reserved before the
request and settled or released when it ends, however it ends.
"""

from __future__ import annotations

import asyncio
import importlib.util
import ipaddress
import re
import uuid
from collections.abc import Awaitable, Callable
from contextlib import aclosing
from typing import Any
from urllib.parse import quote, urlsplit

import httpx

from nexus.adapters import governed_loop
from nexus.adapters.base import BaseAdapter
from nexus.adapters.governed_loop import CANCELLED, ERROR, Event, ProviderError
from nexus.config import settings
from nexus.runtime.adapter import AgentSession, TaskResult

CODE = "AZURE_OPENAI"
REGISTRY_KEY = "azure_openai_native"

# Endpoint families (docs/azure-openai-provider.md has the per-page evidence table).
# Only the Azure OpenAI resource family is supported: its example pages show the
# implemented /openai/v1/chat/completions transport. A Foundry project endpoint is a
# different family and no page shows a v1 chat example for it, so it stays disabled.
RESOURCE = "openai_resource"  # https://<name>.openai.azure.com
FOUNDRY = "foundry_project"  # https://<name>.services.ai.azure.com
FAMILY_SUFFIXES = {RESOURCE: ".openai.azure.com", FOUNDRY: ".services.ai.azure.com"}
SUPPORTED_FAMILIES = (RESOURCE,)

# The Entra scope is derived from the endpoint family, never configured. Microsoft Learn
# disagrees for the resource family + /openai/v1, so the live probe of 2026-10-02 decided
# it: both candidate scopes returned HTTP 200 on a South India resource, and NEXUS
# deliberately selects ai.azure.com, the service-specific audience that the current docs
# show for this exact path. No fallback to a second scope (docs/azure-openai-provider.md).
ENTRA_SCOPES: dict[str, str] = {RESOURCE: "https://ai.azure.com/.default"}
ENTRA_SCOPE_BASIS = "live_validated"

MAX_ITERATIONS = 8
MAX_CALLS = 16
MAX_CALLS_PER_RESPONSE = 4
MAX_RESPONSE_BYTES = 1_000_000
MAX_ARGUMENT_BYTES = 64_000
MAX_TOOL_RESULT_CHARS = 32_000
MAX_TOKENS = 4096
READ_TIMEOUT_SECONDS = 60.0
MAX_RETRIES_CAP = 5
RETRY_AFTER_CAP_SECONDS = 5.0
RETRYABLE = frozenset({0, 429, 500, 502, 503, 504})  # 0: could not connect
REDACTED = "[REDACTED]"

_NAME = re.compile(r"^[A-Za-z0-9._-]{1,64}$")

TokenSource = Callable[[str], Awaitable[str]]
# Tests inject a source; production uses azure-identity (see _entra_token).
_token_source: TokenSource | None = None
_sleep = asyncio.sleep


def _is_loopback(host: str) -> bool:
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def _family_of(host: str) -> str | None:
    if _is_loopback(host):  # the existing SSRF policy's explicit loopback allowance (tests)
        return RESOURCE
    for family, suffix in FAMILY_SUFFIXES.items():
        if host.endswith(suffix) and len(host) > len(suffix):
            return family
    return None


def _classify() -> tuple[str, str]:
    """The operator's endpoint and its family: a public Azure OpenAI resource over https."""
    from nexus.governance.ssrf_protection import guard_url

    raw = settings.azure_openai_endpoint.strip().rstrip("/")
    if not raw:
        raise ProviderError(f"{CODE}_ENDPOINT_MISSING: no endpoint configured")
    try:
        guard_url(raw, "azure_openai_endpoint")
        parts = urlsplit(raw)
        host = (parts.hostname or "").lower()
        if parts.username or parts.password or parts.query or parts.fragment:
            raise ValueError
        family = _family_of(host)
        if family is None:
            raise ValueError
        if not _is_loopback(host) and (
            parts.scheme != "https" or parts.path or parts.port not in (None, 443)
        ):
            raise ValueError
    except ValueError:
        message = f"{CODE}_ENDPOINT_INVALID: https Azure OpenAI resource endpoint required"
        raise ProviderError(message) from None
    if family not in SUPPORTED_FAMILIES:
        message = f"{CODE}_ENDPOINT_FAMILY_UNSUPPORTED: only *.openai.azure.com is supported"
        raise ProviderError(message)
    return raw, family


def _endpoint() -> str:
    return _classify()[0]


def _deployment() -> str:
    name = settings.azure_openai_deployment.strip()
    if not name:
        raise ProviderError(f"{CODE}_DEPLOYMENT_MISSING: no deployment configured")
    if not _NAME.match(name):
        raise ProviderError(f"{CODE}_DEPLOYMENT_INVALID: unsupported deployment name")
    return name


def _model_id() -> str:
    if not settings.azure_openai_model.strip():
        raise ProviderError(f"{CODE}_MODEL_MISSING: no model identifier configured")
    return settings.azure_openai_model.strip()


def _api_version() -> str:
    version = settings.azure_openai_api_version.strip()
    if not _NAME.match(version):
        raise ProviderError(f"{CODE}_API_VERSION_INVALID: unsupported api version")
    return version


def _url() -> str:
    base, version = _endpoint(), _api_version()
    if version == "v1":
        return f"{base}/openai/v1/chat/completions"
    deployment = quote(_deployment(), safe="")
    return f"{base}/openai/deployments/{deployment}/chat/completions?api-version={version}"


def _timeout() -> float:
    seconds = settings.azure_openai_timeout_seconds
    if not 0 < seconds <= 900:
        raise ProviderError(f"{CODE}_TIMEOUT_INVALID: timeout must be within (0, 900] seconds")
    return float(seconds)


def _retries() -> int:
    return max(0, min(int(settings.azure_openai_max_retries), MAX_RETRIES_CAP))


def _secret() -> str | None:
    """The development key from the secret backend; never a setting or agent field."""
    from nexus.database import async_session_factory
    from nexus.governance.secret_backend import make_secret_backend

    return make_secret_backend(async_session_factory).decrypt(settings.azure_openai_secret_ref)


def _identity_sdk() -> bool:
    if _token_source is not None:
        return True
    try:  # aiohttp is the async transport azure.identity.aio needs to build a credential
        found = (importlib.util.find_spec(m) for m in ("azure.identity.aio", "aiohttp"))
        return all(spec is not None for spec in found)
    except ImportError:
        return False


def _auth() -> str:
    mode = settings.azure_openai_auth.strip().lower()
    if mode not in ("entra", "key"):
        raise ProviderError(f"{CODE}_AUTH_INVALID: auth must be entra or key")
    return mode


def _scope() -> str:
    """The Entra scope derived from the validated endpoint family; never operator text."""
    return ENTRA_SCOPES[_classify()[1]]  # _classify only returns SUPPORTED_FAMILIES


def unavailable_reason() -> str | None:
    """Why governed Azure turns cannot run now, or None. Makes no request, reads no secret value."""
    if not settings.azure_openai_enabled:
        return f"{CODE}_DISABLED: Azure OpenAI is off (operator setting)"
    try:
        _endpoint()
        _deployment()
        _model_id()
        _api_version()
        _timeout()
        if _auth() == "entra":
            _scope()
            if not _identity_sdk():
                raise ProviderError(f"{CODE}_IDENTITY_SDK_MISSING: azure-identity is not installed")
        elif not _secret():
            raise ProviderError(f"{CODE}_KEY_MISSING: no key in the secret backend")
    except ProviderError as exc:
        return str(exc)
    return None


def status() -> dict[str, Any]:
    """Non-secret configuration state for diagnostics; makes no request and shows no secret."""

    def ok(check: Callable[[], Any]) -> bool:
        try:
            check()
        except ProviderError:
            return False
        return True

    auth = settings.azure_openai_auth.strip().lower()
    try:
        family: str | None = _classify()[1]
    except ProviderError:
        family = None
    return {
        "enabled": settings.azure_openai_enabled,
        "endpoint_valid": ok(_endpoint),
        "endpoint_family": family,
        "deployment_configured": ok(_deployment),
        "model_configured": ok(_model_id),
        "api_version": settings.azure_openai_api_version,
        "auth": auth if auth in ("entra", "key") else "invalid",
        "entra_scope": ENTRA_SCOPES.get(family) if family else None,
        "entra_scope_basis": ENTRA_SCOPE_BASIS if family in ENTRA_SCOPES else None,
        "identity_sdk": _identity_sdk(),
        "credential_reference_present": bool(_secret()) if auth == "key" else None,
        "timeout_seconds": settings.azure_openai_timeout_seconds,
        "available": unavailable_reason() is None,
        "unavailable_reason": unavailable_reason(),
    }


async def _entra_token(scope: str) -> str:
    if _token_source is not None:
        return await _token_source(scope)
    try:
        from azure.identity.aio import DefaultAzureCredential
    except ImportError:
        message = f"{CODE}_IDENTITY_SDK_MISSING: azure-identity is not installed"
        raise ProviderError(message) from None
    # ponytail: one credential per round; cache one per process if token latency matters
    async with DefaultAzureCredential() as credential:
        return str((await credential.get_token(scope)).token)


def _delay(attempt: int, retry_after: str | None) -> float:
    try:
        return min(max(float(retry_after or ""), 0.0), RETRY_AFTER_CAP_SECONDS)
    except ValueError:
        return min(0.5 * 2 ** (attempt - 1), RETRY_AFTER_CAP_SECONDS)


class AzureOpenAINativeAdapter(BaseAdapter):
    """Azure OpenAI chat with native governed tool calls. Has no ``register_tool``."""

    adapter_type: str = REGISTRY_KEY
    # Rounds are reserved and settled inside the loop; callers must not reserve again.
    meters_budget: bool = True

    async def _do_create_session(self, session: AgentSession) -> None:
        prompt = session.config.get("system_prompt", "")
        if prompt:
            self._conversation_history[session.session_id] = [{"role": "system", "content": prompt}]

    def validate_config(self, config: dict[str, Any]) -> None:
        """Nothing to validate: endpoint, deployment, auth and key are operator settings."""

    async def _do_execute(
        self, session: AgentSession, task_id: uuid.UUID, payload: dict[str, Any]
    ) -> TaskResult:
        from nexus.models_router.preflight import BudgetExceededError, BudgetInfraUnavailable

        secrets: list[str] = []
        try:
            if (reason := unavailable_reason()) is not None:
                raise ProviderError(reason)
            cm = asyncio.timeout(_timeout())
            async with cm:
                output, artifacts, usage = await self._run(session, task_id, payload, secrets, cm)
        except ProviderError as exc:
            return self._fail(session, task_id, str(exc), secrets)
        except BudgetExceededError:
            return self._fail(session, task_id, f"{CODE}_BUDGET_EXCEEDED", secrets)
        except BudgetInfraUnavailable:
            return self._fail(session, task_id, f"{CODE}_BUDGET_UNAVAILABLE", secrets)
        except TimeoutError:
            return self._fail(session, task_id, f"{CODE}_TIMEOUT", secrets)
        except httpx.HTTPError as exc:
            return self._fail(session, task_id, f"{CODE}_TRANSPORT: {type(exc).__name__}", secrets)
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
        session: AgentSession, task_id: uuid.UUID, error: str, secrets: list[str]
    ) -> TaskResult:
        for secret in filter(None, secrets):
            error = error.replace(secret, REDACTED)
        return TaskResult(task_id=task_id, agent_id=session.agent_id, success=False, error=error)

    async def _run(
        self,
        session: AgentSession,
        task_id: uuid.UUID,
        payload: dict[str, Any],
        secrets: list[str],
        deadline: asyncio.Timeout,
    ) -> tuple[str, list[dict[str, Any]], dict[str, Any]]:
        from nexus.services.streaming_budget import RoundMeter

        ctx = session.context
        prepared = await governed_loop.prepare(ctx, task_id, CODE)
        messages = list(self._conversation_history.get(session.session_id, []))
        messages.append({"role": "user", "content": payload.get("prompt", "")})
        url, deployment, auth = _url(), _deployment(), _auth()
        # The dated route names the deployment in the path and takes max_tokens.
        v1 = _api_version() == "v1"
        limits = governed_loop.Limits(
            CODE,
            max_iterations=MAX_ITERATIONS,
            max_calls=MAX_CALLS,
            max_calls_per_response=MAX_CALLS_PER_RESPONSE,
            max_argument_bytes=MAX_ARGUMENT_BYTES,
            max_tool_result_chars=MAX_TOOL_RESULT_CHARS,
        )
        turn = payload.get("turn_id")
        meter = RoundMeter(
            company_id=ctx.company_id,
            agent_id=ctx.agent_id,
            provider="azure_openai",
            model=_model_id(),
            max_output_tokens=MAX_TOKENS,
            session_id=getattr(ctx, "session_id", None),
            turn_id=uuid.UUID(str(turn)) if turn else None,
            execution_id=task_id,
        )
        on_event = payload.get("on_event")

        def relay(event: Event) -> None:
            # A hard timeout reaches the loop as a cancellation; report it as the error it is.
            if event.type == CANCELLED and deadline.expired():
                event = Event(ERROR, error=f"{CODE}_TIMEOUT")
            if on_event is not None:
                on_event(event)

        async def headers() -> dict[str, str]:
            base = {"Content-Type": "application/json", "Accept": "text/event-stream"}
            if auth == "key":
                key = _secret()
                if not key:
                    raise ProviderError(f"{CODE}_KEY_MISSING: no key in the secret backend")
                secrets.append(key)
                return {**base, "api-key": key}
            token = await self._token(_scope())
            secrets.append(token)
            return {**base, "Authorization": f"Bearer {token}"}

        timeout = httpx.Timeout(READ_TIMEOUT_SECONDS, connect=10.0)
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=False) as client:

            def transport(msgs: list[dict[str, Any]], tools: list[dict[str, Any]]):
                body: dict[str, Any] = {
                    "messages": msgs,
                    "stream": True,
                    "stream_options": {"include_usage": True},
                    "max_completion_tokens" if v1 else "max_tokens": MAX_TOKENS,
                }
                if v1:
                    body["model"] = deployment
                if tools:
                    body["tools"] = tools
                    body["tool_choice"] = "auto"
                return self._stream(client, url, headers, body)

            done = await governed_loop.run(
                prepared,
                task_id,
                messages,
                transport,
                limits,
                meter=meter,
                on_event=relay,
                cancelled=payload.get("cancelled"),
            )
        self._conversation_history[session.session_id] = done.messages
        return done.text, done.artifacts, done.usage

    @staticmethod
    async def _token(scope: str) -> str:
        try:
            token = await _entra_token(scope)
        except ProviderError:
            raise
        except Exception:  # noqa: BLE001 -- identity errors can carry tenant detail; keep the code only
            raise ProviderError(f"{CODE}_AUTH_FAILED: could not obtain an Entra token") from None
        if not token:
            raise ProviderError(f"{CODE}_AUTH_FAILED: could not obtain an Entra token")
        return token

    @staticmethod
    async def _stream(
        client: httpx.AsyncClient,
        url: str,
        headers: Callable[[], Awaitable[dict[str, str]]],
        body: dict[str, Any],
    ):
        """One streamed request. Retries only before the first response byte is consumed."""
        attempt = 0
        while True:
            hdrs = await headers()
            retry_after = None
            try:
                async with client.stream("POST", url, json=body, headers=hdrs) as resp:
                    if resp.status_code == 200:
                        async with aclosing(
                            governed_loop.sse_chunks(resp.aiter_lines(), CODE, MAX_RESPONSE_BYTES)
                        ) as chunks:
                            async for chunk in chunks:
                                yield chunk
                        return
                    status_code = resp.status_code
                    retry_after = resp.headers.get("retry-after")
            except (httpx.ConnectError, httpx.ConnectTimeout):
                status_code = 0
            if status_code in RETRYABLE and attempt < _retries():
                attempt += 1
                await _sleep(_delay(attempt, retry_after))
                continue
            raise ProviderError(
                f"{CODE}_HTTP_{status_code}" if status_code else f"{CODE}_TRANSPORT"
            )

    async def _do_heartbeat(self, session: AgentSession) -> bool:
        return True

    async def _do_terminate(self, session: AgentSession) -> None:
        self._conversation_history.pop(session.session_id, None)
