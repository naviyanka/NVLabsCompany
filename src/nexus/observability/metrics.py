"""Prometheus metrics registry and export engine for NEXUS.

Provides:
- Standardized Prometheus metrics across LLM usage, cost, HTTP requests, circuit breakers, and task execution.
- High-level helper functions for metric updates.
- FastAPI /metrics router exporting Prometheus text exposition format.
"""

from __future__ import annotations

import logging
import time
from typing import Any

from fastapi import APIRouter, Response

logger = logging.getLogger(__name__)

# Default latency histogram buckets (in seconds)
DEFAULT_LATENCY_BUCKETS = (
    0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0
)
LLM_LATENCY_BUCKETS = (
    0.1, 0.5, 1.0, 2.0, 5.0, 10.0, 20.0, 30.0, 60.0, 120.0
)
TASK_DURATION_BUCKETS = (
    0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0, 120.0, 300.0
)

try:
    from prometheus_client import (
        CONTENT_TYPE_LATEST,
        CollectorRegistry,
        Counter,
        Gauge,
        Histogram,
        REGISTRY,
        generate_latest,
    )
    _PROMETHEUS_AVAILABLE = True
except ImportError:
    _PROMETHEUS_AVAILABLE = False
    CONTENT_TYPE_LATEST = "text/plain; version=0.0.4; charset=utf-8"


if _PROMETHEUS_AVAILABLE:
    # ---------------------------------------------------------------------------
    # Counters
    # ---------------------------------------------------------------------------
    nexus_llm_tokens_total = Counter(
        "nexus_llm_tokens_total",
        "Total LLM tokens consumed across prompts and completions",
        ["company_id", "agent_id", "model", "token_type"],
    )

    nexus_llm_cost_cents_total = Counter(
        "nexus_llm_cost_cents_total",
        "Total LLM monetary spend in cents",
        ["company_id", "agent_id", "provider"],
    )

    nexus_circuit_breaker_trips_total = Counter(
        "nexus_circuit_breaker_trips_total",
        "Total number of circuit breaker trip incidents",
        ["service"],
    )

    nexus_budget_exhausted_total = Counter(
        "nexus_budget_exhausted_total",
        "Total budget exhaustion occurrences by scope",
        ["company_id", "scope"],
    )

    nexus_checkpoint_saves_total = Counter(
        "nexus_checkpoint_saves_total",
        "Total execution checkpoints saved",
        ["status"],
    )

    nexus_checkpoint_recoveries_total = Counter(
        "nexus_checkpoint_recoveries_total",
        "Total task recoveries initiated from checkpoints",
        ["status"],
    )

    # ---------------------------------------------------------------------------
    # Histograms
    # ---------------------------------------------------------------------------
    nexus_http_request_duration_seconds = Histogram(
        "nexus_http_request_duration_seconds",
        "HTTP request duration in seconds",
        ["method", "endpoint", "status_code"],
        buckets=DEFAULT_LATENCY_BUCKETS,
    )

    nexus_llm_request_duration_seconds = Histogram(
        "nexus_llm_request_duration_seconds",
        "LLM inference request round-trip latency in seconds",
        ["provider", "model"],
        buckets=LLM_LATENCY_BUCKETS,
    )

    nexus_task_execution_duration_seconds = Histogram(
        "nexus_task_execution_duration_seconds",
        "Task execution lifecycle duration in seconds",
        ["agent_id", "status"],
        buckets=TASK_DURATION_BUCKETS,
    )

    # ---------------------------------------------------------------------------
    # Gauges
    # ---------------------------------------------------------------------------
    nexus_active_reservations_cents = Gauge(
        "nexus_active_reservations_cents",
        "Total value of active budget reservations in cents",
        ["company_id"],
    )

    nexus_running_tasks_count = Gauge(
        "nexus_running_tasks_count",
        "Current number of tasks by execution status",
        ["status"],
    )

    nexus_orchestrator_tick_last_timestamp_seconds = Gauge(
        "nexus_orchestrator_tick_last_timestamp_seconds",
        "Timestamp in unix epoch seconds of the last orchestrator tick",
    )
else:
    # No-op placeholders if prometheus_client is absent
    nexus_llm_tokens_total = None  # type: ignore
    nexus_llm_cost_cents_total = None  # type: ignore
    nexus_circuit_breaker_trips_total = None  # type: ignore
    nexus_budget_exhausted_total = None  # type: ignore
    nexus_checkpoint_saves_total = None  # type: ignore
    nexus_checkpoint_recoveries_total = None  # type: ignore
    nexus_http_request_duration_seconds = None  # type: ignore
    nexus_llm_request_duration_seconds = None  # type: ignore
    nexus_task_execution_duration_seconds = None  # type: ignore
    nexus_active_reservations_cents = None  # type: ignore
    nexus_running_tasks_count = None  # type: ignore
    nexus_orchestrator_tick_last_timestamp_seconds = None  # type: ignore


# ---------------------------------------------------------------------------
# Recording Helper Functions
# ---------------------------------------------------------------------------


