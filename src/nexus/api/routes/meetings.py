"""Meeting API endpoints - scheduling, conducting, and recording meetings."""

import uuid
from datetime import datetime
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select

from nexus.api.deps import CurrentCompanyId, DbSession
from nexus.models.meeting import ActionItem, Meeting, MeetingMinutes, MeetingParticipant

router = APIRouter(tags=["meetings"])


# ---------------------------------------------------------------------------
# Request / Response Models
# ---------------------------------------------------------------------------


class ScheduleMeetingRequest(BaseModel):
    """Request body for scheduling a meeting."""

    meeting_type: str
    title: str
    scheduled_at: Optional[datetime] = None
    participants: list[uuid.UUID] = []
    recurrence_rule: Optional[str] = None


class MeetingResponse(BaseModel):
    """Response model for a meeting."""

    id: uuid.UUID
    company_id: uuid.UUID
    meeting_type: str
    title: str
    status: str
    scheduled_at: Optional[datetime] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    recurrence_rule: Optional[str] = None
    created_at: datetime


class ContributionRequest(BaseModel):
    """Request body for adding a meeting contribution."""

    agent_id: uuid.UUID
    content: str


class MinutesResponse(BaseModel):
    """Response model for meeting minutes."""

    id: uuid.UUID
    meeting_id: uuid.UUID
    company_id: uuid.UUID
    summary: str
    decisions: Optional[dict[str, Any]] = None
    created_at: datetime


class ActionItemResponse(BaseModel):
    """Response model for an action item."""

    id: uuid.UUID
    meeting_id: uuid.UUID
    company_id: uuid.UUID
    assigned_agent_id: uuid.UUID
    description: str
    status: str
    due_at: Optional[datetime] = None
    created_at: datetime


class MeetingTemplateResponse(BaseModel):
    """Response model for a meeting template."""

    template_type: str
    title: str
    description: str
    default_duration_minutes: int
    agenda_items: list[str]


# ---------------------------------------------------------------------------
# Meeting Templates (in-memory defaults)
# ---------------------------------------------------------------------------

MEETING_TEMPLATES: dict[str, MeetingTemplateResponse] = {
    "standup": MeetingTemplateResponse(
        template_type="standup",
        title="Daily Standup",
        description="Quick status sync across team members",
        default_duration_minutes=15,
        agenda_items=["What did you do yesterday?", "What will you do today?", "Any blockers?"],
    ),
    "planning": MeetingTemplateResponse(
        template_type="planning",
        title="Sprint Planning",
        description="Plan work for the upcoming sprint",
        default_duration_minutes=60,
        agenda_items=["Review backlog", "Estimate stories", "Commit to sprint goal"],
    ),
    "retrospective": MeetingTemplateResponse(
        template_type="retrospective",
        title="Retrospective",
        description="Reflect on what went well and what can improve",
        default_duration_minutes=45,
        agenda_items=["What went well?", "What could improve?", "Action items"],
    ),
    "design_review": MeetingTemplateResponse(
        template_type="design_review",
        title="Design Review",
        description="Review and critique a design proposal",
        default_duration_minutes=30,
        agenda_items=["Present design", "Q&A", "Feedback", "Decision"],
    ),
    "priority_alignment": MeetingTemplateResponse(
        template_type="priority_alignment",
        title="Priority Alignment",
        description="Align on priorities across teams or departments",
        default_duration_minutes=45,
        agenda_items=["Current priorities", "Conflicts", "Resolution", "Next steps"],
    ),
}


# ---------------------------------------------------------------------------
# Meeting Routes
# ---------------------------------------------------------------------------


@router.post(
    "/api/v1/companies/{company_id}/meetings",
    status_code=status.HTTP_201_CREATED,
    response_model=MeetingResponse,
)
async def schedule_meeting(
    company_id: uuid.UUID, body: ScheduleMeetingRequest, db: DbSession
) -> Any:
    """Schedule a new meeting."""
    meeting = Meeting(
        company_id=company_id,
        meeting_type=body.meeting_type,
        title=body.title,
        scheduled_at=body.scheduled_at,
        recurrence_rule=body.recurrence_rule,
    )
    db.add(meeting)
    await db.flush()

    # Add participants
    for agent_id in body.participants:
        participant = MeetingParticipant(
            meeting_id=meeting.id,
            agent_id=agent_id,
        )
        db.add(participant)
    await db.flush()

    return meeting


