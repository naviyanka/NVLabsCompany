"""Tests for the async guardrail system.

Covers: protocol conformance, chain fail-fast/fail-closed behavior, structural
guardrail validation (lengths, fields, schema), policy guardrail (blocked patterns,
sensitive paths, dangerous commands, tool call whitelisting).
"""

import asyncio
from typing import Any
from unittest.mock import AsyncMock

import pytest

from nexus.guardrails import (
    GuardrailChain,
    GuardrailProtocol,
    GuardrailResult,
    PolicyGuardrail,
    StructuralGuardrail,
)


# ============================================================
# Protocol Conformance Tests
# ============================================================


class TestGuardrailProtocolConformance:
    """Tests that implementations satisfy the GuardrailProtocol."""

    def test_structural_guardrail_is_protocol_instance(self):
        """StructuralGuardrail satisfies GuardrailProtocol at runtime."""
        guardrail = StructuralGuardrail()
        assert isinstance(guardrail, GuardrailProtocol)

    def test_policy_guardrail_is_protocol_instance(self):
        """PolicyGuardrail satisfies GuardrailProtocol at runtime."""
        guardrail = PolicyGuardrail()
        assert isinstance(guardrail, GuardrailProtocol)

    def test_guardrail_protocol_is_runtime_checkable(self):
        """GuardrailProtocol supports isinstance() checks."""

        class FakeGuardrail:
            """A guardrail that does not fully implement the protocol."""

            pass

        assert not isinstance(FakeGuardrail(), GuardrailProtocol)

    def test_structural_guardrail_has_name(self):
        """StructuralGuardrail exposes a name property."""
        guardrail = StructuralGuardrail(name="my_struct")
        assert guardrail.name == "my_struct"

    def test_policy_guardrail_has_name(self):
        """PolicyGuardrail exposes a name property."""
        guardrail = PolicyGuardrail(name="my_policy")
        assert guardrail.name == "my_policy"

    def test_guardrail_result_defaults(self):
        """GuardrailResult has correct default values."""
        result = GuardrailResult(passed=True)
        assert result.passed is True
        assert result.violations == []
        assert result.guardrail_name is None
        assert result.metadata == {}

    def test_guardrail_result_with_metadata(self):
        """GuardrailResult stores metadata correctly."""
        result = GuardrailResult(
            passed=False,
            violations=["test violation"],
            guardrail_name="test",
            metadata={"key": "value"},
        )
        assert result.passed is False
        assert result.violations == ["test violation"]
        assert result.guardrail_name == "test"
        assert result.metadata == {"key": "value"}


# ============================================================
# GuardrailChain Tests
# ============================================================


class TestGuardrailChainBasic:
    """Tests for basic GuardrailChain functionality."""

    def test_chain_add_and_remove(self):
        """Chain supports adding and removing guardrails."""
        chain = GuardrailChain()
        structural = StructuralGuardrail(name="struct1")
        policy = PolicyGuardrail(name="policy1")

        chain.add(structural)
        chain.add(policy)
        assert len(chain.guardrails) == 2

        removed = chain.remove("struct1")
        assert removed is True
        assert len(chain.guardrails) == 1
        assert chain.guardrails[0].name == "policy1"

    def test_chain_remove_nonexistent_returns_false(self):
        """Removing a non-existent guardrail returns False."""
        chain = GuardrailChain()
        removed = chain.remove("does_not_exist")
        assert removed is False

    def test_chain_properties(self):
        """Chain exposes fail_fast and fail_closed properties."""
        chain = GuardrailChain(fail_fast=False, fail_closed=False)
        assert chain.fail_fast is False
        assert chain.fail_closed is False

        chain2 = GuardrailChain(fail_fast=True, fail_closed=True)
        assert chain2.fail_fast is True
        assert chain2.fail_closed is True


