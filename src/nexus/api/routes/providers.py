"""Agent providers API — exposes provider presets merged with CLI backend detection."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter

router = APIRouter(tags=["providers"])


@router.get("/api/v1/agent-providers")
async def list_agent_providers() -> list[dict[str, Any]]:
    """List all supported agent providers with installation status.

    Merges static provider presets (spawn config, model flags, docs) with
    live CLI backend detection (which CLIs are actually on PATH).
    """
    from nexus.adapters.cli_registry import CLIRegistry
    from nexus.adapters.provider_presets import PROVIDER_PRESETS, AgentProviderID

    # Detect installed CLI backends
    cli_registry = CLIRegistry(auto_detect=True)

    results: list[dict[str, Any]] = []
    for provider_id, preset in PROVIDER_PRESETS.items():
        # Skip 'custom' — it's a catch-all with no useful config
        if provider_id == AgentProviderID.custom:
            continue

        # Check if the CLI command is installed
        installed = (
            cli_registry.is_available(preset.default_command)
            if preset.default_command
            else False
        )
        version = None
        if installed:
            # Try to detect version
            for backend in cli_registry.get_all():
                if backend.command == preset.default_command:
                    version = cli_registry.probe_version(backend.id)
                    break

        results.append({
            "id": provider_id.value,
            "label": preset.label,
            "default_command": preset.default_command,
            "auto_mode_flag": preset.auto_mode_flag,
            "supports_model": preset.supports_model,
            "model_flag": preset.model_flag,
            "hive_aware": preset.hive_aware,
            "can_receive_inbox": preset.can_receive_inbox,
            "recommended_model": preset.recommended_orchestrator_model,
            "resume_flag": preset.resume_flag,
            "install_command": preset.install_command,
            "docs_url": preset.docs_url,
            "installed": installed,
            "version": version,
        })

    # Also include CLI-only backends not in PROVIDER_PRESETS (kiro-cli, aider)
    preset_commands = {p.default_command for p in PROVIDER_PRESETS.values()}
    for backend in cli_registry.get_all():
        if backend.command not in preset_commands:
            installed = cli_registry.is_available(backend.id)
            version = cli_registry.probe_version(backend.id) if installed else None
            results.append({
                "id": backend.id,
                "label": backend.name,
                "default_command": backend.command,
                "auto_mode_flag": "",
                "supports_model": True,
                "model_flag": "--model",
                "hive_aware": False,
                "can_receive_inbox": backend.supports_stdin,
                "recommended_model": None,
                "resume_flag": None,
                "install_command": None,
                "docs_url": None,
                "installed": installed,
                "version": version,
            })

    return results


@router.get("/api/v1/agent-providers/{provider_id}")
async def get_agent_provider(provider_id: str) -> dict[str, Any]:
    """Get detailed configuration for a specific provider."""
    from fastapi import HTTPException, status

    from nexus.adapters.provider_presets import PROVIDER_PRESETS, AgentProviderID

    try:
        pid = AgentProviderID(provider_id)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=(
                f"Provider '{provider_id}' not found. Available: "
                f"{', '.join(p.value for p in AgentProviderID if p != AgentProviderID.custom)}"
            ),
        )

    preset = PROVIDER_PRESETS.get(pid)
    if preset is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Provider '{provider_id}' has no preset configuration",
        )

    from nexus.adapters.cli_registry import CLIRegistry

    cli_registry = CLIRegistry(auto_detect=True)
    installed = (
        cli_registry.is_available(preset.default_command)
        if preset.default_command
        else False
    )

    return {
        "id": pid.value,
        "label": preset.label,
        "default_command": preset.default_command,
        "auto_mode_flag": preset.auto_mode_flag,
        "supports_model": preset.supports_model,
        "model_flag": preset.model_flag,
        "hive_aware": preset.hive_aware,
        "can_receive_inbox": preset.can_receive_inbox,
        "recommended_model": preset.recommended_orchestrator_model,
        "resume_flag": preset.resume_flag,
        "install_command": preset.install_command,
        "docs_url": preset.docs_url,
        "installed": installed,
        "non_interactive_env": (
            dict(preset.non_interactive_env) if preset.non_interactive_env else {}
        ),
    }


# Static model catalogs per provider. These are the commonly-used models
# available through each CLI/provider. Updated periodically.
PROVIDER_MODELS: dict[str, list[dict[str, str]]] = {
    "claude": [
        {"id": "claude-sonnet-4-20250514", "name": "Claude Sonnet 4", "tier": "flagship"},
        {"id": "claude-opus-4-20250514", "name": "Claude Opus 4", "tier": "flagship"},
        {"id": "claude-haiku-4-20250514", "name": "Claude Haiku 4", "tier": "fast"},
        {"id": "claude-sonnet-4-5-20250514", "name": "Claude Sonnet 4.5", "tier": "flagship"},
        {"id": "claude-3-7-sonnet-20250219", "name": "Claude 3.7 Sonnet", "tier": "balanced"},
        {"id": "claude-3-5-haiku-20241022", "name": "Claude 3.5 Haiku", "tier": "fast"},
    ],
    "codex": [
        {"id": "gpt-4o", "name": "GPT-4o", "tier": "flagship"},
        {"id": "gpt-4o-mini", "name": "GPT-4o Mini", "tier": "fast"},
        {"id": "o3", "name": "o3", "tier": "reasoning"},
        {"id": "o3-mini", "name": "o3 Mini", "tier": "reasoning"},
        {"id": "o4-mini", "name": "o4 Mini", "tier": "reasoning"},
        {"id": "gpt-4.1", "name": "GPT-4.1", "tier": "flagship"},
        {"id": "gpt-4.1-mini", "name": "GPT-4.1 Mini", "tier": "fast"},
    ],
    "grok": [
        {"id": "grok-3", "name": "Grok 3", "tier": "flagship"},
        {"id": "grok-3-mini", "name": "Grok 3 Mini", "tier": "fast"},
        {"id": "grok-3-fast", "name": "Grok 3 Fast", "tier": "fast"},
    ],
    "kimi": [
        {"id": "kimi-latest", "name": "Kimi Latest", "tier": "flagship"},
        {"id": "moonshot-v1-128k", "name": "Moonshot v1 128K", "tier": "flagship"},
    ],
    "antigravity": [
        {"id": "gemini-2.5-pro", "name": "Gemini 2.5 Pro", "tier": "flagship"},
        {"id": "gemini-2.5-flash", "name": "Gemini 2.5 Flash", "tier": "fast"},
        {"id": "gemini-2.0-flash", "name": "Gemini 2.0 Flash", "tier": "fast"},
    ],
    "qwen": [
        {"id": "qwen3-coder-plus", "name": "Qwen3 Coder Plus", "tier": "flagship"},
        {"id": "qwen3-coder", "name": "Qwen3 Coder", "tier": "balanced"},
        {"id": "qwen3-235b", "name": "Qwen3 235B", "tier": "flagship"},
        {"id": "qwen3-32b", "name": "Qwen3 32B", "tier": "balanced"},
    ],
    "opencode": [
        {"id": "anthropic/claude-sonnet-4", "name": "Claude Sonnet 4", "tier": "flagship"},
        {"id": "openai/gpt-4o", "name": "GPT-4o", "tier": "flagship"},
        {"id": "google/gemini-2.5-pro", "name": "Gemini 2.5 Pro", "tier": "flagship"},
    ],
    "crush": [
        {"id": "openai/gpt-4o", "name": "GPT-4o", "tier": "flagship"},
        {"id": "anthropic/claude-sonnet-4", "name": "Claude Sonnet 4", "tier": "flagship"},
        {"id": "openai/o3-mini", "name": "o3 Mini", "tier": "reasoning"},
    ],
    "pi": [
        {"id": "anthropic/claude-sonnet-4-5", "name": "Claude Sonnet 4.5", "tier": "flagship"},
        {"id": "anthropic/claude-sonnet-4", "name": "Claude Sonnet 4", "tier": "flagship"},
        {"id": "openai/gpt-4o", "name": "GPT-4o", "tier": "flagship"},
    ],
    "copilot": [
        {"id": "claude-sonnet-4", "name": "Claude Sonnet 4", "tier": "flagship"},
        {"id": "gpt-4o", "name": "GPT-4o", "tier": "flagship"},
        {"id": "o3-mini", "name": "o3 Mini", "tier": "reasoning"},
        {"id": "gemini-2.5-pro", "name": "Gemini 2.5 Pro", "tier": "flagship"},
    ],
    "kiro-cli": [
        {"id": "claude-sonnet-4", "name": "Claude Sonnet 4", "tier": "flagship"},
        {"id": "claude-sonnet-4-5", "name": "Claude Sonnet 4.5", "tier": "flagship"},
        {"id": "claude-haiku-4", "name": "Claude Haiku 4", "tier": "fast"},
    ],
    "aider": [
        {"id": "claude-sonnet-4", "name": "Claude Sonnet 4 (Anthropic)", "tier": "flagship"},
        {"id": "gpt-4o", "name": "GPT-4o (OpenAI)", "tier": "flagship"},
        {"id": "deepseek/deepseek-chat", "name": "DeepSeek Chat", "tier": "balanced"},
        {"id": "ollama/llama3.1", "name": "Llama 3.1 (local)", "tier": "local"},
        {"id": "gemini/gemini-2.5-pro", "name": "Gemini 2.5 Pro", "tier": "flagship"},
    ],
}


@router.get("/api/v1/agent-providers/{provider_id}/models")
async def list_provider_models(provider_id: str) -> list[dict[str, str]]:
    """List available models for a specific provider.

    Returns a curated list of models known to work with the given provider CLI.
    """
    from fastapi import HTTPException, status

    from nexus.adapters.provider_presets import AgentProviderID

    try:
        AgentProviderID(provider_id)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Provider '{provider_id}' not found",
        )

    return PROVIDER_MODELS.get(provider_id, [])
