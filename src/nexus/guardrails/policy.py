"""PolicyGuardrail - validates content against security and policy rules.

Checks for blocked patterns (regex), sensitive file paths, dangerous commands,
and tool call whitelisting.
"""

from __future__ import annotations

import re
from typing import Any

from nexus.guardrails.protocol import GuardrailResult


class PolicyGuardrail:
    """Validates content against configurable security and policy rules.

    Checks:
        - blocked_patterns: Regex patterns that should not appear in content.
        - sensitive_paths: File paths that should not be accessed.
        - dangerous_commands: Shell commands that should be blocked.
        - allowed_tools: Whitelist of tool names allowed for tool calls.
    """

    def __init__(
        self,
        name: str = "policy",
        blocked_patterns: list[str] | None = None,
        sensitive_paths: list[str] | None = None,
        dangerous_commands: list[str] | None = None,
        allowed_tools: list[str] | None = None,
    ) -> None:
        """Initialize the policy guardrail.

        Args:
            name: Identifier for this guardrail.
            blocked_patterns: Regex patterns that should not appear in content.
            sensitive_paths: File paths that should not be referenced.
            dangerous_commands: Shell commands that should be blocked.
            allowed_tools: Whitelist of allowed tool names. If None, all tools allowed.
        """
        self._name = name
        self._blocked_patterns = blocked_patterns or []
        self._sensitive_paths = sensitive_paths or []
        self._dangerous_commands = dangerous_commands or []
        self._allowed_tools = allowed_tools

    @property
    def name(self) -> str:
        """The guardrail's identifier."""
        return self._name

    async def validate_input(
        self, input: Any, context: dict[str, Any]
    ) -> GuardrailResult:
        """Validate input against policy rules.

        Args:
            input: The input data to validate.
            context: Contextual information.

        Returns:
            A GuardrailResult.
        """
        return self._validate_content(input)

    async def validate_output(
        self, output: Any, context: dict[str, Any]
    ) -> GuardrailResult:
        """Validate output against policy rules.

        Args:
            output: The output data to validate.
            context: Contextual information.

        Returns:
            A GuardrailResult.
        """
        return self._validate_content(output)

    async def validate_tool_call(
        self, tool_name: str, args: dict[str, Any], context: dict[str, Any]
    ) -> GuardrailResult:
        """Validate a tool call against the allowed tools whitelist.

        Args:
            tool_name: Name of the tool being invoked.
            args: Arguments to the tool call.
            context: Contextual information.

        Returns:
            A GuardrailResult indicating whether the tool call is allowed.
        """
        violations: list[str] = []

        # Check allowed tools whitelist
        if self._allowed_tools is not None and tool_name not in self._allowed_tools:
            violations.append(
                f"Tool '{tool_name}' is not in the allowed tools list"
            )

        # Check args for sensitive paths
        args_str = str(args)
        for path in self._sensitive_paths:
            if path in args_str:
                violations.append(
                    f"Tool call references sensitive path: {path}"
                )

        # Check args for dangerous commands
        for cmd in self._dangerous_commands:
            if cmd in args_str:
                violations.append(
                    f"Tool call contains dangerous command: {cmd}"
                )

        return GuardrailResult(
            passed=len(violations) == 0,
            violations=violations,
            guardrail_name=self._name if violations else None,
        )

    def _validate_content(self, data: Any) -> GuardrailResult:
        """Validate content against blocked patterns, paths, and commands.

        Args:
            data: The data to validate.

        Returns:
            A GuardrailResult with any violations found.
        """
        violations: list[str] = []
        text = str(data) if data is not None else ""

        # Check blocked patterns
        for pattern in self._blocked_patterns:
            if re.search(pattern, text, re.IGNORECASE):
                violations.append(f"Content matches blocked pattern: {pattern}")

        # Check sensitive paths
        for path in self._sensitive_paths:
            if path in text:
                violations.append(f"Content references sensitive path: {path}")

        # Check dangerous commands
        for cmd in self._dangerous_commands:
            if cmd in text:
                violations.append(f"Content contains dangerous command: {cmd}")

        return GuardrailResult(
            passed=len(violations) == 0,
            violations=violations,
            guardrail_name=self._name if violations else None,
        )
