"""StructuralGuardrail - validates output structure, lengths, and required fields.

Performs structural validation without external dependencies. Supports max/min
length checks, required field checks for dict outputs, basic JSON schema type
validation, and non-empty output validation.
"""

from __future__ import annotations

from typing import Any

from nexus.guardrails.protocol import GuardrailResult


class StructuralGuardrail:
    """Validates output against structural constraints.

    Checks:
        - max_length: Maximum string length of the output.
        - min_length: Minimum string length of the output.
        - required_fields: Fields that must be present in dict outputs.
        - json_schema: Basic type and required field validation.
        - non_empty: Ensures output is not empty/None.
    """

    def __init__(
        self,
        name: str = "structural",
        max_length: int | None = None,
        min_length: int | None = None,
        required_fields: list[str] | None = None,
        json_schema: dict[str, Any] | None = None,
        non_empty: bool = False,
    ) -> None:
        """Initialize the structural guardrail.

        Args:
            name: Identifier for this guardrail.
            max_length: Maximum allowed length (for string representation).
            min_length: Minimum required length (for string representation).
            required_fields: List of field names required in dict outputs.
            json_schema: Basic JSON schema for type and required field validation.
            non_empty: If True, reject empty/None outputs.
        """
        self._name = name
        self._max_length = max_length
        self._min_length = min_length
        self._required_fields = required_fields or []
        self._json_schema = json_schema or {}
        self._non_empty = non_empty

    @property
    def name(self) -> str:
        """The guardrail's identifier."""
        return self._name

    async def validate_input(
        self, input: Any, context: dict[str, Any]
    ) -> GuardrailResult:
        """Validate input against structural constraints.

        Args:
            input: The input data to validate.
            context: Contextual information.

        Returns:
            A GuardrailResult.
        """
        return self._validate(input)

    async def validate_output(
        self, output: Any, context: dict[str, Any]
    ) -> GuardrailResult:
        """Validate output against structural constraints.

        Args:
            output: The output data to validate.
            context: Contextual information.

        Returns:
            A GuardrailResult.
        """
        return self._validate(output)

    async def validate_tool_call(
        self, tool_name: str, args: dict[str, Any], context: dict[str, Any]
    ) -> GuardrailResult:
        """Validate a tool call (structural guardrail passes all tool calls).

        Args:
            tool_name: Name of the tool being invoked.
            args: Arguments to the tool call.
            context: Contextual information.

        Returns:
            A passing GuardrailResult (structural checks are not applicable to tool calls).
        """
        return GuardrailResult(passed=True, guardrail_name=self._name)

    def _validate(self, data: Any) -> GuardrailResult:
        """Perform the actual structural validation.

        Args:
            data: The data to validate.

        Returns:
            A GuardrailResult with any violations found.
        """
        violations: list[str] = []

        # Non-empty check
        if self._non_empty:
            if data is None:
                violations.append("Output must not be empty (got None)")
            elif isinstance(data, str) and len(data.strip()) == 0:
                violations.append("Output must not be empty (got empty string)")
            elif isinstance(data, (list, dict)) and len(data) == 0:
                violations.append("Output must not be empty (got empty collection)")

        # Length checks (on string representation)
        if data is not None:
            text = str(data) if not isinstance(data, str) else data
            if self._max_length is not None and len(text) > self._max_length:
                violations.append(
                    f"Output exceeds maximum length: {len(text)} > {self._max_length}"
                )
            if self._min_length is not None and len(text) < self._min_length:
                violations.append(
                    f"Output below minimum length: {len(text)} < {self._min_length}"
                )

        # Required fields check (for dict outputs)
        if self._required_fields and isinstance(data, dict):
            for field_name in self._required_fields:
                if field_name not in data:
                    violations.append(f"Missing required field: {field_name}")

        # JSON schema validation (basic type and required checking)
        if self._json_schema:
            schema_violations = self._validate_schema(data)
            violations.extend(schema_violations)

        return GuardrailResult(
            passed=len(violations) == 0,
            violations=violations,
            guardrail_name=self._name if violations else None,
        )

    def _validate_schema(self, data: Any) -> list[str]:
        """Validate data against the configured JSON schema (basic checks).

        Supports type checking (object, string, array, number, integer, boolean)
        and required field validation.

        Args:
            data: The data to validate.

        Returns:
            List of violation messages.
        """
        violations: list[str] = []

        expected_type = self._json_schema.get("type")
        if expected_type:
            type_map = {
                "object": dict,
                "string": str,
                "array": list,
                "number": (int, float),
                "integer": int,
                "boolean": bool,
            }
            expected_python_type = type_map.get(expected_type)
            if expected_python_type and not isinstance(data, expected_python_type):
                violations.append(
                    f"Expected type '{expected_type}', got '{type(data).__name__}'"
                )

        # Check required fields from schema (for object types)
        if isinstance(data, dict):
            required = self._json_schema.get("required", [])
            for field_name in required:
                if field_name not in data:
                    violations.append(f"Schema missing required field: {field_name}")

        return violations
