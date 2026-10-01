"""Verification of the short-lived worker tokens minted by the NEXUS backend.

The worker holds no database and trusts no client claim: it only checks that the
backend signed a token for this audience, that it is fresh, and that it is used once.
"""

from __future__ import annotations

import time

import jwt

AUDIENCE = "nexus:voice-worker"
MAX_TTL_S = 120


class TokenError(Exception):
    pass


class TokenVerifier:
    def __init__(self, secret: str) -> None:
        if len(secret) < 32:
            raise ValueError("NEXUS_VOICE_WORKER_SECRET must be at least 32 characters")
        self.secret = secret
        self._seen: dict[str, float] = {}

    def verify(self, token: str, scope: str) -> dict:
        try:
            claims = jwt.decode(
                token,
                self.secret,
                algorithms=["HS256"],
                audience=AUDIENCE,
                options={"require": ["exp", "iat", "jti", "sid", "scope"]},
            )
        except jwt.PyJWTError as exc:
            raise TokenError("invalid token") from exc
        if claims["scope"] != scope or claims["exp"] - claims["iat"] > MAX_TTL_S:
            raise TokenError("invalid token")
        now = time.time()
        self._seen = {j: e for j, e in self._seen.items() if e > now}
        if claims["jti"] in self._seen:
            raise TokenError("token already used")
        self._seen[claims["jti"]] = claims["exp"]
        return claims
