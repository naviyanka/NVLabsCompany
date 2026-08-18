"""Tests for the Company Simulation module.

Tests OrgChart, DelegationEngine, PerformanceManager, and HiringManager
using pure logic (no DB) with mock objects.
"""

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from nexus.company import (
    DelegationEngine,
    HiringManager,
    OrgChart,
    PerformanceManager,
)


# --- Helpers ---


def make_agent(
    agent_id=None,
    company_id=None,
    name="Agent",
    role="engineer",
    title="Engineer",
    manager_id=None,
    department_id=None,
    team_id=None,
    skills=None,
    status="idle",
):
    """Create a mock agent object."""
    return SimpleNamespace(
        id=agent_id or uuid.uuid4(),
        company_id=company_id or uuid.uuid4(),
        name=name,
        role=role,
        title=title,
        manager_id=manager_id,
        department_id=department_id,
        team_id=team_id,
        skills=skills or [],
        tools=[],
        capabilities=[],
        status=status,
        budget_monthly_cents=5000,
        spent_monthly_cents=0,
        performance_score=None,
    )


def make_department(dept_id=None, company_id=None, name="Engineering"):
    """Create a mock department object."""
    return SimpleNamespace(
        id=dept_id or uuid.uuid4(),
        company_id=company_id or uuid.uuid4(),
        name=name,
    )


def make_team(team_id=None, company_id=None, department_id=None, name="Team Alpha"):
    """Create a mock team object."""
    return SimpleNamespace(
        id=team_id or uuid.uuid4(),
        company_id=company_id or uuid.uuid4(),
        department_id=department_id or uuid.uuid4(),
        name=name,
    )


# --- OrgChart Tests ---