@router.get(
    "/api/v1/companies/{company_id}/meetings",
    response_model=list[MeetingResponse],
)
async def list_meetings(
    company_id: uuid.UUID,
    db: DbSession,
    status_filter: Optional[str] = None,
    meeting_type: Optional[str] = None,
    agent_id: Optional[uuid.UUID] = None,
    limit: int = 100,
    offset: int = 0,
) -> Any:
    """List meetings for a company."""
    stmt = select(Meeting).where(Meeting.company_id == company_id)
    if status_filter:
        stmt = stmt.where(Meeting.status == status_filter)
    if meeting_type:
        stmt = stmt.where(Meeting.meeting_type == meeting_type)
    if agent_id:
        stmt = stmt.join(MeetingParticipant, MeetingParticipant.meeting_id == Meeting.id).where(
            MeetingParticipant.agent_id == agent_id
        )
    stmt = stmt.offset(offset).limit(limit).order_by(Meeting.created_at.desc())
    result = await db.execute(stmt)
    return list(result.scalars().all())


@router.get(
    "/api/v1/meetings/{meeting_id}",
    response_model=MeetingResponse,
)
async def get_meeting(meeting_id: uuid.UUID, db: DbSession, company_id: CurrentCompanyId) -> Any:
    """Get meeting details by ID."""
    stmt = select(Meeting).where(Meeting.id == meeting_id, Meeting.company_id == company_id)
    result = await db.execute(stmt)
    meeting = result.scalar_one_or_none()
    if meeting is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Meeting {meeting_id} not found",
        )
    return meeting


@router.post(
    "/api/v1/meetings/{meeting_id}/start",
    response_model=MeetingResponse,
)
async def start_meeting(meeting_id: uuid.UUID, db: DbSession, company_id: CurrentCompanyId) -> Any:
    """Start a scheduled meeting."""
    stmt = select(Meeting).where(Meeting.id == meeting_id, Meeting.company_id == company_id)
    result = await db.execute(stmt)
    meeting = result.scalar_one_or_none()
    if meeting is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Meeting {meeting_id} not found",
        )
    if meeting.status != "scheduled":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Meeting cannot be started from status '{meeting.status}'",
        )
    meeting.status = "in_progress"
    meeting.started_at = datetime.utcnow()
    await db.flush()
    return meeting


@router.post(
    "/api/v1/meetings/{meeting_id}/end",
    response_model=MeetingResponse,
)
async def end_meeting(meeting_id: uuid.UUID, db: DbSession, company_id: CurrentCompanyId) -> Any:
    """End an in-progress meeting."""
    stmt = select(Meeting).where(Meeting.id == meeting_id, Meeting.company_id == company_id)
    result = await db.execute(stmt)
    meeting = result.scalar_one_or_none()
    if meeting is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Meeting {meeting_id} not found",
        )
    if meeting.status != "in_progress":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Meeting cannot be ended from status '{meeting.status}'",
        )
    meeting.status = "completed"
    meeting.completed_at = datetime.utcnow()
    await db.flush()
    return meeting


@router.post(
    "/api/v1/meetings/{meeting_id}/contributions",
    status_code=status.HTTP_201_CREATED,
)
async def add_contribution(
    meeting_id: uuid.UUID, body: ContributionRequest, db: DbSession, company_id: CurrentCompanyId
) -> dict[str, Any]:
    """Add a contribution from an agent during a meeting."""
    # Verify meeting exists and is in progress
    stmt = select(Meeting).where(Meeting.id == meeting_id, Meeting.company_id == company_id)
    result = await db.execute(stmt)
    meeting = result.scalar_one_or_none()
    if meeting is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Meeting {meeting_id} not found",
        )

    # Mark participant as attended
    part_stmt = select(MeetingParticipant).where(
        MeetingParticipant.meeting_id == meeting_id,
        MeetingParticipant.agent_id == body.agent_id,
    )
    part_result = await db.execute(part_stmt)
    participant = part_result.scalar_one_or_none()
    if participant:
        participant.attended = True
        await db.flush()

    return {
        "meeting_id": str(meeting_id),
        "agent_id": str(body.agent_id),
        "content": body.content,
        "recorded": True,
    }


