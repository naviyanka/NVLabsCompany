"""Tests for the LLM Evolution Advisor module.

Validates LLMEvolutionAdvisor methods using mocked LLM callables,
including fallback behavior on exceptions, invalid JSON, and None-safe
operation when no LLM callable is provided.
"""

import json
import uuid
from unittest.mock import AsyncMock

import pytest

from nexus.evolution.ab_testing import ABTestFramework
from nexus.evolution.agent_evolution import AgentEvolution
from nexus.evolution.llm_evolution import LLMEvolutionAdvisor
from nexus.evolution.skill_evolution import SkillEvolution


@pytest.fixture
def agent_id():
    """Provide a fixed agent UUID for tests."""
    return uuid.UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")


@pytest.fixture
def skill_id():
    """Provide a fixed skill UUID for tests."""
    return uuid.UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")


@pytest.fixture
def performance_data():
    """Provide sample agent performance data."""
    return {
        "task_type_performance": {
            "summarization": {"gpt-4": 0.9, "gpt-3.5": 0.7},
            "coding": {"gpt-4": 0.85, "claude-3": 0.88},
        },
        "tool_usage_stats": {
            "search": {"usage_count": 20, "success_rate": 0.85, "avg_duration_ms": 300},
            "calculator": {"usage_count": 10, "success_rate": 0.2, "avg_duration_ms": 50},
            "unused_tool": {"usage_count": 0, "success_rate": 0.0, "avg_duration_ms": 0},
        },
        "cost_history": [100, 120, 110, 130, 125],
        "quality_history": [0.7, 0.72, 0.68, 0.75, 0.73],
    }


@pytest.fixture
def skill_performance_data():
    """Provide sample skill performance data."""
    return {
        "task_results": [
            {"score": 0.6},
            {"score": 0.55},
            {"score": 0.65},
            {"score": 0.58},
        ],
        "version_a": {
            "id": str(uuid.uuid4()),
            "version_number": 1,
            "performance_score": 0.55,
        },
        "version_b": {
            "id": str(uuid.uuid4()),
            "version_number": 2,
            "performance_score": 0.65,
        },
    }


class TestLLMEvolutionAdvisorAgentImprovements:
    """Tests for suggest_agent_improvements with mocked LLM."""

    async def test_suggest_agent_improvements_with_valid_llm_response(
        self, agent_id, performance_data
    ):
        """Test successful agent improvement suggestion with valid LLM JSON."""
        llm_response = json.dumps({
            "model_changes": {"summarization": "gpt-4", "coding": "claude-3"},
            "tool_additions": ["web_browser"],
            "tool_removals": ["calculator"],
            "budget_recommendation": "increase",
            "budget_amount_cents": 50,
            "rationale": "Higher quality models improve output for coding tasks",
            "confidence": 0.82,
        })
        mock_llm = AsyncMock(return_value=llm_response)

        advisor = LLMEvolutionAdvisor(llm_callable=mock_llm)
        result = await advisor.suggest_agent_improvements(agent_id, performance_data)

        assert result["source"] == "llm"
        assert result["model_changes"] == {"summarization": "gpt-4", "coding": "claude-3"}
        assert result["tool_additions"] == ["web_browser"]
        assert result["tool_removals"] == ["calculator"]
        assert result["budget_recommendation"] == "increase"
        assert result["budget_amount_cents"] == 50
        assert result["confidence"] == 0.82
        assert "rationale" in result

        mock_llm.assert_called_once()

    async def test_suggest_agent_improvements_fallback_on_exception(
        self, agent_id, performance_data
    ):
        """Test fallback to heuristic when LLM raises an exception."""
        mock_llm = AsyncMock(side_effect=RuntimeError("LLM service unavailable"))

        advisor = LLMEvolutionAdvisor(llm_callable=mock_llm)
        result = await advisor.suggest_agent_improvements(agent_id, performance_data)

        assert result["source"] == "heuristic"
        assert "model_changes" in result
        assert "tool_additions" in result
        assert "tool_removals" in result
        assert "budget_recommendation" in result
        assert "budget_amount_cents" in result
        assert "rationale" in result
        assert "confidence" in result

        # Verify heuristic used optimize_model_selection
        assert result["model_changes"]["summarization"] == "gpt-4"
        assert result["model_changes"]["coding"] == "claude-3"

    async def test_suggest_agent_improvements_fallback_on_invalid_json(
        self, agent_id, performance_data
    ):
        """Test fallback when LLM returns invalid JSON."""
        mock_llm = AsyncMock(return_value="This is not valid JSON")

        advisor = LLMEvolutionAdvisor(llm_callable=mock_llm)
        result = await advisor.suggest_agent_improvements(agent_id, performance_data)

        assert result["source"] == "heuristic"
        assert "model_changes" in result

    async def test_suggest_agent_improvements_fallback_on_missing_fields(
        self, agent_id, performance_data
    ):
        """Test fallback when LLM returns JSON with missing fields."""
        llm_response = json.dumps({
            "model_changes": {"summarization": "gpt-4"},
            # Missing other required fields
        })
        mock_llm = AsyncMock(return_value=llm_response)

        advisor = LLMEvolutionAdvisor(llm_callable=mock_llm)
        result = await advisor.suggest_agent_improvements(agent_id, performance_data)

        assert result["source"] == "heuristic"


