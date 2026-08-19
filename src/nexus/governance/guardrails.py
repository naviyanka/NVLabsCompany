"""Guardrail Chain - validates outputs against structural, content, and policy rules.

.. deprecated::
    This module is the legacy synchronous guardrail implementation. For new code,
    prefer the async guardrail system in ``nexus.guardrails`` which provides:
    - Protocol-based composition (``GuardrailProtocol``)
    - Async execution with ``GuardrailChain``
    - Fail-fast and fail-closed semantics
    - ``StructuralGuardrail`` and ``PolicyGuardrail`` implementations

    This module (``nexus.governance.guardrails``) is maintained for backward
    compatibility and will be consolidated into ``nexus.guardrails`` in a future
    release. Do not add new guardrail logic here.
"""

import re
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable


@dataclass
class GuardrailResult:
    """Result of guardrail validation.

    Attributes:
        passed: Whether all guardrails passed.
        violations: List of violation descriptions.
        guardrail_name: Name of the first failing guardrail, if any.
    """

    passed: bool
    violations: list[str] = field(default_factory=list)
    guardrail_name: str | None = None


@runtime_checkable
class Guardrail(Protocol):
    """Protocol for individual guardrail implementations."""

    @property
    def name(self) -> str:
        """The guardrail's identifier."""
        ...

    def validate(self, output: Any, context: dict[str, Any] | None = None) -> GuardrailResult:
        """Validate output against this guardrail's rules.

        Args:
            output: The output to validate.
            context: Optional context for validation.

        Returns:
            A GuardrailResult indicating pass/fail.
        """
        ...


class StructuralGuardrail:
    """Validates output against a JSON schema structure.

    Checks that the output conforms to expected types, required fields,
    and structural constraints.
    """

    def __init__(
        self, name: str = "structural", schema: dict[str, Any] | None = None
    ) -> None:
        """Initialize the structural guardrail.

        Args:
            name: Identifier for this guardrail.
            schema: JSON Schema to validate against.
        """
        self._name = name
        self._schema = schema or {}

    @property
    def name(self) -> str:
        """The guardrail's identifier."""
        return self._name

    def validate(
        self, output: Any, context: dict[str, Any] | None = None
    ) -> GuardrailResult:
        """Validate output structure against the configured schema.

        Args:
            output: The output to validate.
            context: Optional context.

        Returns:
            A GuardrailResult.
        """
        violations: list[str] = []

        if not self._schema:
            return GuardrailResult(passed=True)

        expected_type = self._schema.get("type")
        if expected_type:
            if expected_type == "object" and not isinstance(output, dict):
                violations.append(f"Expected object, got {type(output).__name__}")
            elif expected_type == "string" and not isinstance(output, str):
                violations.append(f"Expected string, got {type(output).__name__}")
            elif expected_type == "array" and not isinstance(output, list):
                violations.append(f"Expected array, got {type(output).__name__}")

        # Check required fields for objects
        if isinstance(output, dict):
            required = self._schema.get("required", [])
            for field_name in required:
                if field_name not in output:
                    violations.append(f"Missing required field: {field_name}")

        return GuardrailResult(
            passed=len(violations) == 0,
            violations=violations,
            guardrail_name=self._name if violations else None,
        )


class ContentGuardrail:
    """Validates content safety: blocked patterns, maximum length, etc."""

    def __init__(
        self,
        name: str = "content",
        blocked_patterns: list[str] | None = None,
        max_length: int | None = None,
        min_length: int | None = None,
    ) -> None:
        """Initialize the content guardrail.

        Args:
            name: Identifier for this guardrail.
            blocked_patterns: Regex patterns that should not appear in output.
            max_length: Maximum allowed output length.
            min_length: Minimum required output length.
        """
        self._name = name
        self._blocked_patterns = blocked_patterns or []
        self._max_length = max_length
        self._min_length = min_length

    @property
    def name(self) -> str:
        """The guardrail's identifier."""
        return self._name

    def validate(
        self, output: Any, context: dict[str, Any] | None = None
    ) -> GuardrailResult:
        """Validate content against safety rules.

        Args:
            output: The output to validate.
            context: Optional context.

        Returns:
            A GuardrailResult.
        """
        violations: list[str] = []
        text = str(output) if output is not None else ""

        # Check length constraints
        if self._max_length and len(text) > self._max_length:
            violations.append(
                f"Output exceeds maximum length: {len(text)} > {self._max_length}"
            )

        if self._min_length and len(text) < self._min_length:
            violations.append(
                f"Output below minimum length: {len(text)} < {self._min_length}"
            )

        # Check blocked patterns
        for pattern in self._blocked_patterns:
            if re.search(pattern, text, re.IGNORECASE):
                violations.append(f"Output contains blocked pattern: {pattern}")

        return GuardrailResult(
            passed=len(violations) == 0,
            violations=violations,
            guardrail_name=self._name if violations else None,
        )


