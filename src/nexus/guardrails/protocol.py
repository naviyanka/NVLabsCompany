"""Guardrail Protocol and Result types for the async guardrail system.

Defines the GuardrailResult dataclass and GuardrailProtocol - a runtime-checkable
Protocol that guardrail implementations must satisfy.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable


@dataclass
class GuardrailResult:
    """Result of a guardrail validation check.

    Attributes:
        passed: Whether the validation passed without violations.
        violations: List of human-readable violation descriptions.
        guardrail_name: Name of the guardrail that produced this result.
        metadata: Additional metadata about the validation.
    """

    passed: bool
    violations: list[str] = field(default_factory=list)
    guardrail_name: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@runtime_checkable
class GuardrailProtocol(Protocol):
    """Protocol for async guardrail implementations.

    All guardrails must implement this protocol to be usable in a GuardrailChain.
    The protocol is runtime-checkable, allowing isinstance() verification.
    """

    @property
    def name(self) -> str:
        """The unique identifier for this guardrail."""
        ...

    async def validate_input(
        self, input: Any, context: dict[str, Any]
    ) -> GuardrailResult:
        """Validate input before processing.

        Args:
            input: The input data to validate.
            context: Contextual information for validation decisions.

        Returns:
            A GuardrailResult indicating whether the input is acceptable.
        """
        ...

    async def validate_output(
        self, output: Any, context: dict[str, Any]
    ) -> GuardrailResult:
        """Validate output after processing.

        Args:
            output: The output data to validate.
            context: Contextual information for validation decisions.

        Returns:
            A GuardrailResult indicating whether the output is acceptable.
        """
        ...

    async def validate_tool_call(
        self, tool_name: str, args: dict[str, Any], context: dict[str, Any]
    ) -> GuardrailResult:
        """Validate a tool call before execution.

        Args:
            tool_name: Name of the tool being invoked.
            args: Arguments to the tool call.
            context: Contextual information for validation decisions.

        Returns:
            A GuardrailResult indicating whether the tool call is allowed.
        """
        ...
