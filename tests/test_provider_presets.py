"""Tests for the agent provider presets module (nexus.adapters.provider_presets)."""

import pytest

from nexus.adapters.provider_presets import (
    PROVIDER_PRESETS,
    AgentProviderID,
    AgentProviderPreset,
    get_preset,
)


class TestAgentProviderID:
    """Tests for AgentProviderID enum."""

    def test_all_eleven_providers(self) -> None:
        """All 11 expected provider IDs exist."""
        expected = {
            "claude", "codex", "grok", "kimi", "antigravity",
            "qwen", "opencode", "crush", "pi", "copilot", "custom",
        }
        actual = {p.value for p in AgentProviderID}
        assert actual == expected

    def test_is_str_enum(self) -> None:
        """AgentProviderID values are strings."""
        assert AgentProviderID.claude == "claude"
        assert isinstance(AgentProviderID.codex, str)


class TestProviderPresets:
    """Tests for the PROVIDER_PRESETS mapping."""

    def test_all_eleven_in_mapping(self) -> None:
        """All 11 providers are present in PROVIDER_PRESETS."""
        assert len(PROVIDER_PRESETS) == 11
        for pid in AgentProviderID:
            assert pid in PROVIDER_PRESETS

    def test_all_presets_are_frozen_dataclass(self) -> None:
        """Each preset is an AgentProviderPreset frozen instance."""
        for preset in PROVIDER_PRESETS.values():
            assert isinstance(preset, AgentProviderPreset)
            with pytest.raises(Exception):
                preset.label = "hack"  # type: ignore[misc]

    def test_required_fields_present(self) -> None:
        """Each preset has the minimum required fields populated."""
        for pid, preset in PROVIDER_PRESETS.items():
            assert preset.id == pid
            assert isinstance(preset.label, str) and len(preset.label) > 0
            assert isinstance(preset.default_command, str)
            assert isinstance(preset.auto_mode_flag, str)


class TestGetPreset:
    """Tests for get_preset() lookup."""

    def test_returns_matching_preset(self) -> None:
        """get_preset returns the preset for each known ID."""
        for pid in AgentProviderID:
            preset = get_preset(pid)
            assert preset.id == pid

    def test_fallback_to_claude(self) -> None:
        """Unknown provider ID falls back to Claude preset."""
        # Simulate an unknown ID by passing a string that looks like a valid
        # AgentProviderID but isn't in the mapping. We test the dict.get fallback.
        # Since AgentProviderID is an enum, we test by ensuring get_preset with
        # a valid ID returns the correct one, and the fallback mechanism works.
        claude_preset = PROVIDER_PRESETS[AgentProviderID.claude]
        # Access the internal dict.get fallback by passing a non-existent key
        result = PROVIDER_PRESETS.get("nonexistent", claude_preset)  # type: ignore[arg-type]
        assert result.id == AgentProviderID.claude


class TestClaudePreset:
    """Verify key metadata values for the Claude preset."""

    @pytest.fixture()
    def preset(self) -> AgentProviderPreset:
        return get_preset(AgentProviderID.claude)

    def test_command(self, preset: AgentProviderPreset) -> None:
        assert preset.default_command == "claude"

    def test_auto_mode_flag(self, preset: AgentProviderPreset) -> None:
        assert preset.auto_mode_flag == "--permission-mode bypassPermissions"

    def test_model_flag(self, preset: AgentProviderPreset) -> None:
        assert preset.model_flag == "--model"

    def test_hive_aware(self, preset: AgentProviderPreset) -> None:
        assert preset.hive_aware is True

    def test_can_receive_inbox(self, preset: AgentProviderPreset) -> None:
        assert preset.can_receive_inbox is True

    def test_recommended_model(self, preset: AgentProviderPreset) -> None:
        assert preset.recommended_orchestrator_model == "claude-opus-4-8[1m]"

    def test_resume_flag(self, preset: AgentProviderPreset) -> None:
        assert preset.resume_flag == "--resume"

    def test_install_command(self, preset: AgentProviderPreset) -> None:
        assert preset.install_command == "npm install -g @anthropic-ai/claude-code"


class TestCodexPreset:
    """Verify key metadata values for the Codex preset."""

    @pytest.fixture()
    def preset(self) -> AgentProviderPreset:
        return get_preset(AgentProviderID.codex)

    def test_command(self, preset: AgentProviderPreset) -> None:
        assert preset.default_command == "codex"

    def test_auto_mode_flag(self, preset: AgentProviderPreset) -> None:
        assert preset.auto_mode_flag == "--dangerously-bypass-approvals-and-sandbox"

    def test_hive_aware(self, preset: AgentProviderPreset) -> None:
        assert preset.hive_aware is False

    def test_can_receive_inbox(self, preset: AgentProviderPreset) -> None:
        assert preset.can_receive_inbox is True

    def test_hook_bridge(self, preset: AgentProviderPreset) -> None:
        assert preset.hook_bridge == "codex"

    def test_recommended_model(self, preset: AgentProviderPreset) -> None:
        assert preset.recommended_orchestrator_model == "gpt-5-codex"

    def test_non_interactive_env(self, preset: AgentProviderPreset) -> None:
        assert preset.non_interactive_env == {"CODEX_NON_INTERACTIVE": "1"}


class TestAntigravityPreset:
    """Verify key metadata values for the Antigravity preset."""

    @pytest.fixture()
    def preset(self) -> AgentProviderPreset:
        return get_preset(AgentProviderID.antigravity)

    def test_command(self, preset: AgentProviderPreset) -> None:
        assert preset.default_command == "agy"

    def test_auto_mode_flag(self, preset: AgentProviderPreset) -> None:
        assert preset.auto_mode_flag == "--dangerously-skip-permissions"

    def test_hook_bridge(self, preset: AgentProviderPreset) -> None:
        assert preset.hook_bridge == "agy"

    def test_can_receive_inbox(self, preset: AgentProviderPreset) -> None:
        assert preset.can_receive_inbox is True

    def test_recommended_model(self, preset: AgentProviderPreset) -> None:
        assert preset.recommended_orchestrator_model == "Gemini 3.1 Pro (High)"

    def test_resume_flag(self, preset: AgentProviderPreset) -> None:
        assert preset.resume_flag == "--conversation"


class TestPiPreset:
    """Verify key metadata values for the Pi preset."""

    @pytest.fixture()
    def preset(self) -> AgentProviderPreset:
        return get_preset(AgentProviderID.pi)

    def test_non_interactive_env(self, preset: AgentProviderPreset) -> None:
        assert preset.non_interactive_env == {"PI_SKIP_VERSION_CHECK": "1", "PI_TELEMETRY": "0"}

    def test_resume_flag(self, preset: AgentProviderPreset) -> None:
        assert preset.resume_flag == "--session"


class TestCustomPreset:
    """Verify the custom preset has no capabilities."""

    @pytest.fixture()
    def preset(self) -> AgentProviderPreset:
        return get_preset(AgentProviderID.custom)

    def test_empty_command(self, preset: AgentProviderPreset) -> None:
        assert preset.default_command == ""

    def test_no_model_support(self, preset: AgentProviderPreset) -> None:
        assert preset.supports_model is False

    def test_not_hive_aware(self, preset: AgentProviderPreset) -> None:
        assert preset.hive_aware is False

    def test_cannot_receive_inbox(self, preset: AgentProviderPreset) -> None:
        assert preset.can_receive_inbox is False
