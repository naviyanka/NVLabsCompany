"""Tests for the LLM-enhanced Improvement Proposer module.

Validates LLMImprovementProposer proposal generation using mocked LLM callables,
including fallback behavior, implementation_steps validation, and heuristic fallback.
"""

import json
import uuid
from unittest.mock import AsyncMock

import pytest

from nexus.evolution.llm_proposer import LLMImprovementProposer
from nexus.evolution.proposer import ImprovementProposer


@pytest.fixture
def company_id():
    """Provide a fixed company UUID for tests."""
    return uuid.UUID("11111111-1111-1111-1111-111111111111")


@pytest.fixture
def valid_llm_response():
    """Provide a valid LLM JSON response for proposal generation."""
    return json.dumps({
        "proposal_type": "skill_improvement",
        "title": "Improve error handling in data extraction",
        "description": "Add retry logic and better error messages for data extraction failures",
        "expected_impact": "Reduce extraction failures by 40%",
        "confidence": 0.75,
        "risk_level": "low",
        "estimated_cost_cents": 300,
        "implementation_steps": [
            "Add retry decorator to extraction functions",
            "Improve error messages with context",
            "Add fallback extraction strategy",
        ],
    })


class TestLLMImprovementProposer:
    """Tests for LLMImprovementProposer.generate_proposal() with mocked LLM."""

    async def test_successful_proposal_generation(self, company_id, valid_llm_response):
        """Test successful proposal generation with valid LLM JSON response."""
        mock_llm = AsyncMock(return_value=valid_llm_response)

        proposer = LLMImprovementProposer(llm_callable=mock_llm)
        proposal = await proposer.generate_proposal(
            company_id, {"performance": "low", "failure_rate": 0.3}
        )

        assert proposal["proposal_type"] == "skill_improvement"
        assert proposal["title"] == "Improve error handling in data extraction"
        assert proposal["confidence"] == 0.75
        assert proposal["risk_level"] == "low"
        assert proposal["estimated_cost_cents"] == 300
        assert proposal["proposed_by"] == "llm_evolution_engine"
        assert proposal["company_id"] == str(company_id)
        assert "proposed_at" in proposal
        assert len(proposal["implementation_steps"]) == 3
        assert "Add retry decorator" in proposal["implementation_steps"][0]

        # Verify LLM was called
        mock_llm.assert_called_once()

    async def test_fallback_on_invalid_json(self, company_id):
        """Test fallback to heuristic when LLM returns invalid JSON."""
        mock_llm = AsyncMock(return_value="This is not valid JSON at all")

        proposer = LLMImprovementProposer(llm_callable=mock_llm)
        proposal = await proposer.generate_proposal(
            company_id, {"performance": "low"}
        )

        # Should fall back to heuristic proposal
        assert "proposal_type" in proposal
        assert "implementation_steps" in proposal
        assert isinstance(proposal["implementation_steps"], list)
        assert len(proposal["implementation_steps"]) > 0
        assert proposal["company_id"] == str(company_id)

    async def test_fallback_on_llm_exception(self, company_id):
        """Test fallback when LLM callable raises an exception."""
        mock_llm = AsyncMock(side_effect=RuntimeError("LLM service unavailable"))

        proposer = LLMImprovementProposer(llm_callable=mock_llm)
        proposal = await proposer.generate_proposal(
            company_id, {"performance": "low"}
        )

        # Should fall back to heuristic proposal
        assert "proposal_type" in proposal
        assert "implementation_steps" in proposal
        assert isinstance(proposal["implementation_steps"], list)
        assert len(proposal["implementation_steps"]) > 0

    async def test_implementation_steps_always_present(self, company_id):
        """Test that implementation_steps is always present in output regardless of path."""
        # Test with valid LLM response
        valid_response = json.dumps({
            "proposal_type": "workflow_change",
            "title": "Optimize pipeline",
            "description": "Reorder stages for better throughput",
            "expected_impact": "20% faster",
            "confidence": 0.8,
            "risk_level": "medium",
            "estimated_cost_cents": 500,
            "implementation_steps": ["Step 1", "Step 2"],
        })
        mock_llm = AsyncMock(return_value=valid_response)
        proposer = LLMImprovementProposer(llm_callable=mock_llm)
        proposal = await proposer.generate_proposal(company_id, {})
        assert "implementation_steps" in proposal
        assert isinstance(proposal["implementation_steps"], list)
        assert len(proposal["implementation_steps"]) > 0

        # Test with failed LLM (fallback path)
        mock_llm_fail = AsyncMock(side_effect=Exception("fail"))
        proposer_fail = LLMImprovementProposer(llm_callable=mock_llm_fail)
        proposal_fail = await proposer_fail.generate_proposal(company_id, {})
        assert "implementation_steps" in proposal_fail
        assert isinstance(proposal_fail["implementation_steps"], list)
        assert len(proposal_fail["implementation_steps"]) > 0

    async def test_with_explicit_fallback_proposer(self, company_id):
        """Test with an explicit fallback_proposer instance."""
        mock_llm = AsyncMock(side_effect=RuntimeError("LLM down"))
        fallback = ImprovementProposer()

        skill_id = uuid.uuid4()
        context = {
            "skill_id": str(skill_id),
            "failure_analysis": [
                {
                    "factor_type": "prompt",
                    "factor_value": "unclear instructions",
                    "occurrence_count": 5,
                    "percentage": 60.0,
                },
            ],
        }

        proposer = LLMImprovementProposer(
            llm_callable=mock_llm, fallback_proposer=fallback
        )
        proposal = await proposer.generate_proposal(company_id, context)

        # Should use the explicit fallback proposer
        assert proposal["proposal_type"] == "skill_improvement"
        assert proposal["company_id"] == str(company_id)
        assert "implementation_steps" in proposal
        assert isinstance(proposal["implementation_steps"], list)
        assert len(proposal["implementation_steps"]) > 0

    async def test_fallback_on_missing_implementation_steps(self, company_id):
        """Test fallback when LLM response is valid JSON but missing implementation_steps."""
        invalid_response = json.dumps({
            "proposal_type": "skill_improvement",
            "title": "Some improvement",
            "description": "Details",
            "expected_impact": "Better",
            "confidence": 0.7,
            "risk_level": "low",
            "estimated_cost_cents": 100,
            # Missing implementation_steps
        })
        mock_llm = AsyncMock(return_value=invalid_response)

        proposer = LLMImprovementProposer(llm_callable=mock_llm)
        proposal = await proposer.generate_proposal(company_id, {})

        # Should fall back due to missing required field
        assert "implementation_steps" in proposal
        assert isinstance(proposal["implementation_steps"], list)
        assert len(proposal["implementation_steps"]) > 0

    async def test_fallback_on_empty_implementation_steps(self, company_id):
        """Test fallback when LLM response has empty implementation_steps."""
        invalid_response = json.dumps({
            "proposal_type": "skill_improvement",
            "title": "Some improvement",
            "description": "Details",
            "expected_impact": "Better",
            "confidence": 0.7,
            "risk_level": "low",
            "estimated_cost_cents": 100,
            "implementation_steps": [],
        })
        mock_llm = AsyncMock(return_value=invalid_response)

        proposer = LLMImprovementProposer(llm_callable=mock_llm)
        proposal = await proposer.generate_proposal(company_id, {})

        # Should fall back due to empty implementation_steps
        assert "implementation_steps" in proposal
        assert isinstance(proposal["implementation_steps"], list)
        assert len(proposal["implementation_steps"]) > 0
