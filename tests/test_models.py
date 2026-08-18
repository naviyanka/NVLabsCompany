"""Tests for all SQLModel table classes.

Validates that models can be instantiated with required fields,
defaults work correctly, and field relationships are properly defined.
"""

import uuid
from datetime import datetime, timezone

import pytest

# We test models by direct instantiation (SQLModel supports this without a DB).
# Since we cannot pip install dependencies, we validate the module structure
# by testing the pure dataclass-like instantiation behavior.


class TestCompanyModel:
    """Tests for the Company model."""

    def test_company_instantiate_with_required_fields(self):
        """Company can be created with just a name."""
        from nexus.models.company import Company

        company = Company(name="Acme AI")
        assert company.name == "Acme AI"
        assert company.id is not None
        assert isinstance(company.id, uuid.UUID)

    def test_company_default_status(self):
        """Company defaults to active status."""
        from nexus.models.company import Company

        company = Company(name="Test Corp")
        assert company.status == "active"

    def test_company_default_budget(self):
        """Company budget defaults to zero."""
        from nexus.models.company import Company

        company = Company(name="Budget Corp")
        assert company.budget_monthly_cents == 0
        assert company.spent_monthly_cents == 0

    def test_company_timestamps_set(self):
        """Company has created_at and updated_at set on creation."""
        from nexus.models.company import Company

        company = Company(name="Time Corp")
        assert company.created_at is not None
        assert company.updated_at is not None
        assert isinstance(company.created_at, datetime)


class TestCompanyMembershipModel:
    """Tests for the CompanyMembership model."""

    def test_membership_instantiate(self):
        """CompanyMembership can be created with required fields."""
        from nexus.models.company import CompanyMembership

        cid = uuid.uuid4()
        uid = uuid.uuid4()
        membership = CompanyMembership(company_id=cid, user_id=uid)
        assert membership.company_id == cid
        assert membership.user_id == uid
        assert membership.role == "member"


class TestDepartmentModel:
    """Tests for the Department model."""

    def test_department_instantiate(self):
        """Department can be created with required fields."""
        from nexus.models.company import Department

        cid = uuid.uuid4()
        dept = Department(company_id=cid, name="Engineering")
        assert dept.name == "Engineering"
        assert dept.company_id == cid


class TestTeamModel:
    """Tests for the Team model."""

    def test_team_instantiate(self):
        """Team can be created with required fields."""
        from nexus.models.company import Team

        cid = uuid.uuid4()
        did = uuid.uuid4()
        team = Team(company_id=cid, department_id=did, name="ML Team")
        assert team.name == "ML Team"
        assert team.department_id == did


class TestAgentModel:
    """Tests for the Agent model."""

    def test_agent_instantiate_with_required_fields(self):
        """Agent can be created with company_id, name, and role."""
        from nexus.models.agent import Agent

        cid = uuid.uuid4()
        agent = Agent(company_id=cid, name="Worker-1", role="engineer")
        assert agent.name == "Worker-1"
        assert agent.role == "engineer"
        assert agent.company_id == cid

    def test_agent_default_status(self):
        """Agent defaults to idle status."""
        from nexus.models.agent import Agent

        agent = Agent(company_id=uuid.uuid4(), name="Agent", role="dev")
        assert agent.status == "idle"

    def test_agent_default_adapter(self):
        """Agent defaults to langchain adapter."""
        from nexus.models.agent import Agent

        agent = Agent(company_id=uuid.uuid4(), name="Agent", role="dev")
        assert agent.adapter_type == "langchain"

    def test_agent_optional_fields_none(self):
        """Optional fields default to None."""
        from nexus.models.agent import Agent

        agent = Agent(company_id=uuid.uuid4(), name="Agent", role="dev")
        assert agent.title is None
        assert agent.department_id is None
        assert agent.team_id is None
        assert agent.manager_id is None
        assert agent.model is None

    def test_agent_budget_defaults(self):
        """Agent budget and performance fields have defaults."""
        from nexus.models.agent import Agent

        agent = Agent(company_id=uuid.uuid4(), name="Agent", role="dev")
        assert agent.budget_monthly_cents == 0
        assert agent.spent_monthly_cents == 0
        assert agent.performance_score is None

    def test_agent_company_id_reference(self):
        """Agent company_id correctly references a company UUID."""
        from nexus.models.agent import Agent

        cid = uuid.UUID("12345678-1234-1234-1234-123456789abc")
        agent = Agent(company_id=cid, name="Ref Agent", role="tester")
        assert agent.company_id == cid


class TestGoalModel:
    """Tests for the Goal model."""

    def test_goal_instantiate(self):
        """Goal can be created with required fields."""
        from nexus.models.task import Goal

        cid = uuid.uuid4()
        goal = Goal(company_id=cid, title="Increase revenue 10x")
        assert goal.title == "Increase revenue 10x"
        assert goal.status == "active"
        assert goal.level == "company"


