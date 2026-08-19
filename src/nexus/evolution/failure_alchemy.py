"""Failure Alchemy - transforms failed tasks into protective artifacts.

Converts execution failures into structured learning artifacts:
- Antibodies: defensive rules to prevent recurrence
- Vaccines: test scenarios derived from real failures
- Catalysts: improvement proposals for systemic issues

Uses rule-based heuristics (not LLM) to extract patterns from errors
and generate actionable artifacts that strengthen the system over time.
"""

import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Protocol


class ArtifactType(str, Enum):
    """Types of learning artifacts produced from failures.

    Values:
        ANTIBODY: A defensive rule to prevent error recurrence.
        VACCINE: A test scenario derived from a real failure.
        CATALYST: An improvement proposal for systemic issues.
    """

    ANTIBODY = "antibody"
    VACCINE = "vaccine"
    CATALYST = "catalyst"


@dataclass
class Antibody:
    """A defensive rule extracted from a failure to prevent recurrence.

    Attributes:
        rule: The defensive rule statement (e.g., 'Never run X without checking Y').
        source_error: The original error message that generated this antibody.
        created_at: When this antibody was created.
        severity: Severity level of the original failure (low, medium, high, critical).
    """

    rule: str
    source_error: str
    created_at: datetime
    severity: str


@dataclass
class Vaccine:
    """A test scenario derived from a real failure.

    Attributes:
        scenario: Description of the test scenario.
        expected: What the correct behavior should be.
        actual: What actually happened during the failure.
        root_cause: Identified root cause of the failure.
        created_at: When this vaccine was created.
    """

    scenario: str
    expected: str
    actual: str
    root_cause: str
    created_at: datetime


@dataclass
class Catalyst:
    """An improvement proposal generated from recurring failure patterns.

    Attributes:
        proposal: Description of the proposed improvement.
        target_system: Which system or component should be improved.
        priority: Priority level for the improvement (low, medium, high).
        created_at: When this catalyst was created.
    """

    proposal: str
    target_system: str
    priority: str
    created_at: datetime


@dataclass
class FailureLearning:
    """Complete learning output from analyzing a single failure.

    Attributes:
        antibody: The defensive rule extracted from this failure.
        vaccine: The test scenario created from this failure.
        catalyst: Optional improvement proposal (only for systemic issues).
        task_id: The task that failed.
        agent_id: The agent that experienced the failure.
        created_at: When this learning was generated.
    """

    antibody: Antibody
    vaccine: Vaccine
    catalyst: Catalyst | None
    task_id: uuid.UUID
    agent_id: uuid.UUID
    created_at: datetime


class LearningEventBusProtocol(Protocol):
    """Protocol for emitting learning events for audit trail."""

    async def publish(
        self,
        event_type: str,
        payload: dict[str, Any] | None = None,
        source_agent_id: Any = None,
        company_id: Any = None,
    ) -> Any: ...


