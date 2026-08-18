"""Failure Analyzer - root cause analysis and success factor extraction.

Analyzes failed and successful executions to identify common factors,
bottlenecks, and cost effectiveness patterns.
"""

from collections import Counter
from typing import Any


class FailureAnalyzer:
    """Analyzes execution failures to identify root causes and improvement opportunities.

    Provides root cause analysis, success factor extraction, bottleneck identification,
    and cost effectiveness analysis to guide evolution proposals.
    """

    def root_cause_analysis(
        self,
        failed_executions: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Group failures by common factors to identify root causes.

        Each execution dict should contain: agent_id, task_type, tool_used,
        error, timestamp.

        Args:
            failed_executions: List of failed execution records.

        Returns:
            List of root cause dicts with factor_type, factor_value,
            occurrence_count, and percentage.
        """
        if not failed_executions:
            return []

        total = len(failed_executions)
        results: list[dict[str, Any]] = []

        # Analyze by each factor type
        factor_types = ["agent_id", "task_type", "tool_used"]
        for factor_type in factor_types:
            counter: Counter[str] = Counter()
            for ex in failed_executions:
                value = ex.get(factor_type)
                if value:
                    counter[str(value)] += 1

            for factor_value, count in counter.most_common():
                if count >= 2:  # Only report factors that appear more than once
                    results.append({
                        "factor_type": factor_type,
                        "factor_value": factor_value,
                        "occurrence_count": count,
                        "percentage": (count / total) * 100,
                    })

        # Sort by occurrence count descending
        results.sort(key=lambda x: x["occurrence_count"], reverse=True)
        return results

    def extract_success_factors(
        self,
        successful_executions: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Identify commonalities among successful executions.

        Args:
            successful_executions: List of successful execution records.

        Returns:
            List of factor dicts with factor and frequency (0-1).
        """
        if not successful_executions:
            return []

        total = len(successful_executions)
        factor_counts: Counter[str] = Counter()

        for ex in successful_executions:
            # Track agent, task_type, and tool_used as factors
            if ex.get("agent_id"):
                factor_counts[f"agent:{ex['agent_id']}"] += 1
            if ex.get("task_type"):
                factor_counts[f"task_type:{ex['task_type']}"] += 1
            if ex.get("tool_used"):
                factor_counts[f"tool:{ex['tool_used']}"] += 1

        results: list[dict[str, Any]] = []
        for factor, count in factor_counts.most_common():
            frequency = count / total
            if frequency >= 0.3:  # Only report factors present in 30%+ of successes
                results.append({
                    "factor": factor,
                    "frequency": frequency,
                })

        return results

    def compare_outcomes(
        self,
        successes: list[dict[str, Any]],
        failures: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Compare successful and failed executions to find differentiators.

        Args:
            successes: List of successful execution records.
            failures: List of failed execution records.

        Returns:
            Dict with common_in_success, common_in_failure, and differentiators.
        """
        success_factors: set[str] = set()
        failure_factors: set[str] = set()

        for ex in successes:
            if ex.get("agent_id"):
                success_factors.add(f"agent:{ex['agent_id']}")
            if ex.get("task_type"):
                success_factors.add(f"task_type:{ex['task_type']}")
            if ex.get("tool_used"):
                success_factors.add(f"tool:{ex['tool_used']}")

        for ex in failures:
            if ex.get("agent_id"):
                failure_factors.add(f"agent:{ex['agent_id']}")
            if ex.get("task_type"):
                failure_factors.add(f"task_type:{ex['task_type']}")
            if ex.get("tool_used"):
                failure_factors.add(f"tool:{ex['tool_used']}")

        common_in_success = list(success_factors - failure_factors)
        common_in_failure = list(failure_factors - success_factors)
        differentiators = list(success_factors.symmetric_difference(failure_factors))

        return {
            "common_in_success": common_in_success,
            "common_in_failure": common_in_failure,
            "differentiators": differentiators,
        }

    def identify_bottlenecks(
        self,
        execution_history: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Find stages that slow down execution.

        Each execution dict should have duration_seconds and stage fields.

        Args:
            execution_history: List of execution records with stage and duration info.

        Returns:
            List of bottleneck dicts sorted by avg_duration descending,
            each with stage, avg_duration, and count.
        """
        if not execution_history:
            return []

        stage_durations: dict[str, list[float]] = {}
        for ex in execution_history:
            stage = ex.get("stage", "unknown")
            duration = ex.get("duration_seconds", 0)
            stage_durations.setdefault(stage, []).append(duration)

        results: list[dict[str, Any]] = []
        for stage, durations in stage_durations.items():
            avg_duration = sum(durations) / len(durations)
            results.append({
                "stage": stage,
                "avg_duration": avg_duration,
                "count": len(durations),
            })

        # Sort by average duration descending (slowest first)
        results.sort(key=lambda x: x["avg_duration"], reverse=True)
        return results

    def cost_effectiveness_analysis(
        self,
        executions: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Calculate cost per quality unit for different approaches.

        Each execution dict should have cost_cents, quality_score, and approach fields.

        Args:
            executions: List of execution records with cost, quality, and approach.

        Returns:
            Dict with avg_cost_per_quality, best_approach, and worst_approach.
        """
        if not executions:
            return {
                "avg_cost_per_quality": 0.0,
                "best_approach": "none",
                "worst_approach": "none",
            }

        approach_metrics: dict[str, dict[str, float]] = {}
        for ex in executions:
            approach = ex.get("approach", "default")
            cost = ex.get("cost_cents", 0)
            quality = ex.get("quality_score", 1.0)

            if approach not in approach_metrics:
                approach_metrics[approach] = {"total_cost": 0, "total_quality": 0, "count": 0}

            approach_metrics[approach]["total_cost"] += cost
            approach_metrics[approach]["total_quality"] += quality
            approach_metrics[approach]["count"] += 1

        # Calculate cost per quality for each approach
        approach_efficiency: dict[str, float] = {}
        total_cost_per_quality = 0.0
        total_count = 0

        for approach, metrics in approach_metrics.items():
            if metrics["total_quality"] > 0:
                cost_per_quality = metrics["total_cost"] / metrics["total_quality"]
            else:
                cost_per_quality = float("inf")
            approach_efficiency[approach] = cost_per_quality
            total_cost_per_quality += cost_per_quality * metrics["count"]
            total_count += metrics["count"]

        avg_cost_per_quality = total_cost_per_quality / total_count if total_count > 0 else 0.0

        # Find best (lowest cost per quality) and worst
        sorted_approaches = sorted(approach_efficiency.items(), key=lambda x: x[1])
        best_approach = sorted_approaches[0][0] if sorted_approaches else "none"
        worst_approach = sorted_approaches[-1][0] if sorted_approaches else "none"

        return {
            "avg_cost_per_quality": avg_cost_per_quality,
            "best_approach": best_approach,
            "worst_approach": worst_approach,
        }
