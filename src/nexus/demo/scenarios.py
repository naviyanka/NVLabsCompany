"""Demo Scenarios - pre-defined workflow demonstrations for NexusCorp.

Provides three scenarios that exercise different delegation patterns:
1. Build a REST API - full delegation chain (CEO -> CTO -> Engineers -> QA)
2. Fix a bug - single agent execution (CTO -> Senior Engineer)
3. Research and propose architecture - multi-agent collaboration

Each scenario defines an objective, expected delegation path, and success
criteria for validation.
"""

from dataclasses import dataclass, field
from typing import Any

from nexus.workflows.company_flow import CompanyWorkflow, WorkflowTrace


@dataclass
class Scenario:
    """A demo scenario configuration.

    Defines a complete scenario with its objective, expected execution
    path through the agent hierarchy, and criteria for determining
    success.

    Attributes:
        scenario_id: Unique identifier for this scenario.
        name: Human-readable scenario name.
        objective: The high-level objective to accomplish.
        description: Detailed description of what this scenario demonstrates.
        expected_delegation_path: Expected chain of agent roles involved.
        success_criteria: List of criteria that must be met for success.
        estimated_cost_cents: Estimated total cost for this scenario.
        metadata: Additional scenario metadata.
    """

    scenario_id: str = ""
    name: str = ""
    objective: str = ""
    description: str = ""
    expected_delegation_path: list[str] = field(default_factory=list)
    success_criteria: list[str] = field(default_factory=list)
    estimated_cost_cents: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)

    async def run_scenario(self, company_id: str) -> WorkflowTrace:
        """Execute this scenario as a CompanyWorkflow.

        Creates a CompanyWorkflow with the scenario's objective and
        executes it through the full delegation chain.

        Args:
            company_id: The company ID to run this scenario under.

        Returns:
            A WorkflowTrace capturing the complete execution history.
        """
        workflow = CompanyWorkflow(company_id=company_id)
        trace = await workflow.execute(
            objective=self.objective,
            estimated_cost_cents=self.estimated_cost_cents,
            metadata={
                "scenario_id": self.scenario_id,
                "scenario_name": self.name,
                "expected_path": self.expected_delegation_path,
                "success_criteria": self.success_criteria,
            },
        )
        return trace


# Pre-defined demo scenarios
SCENARIOS: list[Scenario] = [
    Scenario(
        scenario_id="scenario_1",
        name="Build a REST API",
        objective="Build a REST API with user authentication, CRUD endpoints, and rate limiting",
        description=(
            "Full delegation chain demonstration. The CEO receives the objective "
            "and creates a strategy, the CTO decomposes it into technical tasks, "
            "engineers implement the code, and QA validates the results."
        ),
        expected_delegation_path=["CEO", "CTO", "Forge", "Shield"],
        success_criteria=[
            "API endpoint created",
            "Tests pass",
            "QA approved",
        ],
        estimated_cost_cents=500,
        metadata={
            "complexity": "high",
            "estimated_duration_minutes": 30,
            "tags": ["api", "authentication", "crud", "rate-limiting"],
        },
    ),
    Scenario(
        scenario_id="scenario_2",
        name="Fix a bug",
        objective="Fix the authentication timeout bug in the session management module",
        description=(
            "Single agent execution demonstration. The CTO identifies the bug "
            "location and assigns it directly to the senior engineer for "
            "implementation. Minimal delegation chain for focused work."
        ),
        expected_delegation_path=["CTO", "Forge"],
        success_criteria=[
            "Bug identified",
            "Fix implemented",
            "No regression",
        ],
        estimated_cost_cents=100,
        metadata={
            "complexity": "medium",
            "estimated_duration_minutes": 10,
            "tags": ["bugfix", "authentication", "sessions"],
        },
    ),
    Scenario(
        scenario_id="scenario_3",
        name="Research and propose architecture",
        objective="Design microservices migration plan for the monolithic application",
        description=(
            "Multi-agent collaboration demonstration. The CEO initiates "
            "the research objective, the CTO leads the technical investigation "
            "with Nova performing deep research, and the results are "
            "reviewed by the CEO for final approval."
        ),
        expected_delegation_path=["CEO", "CTO", "Nova", "CEO"],
        success_criteria=[
            "Research complete",
            "Proposal documented",
            "CEO approved",
        ],
        estimated_cost_cents=300,
        metadata={
            "complexity": "high",
            "estimated_duration_minutes": 45,
            "tags": ["architecture", "microservices", "migration", "research"],
        },
    ),
]


def get_scenario(scenario_id: str) -> Scenario | None:
    """Retrieve a scenario by its ID.

    Args:
        scenario_id: The scenario identifier to look up.

    Returns:
        The Scenario if found, None otherwise.
    """
    for scenario in SCENARIOS:
        if scenario.scenario_id == scenario_id:
            return scenario
    return None


def list_scenario_names() -> list[str]:
    """Get the names of all available scenarios.

    Returns:
        List of scenario name strings.
    """
    return [s.name for s in SCENARIOS]
