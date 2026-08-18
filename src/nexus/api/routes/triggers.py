"""Trigger API endpoints - proactive agent activation and scheduling."""

import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select, update

from nexus.api.deps import DbSession
from nexus.models.trigger import Trigger, TriggerExecution

router = APIRouter(tags=["triggers"])


class TriggerCreate(BaseModel):
    """Request body for creating a trigger."""

    agent_id: uuid.UUID
    trigger_type: str
    name: str
    description: str | None = None
    config: dict[str, Any] | None = None
    is_active: bool = True
    next_fire_at: datetime | None = None


class TriggerUpdate(BaseModel):
    """Request body for updating a trigger."""

    name: str | None = None
    description: str | None = None
    config: dict[str, Any] | None = None
    is_active: bool | None = None
    next_fire_at: datetime | None = None


class TriggerResponse(BaseModel):
    """Response model for a trigger."""

    id: uuid.UUID
    company_id: uuid.UUID
    agent_id: uuid.UUID
    trigger_type: str
    name: str
    description: str | None = None
    config: dict[str, Any] | None = None
    is_active: bool
    last_fired_at: datetime | None = None
    next_fire_at: datetime | None = None
    created_at: datetime


class TriggerExecutionResponse(BaseModel):
    """Response model for a trigger execution."""

    id: uuid.UUID
    trigger_id: uuid.UUID
    company_id: uuid.UUID
    status: str
    result: dict[str, Any] | None = None
    error: str | None = None
    started_at: datetime
    completed_at: datetime | None = None


@router.post(
    "/api/v1/companies/{company_id}/triggers",
    status_code=status.HTTP_201_CREATED,
    response_model=TriggerResponse,
)
async def create_trigger(
    company_id: uuid.UUID, body: TriggerCreate, db: DbSession
) -> Any:
    """Create a new trigger for an agent."""
    trigger = Trigger(
        company_id=company_id,
        agent_id=body.agent_id,
        trigger_type=body.trigger_type,
        name=body.name,
        description=body.description,
        config=body.config,
        is_active=body.is_active,
        next_fire_at=body.next_fire_at,
    )
    db.add(trigger)
    await db.flush()
    return trigger


@router.get(
    "/api/v1/companies/{company_id}/triggers",
    response_model=list[TriggerResponse],
)
async def list_triggers(
    company_id: uuid.UUID,
    db: DbSession,
    is_active: bool | None = None,
    limit: int = 100,
    offset: int = 0,
) -> Any:
    """List triggers for a company."""
    stmt = select(Trigger).where(Trigger.company_id == company_id)
    if is_active is not None:
        stmt = stmt.where(Trigger.is_active == is_active)
    stmt = stmt.offset(offset).limit(limit).order_by(Trigger.created_at.desc())
    result = await db.execute(stmt)
    return list(result.scalars().all())


@router.put("/api/v1/triggers/{trigger_id}", response_model=TriggerResponse)
async def update_trigger(
    trigger_id: uuid.UUID, body: TriggerUpdate, db: DbSession
) -> Any:
    """Update a trigger."""
    updates = body.model_dump(exclude_unset=True)
    if not updates:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No fields to update",
        )
    stmt = update(Trigger).where(Trigger.id == trigger_id).values(**updates)
    await db.execute(stmt)

    result = await db.execute(select(Trigger).where(Trigger.id == trigger_id))
    trigger = result.scalar_one_or_none()
    if trigger is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Trigger {trigger_id} not found",
        )
    return trigger


@router.post(
    "/api/v1/triggers/{trigger_id}/fire",
    status_code=status.HTTP_201_CREATED,
    response_model=TriggerExecutionResponse,
)
async def fire_trigger(trigger_id: uuid.UUID, db: DbSession) -> Any:
    """Manually fire a trigger, creating an execution record."""
    # Verify trigger exists
    stmt = select(Trigger).where(Trigger.id == trigger_id)
    result = await db.execute(stmt)
    trigger = result.scalar_one_or_none()
    if trigger is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Trigger {trigger_id} not found",
        )

    now = datetime.now(timezone.utc)

    # Update trigger last_fired_at
    update_stmt = (
        update(Trigger)
        .where(Trigger.id == trigger_id)
        .values(last_fired_at=now)
    )
    await db.execute(update_stmt)

    # Create execution record
    execution = TriggerExecution(
        trigger_id=trigger_id,
        company_id=trigger.company_id,
        status="running",
        started_at=now,
    )
    db.add(execution)
    await db.flush()
    return execution
