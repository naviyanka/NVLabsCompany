"""Legacy Telegram inbound webhook: permanently disabled.

This route used to run bot commands (``/task``, ``/agents``, ``/status``) for
the company bound to the request's API key. An API key identifies a company,
not the human who sent the Telegram message, so every sender was treated as an
authorized operator and ``/task`` created Tasks on their behalf.

The route is kept only so existing webhook registrations get a stable,
sanitized answer. It reads no request body, touches no database row, sends no
Telegram message and does not depend on a company or principal. Outbound
Telegram notifications are unaffected: they live in the ``msg-telegram-send``
workflow node.

The secure replacement (provider verification, channel installation, linked
identity, active membership, NEXUS principal, normal authorization) is tracked
in ADR 0006. See ``docs/security/LEGACY_CHANNEL_INGRESS.md``.
"""

import logging

from fastapi import APIRouter
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)

router = APIRouter(tags=["channels"])

LEGACY_CHANNEL_INGRESS_DISABLED = "LEGACY_CHANNEL_INGRESS_DISABLED"


@router.post("/api/v1/channels/telegram/webhook", deprecated=True)
async def telegram_webhook() -> JSONResponse:
    """Refuse every legacy Telegram update without reading it."""
    logger.warning("Legacy channel ingress rejected: channel=telegram")
    return JSONResponse(
        status_code=410,
        content={
            "detail": "Legacy Telegram inbound commands are disabled.",
            "code": LEGACY_CHANNEL_INGRESS_DISABLED,
        },
    )
