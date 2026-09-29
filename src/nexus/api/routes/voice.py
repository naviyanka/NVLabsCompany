"""Local CEO voice gateway: session issue (REST) and the audio WebSocket.

The company, CEO, chat session and expiry are chosen here from the authenticated
principal; the browser only asks for a language mode and voices.
"""

from __future__ import annotations

import time
import uuid
from typing import Literal

from fastapi import APIRouter, HTTPException, Request, WebSocket, status
from pydantic import BaseModel

from nexus.api.deps import CurrentCompanyId, CurrentPrincipal, DbSession
from nexus.auth.middleware import get_principal_from_scope
from nexus.config import settings
from nexus.governance.audit_service import record_audit
from nexus.services import ceo_service
from nexus.services.session_service import get_or_create_default_session
from nexus.voice import gateway, protocol, worker_client
from nexus.voice.tokens import VoiceSession, mint_ticket

router = APIRouter(tags=["voice"])


class VoiceSessionRequest(BaseModel):
    mode: Literal["auto", "hi", "en", "mixed"] = "auto"
    voice_en: str | None = None
    voice_hi: str | None = None


def _refuse(code: str, message: str, http: int) -> HTTPException:
    return HTTPException(status_code=http, detail={"code": code, "message": message})


@router.get("/api/v1/voice/status")
async def voice_status(
    principal: CurrentPrincipal, db: DbSession, company_id: CurrentCompanyId
) -> dict:
    ceo = await ceo_service.current_ceo(db, company_id) if settings.voice_enabled else None
    # Voice catalogue (licence, commercial-use flag, installed) comes from the worker itself.
    catalog = await worker_client.worker_get("/v1/voices") if settings.voice_enabled else None
    return {
        "voices": (catalog or {}).get("voices", []),
        "allow_noncommercial_models": (catalog or {}).get("allow_noncommercial", False),
        "worker_reachable": catalog is not None,
        "ceo_id": str(ceo.id) if ceo else None,
        "enabled": settings.voice_enabled,
        "protocol": protocol.VERSION,
        "modes": list(protocol.MODES),
        "default_voices": {"en": settings.voice_default_en, "hi": settings.voice_default_hi},
        "max_utterance_seconds": settings.voice_max_utterance_seconds,
        "raw_audio_stored": False,
    }


@router.post("/api/v1/voice/sessions", status_code=status.HTTP_201_CREATED)
async def create_voice_session(
    body: VoiceSessionRequest,
    request: Request,
    db: DbSession,
    company_id: CurrentCompanyId,
    principal: CurrentPrincipal,
) -> dict:
    if not settings.voice_enabled:
        raise _refuse("VOICE_DISABLED", "Voice is not enabled on this server", 404)
    if principal.kind != "user" or principal.user_id is None:
        raise _refuse("HUMAN_REQUIRED", "Voice needs a signed-in person", 403)
    for v in (body.voice_en, body.voice_hi):
        if v is not None and not gateway.valid_voice(v):
            raise _refuse("BAD_VOICE", "Unknown voice id", 422)
    if not gateway.ensure_state(request.app).voice_session_limits.allow(
        f"{company_id}:{principal.user_id}"
    ):
        raise _refuse("RATE_LIMITED", "Too many voice sessions; wait a moment", 429)
    ceo = await ceo_service.current_ceo(db, company_id)
    if ceo is None:
        raise _refuse("NO_CEO", "This company has no designated CEO", 409)
    chat = await get_or_create_default_session(db, ceo)
    now = time.time()
    sess = VoiceSession(
        id=uuid.uuid4().hex,
        user_id=principal.user_id,
        company_id=company_id,
        ceo_id=ceo.id,
        chat_session_id=chat.id,
        mode=body.mode,
        voice_en=body.voice_en or settings.voice_default_en,
        voice_hi=body.voice_hi or settings.voice_default_hi,
        expires_at=now + settings.voice_session_ttl_seconds,
        jti=uuid.uuid4().hex,
    )
    await record_audit(
        company_id,
        "voice.session_started",
        actor_type="user",
        actor_id=str(principal.user_id),
        resource_type="agent",
        resource_id=str(ceo.id),
        details={"voice_session_id": sess.id, "mode": sess.mode},
        db=db,
    )
    await db.commit()
    return {
        "voice_session_id": sess.id,
        "ticket": mint_ticket(sess, settings.voice_ticket_ttl_seconds),
        "ws_path": "/api/v1/voice/ws",
        "expires_at": sess.expires_at,
        "protocol": protocol.VERSION,
        "mode": sess.mode,
        "voices": {"en": sess.voice_en, "hi": sess.voice_hi},
        "ceo": {"id": str(ceo.id), "name": ceo.name},
        "chat_session_id": str(chat.id),
    }


@router.websocket("/api/v1/voice/ws")
async def voice_socket(websocket: WebSocket) -> None:
    principal = get_principal_from_scope(websocket.scope)
    if principal is None or not settings.voice_enabled:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return
    await gateway.serve(websocket, principal)
