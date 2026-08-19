"""Tests for trigger system modules."""

import pytest

from nexus.triggers.types import (
    TriggerMode,
    InboundKind,
    DEFAULT_TRIGGER_MODE,
    is_auto_allowed,
)
from nexus.triggers.classifier import classify_inbound_kind
from nexus.triggers.schema_validator import validate_against_schema
from nexus.triggers.context_trigger import (
    ContextRule,
    ContextTriggerConfig,
    DEFAULT_CONTEXT_TRIGGER,
)
from nexus.triggers.history import (
    TriggerHistoryEntry,
    TriggerHistoryLedger,
    TRIGGER_HISTORY_LIMIT,
)


class TestTriggerMode:
    """Tests for TriggerMode enum."""

    def test_trigger_mode_values(self) -> None:
        """TriggerMode should have exactly 3 values."""
        assert TriggerMode.strict == "strict"
        assert TriggerMode.allow_all == "allow-all"
        assert TriggerMode.communication_only == "communication-only"
        assert len(TriggerMode) == 3

    def test_default_trigger_mode(self) -> None:
        """Default trigger mode should be strict."""
        assert DEFAULT_TRIGGER_MODE == TriggerMode.strict


class TestInboundKind:
    """Tests for InboundKind enum."""

    def test_inbound_kind_values(self) -> None:
        """InboundKind should have exactly 2 values."""
        assert InboundKind.directive == "directive"
        assert InboundKind.communication == "communication"
        assert len(InboundKind) == 2


class TestIsAutoAllowed:
    """Tests for is_auto_allowed gate function."""

    def test_strict_blocks_all(self) -> None:
        """Strict mode should block all auto-processing."""
        assert is_auto_allowed(TriggerMode.strict, InboundKind.directive) is False
        assert (
            is_auto_allowed(TriggerMode.strict, InboundKind.communication) is False
        )

    def test_allow_all_allows_all(self) -> None:
        """Allow-all mode should allow all auto-processing."""
        assert is_auto_allowed(TriggerMode.allow_all, InboundKind.directive) is True
        assert (
            is_auto_allowed(TriggerMode.allow_all, InboundKind.communication) is True
        )

    def test_communication_only_selective(self) -> None:
        """Communication-only mode should only allow communication."""
        assert (
            is_auto_allowed(TriggerMode.communication_only, InboundKind.directive)
            is False
        )
        assert (
            is_auto_allowed(TriggerMode.communication_only, InboundKind.communication)
            is True
        )