class TestGuardrailChainValidation:
    """Tests for GuardrailChain validation execution."""

    def test_empty_chain_passes(self):
        """Empty chain passes all validations."""
        chain = GuardrailChain()
        result = asyncio.run(chain.validate_input("anything", {}))
        assert result.passed is True

    def test_chain_validates_input(self):
        """Chain runs validate_input on all guardrails."""
        structural = StructuralGuardrail(name="struct", max_length=10)
        chain = GuardrailChain(guardrails=[structural])

        result = asyncio.run(chain.validate_input("short", {}))
        assert result.passed is True

        result = asyncio.run(chain.validate_input("this is way too long for the limit", {}))
        assert result.passed is False
        assert any("maximum length" in v for v in result.violations)

    def test_chain_validates_output(self):
        """Chain runs validate_output on all guardrails."""
        structural = StructuralGuardrail(name="struct", min_length=20)
        chain = GuardrailChain(guardrails=[structural])

        result = asyncio.run(chain.validate_output("short", {}))
        assert result.passed is False
        assert any("minimum length" in v for v in result.violations)

    def test_chain_validates_tool_call(self):
        """Chain runs validate_tool_call on all guardrails."""
        policy = PolicyGuardrail(
            name="policy", allowed_tools=["safe_tool", "another_tool"]
        )
        chain = GuardrailChain(guardrails=[policy])

        result = asyncio.run(chain.validate_tool_call("safe_tool", {}, {}))
        assert result.passed is True

        result = asyncio.run(chain.validate_tool_call("dangerous_tool", {}, {}))
        assert result.passed is False
        assert any("not in the allowed tools" in v for v in result.violations)


class TestGuardrailChainFailFast:
    """Tests for fail-fast short-circuit behavior."""

    def test_fail_fast_stops_at_first_failure(self):
        """With fail_fast=True, chain stops on first failure."""
        first = StructuralGuardrail(name="first", max_length=5)
        second = StructuralGuardrail(name="second", min_length=100)
        chain = GuardrailChain(guardrails=[first, second], fail_fast=True)

        result = asyncio.run(chain.validate_output("too long string here", {}))
        assert result.passed is False
        assert result.guardrail_name == "first"
        # Only violations from the first guardrail
        assert any("maximum length" in v for v in result.violations)
        assert not any("minimum length" in v for v in result.violations)

    def test_no_fail_fast_collects_all_violations(self):
        """With fail_fast=False, chain collects violations from all guardrails."""
        first = StructuralGuardrail(name="first", max_length=5)
        second = StructuralGuardrail(name="second", required_fields=["missing"])
        chain = GuardrailChain(guardrails=[first, second], fail_fast=False)

        result = asyncio.run(chain.validate_output({"data": "too long string"}, {}))
        assert result.passed is False
        # Should have violations from both guardrails
        assert any("maximum length" in v for v in result.violations)
        assert any("Missing required field" in v for v in result.violations)

    def test_fail_fast_reports_first_failure_name(self):
        """Fail-fast reports the name of the first failing guardrail."""
        passing = StructuralGuardrail(name="passing_one", max_length=1000)
        failing = StructuralGuardrail(name="failing_one", max_length=3)
        chain = GuardrailChain(guardrails=[passing, failing], fail_fast=True)

        result = asyncio.run(chain.validate_output("hello", {}))
        assert result.passed is False
        assert result.guardrail_name == "failing_one"