# Error pattern definitions for heuristic matching
_ERROR_PATTERNS: list[dict[str, Any]] = [
    {
        "pattern": re.compile(r"timeout|timed?\s*out|deadline\s*exceeded", re.IGNORECASE),
        "rule_template": "Never run {action} without setting a timeout guard",
        "severity": "high",
        "root_cause": "Operation exceeded time limit",
        "system": "timeout_handling",
    },
    {
        "pattern": re.compile(r"budget|cost|spend|exceeded\s*limit", re.IGNORECASE),
        "rule_template": "Never execute {action} without checking budget remaining",
        "severity": "critical",
        "root_cause": "Budget or cost limit exceeded",
        "system": "budget_enforcement",
    },
    {
        "pattern": re.compile(r"permission|denied|unauthorized|forbidden|403", re.IGNORECASE),
        "rule_template": "Never attempt {action} without verifying permissions first",
        "severity": "high",
        "root_cause": "Insufficient permissions for requested operation",
        "system": "access_control",
    },
    {
        "pattern": re.compile(r"not\s*found|404|missing|does\s*not\s*exist", re.IGNORECASE),
        "rule_template": "Never reference {action} without confirming resource exists",
        "severity": "medium",
        "root_cause": "Referenced resource does not exist",
        "system": "resource_validation",
    },
    {
        "pattern": re.compile(r"connection|refused|unreachable|network", re.IGNORECASE),
        "rule_template": "Never depend on {action} without a connectivity check",
        "severity": "high",
        "root_cause": "Network or connection failure",
        "system": "connectivity",
    },
    {
        "pattern": re.compile(r"rate\s*limit|throttl|429|too\s*many", re.IGNORECASE),
        "rule_template": "Never call {action} without respecting rate limits",
        "severity": "medium",
        "root_cause": "API rate limit exceeded",
        "system": "rate_limiting",
    },
    {
        "pattern": re.compile(r"memory|oom|out\s*of\s*memory|heap", re.IGNORECASE),
        "rule_template": "Never run {action} without checking available memory",
        "severity": "critical",
        "root_cause": "Memory exhaustion during operation",
        "system": "resource_management",
    },
    {
        "pattern": re.compile(r"deadlock|lock\s*timeout|concurrent", re.IGNORECASE),
        "rule_template": "Never perform {action} without acquiring proper locks",
        "severity": "high",
        "root_cause": "Concurrency conflict or deadlock",
        "system": "concurrency",
    },
]

# Default pattern for unmatched errors
_DEFAULT_PATTERN: dict[str, Any] = {
    "rule_template": "Never execute {action} without proper validation and error handling",
    "severity": "medium",
    "root_cause": "Unexpected execution error",
    "system": "general",
}