class TestClassifyInboundKind:
    """Tests for classify_inbound_kind function."""

    def test_empty_text_is_communication(self) -> None:
        """Empty text should be classified as communication."""
        assert classify_inbound_kind("") == InboundKind.communication
        assert classify_inbound_kind("   ") == InboundKind.communication

    def test_question_is_communication(self) -> None:
        """Questions without imperative verbs are communication."""
        assert classify_inbound_kind("What is the status?") == InboundKind.communication
        assert (
            classify_inbound_kind("How does this work?") == InboundKind.communication
        )
        assert (
            classify_inbound_kind("When is the deadline?") == InboundKind.communication
        )
        assert (
            classify_inbound_kind("Where is the config?") == InboundKind.communication
        )
        assert classify_inbound_kind("Who owns this?") == InboundKind.communication
        assert (
            classify_inbound_kind("Why did it fail?") == InboundKind.communication
        )
        assert (
            classify_inbound_kind("Is this ready?") == InboundKind.communication
        )
        assert (
            classify_inbound_kind("Are there any issues?") == InboundKind.communication
        )
        assert (
            classify_inbound_kind("Can we proceed?") == InboundKind.communication
        )
        assert (
            classify_inbound_kind("Could you explain?") == InboundKind.communication
        )
        assert (
            classify_inbound_kind("Status of the project?") == InboundKind.communication
        )
        assert (
            classify_inbound_kind("Any updates?") == InboundKind.communication
        )

    def test_question_with_imperative_is_directive(self) -> None:
        """Questions containing imperative verbs are directives."""
        assert (
            classify_inbound_kind("Can you fix this?") == InboundKind.directive
        )
        assert (
            classify_inbound_kind("Could you deploy the app?") == InboundKind.directive
        )
        assert (
            classify_inbound_kind("Can you create a new file?") == InboundKind.directive
        )
        assert (
            classify_inbound_kind("How do I build this?") == InboundKind.directive
        )

    def test_imperative_is_directive(self) -> None:
        """Imperative statements are directives."""
        assert classify_inbound_kind("Fix the bug") == InboundKind.directive
        assert classify_inbound_kind("Deploy to production") == InboundKind.directive
        assert classify_inbound_kind("Build the project") == InboundKind.directive
        assert classify_inbound_kind("Run the tests") == InboundKind.directive
        assert classify_inbound_kind("Write a function") == InboundKind.directive
        assert classify_inbound_kind("Create a new module") == InboundKind.directive
        assert classify_inbound_kind("Add logging") == InboundKind.directive
        assert classify_inbound_kind("Remove dead code") == InboundKind.directive
        assert classify_inbound_kind("Delete the file") == InboundKind.directive
        assert classify_inbound_kind("Refactor the class") == InboundKind.directive
        assert classify_inbound_kind("Implement auth") == InboundKind.directive
        assert classify_inbound_kind("Update dependencies") == InboundKind.directive
        assert classify_inbound_kind("Merge the PR") == InboundKind.directive
        assert classify_inbound_kind("Revert the change") == InboundKind.directive

    def test_non_question_without_imperative(self) -> None:
        """Non-question text without imperative verbs is still directive."""
        assert classify_inbound_kind("hello") == InboundKind.directive
        assert (
            classify_inbound_kind("The system is down") == InboundKind.directive
        )

    def test_question_without_question_mark(self) -> None:
        """Question words without trailing '?' are directives."""
        assert (
            classify_inbound_kind("What is the status") == InboundKind.directive
        )

    def test_do_does_did_questions(self) -> None:
        """Do/does/did questions are communication."""
        assert (
            classify_inbound_kind("Do we need this?") == InboundKind.communication
        )
        assert (
            classify_inbound_kind("Does it work?") == InboundKind.communication
        )
        assert (
            classify_inbound_kind("Did it pass?") == InboundKind.communication
        )


