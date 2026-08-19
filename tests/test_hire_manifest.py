"""Comprehensive tests for the hire manifest module.

Tests cover: HireManifest Pydantic model validation, security boundary rejection,
ManifestRegistry filesystem operations, and the validate_hire_manifest function.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from nexus.templates.hire_manifest import (
    HIRE_SPEC_V1,
    KNOWN_PROVIDERS,
    SAFE_FLAG_NAMES,
    HireManifest,
    HireValidation,
    validate_hire_manifest,
)
from nexus.templates.hire_registry import ManifestRegistry
from nexus.templates.hire_security import is_safe_flag, validate_command_flags, validate_model_id


# ---------------------------------------------------------------------------
# HireManifest Pydantic model tests
# ---------------------------------------------------------------------------


def _valid_manifest_dict() -> dict:
    """Return a minimal valid manifest dictionary."""
    return {
        "spec": "nexus/hire@1",
        "name": "TestAgent",
        "description": "A test agent",
        "goal": "Do testing",
        "provider": "claude",
        "model": "claude-sonnet-4-6",
        "command_flags": ["--max-turns", "80"],
        "capabilities": ["testing", "qa"],
        "isolate": False,
        "token_cap": 2000000,
        "author": "Test Author",
        "homepage": "https://example.com",
    }


class TestValidManifest:
    """Tests for valid manifest parsing."""

    def test_valid_manifest_parses(self) -> None:
        """A valid manifest dict should parse into a HireManifest."""
        data = _valid_manifest_dict()
        manifest = HireManifest(**data)
        assert manifest.name == "TestAgent"
        assert manifest.spec == HIRE_SPEC_V1
        assert manifest.description == "A test agent"
        assert manifest.goal == "Do testing"
        assert manifest.provider == "claude"
        assert manifest.model == "claude-sonnet-4-6"
        assert manifest.command_flags == ["--max-turns", "80"]
        assert manifest.capabilities == ["testing", "qa"]
        assert manifest.isolate is False
        assert manifest.token_cap == 2000000
        assert manifest.author == "Test Author"
        assert manifest.homepage == "https://example.com"

    def test_minimal_manifest(self) -> None:
        """A manifest with only the required name field should parse."""
        manifest = HireManifest(name="Minimal")
        assert manifest.name == "Minimal"
        assert manifest.spec == HIRE_SPEC_V1
        assert manifest.description is None
        assert manifest.provider is None
        assert manifest.model is None
        assert manifest.command_flags == []
        assert manifest.capabilities == []
        assert manifest.isolate is False
        assert manifest.token_cap is None


class TestNameValidation:
    """Tests for name field validation."""

    def test_name_required(self) -> None:
        """Name is a required field."""
        with pytest.raises(ValidationError):
            HireManifest()  # type: ignore[call-arg]

    def test_name_empty_rejected(self) -> None:
        """Empty name should be rejected."""
        with pytest.raises(ValidationError):
            HireManifest(name="")

    def test_name_max_length(self) -> None:
        """Name exceeding 40 characters should be rejected."""
        with pytest.raises(ValidationError):
            HireManifest(name="A" * 41)

    def test_name_at_max_length(self) -> None:
        """Name of exactly 40 characters should be accepted."""
        manifest = HireManifest(name="A" * 40)
        assert len(manifest.name) == 40


class TestModelValidation:
    """Tests for model field validation."""

    def test_model_rejects_shell_metacharacters(self) -> None:
        """Shell metacharacters in model IDs should be rejected."""
        dangerous_chars = ["&", "|", ";", "$", "`", "<", ">", "!", "%", "^", "'", '"']
        for char in dangerous_chars:
            with pytest.raises(ValidationError):
                HireManifest(name="Test", model=f"model{char}inject")

    def test_model_accepts_valid(self) -> None:
        """Real-world model IDs should be accepted."""
        valid_models = [
            "claude-sonnet-4-6[1m]",
            "Gemini 3.1 Pro (High)",
            "openai/gpt-4o",
            "claude-opus-4-8",
            "claude-haiku-4-5-20251001",
            "gpt-4o-mini",
            "o1",
        ]
        for model in valid_models:
            manifest = HireManifest(name="Test", model=model)
            assert manifest.model == model

    def test_model_max_length(self) -> None:
        """Model IDs longer than 80 characters should be rejected."""
        with pytest.raises(ValidationError):
            HireManifest(name="Test", model="a" * 81)

    def test_model_none_allowed(self) -> None:
        """Model can be None (omitted)."""
        manifest = HireManifest(name="Test", model=None)
        assert manifest.model is None


class TestFlagValidation:
    """Tests for command_flags field validation."""

    def test_flags_rejects_unsafe(self) -> None:
        """Unsafe flags must be rejected by the allowlist."""
        unsafe_flags = [
            "--permission-mode",
            "--settings",
            "-c",
            "--system-prompt",
            "--provider",
            "--base-url",
            "--config",
        ]
        for flag in unsafe_flags:
            with pytest.raises(ValidationError):
                HireManifest(name="Test", command_flags=[flag])

    def test_flags_allows_safe(self) -> None:
        """All flags in SAFE_FLAG_NAMES should be accepted."""
        for flag in SAFE_FLAG_NAMES:
            manifest = HireManifest(name="Test", command_flags=[flag, "value"])
            assert flag in manifest.command_flags

    def test_flags_allows_safe_with_equals(self) -> None:
        """Safe flags with inline = values should be accepted."""
        manifest = HireManifest(name="Test", command_flags=["--model=gpt-4o"])
        assert manifest.command_flags == ["--model=gpt-4o"]

    def test_flags_value_only_after_flag(self) -> None:
        """Bare value at position 0 should be rejected."""
        with pytest.raises(ValidationError):
            HireManifest(name="Test", command_flags=["bare_value"])

    def test_flags_consecutive_values_rejected(self) -> None:
        """Two consecutive bare values should be rejected."""
        with pytest.raises(ValidationError):
            HireManifest(name="Test", command_flags=["--model", "val1", "val2"])

    def test_flags_max_16_items(self) -> None:
        """More than 16 flag entries should be rejected."""
        # Build 17 entries: alternating safe flag and value
        flags = []
        for _ in range(9):
            flags.extend(["--model", "value"])
        # 18 entries
        with pytest.raises(ValidationError):
            HireManifest(name="Test", command_flags=flags)

    def test_flags_empty_list_accepted(self) -> None:
        """Empty command_flags list should be accepted."""
        manifest = HireManifest(name="Test", command_flags=[])
        assert manifest.command_flags == []

    def test_flags_rejects_metacharacters(self) -> None:
        """Flag tokens with shell metacharacters should be rejected."""
        with pytest.raises(ValidationError):
            HireManifest(name="Test", command_flags=["--model", "val;inject"])

    def test_flags_value_after_equals_flag_rejected(self) -> None:
        """A bare value after a --flag=value (already consumed) should be rejected."""
        with pytest.raises(ValidationError):
            HireManifest(name="Test", command_flags=["--model=gpt-4o", "extra"])


class TestProviderValidation:
    """Tests for provider field validation."""

    def test_provider_validates_known(self) -> None:
        """Unknown provider should raise ValidationError."""
        with pytest.raises(ValidationError):
            HireManifest(name="Test", provider="unknown_provider")

    def test_provider_rejects_custom(self) -> None:
        """Custom provider is excluded for security."""
        with pytest.raises(ValidationError):
            HireManifest(name="Test", provider="custom")

    def test_provider_allows_known(self) -> None:
        """Each known provider should be accepted."""
        for provider in KNOWN_PROVIDERS:
            manifest = HireManifest(name="Test", provider=provider)
            assert manifest.provider == provider

    def test_provider_none_allowed(self) -> None:
        """Provider can be None (omitted)."""
        manifest = HireManifest(name="Test", provider=None)
        assert manifest.provider is None


class TestHomepageValidation:
    """Tests for homepage field validation."""

    def test_homepage_must_be_https(self) -> None:
        """http:// URLs should be rejected."""
        with pytest.raises(ValidationError):
            HireManifest(name="Test", homepage="http://example.com")

    def test_homepage_accepts_https(self) -> None:
        """https:// URLs should be accepted."""
        manifest = HireManifest(name="Test", homepage="https://example.com")
        assert manifest.homepage == "https://example.com"

    def test_homepage_rejects_ftp(self) -> None:
        """Non-http schemes should be rejected."""
        with pytest.raises(ValidationError):
            HireManifest(name="Test", homepage="ftp://example.com")

    def test_homepage_none_allowed(self) -> None:
        """Homepage can be None."""
        manifest = HireManifest(name="Test", homepage=None)
        assert manifest.homepage is None