class PolicyGuardrail:
    """Validates output against configurable business policy rules."""

    def __init__(
        self,
        name: str = "policy",
        rules: list[dict[str, Any]] | None = None,
    ) -> None:
        """Initialize the policy guardrail.

        Args:
            name: Identifier for this guardrail.
            rules: List of policy rules. Each rule is a dict with
                'field', 'operator', and 'value' keys.
        """
        self._name = name
        self._rules = rules or []

    @property
    def name(self) -> str:
        """The guardrail's identifier."""
        return self._name

    def validate(
        self, output: Any, context: dict[str, Any] | None = None
    ) -> GuardrailResult:
        """Validate output against configured policy rules.

        Args:
            output: The output to validate.
            context: Optional context.

        Returns:
            A GuardrailResult.
        """
        violations: list[str] = []

        if not isinstance(output, dict):
            # Policy rules only apply to structured (dict) output
            return GuardrailResult(passed=True)

        for rule in self._rules:
            field_name = rule.get("field", "")
            operator = rule.get("operator", "exists")
            value = rule.get("value")

            field_value = output.get(field_name)

            if operator == "exists" and field_value is None:
                violations.append(f"Policy violation: field '{field_name}' must exist")
            elif operator == "equals" and field_value != value:
                violations.append(
                    f"Policy violation: '{field_name}' must equal '{value}'"
                )
            elif operator == "not_equals" and field_value == value:
                violations.append(
                    f"Policy violation: '{field_name}' must not equal '{value}'"
                )
            elif operator == "max" and field_value is not None:
                if isinstance(field_value, (int, float)) and field_value > value:
                    violations.append(
                        f"Policy violation: '{field_name}' exceeds max ({field_value} > {value})"
                    )
            elif operator == "min" and field_value is not None:
                if isinstance(field_value, (int, float)) and field_value < value:
                    violations.append(
                        f"Policy violation: '{field_name}' below min ({field_value} < {value})"
                    )

        return GuardrailResult(
            passed=len(violations) == 0,
            violations=violations,
            guardrail_name=self._name if violations else None,
        )


class GuardrailChain:
    """Chains multiple guardrails and runs them in sequence.

    The chain runs all configured guardrails and returns the first
    failure, or a passing result if all guardrails pass.
    """

    def __init__(
        self,
        guardrails: list[Any] | None = None,
    ) -> None:
        """Initialize the guardrail chain.

        Args:
            guardrails: List of guardrail instances to chain.
        """
        self._guardrails: list[Any] = guardrails or []

    def add_guardrail(self, guardrail: Any) -> None:
        """Add a guardrail to the chain.

        Args:
            guardrail: A guardrail instance with a validate method.
        """
        self._guardrails.append(guardrail)

    def validate(
        self, output: Any, rules: dict[str, Any] | None = None
    ) -> GuardrailResult:
        """Run all guardrails in sequence and return first failure.

        Args:
            output: The output to validate.
            rules: Optional additional rules/context passed to guardrails.

        Returns:
            A GuardrailResult. Returns the first failing result,
            or a passing result if all guardrails pass.
        """
        all_violations: list[str] = []

        for guardrail in self._guardrails:
            result = guardrail.validate(output, context=rules)
            if not result.passed:
                return result
            all_violations.extend(result.violations)

        return GuardrailResult(passed=True, violations=all_violations)
