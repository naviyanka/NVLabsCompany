"""Public inbound webhook intake.

A trigger with ``trigger_type == "webhook"`` was only ever outbound: the
scheduler POSTs to a configured URL. Nothing let an external service fire a
trigger *into* the platform, because every other trigger route requires an
authenticated company and an external caller has no session.

This route is that entry point. Authentication is a per-trigger secret stored in
the trigger's ``config`` under ``inbound_secret``, verified in constant time.
Rate limiting, body size capping and the constant-time comparison all come from
``nexus.communication.webhook_server``, which already implements them.

An unknown trigger id and a wrong secret are answered identically, so the
endpoint cannot be used to discover which triggers exist.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Request, Response, status
from sqlmodel import select

from nexus.api.deps import DbSession
from nexus.communication.webhook_server import (
    MAX_BODY_BYTES,
    PER_ENDPOINT_RATE_LIMIT,
    RATE_LIMIT,
    WebhookServer,
)
from nexus.models.trigger import Trigger, TriggerExecution

logger = logging.getLogger(__name__)

router = APIRouter(tags=["webhooks"])

# Bucket for requests naming no known trigger, so a flood of guesses cannot
# consume a real trigger's allowance.
UNKNOWN_BUCKET = "__unknown__"

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
    """The single response used for every rejection.

    Unknown trigger, wrong secret, disabled trigger and wrong type all produce
    this. Distinguishing them would let a caller enumerate triggers.
    """
    return Response(status_code=status.HTTP_401_UNAUTHORIZED, content="")


@router.post("/api/v1/webhooks/{trigger_id}", include_in_schema=True)
async def receive_webhook(
    trigger_id: str,
    request: Request,
    db: DbSession,
) -> Response:
    """Fire a webhook trigger from an external service.

    The caller proves itself with the trigger's ``inbound_secret``, sent as
    ``X-Webhook-Secret``. The request body, if it is JSON, is passed to the
    agent as the trigger's payload.

    Args:
        trigger_id: The trigger to fire.
        request: The inbound request, read for its body and secret header.
        db: Database session.

    Returns:
        202 when the trigger fired, 401 for any rejection, 413 for an oversized
        body, 429 when rate limited.
    """
    server = _get_server()

    # Rate limit before any parsing or database work, so a flood costs little.
    if not server.allow_request("", RATE_LIMIT):
        return Response(status_code=status.HTTP_429_TOO_MANY_REQUESTS, content="")

    body = await request.body()
    if len(body) > MAX_BODY_BYTES:
        return Response(status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, content="")

    provided = request.headers.get("X-Webhook-Secret", "")

    try:
        parsed_id = uuid.UUID(trigger_id)
    except ValueError:
        # A malformed id cannot match anything, but it still consumes the
        # unknown bucket so probing is bounded.
        server.allow_request(UNKNOWN_BUCKET, PER_ENDPOINT_RATE_LIMIT)
        server.verify_secret(provided, None)
        return _refused()

    trigger = (
        await db.execute(select(Trigger).where(Trigger.id == parsed_id))
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

    payload: Any = None
    if body:
        try:
            import json

            payload = json.loads(body)
        except ValueError:
            payload = {"raw": body.decode("utf-8", errors="replace")[:10_000]}

    await _fire_inbound(db, trigger, payload)
    await db.commit()

    return Response(status_code=status.HTTP_202_ACCEPTED, content="")


async def _fire_inbound(db: Any, trigger: Trigger, payload: Any) -> None:
    """Run the trigger's agent against the inbound payload.

    Mirrors how the scheduler fires an agent-based trigger, so an inbound
    webhook and a scheduled tick produce the same kind of TriggerExecution row.
    """
    from nexus.api.routes.chat import _build_system_prompt, _call_llm
    from nexus.models.agent import Agent

    agent = (
        await db.execute(
            select(Agent).where(
                Agent.id == trigger.agent_id,
                Agent.company_id == trigger.company_id,
            )
        )
    ).scalar_one_or_none()

    now = datetime.now(UTC).replace(tzinfo=None)

    if agent is None:
        db.add(
            TriggerExecution(
                trigger_id=trigger.id,
                company_id=trigger.company_id,
                status="failed",
                error=f"Agent {trigger.agent_id} not found",
                completed_at=now,
            )
        )
        return

    config = trigger.config or {}
    prompt = config.get(
        "prompt", config.get("message", f"Handle inbound webhook: {trigger.name}")
    )
    if payload is not None:
        prompt = f"{prompt}\n\nInbound payload:\n{payload}"

    try:
        system_prompt = _build_system_prompt(agent)
        response_text, model_used, tokens_used = await _call_llm(
            agent, system_prompt, prompt, []
        )
        db.add(
            TriggerExecution(
                trigger_id=trigger.id,
                company_id=trigger.company_id,
                status="success",
                result={
                    "output": response_text[:5000],
                    "model": model_used,
                    "tokens": tokens_used,
                },
                completed_at=now,
            )
        )
        logger.info("Inbound webhook fired trigger '%s'", trigger.name)
    except Exception as exc:  # noqa: BLE001 - the caller gets 202 regardless
        db.add(
            TriggerExecution(
                trigger_id=trigger.id,
                company_id=trigger.company_id,
                status="failed",
                error=str(exc)[:1000],
                completed_at=now,
            )
        )
        logger.warning("Inbound webhook for trigger %s failed: %s", trigger.id, exc)

    trigger.last_fired_at = now
    db.add(trigger)
