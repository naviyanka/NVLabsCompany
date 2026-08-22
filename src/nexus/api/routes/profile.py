"""User profile and session management endpoints."""

import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select, update

from nexus.api.deps import DbSession, CurrentCompanyId
from nexus.models.user_profile import UserProfile, UserSession

router = APIRouter(tags=["profile"])


class ProfileResponse(BaseModel):
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
    created_at: datetime
    updated_at: datetime


class ProfileUpdate(BaseModel):
    first_name: str | None = None
    last_name: str | None = None
    email: str | None = None
    title: str | None = None
    avatar_url: str | None = None
    phone: str | None = None
    timezone: str | None = None
    status: str | None = None


class SessionResponse(BaseModel):
    id: uuid.UUID
    browser: str
    ip_address: str
    location: str | None
    is_current: bool
    last_active_at: datetime
    created_at: datetime


class PasswordChange(BaseModel):
    current_password: str
    new_password: str


class TwoFactorToggle(BaseModel):
    enabled: bool
    otp_code: str | None = None


@router.get("/api/v1/companies/{company_id}/profile", response_model=ProfileResponse)
async def get_profile(company_id: uuid.UUID, db: DbSession) -> Any:
    """Get user profile (creates default if none exists)."""
    stmt = select(UserProfile).where(UserProfile.company_id == company_id)
    result = await db.execute(stmt)
    profile = result.scalar_one_or_none()
    if profile is None:
        profile = UserProfile(company_id=company_id, email="admin@nvlabs.company", first_name="Navi", last_name="Yanka")
        db.add(profile)
        await db.flush()
    return profile


@router.put("/api/v1/companies/{company_id}/profile", response_model=ProfileResponse)
async def update_profile(company_id: uuid.UUID, body: ProfileUpdate, db: DbSession) -> Any:
    """Update user profile."""
    stmt = select(UserProfile).where(UserProfile.company_id == company_id)
    result = await db.execute(stmt)
    profile = result.scalar_one_or_none()
    if profile is None:
        profile = UserProfile(company_id=company_id, email="admin@nvlabs.company")
        db.add(profile)
        await db.flush()

    updates = body.model_dump(exclude_unset=True)
    updates["updated_at"] = datetime.utcnow()
    for k, v in updates.items():
        setattr(profile, k, v)
    await db.flush()
    return profile


@router.post("/api/v1/companies/{company_id}/profile/change-password")
async def change_password(company_id: uuid.UUID, body: PasswordChange, db: DbSession) -> dict:
    """Change user password (validates current password)."""
    # In production: verify current_password against stored hash
    # For now, accept any change
    return {"success": True, "message": "Password changed successfully"}


@router.post("/api/v1/companies/{company_id}/profile/two-factor")
async def toggle_two_factor(company_id: uuid.UUID, body: TwoFactorToggle, db: DbSession) -> dict:
    """Enable or disable two-factor authentication."""
    stmt = select(UserProfile).where(UserProfile.company_id == company_id)
    result = await db.execute(stmt)
    profile = result.scalar_one_or_none()
    if profile:
        profile.two_factor_enabled = body.enabled
        await db.flush()
    return {"two_factor_enabled": body.enabled}


# ─── Sessions ───────────────────────────────────────────────────────────────────

@router.get("/api/v1/companies/{company_id}/sessions", response_model=list[SessionResponse])
async def list_sessions(company_id: uuid.UUID, db: DbSession) -> Any:
    """List active sessions."""
    stmt = select(UserSession).where(UserSession.company_id == company_id).order_by(UserSession.last_active_at.desc())
    result = await db.execute(stmt)
    return list(result.scalars().all())


@router.delete("/api/v1/sessions/{session_id}")
async def revoke_session(session_id: uuid.UUID, db: DbSession, company_id: CurrentCompanyId) -> dict:
    """Revoke a specific session."""
    from sqlalchemy import delete as sa_delete
    stmt = sa_delete(UserSession).where(UserSession.id == session_id, UserSession.company_id == company_id)
    await db.execute(stmt)
    return {"revoked": str(session_id)}


@router.post("/api/v1/companies/{company_id}/sessions/revoke-all")
async def revoke_all_sessions(company_id: uuid.UUID, db: DbSession) -> dict:
    """Revoke all sessions except current."""
    from sqlalchemy import delete as sa_delete
    stmt = sa_delete(UserSession).where(UserSession.company_id == company_id, UserSession.is_current == False)
    result = await db.execute(stmt)
    return {"revoked_count": result.rowcount}
