"""Tests for the Meetings module.

Validates MeetingScheduler, MeetingConductor, and MeetingTemplates functionality.
Pure logic tests do not require a database. DB-dependent methods use mocked sessions.
"""

import uuid
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from nexus.meetings.templates import MeetingTemplates
from nexus.meetings.conductor import MeetingConductor
from nexus.meetings.scheduler import MeetingScheduler


@pytest.fixture
def company_id():
    """Provide a fixed company UUID for tests."""
    return uuid.UUID("12345678-1234-1234-1234-123456789abc")


@pytest.fixture
def agent_a_id():
    """Provide a fixed agent A UUID for tests."""
    return uuid.UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")


@pytest.fixture
def agent_b_id():
    """Provide a fixed agent B UUID for tests."""
    return uuid.UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")


@pytest.fixture
def mock_db():
    """Provide a mocked async database session."""
    db = AsyncMock()
    db.add = MagicMock()
    db.flush = AsyncMock()
    db.commit = AsyncMock()
    db.refresh = AsyncMock()
    db.execute = AsyncMock()
    return db


class TestMeetingTemplates:
    """Tests for the MeetingTemplates class."""

    def test_standup_template_structure(self):
        """Standup template has correct meeting_type and sections."""
        template = MeetingTemplates.get_standup_template()
        assert template["meeting_type"] == "standup"
        assert len(template["sections"]) == 3
        section_names = [s["name"] for s in template["sections"]]
        assert section_names == ["blockers", "progress", "next_steps"]
        assert template["duration_minutes"] == 15
        assert "facilitator" in template["required_roles"]

    def test_planning_template_structure(self):
        """Planning template has correct meeting_type and sections."""
        template = MeetingTemplates.get_planning_template()
        assert template["meeting_type"] == "planning"
        assert len(template["sections"]) == 4
        section_names = [s["name"] for s in template["sections"]]
        assert section_names == ["goal", "capacity", "task_selection", "assignments"]
        assert template["duration_minutes"] == 60

    def test_retrospective_template_structure(self):
        """Retrospective template has correct meeting_type and sections."""
        template = MeetingTemplates.get_retrospective_template()
        assert template["meeting_type"] == "retrospective"
        assert len(template["sections"]) == 3
        section_names = [s["name"] for s in template["sections"]]
        assert section_names == ["went_well", "improve", "actions"]
        assert template["duration_minutes"] == 45

    def test_design_review_template_structure(self):
        """Design review template has correct meeting_type and sections."""
        template = MeetingTemplates.get_design_review_template()
        assert template["meeting_type"] == "design_review"
        assert len(template["sections"]) == 4
        section_names = [s["name"] for s in template["sections"]]
        assert section_names == ["proposal", "critique", "decision", "next_steps"]
        assert template["duration_minutes"] == 60

    def test_priority_alignment_template_structure(self):
        """Priority alignment template has correct meeting_type and sections."""
        template = MeetingTemplates.get_priority_alignment_template()
        assert template["meeting_type"] == "priority_alignment"
        assert len(template["sections"]) == 4
        section_names = [s["name"] for s in template["sections"]]
        assert section_names == ["goals", "priorities", "trade_offs", "consensus"]
        assert template["duration_minutes"] == 45

    def test_get_all_templates_returns_all_five(self):
        """get_all_templates returns all 5 meeting types."""
        all_templates = MeetingTemplates.get_all_templates()
        assert len(all_templates) == 5
        expected_keys = {"standup", "planning", "retrospective", "design_review", "priority_alignment"}
        assert set(all_templates.keys()) == expected_keys

    def test_all_templates_have_required_fields(self):
        """All templates have meeting_type, sections, duration_minutes, required_roles."""
        all_templates = MeetingTemplates.get_all_templates()
        for key, template in all_templates.items():
            assert "meeting_type" in template, f"{key} missing meeting_type"
            assert "sections" in template, f"{key} missing sections"
            assert "duration_minutes" in template, f"{key} missing duration_minutes"
            assert "required_roles" in template, f"{key} missing required_roles"
            assert isinstance(template["sections"], list)
            for section in template["sections"]:
                assert "name" in section, f"{key} section missing name"
                assert "prompt" in section, f"{key} section missing prompt"
                assert "expected_format" in section, f"{key} section missing expected_format"