def record_llm_metrics(
    company_id: Any | None,
    agent_id: Any | None,
    provider: str,
    model: str,
    input_tokens: int,
    output_tokens: int,
    cost_cents: float | int,
    duration_seconds: float | None = None,
) -> None:
    """Record LLM token consumption, cost, and inference latency.

    Args:
        company_id: Company UUID or identifier.
        agent_id: Agent UUID or identifier.
        provider: Provider name (e.g. openai, anthropic, hermes).
        model: Model name (e.g. gpt-4o, hermes3:8b).
        input_tokens: Number of prompt/input tokens.
        output_tokens: Number of completion/output tokens.
        cost_cents: Cost of the call in cents.
        duration_seconds: Optional latency in seconds.
    """
    if not _PROMETHEUS_AVAILABLE:
        return

    cid = str(company_id) if company_id else "system"
    aid = str(agent_id) if agent_id else "unknown"
    prov = str(provider or "unknown").lower()
    mod = str(model or "unknown").lower()

    if input_tokens > 0:
        nexus_llm_tokens_total.labels(
            company_id=cid, agent_id=aid, model=mod, token_type="input"
        ).inc(input_tokens)

    if output_tokens > 0:
        nexus_llm_tokens_total.labels(
            company_id=cid, agent_id=aid, model=mod, token_type="output"
        ).inc(output_tokens)

    total_tokens = input_tokens + output_tokens
    if total_tokens > 0:
        nexus_llm_tokens_total.labels(
            company_id=cid, agent_id=aid, model=mod, token_type="total"
        ).inc(total_tokens)

    if cost_cents > 0:
        nexus_llm_cost_cents_total.labels(
            company_id=cid, agent_id=aid, provider=prov
        ).inc(float(cost_cents))

    if duration_seconds is not None and duration_seconds >= 0:
        nexus_llm_request_duration_seconds.labels(
            provider=prov, model=mod
        ).observe(duration_seconds)


def record_task_metrics(
    agent_id: Any | None,
    status: str,
    duration_seconds: float | None = None,
) -> None:
    """Record task completion status and duration.

    Args:
        agent_id: Agent UUID or identifier.
        status: Task status (e.g. 'completed', 'failed', 'timeout').
        duration_seconds: Optional runtime duration in seconds.
    """
    if not _PROMETHEUS_AVAILABLE:
        return

    aid = str(agent_id) if agent_id else "unknown"
    stat = str(status or "unknown").lower()

    if duration_seconds is not None and duration_seconds >= 0:
        nexus_task_execution_duration_seconds.labels(
            agent_id=aid, status=stat
        ).observe(duration_seconds)


def record_circuit_breaker_trip(service: str) -> None:
    """Increment circuit breaker trip counter.

    Args:
        service: Name of the tripped service/provider.
    """
    if not _PROMETHEUS_AVAILABLE:
        return
    nexus_circuit_breaker_trips_total.labels(service=str(service).lower()).inc()


def record_budget_exhausted(company_id: Any | None, scope: str = "monthly") -> None:
    """Increment budget exhaustion incident counter.

    Args:
        company_id: Company UUID.
        scope: Exhaustion scope (e.g. 'monthly', 'agent', 'task').
    """
    if not _PROMETHEUS_AVAILABLE:
        return
    cid = str(company_id) if company_id else "system"
    nexus_budget_exhausted_total.labels(company_id=cid, scope=scope).inc()


def record_checkpoint_save(status: str = "active") -> None:
    """Increment checkpoint save counter."""
    if not _PROMETHEUS_AVAILABLE:
        return
    nexus_checkpoint_saves_total.labels(status=status).inc()


def record_checkpoint_recovery(status: str = "success") -> None:
    """Increment checkpoint recovery counter."""
    if not _PROMETHEUS_AVAILABLE:
        return
    nexus_checkpoint_recoveries_total.labels(status=status).inc()


def record_http_request(
    method: str,
    endpoint: str,
    status_code: int | str,
    duration_seconds: float,
) -> None:
    """Record HTTP request latency and status."""
    if not _PROMETHEUS_AVAILABLE:
        return
    nexus_http_request_duration_seconds.labels(
        method=method.upper(),
        endpoint=endpoint,
        status_code=str(status_code),
    ).observe(duration_seconds)


def set_active_reservations(company_id: Any | None, cents: float | int) -> None:
    """Update active reservations gauge."""
    if not _PROMETHEUS_AVAILABLE:
        return
    cid = str(company_id) if company_id else "system"
    nexus_active_reservations_cents.labels(company_id=cid).set(float(cents))


def set_running_tasks(status: str, count: int) -> None:
    """Update running tasks gauge for a specific status."""
    if not _PROMETHEUS_AVAILABLE:
        return
    nexus_running_tasks_count.labels(status=status.lower()).set(float(count))


def record_orchestrator_tick() -> None:
    """Record current timestamp on orchestrator tick gauge."""
    if not _PROMETHEUS_AVAILABLE:
        return
    nexus_orchestrator_tick_last_timestamp_seconds.set(time.time())


def generate_metrics_response() -> tuple[bytes, str]:
    """Generate Prometheus exposition text format.

    Returns:
        A tuple of (body_bytes, content_type_header).
    """
    if _PROMETHEUS_AVAILABLE:
        return generate_latest(REGISTRY), CONTENT_TYPE_LATEST
    # Fallback to telemetry.py format if prometheus_client not available
    from nexus.telemetry import render_metrics
    return render_metrics().encode("utf-8"), CONTENT_TYPE_LATEST


# ---------------------------------------------------------------------------
# FastAPI Router
# ---------------------------------------------------------------------------

metrics_router = APIRouter(tags=["observability"])


@metrics_router.get(
    "/metrics",
    response_class=Response,
    summary="Prometheus Metrics Endpoint",
    description="Exposes application and GenAI metrics in Prometheus text exposition format.",
)
async def get_metrics() -> Response:
    """Return all NEXUS metrics in Prometheus text format."""
    body, content_type = generate_metrics_response()
    return Response(
        content=body,
        media_type=content_type,
    )
