"""Metric calculation functions for model evaluation.

Provides pure functions for computing evaluation metrics:
- accuracy: Exact match ratio between predictions and expected outputs
- latency_stats: Statistical summary of latency measurements
- cost_total: Token cost estimation using a simple pricing model
- token_efficiency: Useful output per token ratio

All functions are pure (no side effects, no async) and operate
on lists of primitive values.
"""

from __future__ import annotations

from typing import Any


def accuracy(predictions: list[str], expected: list[str]) -> float:
    """Compute exact match accuracy between predictions and expected outputs.

    Compares each prediction against the corresponding expected output
    using exact string matching. Returns the ratio of matches.

    Args:
        predictions: List of model predictions.
        expected: List of expected/ground-truth outputs.

    Returns:
        Accuracy as a float between 0.0 and 1.0.
        Returns 0.0 if both lists are empty.

    Raises:
        ValueError: If predictions and expected have different lengths.
    """
    if len(predictions) != len(expected):
        raise ValueError(
            f"predictions and expected must have the same length, "
            f"got {len(predictions)} and {len(expected)}"
        )

    if not predictions:
        return 0.0

    matches = sum(1 for p, e in zip(predictions, expected) if p == e)
    return matches / len(predictions)


def latency_stats(latencies: list[float]) -> dict[str, float]:
    """Compute statistical summary of latency measurements.

    Calculates mean, median (p50), p95, p99, and max latency values
    from a list of latency measurements in seconds.

    Args:
        latencies: List of latency values in seconds.

    Returns:
        Dictionary with keys: mean, p50, p95, p99, max.
        All values are floats representing seconds.
        Returns all zeros if the list is empty.
    """
    if not latencies:
        return {"mean": 0.0, "p50": 0.0, "p95": 0.0, "p99": 0.0, "max": 0.0}

    sorted_latencies = sorted(latencies)
    n = len(sorted_latencies)

    mean_val = sum(sorted_latencies) / n
    p50 = _percentile(sorted_latencies, 50)
    p95 = _percentile(sorted_latencies, 95)
    p99 = _percentile(sorted_latencies, 99)
    max_val = sorted_latencies[-1]

    return {
        "mean": mean_val,
        "p50": p50,
        "p95": p95,
        "p99": p99,
        "max": max_val,
    }


def cost_total(token_counts: list[dict[str, Any]]) -> dict[str, Any]:
    """Compute total token cost using a simple pricing model.

    Uses a simplified pricing model:
    - Input tokens: $0.0015 per 1000 tokens
    - Output tokens: $0.002 per 1000 tokens

    Each dict in token_counts should have 'input_tokens' and
    'output_tokens' integer fields.

    Args:
        token_counts: List of dicts with 'input_tokens' and 'output_tokens' keys.

    Returns:
        Dictionary with total_input_tokens, total_output_tokens, and
        estimated_cost (in dollars).
    """
    total_input = 0
    total_output = 0

    for entry in token_counts:
        total_input += entry.get("input_tokens", 0)
        total_output += entry.get("output_tokens", 0)

    # Simple pricing model (per 1000 tokens)
    input_cost_per_1k = 0.0015
    output_cost_per_1k = 0.002

    estimated_cost = (
        (total_input / 1000.0) * input_cost_per_1k
        + (total_output / 1000.0) * output_cost_per_1k
    )

    return {
        "total_input_tokens": total_input,
        "total_output_tokens": total_output,
        "estimated_cost": round(estimated_cost, 6),
    }


def token_efficiency(outputs: list[str], token_counts: list[int]) -> float:
    """Compute useful output per token ratio.

    Measures how efficiently the model uses tokens by comparing
    the total character length of outputs to the total tokens consumed.
    Higher values indicate more efficient token usage.

    Args:
        outputs: List of output strings produced by the model.
        token_counts: List of total token counts (input + output) for each call.

    Returns:
        Ratio of total output characters to total tokens consumed.
        Returns 0.0 if total tokens is zero or lists are empty.

    Raises:
        ValueError: If outputs and token_counts have different lengths.
    """
    if len(outputs) != len(token_counts):
        raise ValueError(
            f"outputs and token_counts must have the same length, "
            f"got {len(outputs)} and {len(token_counts)}"
        )

    if not outputs:
        return 0.0

    total_chars = sum(len(output) for output in outputs)
    total_tokens = sum(token_counts)

    if total_tokens == 0:
        return 0.0

    return total_chars / total_tokens


def _percentile(sorted_values: list[float], percentile: int) -> float:
    """Compute a percentile from a sorted list of values.

    Uses linear interpolation between closest data points.

    Args:
        sorted_values: Pre-sorted list of numeric values.
        percentile: Percentile to compute (0-100).

    Returns:
        The computed percentile value.
    """
    if not sorted_values:
        return 0.0

    n = len(sorted_values)
    if n == 1:
        return sorted_values[0]

    # Calculate the index for the percentile
    k = (percentile / 100.0) * (n - 1)
    lower_idx = int(k)
    upper_idx = lower_idx + 1

    if upper_idx >= n:
        return sorted_values[-1]

    # Linear interpolation
    fraction = k - lower_idx
    return sorted_values[lower_idx] + fraction * (sorted_values[upper_idx] - sorted_values[lower_idx])
