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
    "hermes": {
        # Nous Research Hermes 3 — local Ollama with OpenRouter cloud fallback.
        # Config keys follow HermesAdapter.create_session expectations:
        # ollama_host + openrouter_api_key (NOT the generic "host").
        "registry_key": "hermes",
        "env_key": None,
        "default_model": "hermes3:8b",
        "host": "http://localhost:11434",
        "supports_streaming": True,
        "supports_tools": True,
        "models": [
            "hermes3:8b",
            "nousresearch/hermes-3-llama-3.1-8b",
            "nousresearch/hermes-3-llama-3.1-405b",
        ],
    },
    # Claude Code dedicated subprocess adapter
    "claude_code": {
        "registry_key": "claude_code",
        "env_key": None,
        "supports_streaming": False,
        "supports_tools": True,
        "models": [],
    },
    # Generic CLI backends (subprocess-based)
    "cli": {"registry_key": "cli", "backend": "claude", "env_key": None},
    "codex": {"registry_key": "cli", "backend": "codex", "env_key": None},
    "aider": {"registry_key": "cli", "backend": "aider", "env_key": None},
    "kiro-cli": {"registry_key": "cli", "backend": "kiro-cli", "env_key": None},
    "agy": {"registry_key": "cli", "backend": "agy", "env_key": None},
    "opencode": {"registry_key": "cli", "backend": "opencode", "env_key": None},
    "cursor": {"registry_key": "cli", "backend": "cursor", "env_key": None},
    "hermes-cli": {
        # Uses the same Nous Portal backend as the hermes CLI app.
        # Reads auth token from hermes auth.json (same credentials).
        "registry_key": "hermes",
        "env_key": None,
        "default_model": "poolside/laguna-s-2.1:free",
        "host": "http://localhost:11434",
        "supports_streaming": True,
        "supports_tools": True,
        "models": [
            "poolside/laguna-s-2.1:free",
            "nousresearch/hermes-4-405b",
            "nousresearch/hermes-4-70b",
            "anthropic/claude-sonnet-4",
            "deepseek/deepseek-chat",
        ],
    },
}

# Aliases for backward compatibility. "claude" historically resolved to the
# Anthropic API adapter in chat routing (NOT the Claude Code CLI), so it stays
# an alias here to avoid silently switching existing agents to subprocesses.
PROVIDER_ALIASES: dict[str, str] = {
    "langchain": "anthropic",
    "claude": "anthropic",
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
    elif registry_key == "hermes":
        config["model"] = model or provider.get("default_model", "")
        config["ollama_host"] = os.environ.get(
            "OLLAMA_HOST", provider.get("host", "http://localhost:11434")
        )
        config["openrouter_api_key"] = os.environ.get("OPENROUTER_API_KEY", "")
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