class TestGuardrailChainFailClosed:
    """Tests for fail-closed exception handling."""

    def test_fail_closed_catches_exception(self):
        """With fail_closed=True, exceptions become failures."""

        class BrokenGuardrail:
            """A guardrail that raises an exception."""

            @property
            def name(self) -> str:
                return "broken"

            async def validate_input(self, input: Any, context: dict) -> GuardrailResult:
                raise RuntimeError("Something went wrong")

            async def validate_output(self, output: Any, context: dict) -> GuardrailResult:
                raise RuntimeError("Something went wrong")

            async def validate_tool_call(
                self, tool_name: str, args: dict, context: dict
            ) -> GuardrailResult:
                raise RuntimeError("Something went wrong")

        chain = GuardrailChain(guardrails=[BrokenGuardrail()], fail_closed=True)

        result = asyncio.run(chain.validate_input("test", {}))
        assert result.passed is False
        assert any("exception" in v.lower() for v in result.violations)
        assert result.guardrail_name == "broken"

    def test_fail_closed_false_propagates_exception(self):
        """With fail_closed=False, exceptions propagate."""

        class BrokenGuardrail:
            """A guardrail that raises an exception."""

            @property
            def name(self) -> str:
                return "broken"

            async def validate_input(self, input: Any, context: dict) -> GuardrailResult:
                raise RuntimeError("Kaboom")

            async def validate_output(self, output: Any, context: dict) -> GuardrailResult:
                raise RuntimeError("Kaboom")

            async def validate_tool_call(
                self, tool_name: str, args: dict, context: dict
            ) -> GuardrailResult:
                raise RuntimeError("Kaboom")

        chain = GuardrailChain(guardrails=[BrokenGuardrail()], fail_closed=False)

        with pytest.raises(RuntimeError, match="Kaboom"):
            asyncio.run(chain.validate_output("test", {}))

    def test_fail_closed_on_tool_call(self):
        """Fail-closed works for validate_tool_call as well."""

        class BrokenGuardrail:
            """A guardrail that raises on tool_call validation."""

            @property
            def name(self) -> str:
                return "broken_tool"

            async def validate_input(self, input: Any, context: dict) -> GuardrailResult:
                return GuardrailResult(passed=True)

            async def validate_output(self, output: Any, context: dict) -> GuardrailResult:
                return GuardrailResult(passed=True)

            async def validate_tool_call(
                self, tool_name: str, args: dict, context: dict
            ) -> GuardrailResult:
                raise ValueError("Tool validation error")

        chain = GuardrailChain(guardrails=[BrokenGuardrail()], fail_closed=True)
        result = asyncio.run(chain.validate_tool_call("some_tool", {}, {}))
        assert result.passed is False
        assert any("exception" in v.lower() for v in result.violations)

    def test_fail_closed_with_fail_fast_false_continues(self):
        """Fail-closed with fail_fast=False continues after exception."""

        class BrokenGuardrail:
            """A guardrail that raises."""

            @property
            def name(self) -> str:
                return "broken"

            async def validate_input(self, input: Any, context: dict) -> GuardrailResult:
                raise RuntimeError("Error!")

            async def validate_output(self, output: Any, context: dict) -> GuardrailResult:
                raise RuntimeError("Error!")

            async def validate_tool_call(
                self, tool_name: str, args: dict, context: dict
            ) -> GuardrailResult:
                raise RuntimeError("Error!")

        structural = StructuralGuardrail(name="struct", max_length=5)
        chain = GuardrailChain(
            guardrails=[BrokenGuardrail(), structural],
            fail_fast=False,
            fail_closed=True,
        )

        result = asyncio.run(chain.validate_output("too long text here", {}))
        assert result.passed is False
        # Should have violations from both the exception and the structural check
        assert any("exception" in v.lower() for v in result.violations)
        assert any("maximum length" in v for v in result.violations)


# ============================================================
# StructuralGuardrail Tests
# ============================================================


class TestStructuralGuardrailLengths:
    """Tests for StructuralGuardrail length validation."""

    def test_max_length_passes(self):
        """Output within max_length passes."""
        guardrail = StructuralGuardrail(max_length=100)
        result = asyncio.run(guardrail.validate_output("short text", {}))
        assert result.passed is True

    def test_max_length_fails(self):
        """Output exceeding max_length fails."""
        guardrail = StructuralGuardrail(max_length=5)
        result = asyncio.run(guardrail.validate_output("this is too long", {}))
        assert result.passed is False
        assert any("maximum length" in v for v in result.violations)

    def test_min_length_passes(self):
        """Output meeting min_length passes."""
        guardrail = StructuralGuardrail(min_length=5)
        result = asyncio.run(guardrail.validate_output("long enough", {}))
        assert result.passed is True

    def test_min_length_fails(self):
        """Output below min_length fails."""
        guardrail = StructuralGuardrail(min_length=50)
        result = asyncio.run(guardrail.validate_output("short", {}))
        assert result.passed is False
        assert any("minimum length" in v for v in result.violations)

    def test_both_length_constraints_pass(self):
        """Output within both min and max passes."""
        guardrail = StructuralGuardrail(min_length=5, max_length=20)
        result = asyncio.run(guardrail.validate_output("just right", {}))
        assert result.passed is True

    def test_both_length_constraints_fail_min(self):
        """Output below min when both constraints exist fails."""
        guardrail = StructuralGuardrail(min_length=20, max_length=100)
        result = asyncio.run(guardrail.validate_output("short", {}))
        assert result.passed is False


