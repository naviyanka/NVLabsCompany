"""Evaluation reporting and comparison utilities.

Provides report generation, JSON export, and result comparison
for model evaluation results. All reports are serializable to
JSON format for persistence and sharing.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from nexus.evaluation.evaluator import EvaluationResult


class ReportFormat(Enum):
    """Supported report output formats."""

    JSON = "json"


@dataclass
class EvaluationReport:
    """A report wrapping multiple evaluation results with summary statistics.

    Attributes:
        results: List of evaluation results included in this report.
        summary: Computed summary statistics across all results.
        generated_at: ISO format timestamp of when the report was generated.
    """

    results: list[EvaluationResult]
    summary: dict[str, Any] = field(default_factory=dict)
    generated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> dict[str, Any]:
        """Serialize the report to a dictionary.

        Returns:
            Dictionary representation of the report.
        """
        return {
            "results": [r.to_dict() for r in self.results],
            "summary": self.summary,
            "generated_at": self.generated_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> EvaluationReport:
        """Create an EvaluationReport from a dictionary.

        Args:
            data: Dictionary with report fields.

        Returns:
            A new EvaluationReport instance.
        """
        return cls(
            results=[EvaluationResult.from_dict(r) for r in data.get("results", [])],
            summary=data.get("summary", {}),
            generated_at=data.get("generated_at", datetime.now(timezone.utc).isoformat()),
        )


def generate_report(results: list[EvaluationResult]) -> EvaluationReport:
    """Generate an evaluation report with comparative statistics.

    Computes summary statistics across all evaluation results, including
    best/worst accuracy, average latency, and total cost.

    Args:
        results: List of evaluation results to include in the report.

    Returns:
        An EvaluationReport with computed summary statistics.
    """
    if not results:
        return EvaluationReport(results=[], summary={})

    accuracies: list[float] = []
    durations: list[float] = []
    total_cost = 0.0
    model_names: list[str] = []

    for result in results:
        metrics = result.metrics
        accuracies.append(metrics.get("accuracy", 0.0))
        durations.append(result.duration)
        cost_info = metrics.get("cost", {})
        total_cost += cost_info.get("estimated_cost", 0.0)
        model_names.append(result.config.model_name)

    summary: dict[str, Any] = {
        "total_evaluations": len(results),
        "models_evaluated": list(set(model_names)),
        "best_accuracy": max(accuracies),
        "worst_accuracy": min(accuracies),
        "mean_accuracy": sum(accuracies) / len(accuracies),
        "total_duration": sum(durations),
        "mean_duration": sum(durations) / len(durations),
        "total_estimated_cost": round(total_cost, 6),
    }

    return EvaluationReport(results=results, summary=summary)


def export_report(report: EvaluationReport, format: ReportFormat) -> str:
    """Export an evaluation report to the specified format.

    Currently supports JSON format only.

    Args:
        report: The evaluation report to export.
        format: The output format (currently only JSON).

    Returns:
        Serialized report as a string.

    Raises:
        ValueError: If the format is not supported.
    """
    if format == ReportFormat.JSON:
        return json.dumps(report.to_dict(), indent=2, default=str)

    raise ValueError(f"Unsupported report format: {format}")


def compare_results(
    result_a: EvaluationResult,
    result_b: EvaluationResult,
) -> dict[str, Any]:
    """Compare two evaluation results and produce a comparison dict.

    Shows deltas for each metric between result_a and result_b.
    Positive deltas indicate result_b is higher than result_a.

    Args:
        result_a: The baseline evaluation result.
        result_b: The comparison evaluation result.

    Returns:
        Dictionary with comparison data including per-metric deltas.
    """
    metrics_a = result_a.metrics
    metrics_b = result_b.metrics

    # Accuracy delta
    acc_a = metrics_a.get("accuracy", 0.0)
    acc_b = metrics_b.get("accuracy", 0.0)
    accuracy_delta = acc_b - acc_a

    # Latency deltas
    lat_a = metrics_a.get("latency", {})
    lat_b = metrics_b.get("latency", {})
    latency_delta: dict[str, float] = {}
    for key in ("mean", "p50", "p95", "p99", "max"):
        latency_delta[key] = lat_b.get(key, 0.0) - lat_a.get(key, 0.0)

    # Cost delta
    cost_a = metrics_a.get("cost", {}).get("estimated_cost", 0.0)
    cost_b = metrics_b.get("cost", {}).get("estimated_cost", 0.0)
    cost_delta = cost_b - cost_a

    # Token efficiency delta
    eff_a = metrics_a.get("token_efficiency", 0.0)
    eff_b = metrics_b.get("token_efficiency", 0.0)
    efficiency_delta = eff_b - eff_a

    # Duration delta
    duration_delta = result_b.duration - result_a.duration

    return {
        "model_a": result_a.config.model_name,
        "model_b": result_b.config.model_name,
        "deltas": {
            "accuracy": round(accuracy_delta, 6),
            "latency": {k: round(v, 6) for k, v in latency_delta.items()},
            "estimated_cost": round(cost_delta, 6),
            "token_efficiency": round(efficiency_delta, 6),
            "duration": round(duration_delta, 6),
        },
        "summary": {
            "accuracy_improved": accuracy_delta > 0,
            "latency_improved": latency_delta.get("mean", 0.0) < 0,
            "cost_improved": cost_delta < 0,
        },
    }