class TestMeetingConductorPureLogic:
    """Tests for MeetingConductor pure logic methods (no DB)."""

    def test_generate_agenda_from_template(self, mock_db):
        """generate_agenda creates ordered agenda items from template sections."""
        conductor = MeetingConductor(db=mock_db)
        template = MeetingTemplates.get_standup_template()

        agenda = conductor.generate_agenda("standup", template)

        assert len(agenda) == 3
        assert agenda[0]["section"] == "blockers"
        assert agenda[0]["order"] == 1
        assert agenda[1]["section"] == "progress"
        assert agenda[1]["order"] == 2
        assert agenda[2]["section"] == "next_steps"
        assert agenda[2]["order"] == 3

    def test_generate_agenda_includes_prompts(self, mock_db):
        """generate_agenda includes prompt and expected_format from template."""
        conductor = MeetingConductor(db=mock_db)
        template = MeetingTemplates.get_planning_template()

        agenda = conductor.generate_agenda("planning", template)

        for item in agenda:
            assert "prompt" in item
            assert "expected_format" in item
            assert len(item["prompt"]) > 0

    def test_generate_agenda_empty_template(self, mock_db):
        """generate_agenda handles empty template gracefully."""
        conductor = MeetingConductor(db=mock_db)
        template = {"sections": []}

        agenda = conductor.generate_agenda("custom", template)

        assert agenda == []

    def test_extract_action_items_action_prefix(self, mock_db):
        """extract_action_items finds ACTION: prefixed lines."""
        conductor = MeetingConductor(db=mock_db)
        text = "Some notes\nACTION: Deploy the new service\nMore notes"

        items = conductor.extract_action_items(text)

        assert len(items) == 1
        assert items[0]["description"] == "Deploy the new service"

    def test_extract_action_items_todo_prefix(self, mock_db):
        """extract_action_items finds TODO: prefixed lines."""
        conductor = MeetingConductor(db=mock_db)
        text = "TODO: Write documentation\nTODO: Update tests"

        items = conductor.extract_action_items(text)

        assert len(items) == 2
        assert items[0]["description"] == "Write documentation"
        assert items[1]["description"] == "Update tests"

    def test_extract_action_items_checkbox(self, mock_db):
        """extract_action_items finds markdown checkbox lines."""
        conductor = MeetingConductor(db=mock_db)
        text = "- [ ] Review the PR\n- [x] Already done\n- [ ] Fix the bug"

        items = conductor.extract_action_items(text)

        assert len(items) == 2
        assert items[0]["description"] == "Review the PR"
        assert items[1]["description"] == "Fix the bug"

    def test_extract_action_items_mixed_patterns(self, mock_db):
        """extract_action_items finds all pattern types in one text."""
        conductor = MeetingConductor(db=mock_db)
        text = """Meeting notes:
ACTION: Deploy service by Friday
Some discussion happened.
TODO: Update the API docs
- [ ] Send follow-up email
Regular line with no action items.
"""
        items = conductor.extract_action_items(text)

        assert len(items) == 3
        assert items[0]["description"] == "Deploy service by Friday"
        assert items[1]["description"] == "Update the API docs"
        assert items[2]["description"] == "Send follow-up email"

    def test_extract_action_items_case_insensitive(self, mock_db):
        """extract_action_items handles case variations of ACTION/TODO."""
        conductor = MeetingConductor(db=mock_db)
        text = "action: Lower case action\ntodo: lower case todo"

        items = conductor.extract_action_items(text)

        assert len(items) == 2

    def test_extract_action_items_no_items(self, mock_db):
        """extract_action_items returns empty list when no patterns found."""
        conductor = MeetingConductor(db=mock_db)
        text = "Just some regular meeting notes.\nNothing actionable here."

        items = conductor.extract_action_items(text)

        assert items == []


