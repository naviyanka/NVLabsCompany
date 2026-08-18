"""Meeting conductor for running meeting sessions.

Handles the execution lifecycle of a meeting: starting, collecting input
from participants, generating agendas, extracting action items, producing
minutes, and ending the meeting.
"""

import re
import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from nexus.models.meeting import ActionItem, Meeting, MeetingMinutes, MeetingParticipant


class MeetingConductor:
    """Conducts meetings through their execution lifecycle.

    Manages the transition of meetings from scheduled through in_progress
    to completed, collecting agent contributions, generating structured
    minutes, and creating action items.
    """

    def __init__(self, db: AsyncSession) -> None:
        """Initialize the conductor with a database session.

        Args:
            db: An async SQLAlchemy session for persistence operations.
        """
        self.db = db

    async def start_meeting(self, meeting_id: uuid.UUID) -> Meeting:
        """Start a scheduled meeting, transitioning it to in_progress.

        Sets the meeting status to 'in_progress' and records the started_at
        timestamp.

        Args:
            meeting_id: The ID of the meeting to start.

        Returns:
            The updated Meeting record.

        Raises:
            ValueError: If the meeting is not found or not in 'scheduled' status.
        """
        statement = select(Meeting).where(Meeting.id == meeting_id)
        result = await self.db.execute(statement)
        meeting = result.scalar_one_or_none()

        if meeting is None:
            raise ValueError(f"Meeting {meeting_id} not found")

        if meeting.status != "scheduled":
            raise ValueError(
                f"Meeting {meeting_id} cannot be started from status '{meeting.status}'"
            )

        meeting.status = "in_progress"
        meeting.started_at = datetime.now(timezone.utc)
        self.db.add(meeting)
        await self.db.commit()
        await self.db.refresh(meeting)
        return meeting

    def generate_agenda(self, meeting_type: str, template: dict) -> list[dict]:
        """Generate an agenda from a meeting template.

        Builds a structured list of agenda items from the template's sections,
        including prompts and expected formats for each section.

        Args:
            meeting_type: The type of meeting (used for context).
            template: A template dict with 'sections' list containing dicts
                with 'name', 'prompt', and 'expected_format' keys.

        Returns:
            List of agenda item dicts with 'section', 'prompt',
            'expected_format', and 'order' keys.
        """
        agenda_items = []
        for i, section in enumerate(template.get("sections", [])):
            agenda_items.append(
                {
                    "section": section["name"],
                    "prompt": section["prompt"],
                    "expected_format": section["expected_format"],
                    "order": i + 1,
                }
            )
        return agenda_items

    async def collect_input(
        self, meeting_id: uuid.UUID, agent_id: uuid.UUID, input_text: str
    ) -> MeetingParticipant:
        """Record an agent's contribution to a meeting.

        Marks the participant as having attended and stores their input.
        This tracks active participation during meeting sessions.

        Args:
            meeting_id: The ID of the meeting.
            agent_id: The ID of the contributing agent.
            input_text: The text contribution from the agent.

        Returns:
            The updated MeetingParticipant record.

        Raises:
            ValueError: If the participant record is not found.
        """
        statement = select(MeetingParticipant).where(
            MeetingParticipant.meeting_id == meeting_id,
            MeetingParticipant.agent_id == agent_id,
        )
        result = await self.db.execute(statement)
        participant = result.scalar_one_or_none()

        if participant is None:
            raise ValueError(
                f"Participant {agent_id} not found in meeting {meeting_id}"
            )

        participant.attended = True
        self.db.add(participant)
        await self.db.commit()
        await self.db.refresh(participant)
        return participant

    def extract_action_items(self, minutes_text: str) -> list[dict]:
        """Extract action items from meeting minutes text.

        Parses text looking for action item patterns:
        - Lines starting with "ACTION:"
        - Lines starting with "TODO:"
        - Lines starting with "- [ ]" (markdown checkbox)

        Args:
            minutes_text: The raw text of meeting minutes/notes.

        Returns:
            List of dicts with 'description' key for each extracted action item.
        """
        action_items: list[dict] = []
        lines = minutes_text.split("\n")

        for line in lines:
            stripped = line.strip()

            # Match ACTION: prefix
            match = re.match(r"^ACTION:\s*(.+)$", stripped, re.IGNORECASE)
            if match:
                action_items.append({"description": match.group(1).strip()})
                continue

            # Match TODO: prefix
            match = re.match(r"^TODO:\s*(.+)$", stripped, re.IGNORECASE)
            if match:
                action_items.append({"description": match.group(1).strip()})
                continue

            # Match markdown checkbox - [ ]
            match = re.match(r"^-\s*\[\s*\]\s*(.+)$", stripped)
            if match:
                action_items.append({"description": match.group(1).strip()})
                continue

        return action_items

    async def generate_minutes(
        self,
        meeting_id: uuid.UUID,
        company_id: uuid.UUID,
        contributions: list[dict],
    ) -> MeetingMinutes:
        """Generate and store meeting minutes from agent contributions.

        Creates a MeetingMinutes record with a summary built from the
        contributions and any decisions made during the meeting.

        Args:
            meeting_id: The ID of the meeting.
            company_id: The company this meeting belongs to.
            contributions: List of dicts with 'agent_id', 'section', and
                'content' keys representing each agent's input.

        Returns:
            The created MeetingMinutes record.
        """
        # Build summary from contributions
        summary_parts = []
        decisions: dict = {}

        for contribution in contributions:
            agent_id = contribution.get("agent_id", "unknown")
            section = contribution.get("section", "general")
            content = contribution.get("content", "")
            summary_parts.append(f"[{section}] Agent {agent_id}: {content}")

            # Extract decisions from contributions marked as such
            if section == "decision" or section == "decisions":
                decisions[str(agent_id)] = content

        summary = "\n".join(summary_parts) if summary_parts else "No contributions recorded."

        minutes = MeetingMinutes(
            meeting_id=meeting_id,
            company_id=company_id,
            summary=summary,
            decisions=decisions if decisions else None,
        )
        self.db.add(minutes)
        await self.db.commit()
        await self.db.refresh(minutes)
        return minutes

    async def end_meeting(self, meeting_id: uuid.UUID) -> Meeting:
        """End a meeting, transitioning it to completed status.

        Sets the meeting status to 'completed' and records the completed_at
        timestamp.

        Args:
            meeting_id: The ID of the meeting to end.

        Returns:
            The updated Meeting record.

        Raises:
            ValueError: If the meeting is not found or not in 'in_progress' status.
        """
        statement = select(Meeting).where(Meeting.id == meeting_id)
        result = await self.db.execute(statement)
        meeting = result.scalar_one_or_none()

        if meeting is None:
            raise ValueError(f"Meeting {meeting_id} not found")

        if meeting.status != "in_progress":
            raise ValueError(
                f"Meeting {meeting_id} cannot be ended from status '{meeting.status}'"
            )

        meeting.status = "completed"
        meeting.completed_at = datetime.now(timezone.utc)
        self.db.add(meeting)
        await self.db.commit()
        await self.db.refresh(meeting)
        return meeting

    async def create_action_items(
        self,
        meeting_id: uuid.UUID,
        company_id: uuid.UUID,
        items: list[dict],
    ) -> list[ActionItem]:
        """Create action item records from a list of item descriptions.

        Each item dict should contain 'description' and 'assigned_agent_id',
        with optional 'due_at' datetime.

        Args:
            meeting_id: The ID of the meeting these items came from.
            company_id: The company this meeting belongs to.
            items: List of dicts with 'description' (str),
                'assigned_agent_id' (UUID), and optional 'due_at' (datetime).

        Returns:
            List of created ActionItem records.
        """
        action_items: list[ActionItem] = []

        for item in items:
            action_item = ActionItem(
                meeting_id=meeting_id,
                company_id=company_id,
                assigned_agent_id=item["assigned_agent_id"],
                description=item["description"],
                status="pending",
                due_at=item.get("due_at"),
            )
            self.db.add(action_item)
            action_items.append(action_item)

        await self.db.commit()

        for action_item in action_items:
            await self.db.refresh(action_item)

        return action_items