class TestLLMEvolutionAdvisorSkillImprovements:
    """Tests for suggest_skill_improvements with mocked LLM."""

    async def test_suggest_skill_improvements_with_valid_llm_response(
        self, skill_id, skill_performance_data
    ):
        """Test successful skill improvement suggestion with valid LLM JSON."""
        llm_response = json.dumps({
            "prompt_rewrites": [
                {
                    "original_pattern": "Summarize the text",
                    "suggested_replacement": "Provide a concise summary focusing on key insights",
                }
            ],
            "parameter_changes": {"temperature": 0.3, "max_tokens": 500},
            "optimization_notes": [
                "Lower temperature improves consistency",
                "Increased max_tokens prevents truncation",
            ],
            "rationale": "Analysis shows truncation and inconsistency as primary failure modes",
            "confidence": 0.75,
        })
        mock_llm = AsyncMock(return_value=llm_response)

        advisor = LLMEvolutionAdvisor(llm_callable=mock_llm)
        result = await advisor.suggest_skill_improvements(skill_id, skill_performance_data)

        assert result["source"] == "llm"
        assert len(result["prompt_rewrites"]) == 1
        assert result["parameter_changes"]["temperature"] == 0.3
        assert len(result["optimization_notes"]) == 2
        assert result["confidence"] == 0.75
        assert "rationale" in result

        mock_llm.assert_called_once()

    async def test_suggest_skill_improvements_fallback_on_invalid_json(
        self, skill_id, skill_performance_data
    ):
        """Test fallback when LLM returns invalid JSON for skill improvements."""
        mock_llm = AsyncMock(return_value="not json {{{")

        advisor = LLMEvolutionAdvisor(llm_callable=mock_llm)
        result = await advisor.suggest_skill_improvements(skill_id, skill_performance_data)

        assert result["source"] == "heuristic"
        assert "prompt_rewrites" in result
        assert "parameter_changes" in result
        assert "optimization_notes" in result
        assert "rationale" in result
        assert "confidence" in result
        # Score is around 0.595, which is below 0.75 but above 0.5
        assert any("moderate" in note.lower() or "fine-tune" in note.lower()
                   for note in result["optimization_notes"])

    async def test_suggest_skill_improvements_fallback_on_exception(
        self, skill_id, skill_performance_data
    ):
        """Test fallback when LLM raises an exception for skill improvements."""
        mock_llm = AsyncMock(side_effect=ConnectionError("Network error"))

        advisor = LLMEvolutionAdvisor(llm_callable=mock_llm)
        result = await advisor.suggest_skill_improvements(skill_id, skill_performance_data)

        assert result["source"] == "heuristic"
        assert isinstance(result["optimization_notes"], list)
        assert len(result["optimization_notes"]) > 0