class TestOrgChart:
    """Tests for OrgChart organizational hierarchy management."""

    def setup_method(self):
        self.org_chart = OrgChart()
        self.company_id = uuid.uuid4()

    def test_build_hierarchy_single_root(self):
        """A single agent with no manager is the root."""
        ceo = make_agent(company_id=self.company_id, name="CEO", manager_id=None)
        result = self.org_chart.build_hierarchy(self.company_id, [ceo])
        assert ceo.id in result
        assert result[ceo.id]["agent"] == ceo
        assert result[ceo.id]["reports"] == []

    def test_build_hierarchy_with_reports(self):
        """Agents with manager_id are nested under their manager."""
        ceo = make_agent(company_id=self.company_id, name="CEO", manager_id=None)
        cto = make_agent(company_id=self.company_id, name="CTO", manager_id=ceo.id)
        eng = make_agent(company_id=self.company_id, name="Eng", manager_id=cto.id)

        result = self.org_chart.build_hierarchy(self.company_id, [ceo, cto, eng])
        assert ceo.id in result
        assert len(result[ceo.id]["reports"]) == 1
        assert result[ceo.id]["reports"][0]["agent"] == cto
        assert len(result[ceo.id]["reports"][0]["reports"]) == 1
        assert result[ceo.id]["reports"][0]["reports"][0]["agent"] == eng

    def test_build_hierarchy_filters_by_company(self):
        """Only agents from the specified company are included."""
        other_company = uuid.uuid4()
        agent_a = make_agent(company_id=self.company_id, name="A")
        agent_b = make_agent(company_id=other_company, name="B")

        result = self.org_chart.build_hierarchy(self.company_id, [agent_a, agent_b])
        assert agent_a.id in result
        assert agent_b.id not in result

    def test_get_reporting_chain(self):
        """Chain goes from agent up to root."""
        ceo = make_agent(company_id=self.company_id, name="CEO", manager_id=None)
        cto = make_agent(company_id=self.company_id, name="CTO", manager_id=ceo.id)
        eng = make_agent(company_id=self.company_id, name="Eng", manager_id=cto.id)

        agents = [ceo, cto, eng]
        chain = self.org_chart.get_reporting_chain(eng.id, agents)
        assert len(chain) == 3
        assert chain[0] == eng
        assert chain[1] == cto
        assert chain[2] == ceo

    def test_get_reporting_chain_root(self):
        """Root agent chain is just itself."""
        ceo = make_agent(company_id=self.company_id, name="CEO", manager_id=None)
        chain = self.org_chart.get_reporting_chain(ceo.id, [ceo])
        assert len(chain) == 1
        assert chain[0] == ceo

    def test_get_direct_reports(self):
        """Returns only direct reports."""
        ceo = make_agent(company_id=self.company_id, name="CEO", manager_id=None)
        cto = make_agent(company_id=self.company_id, name="CTO", manager_id=ceo.id)
        cfo = make_agent(company_id=self.company_id, name="CFO", manager_id=ceo.id)
        eng = make_agent(company_id=self.company_id, name="Eng", manager_id=cto.id)

        agents = [ceo, cto, cfo, eng]
        reports = self.org_chart.get_direct_reports(ceo.id, agents)
        assert len(reports) == 2
        assert cto in reports
        assert cfo in reports
        assert eng not in reports

    def test_get_department_structure(self):
        """Returns nested dept -> teams -> agents structure."""
        dept = make_department(company_id=self.company_id)
        team = make_team(company_id=self.company_id, department_id=dept.id)
        agent = make_agent(
            company_id=self.company_id, team_id=team.id, department_id=dept.id
        )

        result = self.org_chart.get_department_structure(
            self.company_id, [dept], [team], [agent]
        )
        assert dept.id in result
        assert team.id in result[dept.id]["teams"]
        assert agent in result[dept.id]["teams"][team.id]["agents"]

    def test_calculate_span_of_control(self):
        """Counts direct and indirect reports."""
        ceo = make_agent(company_id=self.company_id, name="CEO", manager_id=None)
        cto = make_agent(company_id=self.company_id, name="CTO", manager_id=ceo.id)
        eng1 = make_agent(company_id=self.company_id, name="Eng1", manager_id=cto.id)
        eng2 = make_agent(company_id=self.company_id, name="Eng2", manager_id=cto.id)

        agents = [ceo, cto, eng1, eng2]
        span = self.org_chart.calculate_span_of_control(ceo.id, agents)
        assert span["direct"] == 1
        assert span["indirect"] == 2
        assert span["total"] == 3

    def test_serialize_to_dict(self):
        """Serializes hierarchy to JSON-safe dict."""
        ceo = make_agent(company_id=self.company_id, name="CEO", role="ceo")
        eng = make_agent(company_id=self.company_id, name="Eng", role="engineer", manager_id=ceo.id)

        hierarchy = self.org_chart.build_hierarchy(self.company_id, [ceo, eng])
        result = self.org_chart.serialize_to_dict(hierarchy)

        assert str(ceo.id) in result
        node = result[str(ceo.id)]
        assert node["name"] == "CEO"
        assert node["role"] == "ceo"
        assert len(node["reports"]) == 1
        assert node["reports"][0]["name"] == "Eng"


# --- DelegationEngine Tests ---


