"""Health check and readiness probe endpoints."""

import asyncio
import time
from typing import Any

try:
    import resource
except ImportError:
    resource = None  # type: ignore[assignment]  # Not available on Windows

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from sqlalchemy import text

from nexus import __version__
from nexus.config import settings
from nexus.database import engine
from nexus.temporal.client import is_temporal_enabled

router = APIRouter(tags=["health"])

_start_time: float = time.time()

# A readiness probe must answer quickly. DescribeTaskQueue is a control-plane
# call, so it gets a hard ceiling rather than the client's default.
_POLLER_PROBE_TIMEOUT = 3.0


@router.get("/health/live")
async def liveness() -> dict[str, str]:
    """Liveness probe - lightweight process check for container orchestrators.

    Always returns 200 if the process event loop is active and responding.
    """
    return {"status": "alive"}


@router.get("/health/startup")
async def startup() -> JSONResponse:
    """Startup probe - verifies application has booted and database is initialized.

    Returns 200 when initialized, 503 while bootstrapping.
    """
    db_connected = False
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        db_connected = True
    except Exception:
        db_connected = False

    status_code = 200 if db_connected else 503
    return JSONResponse(
        status_code=status_code,
        content={
            "status": "started" if db_connected else "starting",
            "db": "connected" if db_connected else "disconnected",
        },
    )


def _safe_int(val: Any) -> int | None:
    """Safely extract an integer from a property or callable."""
    if isinstance(val, int):
        return val
    try:
        if callable(val):
            res = val()
            if isinstance(res, int):
                return res
    except Exception:
        pass
    return None


async def _check_db_health() -> dict[str, Any]:
    """Inspect DB connection and connection pool capacity."""
    start = time.perf_counter()
    pool_info: dict[str, Any] = {}
    try:
        pool = getattr(engine, "pool", None)
        if pool is not None and not str(type(pool)).startswith("<class 'unittest.mock."):
            pool_info = {
                "size": _safe_int(getattr(pool, "size", None)) or 0,
                "checked_in": _safe_int(getattr(pool, "checkedin", None)) or 0,
                "checked_out": _safe_int(getattr(pool, "checkedout", None)) or 0,
                "overflow": _safe_int(getattr(pool, "overflow", None)) or 0,
            }
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        latency_ms = round((time.perf_counter() - start) * 1000, 2)
        return {
            "status": "connected",
            "latency_ms": latency_ms,
            "pool": pool_info,
        }
    except Exception as exc:
        latency_ms = round((time.perf_counter() - start) * 1000, 2)
        return {
            "status": "disconnected",
            "error": str(exc),
            "latency_ms": latency_ms,
            "pool": pool_info,
        }


async def _check_redis_health() -> dict[str, Any]:
    """Inspect Redis connectivity and latency."""
    if not settings.redis_url:
        return {"status": "disabled", "detail": "redis_url not configured"}

    start = time.perf_counter()
    try:
        import redis.asyncio as aioredis

        client = aioredis.from_url(
            settings.redis_url,
            socket_connect_timeout=2.0,
            socket_timeout=2.0,
        )
        try:
            pong = await client.ping()
            latency_ms = round((time.perf_counter() - start) * 1000, 2)
            if pong:
                return {"status": "connected", "latency_ms": latency_ms}
            return {"status": "disconnected", "error": "Invalid ping response"}
        finally:
            await client.aclose()
    except Exception as exc:
        latency_ms = round((time.perf_counter() - start) * 1000, 2)
        return {"status": "disconnected", "error": str(exc), "latency_ms": latency_ms}


async def _check_temporal_health() -> dict[str, Any]:
    """Inspect Temporal readiness: the frontend AND a worker on the task queue.

    Frontend connectivity alone is not readiness. With ``USE_TEMPORAL=true`` and
    a reachable server but no worker polling ``nexus-main``, every workflow the
    application starts is accepted and then sits queued forever — the API reports
    success, nothing runs, and nothing says why. That is the failure this check
    exists to make visible.

    ``DescribeTaskQueue`` answers it in one call: a poller count of zero means no
    worker. The call is wrapped in a short timeout because a readiness probe must
    not hang on a slow control-plane RPC, and a timeout is reported as unknown
    rather than as failure — an inconclusive probe is not evidence of a problem.

    **Staleness, measured.** The server keeps a poller registration for a while
    after the worker is gone: with the worker process confirmed dead, this reported
    one poller for ~126 seconds before dropping to zero. So a *zero* count is
    trustworthy — nothing has polled for over two minutes — while a *non-zero*
    count means "a worker polled recently", not "a worker is alive right now".
    That asymmetry is the right way round for catching a misconfigured start, and
    it is why this is a readiness signal rather than a liveness one.
    """
    if not is_temporal_enabled():
        return {"status": "disabled", "detail": "USE_TEMPORAL is false"}

    try:
        from nexus.temporal.client import TASK_QUEUE, _get_client

        client = await _get_client()
        if client is None:
            return {
                "status": "disconnected",
                "error": "Unable to connect to Temporal frontend",
            }
    except Exception as exc:
        return {"status": "disconnected", "error": str(exc)}

    try:
        pollers = await asyncio.wait_for(
            _count_task_queue_pollers(client, TASK_QUEUE), timeout=_POLLER_PROBE_TIMEOUT
        )
    except asyncio.TimeoutError:
        return {
            "status": "connected",
            "task_queue": TASK_QUEUE,
            "workers": "unknown",
            "detail": "Worker probe timed out; worker presence not determined.",
        }
    except Exception as exc:  # noqa: BLE001 - probe failure must not fail readiness
        return {
            "status": "connected",
            "task_queue": TASK_QUEUE,
            "workers": "unknown",
            "detail": f"Worker probe unavailable: {type(exc).__name__}",
        }

    if pollers == 0:
        return {
            "status": "no_workers",
            "task_queue": TASK_QUEUE,
            "workers": 0,
            "error": (
                f"Temporal is enabled and reachable, but no worker is polling "
                f"'{TASK_QUEUE}'. Workflows would be queued and never executed. "
                f"Start it with: python -m nexus.temporal.worker (or "
                f"docker compose -f docker-compose.dev.yml up temporal-worker)"
            ),
        }

    return {"status": "connected", "task_queue": TASK_QUEUE, "workers": pollers}


