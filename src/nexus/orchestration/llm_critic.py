"""LLM-enhanced Critic Evaluator - uses LLM for intelligent quality evaluation."""

import hashlib
import json
import uuid
from typing import Any, Callable, Awaitable

from nexus.orchestration.critic import (
    CriticEvaluator,
    EvaluationCriteria,
    EvaluationResult,
)


DEFAULT_CRITERION_PROMPT = """You are a quality evaluator. Evaluate the following task result against the criterion described below.

Task description: {task_description}
Criterion: {criterion_name} - {criterion_description}
Result to evaluate:
{result}

Context: {context}

Evaluate how well the result satisfies the criterion on a scale from 0.0 (worst) to 1.0 (best).

Output ONLY a JSON object with:
- "verdict": "pass" or "fail"
- "score": a float between 0.0 and 1.0
- "reason": a brief explanation of the score

Example output:
{{"verdict": "pass", "score": 0.85, "reason": "The result addresses most aspects of the criterion with minor gaps."}}
"""


class LLMCriticEvaluator:
    """Evaluator that uses an LLM for intelligent quality assessment.

    Uses a configurable LLM callable to evaluate task results against
    quality criteria. Falls back gracefully to the existing heuristic-based
    CriticEvaluator when the LLM call fails or returns invalid output.

    Caches evaluation results by (task_id, hash(result), criterion_name)
    to avoid redundant LLM calls.

    Attributes:
        llm_callable: Async function that takes a prompt string and returns a response string.
        quality_threshold: Minimum composite score to pass evaluation.
        criteria: List of evaluation criteria to assess.
        prompt_templates: Dict of prompt templates keyed by criterion name.
    """

    def __init__(
        self,
        llm_callable: Callable[[str], Awaitable[str]],
        quality_threshold: float = 0.7,
        criteria: list[EvaluationCriteria] | None = None,
        prompt_templates: dict[str, str] | None = None,
        max_consecutive_parse_failures: int = 3,
    ) -> None:
        """Initialize the LLM-enhanced critic evaluator.

        Args:
            llm_callable: Async function that accepts a prompt string and returns a response string.
            quality_threshold: Minimum score (0-1) to pass evaluation (default 0.7).
            criteria: Optional list of evaluation criteria. Uses defaults if None.
            prompt_templates: Optional dict of prompt templates keyed by criterion name.
                             Each template should have {task_description}, {criterion_name},
                             {criterion_description}, {result}, and {context} placeholders.
            max_consecutive_parse_failures: Consecutive judge failures tolerated
                before evaluate() returns verdict "paused" so the caller stops
                rather than spinning on a broken judge.
        """
        self._llm_callable = llm_callable
        self._quality_threshold = quality_threshold
        self._max_consecutive_parse_failures = max_consecutive_parse_failures
        self._consecutive_parse_failures = 0
        self._criteria = criteria or [
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
        self._prompt_templates = prompt_templates or {}
        self._cache: dict[tuple[str, str, str], float] = {}
        self._fallback_evaluator = CriticEvaluator(
            quality_threshold=quality_threshold,
            criteria=self._criteria,
        )

    @property
    def quality_threshold(self) -> float:
        """Get the configured quality threshold."""
        return self._quality_threshold

    async def evaluate(
        self,
        task_id: uuid.UUID,
        task_description: str,
        result: Any,
        context: dict[str, Any] | None = None,
    ) -> EvaluationResult:
        """Evaluate a task result against quality criteria using the LLM.

        Iterates over each criterion, calling _llm_evaluate_criterion() for
        each. Computes a weighted composite score and determines pass/fail.

        Args:
            task_id: The task that was evaluated.
            task_description: Description of what the task was supposed to do.
            result: The output produced by the task.
            context: Optional additional context for evaluation.

        Returns:
            An EvaluationResult with scores and pass/fail determination.
        """
        context = context or {}
        criteria_scores: dict[str, float] = {}
        feedback_parts: list[str] = []
        judge_failed = False

        for criterion in self._criteria:
            score, ok = await self._llm_evaluate_criterion(
                criterion, task_id, task_description, result, context
            )
            judge_failed = judge_failed or not ok
            criteria_scores[criterion.name] = score

        if judge_failed:
            self._consecutive_parse_failures += 1
        else:
            self._consecutive_parse_failures = 0

        # Compute weighted composite
        total_weight = sum(c.weight for c in self._criteria)
        if total_weight > 0:
            composite = sum(
                criteria_scores[c.name] * c.weight for c in self._criteria
            ) / total_weight
        else:
            composite = 0.0

        passed = composite >= self._quality_threshold

        # Judge error: fail open to "continue", or pause once the failure cap is hit.
        if judge_failed:
            if self._consecutive_parse_failures >= self._max_consecutive_parse_failures:
                return EvaluationResult(
                    task_id=task_id,
                    score=composite,
                    passed=True,
                    feedback=(
                        f"Judge unusable for {self._consecutive_parse_failures} "
                        f"consecutive evaluations — pausing quality gate."
                    ),
                    criteria_scores=criteria_scores,
                    verdict="paused",
                )
            return EvaluationResult(
                task_id=task_id,
                score=composite,
                passed=True,
                feedback="Judge error — quality gate failed open (heuristic fallback scores).",
                criteria_scores=criteria_scores,
                verdict="continue",
            )

        if passed:
            feedback_parts.append("Output meets quality threshold.")
        else:
            feedback_parts.append(
                f"Output below threshold ({composite:.2f} < {self._quality_threshold:.2f})."
            )
            low_criteria = [
                name for name, score in criteria_scores.items() if score < 0.5
            ]
            if low_criteria:
                feedback_parts.append(
                    f"Low-scoring criteria: {', '.join(low_criteria)}"
                )

        return EvaluationResult(
            task_id=task_id,
            score=composite,
            passed=passed,
            feedback=" ".join(feedback_parts),
            criteria_scores=criteria_scores,
            verdict="pass" if passed else "fail",
        )

    async def _llm_evaluate_criterion(
        self,
        criterion: EvaluationCriteria,
        task_id: uuid.UUID,
        task_description: str,
        result: Any,
        context: dict[str, Any],
    ) -> tuple[float, bool]:
        """Evaluate a single criterion using the LLM.

        Checks cache first, then calls the LLM. Caches successful results.
        Falls back to the heuristic-based CriticEvaluator on failure.

        Args:
            criterion: The criterion to evaluate.
            task_id: The task being evaluated.
            task_description: Task description for context.
            result: The output to evaluate.
            context: Additional context.

        Returns:
            Tuple of (score in 0.0-1.0, whether the LLM judge succeeded).
        """
        # Check cache
        result_hash = hashlib.sha256(str(result).encode()).hexdigest()
        cache_key = (str(task_id), result_hash, criterion.name)

        if cache_key in self._cache:
            return self._cache[cache_key], True

        try:
            # Get the prompt template for this criterion
            template = self._prompt_templates.get(
                criterion.name, DEFAULT_CRITERION_PROMPT
            )

            prompt = template.format(
                task_description=task_description,
                criterion_name=criterion.name,
                criterion_description=criterion.description,
                result=str(result),
                context=json.dumps(context, default=str),
            )

            response = await self._llm_callable(prompt)
            score = self._parse_criterion_response(response)

            # Cache successful result
            self._cache[cache_key] = score
            return score, True

        except Exception:
            # Fall back to heuristic evaluation
            fallback = await self._fallback_evaluator._evaluate_criterion(
                criterion, task_description, result, context
            )
            return fallback, False

    def _parse_criterion_response(self, response: str) -> float:
        """Parse the LLM response for a criterion evaluation.

        Args:
            response: Raw LLM response string (expected JSON with score and reasoning).

        Returns:
            Score float in [0.0, 1.0].

        Raises:
            ValueError: If the response cannot be parsed or score is invalid.
            json.JSONDecodeError: If the response is not valid JSON.
        """
        data = json.loads(response)

        if not isinstance(data, dict):
            raise ValueError("LLM response must be a JSON object")

        score = data.get("score")
        if score is None:
            raise ValueError("LLM response must include a 'score' field")

        score = float(score)
        if score < 0.0 or score > 1.0:
            raise ValueError(f"Score must be between 0.0 and 1.0, got {score}")

        return score


def make_critic(
    llm_callable: Callable[[str], Awaitable[str]] | None = None,
    quality_threshold: float = 0.7,
    use_llm: bool | None = None,
    criteria: list[EvaluationCriteria] | None = None,
) -> "LLMCriticEvaluator | CriticEvaluator":
    """Build the default quality gate.

    The LLM critic is the default. The heuristic CriticEvaluator is returned
    only when explicitly requested (use_llm=False) or when no model is
    available (llm_callable is None).

    Args:
        llm_callable: Async judge callable, or None if no model is available.
        quality_threshold: Minimum composite score to pass.
        use_llm: Explicit override. None means "use the LLM if available".
        criteria: Optional criteria list.

    Returns:
        An evaluator exposing .evaluate() and .quality_threshold.
    """
    if use_llm is False or llm_callable is None:
        return CriticEvaluator(
            quality_threshold=quality_threshold, criteria=criteria
        )
    return LLMCriticEvaluator(
        llm_callable=llm_callable,
        quality_threshold=quality_threshold,
        criteria=criteria,
    )