class TestStructuralGuardrailFields:
    """Tests for StructuralGuardrail required fields validation."""

    def test_required_fields_present(self):
        """Dict with all required fields passes."""
        guardrail = StructuralGuardrail(required_fields=["name", "age"])
        result = asyncio.run(
            guardrail.validate_output({"name": "Alice", "age": 30}, {})
        )
        assert result.passed is True

    def test_required_fields_missing(self):
        """Dict missing required fields fails."""
        guardrail = StructuralGuardrail(required_fields=["name", "age", "email"])
        result = asyncio.run(guardrail.validate_output({"name": "Alice"}, {}))
        assert result.passed is False
        assert any("age" in v for v in result.violations)
        assert any("email" in v for v in result.violations)

    def test_required_fields_on_non_dict_passes(self):
        """Required fields check is skipped for non-dict data."""
        guardrail = StructuralGuardrail(required_fields=["name"])
        result = asyncio.run(guardrail.validate_output("just a string", {}))
        assert result.passed is True


class TestStructuralGuardrailSchema:
    """Tests for StructuralGuardrail JSON schema validation."""

    def test_schema_type_object_passes(self):
        """Dict passes schema type 'object' check."""
        guardrail = StructuralGuardrail(json_schema={"type": "object"})
        result = asyncio.run(guardrail.validate_output({"key": "value"}, {}))
        assert result.passed is True

    def test_schema_type_object_fails_on_string(self):
        """String fails schema type 'object' check."""
        guardrail = StructuralGuardrail(json_schema={"type": "object"})
        result = asyncio.run(guardrail.validate_output("not an object", {}))
        assert result.passed is False
        assert any("Expected type" in v for v in result.violations)

    def test_schema_type_string_passes(self):
        """String passes schema type 'string' check."""
        guardrail = StructuralGuardrail(json_schema={"type": "string"})
        result = asyncio.run(guardrail.validate_output("hello", {}))
        assert result.passed is True

    def test_schema_type_string_fails_on_dict(self):
        """Dict fails schema type 'string' check."""
        guardrail = StructuralGuardrail(json_schema={"type": "string"})
        result = asyncio.run(guardrail.validate_output({"key": "value"}, {}))
        assert result.passed is False

    def test_schema_type_array_passes(self):
        """List passes schema type 'array' check."""
        guardrail = StructuralGuardrail(json_schema={"type": "array"})
        result = asyncio.run(guardrail.validate_output([1, 2, 3], {}))
        assert result.passed is True

    def test_schema_type_array_fails_on_string(self):
        """String fails schema type 'array' check."""
        guardrail = StructuralGuardrail(json_schema={"type": "array"})
        result = asyncio.run(guardrail.validate_output("not an array", {}))
        assert result.passed is False

    def test_schema_required_fields(self):
        """Schema required fields are validated."""
        guardrail = StructuralGuardrail(
            json_schema={"type": "object", "required": ["id", "status"]}
        )
        result = asyncio.run(guardrail.validate_output({"id": 1}, {}))
        assert result.passed is False
        assert any("status" in v for v in result.violations)

    def test_schema_required_fields_present(self):
        """Schema passes when all required fields present."""
        guardrail = StructuralGuardrail(
            json_schema={"type": "object", "required": ["id", "status"]}
        )
        result = asyncio.run(
            guardrail.validate_output({"id": 1, "status": "active"}, {})
        )
        assert result.passed is True

    def test_schema_number_type(self):
        """Number type validation works."""
        guardrail = StructuralGuardrail(json_schema={"type": "number"})
        result = asyncio.run(guardrail.validate_output(42.5, {}))
        assert result.passed is True

        result = asyncio.run(guardrail.validate_output("not a number", {}))
        assert result.passed is False

    def test_schema_integer_type(self):
        """Integer type validation works."""
        guardrail = StructuralGuardrail(json_schema={"type": "integer"})
        result = asyncio.run(guardrail.validate_output(42, {}))
        assert result.passed is True

        result = asyncio.run(guardrail.validate_output(42.5, {}))
        assert result.passed is False

    def test_schema_boolean_type(self):
        """Boolean type validation works."""
        guardrail = StructuralGuardrail(json_schema={"type": "boolean"})
        result = asyncio.run(guardrail.validate_output(True, {}))
        assert result.passed is True

        result = asyncio.run(guardrail.validate_output("true", {}))
        assert result.passed is False


