"""Meeting scheduler for creating and managing scheduled meetings.

Handles the lifecycle of meeting scheduling including creation, cancellation,
rescheduling, and querying upcoming meetings.
"""

import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from nexus.models.meeting import Meeting, MeetingParticipant


class MeetingScheduler:
    """Schedules and manages meetings between agents.

    Provides methods to create meetings with participants, cancel or reschedule
    them, and query upcoming meetings filtered by company or agent.

    Integration with the trigger system: For recurring meetings (those with a
    recurrence_rule), the scheduler stores the rule on the Meeting record. A
    separate trigger should be created via the trigger system to fire at the
    appropriate interval and invoke schedule_meeting again for the next
    occurrence. This decouples scheduling from execution and allows the trigger
    system to handle timing, retries, and deactivation independently.
    """

    def __init__(self, db: AsyncSession) -> None:
        """Initialize the scheduler with a database session.

        Args:
            db: An async SQLAlchemy session for persistence operations.
        """
        self.db = db

    async def schedule_meeting(
        self,
        company_id: uuid.UUID,
        meeting_type: str,
        title: str,
        scheduled_at: datetime,
        participants: list[dict],
        recurrence_rule: Optional[str] = None,
    ) -> Meeting:
        """Schedule a new meeting with participants.

        Creates a Meeting record and associated MeetingParticipant records.
        For recurring meetings, stores the recurrence_rule on the meeting.
        Integration with the trigger system should create a corresponding
        Trigger record to handle automatic scheduling of future occurrences.

        Args:
            company_id: The company this meeting belongs to.
            meeting_type: Type of meeting (standup, planning, retrospective,
                design_review, priority_alignment).
            title: Human-readable title for the meeting.
            scheduled_at: When the meeting is scheduled to occur.
            participants: List of dicts with 'agent_id' (UUID) and 'role'
                ('required', 'optional', or 'facilitator').
            recurrence_rule: Optional recurrence pattern - one of 'daily',
                'weekly', 'biweekly', 'monthly', or None for one-off meetings.

        Returns:
            The created Meeting record.
        """
        meeting = Meeting(
            company_id=company_id,
            meeting_type=meeting_type,
            title=title,
            status="scheduled",
            scheduled_at=scheduled_at,
            recurrence_rule=recurrence_rule,
        )
        self.db.add(meeting)
        await self.db.flush()

        for participant in participants:
            meeting_participant = MeetingParticipant(
                meeting_id=meeting.id,
                agent_id=participant["agent_id"],
                role=participant.get("role", "required"),
            )
            self.db.add(meeting_participant)

        await self.db.commit()
        await self.db.refresh(meeting)
        return meeting

    async def cancel_meeting(self, meeting_id: uuid.UUID) -> Meeting:
        """Cancel a scheduled meeting.

        Sets the meeting status to 'cancelled'. Does not delete the record
        to preserve audit history.

        Args:
            meeting_id: The ID of the meeting to cancel.

        Returns:
            The updated Meeting record.

        Raises:
            ValueError: If the meeting is not found.
        """
        statement = select(Meeting).where(Meeting.id == meeting_id)
        result = await self.db.execute(statement)
        meeting = result.scalar_one_or_none()

        if meeting is None:
            raise ValueError(f"Meeting {meeting_id} not found")

        meeting.status = "cancelled"
        self.db.add(meeting)
        await self.db.commit()
        await self.db.refresh(meeting)
        return meeting

    async def get_upcoming_meetings(
        self,
        company_id: uuid.UUID,
        agent_id: Optional[uuid.UUID] = None,
        limit: int = 10,
    ) -> list[Meeting]:
        """Get upcoming scheduled meetings for a company or specific agent.

        Returns meetings with status 'scheduled' ordered by scheduled_at,
        optionally filtered by agent participation.

        Args:
            company_id: The company to query meetings for.
            agent_id: Optional agent ID to filter meetings where this agent
                is a participant.
            limit: Maximum number of meetings to return (default 10).

        Returns:
            List of upcoming Meeting records ordered by scheduled time.
        """
        now = datetime.now(timezone.utc)

        if agent_id is not None:
            statement = (
                select(Meeting)
                .join(MeetingParticipant, Meeting.id == MeetingParticipant.meeting_id)
                .where(
                    Meeting.company_id == company_id,
                    Meeting.status == "scheduled",
                    Meeting.scheduled_at >= now,
                    MeetingParticipant.agent_id == agent_id,
                )
                .order_by(Meeting.scheduled_at)
                .limit(limit)
            )
        else:
            statement = (
                select(Meeting)
                .where(
                    Meeting.company_id == company_id,
                    Meeting.status == "scheduled",
                    Meeting.scheduled_at >= now,
                )
                .order_by(Meeting.scheduled_at)
                .limit(limit)
            )

        result = await self.db.execute(statement)
        return list(result.scalars().all())

    async def reschedule_meeting(
        self, meeting_id: uuid.UUID, new_time: datetime
    ) -> Meeting:
        """Reschedule a meeting to a new time.

        Updates the scheduled_at field of an existing meeting.

        Args:
            meeting_id: The ID of the meeting to reschedule.
            new_time: The new scheduled time for the meeting.

        Returns:
            The updated Meeting record.

        Raises:
            ValueError: If the meeting is not found.
        """
        statement = select(Meeting).where(Meeting.id == meeting_id)
        result = await self.db.execute(statement)
        meeting = result.scalar_one_or_none()

        if meeting is None:
            raise ValueError(f"Meeting {meeting_id} not found")

        meeting.scheduled_at = new_time
        self.db.add(meeting)
        await self.db.commit()
        await self.db.refresh(meeting)
        return meeting
