"""GuardrailChain - runs multiple guardrails in sequence with configurable behavior.

Supports fail-fast mode (short-circuit on first failure) and fail-closed behavior
(treat exceptions as failures rather than letting them propagate).
"""

from __future__ import annotations

from typing import Any

from nexus.guardrails.protocol import GuardrailProtocol, GuardrailResult


class GuardrailChain:
    """Chains multiple async guardrails and runs them in sequence.

    Features:
        - fail_fast: Stop at the first failure (default True).
        - fail_closed: If a guardrail raises an exception, treat it as a failure
          rather than propagating the exception (default True).

    When fail_fast is False, all guardrails are executed and violations are
    collected from all of them.
    """

    def __init__(
        self,
        guardrails: list[GuardrailProtocol] | None = None,
        fail_fast: bool = True,
        fail_closed: bool = True,
    ) -> None:
        """Initialize the guardrail chain.

        Args:
            guardrails: Initial list of guardrails to include in the chain.
            fail_fast: If True, stop on the first failing guardrail.
            fail_closed: If True, treat guardrail exceptions as failures.
        """
        self._guardrails: list[GuardrailProtocol] = list(guardrails or [])
        self._fail_fast = fail_fast
        self._fail_closed = fail_closed

    @property
    def fail_fast(self) -> bool:
        """Whether the chain stops at the first failure."""
        return self._fail_fast

    @property
    def fail_closed(self) -> bool:
        """Whether exceptions are treated as failures."""
        return self._fail_closed

    @property
    def guardrails(self) -> list[GuardrailProtocol]:
        """The list of guardrails in this chain."""
        return list(self._guardrails)

    def add(self, guardrail: GuardrailProtocol) -> None:
        """Add a guardrail to the end of the chain.

        Args:
            guardrail: A guardrail implementing the GuardrailProtocol.
        """
        self._guardrails.append(guardrail)

    def remove(self, name: str) -> bool:
        """Remove a guardrail by name.

        Args:
            name: The name of the guardrail to remove.

        Returns:
            True if a guardrail was removed, False if not found.
        """
        for i, guardrail in enumerate(self._guardrails):
            if guardrail.name == name:
                self._guardrails.pop(i)
                return True
        return False

    async def validate_input(
        self, input: Any, context: dict[str, Any] | None = None
    ) -> GuardrailResult:
        """Run all guardrails' validate_input in sequence.

        Args:
            input: The input data to validate.
            context: Optional contextual information.

        Returns:
            A combined GuardrailResult from all guardrails.
        """
        ctx = context or {}
        return await self._run_all("validate_input", input, ctx)

    async def validate_output(
        self, output: Any, context: dict[str, Any] | None = None
    ) -> GuardrailResult:
        """Run all guardrails' validate_output in sequence.

        Args:
            output: The output data to validate.
            context: Optional contextual information.

        Returns:
            A combined GuardrailResult from all guardrails.
        """
        ctx = context or {}
        return await self._run_all("validate_output", output, ctx)

    async def validate_tool_call(
        self, tool_name: str, args: dict[str, Any], context: dict[str, Any] | None = None
    ) -> GuardrailResult:
        """Run all guardrails' validate_tool_call in sequence.

        Args:
            tool_name: Name of the tool being invoked.
            args: Arguments to the tool call.
            context: Optional contextual information.

        Returns:
            A combined GuardrailResult from all guardrails.
        """
        ctx = context or {}
        return await self._run_tool_call_all(tool_name, args, ctx)

    async def _run_all(
        self, method_name: str, data: Any, context: dict[str, Any]
    ) -> GuardrailResult:
        """Run a validation method on all guardrails in sequence.

        Args:
            method_name: The method to call (validate_input or validate_output).
            data: The data to pass to the validation method.
            context: Contextual information.

        Returns:
            A combined GuardrailResult.
        """
        all_violations: list[str] = []
        failed = False
        first_failure_name: str | None = None

        for guardrail in self._guardrails:
            try:
                method = getattr(guardrail, method_name)
                result: GuardrailResult = await method(data, context)
            except Exception as exc:
                if self._fail_closed:
                    result = GuardrailResult(
                        passed=False,
                        violations=[
                            f"Guardrail '{guardrail.name}' raised an exception: {exc}"
                        ],
                        guardrail_name=guardrail.name,
                    )
                else:
                    raise

            if not result.passed:
                failed = True
                all_violations.extend(result.violations)
                if first_failure_name is None:
                    first_failure_name = result.guardrail_name or guardrail.name
                if self._fail_fast:
                    return GuardrailResult(
                        passed=False,
                        violations=all_violations,
                        guardrail_name=first_failure_name,
                    )
            else:
                all_violations.extend(result.violations)

        return GuardrailResult(
            passed=not failed,
            violations=all_violations,
            guardrail_name=first_failure_name,
        )

    async def _run_tool_call_all(
        self, tool_name: str, args: dict[str, Any], context: dict[str, Any]
    ) -> GuardrailResult:
        """Run validate_tool_call on all guardrails in sequence.

        Args:
            tool_name: Name of the tool being invoked.
            args: Arguments to the tool call.
            context: Contextual information.

        Returns:
            A combined GuardrailResult.
        """
        all_violations: list[str] = []
        failed = False
        first_failure_name: str | None = None

        for guardrail in self._guardrails:
            try:
                result: GuardrailResult = await guardrail.validate_tool_call(
                    tool_name, args, context
                )
            except Exception as exc:
                if self._fail_closed:
                    result = GuardrailResult(
                        passed=False,
                        violations=[
                            f"Guardrail '{guardrail.name}' raised an exception: {exc}"
                        ],
                        guardrail_name=guardrail.name,
                    )
                else:
                    raise

            if not result.passed:
                failed = True
                all_violations.extend(result.violations)
                if first_failure_name is None:
                    first_failure_name = result.guardrail_name or guardrail.name
                if self._fail_fast:
                    return GuardrailResult(
                        passed=False,
                        violations=all_violations,
                        guardrail_name=first_failure_name,
                    )
            else:
                all_violations.extend(result.violations)

        return GuardrailResult(
            passed=not failed,
            violations=all_violations,
            guardrail_name=first_failure_name,
        )
