"""The signed-in user's own profile.

Scoped to ``principal.user_id``, not to the company. The previous version looked
its subject up with ``select(UserProfile).where(company_id == ...)`` and took
whichever row came back first, so in any company with more than one member every
caller read and wrote a colleague's profile — and when the table was empty it
invented a row for ``admin@nvlabs.company`` and returned it as fact.

Credential and session management deliberately does not live here. It lives in
:mod:`nexus.api.routes.auth`, which owns the session table:

* ``POST /api/v1/auth/change-password`` verifies the current password and revokes
  the caller's other sessions. The version formerly on this router verified
  nothing and returned ``{"success": true}`` without touching the database.
* ``GET /api/v1/auth/sessions``, ``DELETE /api/v1/auth/sessions/{id}`` and
  ``POST /api/v1/auth/sessions/revoke-others`` are scoped by user. The versions
  formerly here were scoped by *company* and issued hard ``DELETE``s against
  ``user_sessions`` — the same table the login cookie resolves through — so any
  member could sign out everyone in the company, and the "revoke all" variant
  keyed off the mutable ``is_current`` flag rather than the caller's own session.

Two-factor enrolment is likewise absent. Nothing in the login path checks a
second factor yet, so an endpoint that flipped ``two_factor_enabled`` to true
would report protection the server does not enforce. The column stays; the
switch arrives with the TOTP verification that makes it mean something.
"""

import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from nexus.api.deps import DbSession, PathCompanyId, RequireUser
from nexus.models._time import utcnow
from nexus.models.user_profile import UserProfile

router = APIRouter(tags=["profile"])

# Settable through this endpoint. Everything else on the row is either identity
# the server assigns (id, company_id, timestamps) or authority the user must not
# grant themselves (hashed_password, is_active, is_superuser, is_verified,
# two_factor_enabled) — a mass assignment here would be a privilege escalation.
EDITABLE_FIELDS = frozenset(
    {"first_name", "last_name", "title", "avatar_url", "phone", "timezone", "status"}
)

VALID_STATUSES = frozenset({"online", "busy", "dnd", "offline"})


class ProfileResponse(BaseModel):
    """The caller's profile as the dashboard header and settings page read it."""

    id: uuid.UUID
    company_id: uuid.UUID
    email: str
    first_name: str
    last_name: str
    title: str
    avatar_url: str | None
    phone: str | None
    timezone: str
    status: str
    two_factor_enabled: bool
    last_login_at: datetime | None
    created_at: datetime
    updated_at: datetime


class ProfileUpdate(BaseModel):
    """Fields a user may change about themselves.

    ``email`` is absent on purpose: it is the login identifier and is unique
    across the platform, so changing it is an account change rather than a
    profile edit. It belongs with the credential routes, behind a password
    confirmation and a verification mail neither of which exists yet.
    """

    first_name: str | None = None
    last_name: str | None = None
    title: str | None = None
    avatar_url: str | None = None
    phone: str | None = None
    timezone: str | None = None
    status: str | None = None


async def _own_profile(db: AsyncSession, user_id: uuid.UUID) -> UserProfile:
    """Load the caller's profile row.

    404 rather than creating one: a principal exists because a session resolved
    against a ``user_profiles`` row, so a missing row means the account was
    deleted mid-session. Inventing a replacement would resurrect it.
    """
    profile = await db.get(UserProfile, user_id)
    if profile is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Profile not found"
        )
    return profile


@router.get("/api/v1/companies/{company_id}/profile", response_model=ProfileResponse)
async def get_profile(
    company_id: PathCompanyId, db: DbSession, principal: RequireUser
) -> Any:
    """Get the signed-in user's profile.

    ``company_id`` is validated against the caller's active company and then
    unused — the profile belongs to the user, not to the tenant. The path keeps
    its shape because the dashboard builds its URLs that way.
    """
    return await _own_profile(db, principal.user_id)


@router.put("/api/v1/companies/{company_id}/profile", response_model=ProfileResponse)
async def update_profile(
    company_id: PathCompanyId,
    body: ProfileUpdate,
    db: DbSession,
    principal: RequireUser,
) -> Any:
    """Update the signed-in user's profile."""
    updates = {
        key: value
        for key, value in body.model_dump(exclude_unset=True).items()
        if key in EDITABLE_FIELDS
    }
    if not updates:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="No fields to update"
        )

    presence = updates.get("status")
    if presence is not None and presence not in VALID_STATUSES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unknown status '{presence}'. Valid: {sorted(VALID_STATUSES)}",
        )

    profile = await _own_profile(db, principal.user_id)
    for key, value in updates.items():
        setattr(profile, key, value)
    profile.updated_at = utcnow()
    db.add(profile)
    await db.flush()
    return profile
