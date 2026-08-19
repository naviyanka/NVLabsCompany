"""In-process metrics and telemetry for NEXUS.

Provides lightweight Prometheus-compatible metrics without external dependencies.

Classes:
- Counter: monotonically increasing counter with labels
- Histogram: distribution tracker with configurable buckets
- MetricsMiddleware: ASGI middleware for HTTP request tracking

The /metrics endpoint renders all registered metrics in Prometheus text
exposition format.
"""

import time
from collections import defaultdict
from threading import Lock
from typing import Any

from fastapi import APIRouter, Response
from starlette.types import ASGIApp, Message, Receive, Scope, Send

# Default histogram buckets (in seconds)
DEFAULT_BUCKETS: tuple[float, ...] = (
    0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0
)


class Counter:
    """A monotonically increasing counter metric.

    Supports optional labels for multi-dimensional tracking.

    Example:
        counter = Counter("http_requests_total", "Total HTTP requests")
        counter.inc(labels={"method": "GET", "status": "200"})
    """

    def __init__(self, name: str, help_text: str = "") -> None:
        """Initialize the counter.

        Args:
            name: Metric name (Prometheus-compatible).
            help_text: Human-readable description.
        """
        self.name = name
        self.help_text = help_text
        self._values: dict[tuple[tuple[str, str], ...], float] = defaultdict(float)
        self._lock = Lock()

    def inc(self, amount: float = 1.0, labels: dict[str, str] | None = None) -> None:
        """Increment the counter.

        Args:
            amount: Amount to increment by (must be positive).
            labels: Optional label dict for this observation.
        """
        key = tuple(sorted((labels or {}).items()))
        with self._lock:
            self._values[key] += amount

    @property
    def value(self) -> float:
        """Get the total counter value (sum of all label combinations)."""
        with self._lock:
            return sum(self._values.values())

    def get(self, labels: dict[str, str] | None = None) -> float:
        """Get the counter value for specific labels.

        Args:
            labels: Label dict to look up.

        Returns:
            The current counter value for those labels.
        """
        key = tuple(sorted((labels or {}).items()))
        with self._lock:
            return self._values.get(key, 0.0)

    def collect(self) -> list[dict[str, Any]]:
        """Collect all metric samples for rendering.

        Returns:
            List of dicts with 'labels' and 'value' keys.
        """
        with self._lock:
            return [
                {"labels": dict(key), "value": val}
                for key, val in self._values.items()
            ]


class Histogram:
    """A distribution metric with configurable buckets.

    Tracks count, sum, and per-bucket counts for observed values.

    Example:
        hist = Histogram("http_request_duration_seconds", "Request duration")
        hist.observe(0.123)
    """

    def __init__(
        self,
        name: str,
        help_text: str = "",
        buckets: tuple[float, ...] = DEFAULT_BUCKETS,
    ) -> None:
        """Initialize the histogram.

        Args:
            name: Metric name (Prometheus-compatible).
            help_text: Human-readable description.
            buckets: Upper bounds for histogram buckets.
        """
        self.name = name
        self.help_text = help_text
        self.buckets = buckets
        self._counts: dict[tuple[tuple[str, str], ...], list[int]] = {}
        self._sums: dict[tuple[tuple[str, str], ...], float] = defaultdict(float)
        self._totals: dict[tuple[tuple[str, str], ...], int] = defaultdict(int)
        self._lock = Lock()

    def observe(
        self, value: float, labels: dict[str, str] | None = None
    ) -> None:
        """Record an observation.

        Args:
            value: The observed value.
            labels: Optional label dict for this observation.
        """
        key = tuple(sorted((labels or {}).items()))
        with self._lock:
            if key not in self._counts:
                self._counts[key] = [0] * len(self.buckets)
            for i, bound in enumerate(self.buckets):
                if value <= bound:
                    self._counts[key][i] += 1
                    break
            self._sums[key] += value
            self._totals[key] += 1

    @property
    def count(self) -> int:
        """Get total observation count across all labels."""
        with self._lock:
            return sum(self._totals.values())

    @property
    def sum(self) -> float:
        """Get total sum of observations across all labels."""
        with self._lock:
            return sum(self._sums.values())

    def get_buckets(
        self, labels: dict[str, str] | None = None
    ) -> list[tuple[float, int]]:
        """Get cumulative bucket counts for specific labels.

        Args:
            labels: Label dict to look up.

        Returns:
            List of (upper_bound, cumulative_count) tuples.
        """
        key = tuple(sorted((labels or {}).items()))
        with self._lock:
            counts = self._counts.get(key, [0] * len(self.buckets))
            cumulative = 0
            result = []
            for i, bound in enumerate(self.buckets):
                cumulative += counts[i]
                result.append((bound, cumulative))
            return result

    def collect(self) -> list[dict[str, Any]]:
        """Collect all metric samples for rendering.

        Returns:
            List of dicts with labels, bucket counts, sum, and count.
        """
        with self._lock:
            results = []
            for key in self._totals:
                cumulative = 0
                bucket_values = []
                counts = self._counts.get(key, [0] * len(self.buckets))
                for i, bound in enumerate(self.buckets):
                    cumulative += counts[i]
                    bucket_values.append((bound, cumulative))
                results.append({
                    "labels": dict(key),
                    "buckets": bucket_values,
                    "count": self._totals[key],
                    "sum": self._sums[key],
                })
            return results