class TestLLMEvolutionAdvisorHypothesis:
    """Tests for generate_evolution_hypothesis."""

    async def test_generate_evolution_hypothesis_with_llm(self):
        """Test hypothesis generation with valid LLM response."""
        llm_response = json.dumps({
            "hypothesis": "Switching to GPT-4 for coding tasks improves accuracy by 15%",
            "metric": "accuracy",
            "baseline_mean": 0.72,
            "baseline_std": 0.08,
            "expected_effect": 0.108,
            "rationale": "GPT-4 has shown superior performance on code generation benchmarks",
        })
        mock_llm = AsyncMock(return_value=llm_response)

        advisor = LLMEvolutionAdvisor(llm_callable=mock_llm)
        context = {
            "performance_data": {"quality_history": [0.7, 0.72, 0.71, 0.73]},
            "agent_id": str(uuid.uuid4()),
        }
        result = await advisor.generate_evolution_hypothesis(context)

        assert result["source"] == "llm"
        assert result["hypothesis"] == "Switching to GPT-4 for coding tasks improves accuracy by 15%"
        assert result["metric"] == "accuracy"
        assert result["baseline_mean"] == 0.72
        assert result["baseline_std"] == 0.08
        assert result["expected_effect"] == 0.108
        assert "rationale" in result

        mock_llm.assert_called_once()

    async def test_generate_evolution_hypothesis_fallback(self):
        """Test heuristic hypothesis generation on LLM failure."""
        mock_llm = AsyncMock(side_effect=TimeoutError("LLM timed out"))

        context = {
            "performance_data": {"quality_history": [0.6, 0.65, 0.62, 0.64]},
        }
        advisor = LLMEvolutionAdvisor(llm_callable=mock_llm)
        result = await advisor.generate_evolution_hypothesis(context)

        assert result["source"] == "heuristic"
        assert "hypothesis" in result
        assert "metric" in result
        assert "baseline_mean" in result
        assert "baseline_std" in result
        assert "expected_effect" in result
        assert "rationale" in result

        # Verify heuristic uses the actual data
        assert abs(result["baseline_mean"] - 0.6275) < 0.01

    async def test_generate_evolution_hypothesis_fallback_no_data(self):
        """Test heuristic hypothesis generation with empty context."""
        mock_llm = AsyncMock(side_effect=Exception("failure"))

        advisor = LLMEvolutionAdvisor(llm_callable=mock_llm)
        result = await advisor.generate_evolution_hypothesis({})

        assert result["source"] == "heuristic"
        # Should use defaults
        assert result["baseline_mean"] == 0.7
        assert result["baseline_std"] == 0.15


class TestLLMEvolutionAdvisorValidateHypothesis:
    """Tests for validate_hypothesis integrating with ABTestFramework."""

    async def test_validate_hypothesis_improved(self):
        """Test hypothesis validation that shows improvement."""
        ab_framework = ABTestFramework()
        advisor = LLMEvolutionAdvisor(ab_framework=ab_framework)

        hypothesis = {
            "hypothesis": "New model improves accuracy",
            "metric": "accuracy",
        }
        # Control: lower scores, Treatment: higher scores
        control = [0.60, 0.62, 0.58, 0.61, 0.59, 0.63, 0.60, 0.62,
                   0.57, 0.61, 0.60, 0.59, 0.62, 0.58, 0.61, 0.60,
                   0.59, 0.63, 0.60, 0.58]
        treatment = [0.80, 0.82, 0.78, 0.81, 0.79, 0.83, 0.80, 0.82,
                     0.77, 0.81, 0.80, 0.79, 0.82, 0.78, 0.81, 0.80,
                     0.79, 0.83, 0.80, 0.78]

        result = await advisor.validate_hypothesis(hypothesis, control, treatment)

        assert result["hypothesis"] == "New model improves accuracy"
        assert result["metric"] == "accuracy"
        assert result["verdict"] == "improved"
        assert result["is_significant"] is True
        assert result["p_value"] < 0.05
        assert result["mean_difference"] > 0
        assert "confidence_interval" in result
        assert result["treatment_mean"] > result["control_mean"]

    async def test_validate_hypothesis_inconclusive(self):
        """Test hypothesis validation that is inconclusive."""
        ab_framework = ABTestFramework()
        advisor = LLMEvolutionAdvisor(ab_framework=ab_framework)

        hypothesis = {
            "hypothesis": "Change has no significant effect",
            "metric": "latency_ms",
        }
        # Very similar results (no significant difference)
        control = [100, 102, 99, 101, 100, 103, 98, 101, 100, 102]
        treatment = [101, 100, 102, 99, 101, 100, 103, 100, 101, 99]

        result = await advisor.validate_hypothesis(hypothesis, control, treatment)

        assert result["verdict"] == "inconclusive"
        assert result["is_significant"] is False
        assert result["p_value"] > 0.05

    async def test_validate_hypothesis_uses_ab_framework(self):
        """Test that validate_hypothesis delegates to ABTestFramework.run_test."""
        ab_framework = ABTestFramework()
        advisor = LLMEvolutionAdvisor(ab_framework=ab_framework)

        hypothesis = {"hypothesis": "test", "metric": "score"}
        control = [1.0, 2.0, 3.0, 4.0, 5.0]
        treatment = [2.0, 3.0, 4.0, 5.0, 6.0]

        result = await advisor.validate_hypothesis(hypothesis, control, treatment)

        # Verify the structure matches what ABTestFramework.run_test produces
        assert "verdict" in result
        assert "p_value" in result
        assert "effect_size" in result
        assert "confidence_interval" in result
        assert "control_mean" in result
        assert "treatment_mean" in result
        assert "mean_difference" in result
        assert "is_significant" in result