class TestTokenCapValidation:
    """Tests for token_cap field validation."""

    def test_token_cap_bounds_zero_rejected(self) -> None:
        """Zero token_cap should be rejected (must be > 0)."""
        with pytest.raises(ValidationError):
            HireManifest(name="Test", token_cap=0)

    def test_token_cap_bounds_negative_rejected(self) -> None:
        """Negative token_cap should be rejected."""
        with pytest.raises(ValidationError):
            HireManifest(name="Test", token_cap=-100)

    def test_token_cap_max_accepted(self) -> None:
        """Maximum value of 10^10 should be accepted."""
        manifest = HireManifest(name="Test", token_cap=10_000_000_000)
        assert manifest.token_cap == 10_000_000_000

    def test_token_cap_over_max_rejected(self) -> None:
        """Values exceeding 10^10 should be rejected."""
        with pytest.raises(ValidationError):
            HireManifest(name="Test", token_cap=10_000_000_001)

    def test_token_cap_valid(self) -> None:
        """A normal token cap should be accepted."""
        manifest = HireManifest(name="Test", token_cap=2000000)
        assert manifest.token_cap == 2000000


class TestCapabilitiesValidation:
    """Tests for capabilities field validation."""

    def test_capabilities_max_12(self) -> None:
        """More than 12 capabilities should be rejected."""
        caps = [f"cap{i}" for i in range(13)]
        with pytest.raises(ValidationError):
            HireManifest(name="Test", capabilities=caps)

    def test_capabilities_12_accepted(self) -> None:
        """Exactly 12 capabilities should be accepted."""
        caps = [f"cap{i}" for i in range(12)]
        manifest = HireManifest(name="Test", capabilities=caps)
        assert len(manifest.capabilities) == 12

    def test_capabilities_truncated_to_40(self) -> None:
        """Capabilities longer than 40 chars should be truncated."""
        long_cap = "a" * 50
        manifest = HireManifest(name="Test", capabilities=[long_cap])
        assert len(manifest.capabilities[0]) == 40