class TestStructuralGuardrailNonEmpty:
    """Tests for StructuralGuardrail non-empty validation."""

    def test_non_empty_passes_with_content(self):
        """Non-empty check passes with actual content."""
        guardrail = StructuralGuardrail(non_empty=True)
        result = asyncio.run(guardrail.validate_output("content", {}))
        assert result.passed is True

    def test_non_empty_fails_with_none(self):
        """Non-empty check fails with None."""
        guardrail = StructuralGuardrail(non_empty=True)
        result = asyncio.run(guardrail.validate_output(None, {}))
        assert result.passed is False
        assert any("empty" in v.lower() for v in result.violations)

    def test_non_empty_fails_with_empty_string(self):
        """Non-empty check fails with empty string."""
        guardrail = StructuralGuardrail(non_empty=True)
        result = asyncio.run(guardrail.validate_output("", {}))
        assert result.passed is False

    def test_non_empty_fails_with_whitespace_only(self):
        """Non-empty check fails with whitespace-only string."""
        guardrail = StructuralGuardrail(non_empty=True)
        result = asyncio.run(guardrail.validate_output("   ", {}))
        assert result.passed is False

    def test_non_empty_fails_with_empty_list(self):
        """Non-empty check fails with empty list."""
        guardrail = StructuralGuardrail(non_empty=True)
        result = asyncio.run(guardrail.validate_output([], {}))
        assert result.passed is False

    def test_non_empty_fails_with_empty_dict(self):
        """Non-empty check fails with empty dict."""
        guardrail = StructuralGuardrail(non_empty=True)
        result = asyncio.run(guardrail.validate_output({}, {}))
        assert result.passed is False

    def test_non_empty_passes_with_zero(self):
        """Non-empty check passes with numeric zero (it is a value)."""
        guardrail = StructuralGuardrail(non_empty=True)
        result = asyncio.run(guardrail.validate_output(0, {}))
        assert result.passed is True


class TestStructuralGuardrailToolCall:
    """Tests for StructuralGuardrail tool call validation."""

    def test_tool_call_always_passes(self):
        """Structural guardrail passes all tool calls."""
        guardrail = StructuralGuardrail(
            max_length=5, required_fields=["x"], non_empty=True
        )
        result = asyncio.run(guardrail.validate_tool_call("any_tool", {}, {}))
        assert result.passed is True


# ============================================================
# PolicyGuardrail Tests
# ============================================================


