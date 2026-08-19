"""Degradation dashboard endpoint for system capability status.

Provides a GET /system/degradation endpoint that checks the availability
of optional system components and reports their status as full, degraded,
or unavailable.
"""

import shutil

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from nexus.config import settings

router = APIRouter(tags=["system"])


async def _check_redis() -> dict[str, str]:
    """Check Redis connectivity by attempting a PING.

    Returns:
        Dict with 'status' (full/unavailable) and 'detail'.
    """
    try:
        import redis.asyncio as aioredis

        client = aioredis.from_url(
            settings.redis_url,
            decode_responses=True,
            socket_connect_timeout=2.0,
            socket_timeout=2.0,
        )
        try:
            result = await client.ping()
            if result:
                return {"status": "full", "detail": "Redis responding to PING"}
            return {"status": "unavailable", "detail": "Redis PING returned False"}
        finally:
            await client.aclose()
    except Exception as exc:
        return {"status": "unavailable", "detail": f"Redis unreachable: {exc}"}


def _check_docker() -> dict[str, str]:
    """Check Docker availability via shutil.which.

    Returns:
        Dict with 'status' (full/unavailable) and 'detail'.
    """
    docker_path = shutil.which("docker")
    if docker_path:
        return {"status": "full", "detail": f"Docker found at {docker_path}"}
    return {"status": "unavailable", "detail": "Docker binary not found in PATH"}


def _check_llm() -> dict[str, str]:
    """Check LLM provider reachability by verifying API keys are configured.

    Returns:
        Dict with 'status' (full/degraded/unavailable) and 'detail'.
    """
    has_openai = bool(settings.openai_api_key)
    has_anthropic = bool(settings.anthropic_api_key)

    if has_openai and has_anthropic:
        return {"status": "full", "detail": "Both OpenAI and Anthropic keys configured"}
    if has_openai or has_anthropic:
        provider = "OpenAI" if has_openai else "Anthropic"
        return {
            "status": "degraded",
            "detail": f"Only {provider} API key configured",
        }
    return {"status": "unavailable", "detail": "No LLM API keys configured"}


def _check_embedding() -> dict[str, str]:
    """Check embedding provider status based on API key availability.

    Returns:
        Dict with 'status' (full/unavailable) and 'detail'.
    """
    if settings.openai_api_key:
        return {"status": "full", "detail": "OpenAI embeddings available"}
    return {"status": "unavailable", "detail": "No embedding provider configured"}


def _check_mempalace() -> dict[str, str]:
    """Check mempalace (layered memory) availability.

    Returns:
        Dict with 'status' and 'detail'.
    """
    try:
        from nexus.memory.layered import LayeredMemoryStore  # noqa: F401

        return {"status": "full", "detail": "LayeredMemoryStore importable"}
    except ImportError:
        return {"status": "unavailable", "detail": "Memory module not available"}


@router.get("/system/degradation")
async def degradation_status() -> JSONResponse:
    """Return system degradation status for all optional components.

    Checks Redis, Docker, LLM, embedding, and mempalace availability.
    Returns a structured JSON response with per-feature status.

    Status values:
    - full: Component fully operational.
    - degraded: Component partially available (reduced functionality).
    - unavailable: Component not available (feature disabled).
    """
    redis_status = await _check_redis()
    docker_status = _check_docker()
    llm_status = _check_llm()
    embedding_status = _check_embedding()
    mempalace_status = _check_mempalace()

    features = {
        "redis": redis_status,
        "docker": docker_status,
        "llm": llm_status,
        "embedding": embedding_status,
        "mempalace": mempalace_status,
    }

    # Determine overall system status
    statuses = [f["status"] for f in features.values()]
    if all(s == "full" for s in statuses):
        overall = "full"
    elif any(s == "unavailable" for s in statuses):
        overall = "degraded"
    else:
        overall = "degraded"

    return JSONResponse(
        status_code=200,
        content={
            "overall_status": overall,
            "features": features,
        },
    )
