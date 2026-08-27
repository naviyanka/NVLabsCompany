"""Critic/Evaluator - evaluates task results for quality and correctness."""

import uuid
from dataclasses import dataclass, field
from typing import Any


@dataclass
class EvaluationResult:
    """The result of a critic evaluation on task output.

    Attributes:
        task_id: The task that was evaluated.
        score: Quality score from 0.0 (worst) to 1.0 (best).
        passed: Whether the result meets the quality threshold.
        feedback: Human-readable evaluation feedback.
        criteria_scores: Per-criterion breakdown of scores.
        verdict: Structured verdict - one of pass, fail, continue, paused.
            "continue" means the judge errored and the gate failed open.
            "paused" means the judge failed repeatedly and the caller
            should stop rather than spin.
    """

    task_id: uuid.UUID
    score: float
    passed: bool
    feedback: str = ""
    criteria_scores: dict[str, float] = field(default_factory=dict)
    verdict: str = "pass"


@dataclass
class EvaluationCriteria:
    """A single evaluation criterion.

    Attributes:
        name: Identifier for the criterion.
        description: What this criterion measures.
        weight: Relative weight in the composite score.
    """

    name: str
    description: str = ""
    weight: float = 1.0


class CriticEvaluator:
    """Evaluates task results against configurable quality criteria.

    The critic applies multiple evaluation criteria and computes a
    weighted composite score. Results below the quality threshold
    are marked as failing.
    """

    def __init__(
        self,
        quality_threshold: float = 0.7,
        criteria: list[EvaluationCriteria] | None = None,
    ) -> None:
        """Initialize the evaluator.

        Args:
            quality_threshold: Minimum score (0-1) to pass evaluation.
            criteria: List of evaluation criteria. Uses defaults if None.
        """
        self._quality_threshold = quality_threshold
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
        """Evaluate a task result against quality criteria.

        In a full implementation, this would invoke an LLM to assess
        quality. The default implementation provides a structural
        evaluation based on output presence and type.

        Args:
            task_id: The task that produced the result.
            task_description: Description of what the task was supposed to do.
            result: The output produced by the task.
            context: Optional additional context for evaluation.

        Returns:
            An EvaluationResult with scores and pass/fail determination.
        """
        criteria_scores: dict[str, float] = {}
        feedback_parts: list[str] = []

        for criterion in self._criteria:
            score = await self._evaluate_criterion(
                criterion, task_description, result, context
            )
            criteria_scores[criterion.name] = score

        # Compute weighted composite
        total_weight = sum(c.weight for c in self._criteria)
        if total_weight > 0:
            composite = sum(
                criteria_scores[c.name] * c.weight for c in self._criteria
            ) / total_weight
        else:
            composite = 0.0

        passed = composite >= self._quality_threshold

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

    async def _evaluate_criterion(
        self,
        criterion: EvaluationCriteria,
        task_description: str,
        result: Any,
        context: dict[str, Any] | None,
    ) -> float:
        """Evaluate a single criterion. Override for LLM-based evaluation.

        Default implementation checks structural properties of the result.

        Args:
            criterion: The criterion to evaluate.
            task_description: Task description for context.
            result: The output to evaluate.
            context: Additional context.

        Returns:
            Score from 0.0 to 1.0.
        """
        if result is None:
            return 0.0
        if isinstance(result, str) and not result.strip():
            return 0.1

        # Basic structural scoring
        if criterion.name == "completeness":
            if isinstance(result, str):
                # Longer results are more likely complete (heuristic)
                return min(len(result) / 100, 1.0)
            return 0.7

        if criterion.name == "correctness":
            # Without LLM, assume present result is correct
            return 0.8

        if criterion.name == "quality":
            if isinstance(result, str) and len(result) > 10:
                return 0.7
            return 0.5

        return 0.5
