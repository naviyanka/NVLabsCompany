"""Tests for chat adapter resolution via UASTL and control router mounting.

Covers the Phase 0 gap-closure fixes:
- F-01: hermes adapter_type resolves to the Hermes adapter (not anthropic).
- F-03: chat routing delegates to the UASTL provider registry (no dead module).
- F-02: the control router is mounted under /api/v1.
"""

import os
import uuid

import pytest

from nexus.adapters import uastl
from nexus.api.routes.chat import _resolve_adapter_type


class _FakeAgent:
    """Minimal stand-in for the Agent model fields used in resolution."""

    def __init__(self, adapter_type=None, model=None):
        self.adapter_type = adapter_type
        self.model = model


def test_hermes_resolves_to_hermes_registry_key():
    key, config = _resolve_adapter_type(_FakeAgent("hermes", "hermes3:8b"))
    assert key == "hermes"
    assert config["model"] == "hermes3:8b"
    # HermesAdapter expects ollama_host + openrouter_api_key, not generic host
    assert "ollama_host" in config
    assert "openrouter_api_key" in config


def test_hermes_default_model():
    key, config = _resolve_adapter_type(_FakeAgent("hermes"))
    assert key == "hermes"
    assert config["model"] == uastl.PROVIDERS["hermes"]["default_model"]


def test_legacy_mappings_preserved():
    cases = {
        "anthropic": "anthropic",
        "openai": "openai",
        "claude": "anthropic",  # historical: claude meant the Anthropic API
        "claude_code": "claude_code",
        "cli": "cli",
        "ollama": "ollama",
        "azure": "azure_openai",
        "bedrock": "bedrock",
        "google": "google_gemini",
        "langchain": "anthropic",
    }
    for adapter_type, expected_key in cases.items():
        key, _ = _resolve_adapter_type(_FakeAgent(adapter_type))
        assert key == expected_key, f"{adapter_type} -> {key}, expected {expected_key}"


def test_unknown_defaults_to_anthropic():
    key, config = _resolve_adapter_type(_FakeAgent("does-not-exist"))
    assert key == "anthropic"
    assert "api_key" in config


def test_none_defaults_to_anthropic():
    key, _ = _resolve_adapter_type(_FakeAgent())
    assert key == "anthropic"


def test_model_override_passthrough():
    _, config = _resolve_adapter_type(_FakeAgent("openai", "gpt-4o-mini"))
    assert config["model"] == "gpt-4o-mini"


def test_cli_backend_resolution():
    _, config = _resolve_adapter_type(_FakeAgent("codex"))
    assert config["backend"] == "codex"


def test_ollama_host_config():
    _, config = _resolve_adapter_type(_FakeAgent("ollama"))
    assert config["host"] == "http://localhost:11434"


def test_uastl_lists_providers_including_hermes():
    providers = {p["id"]: p for p in uastl.list_available_providers()}
    assert "hermes" in providers
    assert providers["hermes"]["registry_key"] == "hermes"


def _all_app_paths(app) -> set:
    """Collect every routable path, recursing into included routers.

    Newer FastAPI versions wrap include_router() results in _IncludedRouter
    objects instead of flattening APIRoutes into app.routes.
    """
    paths: set = set()
    for route in app.routes:
        path = getattr(route, "path", None)
        if path:
            paths.add(path)
        original = getattr(route, "original_router", None)
        if original is not None:
            for sub in original.routes:
                sub_path = getattr(sub, "path", None)
                if sub_path:
                    paths.add(sub_path)
    return paths


def test_control_router_mounted_under_api_v1():
    from nexus.main import app

    paths = _all_app_paths(app)
    for expected in (
        "/api/v1/control/{agent_id}/pause",
        "/api/v1/control/{agent_id}/steer",
        "/api/v1/control/{agent_id}/snapshot",
    ):
        assert expected in paths, f"{expected} not mounted"


@pytest.mark.asyncio
async def test_get_history_fresh_reloads_after_ttl(monkeypatch):
    import asyncio

    from nexus.api.routes import chat as chat_module

    agent_id = "11111111-1111-1111-1111-111111111111"
    company_id = uuid.uuid4()
    chat_module._conversations.pop(agent_id, None)
    chat_module._cache_loaded_at.pop(agent_id, None)

    calls = {"n": 0}

    async def fake_load(db, aid, cid, limit=100):
        calls["n"] += 1
        return [{"id": "m1", "sender": "user", "text": "hi", "timestamp": ""}]

    monkeypatch.setattr(chat_module, "_load_history_from_db", fake_load)

    history = await chat_module._get_history_fresh(None, agent_id, company_id)
    assert len(history) == 1
    assert calls["n"] == 1

    history = await chat_module._get_history_fresh(None, agent_id, company_id)
    assert calls["n"] == 1  # served from fresh cache

    chat_module._cache_loaded_at[agent_id] -= chat_module._CACHE_TTL_SECONDS + 1
    await chat_module._get_history_fresh(None, agent_id, company_id)
    assert calls["n"] == 2  # stale cache triggers DB reload

    chat_module._conversations.pop(agent_id, None)
    chat_module._cache_loaded_at.pop(agent_id, None)
