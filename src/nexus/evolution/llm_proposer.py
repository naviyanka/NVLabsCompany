"""LLM-enhanced Improvement Proposer - uses LLM for intelligent proposal generation.

Generates structured improvement proposals using an LLM callable with graceful
fallback to the heuristic-based ImprovementProposer on any failure.
"""

import json
import uuid
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable

from nexus.evolution.proposer import ImprovementProposer


DEFAULT_PROPOSAL_PROMPT = """You are an AI evolution engine. Generate an improvement proposal for a company.

Company ID: {company_id}
Context: {context}

Output a JSON object with the following fields:
- "proposal_type": one of "skill_improvement", "workflow_change", "agent_config", "org_change"
- "title": a concise title for the proposal
- "description": detailed description of the proposed change
- "expected_impact": expected outcome of implementing this proposal
- "confidence": a float between 0.0 and 1.0 indicating confidence
- "risk_level": one of "low", "medium", "high"
- "estimated_cost_cents": integer cost estimate in cents
- "implementation_steps": a list of strings describing concrete steps to implement the change

Rules:
- implementation_steps MUST be a non-empty list of actionable steps.
- Be specific and actionable in your recommendations.
- Output ONLY the JSON object, no additional text.

Example output:
{{
  "proposal_type": "skill_improvement",
  "title": "Improve error handling in data extraction",
  "description": "Add retry logic and better error messages for data extraction failures",
  "expected_impact": "Reduce extraction failures by 40%",
  "confidence": 0.75,
  "risk_level": "low",
  "estimated_cost_cents": 300,
  "implementation_steps": ["Add retry decorator to extraction functions", "Improve error messages with context", "Add fallback extraction strategy"]
}}
"""


class LLMImprovementProposer:
    """Generates improvement proposals using an LLM with heuristic fallback.

    Uses a configurable LLM callable to generate structured proposals.
    Falls back gracefully to the existing heuristic-based ImprovementProposer
    when the LLM call fails, returns unparseable output, or produces
    invalid data.

    Attributes:
        llm_callable: Async function that takes a prompt string and returns a response string.
        fallback_proposer: Optional ImprovementProposer instance for heuristic fallback.
    """

    def __init__(
        self,
        llm_callable: Callable[[str], Awaitable[str]],
        fallback_proposer: ImprovementProposer | None = None,
    ) -> None:
        """Initialize the LLM-enhanced improvement proposer.

        Args:
            llm_callable: Async function that accepts a prompt string and returns a response string.
            fallback_proposer: Optional ImprovementProposer for fallback behavior.
        """
        self._llm_callable = llm_callable
        self._fallback_proposer = fallback_proposer or ImprovementProposer()

    async def generate_proposal(
        self,
        company_id: uuid.UUID,
        context: dict[str, Any],
    ) -> dict[str, Any]:
        """Generate an improvement proposal using the LLM.

        Sends the company context to the LLM with a structured prompt,
        parses the JSON response into a proposal dict, and validates it.
        Falls back to a heuristic proposal if any step fails.

        Args:
            company_id: The company to generate a proposal for.
            context: Additional context including performance data, failures, etc.

        Returns:
            Proposal dict with proposal_type, title, description, expected_impact,
            confidence, risk_level, estimated_cost_cents, implementation_steps,
            proposed_by, proposed_at, and company_id.
        """
        try:
            prompt = DEFAULT_PROPOSAL_PROMPT.format(
                company_id=str(company_id),
                context=json.dumps(context, default=str),
            )
            response = await self._llm_callable(prompt)
            proposal = self._parse_llm_response(response, company_id)
            return proposal

        except Exception:
            return self._heuristic_fallback(company_id, context)

    def _parse_llm_response(
        self,
        response: str,
        company_id: uuid.UUID,
    ) -> dict[str, Any]:
        """Parse the LLM JSON response into a proposal dict.

        Args:
            response: Raw LLM response string (expected to be a JSON object).
            company_id: The company the proposal is for.

        Returns:
            Validated proposal dict with all required fields.

        Raises:
            ValueError: If the response cannot be parsed into a valid proposal.
            json.JSONDecodeError: If the response is not valid JSON.
        """
        data = json.loads(response)

        if not isinstance(data, dict):
            raise ValueError("LLM response must be a JSON object")

        # Validate required fields
        required_fields = [
            "proposal_type",
            "title",
            "description",
            "expected_impact",
            "confidence",
            "risk_level",
            "estimated_cost_cents",
            "implementation_steps",
        ]
        for field in required_fields:
            if field not in data:
                raise ValueError(f"Missing required field: {field}")

        # Validate implementation_steps is a non-empty list
        if not isinstance(data["implementation_steps"], list) or len(data["implementation_steps"]) == 0:
            raise ValueError("implementation_steps must be a non-empty list")

        # Validate types
        if not isinstance(data["confidence"], (int, float)):
            raise ValueError("confidence must be a number")
        if data["risk_level"] not in ("low", "medium", "high"):
            raise ValueError("risk_level must be low, medium, or high")

        # Build final proposal with metadata
        proposal: dict[str, Any] = {
            "proposal_type": data["proposal_type"],
            "title": data["title"],
            "description": data["description"],
            "expected_impact": data["expected_impact"],
            "confidence": float(data["confidence"]),
            "risk_level": data["risk_level"],
            "estimated_cost_cents": int(data["estimated_cost_cents"]),
            "implementation_steps": list(data["implementation_steps"]),
            "proposed_by": "llm_evolution_engine",
            "proposed_at": datetime.now(timezone.utc).isoformat(),
            "company_id": str(company_id),
        }

        return proposal

    def _heuristic_fallback(
        self,
        company_id: uuid.UUID,
        context: dict[str, Any],
    ) -> dict[str, Any]:
        """Generate a heuristic proposal when LLM fails.

        Uses the fallback proposer's skill improvement method if failure
        analysis is available in context, otherwise builds a generic proposal.

        Args:
            company_id: The company to generate a proposal for.
            context: Context data that may contain failure_analysis or performance_data.

        Returns:
            Proposal dict with implementation_steps always present.
        """
        failure_analysis = context.get("failure_analysis", [])
        skill_id = context.get("skill_id")

        if failure_analysis and skill_id:
            # Use the fallback proposer for structured analysis
            proposal = self._fallback_proposer.propose_skill_improvement(
                company_id=company_id,
                skill_id=uuid.UUID(str(skill_id)) if not isinstance(skill_id, uuid.UUID) else skill_id,
                failure_analysis=failure_analysis,
            )
        else:
            # Generate a generic improvement proposal
            proposal = {
                "proposal_type": "skill_improvement",
                "title": f"General improvement for company {company_id}",
                "description": "Heuristic-based improvement proposal generated as LLM fallback.",
                "expected_impact": "Incremental improvement in overall performance",
                "confidence": 0.4,
                "risk_level": "low",
                "estimated_cost_cents": 200,
                "proposed_by": "evolution_engine_heuristic",
                "proposed_at": datetime.now(timezone.utc).isoformat(),
                "company_id": str(company_id),
            }

        # Always ensure implementation_steps is present
        if "implementation_steps" not in proposal:
            proposal["implementation_steps"] = [
                "Analyze current performance metrics",
                "Identify top failure modes",
                "Apply targeted fixes to highest-impact issues",
                "Re-evaluate performance after changes",
            ]

        return proposal