class TestPolicyGuardrailBlockedPatterns:
    """Tests for PolicyGuardrail blocked patterns."""

    def test_blocked_pattern_detected_in_output(self):
        """Output matching a blocked pattern fails."""
        guardrail = PolicyGuardrail(blocked_patterns=[r"password\s*[:=]"])
        result = asyncio.run(
            guardrail.validate_output("The password: secret123", {})
        )
        assert result.passed is False
        assert any("blocked pattern" in v for v in result.violations)

    def test_blocked_pattern_not_matched_passes(self):
        """Output not matching blocked patterns passes."""
        guardrail = PolicyGuardrail(blocked_patterns=[r"password\s*[:=]"])
        result = asyncio.run(
            guardrail.validate_output("This is safe content", {})
        )
        assert result.passed is True

    def test_multiple_blocked_patterns(self):
        """Multiple blocked patterns are all checked."""
        guardrail = PolicyGuardrail(
            blocked_patterns=[r"secret", r"api_key", r"token\s*="]
        )
        result = asyncio.run(guardrail.validate_output("my api_key is here", {}))
        assert result.passed is False

        result = asyncio.run(guardrail.validate_output("token = abc123", {}))
        assert result.passed is False

    def test_blocked_pattern_case_insensitive(self):
        """Blocked pattern matching is case-insensitive."""
        guardrail = PolicyGuardrail(blocked_patterns=[r"SECRET"])
        result = asyncio.run(guardrail.validate_output("my secret value", {}))
        assert result.passed is False

    def test_blocked_pattern_in_input(self):
        """Blocked patterns are checked in input validation too."""
        guardrail = PolicyGuardrail(blocked_patterns=[r"DROP TABLE"])
        result = asyncio.run(guardrail.validate_input("DROP TABLE users;", {}))
        assert result.passed is False


class TestPolicyGuardrailSensitivePaths:
    """Tests for PolicyGuardrail sensitive path detection."""

    def test_sensitive_path_detected(self):
        """Output referencing a sensitive path fails."""
        guardrail = PolicyGuardrail(sensitive_paths=["/etc/passwd", "/etc/shadow"])
        result = asyncio.run(
            guardrail.validate_output("Reading file /etc/passwd", {})
        )
        assert result.passed is False
        assert any("sensitive path" in v for v in result.violations)

    def test_sensitive_path_not_present_passes(self):
        """Output without sensitive paths passes."""
        guardrail = PolicyGuardrail(sensitive_paths=["/etc/passwd"])
        result = asyncio.run(
            guardrail.validate_output("Reading /home/user/file.txt", {})
        )
        assert result.passed is True

    def test_sensitive_path_in_tool_call_args(self):
        """Sensitive paths detected in tool call arguments."""
        guardrail = PolicyGuardrail(sensitive_paths=["/etc/shadow"])
        result = asyncio.run(
            guardrail.validate_tool_call("read_file", {"path": "/etc/shadow"}, {})
        )
        assert result.passed is False
        assert any("sensitive path" in v for v in result.violations)


class TestPolicyGuardrailDangerousCommands:
    """Tests for PolicyGuardrail dangerous command detection."""

    def test_dangerous_command_detected(self):
        """Output containing a dangerous command fails."""
        guardrail = PolicyGuardrail(dangerous_commands=["rm -rf /", "sudo su"])
        result = asyncio.run(
            guardrail.validate_output("Execute: rm -rf / to clean up", {})
        )
        assert result.passed is False
        assert any("dangerous command" in v for v in result.violations)

    def test_dangerous_command_not_present_passes(self):
        """Output without dangerous commands passes."""
        guardrail = PolicyGuardrail(dangerous_commands=["rm -rf /"])
        result = asyncio.run(guardrail.validate_output("ls -la /tmp", {}))
        assert result.passed is True

    def test_dangerous_command_in_tool_call(self):
        """Dangerous commands detected in tool call arguments."""
        guardrail = PolicyGuardrail(dangerous_commands=["rm -rf /"])
        result = asyncio.run(
            guardrail.validate_tool_call(
                "execute_command", {"command": "rm -rf /"}, {}
            )
        )
        assert result.passed is False
        assert any("dangerous command" in v for v in result.violations)


