"""Degradation dashboard endpoint for system capability status.

Provides a GET /system/degradation endpoint that checks the availability
of optional system components and reports their status as full, degraded,
or unavailable.
"""

import os
import shutil

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from nexus.config import settings

router = APIRouter(tags=["system"])

# Module-level Redis client singleton to avoid connection churn.
# Lazily initialized on first use.
_redis_client = None
_redis_client_initialized = False


async def _get_redis_client():
    """Get or create a module-scoped Redis client singleton.

    Returns:
        The shared Redis async client, or None if initialization fails.
    """
    global _redis_client, _redis_client_initialized

    if _redis_client_initialized:
        return _redis_client

    try:
        import redis.asyncio as aioredis

        _redis_client = aioredis.from_url(
            settings.redis_url,
            decode_responses=True,
            socket_connect_timeout=2.0,
            socket_timeout=2.0,
        )
        _redis_client_initialized = True
        return _redis_client
    except Exception:
        _redis_client_initialized = True
        _redis_client = None
        return None


async def _check_redis() -> dict[str, str]:
    """Check Redis connectivity by attempting a PING.

    Reuses a module-scoped Redis client to avoid creating a new
    connection pool on every request.

    Returns:
        Dict with 'status' (full/unavailable) and 'detail'.
    """
    try:
        client = await _get_redis_client()
        if client is None:
            return {"status": "unavailable", "detail": "Redis client not configured"}
        result = await client.ping()
        if result:
            return {"status": "full", "detail": "Redis responding to PING"}
        return {"status": "unavailable", "detail": "Redis PING returned False"}
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


def _check_temporal() -> dict[str, str]:
    """Check durable-workflow (Temporal) availability.

    The integration is intentionally optional: the worker runs out-of-process
    (docker-compose `temporal-worker`), and the SDK import is lazy so the app
    never depends on temporalio being installed.
    """
    use_temporal = os.environ.get("USE_TEMPORAL", "").lower() == "true"
    try:
        import temporalio  # noqa: F401

        sdk = True
    except ImportError:
        sdk = False

    if use_temporal and sdk:
        host = os.environ.get("TEMPORAL_HOST", "localhost:7233")
        return {"status": "full", "detail": f"Temporal enabled (worker target {host})"}
    if use_temporal and not sdk:
        return {
            "status": "degraded",
            "detail": "USE_TEMPORAL=true but temporalio package not installed",
        }
    return {"status": "unavailable", "detail": "Temporal disabled (USE_TEMPORAL != true)"}


def _check_rate_limiter_backend(redis_status: dict[str, str]) -> dict[str, str]:
    """Report which rate limiter backend the middleware is using.

    Distributed (Redis) enforcement is active only when Redis itself answers;
    otherwise requests are limited per-process in memory.
    """
    if redis_status["status"] == "full":
        return {
            "status": "full",
            "detail": "Redis-backed sliding window shared across workers",
        }
    return {
        "status": "degraded",
        "detail": "In-memory per-process rate limiting (no reachable Redis)",
    }


@router.get("/system/degradation")
async def degradation_status() -> JSONResponse:
    """Return system degradation status for all optional components.

    Checks Redis, Docker, LLM, embedding, mempalace, and Temporal availability.
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
    temporal_status = _check_temporal()

    features = {
        "redis": redis_status,
        "docker": docker_status,
        "llm": llm_status,
        "embedding": embedding_status,
        "mempalace": mempalace_status,
        "temporal": temporal_status,
        "rate_limiter": _check_rate_limiter_backend(redis_status),
    }

    # Determine overall system status
    statuses = [f["status"] for f in features.values()]
    if all(s == "full" for s in statuses):
        overall = "full"
    elif any(s == "unavailable" for s in statuses):
        overall = "degraded"
    elif any(s == "degraded" for s in statuses):
        # All components are either full or degraded (none unavailable)
        overall = "degraded"
    else:
        overall = "full"

    return JSONResponse(
        status_code=200,
        content={
            "overall_status": overall,
            "features": features,
        },
    )
