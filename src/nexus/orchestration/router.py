"""Agent Router - matches tasks to the best available agent based on scoring."""

import uuid
from dataclasses import dataclass, field
from typing import Any


@dataclass
class AgentCandidate:
    """Represents an agent available for task routing.

    Attributes:
        agent_id: The agent's unique identifier.
        name: Display name.
        skills: List of skill identifiers the agent possesses.
        current_workload: Number of active tasks.
        max_concurrent: Maximum concurrent tasks this agent can handle.
        budget_remaining_cents: Remaining budget for this agent.
        performance_score: Historical performance metric (0.0 to 1.0).
        status: Current agent status.
    """

    agent_id: uuid.UUID = field(default_factory=uuid.uuid4)
    name: str = ""
    skills: list[str] = field(default_factory=list)
    current_workload: int = 0
    max_concurrent: int = 5
    budget_remaining_cents: int = 0
    performance_score: float = 0.5
    status: str = "idle"


@dataclass
class RoutingDecision:
    """The result of a routing decision.

    Attributes:
        agent_id: The selected agent's ID.
        score: The composite routing score.
        reasons: Human-readable explanation of the selection.
    """

    agent_id: uuid.UUID
    score: float
    reasons: list[str] = field(default_factory=list)


class AgentRouter:
    """Routes tasks to the best agent based on skills, workload, and budget.

    The router scores each candidate agent across multiple dimensions
    and selects the one with the highest composite score.
    """

    def __init__(
        self,
        skill_weight: float = 0.4,
        workload_weight: float = 0.25,
        performance_weight: float = 0.2,
        budget_weight: float = 0.15,
    ) -> None:
        """Initialize the router with scoring weights.

        Args:
            skill_weight: Weight for skill match score.
            workload_weight: Weight for available capacity score.
            performance_weight: Weight for historical performance.
            budget_weight: Weight for budget availability.
        """
        self._skill_weight = skill_weight
        self._workload_weight = workload_weight
        self._performance_weight = performance_weight
        self._budget_weight = budget_weight

    async def route_task(
        self,
        task_description: str,
        required_skills: list[str],
        estimated_cost_cents: int,
        available_agents: list[AgentCandidate],
    ) -> RoutingDecision | None:
        """Match a task to the best available agent.

        Scores each agent on skill match, workload availability,
        historical performance, and budget. Returns the agent with
        the highest composite score, or None if no agents qualify.

        Args:
            task_description: Description of the task to route.
            required_skills: Skills needed to complete the task.
            estimated_cost_cents: Estimated cost for the task.
            available_agents: List of candidate agents.

        Returns:
            A RoutingDecision for the best agent, or None if no match.
        """
        if not available_agents:
            return None

        scored: list[tuple[AgentCandidate, float, list[str]]] = []

        for agent in available_agents:
            if agent.status not in ("idle", "ready"):
                continue
            if agent.current_workload >= agent.max_concurrent:
                continue
            if estimated_cost_cents > 0 and agent.budget_remaining_cents < estimated_cost_cents:
                continue

            score, reasons = self._score_agent(
                agent, required_skills, estimated_cost_cents
            )
            scored.append((agent, score, reasons))

        if not scored:
            return None

        scored.sort(key=lambda x: x[1], reverse=True)
        best_agent, best_score, best_reasons = scored[0]

        return RoutingDecision(
            agent_id=best_agent.agent_id,
            score=best_score,
            reasons=best_reasons,
        )

    def _score_agent(
        self,
        agent: AgentCandidate,
        required_skills: list[str],
        estimated_cost_cents: int,
    ) -> tuple[float, list[str]]:
        """Compute the composite score for an agent.

        Args:
            agent: The candidate agent to score.
            required_skills: Skills required by the task.
            estimated_cost_cents: Estimated task cost.

        Returns:
            Tuple of (score, reasoning list).
        """
        reasons: list[str] = []

        # Skill match score
        if required_skills:
            matched = sum(1 for s in required_skills if s in agent.skills)
            skill_score = matched / len(required_skills)
        else:
            skill_score = 1.0
        reasons.append(f"skill_match={skill_score:.2f}")

        # Workload score (more capacity = higher score)
        capacity = agent.max_concurrent - agent.current_workload
        workload_score = min(capacity / max(agent.max_concurrent, 1), 1.0)
        reasons.append(f"workload_capacity={workload_score:.2f}")

        # Performance score
        performance_score = agent.performance_score
        reasons.append(f"performance={performance_score:.2f}")

        # Budget score
        if estimated_cost_cents > 0 and agent.budget_remaining_cents > 0:
            budget_score = min(
                agent.budget_remaining_cents / (estimated_cost_cents * 5), 1.0
            )
        else:
            budget_score = 1.0
        reasons.append(f"budget={budget_score:.2f}")

        composite = (
            skill_score * self._skill_weight
            + workload_score * self._workload_weight
            + performance_score * self._performance_weight
            + budget_score * self._budget_weight
        )

        return composite, reasons
