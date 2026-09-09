"""Gateway model catalog discovery (WP-22c step 5: real context windows).

An OpenAI-compatible gateway exposes ``GET /v1/models`` with a real
``context_length`` / ``max_input_tokens`` / ``max_output_tokens`` per model.
Registering those into the ProviderRegistry makes ModelCapabilityResolver
return the true window instead of the 8K DEFAULT_LIMITS, so
memory/compaction.py stops truncating a 200K-context model at 8K.

Fail-open (R12): any transport or parse error leaves the static registry
untouched and returns 0 — discovery never blocks boot.

No vendor name appears here (R9); the endpoint is any Connection base_url.
"""

from __future__ import annotations

from typing import Any

from nexus.models_router.provider_registry import (
    LLMProviderSpec,
    ModelCapabilities,
    ProviderRegistry,
)

# Registry provider name for discovered models. Kept distinct from the static
# built-ins so a refresh can replace exactly this spec.
_DISCOVERED_PROVIDER = "gateway-discovered"


def _to_capabilities(model: dict[str, Any]) -> ModelCapabilities | None:
    """Map one /v1/models entry to ModelCapabilities, or None if no window."""
    ctx = model.get("context_length") or model.get("max_input_tokens")
    if not ctx:
        return None
    caps = model.get("capabilities") or {}
    return ModelCapabilities(
        context_window=int(ctx),
        supports_tools=bool(caps.get("tool_calling")),
        supports_vision=bool(caps.get("vision")),
        supports_streaming=True,
        supports_json_mode=False,
    )


def register_catalog(models: list[dict[str, Any]], api_base: str = "") -> int:
    """Register discovered models into the ProviderRegistry.

    Args:
        models: The ``data`` list from a ``/v1/models`` response.
        api_base: The gateway base URL (informational).

    Returns:
        Number of models registered (those carrying a usable context window).
    """
    capabilities: dict[str, ModelCapabilities] = {}
    for m in models:
        mid = m.get("id")
        caps = _to_capabilities(m)
        if mid and caps is not None:
            capabilities[mid] = caps
    if not capabilities:
        return 0
    ProviderRegistry.register(
        LLMProviderSpec(
            name=_DISCOVERED_PROVIDER,
            models_available=list(capabilities),
            pricing={},
            capabilities=capabilities,
            api_base=api_base,
        )
    )
    return len(capabilities)


# Per-base_url monotonic timestamp of the last successful discovery. In-memory
# on purpose: /v1/models is one cheap, unauthenticated, fail-open GET, so a
# process restart re-discovering is fine and a DB cache table would be a moving
# part earning nothing. ponytail: in-memory TTL, add a table only if restart
# re-fetch ever measurably hurts.
_last_discovered: dict[str, float] = {}


async def discover_models(
    base_url: str, api_key: str = "", ttl_seconds: int | None = None
) -> int:
    """Fetch ``{base_url}/models`` and register the catalog. Fail-open.

    Skips the fetch when the last successful discovery for ``base_url`` is
    younger than ``ttl_seconds`` (default: settings.gateway_catalog_refresh_seconds),
    returning -1 to mean "cache still fresh, nothing re-fetched". Returns the
    count registered on a fetch, or 0 on any error (static registry kept).
    """
    import time

    import httpx

    if ttl_seconds is None:
        from nexus.config import settings

        ttl_seconds = settings.gateway_catalog_refresh_seconds

    now = time.monotonic()
    last = _last_discovered.get(base_url)
    if last is not None and (now - last) < ttl_seconds:
        return -1

    url = f"{base_url.rstrip('/')}/models"
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(url, headers=headers)
            resp.raise_for_status()
            data = resp.json().get("data", [])
    except Exception:
        return 0
    n = register_catalog(data, api_base=base_url)
    _last_discovered[base_url] = now
    return n
