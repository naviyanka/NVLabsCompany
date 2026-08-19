"""Model Evaluation Framework for the Nexus AI Company OS.

Provides systematic evaluation of different models and prompts through
benchmark definitions, metric calculations, model evaluation execution,
and JSON reporting. Results feed into the evolution subsystem for
continuous improvement.

Components:
- benchmark: TestCase, Benchmark, and BenchmarkSuite definitions
- metrics: Pure metric calculation functions (accuracy, latency, cost, efficiency)
- evaluator: ModelEvaluator that runs benchmarks against adapter functions
- reporter: Report generation, JSON export, and result comparison
"""

from __future__ import annotations

from nexus.evaluation.benchmark import Benchmark, BenchmarkSuite, TestCase
from nexus.evaluation.evaluator import EvaluationConfig, EvaluationResult, ModelEvaluator
from nexus.evaluation.metrics import accuracy, cost_total, latency_stats, token_efficiency
from nexus.evaluation.reporter import (
    EvaluationReport,
    ReportFormat,
    compare_results,
    export_report,
    generate_report,
)

__all__ = [
    "Benchmark",
    "BenchmarkSuite",
    "EvaluationConfig",
    "EvaluationReport",
    "EvaluationResult",
    "ModelEvaluator",
    "ReportFormat",
    "TestCase",
    "accuracy",
    "compare_results",
    "cost_total",
    "export_report",
    "generate_report",
    "latency_stats",
    "token_efficiency",
]