class TestDelegationEngine:
    """Tests for DelegationEngine task delegation."""

    def setup_method(self):
        self.engine = DelegationEngine()
        self.company_id = uuid.uuid4()

    def test_find_best_delegate_by_skills(self):
        """Agent with best skill match wins."""
        agent_a = make_agent(skills=["python", "testing"])
        agent_b = make_agent(skills=["python", "fastapi", "testing"])

        best, score = self.engine.find_best_delegate(
            "Build API tests", ["python", "testing", "fastapi"], [agent_a, agent_b]
        )
        assert best == agent_b
        assert score > 0

    def test_find_best_delegate_prefers_idle(self):
        """Idle agents preferred over busy ones with same skills."""
        agent_busy = make_agent(skills=["python"], status="busy")
        agent_idle = make_agent(skills=["python"], status="idle")

        best, score = self.engine.find_best_delegate(
            "Python task", ["python"], [agent_busy, agent_idle]
        )
        assert best == agent_idle

    def test_find_best_delegate_empty_candidates(self):
        """Returns (None, 0.0) for empty candidates."""
        best, score = self.engine.find_best_delegate("Task", ["python"], [])
        assert best is None
        assert score == 0.0

    @pytest.mark.asyncio
    async def test_delegate_task(self):
        """Creates delegation record and returns id with status."""
        task_id = uuid.uuid4()
        from_id = uuid.uuid4()
        to_id = uuid.uuid4()

        result = await self.engine.delegate_task(
            task_id, from_id, to_id, "best skills match", self.company_id
        )
        assert "delegation_id" in result
        assert result["status"] == "delegated"

    @pytest.mark.asyncio
    async def test_track_delegation(self):
        """Can track a delegation after creation."""
        task_id = uuid.uuid4()
        from_id = uuid.uuid4()
        to_id = uuid.uuid4()

        created = await self.engine.delegate_task(
            task_id, from_id, to_id, "test", self.company_id
        )
        tracked = await self.engine.track_delegation(created["delegation_id"])
        assert tracked["status"] == "delegated"
        assert tracked["from_agent_id"] == from_id

    @pytest.mark.asyncio
    async def test_track_delegation_not_found(self):
        """Returns not_found for unknown delegation."""
        result = await self.engine.track_delegation(uuid.uuid4())
        assert result["status"] == "not_found"

    @pytest.mark.asyncio
    async def test_get_delegation_chain(self):
        """Returns full delegation history for a task."""
        task_id = uuid.uuid4()
        from1 = uuid.uuid4()
        to1 = uuid.uuid4()
        to2 = uuid.uuid4()

        await self.engine.delegate_task(task_id, from1, to1, "step1", self.company_id)
        await self.engine.delegate_task(task_id, to1, to2, "step2", self.company_id)

        chain = await self.engine.get_delegation_chain(task_id)
        assert len(chain) == 2
        assert chain[0]["from_agent_id"] == from1
        assert chain[1]["from_agent_id"] == to1

    def test_cascade_delegation(self):
        """Walks chain and finds best delegate at each level."""
        ceo = make_agent(name="CEO", skills=["strategy"])
        cto = make_agent(name="CTO", skills=["python", "architecture"])
        eng = make_agent(name="Engineer", skills=["python", "testing"])

        chain = [[ceo], [cto], [eng]]
        steps = self.engine.cascade_delegation("Build tests", ["python", "testing"], chain)

        assert len(steps) == 2
        assert steps[0]["from_agent_id"] == ceo.id
        assert steps[0]["to_agent_id"] == cto.id
        assert steps[1]["from_agent_id"] == cto.id
        assert steps[1]["to_agent_id"] == eng.id


# --- PerformanceManager Tests ---


