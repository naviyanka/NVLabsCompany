"""Agent providers API — serializes the canonical CLI backend catalog.

``nexus.adapters.cli_registry`` is the single source of truth; this module
only exposes it. Nothing here accepts an executable path or command from the
request, and nothing here runs an LLM task.
"""

from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, HTTPException, status

from nexus.adapters.cli_registry import get_cli_registry
from nexus.api.deps import require_permission

router = APIRouter(tags=["providers"])


def _canonical_id(backend_id: str) -> str:
    """Resolve an ID or alias to its canonical backend ID, or 404."""
    registry = get_cli_registry()
    canonical = registry.resolve_backend_id(backend_id)
    if canonical is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "code": "CLI_BACKEND_UNKNOWN",
                "message": f"Unknown CLI backend '{backend_id}'.",
            },
        )
    return canonical


@router.get("/api/v1/agent-providers")
async def list_agent_providers() -> list[dict[str, Any]]:
    """List every cataloged CLI backend with detection and capability status."""
    registry = get_cli_registry()
    # Version probes spawn subprocesses; keep them off the event loop.
    return await asyncio.to_thread(
        lambda: [registry.describe(b.id) for b in registry.get_all()]
    )


@router.get("/api/v1/agent-providers/{backend_id}")
async def get_agent_provider(backend_id: str) -> dict[str, Any]:
    """Describe one backend; aliases (e.g. ``antigravity``) resolve."""
    canonical = _canonical_id(backend_id)
    return await asyncio.to_thread(get_cli_registry().describe, canonical)


@router.get("/api/v1/agent-providers/{backend_id}/models")
async def list_provider_models(backend_id: str) -> list[dict[str, str]]:
    """Verified default models for a backend. Custom model strings are allowed."""
    backend = get_cli_registry().get_backend(_canonical_id(backend_id))
    return [{"id": m, "name": m} for m in backend.default_models]


@router.post(
    "/api/v1/agent-providers/{backend_id}/probe",
    dependencies=[require_permission("write", "agent")],
)
async def probe_agent_provider(backend_id: str) -> dict[str, Any]:
    """Re-detect one backend: PATH lookup plus a timed ``--version`` probe.

    Only cataloged command candidates are probed. No prompt is sent, so no
    tokens are consumed.
    """
    canonical = _canonical_id(backend_id)
    registry = get_cli_registry()
    await asyncio.to_thread(registry.refresh, True)
    info = await asyncio.to_thread(registry.describe, canonical)
    error = None
    if not info["installed"]:
        error = "Executable not found on PATH."
    elif not info["execution_supported"]:
        error = "Backend is catalog-only; non-interactive execution is not verified."
    elif info["version"] is None:
        error = "Executable found but version probe failed or timed out."
    return {
        "id": canonical,
        "installed": info["installed"],
        "resolved_command": info["resolved_command"],
        "version": info["version"],
        "execution_supported": info["execution_supported"],
        "configured": info["configured"],
        "ok": error is None,
        "error": error,
    }
