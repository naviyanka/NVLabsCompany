"""Legacy Slack Events API inbound endpoint: permanently disabled.

This route used to create a Task for every ``app_mention`` event, in the company
bound to the request's API key. An API key identifies a company, not the Slack
user who wrote the message, and the route verified no Slack signature, so any
sender could create Tasks. Slack's ``url_verification`` challenge is refused as
well, so the endpoint cannot be registered with Slack and look supported.

The route is kept only so existing Slack app configurations get a stable,
sanitized answer. It reads no request body, touches no database row and does
not depend on a company or principal. Outbound Slack notifications are
unaffected: they live in ``nexus.communication.channels``.

The secure replacement is tracked in ADR 0006. See
``docs/security/LEGACY_CHANNEL_INGRESS.md``.
"""

import logging

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from nexus.api.routes.telegram_bot import LEGACY_CHANNEL_INGRESS_DISABLED

router = APIRouter(tags=["channels"])

logger = logging.getLogger(__name__)


@router.post("/api/v1/channels/slack/events", deprecated=True)
async def slack_events() -> JSONResponse:
    """Refuse every legacy Slack event without reading it."""
    logger.warning("Legacy channel ingress rejected: channel=slack")
    return JSONResponse(
        status_code=410,
        content={
            "detail": "Legacy Slack inbound events are disabled.",
            "code": LEGACY_CHANNEL_INGRESS_DISABLED,
        },
    )