class TestPerformanceManager:
    """Tests for PerformanceManager scoring and recommendations."""

    def setup_method(self):
        self.pm = PerformanceManager()

    def test_calculate_score_empty_history(self):
        """Empty history returns 0."""
        assert self.pm.calculate_score([]) == 0.0

    def test_calculate_score_perfect_history(self):
        """Perfect metrics yield high score."""
        history = [
            {
                "task_id": uuid.uuid4(),
                "status": "completed",
                "quality_score": 1.0,
                "duration_hours": 2.0,
                "cost_cents": 100,
            }
            for _ in range(5)
        ]
        score = self.pm.calculate_score(history)
        assert score >= 90.0

    def test_calculate_score_mixed_history(self):
        """Mixed results give moderate score."""
        history = [
            {
                "task_id": uuid.uuid4(),
                "status": "completed",
                "quality_score": 0.8,
                "duration_hours": 4.0,
                "cost_cents": 500,
            },
            {
                "task_id": uuid.uuid4(),
                "status": "failed",
                "quality_score": 0.3,
                "duration_hours": 10.0,
                "cost_cents": 2000,
            },
        ]
        score = self.pm.calculate_score(history)
        assert 20.0 < score < 90.0

    def test_get_metrics(self):
        """Returns correct metrics breakdown."""
        history = [
            {
                "task_id": uuid.uuid4(),
                "status": "completed",
                "quality_score": 0.9,
                "duration_hours": 3.0,
                "cost_cents": 400,
            },
            {
                "task_id": uuid.uuid4(),
                "status": "completed",
                "quality_score": 0.7,
                "duration_hours": 5.0,
                "cost_cents": 600,
            },
        ]
        metrics = self.pm.get_metrics(history)
        assert metrics["total_tasks"] == 2
        assert metrics["completion_rate"] == 1.0
        assert metrics["avg_quality"] == 0.8
        assert metrics["avg_duration_hours"] == 4.0
        assert metrics["avg_cost_cents"] == 500.0

    def test_get_metrics_empty(self):
        """Empty history returns zeroes."""
        metrics = self.pm.get_metrics([])
        assert metrics["total_tasks"] == 0
        assert metrics["completion_rate"] == 0.0

    def test_compare_agents(self):
        """Agents are ranked by score."""
        agent1_id = uuid.uuid4()
        agent2_id = uuid.uuid4()

        histories = {
            agent1_id: [
                {"task_id": uuid.uuid4(), "status": "completed", "quality_score": 1.0, "duration_hours": 2.0, "cost_cents": 100}
            ],
            agent2_id: [
                {"task_id": uuid.uuid4(), "status": "failed", "quality_score": 0.2, "duration_hours": 20.0, "cost_cents": 5000}
            ],
        }

        ranked = self.pm.compare_agents(histories)
        assert len(ranked) == 2
        assert ranked[0]["agent_id"] == agent1_id
        assert ranked[0]["rank"] == 1
        assert ranked[1]["agent_id"] == agent2_id
        assert ranked[1]["rank"] == 2

    def test_get_recommendations_promote(self):
        """High score yields promote recommendation."""
        recs = self.pm.get_recommendations(95.0, [{"status": "completed", "quality_score": 1.0}])
        assert "promote" in recs

    def test_get_recommendations_no_change(self):
        """Mid-high score yields no_change."""
        recs = self.pm.get_recommendations(75.0, [{"status": "completed", "quality_score": 0.8}])
        assert "no_change" in recs

    def test_get_recommendations_retrain(self):
        """Mid-low score yields retrain."""
        recs = self.pm.get_recommendations(55.0, [{"status": "completed", "quality_score": 0.6}])
        assert "retrain" in recs

    def test_get_recommendations_replace(self):
        """Low score yields replace."""
        recs = self.pm.get_recommendations(30.0, [{"status": "failed", "quality_score": 0.2}])
        assert "replace" in recs

    def test_track_trend_improving(self):
        """Last 3 > first 3 avg means improving."""
        scores = [50.0, 52.0, 48.0, 60.0, 70.0, 75.0, 80.0]
        assert self.pm.track_trend(scores) == "improving"

    def test_track_trend_declining(self):
        """Last 3 < first 3 avg means declining."""
        scores = [80.0, 85.0, 82.0, 60.0, 55.0, 50.0]
        assert self.pm.track_trend(scores) == "declining"

    def test_track_trend_stable(self):
        """Similar averages means stable."""
        scores = [70.0, 71.0, 69.0, 70.0, 71.0, 70.0]
        assert self.pm.track_trend(scores) == "stable"

    def test_track_trend_insufficient_data(self):
        """Less than 3 scores returns stable."""
        assert self.pm.track_trend([50.0, 60.0]) == "stable"


# --- HiringManager Tests ---


