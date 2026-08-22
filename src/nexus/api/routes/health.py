"""Health check and readiness probe endpoints."""

import time

try:
    import resource
except ImportError:
    resource = None  # type: ignore[assignment]  # Not available on Windows

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from sqlalchemy import text

from nexus import __version__
from nexus.database import engine

router = APIRouter(tags=["health"])

_start_time: float = time.time()


@router.get("/health/live")
async def liveness() -> dict[str, str]:
    """Liveness probe - always returns 200 if the process is running."""
    return {"status": "alive"}


@router.get("/health/ready")
async def readiness() -> JSONResponse:
    """Readiness probe - checks database connectivity.

    Returns 200 if the database is reachable, 503 otherwise.
    """
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        return JSONResponse(
            status_code=200,
            content={"status": "ready", "db": "connected"},
        )
    except Exception:
        return JSONResponse(
            status_code=503,
            content={"status": "not_ready", "db": "disconnected"},
        )


@router.get("/health")
async def health_check() -> JSONResponse:
    """Comprehensive health check with uptime, db status, memory, and version.

    Returns 200 with full status details. The db field indicates whether
    the database is currently reachable.
    """
    uptime_seconds = round(time.time() - _start_time, 2)

    # Check database connectivity
    db_status = "connected"
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
    except Exception:
        db_status = "disconnected"

    # Memory usage via resource module (not available on Windows)
    if resource is not None:
        usage = resource.getrusage(resource.RUSAGE_SELF)
        memory_mb = round(usage.ru_maxrss / 1024, 2)  # KB to MB on Linux
    else:
        memory_mb = 0.0

    status = "healthy" if db_status == "connected" else "degraded"

    return JSONResponse(
        status_code=200,
        content={
            "status": status,
            "uptime_seconds": uptime_seconds,
            "db": db_status,
            "memory_mb": memory_mb,
            "version": __version__,
        },
    )