async def _count_task_queue_pollers(client: Any, task_queue: str) -> int:
    """Return how many workers are polling ``task_queue`` for workflow tasks.

    Counts workflow-task pollers only. An activity-only worker cannot advance a
    workflow, so it would not resolve the condition this is checking for.
    """
    from temporalio.api.enums.v1 import TaskQueueType
    from temporalio.api.taskqueue.v1 import TaskQueue
    from temporalio.api.workflowservice.v1 import DescribeTaskQueueRequest

    response = await client.workflow_service.describe_task_queue(
        DescribeTaskQueueRequest(
            namespace=client.namespace,
            task_queue=TaskQueue(name=task_queue),
            task_queue_type=TaskQueueType.TASK_QUEUE_TYPE_WORKFLOW,
        )
    )
    return len(response.pollers)


@router.get("/health/ready")
async def readiness() -> JSONResponse:
    """Readiness probe - checks database, redis, and temporal connectivity.

    Returns 200 with component status when dependencies are healthy, 503 otherwise.
    """
    db_res = await _check_db_health()
    redis_res = await _check_redis_health()
    temporal_res = await _check_temporal_health()

    db_ready = db_res.get("status") == "connected"
    redis_ready = redis_res.get("status") in ("connected", "disabled")
    # "no_workers" is deliberately NOT ready: Temporal is on and reachable but
    # nothing would execute what the application starts.
    temporal_ready = temporal_res.get("status") in ("connected", "disabled")

    all_ready = db_ready and redis_ready and temporal_ready
    status_code = 200 if all_ready else 503

    return JSONResponse(
        status_code=status_code,
        content={
            "status": "ready" if all_ready else "not_ready",
            "db": "connected" if db_ready else "disconnected",
            "redis": redis_res.get("status", "disconnected"),
            "components": {
                "database": db_res,
                "redis": redis_res,
                "temporal": temporal_res,
            },
        },
    )


@router.get("/health")
async def health_check() -> JSONResponse:
    """Comprehensive health check with uptime, db status, memory, and version.

    Returns 200 with full status details. The db field indicates whether
    the database is currently reachable.
    """
    uptime_seconds = round(time.time() - _start_time, 2)

    db_res = await _check_db_health()
    db_status = db_res.get("status", "disconnected")

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


@router.get("/health/services")
async def background_services_health() -> JSONResponse:
    """Check health of background services (scheduler, orchestrator).

    Returns status of each background task including last tick time
    and whether they appear stalled (>5 minutes since last activity).
    """
    from nexus.runtime.orchestrator import _orchestrator_task
    from nexus.runtime.orchestrator import _running as orchestrator_running
    from nexus.runtime.scheduler import _running as scheduler_running
    from nexus.runtime.scheduler import _scheduler_task

    services = {}

    # Scheduler health
    services["scheduler"] = {
        "running": scheduler_running,
        "task_alive": _scheduler_task is not None and not _scheduler_task.done() if _scheduler_task else False,
        "status": "healthy" if scheduler_running and _scheduler_task and not _scheduler_task.done() else "stopped",
    }

    # Orchestrator health
    services["orchestrator"] = {
        "running": orchestrator_running,
        "task_alive": _orchestrator_task is not None and not _orchestrator_task.done() if _orchestrator_task else False,
        "status": "healthy" if orchestrator_running and _orchestrator_task and not _orchestrator_task.done() else "stopped",
    }

    all_healthy = all(s["status"] == "healthy" for s in services.values())

    return JSONResponse(
        status_code=200 if all_healthy else 503,
        content={
            "status": "healthy" if all_healthy else "degraded",
            "services": services,
        },
    )

