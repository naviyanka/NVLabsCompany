"""Improvement Proposer - generates evolution proposals from analysis data.

Creates structured proposals for skill improvements, workflow changes,
agent configuration changes, and organizational restructuring. All proposals
include impact estimates, confidence levels, risk assessments, and cost estimates.
"""

import uuid
from datetime import datetime, timezone
from typing import Any


class ImprovementProposer:
    """Generates improvement proposals based on analysis results.

    All proposals are auditable with proposer identity, timestamp, and full
    rationale. Proposals are structured as dicts matching EvolutionProposal fields.
    """

    def __init__(self, db: Any = None) -> None:
        """Initialize the proposer.

        Args:
            db: Optional async database session for persistence.
        """
        self.db = db

    def propose_skill_improvement(
        self,
        company_id: uuid.UUID,
        skill_id: uuid.UUID,
        failure_analysis: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Generate a proposal to improve a skill based on failure analysis.

        Args:
            company_id: The company owning the skill.
            skill_id: The skill to improve.
            failure_analysis: Results from FailureAnalyzer.root_cause_analysis.

        Returns:
            Proposal dict with type, title, description, expected_impact,
            confidence, risk_level, estimated_cost_cents, proposed_by, proposed_at.
        """
        # Determine severity based on failure frequency
        total_failures = sum(f.get("occurrence_count", 0) for f in failure_analysis)
        top_issue = failure_analysis[0] if failure_analysis else {}

        # Higher failure count = higher confidence that improvement is needed
        confidence = min(0.9, 0.3 + (total_failures * 0.05))

        # Risk is low for prompt changes, medium for tool changes
        risk_level = "low"
        if any(f.get("factor_type") == "tool_used" for f in failure_analysis):
            risk_level = "medium"

        description = (
            f"Skill improvement needed based on {total_failures} failures. "
            f"Primary factor: {top_issue.get('factor_type', 'unknown')} = "
            f"{top_issue.get('factor_value', 'unknown')} "
            f"({top_issue.get('percentage', 0):.1f}% of failures)."
        )

        return {
            "proposal_type": "skill_improvement",
            "title": f"Improve skill {skill_id} based on failure analysis",
            "description": description,
            "expected_impact": f"Reduce failures by estimated {min(80, total_failures * 10)}%",
            "confidence": confidence,
            "risk_level": risk_level,
            "estimated_cost_cents": 500,  # Cost of re-evaluation
            "proposed_by": "evolution_engine",
            "proposed_at": datetime.now(timezone.utc).isoformat(),
            "company_id": str(company_id),
            "skill_id": str(skill_id),
        }

    def propose_workflow_change(
        self,
        company_id: uuid.UUID,
        bottleneck_analysis: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Propose workflow reordering or parallelism based on bottleneck analysis.

        Args:
            company_id: The company to optimize workflows for.
            bottleneck_analysis: Results from FailureAnalyzer.identify_bottlenecks.

        Returns:
            Proposal dict with workflow change details.
        """
        if not bottleneck_analysis:
            return {
                "proposal_type": "workflow_change",
                "title": "No bottlenecks detected",
                "description": "Current workflow appears optimal.",
                "expected_impact": "None",
                "confidence": 0.1,
                "risk_level": "low",
                "estimated_cost_cents": 0,
                "proposed_by": "evolution_engine",
                "proposed_at": datetime.now(timezone.utc).isoformat(),
                "company_id": str(company_id),
            }

        # Focus on the slowest stage
        slowest = bottleneck_analysis[0]
        total_time = sum(b.get("avg_duration", 0) for b in bottleneck_analysis)
        bottleneck_percent = (
            (slowest["avg_duration"] / total_time * 100) if total_time > 0 else 0
        )

        # Higher confidence if bottleneck dominates
        confidence = min(0.85, 0.4 + (bottleneck_percent / 200))

        description = (
            f"Stage '{slowest['stage']}' averages {slowest['avg_duration']:.1f}s "
            f"({bottleneck_percent:.0f}% of total time). "
            f"Propose parallelizing or reordering stages to reduce latency."
        )

        return {
            "proposal_type": "workflow_change",
            "title": f"Optimize workflow bottleneck in stage '{slowest['stage']}'",
            "description": description,
            "expected_impact": f"Reduce total execution time by ~{bottleneck_percent * 0.3:.0f}%",
            "confidence": confidence,
            "risk_level": "medium",
            "estimated_cost_cents": 200,
            "proposed_by": "evolution_engine",
            "proposed_at": datetime.now(timezone.utc).isoformat(),
            "company_id": str(company_id),
        }

    def propose_agent_config(
        self,
        company_id: uuid.UUID,
        agent_id: uuid.UUID,
        performance_data: dict[str, Any],
    ) -> dict[str, Any]:
        """Propose agent configuration changes based on performance data.

        Args:
            company_id: The company owning the agent.
            agent_id: The agent to reconfigure.
            performance_data: Performance metrics including quality, speed, cost.

        Returns:
            Proposal dict with agent config change details.
        """
        avg_quality = performance_data.get("avg_quality", 0.5)
        avg_cost = performance_data.get("avg_cost_cents", 100)
        avg_speed = performance_data.get("avg_duration_seconds", 30)

        # Determine what to optimize
        recommendations: list[str] = []
        if avg_quality < 0.7:
            recommendations.append("upgrade model for better quality")
        if avg_cost > 500:
            recommendations.append("reduce budget or switch to cheaper model")
        if avg_speed > 60:
            recommendations.append("optimize for speed with simpler prompts")

        if not recommendations:
            recommendations.append("maintain current configuration")

        confidence = 0.6 if recommendations else 0.3
        risk_level = "medium" if "upgrade model" in str(recommendations) else "low"

        description = (
            f"Agent performance: quality={avg_quality:.2f}, "
            f"cost={avg_cost} cents/task, speed={avg_speed:.1f}s. "
            f"Recommendations: {'; '.join(recommendations)}."
        )

        return {
            "proposal_type": "agent_config",
            "title": f"Optimize agent {agent_id} configuration",
            "description": description,
            "expected_impact": f"Improve underperforming metrics: {', '.join(recommendations)}",
            "confidence": confidence,
            "risk_level": risk_level,
            "estimated_cost_cents": 300,
            "proposed_by": "evolution_engine",
            "proposed_at": datetime.now(timezone.utc).isoformat(),
            "company_id": str(company_id),
            "agent_id": str(agent_id),
        }

    def propose_org_change(
        self,
        company_id: uuid.UUID,
        performance_data: dict[str, Any],
        org_structure: dict[str, Any],
    ) -> dict[str, Any]:
        """Propose organizational changes based on performance and structure.

        Args:
            company_id: The company to restructure.
            performance_data: Overall company performance metrics.
            org_structure: Current organizational structure (agents, teams, roles).

        Returns:
            Proposal dict with org change details.
        """
        agent_count = len(org_structure.get("agents", []))
        overloaded_agents = [
            a for a in org_structure.get("agents", [])
            if a.get("task_count", 0) > a.get("capacity", 10)
        ]
        underutilized_agents = [
            a for a in org_structure.get("agents", [])
            if a.get("task_count", 0) < a.get("capacity", 10) * 0.3
        ]

        recommendations: list[str] = []
        if overloaded_agents:
            recommendations.append(
                f"Add agent to handle overflow from {len(overloaded_agents)} overloaded agents"
            )
        if underutilized_agents:
            recommendations.append(
                f"Consider merging {len(underutilized_agents)} underutilized agents"
            )
        if not recommendations:
            recommendations.append("Current structure appears balanced")

        confidence = 0.5 + (len(overloaded_agents) * 0.1)
        confidence = min(confidence, 0.85)

        risk_level = "high" if overloaded_agents or underutilized_agents else "low"

        description = (
            f"Organization has {agent_count} agents. "
            f"{len(overloaded_agents)} overloaded, {len(underutilized_agents)} underutilized. "
            f"Recommendations: {'; '.join(recommendations)}."
        )

        return {
            "proposal_type": "org_change",
            "title": f"Organizational restructuring for company {company_id}",
            "description": description,
            "expected_impact": f"Balance workload across agents: {'; '.join(recommendations)}",
            "confidence": confidence,
            "risk_level": risk_level,
            "estimated_cost_cents": 1000,
            "proposed_by": "evolution_engine",
            "proposed_at": datetime.now(timezone.utc).isoformat(),
            "company_id": str(company_id),
        }
