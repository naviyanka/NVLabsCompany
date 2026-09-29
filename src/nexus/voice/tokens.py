"""Signed voice-session tickets and the worker's short-lived internal tokens."""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass

import jwt

from nexus.config import settings

TICKET_AUDIENCE = "nexus:voice-ticket"
WORKER_AUDIENCE = "nexus:voice-worker"  # must match nexus_voice.tokens.AUDIENCE
WORKER_TTL = 60


class TicketError(Exception):
    pass


@dataclass(frozen=True)
class VoiceSession:
    """Everything the server binds a voice session to; the browser supplies none of it."""

    id: str
    user_id: uuid.UUID
    company_id: uuid.UUID
    ceo_id: uuid.UUID
    chat_session_id: uuid.UUID
    mode: str
    voice_en: str
    voice_hi: str
    expires_at: float
    jti: str


def mint_ticket(s: VoiceSession, ttl: int) -> str:
    now = int(time.time())
    return jwt.encode(
        {
            "aud": TICKET_AUDIENCE,
            "iat": now,
            "exp": now + ttl,
            "jti": s.jti,
            "vsid": s.id,
            "sub": str(s.user_id),
            "cid": str(s.company_id),
            "ceo": str(s.ceo_id),
            "chat": str(s.chat_session_id),
            "mode": s.mode,
            "ven": s.voice_en,
            "vhi": s.voice_hi,
            "sx": s.expires_at,
        },
        settings.secret_key,
        algorithm="HS256",
    )


def read_ticket(token: str) -> tuple[VoiceSession, float]:
    """Verify a ticket; returns the session and the ticket's own expiry."""
    try:
        c = jwt.decode(
            token,
            settings.secret_key,
            algorithms=["HS256"],
            audience=TICKET_AUDIENCE,
            options={"require": ["exp", "jti", "vsid", "sub", "cid", "ceo", "chat", "sx"]},
        )
        return VoiceSession(
            id=c["vsid"],
            user_id=uuid.UUID(c["sub"]),
            company_id=uuid.UUID(c["cid"]),
            ceo_id=uuid.UUID(c["ceo"]),
            chat_session_id=uuid.UUID(c["chat"]),
            mode=c["mode"],
            voice_en=c["ven"],
            voice_hi=c["vhi"],
            expires_at=float(c["sx"]),
            jti=c["jti"],
        ), float(c["exp"])
    except (jwt.PyJWTError, KeyError, ValueError) as exc:
        raise TicketError("invalid ticket") from exc


def mint_worker_token(voice_session_id: str, scope: str) -> str:
    now = int(time.time())
    return jwt.encode(
        {
            "aud": WORKER_AUDIENCE,
            "iat": now,
            "exp": now + WORKER_TTL,
            "jti": uuid.uuid4().hex,
            "sid": voice_session_id,
            "scope": scope,
        },
        settings.voice_worker_secret,
        algorithm="HS256",
    )
