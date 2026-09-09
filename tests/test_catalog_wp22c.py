"""WP-22c step 5: discovered context windows beat the 8K default.

memory/compaction.py sizes history from ModelCapabilityResolver. At baseline
an unknown model resolves to DEFAULT_LIMITS (8192), so a 200K-context gateway
model would be compacted at 8K. Registering the discovered catalog fixes it.

R1: tests invoke the resolver and the registrar/discovery, not just import.
R10: discover_models is tested against httpx.MockTransport; no network.
"""

import httpx
import pytest

from nexus.models_router.capabilities import DEFAULT_LIMITS, ModelCapabilityResolver
from nexus.models_router.catalog import (
    _DISCOVERED_PROVIDER,
    discover_models,
    register_catalog,
)
from nexus.models_router.provider_registry import ProviderRegistry


# An id no family keyword in _FAMILY_LIMITS matches, so it hits DEFAULT_LIMITS
# unless the catalog registers it.
_UNKNOWN_ID = "ddgw/frontier-xl-9"

_MODELS = [
    {
        "id": _UNKNOWN_ID,
        "context_length": 200_000,
        "max_input_tokens": 200_000,
        "max_output_tokens": 32_000,
        "capabilities": {"tool_calling": True, "vision": True},
    },
    {"id": "ddgw/no-window", "capabilities": {}},  # dropped: no context_length
]


@pytest.fixture(autouse=True)
def _cleanup():
    yield
    ProviderRegistry.unregister(_DISCOVERED_PROVIDER)


def test_discovered_model_context_window_beats_default_limits():
    # Baseline behaviour: unknown id falls to the 8K default.
    assert ModelCapabilityResolver.resolve(_UNKNOWN_ID).context_window == DEFAULT_LIMITS.context_window

    n = register_catalog(_MODELS, api_base="http://gw/v1")
    assert n == 1  # the windowless model is skipped

    resolved = ModelCapabilityResolver.resolve(_UNKNOWN_ID)
    assert resolved.context_window == 200_000
    assert resolved.context_window != DEFAULT_LIMITS.context_window


def test_discover_models_registers_from_v1_models(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/models")
        return httpx.Response(200, json={"object": "list", "data": _MODELS})

    transport = httpx.MockTransport(handler)
    real_init = httpx.AsyncClient.__init__

    def _init(self, *a, **k):
        k["transport"] = transport
        real_init(self, *a, **k)

    monkeypatch.setattr(httpx.AsyncClient, "__init__", _init)

    import asyncio

    n = asyncio.run(discover_models("http://gw/v1", api_key="sk-x"))
    assert n == 1
    assert ModelCapabilityResolver.resolve(_UNKNOWN_ID).context_window == 200_000


def test_discover_models_skips_refetch_within_ttl(monkeypatch):
    """A second call within ttl_seconds returns -1 without re-fetching (M6)."""
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(200, json={"object": "list", "data": _MODELS})

    transport = httpx.MockTransport(handler)
    real_init = httpx.AsyncClient.__init__

    def _init(self, *a, **k):
        k["transport"] = transport
        real_init(self, *a, **k)

    monkeypatch.setattr(httpx.AsyncClient, "__init__", _init)

    import asyncio

    from nexus.models_router import catalog as cat

    cat._last_discovered.pop("http://ttl-gw/v1", None)
    assert asyncio.run(cat.discover_models("http://ttl-gw/v1", ttl_seconds=999)) == 1
    assert calls["n"] == 1
    # within TTL: cache fresh, no second fetch
    assert asyncio.run(cat.discover_models("http://ttl-gw/v1", ttl_seconds=999)) == -1
    assert calls["n"] == 1
    cat._last_discovered.pop("http://ttl-gw/v1", None)


def test_discover_models_fails_open_on_error(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500)

    transport = httpx.MockTransport(handler)
    real_init = httpx.AsyncClient.__init__

    def _init(self, *a, **k):
        k["transport"] = transport
        real_init(self, *a, **k)

    monkeypatch.setattr(httpx.AsyncClient, "__init__", _init)

    import asyncio

    from nexus.models_router import catalog as cat

    # Distinct base_url so a prior test's TTL cache can't mask the error path.
    cat._last_discovered.pop("http://err-gw/v1", None)
    # Fail-open (R12): a gateway error registers nothing and does not raise.
    assert asyncio.run(cat.discover_models("http://err-gw/v1")) == 0
