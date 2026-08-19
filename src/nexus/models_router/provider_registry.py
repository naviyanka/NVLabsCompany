"""LLM Provider Registry with self-registration at import time.

Provides a pluggable provider system where LLM providers self-register,
capability metadata is tracked, and task-based routing selects the best provider.
"""

from dataclasses import dataclass, field


@dataclass
class ModelCapabilities:
    """Capabilities metadata for a specific LLM model."""

    context_window: int
    supports_tools: bool
    supports_vision: bool
    supports_streaming: bool
    supports_json_mode: bool


@dataclass
class LLMProviderSpec:
    """Specification for an LLM provider including models, pricing, and capabilities."""

    name: str
    models_available: list[str]
    pricing: dict[str, dict[str, float]]
    capabilities: dict[str, ModelCapabilities]
    api_base: str
    is_local: bool = False


class ProviderRegistry:
    """Singleton registry for LLM providers with task-based routing.

    Providers self-register at import time. The registry supports capability-based
    routing to select the best provider for a given task.
    """

    _instance: "ProviderRegistry | None" = None
    _providers: dict[str, LLMProviderSpec] = {}

    def __new__(cls) -> "ProviderRegistry":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._providers = {}
        return cls._instance

    @classmethod
    def register(cls, spec: LLMProviderSpec) -> None:
        """Register a provider spec in the registry."""
        cls._providers[spec.name] = spec

    @classmethod
    def get_provider(cls, name: str) -> LLMProviderSpec | None:
        """Get a provider spec by name, or None if not found."""
        return cls._providers.get(name)

    @classmethod
    def list_providers(cls) -> list[LLMProviderSpec]:
        """List all registered provider specs."""
        return list(cls._providers.values())

    @classmethod
    def unregister(cls, name: str) -> None:
        """Unregister a provider by name. Used for testing."""
        cls._providers.pop(name, None)

    @classmethod
    def reset(cls) -> None:
        """Clear all registrations. Used for testing."""
        cls._providers.clear()
        cls._instance = None

    @classmethod
    def route_to_provider(
        cls, task_type: str, requirements: dict
    ) -> LLMProviderSpec | None:
        """Select the best provider based on task requirements.

        Args:
            task_type: Type of task (currently unused, reserved for future routing).
            requirements: Dict with optional keys:
                - needs_vision (bool): Provider must support vision.
                - needs_tools (bool): Provider must support tool use.
                - min_context_window (int): Minimum context window size.
                - prefer_local (bool): Prefer local providers (e.g., Ollama).
                - needs_streaming (bool): Provider must support streaming.

        Returns:
            The best matching LLMProviderSpec, or None if no provider matches.
        """
        needs_vision = requirements.get("needs_vision", False)
        needs_tools = requirements.get("needs_tools", False)
        min_context_window = requirements.get("min_context_window", 0)
        prefer_local = requirements.get("prefer_local", False)
        needs_streaming = requirements.get("needs_streaming", False)

        candidates: list[LLMProviderSpec] = []

        for provider in cls._providers.values():
            # Check if at least one model in the provider meets all requirements
            has_qualifying_model = False
            for model in provider.models_available:
                caps = provider.capabilities.get(model)
                if caps is None:
                    continue
                if needs_vision and not caps.supports_vision:
                    continue
                if needs_tools and not caps.supports_tools:
                    continue
                if min_context_window and caps.context_window < min_context_window:
                    continue
                if needs_streaming and not caps.supports_streaming:
                    continue
                has_qualifying_model = True
                break

            if has_qualifying_model:
                candidates.append(provider)

        if not candidates:
            return None

        # If prefer_local, prioritize local providers
        if prefer_local:
            local_candidates = [p for p in candidates if p.is_local]
            if local_candidates:
                return local_candidates[0]

        # Return first matching candidate (non-local preferred order)
        return candidates[0]


# ============================================================
# Built-in provider specifications
# ============================================================

OPENAI_SPEC = LLMProviderSpec(
    name="openai",
    models_available=["gpt-4o", "gpt-4o-mini", "gpt-4-turbo"],
    pricing={
        "gpt-4o": {"input": 2.50, "output": 10.00},
        "gpt-4o-mini": {"input": 0.15, "output": 0.60},
        "gpt-4-turbo": {"input": 10.00, "output": 30.00},
    },
    capabilities={
        "gpt-4o": ModelCapabilities(
            context_window=128000,
            supports_tools=True,
            supports_vision=True,
            supports_streaming=True,
            supports_json_mode=True,
        ),
        "gpt-4o-mini": ModelCapabilities(
            context_window=128000,
            supports_tools=True,
            supports_vision=True,
            supports_streaming=True,
            supports_json_mode=True,
        ),
        "gpt-4-turbo": ModelCapabilities(
            context_window=128000,
            supports_tools=True,
            supports_vision=True,
            supports_streaming=True,
            supports_json_mode=True,
        ),
    },
    api_base="https://api.openai.com/v1",
)