# ---------------------------------------------------------------------------
# ManifestRegistry tests
# ---------------------------------------------------------------------------


class TestManifestRegistry:
    """Tests for the ManifestRegistry class."""

    def test_manifest_registry_load(self, tmp_path: Path) -> None:
        """Registry should load all valid JSON manifests from a directory."""
        data = _valid_manifest_dict()
        (tmp_path / "test-agent.json").write_text(json.dumps(data))

        data2 = _valid_manifest_dict()
        data2["name"] = "SecondAgent"
        (tmp_path / "second-agent.json").write_text(json.dumps(data2))

        registry = ManifestRegistry(tmp_path)
        registry.load()

        manifests = registry.list_manifests()
        assert len(manifests) == 2
        names = [m.name for m in manifests]
        assert "TestAgent" in names
        assert "SecondAgent" in names

    def test_manifest_registry_get(self, tmp_path: Path) -> None:
        """Registry get_manifest should find by name."""
        data = _valid_manifest_dict()
        (tmp_path / "test.json").write_text(json.dumps(data))

        registry = ManifestRegistry(tmp_path)
        registry.load()

        result = registry.get_manifest("TestAgent")
        assert result is not None
        assert result.name == "TestAgent"

        assert registry.get_manifest("NonExistent") is None

    def test_manifest_registry_import(self, tmp_path: Path) -> None:
        """import_manifest should validate, save, and register a manifest."""
        registry = ManifestRegistry(tmp_path)
        data = _valid_manifest_dict()

        result = registry.import_manifest(data)
        assert result.ok is True
        assert result.manifest is not None
        assert result.manifest.name == "TestAgent"

        # Verify saved to disk
        saved_file = tmp_path / "testagent.json"
        assert saved_file.exists()
        saved_data = json.loads(saved_file.read_text())
        assert saved_data["name"] == "TestAgent"

        # Verify in registry
        assert registry.get_manifest("TestAgent") is not None

    def test_manifest_registry_import_invalid(self, tmp_path: Path) -> None:
        """import_manifest with invalid data should return errors."""
        registry = ManifestRegistry(tmp_path)
        data = {"name": "", "provider": "invalid_provider"}

        result = registry.import_manifest(data)
        assert result.ok is False
        assert len(result.errors) > 0
        assert registry.get_manifest("") is None

    def test_manifest_registry_skips_invalid_json(self, tmp_path: Path) -> None:
        """Registry should skip files that are not valid JSON."""
        (tmp_path / "bad.json").write_text("not json {{{")
        data = _valid_manifest_dict()
        (tmp_path / "good.json").write_text(json.dumps(data))

        registry = ManifestRegistry(tmp_path)
        registry.load()

        assert len(registry.list_manifests()) == 1

    def test_manifest_registry_skips_invalid_manifest(self, tmp_path: Path) -> None:
        """Registry should skip JSON files that fail manifest validation."""
        invalid = {"name": "", "provider": "not_real"}
        (tmp_path / "invalid.json").write_text(json.dumps(invalid))
        data = _valid_manifest_dict()
        (tmp_path / "valid.json").write_text(json.dumps(data))

        registry = ManifestRegistry(tmp_path)
        registry.load()

        assert len(registry.list_manifests()) == 1

    def test_manifest_registry_empty_dir(self, tmp_path: Path) -> None:
        """Registry with empty directory should have no manifests."""
        registry = ManifestRegistry(tmp_path)
        registry.load()
        assert registry.list_manifests() == []

    def test_manifest_registry_nonexistent_dir(self, tmp_path: Path) -> None:
        """Registry with nonexistent directory should have no manifests."""
        registry = ManifestRegistry(tmp_path / "does_not_exist")
        registry.load()
        assert registry.list_manifests() == []


