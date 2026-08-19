"""Context trigger configuration - rules for context compaction and clearing.

Defines configuration dataclasses for automatic context management triggers
that fire based on time intervals and context usage percentages.

Also provides a composable condition expression system for building complex
trigger conditions using logical operators, thresholds, and time constraints.
"""

from __future__ import annotations

import operator as op_module
from dataclasses import dataclass, field
from datetime import datetime


@dataclass(frozen=True)
class ContextRule:
    """A single context management rule.

    Attributes:
        enabled: Whether this rule is active.
        every_seconds: Interval in seconds between trigger evaluations.
        min_context_pct: Minimum context usage percentage to activate (standard window).
        min_context_pct_large_window: Minimum context usage percentage (large window).
        message: Instruction message when the rule fires.
    """

    enabled: bool
    every_seconds: int
    min_context_pct: int
    min_context_pct_large_window: int
    message: str


@dataclass(frozen=True)
class ContextTriggerConfig:
    """Configuration for context management triggers.

    Attributes:
        compact: Rule for context compaction (summarize and trim).
        clear: Rule for full context clearing.
    """

    compact: ContextRule
    clear: ContextRule


DEFAULT_CONTEXT_TRIGGER: ContextTriggerConfig = ContextTriggerConfig(
    compact=ContextRule(
        enabled=True,
        every_seconds=7200,
        min_context_pct=60,
        min_context_pct_large_window=40,
        message=(
            "Keep the current task, recent decisions, open questions, "
            "and file paths in play. Drop resolved tangents."
        ),
    ),
    clear=ContextRule(
        enabled=False,
        every_seconds=7200,
        min_context_pct=90,
        min_context_pct_large_window=80,
        message="",
    ),
)

# ---------------------------------------------------------------------------
# Condition Expression System
# ---------------------------------------------------------------------------

_OPERATORS: dict[str, object] = {
    ">": op_module.gt,
    "<": op_module.lt,
    ">=": op_module.ge,
    "<=": op_module.le,
    "==": op_module.eq,
    "!=": op_module.ne,
}


@dataclass(frozen=True)
class ConditionExpression:
    """Base marker class for all condition expressions."""


@dataclass(frozen=True)
class AndCondition(ConditionExpression):
    """Logical AND of multiple conditions.

    All child conditions must evaluate to True for this condition to be True.
    Uses short-circuit evaluation: stops on the first False result.

    Attributes:
        conditions: Child conditions to combine with logical AND.
    """

    conditions: list[ConditionExpression] = field(default_factory=list)


@dataclass(frozen=True)
class OrCondition(ConditionExpression):
    """Logical OR of multiple conditions.

    At least one child condition must evaluate to True for this to be True.
    Uses short-circuit evaluation: stops on the first True result.

    Attributes:
        conditions: Child conditions to combine with logical OR.
    """

    conditions: list[ConditionExpression] = field(default_factory=list)


@dataclass(frozen=True)
class NotCondition(ConditionExpression):
    """Logical NOT (negation) of a single condition.

    Attributes:
        condition: The condition to negate.
    """

    condition: ConditionExpression = field(default_factory=ConditionExpression)


@dataclass(frozen=True)
class ThresholdCondition(ConditionExpression):
    """Numeric threshold comparison against a context metric.

    Looks up ``context[metric]`` and compares it to ``value`` using
    the specified ``operator``.

    Attributes:
        metric: Key to look up in the context dictionary.
        operator: Comparison operator (one of '>', '<', '>=', '<=', '==', '!=').
        value: Numeric threshold to compare against.
    """

    metric: str = ""
    operator: str = ">"
    value: float = 0.0


@dataclass(frozen=True)
class TimeCondition(ConditionExpression):
    """Time-based condition checking current time against constraints.

    Evaluates against ``context.get("current_time")`` or ``datetime.now()``
    if not provided.

    Attributes:
        after: If set, current time must be after this datetime.
        before: If set, current time must be before this datetime.
        weekdays: If set, current weekday must be in this list
            (0=Monday, 6=Sunday).
    """

    after: datetime | None = None
    before: datetime | None = None
    weekdays: list[int] | None = None