class TestPolicyGuardrailAllowedTools:
    """Tests for PolicyGuardrail tool call whitelist."""

    def test_allowed_tool_passes(self):
        """Tool in the allowed list passes."""
        guardrail = PolicyGuardrail(allowed_tools=["read_file", "write_file"])
        result = asyncio.run(guardrail.validate_tool_call("read_file", {}, {}))
        assert result.passed is True

    def test_disallowed_tool_fails(self):
        """Tool not in the allowed list fails."""
        guardrail = PolicyGuardrail(allowed_tools=["read_file", "write_file"])
        result = asyncio.run(
            guardrail.validate_tool_call("execute_shell", {}, {})
        )
        assert result.passed is False
        assert any("not in the allowed tools" in v for v in result.violations)

    def test_no_allowed_tools_list_allows_all(self):
        """When allowed_tools is None, all tools pass."""
        guardrail = PolicyGuardrail(allowed_tools=None)
        result = asyncio.run(
            guardrail.validate_tool_call("any_tool_at_all", {}, {})
        )
        assert result.passed is True

    def test_empty_allowed_tools_blocks_all(self):
        """When allowed_tools is empty list, all tools are blocked."""
        guardrail = PolicyGuardrail(allowed_tools=[])
        result = asyncio.run(guardrail.validate_tool_call("any_tool", {}, {}))
        assert result.passed is False

    def test_combined_tool_checks(self):
        """Tool call checks both whitelist and sensitive paths."""
        guardrail = PolicyGuardrail(
            allowed_tools=["read_file"],
            sensitive_paths=["/etc/shadow"],
        )
        # Allowed tool but sensitive path
        result = asyncio.run(
            guardrail.validate_tool_call("read_file", {"path": "/etc/shadow"}, {})
        )
        assert result.passed is False
        assert any("sensitive path" in v for v in result.violations)

        # Allowed tool, safe path
        result = asyncio.run(
            guardrail.validate_tool_call("read_file", {"path": "/tmp/test.txt"}, {})
        )
        assert result.passed is True


# ============================================================
# Integration Tests
# ============================================================


class TestGuardrailChainIntegration:
    """Integration tests combining multiple guardrails."""

    def test_structural_and_policy_chain(self):
        """Chain with both structural and policy guardrails works."""
        structural = StructuralGuardrail(
            name="struct", max_length=200, non_empty=True
        )
        policy = PolicyGuardrail(
            name="policy", blocked_patterns=[r"secret"], dangerous_commands=["rm -rf"]
        )
        chain = GuardrailChain(guardrails=[structural, policy])

        # Valid output
        result = asyncio.run(chain.validate_output("Safe content here", {}))
        assert result.passed is True

        # Fails structural (empty)
        result = asyncio.run(chain.validate_output(None, {}))
        assert result.passed is False

        # Fails policy (blocked pattern)
        result = asyncio.run(chain.validate_output("my secret key", {}))
        assert result.passed is False

    def test_chain_context_passed_through(self):
        """Context dict is passed to all guardrails."""
        structural = StructuralGuardrail(name="struct")
        policy = PolicyGuardrail(name="policy")
        chain = GuardrailChain(guardrails=[structural, policy])

        # Should not raise - context flows through
        result = asyncio.run(
            chain.validate_output("test", {"user_id": "123", "role": "admin"})
        )
        assert result.passed is True

    def test_chain_with_none_context(self):
        """Chain handles None context gracefully."""
        structural = StructuralGuardrail(name="struct", max_length=100)
        chain = GuardrailChain(guardrails=[structural])

        result = asyncio.run(chain.validate_output("test", None))
        assert result.passed is True

    def test_full_pipeline_tool_validation(self):
        """Full pipeline: tool call validation with multiple guardrails."""
        policy1 = PolicyGuardrail(
            name="tool_whitelist",
            allowed_tools=["read_file", "write_file", "search"],
        )
        policy2 = PolicyGuardrail(
            name="path_guard",
            sensitive_paths=["/etc/passwd", "/root/.ssh"],
        )
        chain = GuardrailChain(guardrails=[policy1, policy2], fail_fast=False)

        # Allowed tool, safe args
        result = asyncio.run(
            chain.validate_tool_call("read_file", {"path": "/tmp/data.txt"}, {})
        )
        assert result.passed is True

        # Disallowed tool
        result = asyncio.run(
            chain.validate_tool_call("shell_exec", {"cmd": "ls"}, {})
        )
        assert result.passed is False

        # Allowed tool, sensitive path
        result = asyncio.run(
            chain.validate_tool_call("read_file", {"path": "/root/.ssh/id_rsa"}, {})
        )
        assert result.passed is False
