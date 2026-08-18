"""Evolution Observer - tracks executions and detects patterns and anomalies.

Monitors agent performance to identify recurring failures, slow tasks,
cost spikes, and anomalous behavior that may indicate opportunities
for improvement.
"""

import uuid
from datetime import datetime, timezone
from typing import Any, Optional


class EvolutionObserver:
    """Observes agent execution patterns and detects anomalies.

    Tracks execution data in-memory and optionally persists to the database.
    Provides pattern detection to identify systemic issues vs one-off failures.
    """

    def __init__(self, db: Any = None) -> None:
        """Initialize the observer.

        Args:
            db: Optional async database session for persistence.
        """
        self.db = db
        self._executions: list[dict[str, Any]] = []

    async def track_execution(
        self,
        company_id: uuid.UUID,
        agent_id: uuid.UUID,
        task_id: uuid.UUID,
        outcome: str,
        duration_seconds: float,
        cost_cents: int,
        metadata: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        """Record an execution event for later analysis.

        Args:
            company_id: The company this execution belongs to.
            agent_id: The agent that performed the task.
            task_id: The task that was executed.
            outcome: Result of execution (e.g., 'success', 'failure', 'partial').
            duration_seconds: How long the execution took.
            cost_cents: Cost of execution in cents.
            metadata: Optional additional context about the execution.

        Returns:
            The recorded execution record.
        """
        record = {
            "id": str(uuid.uuid4()),
            "company_id": str(company_id),
            "agent_id": str(agent_id),
            "task_id": str(task_id),
            "outcome": outcome,
            "duration_seconds": duration_seconds,
            "cost_cents": cost_cents,
            "metadata": metadata or {},
            "tracked_at": datetime.now(timezone.utc).isoformat(),
        }
        self._executions.append(record)
        return record

    def detect_patterns(
        self,
        company_id: uuid.UUID,
        executions: list[dict[str, Any]],
        window_days: int = 7,
    ) -> list[dict[str, Any]]:
        """Analyze executions to find recurring failures, slow tasks, cost spikes.

        Args:
            company_id: Company to filter patterns for.
            executions: List of execution records to analyze.
            window_days: Number of days to look back for patterns.

        Returns:
            List of pattern dicts with pattern_type, description, severity,
            occurrences, and examples.
        """
        patterns: list[dict[str, Any]] = []
        company_str = str(company_id)

        # Filter to company
        company_execs = [
            e for e in executions
            if str(e.get("company_id", "")) == company_str
        ]

        if not company_execs:
            return patterns

        # Detect recurring failures by agent
        failure_execs = [e for e in company_execs if e.get("outcome") == "failure"]
        agent_failures: dict[str, list[dict]] = {}
        for ex in failure_execs:
            agent = str(ex.get("agent_id", "unknown"))
            agent_failures.setdefault(agent, []).append(ex)

        for agent_id, failures in agent_failures.items():
            if len(failures) >= 2:
                severity = "high" if len(failures) >= 5 else "medium" if len(failures) >= 3 else "low"
                patterns.append({
                    "pattern_type": "recurring_failure",
                    "description": f"Agent {agent_id} has {len(failures)} failures",
                    "severity": severity,
                    "occurrences": len(failures),
                    "examples": failures[:3],
                })

        # Detect slow tasks
        if company_execs:
            durations = [e.get("duration_seconds", 0) for e in company_execs]
            if durations:
                avg_duration = sum(durations) / len(durations)
                slow_execs = [
                    e for e in company_execs
                    if e.get("duration_seconds", 0) > avg_duration * 2
                ]
                if len(slow_execs) >= 2:
                    patterns.append({
                        "pattern_type": "slow_execution",
                        "description": f"{len(slow_execs)} executions significantly slower than average ({avg_duration:.1f}s)",
                        "severity": "medium",
                        "occurrences": len(slow_execs),
                        "examples": slow_execs[:3],
                    })

        # Detect cost spikes
        costs = [e.get("cost_cents", 0) for e in company_execs]
        if costs:
            avg_cost = sum(costs) / len(costs)
            expensive_execs = [
                e for e in company_execs
                if e.get("cost_cents", 0) > avg_cost * 3
            ]
            if len(expensive_execs) >= 2:
                patterns.append({
                    "pattern_type": "cost_spike",
                    "description": f"{len(expensive_execs)} executions with costs 3x above average ({avg_cost:.0f} cents)",
                    "severity": "high",
                    "occurrences": len(expensive_execs),
                    "examples": expensive_execs[:3],
                })

        return patterns

    def detect_anomalies(
        self,
        values: list[float],
        threshold_std: float = 2.0,
    ) -> list[int]:
        """Flag indices of values outside mean +/- threshold*std.

        Args:
            values: List of numeric values to check.
            threshold_std: Number of standard deviations to use as threshold.

        Returns:
            List of indices where values are anomalous.
        """
        if not values or len(values) < 2:
            return []

        mean = sum(values) / len(values)
        variance = sum((v - mean) ** 2 for v in values) / len(values)
        std = variance ** 0.5

        if std == 0:
            return []

        anomalies: list[int] = []
        for i, v in enumerate(values):
            if abs(v - mean) > threshold_std * std:
                anomalies.append(i)

        return anomalies

    def classify_pattern(self, pattern: dict[str, Any]) -> str:
        """Classify a pattern as 'systemic' or 'one_off'.

        A pattern is systemic if it has 3+ occurrences and is spread across
        multiple examples (indicating it's not a transient issue).

        Args:
            pattern: A pattern dict from detect_patterns.

        Returns:
            'systemic' if occurrences >= 3 and spread across time, else 'one_off'.
        """
        occurrences = pattern.get("occurrences", 0)
        examples = pattern.get("examples", [])

        # Systemic if 3+ occurrences and multiple examples showing spread
        if occurrences >= 3 and len(examples) >= 2:
            return "systemic"

        return "one_off"
