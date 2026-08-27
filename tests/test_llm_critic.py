"""Tests for the LLM-enhanced Critic Evaluator module.

Validates LLMCriticEvaluator evaluation using mocked LLM callables,
including fallback behavior, caching, threshold determination, and
custom prompt templates.
"""

import json
import uuid
from unittest.mock import AsyncMock

import pytest

from nexus.orchestration.llm_critic import LLMCriticEvaluator, make_critic
from nexus.orchestration.critic import (
    CriticEvaluator,
    EvaluationCriteria,
    EvaluationResult,
)


@pytest.fixture
def task_id():
    """Provide a fixed task UUID for tests."""
    return uuid.UUID("99999999-9999-9999-9999-999999999999")


@pytest.fixture
def default_criteria():
    """Provide the default criteria list."""
    return [
        EvaluationCriteria(
            name="completeness",
            description="Whether the output addresses all parts of the task",
            weight=0.4,
        ),
        EvaluationCriteria(
            name="correctness",
            description="Whether the output is factually and logically correct",
            weight=0.4,
        ),
        EvaluationCriteria(
            name="quality",
            description="Overall quality of the output (clarity, structure)",
            weight=0.2,
        ),
    ]


class TestLLMCriticEvaluatorEvaluation:
    """Tests for LLMCriticEvaluator.evaluate() with mocked LLM."""

    async def test_successful_evaluation(self, task_id):
        """Test successful evaluation with valid LLM scores."""
        responses = [
            json.dumps({"score": 0.9, "reasoning": "Very complete"}),
            json.dumps({"score": 0.85, "reasoning": "Mostly correct"}),
            json.dumps({"score": 0.8, "reasoning": "Good quality"}),
        ]
        mock_llm = AsyncMock(side_effect=responses)

        evaluator = LLMCriticEvaluator(llm_callable=mock_llm)
        result = await evaluator.evaluate(
            task_id,
            "Write a summary",
            "This is a detailed summary of the topic.",
            {"source": "test"},
        )

        assert isinstance(result, EvaluationResult)
        assert result.task_id == task_id
        assert result.passed is True
        # Weighted: 0.9*0.4 + 0.85*0.4 + 0.8*0.2 = 0.36 + 0.34 + 0.16 = 0.86
        assert abs(result.score - 0.86) < 0.01
        assert result.criteria_scores["completeness"] == 0.9
        assert result.criteria_scores["correctness"] == 0.85
        assert result.criteria_scores["quality"] == 0.8
        assert mock_llm.call_count == 3

    async def test_fallback_on_invalid_json(self, task_id):
        """Test fallback to heuristic when LLM returns invalid JSON."""
        mock_llm = AsyncMock(return_value="Not valid JSON")

        evaluator = LLMCriticEvaluator(llm_callable=mock_llm)
        result = await evaluator.evaluate(
            task_id,
            "Write a summary",
            "This is a result with enough content to pass heuristic checks.",
        )

        # Should still produce a valid result via fallback
        assert isinstance(result, EvaluationResult)
        assert result.task_id == task_id
        assert 0.0 <= result.score <= 1.0

    async def test_fallback_on_exception(self, task_id):
        """Test fallback when LLM callable raises an exception."""
        mock_llm = AsyncMock(side_effect=RuntimeError("LLM service down"))

        evaluator = LLMCriticEvaluator(llm_callable=mock_llm)
        result = await evaluator.evaluate(
            task_id,
            "Write a summary",
            "Result content here.",
        )

        # Should still produce a valid result via fallback
        assert isinstance(result, EvaluationResult)
        assert result.task_id == task_id
        assert 0.0 <= result.score <= 1.0

    async def test_caching_prevents_duplicate_calls(self, task_id):
        """Test that caching prevents redundant LLM calls for same task+result."""
        responses = [
            json.dumps({"score": 0.9, "reasoning": "Complete"}),
            json.dumps({"score": 0.85, "reasoning": "Correct"}),
            json.dumps({"score": 0.8, "reasoning": "Quality"}),
        ]
        mock_llm = AsyncMock(side_effect=responses)

        evaluator = LLMCriticEvaluator(llm_callable=mock_llm)

        # First call should invoke the LLM
        result1 = await evaluator.evaluate(
            task_id, "Write a summary", "Same result content"
        )
        assert mock_llm.call_count == 3

        # Second call with same task_id and result should use cache
        result2 = await evaluator.evaluate(
            task_id, "Write a summary", "Same result content"
        )
        # No additional LLM calls
        assert mock_llm.call_count == 3

        # Results should be identical
        assert result1.score == result2.score
        assert result1.criteria_scores == result2.criteria_scores

    async def test_quality_threshold_pass(self, task_id):
        """Test that results above quality threshold pass."""
        responses = [
            json.dumps({"score": 0.9, "reasoning": "Great"}),
            json.dumps({"score": 0.9, "reasoning": "Great"}),
            json.dumps({"score": 0.9, "reasoning": "Great"}),
        ]
        mock_llm = AsyncMock(side_effect=responses)

        evaluator = LLMCriticEvaluator(
            llm_callable=mock_llm, quality_threshold=0.8
        )
        result = await evaluator.evaluate(
            task_id, "Write something", "Excellent result"
        )

        assert result.passed is True
        assert result.score >= 0.8

    async def test_quality_threshold_fail(self, task_id):
        """Test that results below quality threshold fail."""
        responses = [
            json.dumps({"score": 0.3, "reasoning": "Incomplete"}),
            json.dumps({"score": 0.4, "reasoning": "Errors found"}),
            json.dumps({"score": 0.2, "reasoning": "Poor quality"}),
        ]
        mock_llm = AsyncMock(side_effect=responses)

        evaluator = LLMCriticEvaluator(
            llm_callable=mock_llm, quality_threshold=0.7
        )
        result = await evaluator.evaluate(
            task_id, "Write something", "Poor result"
        )

        assert result.passed is False
        # Weighted: 0.3*0.4 + 0.4*0.4 + 0.2*0.2 = 0.12 + 0.16 + 0.04 = 0.32
        assert result.score < 0.7

    async def test_custom_prompt_templates(self, task_id):
        """Test that custom prompt templates per criterion are used."""
        custom_templates = {
            "completeness": "Custom completeness: {task_description} | {criterion_name} | {criterion_description} | {result} | {context}",
        }
        responses = [
            json.dumps({"score": 0.85, "reasoning": "Custom eval"}),
            json.dumps({"score": 0.8, "reasoning": "Default eval"}),
            json.dumps({"score": 0.75, "reasoning": "Default eval"}),
        ]
        mock_llm = AsyncMock(side_effect=responses)

        evaluator = LLMCriticEvaluator(
            llm_callable=mock_llm, prompt_templates=custom_templates
        )
        await evaluator.evaluate(
            task_id, "Test task", "Test result", {"key": "val"}
        )

        # First call should use custom template (completeness)
        first_call_prompt = mock_llm.call_args_list[0][0][0]
        assert first_call_prompt.startswith("Custom completeness:")
        assert "Test task" in first_call_prompt

        # Second call should use default template (correctness)
        second_call_prompt = mock_llm.call_args_list[1][0][0]
        assert "You are a quality evaluator" in second_call_prompt

    async def test_invalid_score_range_triggers_fallback(self, task_id):
        """Test that a score outside [0, 1] triggers fallback."""
        mock_llm = AsyncMock(
            return_value=json.dumps({"score": 1.5, "reasoning": "Too high"})
        )

        evaluator = LLMCriticEvaluator(llm_callable=mock_llm)
        result = await evaluator.evaluate(
            task_id, "Write something", "Some result content here."
        )

        # Should fall back to heuristic
        assert isinstance(result, EvaluationResult)
        assert 0.0 <= result.score <= 1.0

    async def test_different_results_not_cached_together(self, task_id):
        """Test that different results produce separate cache entries."""
        responses = [
            json.dumps({"score": 0.9, "reasoning": "Great"}),
            json.dumps({"score": 0.9, "reasoning": "Great"}),
            json.dumps({"score": 0.9, "reasoning": "Great"}),
            json.dumps({"score": 0.5, "reasoning": "OK"}),
            json.dumps({"score": 0.5, "reasoning": "OK"}),
            json.dumps({"score": 0.5, "reasoning": "OK"}),
        ]
        mock_llm = AsyncMock(side_effect=responses)

        evaluator = LLMCriticEvaluator(llm_callable=mock_llm)

        result1 = await evaluator.evaluate(
            task_id, "Task", "Result A"
        )
        result2 = await evaluator.evaluate(
            task_id, "Task", "Result B"
        )

        # Both should call LLM (different results)
        assert mock_llm.call_count == 6
        assert result1.score != result2.score

    async def test_custom_criteria(self, task_id):
        """Test evaluation with custom criteria list."""
        custom_criteria = [
            EvaluationCriteria(name="accuracy", description="Is it accurate?", weight=1.0),
        ]
        mock_llm = AsyncMock(
            return_value=json.dumps({"score": 0.75, "reasoning": "Accurate"})
        )

        evaluator = LLMCriticEvaluator(
            llm_callable=mock_llm, criteria=custom_criteria
        )
        result = await evaluator.evaluate(
            task_id, "Check accuracy", "Accurate result"
        )

        assert result.criteria_scores["accuracy"] == 0.75
        assert result.score == 0.75
        assert mock_llm.call_count == 1


