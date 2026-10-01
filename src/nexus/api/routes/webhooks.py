"""Inbound webhook intake.

A trigger with ``trigger_type == "webhook"`` was only ever outbound: the
scheduler POSTs to a configured URL. Nothing let an external service fire a
trigger *into* the platform, because every other trigger route requires an
authenticated company and an external caller has no session.

This route is that entry point. Authentication is a per-trigger secret stored in
the trigger's ``config`` under ``inbound_secret``, verified in constant time. The
secret authenticates the integration, not a person: the run acts as the trigger's
agent, in the trigger's company, and the payload cannot change either.
Rate limiting, body size capping and the constant-time comparison all come from
``nexus.communication.webhook_server``, which already implements them.

An unknown trigger id and a wrong secret are answered identically, so the
endpoint cannot be used to discover which triggers exist.

Every delivery needs an ``Idempotency-Key``. After the secret is verified the
delivery is claimed in ``idempotency_records`` (see
``nexus.communication.webhook_idempotency``); a retry of the same key and payload
replays the first answer and runs nothing, and the same key with another payload
is refused. The payload is delivered to the model as untrusted data in a fixed
envelope (see ``nexus.communication.webhook_payload``). No database transaction
is open while the model runs. Payloads, secrets, idempotency keys and headers are
never logged.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import re
import uuid
from dataclasses import dataclass
from typing import Any

from fastapi import APIRouter, Request, Response, status
from fastapi.responses import JSONResponse
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from nexus.communication import webhook_idempotency as ledger
from nexus.communication.webhook_payload import (
    PayloadRejected,
    parse_payload,
    payload_hash,
    render_envelope,
)
from nexus.communication.webhook_server import (
    MAX_BODY_BYTES,
    PER_ENDPOINT_RATE_LIMIT,
    RATE_LIMIT,
    WebhookServer,
)
from nexus.database import async_session_factory, tenant_session
from nexus.memory.safety import redact_text
from nexus.models._time import utcnow
from nexus.models.trigger import Trigger, TriggerExecution

logger = logging.getLogger(__name__)

router = APIRouter(tags=["webhooks"])

# Bucket for requests naming no known trigger, so a flood of guesses cannot
# consume a real trigger's allowance.
UNKNOWN_BUCKET = "__unknown__"

# 8-128 characters, no separators or whitespace: safe in a database key and a log.
IDEMPOTENCY_KEY_RE = re.compile(r"^[A-Za-z0-9._-]{8,128}$")

# One process-wide server instance holds the rate-limit windows and the decoy
# secret. Constructed lazily so importing this module does not depend on config.
_server: WebhookServer | None = None


def _get_server() -> WebhookServer:
    """Return the shared server, which owns the rate-limit state.

    Only ``verify_secret`` and ``allow_request`` are used from it — this route
    resolves endpoints from trigger rows and dispatches through the agent itself,
    so the server's own message and status callbacks are never reached. They are
    stubbed rather than implemented for that reason.
    """
    global _server
    if _server is None:
        _server = WebhookServer(
            endpoints=[],
            on_message=lambda _inbound, _ref: None,
            lookup_status=lambda _token: None,
        )
    return _server


def _refused() -> Response:
    """The single response used for every authentication rejection.

    Unknown trigger, wrong secret, disabled trigger and wrong type all produce
    this. Distinguishing them would let a caller enumerate triggers.
    """
    return Response(status_code=status.HTTP_401_UNAUTHORIZED, content="")


def _error(status_code: int, code: str, detail: str, **headers: str) -> JSONResponse:
    return JSONResponse(
        status_code=status_code, content={"code": code, "detail": detail}, headers=headers
    )


async def _read_body(request: Request) -> bytes | None:
    """The request body, or ``None`` when it exceeds ``MAX_BODY_BYTES``."""
    declared = request.headers.get("content-length", "")
    if declared.isdigit() and int(declared) > MAX_BODY_BYTES:
        return None
    chunks: list[bytes] = []
    size = 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > MAX_BODY_BYTES:
            return None
        chunks.append(chunk)
    return b"".join(chunks)


@router.post("/api/v1/webhooks/{trigger_id}", include_in_schema=True)
async def receive_webhook(trigger_id: str, request: Request) -> Response:
    """Fire a webhook trigger from an external service.

    The caller proves itself with the trigger's ``inbound_secret``, sent as
    ``X-Webhook-Secret``, and names the delivery with a single ``Idempotency-Key``
    header (8-128 characters of ``A-Za-z0-9._-``). A non-empty body must be JSON
    with ``Content-Type: application/json``; it reaches the agent as untrusted data.

    Returns:
        202 with ``{"execution_id", "outcome", "status"}`` when the delivery ran,
        and the same body with ``Idempotent-Replay: true`` when a retry replays it.
        401 for any authentication rejection, 409 when the key was used with a
        different payload or the original delivery is still running, 413 for a
        body, string or payload over its limit, 415 for a body that is not JSON,
        400 for malformed JSON, 422 for a missing or invalid key or an over-deep
        payload, 429 when rate limited.
    """
    server = _get_server()

    # Rate limit before any parsing or database work, so a flood costs little.
    if not server.allow_request("", RATE_LIMIT):
        return Response(status_code=status.HTTP_429_TOO_MANY_REQUESTS, content="")

    body = await _read_body(request)
    if body is None:
        return Response(status_code=413, content="")

    provided = request.headers.get("X-Webhook-Secret", "")

    try:
        parsed_id = uuid.UUID(trigger_id)
    except ValueError:
        # A malformed id cannot match anything, but it still consumes the
        # unknown bucket so probing is bounded.
        server.allow_request(UNKNOWN_BUCKET, PER_ENDPOINT_RATE_LIMIT)
        server.verify_secret(provided, None)
        return _refused()

    # A short session of its own: nothing stays open once the row is read.
    async with async_session_factory() as lookup:
        trigger = (
            await lookup.execute(select(Trigger).where(Trigger.id == parsed_id))
        ).scalar_one_or_none()

    bucket = str(parsed_id) if trigger is not None else UNKNOWN_BUCKET
    if not server.allow_request(bucket, PER_ENDPOINT_RATE_LIMIT):
        return Response(status_code=status.HTTP_429_TOO_MANY_REQUESTS, content="")

    config: dict[str, Any] = (trigger.config or {}) if trigger is not None else {}
    secret = config.get("inbound_secret")

    # verify_secret compares against a decoy when the endpoint is absent, so the
    # timing of an unknown trigger matches that of a wrong secret.
    endpoint = None
    if trigger is not None and secret:
        from nexus.communication.webhook_types import WebhookEndpoint

        endpoint = WebhookEndpoint(
            id=str(parsed_id), name=trigger.name, secret=str(secret)
        )

    if not server.verify_secret(provided, endpoint):
        return _refused()

    # Only now is it safe to reveal nothing further: the caller holds the secret.
    if not trigger.is_active or trigger.trigger_type != "webhook":
        return _refused()

    # Authenticated. Validate everything before a delivery is claimed.
    keys = request.headers.getlist("idempotency-key")
    if not keys:
        return _error(
            422, "WEBHOOK_IDEMPOTENCY_KEY_REQUIRED", "An Idempotency-Key header is required"
        )
    if len(keys) != 1 or not IDEMPOTENCY_KEY_RE.fullmatch(keys[0]):
        return _error(
            422,
            "WEBHOOK_IDEMPOTENCY_KEY_INVALID",
            "Idempotency-Key must be one header of 8-128 characters from A-Za-z0-9._-",
        )
    key = keys[0]

    try:
        payload = parse_payload(body, request.headers.get("content-type"))
        envelope = render_envelope(payload) if payload is not None else None
    except PayloadRejected as exc:
        return _error(exc.status, exc.code, str(exc))
    request_hash = payload_hash(payload)

    begun = await ledger.begin(trigger.company_id, parsed_id, key, request_hash)
    if begun.outcome is ledger.Outcome.BUSY:
        # No waiting: the caller retries and gets the recorded result.
        return _in_flight()
    if begun.outcome is ledger.Outcome.CONFLICT:
        return _error(
            409,
            "WEBHOOK_IDEMPOTENCY_CONFLICT",
            "This Idempotency-Key was already used with a different payload",
        )
    if begun.outcome is ledger.Outcome.REPLAY:
        return Response(
            status_code=begun.status_code or status.HTTP_202_ACCEPTED,
            content=begun.body or "",
            media_type="application/json",
            headers={"Idempotent-Replay": "true"},
        )

    claim = begun.claim
    try:
        ran = await _run_trigger(trigger, envelope)
        execution_id = uuid.uuid4()
        answer = {
            "execution_id": str(execution_id),
            "outcome": ran.status,
            "status": "accepted",
        }

        async def effect(session: AsyncSession) -> None:
            session.add(
                TriggerExecution(
                    id=execution_id,
                    trigger_id=trigger.id,
                    company_id=trigger.company_id,
                    status=ran.status,
                    result=ran.result,
                    error=ran.error,
                    completed_at=ran.finished_at,
                )
            )
            await session.execute(
                update(Trigger)
                .where(Trigger.id == trigger.id)
                .values(last_fired_at=ran.finished_at)
            )

        recorded = await ledger.finish(
            trigger.company_id, claim, effect, status.HTTP_202_ACCEPTED, answer
        )
    except BaseException:
        # Cancelled or an infrastructure failure before anything was recorded:
        # free the key so the sender's retry runs at once, not after the lease.
        with contextlib.suppress(Exception):
            await asyncio.shield(ledger.release(trigger.company_id, claim))
        raise

    if not recorded:
        # Our lease expired and another worker took the delivery over.
        return _in_flight()
    return JSONResponse(status_code=status.HTTP_202_ACCEPTED, content=answer)


def _in_flight() -> JSONResponse:
    return _error(
        409,
        "WEBHOOK_REQUEST_IN_FLIGHT",
        "A delivery with this Idempotency-Key is still running; retry shortly",
        **{"Retry-After": "2"},
    )


@dataclass(frozen=True)
class _Ran:
    status: str
    result: dict[str, Any] | None
    error: str | None
    finished_at: Any


async def _run_trigger(trigger: Trigger, envelope: str | None) -> _Ran:
    """Run the trigger's agent against the inbound payload; no transaction is held.

    Mirrors how the scheduler fires an agent-based trigger. The agent runs with
    ``principal=None``: autonomous work under the agent's own role, so ToolPolicy,
    approvals and budgets decide what it may do exactly as they do for the
    scheduler. The payload is never a system message.
    """
    from nexus.api.routes.chat import _build_system_prompt, _call_llm
    from nexus.models.agent import Agent

    # tenant_session: agents are under RLS, so a lookup without the tenant sees nothing.
    async with tenant_session(trigger.company_id) as session:
        agent = (
            await session.execute(
                select(Agent).where(
                    Agent.id == trigger.agent_id,
                    Agent.company_id == trigger.company_id,
                )
            )
        ).scalar_one_or_none()

    if agent is None:
        return _Ran("failed", None, f"Agent {trigger.agent_id} not found", utcnow())

    config = trigger.config or {}
    prompt = config.get(
        "prompt", config.get("message", f"Handle inbound webhook: {trigger.name}")
    )
    if envelope is not None:
        prompt = f"{prompt}\n\n{envelope}"

    try:
        system_prompt = _build_system_prompt(agent)
        response_text, model_used, tokens_used = await _call_llm(
            agent, system_prompt, prompt, []
        )
    except Exception as exc:  # noqa: BLE001 - the caller gets 202 regardless
        # The class name only: a provider error can echo the prompt, payload included.
        logger.warning(
            "Inbound webhook for trigger %s failed: %s", trigger.id, type(exc).__name__
        )
        return _Ran("failed", None, redact_text(str(exc))[0][:1000], utcnow())

    logger.info("Inbound webhook fired trigger '%s'", trigger.name)
    return _Ran(
        "success",
        {"output": response_text[:5000], "model": model_used, "tokens": tokens_used},
        None,
        utcnow(),
    )
