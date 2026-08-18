"""Health and Observability - System health monitoring.

Provides component health checks, dependency aggregation, health history,
health-based circuit breaking, metrics collection, and alert thresholds.
"""

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable


class HealthStatus(str, Enum):
    """Health status for a component."""

    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"


@dataclass
class ComponentHealth:
    """Health status of a single component.

    Attributes:
        name: Component identifier.
        status: Current health status.
        last_check: When the last health check was performed.
        latency_ms: Response latency in milliseconds.
        details: Additional health details.
        error: Error message if unhealthy.
    """

    name: str = ""
    status: HealthStatus = HealthStatus.HEALTHY
    last_check: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    latency_ms: float = 0.0
    details: dict[str, Any] = field(default_factory=dict)
    error: str = ""


@dataclass
class HealthHistoryEntry:
    """A point-in-time health record.

    Attributes:
        timestamp: When the check occurred.
        component_name: Which component was checked.
        status: Health status at that time.
        latency_ms: Latency at that time.
    """

    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    component_name: str = ""
    status: HealthStatus = HealthStatus.HEALTHY
    latency_ms: float = 0.0


@dataclass
class AlertThreshold:
    """Alert threshold configuration for a metric.

    Attributes:
        metric_name: Name of the metric.
        warning_threshold: Value that triggers a warning.
        critical_threshold: Value that triggers critical alert.
        comparison: How to compare (gt = greater than, lt = less than).
    """

    metric_name: str = ""
    warning_threshold: float = 0.0
    critical_threshold: float = 0.0
    comparison: str = "gt"  # "gt" or "lt"


@dataclass
class MetricsSnapshot:
    """A snapshot of system metrics.

    Attributes:
        timestamp: When the snapshot was taken.
        latency_ms: Average latency in milliseconds.
        throughput_rps: Requests per second.
        error_rate: Error rate as a fraction (0.0 to 1.0).
        custom_metrics: Additional metrics.
    """

    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    latency_ms: float = 0.0
    throughput_rps: float = 0.0
    error_rate: float = 0.0
    custom_metrics: dict[str, float] = field(default_factory=dict)