class TestSchemaValidator:
    """Tests for validate_against_schema function."""

    def test_valid_object(self) -> None:
        """Valid object matching schema should pass."""
        schema = {
            "type": "object",
            "required": ["name", "age"],
            "properties": {
                "name": {"type": "string"},
                "age": {"type": "integer"},
            },
        }
        result = validate_against_schema({"name": "Alice", "age": 30}, schema)
        assert result["ok"] is True

    def test_missing_required_field(self) -> None:
        """Missing required field should fail."""
        schema = {
            "type": "object",
            "required": ["name", "age"],
            "properties": {
                "name": {"type": "string"},
                "age": {"type": "integer"},
            },
        }
        result = validate_against_schema({"name": "Alice"}, schema)
        assert result["ok"] is False
        assert "age" in result["error"]

    def test_type_mismatch_string(self) -> None:
        """Wrong type should fail validation."""
        result = validate_against_schema(42, {"type": "string"})
        assert result["ok"] is False
        assert "string" in result["error"]

    def test_type_mismatch_number(self) -> None:
        """Non-number value should fail number type check."""
        result = validate_against_schema("hello", {"type": "number"})
        assert result["ok"] is False

    def test_type_mismatch_integer(self) -> None:
        """Float should fail integer type check."""
        result = validate_against_schema(3.14, {"type": "integer"})
        assert result["ok"] is False

    def test_type_mismatch_boolean(self) -> None:
        """Non-boolean should fail boolean type check."""
        result = validate_against_schema(1, {"type": "boolean"})
        assert result["ok"] is False

    def test_type_mismatch_array(self) -> None:
        """Non-array should fail array type check."""
        result = validate_against_schema({}, {"type": "array"})
        assert result["ok"] is False

    def test_type_mismatch_object(self) -> None:
        """Non-object should fail object type check."""
        result = validate_against_schema([], {"type": "object"})
        assert result["ok"] is False

    def test_type_null(self) -> None:
        """None value should pass null type check."""
        result = validate_against_schema(None, {"type": "null"})
        assert result["ok"] is True
        result = validate_against_schema("hi", {"type": "null"})
        assert result["ok"] is False

    def test_valid_types(self) -> None:
        """Each type should correctly validate matching values."""
        assert validate_against_schema("hi", {"type": "string"})["ok"] is True
        assert validate_against_schema(3.14, {"type": "number"})["ok"] is True
        assert validate_against_schema(42, {"type": "number"})["ok"] is True
        assert validate_against_schema(42, {"type": "integer"})["ok"] is True
        assert validate_against_schema(True, {"type": "boolean"})["ok"] is True
        assert validate_against_schema([], {"type": "array"})["ok"] is True
        assert validate_against_schema({}, {"type": "object"})["ok"] is True

    def test_enum_valid(self) -> None:
        """Value in enum list should pass."""
        schema = {"enum": ["red", "green", "blue"]}
        result = validate_against_schema("red", schema)
        assert result["ok"] is True

    def test_enum_invalid(self) -> None:
        """Value not in enum list should fail."""
        schema = {"enum": ["red", "green", "blue"]}
        result = validate_against_schema("yellow", schema)
        assert result["ok"] is False
        assert "enum" in result["error"]

    def test_nested_properties(self) -> None:
        """Nested property validation should work recursively."""
        schema = {
            "type": "object",
            "properties": {
                "address": {
                    "type": "object",
                    "required": ["city"],
                    "properties": {
                        "city": {"type": "string"},
                    },
                },
            },
        }
        result = validate_against_schema(
            {"address": {"city": "NYC"}}, schema
        )
        assert result["ok"] is True

        result = validate_against_schema(
            {"address": {"city": 123}}, schema
        )
        assert result["ok"] is False
        assert "address" in result["error"]

    def test_nested_missing_required(self) -> None:
        """Nested missing required fields should fail."""
        schema = {
            "type": "object",
            "properties": {
                "address": {
                    "type": "object",
                    "required": ["city"],
                },
            },
        }
        result = validate_against_schema({"address": {}}, schema)
        assert result["ok"] is False

    def test_unknown_keywords_accepted(self) -> None:
        """Unknown schema keywords should be ignored (degrade to accept)."""
        schema = {
            "type": "string",
            "minLength": 5,
            "pattern": "^[a-z]+$",
            "description": "A short string",
            "$id": "test-schema",
        }
        result = validate_against_schema("hi", schema)
        assert result["ok"] is True

    def test_empty_schema_accepts_anything(self) -> None:
        """An empty schema should accept any value."""
        assert validate_against_schema(42, {})["ok"] is True
        assert validate_against_schema("hello", {})["ok"] is True
        assert validate_against_schema(None, {})["ok"] is True
        assert validate_against_schema([], {})["ok"] is True

    def test_boolean_not_number(self) -> None:
        """Booleans should NOT pass number or integer validation."""
        assert validate_against_schema(True, {"type": "number"})["ok"] is False
        assert validate_against_schema(False, {"type": "integer"})["ok"] is False


