"""Meeting models for structured agent collaboration sessions."""

import uuid
from datetime import timezone, datetime
from typing import Any, Optional

from sqlalchemy import JSON
from sqlmodel import Column, Field, SQLModel


class Meeting(SQLModel, table=True):
    """A structured collaboration session between agents.

    Meetings support various types (standup, planning, retrospective,
    design_review, priority_alignment) and can be triggered by schedules
    or events via an optional trigger link.
    """

    __tablename__ = "meetings"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    company_id: uuid.UUID = Field(foreign_key="companies.id", index=True)
    meeting_type: str = Field(max_length=50)  # standup/planning/retrospective/design_review/priority_alignment
    title: str = Field(max_length=500)
    status: str = Field(default="scheduled", max_length=50)  # scheduled/in_progress/completed/cancelled
    scheduled_at: Optional[datetime] = Field(default=None)
    started_at: Optional[datetime] = Field(default=None)
    completed_at: Optional[datetime] = Field(default=None)
    recurrence_rule: Optional[str] = Field(default=None, max_length=255)
    trigger_id: Optional[uuid.UUID] = Field(
        default=None, foreign_key="triggers.id"
    )
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class MeetingParticipant(SQLModel, table=True):
    """A participant in a meeting with a designated role.

    Roles include required, optional, and facilitator. Tracks whether the
    agent actually attended the meeting.
    """

    __tablename__ = "meeting_participants"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    meeting_id: uuid.UUID = Field(foreign_key="meetings.id", index=True)
    agent_id: uuid.UUID = Field(foreign_key="agents.id", index=True)
    role: str = Field(default="required", max_length=50)  # required/optional/facilitator
    attended: bool = Field(default=False)


class MeetingMinutes(SQLModel, table=True):
    """Summary and decisions from a completed meeting.

    Minutes capture the high-level summary and structured decisions made
    during the meeting session.
    """

    __tablename__ = "meeting_minutes"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    meeting_id: uuid.UUID = Field(foreign_key="meetings.id", index=True)
    company_id: uuid.UUID = Field(foreign_key="companies.id", index=True)
    summary: str
    decisions: Optional[dict[str, Any]] = Field(default=None, sa_column=Column(JSON))
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class ActionItem(SQLModel, table=True):
    """An action item assigned to an agent from a meeting.

    Tracks tasks that emerge from meetings with assignment, status tracking,
    and optional due dates.
    """

    __tablename__ = "action_items"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    meeting_id: uuid.UUID = Field(foreign_key="meetings.id", index=True)
    company_id: uuid.UUID = Field(foreign_key="companies.id", index=True)
    assigned_agent_id: uuid.UUID = Field(foreign_key="agents.id", index=True)
    description: str
    status: str = Field(default="pending", max_length=50)  # pending/in_progress/done
    due_at: Optional[datetime] = Field(default=None)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