class HealthMonitor:
    """System health monitoring with component checks and metrics.

    Provides:
    - Component health registration and checking
    - Dependency health aggregation
    - Health history for trend detection
    - Health-based circuit breaking
    - Metrics collection (latency, throughput, error rate)
    - Configurable alert thresholds
    """

    def __init__(self, max_history: int = 1000) -> None:
        """Initialize the health monitor.

        Args:
            max_history: Maximum number of history entries to retain.
        """
        self._components: dict[str, ComponentHealth] = {}
        self._health_checks: dict[str, Callable[[], ComponentHealth]] = {}
        self._history: list[HealthHistoryEntry] = []
        self._max_history = max_history
        self._alert_thresholds: dict[str, AlertThreshold] = {}
        self._metrics: list[MetricsSnapshot] = []
        self._unhealthy_threshold: int = 2  # Components unhealthy before circuit break

    def register_component(
        self,
        name: str,
        check_fn: Callable[[], ComponentHealth] | None = None,
    ) -> None:
        """Register a component for health monitoring.

        Args:
            name: Component identifier.
            check_fn: Optional function that performs the health check.
                      If None, component must be updated manually.
        """
        self._components[name] = ComponentHealth(name=name)
        if check_fn is not None:
            self._health_checks[name] = check_fn

    def check_component(self, name: str) -> ComponentHealth | None:
        """Check the health of a specific component.

        If a check function is registered, it is called. Otherwise,
        returns the last known state.

        Args:
            name: Component to check.

        Returns:
            ComponentHealth, or None if component not registered.
        """
        if name not in self._components:
            return None

        if name in self._health_checks:
            try:
                health = self._health_checks[name]()
                health.name = name
                health.last_check = datetime.now(timezone.utc)
                self._components[name] = health
            except Exception as e:
                self._components[name] = ComponentHealth(
                    name=name,
                    status=HealthStatus.UNHEALTHY,
                    last_check=datetime.now(timezone.utc),
                    error=str(e),
                )

        # Record to history
        component = self._components[name]
        entry = HealthHistoryEntry(
            component_name=name,
            status=component.status,
            latency_ms=component.latency_ms,
        )
        self._history.append(entry)
        if len(self._history) > self._max_history:
            self._history = self._history[-self._max_history:]

        return component

    def update_component(
        self,
        name: str,
        status: HealthStatus,
        latency_ms: float = 0.0,
        details: dict[str, Any] | None = None,
        error: str = "",
    ) -> ComponentHealth | None:
        """Manually update a component's health status.

        Args:
            name: Component to update.
            status: New health status.
            latency_ms: Current latency.
            details: Additional details.
            error: Error message if unhealthy.

        Returns:
            Updated ComponentHealth, or None if not registered.
        """
        if name not in self._components:
            return None

        self._components[name] = ComponentHealth(
            name=name,
            status=status,
            last_check=datetime.now(timezone.utc),
            latency_ms=latency_ms,
            details=details or {},
            error=error,
        )

        # Record to history
        entry = HealthHistoryEntry(
            component_name=name,
            status=status,
            latency_ms=latency_ms,
        )
        self._history.append(entry)
        if len(self._history) > self._max_history:
            self._history = self._history[-self._max_history:]

        return self._components[name]

    def check_all(self) -> dict[str, ComponentHealth]:
        """Check health of all registered components.

        Returns:
            Dict mapping component names to their ComponentHealth.
        """
        for name in list(self._components.keys()):
            self.check_component(name)
        return dict(self._components)

    def get_health_history(
        self, component_name: str | None = None, limit: int = 100
    ) -> list[HealthHistoryEntry]:
        """Get health history, optionally filtered by component.

        Args:
            component_name: If provided, filter to this component.
            limit: Maximum entries to return.

        Returns:
            List of HealthHistoryEntry objects (most recent first).
        """
        entries = self._history
        if component_name:
            entries = [e for e in entries if e.component_name == component_name]
        return list(reversed(entries[-limit:]))

    def is_system_healthy(self) -> bool:
        """Check if the overall system is healthy.

        Returns True only if no components are unhealthy.

        Returns:
            True if system is healthy or degraded, False if any component is unhealthy.
        """
        for component in self._components.values():
            if component.status == HealthStatus.UNHEALTHY:
                return False
        return True

    def should_circuit_break(self) -> bool:
        """Determine if the system should stop accepting work.

        Returns True if the number of unhealthy components meets or
        exceeds the unhealthy threshold.

        Returns:
            True if system should circuit break.
        """
        unhealthy_count = sum(
            1
            for c in self._components.values()
            if c.status == HealthStatus.UNHEALTHY
        )
        return unhealthy_count >= self._unhealthy_threshold

    def configure_alert_threshold(
        self,
        metric_name: str,
        warning_threshold: float,
        critical_threshold: float,
        comparison: str = "gt",
    ) -> AlertThreshold:
        """Configure an alert threshold for a metric.

        Args:
            metric_name: Name of the metric.
            warning_threshold: Value that triggers a warning.
            critical_threshold: Value that triggers critical alert.
            comparison: "gt" (greater than) or "lt" (less than).

        Returns:
            The configured AlertThreshold.
        """
        threshold = AlertThreshold(
            metric_name=metric_name,
            warning_threshold=warning_threshold,
            critical_threshold=critical_threshold,
            comparison=comparison,
        )
        self._alert_thresholds[metric_name] = threshold
        return threshold

    def get_alert_thresholds(self) -> dict[str, AlertThreshold]:
        """Get all configured alert thresholds.

        Returns:
            Dict mapping metric names to AlertThreshold configs.
        """
        return dict(self._alert_thresholds)

    def record_metrics(
        self,
        latency_ms: float = 0.0,
        throughput_rps: float = 0.0,
        error_rate: float = 0.0,
        custom_metrics: dict[str, float] | None = None,
    ) -> MetricsSnapshot:
        """Record a metrics snapshot.

        Args:
            latency_ms: Average latency in milliseconds.
            throughput_rps: Requests per second.
            error_rate: Error rate as fraction.
            custom_metrics: Additional custom metrics.

        Returns:
            The recorded MetricsSnapshot.
        """
        snapshot = MetricsSnapshot(
            latency_ms=latency_ms,
            throughput_rps=throughput_rps,
            error_rate=error_rate,
            custom_metrics=custom_metrics or {},
        )
        self._metrics.append(snapshot)
        return snapshot

    def get_metrics(self, limit: int = 100) -> list[MetricsSnapshot]:
        """Get recent metrics snapshots.

        Args:
            limit: Maximum snapshots to return.

        Returns:
            List of MetricsSnapshot objects (most recent first).
        """
        return list(reversed(self._metrics[-limit:]))

    def check_alert_thresholds(
        self, metrics: MetricsSnapshot | None = None
    ) -> list[dict[str, Any]]:
        """Check if current metrics exceed alert thresholds.

        Args:
            metrics: Metrics to check. If None, uses latest recorded.

        Returns:
            List of triggered alerts with details.
        """
        if metrics is None:
            if not self._metrics:
                return []
            metrics = self._metrics[-1]

        alerts: list[dict[str, Any]] = []

        metric_values = {
            "latency_ms": metrics.latency_ms,
            "throughput_rps": metrics.throughput_rps,
            "error_rate": metrics.error_rate,
        }
        metric_values.update(metrics.custom_metrics)

        for name, threshold in self._alert_thresholds.items():
            value = metric_values.get(name)
            if value is None:
                continue

            level = None
            if threshold.comparison == "gt":
                if value >= threshold.critical_threshold:
                    level = "critical"
                elif value >= threshold.warning_threshold:
                    level = "warning"
            elif threshold.comparison == "lt":
                if value <= threshold.critical_threshold:
                    level = "critical"
                elif value <= threshold.warning_threshold:
                    level = "warning"

            if level:
                alerts.append({
                    "metric": name,
                    "level": level,
                    "value": value,
                    "threshold": (
                        threshold.critical_threshold
                        if level == "critical"
                        else threshold.warning_threshold
                    ),
                })

        return alerts