ANTHROPIC_SPEC = LLMProviderSpec(
    name="anthropic",
    models_available=["claude-sonnet-4-20250514", "claude-3-5-haiku-20241022"],
    pricing={
        "claude-sonnet-4-20250514": {"input": 3.00, "output": 15.00},
        "claude-3-5-haiku-20241022": {"input": 0.80, "output": 4.00},
    },
    capabilities={
        "claude-sonnet-4-20250514": ModelCapabilities(
            context_window=200000,
            supports_tools=True,
            supports_vision=True,
            supports_streaming=True,
            supports_json_mode=True,
        ),
        "claude-3-5-haiku-20241022": ModelCapabilities(
            context_window=200000,
            supports_tools=True,
            supports_vision=True,
            supports_streaming=True,
            supports_json_mode=True,
        ),
    },
    api_base="https://api.anthropic.com",
)

OLLAMA_SPEC = LLMProviderSpec(
    name="ollama",
    models_available=["llama3", "mistral", "codellama"],
    pricing={
        "llama3": {"input": 0.0, "output": 0.0},
        "mistral": {"input": 0.0, "output": 0.0},
        "codellama": {"input": 0.0, "output": 0.0},
    },
    capabilities={
        "llama3": ModelCapabilities(
            context_window=8192,
            supports_tools=False,
            supports_vision=False,
            supports_streaming=True,
            supports_json_mode=False,
        ),
        "mistral": ModelCapabilities(
            context_window=32768,
            supports_tools=False,
            supports_vision=False,
            supports_streaming=True,
            supports_json_mode=False,
        ),
        "codellama": ModelCapabilities(
            context_window=16384,
            supports_tools=False,
            supports_vision=False,
            supports_streaming=True,
            supports_json_mode=False,
        ),
    },
    api_base="http://localhost:11434",
    is_local=True,
)

DEEPSEEK_SPEC = LLMProviderSpec(
    name="deepseek",
    models_available=["deepseek-chat", "deepseek-coder"],
    pricing={
        "deepseek-chat": {"input": 0.14, "output": 0.28},
        "deepseek-coder": {"input": 0.14, "output": 0.28},
    },
    capabilities={
        "deepseek-chat": ModelCapabilities(
            context_window=64000,
            supports_tools=True,
            supports_vision=False,
            supports_streaming=True,
            supports_json_mode=True,
        ),
        "deepseek-coder": ModelCapabilities(
            context_window=64000,
            supports_tools=True,
            supports_vision=False,
            supports_streaming=True,
            supports_json_mode=True,
        ),
    },
    api_base="https://api.deepseek.com",
)

MISTRAL_SPEC = LLMProviderSpec(
    name="mistral",
    models_available=["mistral-large", "mistral-medium"],
    pricing={
        "mistral-large": {"input": 2.00, "output": 6.00},
        "mistral-medium": {"input": 2.70, "output": 8.10},
    },
    capabilities={
        "mistral-large": ModelCapabilities(
            context_window=128000,
            supports_tools=True,
            supports_vision=False,
            supports_streaming=True,
            supports_json_mode=True,
        ),
        "mistral-medium": ModelCapabilities(
            context_window=32768,
            supports_tools=True,
            supports_vision=False,
            supports_streaming=True,
            supports_json_mode=False,
        ),
    },
    api_base="https://api.mistral.ai",
)

GOOGLE_SPEC = LLMProviderSpec(
    name="google",
    models_available=["gemini-1.5-pro", "gemini-1.5-flash", "gemini-2.0-flash"],
    pricing={
        "gemini-1.5-pro": {"input": 1.25, "output": 5.00},
        "gemini-1.5-flash": {"input": 0.075, "output": 0.30},
        "gemini-2.0-flash": {"input": 0.10, "output": 0.40},
    },
    capabilities={
        "gemini-1.5-pro": ModelCapabilities(
            context_window=2000000,
            supports_tools=True,
            supports_vision=True,
            supports_streaming=True,
            supports_json_mode=True,
        ),
        "gemini-1.5-flash": ModelCapabilities(
            context_window=1000000,
            supports_tools=True,
            supports_vision=True,
            supports_streaming=True,
            supports_json_mode=True,
        ),
        "gemini-2.0-flash": ModelCapabilities(
            context_window=1000000,
            supports_tools=True,
            supports_vision=True,
            supports_streaming=True,
            supports_json_mode=True,
        ),
    },
    api_base="https://generativelanguage.googleapis.com",
)

# ============================================================
# Self-registration of built-in providers at import time
# ============================================================

ProviderRegistry.register(OPENAI_SPEC)
ProviderRegistry.register(ANTHROPIC_SPEC)
ProviderRegistry.register(OLLAMA_SPEC)
ProviderRegistry.register(DEEPSEEK_SPEC)
ProviderRegistry.register(MISTRAL_SPEC)
ProviderRegistry.register(GOOGLE_SPEC)