def evaluate_condition(expression: ConditionExpression, context: dict) -> bool:
    """Recursively evaluate a condition expression against a context dict.

    Args:
        expression: The condition expression tree to evaluate.
        context: Dictionary of runtime values (metrics, current_time, etc.).

    Returns:
        True if the condition is satisfied, False otherwise.

    Raises:
        TypeError: If the expression is an unknown/unsupported type.
    """
    if isinstance(expression, AndCondition):
        return all(evaluate_condition(c, context) for c in expression.conditions)

    if isinstance(expression, OrCondition):
        return any(evaluate_condition(c, context) for c in expression.conditions)

    if isinstance(expression, NotCondition):
        return not evaluate_condition(expression.condition, context)

    if isinstance(expression, ThresholdCondition):
        metric_value = context[expression.metric]
        comparator = _OPERATORS[expression.operator]
        return bool(comparator(metric_value, expression.value))  # type: ignore[operator]

    if isinstance(expression, TimeCondition):
        now: datetime = context.get("current_time") or datetime.now()
        if expression.after is not None and now <= expression.after:
            return False
        if expression.before is not None and now >= expression.before:
            return False
        if expression.weekdays is not None and now.weekday() not in expression.weekdays:
            return False
        return True

    raise TypeError(f"Unknown condition expression type: {type(expression).__name__}")


class ConditionBuilder:
    """Fluent builder for constructing condition expressions.

    Example usage::

        condition = (
            ConditionBuilder()
            .threshold("cpu_usage", ">", 80.0)
            .and_(
                ThresholdCondition(metric="memory", operator=">", value=70.0),
                ThresholdCondition(metric="disk", operator=">", value=90.0),
            )
            .build()
        )
    """

    def __init__(self) -> None:
        """Initialize an empty ConditionBuilder."""
        self._expression: ConditionExpression | None = None

    def and_(self, *conditions: ConditionExpression) -> ConditionBuilder:
        """Combine conditions with logical AND.

        Args:
            *conditions: Two or more condition expressions.

        Returns:
            Self for method chaining.
        """
        self._expression = AndCondition(conditions=list(conditions))
        return self

    def or_(self, *conditions: ConditionExpression) -> ConditionBuilder:
        """Combine conditions with logical OR.

        Args:
            *conditions: Two or more condition expressions.

        Returns:
            Self for method chaining.
        """
        self._expression = OrCondition(conditions=list(conditions))
        return self

    def not_(self, condition: ConditionExpression) -> ConditionBuilder:
        """Negate a condition.

        Args:
            condition: The condition to negate.

        Returns:
            Self for method chaining.
        """
        self._expression = NotCondition(condition=condition)
        return self

    def threshold(self, metric: str, operator: str, value: float) -> ConditionBuilder:
        """Create a threshold comparison condition.

        Args:
            metric: Context key to compare.
            operator: Comparison operator ('>', '<', '>=', '<=', '==', '!=').
            value: Numeric threshold.

        Returns:
            Self for method chaining.
        """
        self._expression = ThresholdCondition(metric=metric, operator=operator, value=value)
        return self

    def time(
        self,
        after: datetime | None = None,
        before: datetime | None = None,
        weekdays: list[int] | None = None,
    ) -> ConditionBuilder:
        """Create a time-based condition.

        Args:
            after: Current time must be after this datetime.
            before: Current time must be before this datetime.
            weekdays: Allowed weekdays (0=Monday, 6=Sunday).

        Returns:
            Self for method chaining.
        """
        self._expression = TimeCondition(after=after, before=before, weekdays=weekdays)
        return self

    def build(self) -> ConditionExpression:
        """Build and return the condition expression.

        Returns:
            The constructed ConditionExpression.

        Raises:
            ValueError: If no condition has been set.
        """
        if self._expression is None:
            raise ValueError("No condition has been set on the builder.")
        return self._expression
