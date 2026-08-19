"""Tests for condition expression system in context_trigger module."""

from datetime import datetime

import pytest

from nexus.triggers.context_trigger import (
    DEFAULT_CONTEXT_TRIGGER,
    AndCondition,
    ConditionBuilder,
    ConditionExpression,
    ContextRule,
    ContextTriggerConfig,
    NotCondition,
    OrCondition,
    ThresholdCondition,
    TimeCondition,
    evaluate_condition,
)

# ---------------------------------------------------------------------------
# Backward compatibility tests
# ---------------------------------------------------------------------------


class TestBackwardCompatibility:
    """Ensure existing ContextRule and DEFAULT_CONTEXT_TRIGGER still work."""

    def test_context_rule_importable(self) -> None:
        """ContextRule should still be importable and functional."""
        rule = ContextRule(
            enabled=True,
            every_seconds=3600,
            min_context_pct=50,
            min_context_pct_large_window=30,
            message="test",
        )
        assert rule.enabled is True
        assert rule.every_seconds == 3600

    def test_context_trigger_config_importable(self) -> None:
        """ContextTriggerConfig should still be importable and functional."""
        config = ContextTriggerConfig(
            compact=ContextRule(
                enabled=True,
                every_seconds=60,
                min_context_pct=50,
                min_context_pct_large_window=30,
                message="compact",
            ),
            clear=ContextRule(
                enabled=False,
                every_seconds=120,
                min_context_pct=90,
                min_context_pct_large_window=80,
                message="clear",
            ),
        )
        assert config.compact.enabled is True
        assert config.clear.enabled is False

    def test_default_context_trigger_unchanged(self) -> None:
        """DEFAULT_CONTEXT_TRIGGER should have original values."""
        assert DEFAULT_CONTEXT_TRIGGER.compact.enabled is True
        assert DEFAULT_CONTEXT_TRIGGER.compact.every_seconds == 7200
        assert DEFAULT_CONTEXT_TRIGGER.compact.min_context_pct == 60
        assert DEFAULT_CONTEXT_TRIGGER.compact.min_context_pct_large_window == 40
        assert DEFAULT_CONTEXT_TRIGGER.clear.enabled is False
        assert DEFAULT_CONTEXT_TRIGGER.clear.every_seconds == 7200
        assert DEFAULT_CONTEXT_TRIGGER.clear.min_context_pct == 90
        assert DEFAULT_CONTEXT_TRIGGER.clear.min_context_pct_large_window == 80


# ---------------------------------------------------------------------------
# AndCondition tests
# ---------------------------------------------------------------------------


class TestAndCondition:
    """Tests for AndCondition evaluation."""

    def test_all_true(self) -> None:
        """AndCondition is True when all sub-conditions are True."""
        cond = AndCondition(
            conditions=[
                ThresholdCondition(metric="a", operator=">", value=0.0),
                ThresholdCondition(metric="b", operator=">", value=0.0),
            ]
        )
        assert evaluate_condition(cond, {"a": 5.0, "b": 10.0}) is True

    def test_one_false(self) -> None:
        """AndCondition is False when any sub-condition is False."""
        cond = AndCondition(
            conditions=[
                ThresholdCondition(metric="a", operator=">", value=5.0),
                ThresholdCondition(metric="b", operator=">", value=5.0),
            ]
        )
        assert evaluate_condition(cond, {"a": 10.0, "b": 3.0}) is False

    def test_short_circuit(self) -> None:
        """AndCondition short-circuits: stops on first False.

        If the first condition is False, the second should never be evaluated.
        We verify by providing a context that would raise KeyError for the
        second condition's metric if it were evaluated.
        """
        cond = AndCondition(
            conditions=[
                ThresholdCondition(metric="a", operator=">", value=100.0),
                ThresholdCondition(metric="missing", operator=">", value=0.0),
            ]
        )
        # "a" < 100, so first condition is False; "missing" not in context
        # but should not be evaluated due to short-circuit
        assert evaluate_condition(cond, {"a": 1.0}) is False

    def test_empty_conditions_is_true(self) -> None:
        """AndCondition with no conditions evaluates to True (vacuous truth)."""
        cond = AndCondition(conditions=[])
        assert evaluate_condition(cond, {}) is True


# ---------------------------------------------------------------------------
# OrCondition tests
# ---------------------------------------------------------------------------


