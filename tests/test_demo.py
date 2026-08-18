"""Tests for NEXUS Demo Configuration - setup and scenarios.

Tests cover:
- setup_demo_company creates company with correct name
- Creates all 5 agents with correct roles and adapter types
- Sets up departments
- Sets up budget policies
- Sets up approval gates
- Idempotency (second call returns same structure)
- SCENARIOS has 3 entries with correct structure
- Each scenario has objective, delegation_path, success_criteria
- Scenario delegation paths are correct
"""

import uuid

import pytest

from nexus.demo.setup import (
    DemoCompany,
    AgentConfig,
    Department,
    BudgetPolicy,
    ApprovalGate,
    setup_demo_company,
    reset_demo_company,
)
from nexus.demo.scenarios import (
    SCENARIOS,
    Scenario,
    get_scenario,
    list_scenario_names,
)


class TestDemoSetup:
    """Test demo company bootstrapping and structure."""

    @pytest.fixture(autouse=True)
    def reset_state(self):
        """Reset demo company state before and after each test."""
        reset_demo_company()
        yield
        reset_demo_company()

    def test_setup_creates_company_with_correct_name(self):
        """setup_demo_company creates NexusCorp."""
        demo = setup_demo_company()

        assert isinstance(demo, DemoCompany)
        assert demo.company_name == "NexusCorp"
        assert isinstance(demo.company_id, uuid.UUID)

    def test_creates_all_five_agents(self):
        """Demo company has exactly 5 agents with expected names."""
        demo = setup_demo_company()

        expected_agents = {"Atlas", "Nova", "Forge", "Spark", "Shield"}
        assert set(demo.agents.keys()) == expected_agents
        assert len(demo.agents) == 5

    def test_agent_roles_correct(self):
        """Each agent has the correct role assignment."""
        demo = setup_demo_company()

        assert demo.agents["Atlas"].role == "ceo"
        assert demo.agents["Nova"].role == "cto"
        assert demo.agents["Forge"].role == "senior_engineer"
        assert demo.agents["Spark"].role == "junior_engineer"
        assert demo.agents["Shield"].role == "qa_engineer"

    def test_agent_adapter_types_correct(self):
        """Each agent has the correct adapter type."""
        demo = setup_demo_company()

        assert demo.agents["Atlas"].adapter_type == "anthropic"
        assert demo.agents["Nova"].adapter_type == "anthropic"
        assert demo.agents["Forge"].adapter_type == "openai"
        assert demo.agents["Spark"].adapter_type == "ollama"
        assert demo.agents["Shield"].adapter_type == "openai"

    def test_agents_have_souls(self):
        """Each agent has a valid Soul attached."""
        demo = setup_demo_company()

        for name, agent in demo.agents.items():
            assert isinstance(agent, AgentConfig)
            assert agent.soul is not None
            assert agent.soul.name == name
            assert agent.soul.role != ""

    def test_agents_have_capabilities(self):
        """Each agent has a non-empty capabilities list."""
        demo = setup_demo_company()

        for name, agent in demo.agents.items():
            assert len(agent.capabilities) > 0, f"{name} has no capabilities"

    def test_agent_hierarchy(self):
        """CEO has no manager, others report up correctly."""
        demo = setup_demo_company()

        # CEO has no manager
        assert demo.agents["Atlas"].manager_id is None

        # CTO reports to CEO
        assert demo.agents["Nova"].manager_id == demo.agents["Atlas"].agent_id

        # Engineers and QA report to CTO
        assert demo.agents["Forge"].manager_id == demo.agents["Nova"].agent_id
        assert demo.agents["Spark"].manager_id == demo.agents["Nova"].agent_id
        assert demo.agents["Shield"].manager_id == demo.agents["Nova"].agent_id

    def test_departments_setup(self):
        """Demo has Engineering and QA departments."""
        demo = setup_demo_company()

        assert "Engineering" in demo.departments
        assert "QA" in demo.departments
        assert len(demo.departments) == 2

        eng_dept = demo.departments["Engineering"]
        assert isinstance(eng_dept, Department)
        assert eng_dept.name == "Engineering"
        assert len(eng_dept.member_ids) >= 2

        qa_dept = demo.departments["QA"]
        assert isinstance(qa_dept, Department)
        assert qa_dept.name == "QA"
        assert len(qa_dept.member_ids) >= 1

    def test_budget_policies_setup(self):
        """Demo has budget policies for company and agents."""
        demo = setup_demo_company()

        assert len(demo.budget_policies) >= 2
        # Should have at least one company-level policy
        company_policies = [p for p in demo.budget_policies if p.scope_type == "company"]
        agent_policies = [p for p in demo.budget_policies if p.scope_type == "agent"]

        assert len(company_policies) >= 1
        assert len(agent_policies) >= 1

        # Company budget should be substantial
        assert company_policies[0].monthly_limit_cents > 0

    def test_approval_gates_setup(self):
        """Demo has approval gates configured."""
        demo = setup_demo_company()

        assert len(demo.approval_gates) >= 1
        gate_types = [g.gate_type for g in demo.approval_gates]
        assert "deployment" in gate_types

        for gate in demo.approval_gates:
            assert isinstance(gate, ApprovalGate)
            assert gate.gate_type != ""
            assert isinstance(gate.approver_id, uuid.UUID)

    def test_skill_assignments_exist(self):
        """Demo has skill assignments for agents."""
        demo = setup_demo_company()

        assert len(demo.skill_assignments) > 0
        # Each assignment references a valid agent
        agent_ids = {a.agent_id for a in demo.agents.values()}
        for assignment in demo.skill_assignments:
            assert assignment.agent_id in agent_ids
            assert assignment.skill_name != ""
            assert 0.0 <= assignment.proficiency <= 1.0

    def test_tool_permissions_exist(self):
        """Demo has tool permissions for agents."""
        demo = setup_demo_company()

        assert len(demo.tool_permissions) > 0
        agent_ids = {a.agent_id for a in demo.agents.values()}
        for perm in demo.tool_permissions:
            assert perm.agent_id in agent_ids
            assert perm.tool_name != ""
            assert perm.access_level in ("read", "write", "execute")

    def test_idempotency_same_structure(self):
        """Calling setup_demo_company twice returns the same instance."""
        demo1 = setup_demo_company()
        demo2 = setup_demo_company()

        assert demo1 is demo2
        assert demo1.company_id == demo2.company_id
        assert demo1.agents.keys() == demo2.agents.keys()

    def test_idempotency_deterministic_ids(self):
        """Agent IDs are deterministic across calls."""
        demo1 = setup_demo_company()
        atlas_id = demo1.agents["Atlas"].agent_id

        reset_demo_company()
        demo2 = setup_demo_company()

        assert demo2.agents["Atlas"].agent_id == atlas_id

    def test_reset_allows_fresh_creation(self):
        """reset_demo_company allows a fresh setup."""
        demo1 = setup_demo_company()
        reset_demo_company()
        demo2 = setup_demo_company()

        # Should be a different object but same structure
        assert demo1 is not demo2
        assert demo1.company_id == demo2.company_id


