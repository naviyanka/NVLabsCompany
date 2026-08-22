"""Incident management API endpoints."""

import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select, update

from nexus.api.deps import CurrentCompanyId, DbSession, require_permission
from nexus.models.incident import Incident, IncidentAction, IncidentEvent

router = APIRouter(tags=["incidents"])


# --- Request/Response Models ---


class IncidentCreate(BaseModel):
    """Request body for creating an incident."""

    title: str
    severity: str = "medium"


class IncidentResolve(BaseModel):
    """Request body for resolving an incident."""

    rca: str | None = None


class IncidentResponse(BaseModel):
    """Response model for an incident."""

    id: uuid.UUID
    company_id: uuid.UUID
    title: str
    severity: str
    status: str
    created_at: datetime
    resolved_at: datetime | None = None
    rca: str | None = None


class IncidentEventResponse(BaseModel):
    """Response model for an incident timeline event."""

    id: uuid.UUID
    incident_id: uuid.UUID
    event_type: str
    description: str | None = None
    timestamp: datetime
    actor: str | None = None


class IncidentActionResponse(BaseModel):
    """Response model for an incident action."""

    id: uuid.UUID
    incident_id: uuid.UUID
    action_type: str
    target: str | None = None
    executed_at: datetime
    result: str | None = None


class TimelineResponse(BaseModel):
    """Combined timeline response with events and actions."""

    events: list[IncidentEventResponse]
    actions: list[IncidentActionResponse]


# --- Routes ---


@router.post(
    "/api/v1/incidents",
    status_code=status.HTTP_201_CREATED,
    response_model=IncidentResponse,
    dependencies=[require_permission("write", "incident")],
)
async def create_incident(
    body: IncidentCreate,
    db: DbSession,
    company_id: CurrentCompanyId,
) -> Any:
    """Create a new incident."""
    incident = Incident(
        company_id=company_id,
        title=body.title,
        severity=body.severity,
    )
    db.add(incident)
    await db.flush()

    # Record the creation event
    event = IncidentEvent(
        incident_id=incident.id,
        event_type="created",
        description=f"Incident created: {body.title}",
        actor="system",
    )
    db.add(event)
    await db.flush()

    return incident


@router.get(
    "/api/v1/incidents",
    response_model=list[IncidentResponse],
)
async def list_incidents(
    db: DbSession,
    company_id: CurrentCompanyId,
    status_filter: str | None = None,
    severity: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> Any:
    """List incidents for the current company."""
    stmt = select(Incident).where(Incident.company_id == company_id)
    if status_filter:
        stmt = stmt.where(Incident.status == status_filter)
    if severity:
        stmt = stmt.where(Incident.severity == severity)
    stmt = stmt.order_by(Incident.created_at.desc()).offset(offset).limit(limit)
    result = await db.execute(stmt)
    return list(result.scalars().all())


@router.put(
    "/api/v1/incidents/{incident_id}/resolve",
    response_model=IncidentResponse,
    dependencies=[require_permission("write", "incident")],
)
async def resolve_incident(
    incident_id: uuid.UUID,
    body: IncidentResolve,
    db: DbSession,
    company_id: CurrentCompanyId,
) -> Any:
    """Resolve an open incident."""
    now = datetime.utcnow()
    stmt = (
        update(Incident)
        .where(
            Incident.id == incident_id,
            Incident.company_id == company_id,
            Incident.status != "resolved",
        )
        .values(
            status="resolved",
            resolved_at=now,
            rca=body.rca,
        )
    )
    result = await db.execute(stmt)
    if result.rowcount == 0:  # type: ignore[union-attr]
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Incident {incident_id} not found or already resolved",
        )

    # Record resolution event
    event = IncidentEvent(
        incident_id=incident_id,
        event_type="resolved",
        description="Incident resolved",
        actor="system",
    )
    db.add(event)
    await db.flush()

    query = await db.execute(select(Incident).where(Incident.id == incident_id))
    return query.scalar_one()


@router.get(
    "/api/v1/incidents/{incident_id}/timeline",
    response_model=TimelineResponse,
)
async def get_incident_timeline(
    incident_id: uuid.UUID,
    db: DbSession,
    company_id: CurrentCompanyId,
) -> Any:
    """Get the full timeline of events and actions for an incident."""
    # Verify incident exists and belongs to company
    stmt = select(Incident).where(
        Incident.id == incident_id, Incident.company_id == company_id
    )
    result = await db.execute(stmt)
    incident = result.scalar_one_or_none()

    if not incident:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Incident {incident_id} not found",
        )

    # Fetch events
    events_stmt = (
        select(IncidentEvent)
        .where(IncidentEvent.incident_id == incident_id)
        .order_by(IncidentEvent.timestamp.asc())
    )
    events_result = await db.execute(events_stmt)
    events = list(events_result.scalars().all())

    # Fetch actions
    actions_stmt = (
        select(IncidentAction)
        .where(IncidentAction.incident_id == incident_id)
        .order_by(IncidentAction.executed_at.asc())
    )
    actions_result = await db.execute(actions_stmt)
    actions = list(actions_result.scalars().all())

    return TimelineResponse(events=events, actions=actions)