class TestOrCondition:
    """Tests for OrCondition evaluation."""

    def test_all_false(self) -> None:
        """OrCondition is False when all sub-conditions are False."""
        cond = OrCondition(
            conditions=[
                ThresholdCondition(metric="a", operator=">", value=100.0),
                ThresholdCondition(metric="b", operator=">", value=100.0),
            ]
        )
        assert evaluate_condition(cond, {"a": 1.0, "b": 2.0}) is False

    def test_one_true(self) -> None:
        """OrCondition is True when at least one sub-condition is True."""
        cond = OrCondition(
            conditions=[
                ThresholdCondition(metric="a", operator=">", value=100.0),
                ThresholdCondition(metric="b", operator=">", value=0.0),
            ]
        )
        assert evaluate_condition(cond, {"a": 1.0, "b": 5.0}) is True

    def test_short_circuit(self) -> None:
        """OrCondition short-circuits: stops on first True.

        If the first condition is True, the second should never be evaluated.
        """
        cond = OrCondition(
            conditions=[
                ThresholdCondition(metric="a", operator=">", value=0.0),
                ThresholdCondition(metric="missing", operator=">", value=0.0),
            ]
        )
        # "a" > 0 is True, so "missing" key never accessed
        assert evaluate_condition(cond, {"a": 5.0}) is True

    def test_empty_conditions_is_false(self) -> None:
        """OrCondition with no conditions evaluates to False."""
        cond = OrCondition(conditions=[])
        assert evaluate_condition(cond, {}) is False


# ---------------------------------------------------------------------------
# NotCondition tests
# ---------------------------------------------------------------------------


class TestNotCondition:
    """Tests for NotCondition evaluation."""

    def test_true_becomes_false(self) -> None:
        """NotCondition negates True to False."""
        cond = NotCondition(condition=ThresholdCondition(metric="a", operator=">", value=0.0))
        assert evaluate_condition(cond, {"a": 5.0}) is False

    def test_false_becomes_true(self) -> None:
        """NotCondition negates False to True."""
        cond = NotCondition(condition=ThresholdCondition(metric="a", operator=">", value=100.0))
        assert evaluate_condition(cond, {"a": 5.0}) is True


# ---------------------------------------------------------------------------
# ThresholdCondition tests
# ---------------------------------------------------------------------------


class TestThresholdCondition:
    """Tests for ThresholdCondition with all operators."""

    def test_greater_than(self) -> None:
        """Operator '>' works correctly."""
        cond = ThresholdCondition(metric="x", operator=">", value=5.0)
        assert evaluate_condition(cond, {"x": 6.0}) is True
        assert evaluate_condition(cond, {"x": 5.0}) is False
        assert evaluate_condition(cond, {"x": 4.0}) is False

    def test_less_than(self) -> None:
        """Operator '<' works correctly."""
        cond = ThresholdCondition(metric="x", operator="<", value=5.0)
        assert evaluate_condition(cond, {"x": 4.0}) is True
        assert evaluate_condition(cond, {"x": 5.0}) is False
        assert evaluate_condition(cond, {"x": 6.0}) is False

    def test_greater_than_or_equal(self) -> None:
        """Operator '>=' works correctly."""
        cond = ThresholdCondition(metric="x", operator=">=", value=5.0)
        assert evaluate_condition(cond, {"x": 6.0}) is True
        assert evaluate_condition(cond, {"x": 5.0}) is True
        assert evaluate_condition(cond, {"x": 4.0}) is False

    def test_less_than_or_equal(self) -> None:
        """Operator '<=' works correctly."""
        cond = ThresholdCondition(metric="x", operator="<=", value=5.0)
        assert evaluate_condition(cond, {"x": 4.0}) is True
        assert evaluate_condition(cond, {"x": 5.0}) is True
        assert evaluate_condition(cond, {"x": 6.0}) is False

    def test_equal(self) -> None:
        """Operator '==' works correctly."""
        cond = ThresholdCondition(metric="x", operator="==", value=5.0)
        assert evaluate_condition(cond, {"x": 5.0}) is True
        assert evaluate_condition(cond, {"x": 4.0}) is False

    def test_not_equal(self) -> None:
        """Operator '!=' works correctly."""
        cond = ThresholdCondition(metric="x", operator="!=", value=5.0)
        assert evaluate_condition(cond, {"x": 4.0}) is True
        assert evaluate_condition(cond, {"x": 5.0}) is False


# ---------------------------------------------------------------------------
# TimeCondition tests
# ---------------------------------------------------------------------------