class TestContextTrigger:
    """Tests for ContextRule and ContextTriggerConfig."""

    def test_context_rule_fields(self) -> None:
        """ContextRule should have expected fields."""
        rule = ContextRule(
            enabled=True,
            every_seconds=3600,
            min_context_pct=50,
            min_context_pct_large_window=30,
            message="test message",
        )
        assert rule.enabled is True
        assert rule.every_seconds == 3600
        assert rule.min_context_pct == 50
        assert rule.min_context_pct_large_window == 30
        assert rule.message == "test message"

    def test_default_context_trigger_compact(self) -> None:
        """Default compact rule should match expected values."""
        compact = DEFAULT_CONTEXT_TRIGGER.compact
        assert compact.enabled is True
        assert compact.every_seconds == 7200
        assert compact.min_context_pct == 60
        assert compact.min_context_pct_large_window == 40
        assert "current task" in compact.message
        assert "Drop resolved tangents" in compact.message

    def test_default_context_trigger_clear(self) -> None:
        """Default clear rule should match expected values."""
        clear = DEFAULT_CONTEXT_TRIGGER.clear
        assert clear.enabled is False
        assert clear.every_seconds == 7200
        assert clear.min_context_pct == 90
        assert clear.min_context_pct_large_window == 80
        assert clear.message == ""

    def test_context_rule_frozen(self) -> None:
        """ContextRule should be immutable (frozen dataclass)."""
        rule = ContextRule(
            enabled=True,
            every_seconds=3600,
            min_context_pct=50,
            min_context_pct_large_window=30,
            message="test",
        )
        with pytest.raises(Exception):
            rule.enabled = False  # type: ignore[misc]


class TestTriggerHistoryLedger:
    """Tests for TriggerHistoryLedger."""

    def _make_entry(self, entry_id: str) -> TriggerHistoryEntry:
        """Create a test entry with given id."""
        return TriggerHistoryEntry(
            id=entry_id,
            source="test",
            source_id="src-1",
            source_name="Test Source",
            direction="inbound",
            peer="user-1",
            body="test body",
            at=1000.0,
        )

    def test_add_and_list(self) -> None:
        """Adding entries and listing them should work."""
        ledger = TriggerHistoryLedger()
        entry = self._make_entry("e1")
        ledger.add(entry)

        entries = ledger.list()
        assert len(entries) == 1
        assert entries[0].id == "e1"

    def test_list_with_limit(self) -> None:
        """List with limit should return only the most recent entries."""
        ledger = TriggerHistoryLedger()
        for i in range(10):
            ledger.add(self._make_entry(f"e{i}"))

        entries = ledger.list(limit=3)
        assert len(entries) == 3
        assert entries[0].id == "e7"
        assert entries[2].id == "e9"

    def test_cap_at_limit(self) -> None:
        """Ledger should cap at TRIGGER_HISTORY_LIMIT entries."""
        ledger = TriggerHistoryLedger()
        for i in range(TRIGGER_HISTORY_LIMIT + 100):
            ledger.add(self._make_entry(f"e{i}"))

        entries = ledger.list()
        assert len(entries) == TRIGGER_HISTORY_LIMIT

    def test_drops_oldest_on_overflow(self) -> None:
        """When capped, the oldest entries should be dropped."""
        ledger = TriggerHistoryLedger()
        for i in range(TRIGGER_HISTORY_LIMIT + 10):
            ledger.add(self._make_entry(f"e{i}"))

        entries = ledger.list()
        # The first 10 entries should have been dropped
        assert entries[0].id == "e10"
        assert entries[-1].id == f"e{TRIGGER_HISTORY_LIMIT + 9}"

    def test_history_entry_defaults(self) -> None:
        """TriggerHistoryEntry should have correct default values."""
        entry = TriggerHistoryEntry(
            id="test",
            source="s",
            source_id="sid",
            source_name="sname",
            direction="in",
            peer="p",
        )
        assert entry.title == ""
        assert entry.body == ""
        assert entry.kind == InboundKind.communication
        assert entry.decision == ""
        assert entry.correlation_id == ""
        assert entry.task_id == ""
        assert entry.at == 0.0

    def test_limit_constant(self) -> None:
        """TRIGGER_HISTORY_LIMIT should be 500."""
        assert TRIGGER_HISTORY_LIMIT == 500