class TestDefaultCriticSelection:
    """Tests for make_critic() — the LLM critic is the default gate."""

    def test_llm_critic_is_default(self):
        """A model is available, so the LLM critic is chosen."""
        critic = make_critic(llm_callable=AsyncMock())
        assert isinstance(critic, LLMCriticEvaluator)

    def test_heuristic_when_no_model_available(self):
        """No llm_callable means no model, so the heuristic is used."""
        critic = make_critic(llm_callable=None)
        assert isinstance(critic, CriticEvaluator)

    def test_heuristic_by_explicit_config(self):
        """use_llm=False explicitly selects the heuristic critic."""
        critic = make_critic(llm_callable=AsyncMock(), use_llm=False)
        assert isinstance(critic, CriticEvaluator)


class TestStructuredVerdict:
    """Tests for the structured {verdict, reason, scores} judge output."""

    async def test_pass_verdict(self, task_id):
        """A passing evaluation reports verdict 'pass'."""
        responses = [
            json.dumps({"verdict": "pass", "score": 0.9, "reason": "Complete"}),
            json.dumps({"verdict": "pass", "score": 0.9, "reason": "Correct"}),
            json.dumps({"verdict": "pass", "score": 0.9, "reason": "Clear"}),
        ]
        evaluator = LLMCriticEvaluator(llm_callable=AsyncMock(side_effect=responses))
        result = await evaluator.evaluate(task_id, "Task", "Good result")

        assert result.verdict == "pass"
        assert result.passed is True

    async def test_fail_verdict_rejects_trivial_output(self, task_id):
        """A trivially incomplete output is rejected where the heuristic passes it.

        The heuristic critic scores a long-but-empty string above the
        threshold on length alone; the LLM judge rejects it.
        """
        trivial = "TODO. " * 40  # long enough for the heuristic to pass

        heuristic = CriticEvaluator(quality_threshold=0.7)
        heuristic_result = await heuristic.evaluate(task_id, "Write a summary", trivial)
        assert heuristic_result.passed is True

        responses = [
            json.dumps({"verdict": "fail", "score": 0.1, "reason": "No content"}),
            json.dumps({"verdict": "fail", "score": 0.1, "reason": "Not correct"}),
            json.dumps({"verdict": "fail", "score": 0.1, "reason": "Placeholder"}),
        ]
        llm = LLMCriticEvaluator(
            llm_callable=AsyncMock(side_effect=responses), quality_threshold=0.7
        )
        llm_result = await llm.evaluate(task_id, "Write a summary", trivial)

        assert llm_result.passed is False
        assert llm_result.verdict == "fail"


