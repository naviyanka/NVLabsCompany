"""Tests for the LLM Provider Registry with self-registration."""

import pytest

from nexus.models_router.provider_registry import (
    LLMProviderSpec,
    ModelCapabilities,
    ProviderRegistry,
    OPENAI_SPEC,
    ANTHROPIC_SPEC,
    OLLAMA_SPEC,
    DEEPSEEK_SPEC,
    MISTRAL_SPEC,
    GOOGLE_SPEC,
)


@pytest.fixture(autouse=True)
def reset_registry():
    """Reset registry before each test and re-register built-ins after."""
    ProviderRegistry.reset()
    # Re-register built-in providers for tests that need them
    ProviderRegistry.register(OPENAI_SPEC)
    ProviderRegistry.register(ANTHROPIC_SPEC)
    ProviderRegistry.register(OLLAMA_SPEC)
    ProviderRegistry.register(DEEPSEEK_SPEC)
    ProviderRegistry.register(MISTRAL_SPEC)
    ProviderRegistry.register(GOOGLE_SPEC)
    yield
    ProviderRegistry.reset()


class TestRegistrySingleton:
    """Test singleton pattern of ProviderRegistry."""

    def test_same_instance_returned(self):
        """Registry returns the same instance."""
        instance_a = ProviderRegistry()
        instance_b = ProviderRegistry()
        assert instance_a is instance_b


class TestRegisterUnregister:
    """Test register and unregister operations."""

    def test_register_new_provider(self):
        """Can register a new provider spec."""
        custom_spec = LLMProviderSpec(
            name="custom",
            models_available=["custom-model"],
            pricing={"custom-model": {"input": 1.0, "output": 2.0}},
            capabilities={
                "custom-model": ModelCapabilities(
                    context_window=4096,
                    supports_tools=False,
                    supports_vision=False,
                    supports_streaming=True,
                    supports_json_mode=False,
                )
            },
            api_base="http://localhost:8080",
        )
        ProviderRegistry.register(custom_spec)
        assert ProviderRegistry.get_provider("custom") is custom_spec

    def test_unregister_provider(self):
        """Can unregister a provider by name."""
        assert ProviderRegistry.get_provider("openai") is not None
        ProviderRegistry.unregister("openai")
        assert ProviderRegistry.get_provider("openai") is None

    def test_unregister_nonexistent_provider(self):
        """Unregistering a non-existent provider does not raise."""
        ProviderRegistry.unregister("nonexistent")  # Should not raise


class TestListProviders:
    """Test listing all providers."""

    def test_list_providers_returns_all_builtins(self):
        """list_providers returns all 6 built-in providers."""
        providers = ProviderRegistry.list_providers()
        assert len(providers) == 6

    def test_list_providers_names(self):
        """All built-in provider names are present."""
        providers = ProviderRegistry.list_providers()
        names = {p.name for p in providers}
        assert names == {"openai", "anthropic", "ollama", "deepseek", "mistral", "google"}


class TestGetProvider:
    """Test get_provider lookup."""

    def test_get_provider_by_name(self):
        """get_provider returns the correct spec for a known provider."""
        openai = ProviderRegistry.get_provider("openai")
        assert openai is not None
        assert openai.name == "openai"
        assert openai.api_base == "https://api.openai.com/v1"
        assert "gpt-4o" in openai.models_available

    def test_get_provider_returns_none_for_unknown(self):
        """get_provider returns None for unknown provider name."""
        result = ProviderRegistry.get_provider("unknown_provider")
        assert result is None