class FailureAlchemist:
    """Transforms execution failures into structured learning artifacts.

    Uses rule-based heuristics to analyze error messages and context,
    producing Antibody (defensive rules), Vaccine (test scenarios), and
    Catalyst (improvement proposals) artifacts. Stores all artifacts
    in-memory for retrieval and analysis.
    """

    def __init__(self, event_bus: LearningEventBusProtocol | None = None) -> None:
        """Initialize the failure alchemist.

        Args:
            event_bus: Optional event bus for emitting learning events.
        """
        self._event_bus = event_bus
        self._learnings: list[FailureLearning] = []
        self._error_counts: dict[str, int] = {}

    def analyze_failure(
        self,
        task_id: uuid.UUID,
        agent_id: uuid.UUID,
        error: str,
        context: dict[str, Any],
    ) -> FailureLearning:
        """Analyze a failure and produce structured learning artifacts.

        Uses pattern matching against known error categories to extract
        antibody rules, create vaccine test scenarios, and optionally
        propose catalyst improvements for recurring issues.

        Args:
            task_id: The task that failed.
            agent_id: The agent that experienced the failure.
            error: The error message from the failure.
            context: Additional context about the failure (action, component, etc.).

        Returns:
            A FailureLearning containing antibody, vaccine, and optional catalyst.
        """
        now = datetime.now(timezone.utc)
        action = context.get("action", "this operation")
        component = context.get("component", "unknown")

        # Match error against known patterns
        matched = self._match_error_pattern(error)
        rule_template = matched["rule_template"]
        severity = matched["severity"]
        root_cause = matched["root_cause"]
        target_system = matched.get("system", "general")

        # Track error pattern occurrences for catalyst generation
        pattern_key = target_system
        self._error_counts[pattern_key] = self._error_counts.get(pattern_key, 0) + 1

        # Generate antibody
        antibody = Antibody(
            rule=rule_template.format(action=action),
            source_error=error,
            created_at=now,
            severity=severity,
        )

        # Generate vaccine
        vaccine = Vaccine(
            scenario=f"Test {component} when {self._describe_failure_condition(error)}",
            expected=f"System handles the error gracefully for {action}",
            actual=f"Failure occurred: {error[:200]}",
            root_cause=root_cause,
            created_at=now,
        )

        # Generate catalyst only for recurring (systemic) patterns
        catalyst: Catalyst | None = None
        if self._error_counts[pattern_key] >= 3:
            catalyst = Catalyst(
                proposal=f"Add automated {target_system} safeguard for {component}",
                target_system=target_system,
                priority=self._catalyst_priority(severity, self._error_counts[pattern_key]),
                created_at=now,
            )

        learning = FailureLearning(
            antibody=antibody,
            vaccine=vaccine,
            catalyst=catalyst,
            task_id=task_id,
            agent_id=agent_id,
            created_at=now,
        )

        self._learnings.append(learning)
        return learning

    async def emit_learning_event(self, learning: FailureLearning) -> None:
        """Emit a learning event to the event bus for audit trail.

        Args:
            learning: The failure learning to emit as an event.
        """
        if self._event_bus is None:
            return

        payload = {
            "task_id": str(learning.task_id),
            "agent_id": str(learning.agent_id),
            "antibody_rule": learning.antibody.rule,
            "antibody_severity": learning.antibody.severity,
            "vaccine_scenario": learning.vaccine.scenario,
            "has_catalyst": learning.catalyst is not None,
            "created_at": learning.created_at.isoformat(),
        }

        await self._event_bus.publish(
            event_type="failure_learning.created",
            payload=payload,
            source_agent_id=learning.agent_id,
        )

    def get_antibodies(self) -> list[Antibody]:
        """Retrieve all generated antibodies.

        Returns:
            List of all Antibody artifacts created from analyzed failures.
        """
        return [learning.antibody for learning in self._learnings]

    def get_vaccines(self) -> list[Vaccine]:
        """Retrieve all generated vaccines.

        Returns:
            List of all Vaccine artifacts created from analyzed failures.
        """
        return [learning.vaccine for learning in self._learnings]

    def get_catalysts(self) -> list[Catalyst]:
        """Retrieve all generated catalysts (non-None only).

        Returns:
            List of all Catalyst artifacts created from systemic failures.
        """
        return [
            learning.catalyst
            for learning in self._learnings
            if learning.catalyst is not None
        ]

    def _match_error_pattern(self, error: str) -> dict[str, Any]:
        """Match an error message against known patterns.

        Args:
            error: The error message to match.

        Returns:
            The matching pattern dict or the default pattern.
        """
        for pattern_def in _ERROR_PATTERNS:
            if pattern_def["pattern"].search(error):
                return pattern_def
        return _DEFAULT_PATTERN

    def _describe_failure_condition(self, error: str) -> str:
        """Generate a human-readable failure condition description.

        Args:
            error: The error message to describe.

        Returns:
            A short description of the failure condition.
        """
        lower = error.lower()
        if "timeout" in lower or "timed out" in lower:
            return "operation times out"
        if "permission" in lower or "denied" in lower or "forbidden" in lower:
            return "permissions are insufficient"
        if "not found" in lower or "404" in lower or "missing" in lower:
            return "required resource is missing"
        if "connection" in lower or "refused" in lower or "unreachable" in lower:
            return "connection is unavailable"
        if "rate limit" in lower or "throttl" in lower or "429" in lower:
            return "rate limit is exceeded"
        if "budget" in lower or "cost" in lower or "exceeded limit" in lower:
            return "budget limit is reached"
        if "memory" in lower or "oom" in lower:
            return "memory is exhausted"
        if "deadlock" in lower or "lock timeout" in lower:
            return "concurrent access conflicts"
        return "an unexpected error occurs"

    def _catalyst_priority(self, severity: str, occurrence_count: int) -> str:
        """Determine catalyst priority based on severity and frequency.

        Args:
            severity: The severity of the underlying error.
            occurrence_count: How many times this pattern has occurred.

        Returns:
            Priority level: 'low', 'medium', or 'high'.
        """
        if severity == "critical" or occurrence_count >= 5:
            return "high"
        if severity == "high" or occurrence_count >= 4:
            return "medium"
        return "low"