class _MetricsRegistry:
    """Global registry for all application metrics."""

    def __init__(self) -> None:
        self._metrics: dict[str, Counter | Histogram] = {}
        self._lock = Lock()

    def register(self, metric: Counter | Histogram) -> Counter | Histogram:
        """Register a metric in the global registry.

        Args:
            metric: The metric instance to register.

        Returns:
            The registered metric instance.
        """
        with self._lock:
            self._metrics[metric.name] = metric
        return metric

    def get(self, name: str) -> Counter | Histogram | None:
        """Get a metric by name.

        Args:
            name: The metric name.

        Returns:
            The metric instance, or None if not found.
        """
        return self._metrics.get(name)

    def all_metrics(self) -> dict[str, Counter | Histogram]:
        """Get all registered metrics.

        Returns:
            Dict mapping metric names to instances.
        """
        with self._lock:
            return dict(self._metrics)

    def reset(self) -> None:
        """Reset all metrics (for testing)."""
        with self._lock:
            self._metrics.clear()


# Global metrics registry
registry = _MetricsRegistry()

# Default application metrics
http_requests_total = registry.register(
    Counter("http_requests_total", "Total number of HTTP requests")
)
http_request_duration_seconds = registry.register(
    Histogram(
        "http_request_duration_seconds",
        "HTTP request duration in seconds",
    )
)
http_requests_in_flight = registry.register(
    Counter("http_requests_in_flight", "Number of HTTP requests currently in flight")
)


def _format_labels(labels: dict[str, str]) -> str:
    """Format labels as a Prometheus label string.

    Args:
        labels: Dict of label key-value pairs.

    Returns:
        Formatted label string like {method="GET",status="200"}.
    """
    if not labels:
        return ""
    pairs = ",".join(f'{k}="{v}"' for k, v in sorted(labels.items()))
    return "{" + pairs + "}"


def render_metrics() -> str:
    """Render all registered metrics in Prometheus text exposition format.

    Returns:
        String in Prometheus text format with HELP, TYPE, and metric lines.
    """
    lines: list[str] = []
    metrics = registry.all_metrics()

    for name, metric in sorted(metrics.items()):
        if isinstance(metric, Counter):
            lines.append(f"# HELP {name} {metric.help_text}")
            lines.append(f"# TYPE {name} counter")
            for sample in metric.collect():
                label_str = _format_labels(sample["labels"])
                lines.append(f"{name}{label_str} {sample['value']}")
        elif isinstance(metric, Histogram):
            lines.append(f"# HELP {name} {metric.help_text}")
            lines.append(f"# TYPE {name} histogram")
            for sample in metric.collect():
                label_str = _format_labels(sample["labels"])
                for bound, count in sample["buckets"]:
                    bucket_labels = dict(sample["labels"])
                    bucket_labels["le"] = str(bound)
                    lines.append(
                        f"{name}_bucket{_format_labels(bucket_labels)} {count}"
                    )
                # +Inf bucket
                inf_labels = dict(sample["labels"])
                inf_labels["le"] = "+Inf"
                lines.append(
                    f"{name}_bucket{_format_labels(inf_labels)}"
                    f" {sample['count']}"
                )
                lines.append(f"{name}_sum{label_str} {sample['sum']}")
                lines.append(f"{name}_count{label_str} {sample['count']}")

    return "\n".join(lines) + "\n"


class MetricsMiddleware:
    """ASGI middleware that tracks HTTP request metrics.

    Records:
    - http_requests_total: counter by method, path, status
    - http_request_duration_seconds: histogram of response times
    - http_requests_in_flight: gauge-like counter (inc on start, dec on end)
    """

    def __init__(self, app: ASGIApp) -> None:
        """Initialize the middleware.

        Args:
            app: The next ASGI application in the chain.
        """
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """ASGI entry point."""
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        method = scope.get("method", "UNKNOWN")
        path = scope.get("path", "/")
        start_time = time.time()

        # Track in-flight requests
        http_requests_in_flight.inc(labels={"state": "active"})
        status_code = "500"  # Default if we never get a response

        async def send_wrapper(message: Message) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = str(message.get("status", 500))
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            duration = time.time() - start_time

            # Record metrics
            labels = {"method": method, "path": path, "status": status_code}
            http_requests_total.inc(labels=labels)
            http_request_duration_seconds.observe(duration, labels=labels)

            # Decrement in-flight
            http_requests_in_flight.inc(
                amount=-1.0, labels={"state": "active"}
            )


# FastAPI router for the /metrics endpoint
metrics_router = APIRouter(tags=["metrics"])


@metrics_router.get(
    "/metrics",
    response_class=Response,
    summary="Prometheus metrics endpoint",
)
async def get_metrics() -> Response:
    """Return all application metrics in Prometheus text exposition format."""
    content = render_metrics()
    return Response(
        content=content,
        media_type="text/plain; version=0.0.4; charset=utf-8",
    )
