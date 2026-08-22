"""Notification API endpoints — CRUD, mark-read, preferences."""

import uuid
from datetime import datetime
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select, update, delete, func

from nexus.api.deps import CurrentCompanyId, DbSession
from nexus.models.notification import Notification, NotificationPreference

router = APIRouter(tags=["notifications"])


# ─── Request/Response Models ────────────────────────────────────────────────────

class NotificationCreate(BaseModel):
    title: str
    description: str | None = None
    notification_type: str = "info"
    module: str = "system"
    priority: str = "low"
    agent_id: uuid.UUID | None = None
    metadata: dict[str, Any] | None = None


class NotificationResponse(BaseModel):
    id: uuid.UUID
    company_id: uuid.UUID
    title: str
    description: str | None = None
    notification_type: str
    module: str
    priority: str
    read: bool
    dismissed: bool
    agent_id: uuid.UUID | None = None
    metadata: dict[str, Any] | None = None
    created_at: datetime


class NotificationPreferenceResponse(BaseModel):
    id: uuid.UUID
    company_id: uuid.UUID
    email_enabled: bool
    push_enabled: bool
    slack_enabled: bool
    quiet_hours_enabled: bool
    quiet_start: str
    quiet_end: str
    agent_completions: bool
    pipeline_failures: bool
    security_alerts: bool
    system_updates: bool
    mentions: bool
    updated_at: datetime


class NotificationPreferenceUpdate(BaseModel):
    email_enabled: bool | None = None
    push_enabled: bool | None = None
    slack_enabled: bool | None = None
    quiet_hours_enabled: bool | None = None
    quiet_start: str | None = None
    quiet_end: str | None = None
    agent_completions: bool | None = None
    pipeline_failures: bool | None = None
    security_alerts: bool | None = None
    system_updates: bool | None = None
    mentions: bool | None = None


# ─── Endpoints ──────────────────────────────────────────────────────────────────

@router.get("/api/v1/companies/{company_id}/notifications", response_model=list[NotificationResponse])
async def list_notifications(
    company_id: uuid.UUID,
    db: DbSession,
    module: str | None = None,
    priority: str | None = None,
    read: bool | None = None,
    limit: int = 50,
    offset: int = 0,
) -> Any:
    """List notifications for a company with optional filters."""
    stmt = select(Notification).where(
        Notification.company_id == company_id,
        Notification.dismissed == False,
    )
    if module:
        stmt = stmt.where(Notification.module == module)
    if priority:
        stmt = stmt.where(Notification.priority == priority)
    if read is not None:
        stmt = stmt.where(Notification.read == read)
    stmt = stmt.offset(offset).limit(limit).order_by(Notification.created_at.desc())
    result = await db.execute(stmt)
    return list(result.scalars().all())


@router.post("/api/v1/companies/{company_id}/notifications", status_code=status.HTTP_201_CREATED, response_model=NotificationResponse)
async def create_notification(company_id: uuid.UUID, body: NotificationCreate, db: DbSession) -> Any:
    """Create a new notification."""
    notif = Notification(
        company_id=company_id,
        title=body.title,
        description=body.description,
        notification_type=body.notification_type,
        module=body.module,
        priority=body.priority,
        agent_id=body.agent_id,
        notification_metadata=body.metadata,
    )
    db.add(notif)
    await db.flush()
    return notif


@router.post("/api/v1/notifications/{notification_id}/read")
async def mark_notification_read(notification_id: uuid.UUID, db: DbSession, company_id: CurrentCompanyId) -> dict:
    """Mark a single notification as read."""
    stmt = update(Notification).where(
        Notification.id == notification_id,
        Notification.company_id == company_id,
    ).values(read=True)
    result = await db.execute(stmt)
    if result.rowcount == 0:
        raise HTTPException(status_code=404, detail="Notification not found")
    return {"id": str(notification_id), "read": True}


@router.post("/api/v1/companies/{company_id}/notifications/read-all")
async def mark_all_notifications_read(company_id: uuid.UUID, db: DbSession) -> dict:
    """Mark all notifications as read for a company."""
    stmt = update(Notification).where(
        Notification.company_id == company_id,
        Notification.read == False,
    ).values(read=True)
    result = await db.execute(stmt)
    return {"marked_read": result.rowcount}


@router.delete("/api/v1/notifications/{notification_id}", status_code=status.HTTP_204_NO_CONTENT)
async def dismiss_notification(notification_id: uuid.UUID, db: DbSession, company_id: CurrentCompanyId) -> None:
    """Dismiss (soft-delete) a notification."""
    stmt = update(Notification).where(
        Notification.id == notification_id,
        Notification.company_id == company_id,
    ).values(dismissed=True)
    await db.execute(stmt)


@router.get("/api/v1/companies/{company_id}/notifications/count")
async def get_notification_counts(company_id: uuid.UUID, db: DbSession) -> dict:
    """Get notification counts by category."""
    total = await db.execute(select(func.count(Notification.id)).where(Notification.company_id == company_id, Notification.dismissed == False))
    unread = await db.execute(select(func.count(Notification.id)).where(Notification.company_id == company_id, Notification.read == False, Notification.dismissed == False))
    return {"total": total.scalar() or 0, "unread": unread.scalar() or 0}


# ─── Preferences ────────────────────────────────────────────────────────────────

@router.get("/api/v1/companies/{company_id}/notifications/preferences", response_model=NotificationPreferenceResponse)
async def get_notification_preferences(company_id: uuid.UUID, db: DbSession) -> Any:
    """Get notification preferences (creates default if none exist)."""
    stmt = select(NotificationPreference).where(NotificationPreference.company_id == company_id)
    result = await db.execute(stmt)
    pref = result.scalar_one_or_none()
    if pref is None:
        pref = NotificationPreference(company_id=company_id)
        db.add(pref)
        await db.flush()
    return pref


@router.put("/api/v1/companies/{company_id}/notifications/preferences", response_model=NotificationPreferenceResponse)
async def update_notification_preferences(company_id: uuid.UUID, body: NotificationPreferenceUpdate, db: DbSession) -> Any:
    """Update notification preferences."""
    stmt = select(NotificationPreference).where(NotificationPreference.company_id == company_id)
    result = await db.execute(stmt)
    pref = result.scalar_one_or_none()
    if pref is None:
        pref = NotificationPreference(company_id=company_id)
        db.add(pref)
        await db.flush()

    updates = body.model_dump(exclude_unset=True)
    updates["updated_at"] = datetime.utcnow()
    for key, val in updates.items():
        setattr(pref, key, val)
    await db.flush()
    return pref