class TestLLMEvolutionAdvisorNoneSafe:
    """Tests for None-safe operation when no LLM callable is provided."""

    async def test_no_llm_suggest_agent_improvements(self, agent_id, performance_data):
        """Test agent improvements gracefully degrade without LLM."""
        advisor = LLMEvolutionAdvisor(llm_callable=None)
        result = await advisor.suggest_agent_improvements(agent_id, performance_data)

        assert result["source"] == "heuristic"
        assert "model_changes" in result
        assert "tool_additions" in result
        assert "tool_removals" in result
        assert "budget_recommendation" in result

    async def test_no_llm_suggest_skill_improvements(self, skill_id, skill_performance_data):
        """Test skill improvements gracefully degrade without LLM."""
        advisor = LLMEvolutionAdvisor(llm_callable=None)
        result = await advisor.suggest_skill_improvements(skill_id, skill_performance_data)

        assert result["source"] == "heuristic"
        assert "prompt_rewrites" in result
        assert "parameter_changes" in result
        assert "optimization_notes" in result

    async def test_no_llm_generate_hypothesis(self):
        """Test hypothesis generation gracefully degrades without LLM."""
        advisor = LLMEvolutionAdvisor(llm_callable=None)
        context = {"performance_data": {"quality_history": [0.8, 0.82, 0.79]}}
        result = await advisor.generate_evolution_hypothesis(context)

        assert result["source"] == "heuristic"
        assert "hypothesis" in result
        assert "metric" in result
        assert "baseline_mean" in result

    async def test_no_llm_validate_hypothesis(self):
        """Test hypothesis validation works without LLM (uses ABTestFramework directly)."""
        advisor = LLMEvolutionAdvisor(llm_callable=None)

        hypothesis = {"hypothesis": "test hypothesis", "metric": "accuracy"}
        control = [0.5, 0.6, 0.55, 0.58, 0.52]
        treatment = [0.7, 0.8, 0.75, 0.78, 0.72]

        result = await advisor.validate_hypothesis(hypothesis, control, treatment)

        # validate_hypothesis doesn't use LLM at all, it uses ABTestFramework
        assert "verdict" in result
        assert "p_value" in result
        assert result["hypothesis"] == "test hypothesis"
        assert result["metric"] == "accuracy"

    async def test_fully_default_initialization(self):
        """Test advisor works with all default parameters."""
        advisor = LLMEvolutionAdvisor()

        agent_id = uuid.uuid4()
        result = await advisor.suggest_agent_improvements(
            agent_id,
            {"task_type_performance": {}, "tool_usage_stats": {},
             "cost_history": [], "quality_history": []},
        )

        assert result["source"] == "heuristic"
        assert isinstance(result, dict)