class TestMeetingScheduler:
    """Tests for MeetingScheduler scheduling and cancellation."""

    def test_scheduler_stores_db_session(self, mock_db):
        """Scheduler stores the provided db session."""
        scheduler = MeetingScheduler(db=mock_db)
        assert scheduler.db is mock_db

    @pytest.mark.asyncio
    async def test_schedule_meeting_creates_proper_structure(
        self, mock_db, company_id, agent_a_id, agent_b_id
    ):
        """schedule_meeting creates a Meeting and MeetingParticipant records."""
        scheduler = MeetingScheduler(db=mock_db)
        scheduled_at = datetime.now(timezone.utc) + timedelta(hours=1)

        participants = [
            {"agent_id": agent_a_id, "role": "facilitator"},
            {"agent_id": agent_b_id, "role": "required"},
        ]

        meeting = await scheduler.schedule_meeting(
            company_id=company_id,
            meeting_type="standup",
            title="Daily Standup",
            scheduled_at=scheduled_at,
            participants=participants,
        )

        # Verify db.add was called for meeting + 2 participants = 3 times
        assert mock_db.add.call_count == 3
        assert mock_db.flush.await_count == 1
        assert mock_db.commit.await_count == 1
        assert mock_db.refresh.await_count == 1

        # The meeting object should have correct fields
        assert meeting.meeting_type == "standup"
        assert meeting.title == "Daily Standup"
        assert meeting.status == "scheduled"
        assert meeting.scheduled_at == scheduled_at
        assert meeting.company_id == company_id

    @pytest.mark.asyncio
    async def test_schedule_meeting_with_recurrence(
        self, mock_db, company_id, agent_a_id
    ):
        """schedule_meeting stores recurrence_rule when provided."""
        scheduler = MeetingScheduler(db=mock_db)
        scheduled_at = datetime.now(timezone.utc) + timedelta(hours=1)

        participants = [{"agent_id": agent_a_id, "role": "required"}]

        meeting = await scheduler.schedule_meeting(
            company_id=company_id,
            meeting_type="standup",
            title="Recurring Standup",
            scheduled_at=scheduled_at,
            participants=participants,
            recurrence_rule="daily",
        )

        assert meeting.recurrence_rule == "daily"

    @pytest.mark.asyncio
    async def test_schedule_meeting_no_recurrence(
        self, mock_db, company_id, agent_a_id
    ):
        """schedule_meeting sets recurrence_rule to None for one-off meetings."""
        scheduler = MeetingScheduler(db=mock_db)
        scheduled_at = datetime.now(timezone.utc) + timedelta(hours=1)

        participants = [{"agent_id": agent_a_id, "role": "required"}]

        meeting = await scheduler.schedule_meeting(
            company_id=company_id,
            meeting_type="planning",
            title="One-off Planning",
            scheduled_at=scheduled_at,
            participants=participants,
        )

        assert meeting.recurrence_rule is None

    @pytest.mark.asyncio
    async def test_cancel_meeting(self, mock_db):
        """cancel_meeting sets status to cancelled."""
        scheduler = MeetingScheduler(db=mock_db)

        # Mock finding a meeting
        from unittest.mock import MagicMock as MockMeeting
        mock_meeting = MockMeeting()
        mock_meeting.id = uuid.uuid4()
        mock_meeting.status = "scheduled"

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_meeting
        mock_db.execute.return_value = mock_result

        result = await scheduler.cancel_meeting(mock_meeting.id)

        assert result.status == "cancelled"
        mock_db.commit.assert_awaited()

    @pytest.mark.asyncio
    async def test_cancel_meeting_not_found_raises(self, mock_db):
        """cancel_meeting raises ValueError when meeting not found."""
        scheduler = MeetingScheduler(db=mock_db)

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db.execute.return_value = mock_result

        with pytest.raises(ValueError, match="Meeting .* not found"):
            await scheduler.cancel_meeting(uuid.uuid4())


class TestMeetingConductorInit:
    """Tests for MeetingConductor initialization."""

    def test_conductor_stores_db_session(self, mock_db):
        """Conductor stores the provided db session."""
        conductor = MeetingConductor(db=mock_db)
        assert conductor.db is mock_db
