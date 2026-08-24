"""Server-side session store backing the login cookie.

The cookie holds an opaque random token. Only its SHA-256 hash reaches the
database, so a dump of ``user_sessions`` yields nothing a caller can present as
a credential. A session is usable while its row is unrevoked and unexpired,
which makes "log out everywhere" and per-device revocation a single UPDATE
rather than a token blocklist.

This is intentionally not an implementation of the fastapi-users ``Strategy``
protocol. That protocol exists to serve fastapi-users' own login routers, which
this application does not mount: login has to select a company and record a
membership, so it is a route of ours. What fastapi-users does provide — the user
manager and the password helper — is used directly.
"""

import hashlib
import secrets
import uuid
from datetime import timezone, timedelta

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from nexus.config import settings
from nexus.models._time import utcnow
from nexus.models.user_profile import UserSession

# Number of random bytes behind a session token. 32 bytes is well beyond
# guessing range and keeps the cookie short.
_TOKEN_BYTES = 32


def generate_token() -> str:
    """Generate a fresh opaque session token."""
    return secrets.token_urlsafe(_TOKEN_BYTES)


def hash_token(token: str) -> str:
    """Hash a session token for storage or lookup."""
    return hashlib.sha256(token.encode()).hexdigest()


async def create_session(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    company_id: uuid.UUID,
    browser: str = "",
    ip_address: str = "",
    lifetime_seconds: int | None = None,
) -> tuple[str, UserSession]:
    """Open a session and return its plaintext token alongside the stored row.

    The token is returned once, for the caller to put in a cookie. It cannot be
    recovered from the row afterwards.
    """
    token = generate_token()
    lifetime = lifetime_seconds or settings.session_lifetime_seconds
    session = UserSession(
        user_id=user_id,
        company_id=company_id,
        token_hash=hash_token(token),
        browser=browser[:255],
        ip_address=ip_address[:45],
        is_current=True,
        expires_at=now(timezone.utc) + timedelta(seconds=lifetime),
    )
    db.add(session)
    await db.flush()
    return token, session


async def resolve_session(db: AsyncSession, token: str) -> UserSession | None:
    """Look up a live session by its plaintext token.

    Returns ``None`` for an unknown, revoked or expired token. Expiry is checked
    in Python against the same naive-UTC clock that wrote ``expires_at``; a row
    with no expiry is treated as expired rather than eternal, so the placeholder
    rows backfilled by the auth migration cannot authenticate anyone.
    """
    if not token:
        return None

    stmt = select(UserSession).where(UserSession.token_hash == hash_token(token))
    session = (await db.execute(stmt)).scalars().first()

    if session is None or session.revoked_at is not None:
        return None
    if session.expires_at is None or session.expires_at <= now(timezone.utc):
        return None

    return session


async def touch_session(db: AsyncSession, session_id: uuid.UUID) -> None:
    """Record activity on a session without extending its expiry."""
    await db.execute(
        update(UserSession).where(UserSession.id == session_id).values(last_active_at=now(timezone.utc))
    )


async def revoke_session(db: AsyncSession, session_id: uuid.UUID) -> bool:
    """Revoke one session. Returns False if it was already gone or revoked."""
    result = await db.execute(
        update(UserSession)
        .where(UserSession.id == session_id, UserSession.revoked_at.is_(None))
        .values(revoked_at=now(timezone.utc), is_current=False)
    )
    return bool(result.rowcount)


async def revoke_user_sessions(
    db: AsyncSession,
    user_id: uuid.UUID,
    *,
    keep_session_id: uuid.UUID | None = None,
) -> int:
    """Revoke every live session for a user, optionally sparing the current one.

    Used by "sign out of all devices" and after a password change, where any
    session opened with the old password must stop working.
    """
    stmt = (
        update(UserSession)
        .where(UserSession.user_id == user_id, UserSession.revoked_at.is_(None))
        .values(revoked_at=now(timezone.utc), is_current=False)
    )
    if keep_session_id is not None:
        stmt = stmt.where(UserSession.id != keep_session_id)

    result = await db.execute(stmt)
    return int(result.rowcount or 0)
