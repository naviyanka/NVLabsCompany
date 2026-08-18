"""Performance management for agents.

Calculates weighted performance scores, tracks trends, compares agents,
and generates recommendations based on configurable thresholds.
"""

import uuid
from typing import Any


class PerformanceManager:
    """Evaluates and tracks agent performance based on task history."""

    # Configurable weight defaults
    WEIGHT_COMPLETION = 0.40
    WEIGHT_QUALITY = 0.30
    WEIGHT_SPEED = 0.20
    WEIGHT_EFFICIENCY = 0.10

    # Recommendation thresholds
    THRESHOLD_PROMOTE = 90.0
    THRESHOLD_NO_CHANGE = 70.0
    THRESHOLD_RETRAIN = 50.0

    # Speed and efficiency baselines (configurable)
    BASELINE_DURATION_HOURS = 8.0
    BASELINE_COST_CENTS = 1000

    def calculate_score(self, task_history: list[dict[str, Any]]) -> float:
        """Compute weighted score (0-100) from task history.

        Weights: completion_rate (40%), quality (30%), speed (20%), efficiency (10%).

        Task history items should have:
            - task_id: uuid
            - status: str (completed/failed/pending)
            - quality_score: float 0-1
            - duration_hours: float
            - cost_cents: int

        Args:
            task_history: List of task result dicts.

        Returns:
            Float score between 0 and 100.
        """
        if not task_history:
            return 0.0

        metrics = self.get_metrics(task_history)

        # Completion rate component (0-100)
        completion_component = metrics["completion_rate"] * 100

        # Quality component (0-100)
        quality_component = metrics["avg_quality"] * 100

        # Speed component (0-100): faster is better, capped at baseline
        if metrics["avg_duration_hours"] > 0:
            speed_ratio = min(
                self.BASELINE_DURATION_HOURS / metrics["avg_duration_hours"], 1.0
            )
        else:
            speed_ratio = 1.0
        speed_component = speed_ratio * 100

        # Efficiency component (0-100): lower cost is better
        if metrics["avg_cost_cents"] > 0:
            efficiency_ratio = min(
                self.BASELINE_COST_CENTS / metrics["avg_cost_cents"], 1.0
            )
        else:
            efficiency_ratio = 1.0
        efficiency_component = efficiency_ratio * 100

        score = (
            self.WEIGHT_COMPLETION * completion_component
            + self.WEIGHT_QUALITY * quality_component
            + self.WEIGHT_SPEED * speed_component
            + self.WEIGHT_EFFICIENCY * efficiency_component
        )

        return round(min(max(score, 0.0), 100.0), 2)

    def get_metrics(self, task_history: list[dict[str, Any]]) -> dict[str, Any]:
        """Return individual metrics breakdown.

        Returns:
            Dict with completion_rate, avg_quality, avg_duration_hours,
            avg_cost_cents, and total_tasks.
        """
        if not task_history:
            return {
                "completion_rate": 0.0,
                "avg_quality": 0.0,
                "avg_duration_hours": 0.0,
                "avg_cost_cents": 0.0,
                "total_tasks": 0,
            }

        total = len(task_history)
        completed = sum(
            1 for t in task_history if t.get("status") == "completed"
        )
        completion_rate = completed / total if total > 0 else 0.0

        quality_scores = [
            t.get("quality_score", 0.0) for t in task_history
            if t.get("quality_score") is not None
        ]
        avg_quality = (
            sum(quality_scores) / len(quality_scores)
            if quality_scores
            else 0.0
        )

        durations = [
            t.get("duration_hours", 0.0) for t in task_history
            if t.get("duration_hours") is not None
        ]
        avg_duration = (
            sum(durations) / len(durations) if durations else 0.0
        )

        costs = [
            t.get("cost_cents", 0) for t in task_history
            if t.get("cost_cents") is not None
        ]
        avg_cost = sum(costs) / len(costs) if costs else 0.0

        return {
            "completion_rate": round(completion_rate, 4),
            "avg_quality": round(avg_quality, 4),
            "avg_duration_hours": round(avg_duration, 2),
            "avg_cost_cents": round(avg_cost, 2),
            "total_tasks": total,
        }

    def compare_agents(
        self, agent_histories: dict[uuid.UUID, list[dict[str, Any]]]
    ) -> list[dict[str, Any]]:
        """Return ranked list of agents by performance score.

        Args:
            agent_histories: Dict mapping agent_id to their task history.

        Returns:
            List of dicts with agent_id, score, and rank, sorted by score descending.
        """
        scored: list[dict[str, Any]] = []
        for agent_id, history in agent_histories.items():
            score = self.calculate_score(history)
            scored.append({"agent_id": agent_id, "score": score})

        # Sort by score descending
        scored.sort(key=lambda x: x["score"], reverse=True)

        # Assign ranks
        for i, entry in enumerate(scored, start=1):
            entry["rank"] = i

        return scored

    def get_recommendations(
        self, score: float, task_history: list[dict[str, Any]]
    ) -> list[str]:
        """Return recommendations based on performance thresholds.

        Thresholds:
            - score >= 90: "promote"
            - score >= 70: "no_change"
            - score >= 50: "retrain"
            - score < 50: "replace"

        Args:
            score: The agent's performance score (0-100).
            task_history: The agent's task history for contextual recommendations.

        Returns:
            List of recommendation strings.
        """
        recommendations: list[str] = []

        if score >= self.THRESHOLD_PROMOTE:
            recommendations.append("promote")
        elif score >= self.THRESHOLD_NO_CHANGE:
            recommendations.append("no_change")
        elif score >= self.THRESHOLD_RETRAIN:
            recommendations.append("retrain")
        else:
            recommendations.append("replace")

        # Additional context-based recommendations
        if task_history:
            metrics = self.get_metrics(task_history)
            if metrics["completion_rate"] < 0.5:
                recommendations.append("review_task_assignment")
            if metrics["avg_quality"] < 0.5:
                recommendations.append("quality_improvement_needed")

        return recommendations

    def track_trend(self, scores_over_time: list[float]) -> str:
        """Identify performance trend from historical scores.

        Compares average of last 3 scores to average of first 3 scores.

        Args:
            scores_over_time: List of scores in chronological order.

        Returns:
            "improving", "declining", or "stable".
        """
        if len(scores_over_time) < 3:
            return "stable"

        first_3_avg = sum(scores_over_time[:3]) / 3
        last_3_avg = sum(scores_over_time[-3:]) / 3

        # Use a threshold to determine significant change
        threshold = 5.0

        if last_3_avg - first_3_avg > threshold:
            return "improving"
        elif first_3_avg - last_3_avg > threshold:
            return "declining"
        else:
            return "stable"