# ---------------------------------------------------------------------------
# validate_hire_manifest function tests
# ---------------------------------------------------------------------------


class TestValidateHireManifest:
    """Tests for the validate_hire_manifest wrapper function."""

    def test_validate_hire_manifest_valid(self) -> None:
        """Valid input should return ok=True with manifest."""
        data = _valid_manifest_dict()
        result = validate_hire_manifest(data)
        assert result.ok is True
        assert result.manifest is not None
        assert result.manifest.name == "TestAgent"
        assert result.errors == []

    def test_validate_hire_manifest_invalid(self) -> None:
        """Invalid input should return ok=False with errors."""
        data = {"name": "", "provider": "invalid"}
        result = validate_hire_manifest(data)
        assert result.ok is False
        assert result.manifest is None
        assert len(result.errors) > 0

    def test_validate_hire_manifest_empty_dict(self) -> None:
        """Empty dict (missing required name) should fail."""
        result = validate_hire_manifest({})
        assert result.ok is False
        assert len(result.errors) > 0

    def test_validate_hire_manifest_model_injection(self) -> None:
        """Model with injection attempt should fail."""
        data = _valid_manifest_dict()
        data["model"] = "model; rm -rf /"
        result = validate_hire_manifest(data)
        assert result.ok is False


# ---------------------------------------------------------------------------
# hire_security module tests
# ---------------------------------------------------------------------------