class TestTimeCondition:
    """Tests for TimeCondition evaluation."""

    def test_after_passes(self) -> None:
        """TimeCondition passes when current_time is after 'after'."""
        cond = TimeCondition(after=datetime(2024, 1, 1, 12, 0, 0))
        ctx = {"current_time": datetime(2024, 1, 1, 13, 0, 0)}
        assert evaluate_condition(cond, ctx) is True

    def test_after_fails(self) -> None:
        """TimeCondition fails when current_time is before 'after'."""
        cond = TimeCondition(after=datetime(2024, 1, 1, 12, 0, 0))
        ctx = {"current_time": datetime(2024, 1, 1, 11, 0, 0)}
        assert evaluate_condition(cond, ctx) is False

    def test_before_passes(self) -> None:
        """TimeCondition passes when current_time is before 'before'."""
        cond = TimeCondition(before=datetime(2024, 1, 1, 12, 0, 0))
        ctx = {"current_time": datetime(2024, 1, 1, 11, 0, 0)}
        assert evaluate_condition(cond, ctx) is True

    def test_before_fails(self) -> None:
        """TimeCondition fails when current_time is at or after 'before'."""
        cond = TimeCondition(before=datetime(2024, 1, 1, 12, 0, 0))
        ctx = {"current_time": datetime(2024, 1, 1, 13, 0, 0)}
        assert evaluate_condition(cond, ctx) is False

    def test_weekday_passes(self) -> None:
        """TimeCondition passes when weekday is in allowed list."""
        # 2024-01-01 is a Monday (weekday=0)
        cond = TimeCondition(weekdays=[0, 1, 2])
        ctx = {"current_time": datetime(2024, 1, 1, 10, 0, 0)}
        assert evaluate_condition(cond, ctx) is True

    def test_weekday_fails(self) -> None:
        """TimeCondition fails when weekday is not in allowed list."""
        # 2024-01-01 is a Monday (weekday=0)
        cond = TimeCondition(weekdays=[5, 6])  # Saturday, Sunday only
        ctx = {"current_time": datetime(2024, 1, 1, 10, 0, 0)}
        assert evaluate_condition(cond, ctx) is False

    def test_combined_after_and_weekday(self) -> None:
        """TimeCondition with both after and weekdays checks both."""
        # 2024-01-03 is a Wednesday (weekday=2)
        cond = TimeCondition(after=datetime(2024, 1, 3, 9, 0, 0), weekdays=[2])
        ctx = {"current_time": datetime(2024, 1, 3, 10, 0, 0)}
        assert evaluate_condition(cond, ctx) is True

    def test_no_constraints_passes(self) -> None:
        """TimeCondition with no constraints always passes."""
        cond = TimeCondition()
        ctx = {"current_time": datetime(2024, 6, 15, 14, 30, 0)}
        assert evaluate_condition(cond, ctx) is True

    def test_uses_datetime_now_when_no_current_time(self) -> None:
        """TimeCondition uses datetime.now() when context has no current_time."""
        # A very far future 'before' should still pass with now()
        cond = TimeCondition(before=datetime(2099, 12, 31, 23, 59, 59))
        assert evaluate_condition(cond, {}) is True


# ---------------------------------------------------------------------------
# Nested conditions tests
# ---------------------------------------------------------------------------


class TestNestedConditions:
    """Tests for nested/composed condition expressions."""

    def test_and_containing_or(self) -> None:
        """And condition containing an Or condition evaluates correctly."""
        cond = AndCondition(
            conditions=[
                OrCondition(
                    conditions=[
                        ThresholdCondition(metric="a", operator=">", value=10.0),
                        ThresholdCondition(metric="b", operator=">", value=10.0),
                    ]
                ),
                ThresholdCondition(metric="c", operator="<", value=5.0),
            ]
        )
        # a=1 (false), b=20 (true) -> Or is True; c=3 < 5 -> True
        assert evaluate_condition(cond, {"a": 1.0, "b": 20.0, "c": 3.0}) is True
        # a=1 (false), b=1 (false) -> Or is False; whole And is False
        assert evaluate_condition(cond, {"a": 1.0, "b": 1.0, "c": 3.0}) is False

    def test_or_containing_and(self) -> None:
        """Or condition containing an And condition evaluates correctly."""
        cond = OrCondition(
            conditions=[
                AndCondition(
                    conditions=[
                        ThresholdCondition(metric="a", operator=">", value=5.0),
                        ThresholdCondition(metric="b", operator=">", value=5.0),
                    ]
                ),
                ThresholdCondition(metric="c", operator="==", value=0.0),
            ]
        )
        # And: a=10>5(T), b=10>5(T) -> T; Or short-circuits
        assert evaluate_condition(cond, {"a": 10.0, "b": 10.0, "c": 99.0}) is True
        # And: a=1>5(F) -> F; c=0==0 -> T
        assert evaluate_condition(cond, {"a": 1.0, "b": 1.0, "c": 0.0}) is True
        # And: a=1(F) -> F; c=1!=0 -> F
        assert evaluate_condition(cond, {"a": 1.0, "b": 1.0, "c": 1.0}) is False

    def test_not_containing_and(self) -> None:
        """Not wrapping an And condition negates the result."""
        inner = AndCondition(
            conditions=[
                ThresholdCondition(metric="a", operator=">", value=0.0),
                ThresholdCondition(metric="b", operator=">", value=0.0),
            ]
        )
        cond = NotCondition(condition=inner)
        # Both true -> And is True -> Not is False
        assert evaluate_condition(cond, {"a": 5.0, "b": 5.0}) is False
        # One false -> And is False -> Not is True
        assert evaluate_condition(cond, {"a": 5.0, "b": -1.0}) is True

    def test_deeply_nested(self) -> None:
        """Deeply nested conditions evaluate correctly."""
        cond = AndCondition(
            conditions=[
                NotCondition(
                    condition=OrCondition(
                        conditions=[
                            ThresholdCondition(metric="x", operator=">", value=100.0),
                            ThresholdCondition(metric="y", operator=">", value=100.0),
                        ]
                    )
                ),
                ThresholdCondition(metric="z", operator=">=", value=1.0),
            ]
        )
        # x=1, y=1 -> Or(F,F)=F -> Not=T; z=5>=1 -> T; And=T
        assert evaluate_condition(cond, {"x": 1.0, "y": 1.0, "z": 5.0}) is True
        # x=200 -> Or(T,...)=T -> Not=F; And=F
        assert evaluate_condition(cond, {"x": 200.0, "y": 1.0, "z": 5.0}) is False


