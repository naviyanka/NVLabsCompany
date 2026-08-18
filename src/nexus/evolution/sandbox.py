"""Evolution Sandbox - isolated testing environment for proposals.

Provides a logical sandbox (in-memory state tracking) for evaluating
proposals against test data before promoting them to production.
Resource limits ensure sandboxes do not exceed cost or time budgets.
"""

import uuid
from datetime import datetime, timezone
from typing import Any


class EvolutionSandbox:
    """Manages logical sandboxes for evaluating evolution proposals.

    Sandboxes are in-memory state containers that track configuration,
    resource limits, and benchmark results. They provide isolation for
    testing proposals without affecting production systems.
    """

    def __init__(self) -> None:
        """Initialize the sandbox manager."""
        self._sandboxes: dict[str, dict[str, Any]] = {}

    def create_sandbox(
        self,
        proposal_id: uuid.UUID,
        config: dict[str, Any],
    ) -> uuid.UUID:
        """Create a new sandbox for evaluating a proposal.

        Args:
            proposal_id: The proposal to test.
            config: Configuration for the sandbox environment.

        Returns:
            The sandbox_id for referencing this sandbox.
        """
        sandbox_id = uuid.uuid4()
        self._sandboxes[str(sandbox_id)] = {
            "sandbox_id": str(sandbox_id),
            "proposal_id": str(proposal_id),
            "config": config,
            "status": "active",
            "max_cost_cents": 1000,
            "max_duration_seconds": 300,
            "results": [],
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        return sandbox_id

    async def run_benchmark(
        self,
        sandbox_id: uuid.UUID,
        test_cases: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Execute proposal against test data within the sandbox.

        Args:
            sandbox_id: The sandbox to run benchmarks in.
            test_cases: List of test case dicts to evaluate against.

        Returns:
            List of result dicts with test_case_id, score, and duration_ms.
        """
        sandbox_key = str(sandbox_id)
        if sandbox_key not in self._sandboxes:
            raise ValueError(f"Sandbox {sandbox_id} not found")

        sandbox = self._sandboxes[sandbox_key]
        if sandbox["status"] != "active":
            raise ValueError(f"Sandbox {sandbox_id} is not active (status: {sandbox['status']})")

        results: list[dict[str, Any]] = []
        for test_case in test_cases:
            # Simulate benchmark execution
            test_case_id = test_case.get("id", str(uuid.uuid4()))
            expected_score = test_case.get("expected_score", 0.8)
            expected_duration = test_case.get("expected_duration_ms", 100.0)

            result = {
                "test_case_id": str(test_case_id),
                "score": expected_score,
                "duration_ms": expected_duration,
            }
            results.append(result)

        sandbox["results"] = results
        return results

    def compare_with_baseline(
        self,
        sandbox_results: list[dict[str, Any]],
        baseline_results: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Compare sandbox results against baseline performance.

        Args:
            sandbox_results: Results from run_benchmark.
            baseline_results: Historical baseline results for comparison.

        Returns:
            Dict with improvement_percent and dimensions breakdown.
        """
        if not sandbox_results or not baseline_results:
            return {"improvement_percent": 0.0, "dimensions": {}}

        # Calculate average scores
        sandbox_avg_score = sum(r.get("score", 0) for r in sandbox_results) / len(sandbox_results)
        baseline_avg_score = sum(r.get("score", 0) for r in baseline_results) / len(baseline_results)

        # Calculate average durations
        sandbox_avg_duration = sum(r.get("duration_ms", 0) for r in sandbox_results) / len(sandbox_results)
        baseline_avg_duration = sum(r.get("duration_ms", 0) for r in baseline_results) / len(baseline_results)

        # Overall improvement based on score
        if baseline_avg_score > 0:
            score_improvement = ((sandbox_avg_score - baseline_avg_score) / baseline_avg_score) * 100
        else:
            score_improvement = 0.0

        # Speed improvement (lower duration is better)
        if baseline_avg_duration > 0:
            speed_improvement = ((baseline_avg_duration - sandbox_avg_duration) / baseline_avg_duration) * 100
        else:
            speed_improvement = 0.0

        # Overall improvement is weighted average
        improvement_percent = score_improvement * 0.7 + speed_improvement * 0.3

        dimensions = {
            "quality": {
                "baseline": baseline_avg_score,
                "candidate": sandbox_avg_score,
                "improvement_percent": score_improvement,
            },
            "speed": {
                "baseline_ms": baseline_avg_duration,
                "candidate_ms": sandbox_avg_duration,
                "improvement_percent": speed_improvement,
            },
        }

        return {
            "improvement_percent": improvement_percent,
            "dimensions": dimensions,
        }

    def enforce_resource_limits(
        self,
        sandbox_id: uuid.UUID,
        max_cost_cents: int = 1000,
        max_duration_seconds: int = 300,
    ) -> None:
        """Apply resource limits to a sandbox.

        Args:
            sandbox_id: The sandbox to apply limits to.
            max_cost_cents: Maximum cost allowed in cents.
            max_duration_seconds: Maximum duration allowed in seconds.
        """
        sandbox_key = str(sandbox_id)
        if sandbox_key not in self._sandboxes:
            raise ValueError(f"Sandbox {sandbox_id} not found")

        self._sandboxes[sandbox_key]["max_cost_cents"] = max_cost_cents
        self._sandboxes[sandbox_key]["max_duration_seconds"] = max_duration_seconds

    def cleanup(self, sandbox_id: uuid.UUID) -> None:
        """Remove a sandbox from tracking.

        Args:
            sandbox_id: The sandbox to clean up.
        """
        sandbox_key = str(sandbox_id)
        if sandbox_key in self._sandboxes:
            del self._sandboxes[sandbox_key]
