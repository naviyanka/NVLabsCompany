"""Universal API Schema Translation Layer (UASTL) — from OpenCompany.

Config-driven provider resolution that eliminates hardcoded adapter mappings.
Providers are defined with their capabilities, env vars, and model catalogs.
Adding a new provider requires only adding an entry here — no code changes.
"""

import os
from typing import Any


# Provider definitions — the single source of truth for adapter resolution
PROVIDERS: dict[str, dict[str, Any]] = {
    "anthropic": {
        "registry_key": "anthropic",
        "env_key": "ANTHROPIC_API_KEY",
        "default_model": "claude-sonnet-4-20250514",
        "supports_streaming": True,
        "supports_tools": True,
        "models": ["claude-opus-4", "claude-sonnet-4", "claude-haiku-4", "claude-sonnet-4-5"],
    },
    "openai": {
        "registry_key": "openai",
        "env_key": "OPENAI_API_KEY",
        "default_model": "gpt-4o",
        "supports_streaming": True,
        "supports_tools": True,
        "models": ["gpt-4o", "gpt-4o-mini", "o3", "o3-mini", "gpt-4.1"],
    },
    "ollama": {
        "registry_key": "ollama",
        "env_key": None,
        "default_model": "llama3.1",
        "host": "http://localhost:11434",
        "supports_streaming": False,
        "supports_tools": False,
        "models": ["llama3.1", "llama3.2", "mistral", "codellama", "qwen2"],
    },
    "google": {
        "registry_key": "google_gemini",
        "env_key": "GOOGLE_API_KEY",
        "default_model": "gemini-2.5-pro",
        "supports_streaming": False,
        "supports_tools": True,
        "models": ["gemini-2.5-pro", "gemini-2.5-flash", "gemini-2.0-flash"],
    },
    "azure": {
        "registry_key": "azure_openai",
        "env_key": "AZURE_OPENAI_API_KEY",
        "default_model": "gpt-4o",
        "supports_streaming": True,
        "supports_tools": True,
        "models": ["gpt-4o", "gpt-4o-mini"],
    },
    "bedrock": {
        "registry_key": "bedrock",
        "env_key": "AWS_SECRET_ACCESS_KEY",
        "default_model": "anthropic.claude-3-5-sonnet",
        "supports_streaming": False,
        "supports_tools": False,
        "models": ["anthropic.claude-3-5-sonnet", "anthropic.claude-3-haiku"],
    },
    "deepseek": {
        "registry_key": "openai",  # DeepSeek uses OpenAI-compatible API
        "env_key": "DEEPSEEK_API_KEY",
        "api_base": "https://api.deepseek.com/v1",
        "default_model": "deepseek-chat",
        "supports_streaming": True,
        "supports_tools": True,
        "models": ["deepseek-chat", "deepseek-coder"],
    },
    "groq": {
        "registry_key": "openai",  # Groq uses OpenAI-compatible API
        "env_key": "GROQ_API_KEY",
        "api_base": "https://api.groq.com/openai/v1",
        "default_model": "llama-3.1-70b-versatile",
        "supports_streaming": True,
        "supports_tools": False,
        "models": ["llama-3.1-70b-versatile", "mixtral-8x7b-32768"],
    },
    # CLI backends (subprocess-based)
    "claude": {"registry_key": "cli", "backend": "claude", "env_key": None},
    "codex": {"registry_key": "cli", "backend": "codex", "env_key": None},
    "aider": {"registry_key": "cli", "backend": "aider", "env_key": None},
    "kiro-cli": {"registry_key": "cli", "backend": "kiro-cli", "env_key": None},
    "agy": {"registry_key": "cli", "backend": "agy", "env_key": None},
    "opencode": {"registry_key": "cli", "backend": "opencode", "env_key": None},
    "cursor": {"registry_key": "cli", "backend": "cursor", "env_key": None},
}

# Aliases for backward compatibility
PROVIDER_ALIASES: dict[str, str] = {
    "langchain": "anthropic",
    "claude_code": "claude",
    "antigravity": "agy",
}


def resolve_provider(adapter_type: str, model: str | None = None) -> tuple[str, dict[str, Any]]:
    """Resolve an adapter_type to a registry key and config dict.

    This replaces the hardcoded dict in chat.py's _resolve_adapter_type().

    Args:
        adapter_type: The agent's configured adapter type.
        model: Optional model override.

    Returns:
        Tuple of (registry_key, config_dict).
    """
    # Resolve aliases
    provider_name = PROVIDER_ALIASES.get(adapter_type, adapter_type)
    provider = PROVIDERS.get(provider_name)

    if provider is None:
        # Default to anthropic
        provider = PROVIDERS["anthropic"]

    registry_key = provider["registry_key"]
    config: dict[str, Any] = {}

    # Build config based on provider type
    if registry_key == "cli":
        config["backend"] = provider.get("backend", adapter_type)
        config["model"] = model or ""
    else:
        env_key = provider.get("env_key")
        if env_key:
            config["api_key"] = os.environ.get(env_key, "")
        config["model"] = model or provider.get("default_model", "")
        if "host" in provider:
            config["host"] = provider["host"]
        if "api_base" in provider:
            config["api_base"] = provider["api_base"]

    return registry_key, config


def list_available_providers() -> list[dict[str, Any]]:
    """List all configured providers with their availability status."""
    result = []
    for name, spec in PROVIDERS.items():
        if name in PROVIDER_ALIASES.values():
            continue  # Skip alias targets that are also providers
        env_key = spec.get("env_key")
        available = True
        if env_key:
            available = bool(os.environ.get(env_key))
        result.append({
            "id": name,
            "registry_key": spec["registry_key"],
            "default_model": spec.get("default_model"),
            "available": available,
            "supports_streaming": spec.get("supports_streaming", False),
            "models": spec.get("models", []),
        })
    return result
