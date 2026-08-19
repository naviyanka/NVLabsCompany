"""Model evaluator for running benchmarks and collecting results.

Provides the ModelEvaluator class that executes benchmark test cases
through a provided adapter function, measures wall-clock time for each
execution, computes metrics, and returns structured evaluation results.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable

from nexus.evaluation.benchmark import Benchmark, TestCase
from nexus.evaluation.metrics import accuracy, cost_total, latency_stats, token_efficiency


@dataclass
class EvaluationConfig:
    """Configuration for a model evaluation run.

    Attributes:
        model_name: Name/identifier of the model being evaluated.
        prompt_template: Template string for formatting inputs (use {input} placeholder).
        temperature: Sampling temperature for the model.
        max_tokens: Maximum tokens to generate per response.
        num_runs: Number of times to run each test case for averaging.
    """

    model_name: str
    prompt_template: str = "{input}"
    temperature: float = 0.0
    max_tokens: int = 1024
    num_runs: int = 1


@dataclass
class EvaluationResult:
    """Result of a model evaluation run.

    Attributes:
        config: The evaluation configuration used.
        predictions: List of model predictions for each test case.
        metrics: Computed metrics dictionary.
        duration: Total wall-clock time for the evaluation in seconds.
        timestamp: ISO format timestamp of when the evaluation completed.
    """

    config: EvaluationConfig
    predictions: list[str]
    metrics: dict[str, Any]
    duration: float
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> dict[str, Any]:
        """Serialize the evaluation result to a dictionary.

        Returns:
            Dictionary representation of the result.
        """
        return {
            "config": {
                "model_name": self.config.model_name,
                "prompt_template": self.config.prompt_template,
                "temperature": self.config.temperature,
                "max_tokens": self.config.max_tokens,
                "num_runs": self.config.num_runs,
            },
            "predictions": self.predictions,
            "metrics": self.metrics,
            "duration": self.duration,
            "timestamp": self.timestamp,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> EvaluationResult:
        """Create an EvaluationResult from a dictionary.

        Args:
            data: Dictionary with result fields.

        Returns:
            A new EvaluationResult instance.
        """
        config_data = data["config"]
        config = EvaluationConfig(
            model_name=config_data["model_name"],
            prompt_template=config_data.get("prompt_template", "{input}"),
            temperature=config_data.get("temperature", 0.0),
            max_tokens=config_data.get("max_tokens", 1024),
            num_runs=config_data.get("num_runs", 1),
        )
        return cls(
            config=config,
            predictions=data["predictions"],
            metrics=data["metrics"],
            duration=data["duration"],
            timestamp=data.get("timestamp", datetime.now(timezone.utc).isoformat()),
        )


class ModelEvaluator:
    """Evaluator that runs benchmarks against a model via an adapter function.

    The evaluator is decoupled from specific LLM implementations by accepting
    an adapter_fn parameter that handles the actual model invocation.
    """

    async def run_benchmark(
        self,
        benchmark: Benchmark,
        config: EvaluationConfig,
        adapter_fn: Callable[[str], Awaitable[str]],
    ) -> EvaluationResult:
        """Execute all test cases in a benchmark and collect results.

        Runs each test case through the adapter function, measuring
        wall-clock time for each execution. Computes accuracy, latency
        statistics, and aggregates results into an EvaluationResult.

        Args:
            benchmark: The benchmark containing test cases to run.
            config: Configuration for this evaluation run.
            adapter_fn: Async callable that takes an input string and returns
                the model's output string. Keeps the evaluator decoupled
                from specific LLM adapters.

        Returns:
            EvaluationResult with predictions, metrics, and timing data.
        """
        predictions: list[str] = []
        latencies: list[float] = []
        expected_outputs: list[str] = []

        total_start = time.monotonic()

        for test_case in benchmark.test_cases:
            # Format the input using the prompt template
            formatted_input = config.prompt_template.replace("{input}", test_case.input)

            # Run multiple times if num_runs > 1 and take the last prediction
            case_latencies: list[float] = []
            prediction = ""

            for _ in range(config.num_runs):
                start_time = time.monotonic()
                prediction = await adapter_fn(formatted_input)
                elapsed = time.monotonic() - start_time
                case_latencies.append(elapsed)

            # Use average latency for this test case
            avg_latency = sum(case_latencies) / len(case_latencies)
            latencies.append(avg_latency)
            predictions.append(prediction)
            expected_outputs.append(test_case.expected_output)

        total_duration = time.monotonic() - total_start

        # Compute metrics
        acc = accuracy(predictions, expected_outputs)
        lat_stats = latency_stats(latencies)

        # Estimate token counts based on string lengths (simple heuristic)
        token_counts_list: list[dict[str, int]] = []
        output_token_counts: list[int] = []
        for tc, pred in zip(benchmark.test_cases, predictions):
            formatted = config.prompt_template.replace("{input}", tc.input)
            input_tokens = max(1, len(formatted) // 4)
            output_tokens = max(1, len(pred) // 4)
            token_counts_list.append({
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
            })
            output_token_counts.append(input_tokens + output_tokens)

        cost = cost_total(token_counts_list)
        efficiency = token_efficiency(predictions, output_token_counts)

        metrics: dict[str, Any] = {
            "accuracy": acc,
            "latency": lat_stats,
            "cost": cost,
            "token_efficiency": efficiency,
            "total_test_cases": len(benchmark.test_cases),
        }

        return EvaluationResult(
            config=config,
            predictions=predictions,
            metrics=metrics,
            duration=total_duration,
        )
