"""Proposal Evaluator - scores proposals and checks promotion criteria.

Evaluates proposals based on sandbox results, checking statistical significance
and promotion thresholds before recommending changes for approval.
"""

import math
import uuid
from datetime import datetime, timezone
from typing import Any


class ProposalEvaluator:
    """Evaluates evolution proposals against baseline performance.

    Creates evaluation records with scores across multiple dimensions
    (quality, speed, cost, safety) and determines whether proposals
    meet promotion criteria.
    """

    def __init__(self, db: Any = None) -> None:
        """Initialize the evaluator.

        Args:
            db: Optional async database session for persistence.
        """
        self.db = db

    def evaluate(
        self,
        proposal_id: uuid.UUID,
        sandbox_results: list[dict[str, Any]],
        baseline_results: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Evaluate a proposal based on sandbox vs baseline results.

        Creates an evaluation with scores across dimensions (quality, speed,
        cost, safety).

        Args:
            proposal_id: The proposal being evaluated.
            sandbox_results: Results from sandbox benchmark.
            baseline_results: Baseline results for comparison.

        Returns:
            Evaluation dict with passed, improvement_percent, dimensions,
            and recommendation.
        """
        if not sandbox_results or not baseline_results:
            return {
                "proposal_id": str(proposal_id),
                "passed": False,
                "improvement_percent": 0.0,
                "dimensions": {},
                "recommendation": "Insufficient data for evaluation",
                "evaluated_at": datetime.now(timezone.utc).isoformat(),
            }

        # Calculate scores per dimension
        sandbox_scores = [r.get("score", 0) for r in sandbox_results]
        baseline_scores = [r.get("score", 0) for r in baseline_results]

        sandbox_avg = sum(sandbox_scores) / len(sandbox_scores) if sandbox_scores else 0
        baseline_avg = sum(baseline_scores) / len(baseline_scores) if baseline_scores else 0

        # Speed dimension
        sandbox_durations = [r.get("duration_ms", 0) for r in sandbox_results]
        baseline_durations = [r.get("duration_ms", 0) for r in baseline_results]

        sandbox_speed = sum(sandbox_durations) / len(sandbox_durations) if sandbox_durations else 0
        baseline_speed = sum(baseline_durations) / len(baseline_durations) if baseline_durations else 0

        # Quality improvement
        if baseline_avg > 0:
            quality_improvement = ((sandbox_avg - baseline_avg) / baseline_avg) * 100
        else:
            quality_improvement = 0.0

        # Speed improvement (lower is better)
        if baseline_speed > 0:
            speed_improvement = ((baseline_speed - sandbox_speed) / baseline_speed) * 100
        else:
            speed_improvement = 0.0

        # Overall improvement (weighted)
        improvement_percent = quality_improvement * 0.6 + speed_improvement * 0.4

        # Check statistical significance
        sample_size = len(sandbox_results)
        is_significant = self.check_significance(improvement_percent, sample_size)

        # Determine if passed
        passed = improvement_percent > 5.0 and is_significant

        # Safety dimension (no degradation in worst-case scenarios)
        min_sandbox = min(sandbox_scores) if sandbox_scores else 0
        min_baseline = min(baseline_scores) if baseline_scores else 0
        safety_ok = min_sandbox >= min_baseline * 0.9  # Allow 10% worst-case degradation

        dimensions = {
            "quality": {
                "baseline_score": baseline_avg,
                "candidate_score": sandbox_avg,
                "improvement_percent": quality_improvement,
            },
            "speed": {
                "baseline_ms": baseline_speed,
                "candidate_ms": sandbox_speed,
                "improvement_percent": speed_improvement,
            },
            "cost": {
                "note": "Cost tracked via resource limits in sandbox",
            },
            "safety": {
                "worst_case_baseline": min_baseline,
                "worst_case_candidate": min_sandbox,
                "no_degradation": safety_ok,
            },
        }

        # Generate recommendation
        if passed and safety_ok:
            recommendation = "Recommend promotion - significant improvement with no safety concerns"
        elif passed and not safety_ok:
            recommendation = "Improvement detected but safety concerns - review worst-case performance"
            passed = False
        elif is_significant and improvement_percent <= 5.0:
            recommendation = "Statistically significant but below minimum improvement threshold"
        else:
            recommendation = "Insufficient improvement or not statistically significant"

        return {
            "proposal_id": str(proposal_id),
            "passed": passed,
            "improvement_percent": improvement_percent,
            "dimensions": dimensions,
            "recommendation": recommendation,
            "statistical_significance": is_significant,
            "evaluated_at": datetime.now(timezone.utc).isoformat(),
        }

    def check_significance(
        self,
        improvement_percent: float,
        sample_size: int,
        confidence_level: float = 0.95,
    ) -> bool:
        """Check if improvement is statistically significant.

        Uses a simple heuristic: improvement must exceed 2/sqrt(sample_size) * 100
        to be considered significant.

        Args:
            improvement_percent: The observed improvement percentage.
            sample_size: Number of test cases evaluated.
            confidence_level: Desired confidence level (default 0.95).

        Returns:
            True if the improvement is statistically significant.
        """
        if sample_size <= 0:
            return False

        # Simple heuristic threshold: improvement > 2/sqrt(n) * 100
        threshold = (2.0 / math.sqrt(sample_size)) * 100
        return abs(improvement_percent) > threshold

    def check_promotion_criteria(
        self,
        evaluation: dict[str, Any],
        min_improvement_percent: float = 5.0,
    ) -> bool:
        """Check if an evaluation meets promotion criteria.

        Args:
            evaluation: Evaluation dict from evaluate().
            min_improvement_percent: Minimum improvement required for promotion.

        Returns:
            True if the evaluation passed and improvement exceeds threshold.
        """
        return (
            evaluation.get("passed", False)
            and evaluation.get("improvement_percent", 0) > min_improvement_percent
        )

    async def reject_with_explanation(
        self,
        proposal_id: uuid.UUID,
        reasons: list[str],
    ) -> dict[str, Any]:
        """Reject a proposal with detailed explanation.

        Args:
            proposal_id: The proposal to reject.
            reasons: List of reasons for rejection.

        Returns:
            Proposal update dict with status and rejection details.
        """
        return {
            "proposal_id": str(proposal_id),
            "status": "rejected",
            "rejection_reasons": reasons,
            "rejected_at": datetime.now(timezone.utc).isoformat(),
        }