class TestDemoScenarios:
    """Test pre-defined demo scenarios."""

    def test_scenarios_has_three_entries(self):
        """SCENARIOS list contains exactly 3 scenarios."""
        assert len(SCENARIOS) == 3

    def test_each_scenario_has_objective(self):
        """Every scenario has a non-empty objective."""
        for scenario in SCENARIOS:
            assert isinstance(scenario, Scenario)
            assert scenario.objective != ""
            assert len(scenario.objective) > 10

    def test_each_scenario_has_delegation_path(self):
        """Every scenario has a non-empty expected_delegation_path."""
        for scenario in SCENARIOS:
            assert len(scenario.expected_delegation_path) >= 2

    def test_each_scenario_has_success_criteria(self):
        """Every scenario has non-empty success_criteria."""
        for scenario in SCENARIOS:
            assert len(scenario.success_criteria) >= 2
            for criterion in scenario.success_criteria:
                assert criterion != ""

    def test_scenario_1_delegation_path(self):
        """Build REST API scenario has correct delegation chain."""
        scenario = SCENARIOS[0]
        assert scenario.name == "Build a REST API"
        assert scenario.expected_delegation_path == ["CEO", "CTO", "Forge", "Shield"]

    def test_scenario_2_delegation_path(self):
        """Fix a bug scenario has correct short delegation chain."""
        scenario = SCENARIOS[1]
        assert scenario.name == "Fix a bug"
        assert scenario.expected_delegation_path == ["CTO", "Forge"]

    def test_scenario_3_delegation_path(self):
        """Research scenario has correct multi-agent delegation path."""
        scenario = SCENARIOS[2]
        assert scenario.name == "Research and propose architecture"
        assert scenario.expected_delegation_path == ["CEO", "CTO", "Nova", "CEO"]

    def test_get_scenario_by_id(self):
        """get_scenario retrieves correct scenario by ID."""
        scenario = get_scenario("scenario_1")
        assert scenario is not None
        assert scenario.name == "Build a REST API"

    def test_get_scenario_unknown_returns_none(self):
        """get_scenario returns None for unknown ID."""
        result = get_scenario("nonexistent_scenario")
        assert result is None

    def test_list_scenario_names(self):
        """list_scenario_names returns all scenario names."""
        names = list_scenario_names()
        assert "Build a REST API" in names
        assert "Fix a bug" in names
        assert "Research and propose architecture" in names
        assert len(names) == 3

    def test_scenarios_have_estimated_costs(self):
        """Each scenario has a positive estimated cost."""
        for scenario in SCENARIOS:
            assert scenario.estimated_cost_cents > 0

    def test_scenarios_have_metadata(self):
        """Each scenario has metadata with complexity and tags."""
        for scenario in SCENARIOS:
            assert "complexity" in scenario.metadata
            assert "tags" in scenario.metadata
            assert len(scenario.metadata["tags"]) > 0

    def test_scenarios_have_unique_ids(self):
        """Each scenario has a unique scenario_id."""
        ids = [s.scenario_id for s in SCENARIOS]
        assert len(ids) == len(set(ids))