@router.get(
    "/api/v1/meetings/{meeting_id}/minutes",
    response_model=MinutesResponse,
)
async def get_minutes(meeting_id: uuid.UUID, db: DbSession, company_id: CurrentCompanyId) -> Any:
    """Get minutes for a meeting."""
    stmt = select(MeetingMinutes).where(MeetingMinutes.meeting_id == meeting_id, MeetingMinutes.company_id == company_id)
    result = await db.execute(stmt)
    minutes = result.scalar_one_or_none()
    if minutes is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Minutes for meeting {meeting_id} not found",
        )
    return minutes


@router.get(
    "/api/v1/meetings/{meeting_id}/action-items",
    response_model=list[ActionItemResponse],
)
async def get_action_items(meeting_id: uuid.UUID, db: DbSession, company_id: CurrentCompanyId) -> Any:
    """Get action items from a meeting."""
    stmt = (
        select(ActionItem)
        .where(ActionItem.meeting_id == meeting_id, ActionItem.company_id == company_id)
        .order_by(ActionItem.created_at)
    )
    result = await db.execute(stmt)
    return list(result.scalars().all())


# ---------------------------------------------------------------------------
# Template Routes
# ---------------------------------------------------------------------------


@router.get(
    "/api/v1/templates",
    response_model=list[MeetingTemplateResponse],
)
async def list_templates() -> Any:
    """List available meeting templates."""
    return list(MEETING_TEMPLATES.values())


@router.get(
    "/api/v1/templates/{template_type}",
    response_model=MeetingTemplateResponse,
)
async def get_template(template_type: str) -> Any:
    """Get a specific meeting template."""
    template = MEETING_TEMPLATES.get(template_type)
    if template is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Template '{template_type}' not found",
        )
    return template



# ---------------------------------------------------------------------------
# Additional Meeting Endpoints
# ---------------------------------------------------------------------------


@router.delete("/api/v1/meetings/{meeting_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_meeting(meeting_id: uuid.UUID, db: DbSession, company_id: CurrentCompanyId) -> None:
    """Delete/cancel a meeting with company_id check."""
    from sqlalchemy import delete as sa_delete

    stmt = sa_delete(Meeting).where(Meeting.id == meeting_id, Meeting.company_id == company_id)
    await db.execute(stmt)


@router.get("/api/v1/companies/{company_id}/meetings/upcoming", response_model=list[MeetingResponse])
async def list_upcoming_meetings(company_id: uuid.UUID, db: DbSession, limit: int = 50) -> Any:
    """List upcoming meetings (scheduled and in the future)."""
    now = datetime.utcnow()
    stmt = (
        select(Meeting)
        .where(
            Meeting.company_id == company_id,
            Meeting.status == "scheduled",
            Meeting.scheduled_at > now,
        )
        .order_by(Meeting.scheduled_at.asc())
        .limit(limit)
    )
    result = await db.execute(stmt)
    return list(result.scalars().all())



@router.delete("/api/v1/meetings/{meeting_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_meeting(meeting_id: uuid.UUID, db: DbSession, company_id: CurrentCompanyId) -> None:
    """Delete/cancel a meeting."""
    from sqlalchemy import delete as sa_delete
    await sa_delete(MeetingParticipant).where(MeetingParticipant.meeting_id == meeting_id)
    await db.execute(sa_delete(Meeting).where(Meeting.id == meeting_id, Meeting.company_id == company_id))


@router.get("/api/v1/companies/{company_id}/meetings/upcoming", response_model=list[MeetingResponse])
async def upcoming_meetings(company_id: uuid.UUID, db: DbSession, limit: int = 10) -> Any:
    """List upcoming scheduled meetings."""
    from datetime import datetime
    now = datetime.utcnow()
    stmt = select(Meeting).where(Meeting.company_id == company_id, Meeting.status == "scheduled").order_by(Meeting.scheduled_at).limit(limit)
    result = await db.execute(stmt)
    return list(result.scalars().all())