class TestHiringManager:
    """Tests for HiringManager hiring and onboarding workflows."""

    def setup_method(self):
        self.hm = HiringManager()
        self.company_id = uuid.uuid4()

    def test_generate_job_description(self):
        """Generates structured JD with all required fields."""
        jd = self.hm.generate_job_description(
            role="Backend Engineer",
            department="Engineering",
            responsibilities=["write APIs", "design databases"],
            required_skills=["python", "sql", "fastapi"],
        )
        assert jd["title"] == "Backend Engineer"
        assert jd["department"] == "Engineering"
        assert jd["responsibilities"] == ["write APIs", "design databases"]
        assert jd["required_skills"] == ["python", "sql", "fastapi"]
        assert isinstance(jd["preferred_skills"], list)
        assert isinstance(jd["description"], str)

    def test_create_agent_from_role(self):
        """Creates agent config dict from template."""
        template = {
            "role": "engineer",
            "name": "NewAgent",
            "title": "Junior Engineer",
            "skills": ["python", "testing"],
            "tools": ["code_editor", "terminal"],
            "budget_monthly_cents": 3000,
        }
        config = self.hm.create_agent_from_role(self.company_id, template)
        assert config["company_id"] == self.company_id
        assert config["name"] == "NewAgent"
        assert config["role"] == "engineer"
        assert config["skills"] == ["python", "testing"]
        assert config["status"] == "idle"
        assert config["spent_monthly_cents"] == 0
        assert "id" in config

    def test_design_onboarding(self):
        """Returns 4 onboarding steps."""
        steps = self.hm.design_onboarding(uuid.uuid4(), "engineer")
        assert len(steps) == 4
        actions = [s["action"] for s in steps]
        assert "configure_skills" in actions
        assert "assign_tools" in actions
        assert "set_permissions" in actions
        assert "initial_tasks" in actions
        assert all(s["status"] == "pending" for s in steps)
        assert steps[0]["step"] == 1
        assert steps[3]["step"] == 4

    def test_evaluate_probation_pass(self):
        """Agent with good history passes probation."""
        history = [
            {"task_id": uuid.uuid4(), "status": "completed", "quality_score": 0.9}
            for _ in range(5)
        ]
        result = self.hm.evaluate_probation(history)
        assert result["passed"] is True
        assert result["score"] > 0
        assert "meets_all_criteria" in result["reasons"]

    def test_evaluate_probation_fail_low_completion(self):
        """Agent with low completion fails."""
        history = [
            {"task_id": uuid.uuid4(), "status": "failed", "quality_score": 0.8}
            for _ in range(5)
        ]
        result = self.hm.evaluate_probation(history)
        assert result["passed"] is False
        assert "low_completion_rate" in result["reasons"]

    def test_evaluate_probation_fail_empty(self):
        """Empty history fails probation."""
        result = self.hm.evaluate_probation([])
        assert result["passed"] is False
        assert "no_tasks_completed_during_probation" in result["reasons"]

    def test_evaluate_probation_fail_insufficient_volume(self):
        """Too few tasks fails probation."""
        history = [
            {"task_id": uuid.uuid4(), "status": "completed", "quality_score": 0.9}
        ]
        result = self.hm.evaluate_probation(history)
        assert result["passed"] is False
        assert "insufficient_task_volume" in result["reasons"]

    def test_recommend_team_placement(self):
        """Recommends team with best skill overlap."""
        team1 = make_team(name="Frontend")
        team2 = make_team(name="Backend")

        team_agents = {
            team1.id: [["javascript", "css", "html"]],
            team2.id: [["python", "sql", "fastapi"]],
        }

        result = self.hm.recommend_team_placement(
            agent_skills=["python", "sql"],
            teams=[team1, team2],
            team_agents=team_agents,
        )
        assert result["recommended_team_id"] == team2.id
        assert result["skill_overlap"] > 0

    def test_recommend_team_placement_no_teams(self):
        """Returns None when no teams available."""
        result = self.hm.recommend_team_placement(
            agent_skills=["python"],
            teams=[],
            team_agents={},
        )
        assert result["recommended_team_id"] is None
        assert result["reason"] == "no_teams_available"