class TestRouteToProvider:
    """Test route_to_provider task-based routing."""

    def test_route_selects_provider_with_vision(self):
        """route_to_provider selects a provider supporting vision."""
        result = ProviderRegistry.route_to_provider(
            "image_analysis", {"needs_vision": True}
        )
        assert result is not None
        # Verify at least one model has vision support
        has_vision = any(
            caps.supports_vision
            for caps in result.capabilities.values()
        )
        assert has_vision

    def test_route_selects_local_provider_when_preferred(self):
        """route_to_provider prefers local provider when prefer_local=True."""
        result = ProviderRegistry.route_to_provider(
            "general", {"prefer_local": True}
        )
        assert result is not None
        assert result.is_local is True
        assert result.name == "ollama"

    def test_route_selects_by_min_context_window(self):
        """route_to_provider filters by minimum context window."""
        # Request a very large context window - only Google (2M) qualifies
        result = ProviderRegistry.route_to_provider(
            "long_document", {"min_context_window": 500000}
        )
        assert result is not None
        assert result.name == "google"

    def test_route_with_needs_tools(self):
        """route_to_provider selects provider with tool support."""
        result = ProviderRegistry.route_to_provider(
            "tool_use", {"needs_tools": True}
        )
        assert result is not None
        # Verify at least one model supports tools
        has_tools = any(
            caps.supports_tools
            for caps in result.capabilities.values()
        )
        assert has_tools

    def test_route_returns_none_when_no_match(self):
        """route_to_provider returns None when no provider matches."""
        # Require impossible combination
        result = ProviderRegistry.route_to_provider(
            "impossible", {"needs_vision": True, "min_context_window": 99999999}
        )
        assert result is None

    def test_route_with_needs_streaming(self):
        """route_to_provider filters by streaming support."""
        result = ProviderRegistry.route_to_provider(
            "streaming", {"needs_streaming": True}
        )
        assert result is not None


class TestModelCapabilitiesMetadata:
    """Test that built-in specs have correct capabilities metadata."""

    def test_openai_gpt4o_capabilities(self):
        """OpenAI gpt-4o has correct capabilities."""
        openai = ProviderRegistry.get_provider("openai")
        assert openai is not None
        caps = openai.capabilities["gpt-4o"]
        assert caps.context_window == 128000
        assert caps.supports_tools is True
        assert caps.supports_vision is True
        assert caps.supports_streaming is True
        assert caps.supports_json_mode is True

    def test_anthropic_claude_capabilities(self):
        """Anthropic claude-sonnet-4-20250514 has correct capabilities."""
        anthropic = ProviderRegistry.get_provider("anthropic")
        assert anthropic is not None
        caps = anthropic.capabilities["claude-sonnet-4-20250514"]
        assert caps.context_window == 200000
        assert caps.supports_tools is True
        assert caps.supports_vision is True
        assert caps.supports_streaming is True
        assert caps.supports_json_mode is True

    def test_ollama_llama3_capabilities(self):
        """Ollama llama3 has correct capabilities (limited)."""
        ollama = ProviderRegistry.get_provider("ollama")
        assert ollama is not None
        caps = ollama.capabilities["llama3"]
        assert caps.context_window == 8192
        assert caps.supports_tools is False
        assert caps.supports_vision is False
        assert caps.supports_streaming is True
        assert caps.supports_json_mode is False

    def test_google_gemini_pro_capabilities(self):
        """Google gemini-1.5-pro has correct capabilities."""
        google = ProviderRegistry.get_provider("google")
        assert google is not None
        caps = google.capabilities["gemini-1.5-pro"]
        assert caps.context_window == 2000000
        assert caps.supports_tools is True
        assert caps.supports_vision is True
        assert caps.supports_streaming is True
        assert caps.supports_json_mode is True

    def test_deepseek_capabilities(self):
        """DeepSeek deepseek-chat has correct capabilities."""
        deepseek = ProviderRegistry.get_provider("deepseek")
        assert deepseek is not None
        caps = deepseek.capabilities["deepseek-chat"]
        assert caps.context_window == 64000
        assert caps.supports_tools is True
        assert caps.supports_vision is False
        assert caps.supports_streaming is True
        assert caps.supports_json_mode is True

    def test_mistral_large_capabilities(self):
        """Mistral mistral-large has correct capabilities."""
        mistral = ProviderRegistry.get_provider("mistral")
        assert mistral is not None
        caps = mistral.capabilities["mistral-large"]
        assert caps.context_window == 128000
        assert caps.supports_tools is True
        assert caps.supports_vision is False
        assert caps.supports_streaming is True
        assert caps.supports_json_mode is True


class TestReset:
    """Test reset functionality."""

    def test_reset_clears_all_registrations(self):
        """reset() clears all registered providers."""
        assert len(ProviderRegistry.list_providers()) == 6
        ProviderRegistry.reset()
        assert len(ProviderRegistry.list_providers()) == 0
