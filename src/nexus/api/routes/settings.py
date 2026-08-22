"""Company settings and user preferences endpoints."""

import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel
from sqlalchemy import select

from nexus.api.deps import DbSession
from nexus.models.settings import CompanySettings

router = APIRouter(tags=["settings"])


class CompanySettingsResponse(BaseModel):
    id: uuid.UUID
    company_id: uuid.UUID
    workspace_name: str
    workspace_description: str | None
    default_language: str
    timezone: str
    default_model: str
    default_adapter: str
    default_budget_cents: int
    max_retries: int
    heartbeat_interval_seconds: int
    auto_pause_idle: bool
    evolution_enabled: bool
    rate_limit_per_minute: int
    circuit_breaker_threshold: int
    require_approval_high_risk: bool
    audit_logging_enabled: bool
    auto_assign_tasks: bool
    daily_standup_enabled: bool
    standup_time: str
    sprint_duration_days: int
    updated_at: datetime


class CompanySettingsUpdate(BaseModel):
    workspace_name: str | None = None
    workspace_description: str | None = None
    default_language: str | None = None
    timezone: str | None = None
    default_model: str | None = None
    default_adapter: str | None = None
    default_budget_cents: int | None = None
    max_retries: int | None = None
    heartbeat_interval_seconds: int | None = None
    auto_pause_idle: bool | None = None
    evolution_enabled: bool | None = None
    rate_limit_per_minute: int | None = None
    circuit_breaker_threshold: int | None = None
    require_approval_high_risk: bool | None = None
    audit_logging_enabled: bool | None = None
    auto_assign_tasks: bool | None = None
    daily_standup_enabled: bool | None = None
    standup_time: str | None = None
    sprint_duration_days: int | None = None


@router.get("/api/v1/companies/{company_id}/settings", response_model=CompanySettingsResponse)
async def get_company_settings(company_id: uuid.UUID, db: DbSession) -> Any:
    """Get company settings (creates defaults if none exist)."""
    stmt = select(CompanySettings).where(CompanySettings.company_id == company_id)
    result = await db.execute(stmt)
    settings = result.scalar_one_or_none()
    if settings is None:
        settings = CompanySettings(company_id=company_id)
        db.add(settings)
        await db.flush()
    return settings


@router.put("/api/v1/companies/{company_id}/settings", response_model=CompanySettingsResponse)
async def update_company_settings(company_id: uuid.UUID, body: CompanySettingsUpdate, db: DbSession) -> Any:
    """Update company settings."""
    stmt = select(CompanySettings).where(CompanySettings.company_id == company_id)
    result = await db.execute(stmt)
    settings = result.scalar_one_or_none()
    if settings is None:
        settings = CompanySettings(company_id=company_id)
        db.add(settings)
        await db.flush()

    updates = body.model_dump(exclude_unset=True)
    updates["updated_at"] = datetime.utcnow()
    for key, val in updates.items():
        setattr(settings, key, val)
    await db.flush()
    return settings