class TestIsSafeFlag:
    """Tests for the is_safe_flag function."""

    def test_is_safe_flag_known(self) -> None:
        """Known safe flags should return True."""
        assert is_safe_flag("--model") is True
        assert is_safe_flag("--max-turns") is True
        assert is_safe_flag("--output-format") is True
        assert is_safe_flag("--verbose") is True

    def test_is_safe_flag_with_equals(self) -> None:
        """Safe flags with =value should still return True."""
        assert is_safe_flag("--model=gpt-4o") is True
        assert is_safe_flag("--max-turns=80") is True

    def test_is_safe_flag_case_insensitive(self) -> None:
        """Flag name matching should be case-insensitive."""
        assert is_safe_flag("--Model") is True
        assert is_safe_flag("--MAX-TURNS") is True

    def test_is_safe_flag_unknown(self) -> None:
        """Unknown flags should return False."""
        assert is_safe_flag("--permission-mode") is False
        assert is_safe_flag("--settings") is False
        assert is_safe_flag("-c") is False
        assert is_safe_flag("--system-prompt") is False

    def test_is_safe_flag_bare_value(self) -> None:
        """Non-flag tokens (no leading dash) should return False."""
        assert is_safe_flag("value") is False
        assert is_safe_flag("model") is False


class TestValidateCommandFlags:
    """Tests for the validate_command_flags function."""

    def test_valid_flags(self) -> None:
        """Valid flag sequences should pass."""
        ok, errors = validate_command_flags(["--model", "gpt-4o"])
        assert ok is True
        assert errors == []

    def test_valid_flags_with_equals(self) -> None:
        """Flags with = values should pass."""
        ok, errors = validate_command_flags(["--model=gpt-4o", "--verbose"])
        assert ok is True
        assert errors == []

    def test_unsafe_flag_rejected(self) -> None:
        """Unsafe flags should produce errors."""
        ok, errors = validate_command_flags(["--permission-mode", "full"])
        assert ok is False
        assert len(errors) > 0

    def test_bare_value_first_rejected(self) -> None:
        """Bare value at position 0 should produce errors."""
        ok, errors = validate_command_flags(["bare_value"])
        assert ok is False
        assert len(errors) > 0

    def test_too_many_flags(self) -> None:
        """More than 16 flags should produce errors."""
        flags = ["--model", "val"] * 9  # 18 items
        ok, errors = validate_command_flags(flags)
        assert ok is False

    def test_empty_list(self) -> None:
        """Empty list should pass."""
        ok, errors = validate_command_flags([])
        assert ok is True
        assert errors == []


class TestValidateModelId:
    """Tests for the validate_model_id function."""

    def test_valid_model_ids(self) -> None:
        """Valid model IDs should pass."""
        valid = [
            "claude-sonnet-4-6",
            "claude-sonnet-4-6[1m]",
            "Gemini 3.1 Pro (High)",
            "openai/gpt-4o",
            "o1",
        ]
        for model in valid:
            ok, reason = validate_model_id(model)
            assert ok is True, f"Expected {model!r} to be valid but got: {reason}"
            assert reason == ""

    def test_invalid_model_ids(self) -> None:
        """Model IDs with dangerous characters should fail."""
        invalid = [
            "model;inject",
            "model&inject",
            "model|inject",
            "model$var",
            "model`cmd`",
            "model<file",
            "model>file",
        ]
        for model in invalid:
            ok, reason = validate_model_id(model)
            assert ok is False, f"Expected {model!r} to be invalid"
            assert reason != ""
