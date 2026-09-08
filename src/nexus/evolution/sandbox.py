"""Evolution Sandbox - isolated execution environment for proposals.

Proposal code runs through `nexus.execution.sandbox` (E2B, Judge0, or a
local subprocess behind `allow_unsafe_local_execution`) - never on the host
API process. This module only owns the per-proposal bookkeeping: which
sandbox belongs to which proposal, its duration budget, and its results.
"""

import uuid
from datetime import datetime, timezone
from typing import Any

from nexus.evolution.isolated_sandbox import ResourceLimitExceeded
from nexus.execution.sandbox import SandboxBackend, get_backend


class EvolutionSandbox:
    """Runs evolution proposals inside a real isolated sandbox backend.

    Each sandbox tracks its proposal, resource budget, and benchmark
    results; the actual code execution is delegated to a
    `nexus.execution.sandbox.SandboxBackend`.
    """

    def __init__(self, backend: SandboxBackend | None = None) -> None:
        """Initialize the sandbox manager.

        Args:
            backend: Execution backend. Defaults to the configured one
                (`settings.sandbox_backend`) resolved at benchmark time.
        """
        self._sandboxes: dict[str, dict[str, Any]] = {}
        self._backend = backend

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

        Raises:
            ValueError: Sandbox missing/inactive, or a test case has no `code`.
            ResourceLimitExceeded: The sandbox duration budget was spent.
        """
        sandbox_key = str(sandbox_id)
        if sandbox_key not in self._sandboxes:
            raise ValueError(f"Sandbox {sandbox_id} not found")

        sandbox = self._sandboxes[sandbox_key]
        if sandbox["status"] != "active":
            raise ValueError(f"Sandbox {sandbox_id} is not active (status: {sandbox['status']})")

        backend = self._backend or get_backend()
        budget = sandbox["max_duration_seconds"]
        language = sandbox["config"].get("language", "python")
        spent = 0.0

        results: list[dict[str, Any]] = []
        for test_case in test_cases:
            test_case_id = str(test_case.get("id", uuid.uuid4()))
            code = test_case.get("code")
            if not code:
                raise ValueError(
                    f"Test case {test_case_id} has no 'code' to execute; "
                    "evolution benchmarks run real code in the sandbox."
                )

            execution = await backend.run(
                code,
                language=test_case.get("language", language),
                timeout=max(1, int(budget - spent)),
                workspace=test_case.get("workspace"),
                run_id=sandbox_key,
            )
            spent += execution.duration_ms / 1000.0

            expected = test_case.get("expected_output")
            passed = execution.ok and (
                expected is None or str(expected).strip() in execution.stdout
            )
            results.append(
                {
                    "test_case_id": test_case_id,
                    "score": 1.0 if passed else 0.0,
                    "duration_ms": float(execution.duration_ms),
                    "stdout": execution.stdout,
                    "stderr": execution.stderr,
                    "exit_code": execution.exit_code,
                    "timed_out": execution.timed_out,
                    "backend": execution.backend.value,
                }
            )

            if spent > budget:
                sandbox["status"] = "aborted"
                sandbox["results"] = results
                raise ResourceLimitExceeded(
                    resource="duration", limit=budget, actual=spent
                )

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