class TestJudgeFailureHandling:
    """Tests for fail-open and the consecutive-parse-failure cap."""

    async def test_judge_error_fails_open_to_continue(self, task_id):
        """A single judge error fails open rather than blocking the run."""
        evaluator = LLMCriticEvaluator(
            llm_callable=AsyncMock(side_effect=RuntimeError("judge down"))
        )
        result = await evaluator.evaluate(task_id, "Task", "Some output")

        assert result.verdict == "continue"
        assert result.passed is True

    async def test_third_consecutive_failure_pauses(self, task_id):
        """A deliberately broken judge pauses instead of spinning."""
        evaluator = LLMCriticEvaluator(
            llm_callable=AsyncMock(return_value="not json at all"),
            max_consecutive_parse_failures=3,
        )

        verdicts = []
        for i in range(3):
            result = await evaluator.evaluate(task_id, "Task", f"Output {i}")
            verdicts.append(result.verdict)

        assert verdicts == ["continue", "continue", "paused"]

    async def test_success_resets_failure_counter(self, task_id):
        """A successful evaluation resets the consecutive failure count."""
        good = json.dumps({"verdict": "pass", "score": 0.9, "reason": "ok"})
        responses = [
            "broken", "broken", "broken",  # attempt 1 — all criteria fail
            "broken", "broken", "broken",  # attempt 2 — all criteria fail
            good, good, good,              # attempt 3 — judge recovers
            "broken", "broken", "broken",  # attempt 4 — fails again
        ]
        evaluator = LLMCriticEvaluator(
            llm_callable=AsyncMock(side_effect=responses),
            max_consecutive_parse_failures=3,
        )

        assert (await evaluator.evaluate(task_id, "T", "o1")).verdict == "continue"
        assert (await evaluator.evaluate(task_id, "T", "o2")).verdict == "continue"
        assert (await evaluator.evaluate(task_id, "T", "o3")).verdict == "pass"
        # Counter was reset, so this is failure 1 of 3 — not a pause.
        assert (await evaluator.evaluate(task_id, "T", "o4")).verdict == "continue"
