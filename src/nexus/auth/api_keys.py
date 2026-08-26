"""API key authentication for service callers.

A key is presented as ``Authorization: Bearer nv_...``. Only its SHA-256 hash is
stored, so lookup is by hash — the same reason the login cookie is stored
hashed. A key resolves to a service principal scoped to the key's company and
limited to the key's own role.

Bearer keys are exempt from CSRF checks: CSRF defends against a browser
attaching a cookie the user did not intend to send, and no browser attaches an
``Authorization`` header on a cross-site request by accident.
"""

import uuid

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from nexus.models._time import utcnow
from nexus.models.api_key import ApiKey

# Every key issued by ApiKey.generate_key() starts with this.
KEY_PREFIX = "nv_"


def looks_like_api_key(credential: str) -> bool:
    """Whether a bearer credential is shaped like one of our API keys."""
    return credential.startswith(KEY_PREFIX)


async def resolve_api_key(db: AsyncSession, credential: str) -> ApiKey | None:
    """Look up an active, unexpired API key by its plaintext value.

    Returns ``None`` for an unknown, revoked or expired key. An expired key is
    also flipped to ``status="expired"`` so the dashboard reflects reality
    without a separate sweep job.
    """
    if not looks_like_api_key(credential):
        return None

    stmt = select(ApiKey).where(ApiKey.key_hash == ApiKey.hash_key(credential))
    key = (await db.execute(stmt)).scalars().first()

    if key is None or key.status != "active":
        return None

    if key.expires_at is not None and key.expires_at <= utcnow():
        await db.execute(update(ApiKey).where(ApiKey.id == key.id).values(status="expired"))
        return None

    return key


async def touch_api_key(db: AsyncSession, key_id: uuid.UUID) -> None:
    """Record that a key was used."""
    await db.execute(update(ApiKey).where(ApiKey.id == key_id).values(last_used_at=utcnow()))