# ---------------------------------------------------------------------------
# Unknown expression type
# ---------------------------------------------------------------------------


class TestUnknownExpression:
    """Tests for TypeError on unknown expression types."""

    def test_raises_type_error_for_unknown(self) -> None:
        """evaluate_condition raises TypeError for unknown expression types."""

        class UnknownExpr(ConditionExpression):
            """Custom unknown expression."""

        with pytest.raises(TypeError, match="Unknown condition expression type"):
            evaluate_condition(UnknownExpr(), {})


# ---------------------------------------------------------------------------
# ConditionBuilder tests
# ---------------------------------------------------------------------------


class TestConditionBuilder:
    """Tests for the ConditionBuilder fluent API."""

    def test_threshold_build(self) -> None:
        """Builder.threshold() produces a ThresholdCondition."""
        expr = ConditionBuilder().threshold("cpu", ">", 80.0).build()
        assert isinstance(expr, ThresholdCondition)
        assert expr.metric == "cpu"
        assert expr.operator == ">"
        assert expr.value == 80.0

    def test_time_build(self) -> None:
        """Builder.time() produces a TimeCondition."""
        after = datetime(2024, 1, 1)
        expr = ConditionBuilder().time(after=after, weekdays=[0, 1]).build()
        assert isinstance(expr, TimeCondition)
        assert expr.after == after
        assert expr.before is None
        assert expr.weekdays == [0, 1]

    def test_and_build(self) -> None:
        """Builder.and_() produces an AndCondition."""
        c1 = ThresholdCondition(metric="a", operator=">", value=1.0)
        c2 = ThresholdCondition(metric="b", operator="<", value=10.0)
        expr = ConditionBuilder().and_(c1, c2).build()
        assert isinstance(expr, AndCondition)
        assert len(expr.conditions) == 2
        assert expr.conditions[0] is c1
        assert expr.conditions[1] is c2

    def test_or_build(self) -> None:
        """Builder.or_() produces an OrCondition."""
        c1 = ThresholdCondition(metric="a", operator=">", value=1.0)
        c2 = ThresholdCondition(metric="b", operator="<", value=10.0)
        expr = ConditionBuilder().or_(c1, c2).build()
        assert isinstance(expr, OrCondition)
        assert len(expr.conditions) == 2

    def test_not_build(self) -> None:
        """Builder.not_() produces a NotCondition."""
        inner = ThresholdCondition(metric="a", operator=">", value=1.0)
        expr = ConditionBuilder().not_(inner).build()
        assert isinstance(expr, NotCondition)
        assert expr.condition is inner

    def test_chaining_overwrites_previous(self) -> None:
        """Later builder calls overwrite the previous expression."""
        builder = ConditionBuilder()
        builder.threshold("a", ">", 1.0)
        builder.threshold("b", "<", 5.0)
        expr = builder.build()
        assert isinstance(expr, ThresholdCondition)
        assert expr.metric == "b"

    def test_build_without_setting_raises(self) -> None:
        """Building without setting a condition raises ValueError."""
        with pytest.raises(ValueError, match="No condition has been set"):
            ConditionBuilder().build()

    def test_builder_produces_evaluable_expression(self) -> None:
        """Expressions from builder can be evaluated correctly."""
        expr = (
            ConditionBuilder()
            .and_(
                ThresholdCondition(metric="cpu", operator=">", value=50.0),
                ThresholdCondition(metric="mem", operator="<", value=90.0),
            )
            .build()
        )
        assert evaluate_condition(expr, {"cpu": 75.0, "mem": 60.0}) is True
        assert evaluate_condition(expr, {"cpu": 30.0, "mem": 60.0}) is False