class TestProjectModel:
    """Tests for the Project model."""

    def test_project_instantiate(self):
        """Project can be created with required fields."""
        from nexus.models.task import Project

        cid = uuid.uuid4()
        project = Project(company_id=cid, name="Project Alpha")
        assert project.name == "Project Alpha"
        assert project.status == "active"
        assert project.budget_cents == 0


class TestTaskModel:
    """Tests for the Task model."""

    def test_task_instantiate_with_required_fields(self):
        """Task can be created with company_id and title."""
        from nexus.models.task import Task

        cid = uuid.uuid4()
        task = Task(company_id=cid, title="Write tests")
        assert task.title == "Write tests"
        assert task.company_id == cid

    def test_task_default_status(self):
        """Task defaults to pending status."""
        from nexus.models.task import Task

        task = Task(company_id=uuid.uuid4(), title="Test Task")
        assert task.status == "pending"

    def test_task_default_priority(self):
        """Task defaults to priority 0."""
        from nexus.models.task import Task

        task = Task(company_id=uuid.uuid4(), title="Test Task")
        assert task.priority == 0

    def test_task_optional_fields(self):
        """Task optional fields default to None."""
        from nexus.models.task import Task

        task = Task(company_id=uuid.uuid4(), title="Test Task")
        assert task.project_id is None
        assert task.assigned_agent_id is None
        assert task.result is None
        assert task.error is None


class TestBudgetPolicyModel:
    """Tests for the BudgetPolicy model."""

    def test_budget_policy_instantiate(self):
        """BudgetPolicy can be created with required fields."""
        from nexus.models.budget import BudgetPolicy

        cid = uuid.uuid4()
        sid = uuid.uuid4()
        policy = BudgetPolicy(
            company_id=cid,
            scope_type="agent",
            scope_id=sid,
            metric="cost_cents",
            window_kind="monthly",
            amount=10000,
        )
        assert policy.scope_type == "agent"
        assert policy.amount == 10000
        assert policy.warn_percent == 80
        assert policy.hard_stop_enabled is True
        assert policy.is_active is True


class TestCostEventModel:
    """Tests for the CostEvent model."""

    def test_cost_event_instantiate(self):
        """CostEvent can be created with required fields."""
        from nexus.models.budget import CostEvent

        cid = uuid.uuid4()
        event = CostEvent(company_id=cid, provider="openai")
        assert event.provider == "openai"
        assert event.input_tokens == 0
        assert event.output_tokens == 0
        assert event.cost_cents == 0


class TestApprovalModel:
    """Tests for the Approval model."""

    def test_approval_instantiate(self):
        """Approval can be created with required fields."""
        from nexus.models.governance import Approval

        cid = uuid.uuid4()
        approval = Approval(company_id=cid, type="deployment")
        assert approval.type == "deployment"
        assert approval.status == "pending"
        assert approval.decided_by is None


class TestSkillModel:
    """Tests for the Skill model."""

    def test_skill_instantiate(self):
        """Skill can be created with required fields."""
        from nexus.models.skill import Skill

        cid = uuid.uuid4()
        skill = Skill(company_id=cid, name="code_review")
        assert skill.name == "code_review"
        assert skill.version == "1.0.0"
        assert skill.category is None


class TestToolModel:
    """Tests for the Tool model."""

    def test_tool_instantiate(self):
        """Tool can be created with required fields."""
        from nexus.models.tool import Tool

        cid = uuid.uuid4()
        tool = Tool(company_id=cid, name="git_push", tool_type="function")
        assert tool.name == "git_push"
        assert tool.tool_type == "function"
        assert tool.is_active is True
        assert tool.risk_level == "low"


class TestMemoryRecordModel:
    """Tests for the MemoryRecord model."""

    def test_memory_record_instantiate(self):
        """MemoryRecord can be created with required fields."""
        from nexus.models.memory import MemoryRecord

        cid = uuid.uuid4()
        record = MemoryRecord(
            company_id=cid,
            scope="agent",
            content="The user prefers concise responses",
        )
        assert record.scope == "agent"
        assert record.content == "The user prefers concise responses"
        assert record.tier == "warm"
        assert record.importance == 0.5
        assert record.access_count == 0


class TestTriggerModel:
    """Tests for the Trigger model."""

    def test_trigger_instantiate(self):
        """Trigger can be created with required fields."""
        from nexus.models.trigger import Trigger

        cid = uuid.uuid4()
        aid = uuid.uuid4()
        trigger = Trigger(
            company_id=cid,
            agent_id=aid,
            trigger_type="cron",
            name="daily_report",
        )
        assert trigger.trigger_type == "cron"
        assert trigger.name == "daily_report"
        assert trigger.is_active is True
        assert trigger.last_fired_at is None
