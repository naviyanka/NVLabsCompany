"""Optional OpenTelemetry tracing — no-op fallback when SDK is absent.

Instruments key NEXUS subsystems (orchestrator, scheduler, node execution,
evolution, channels) with trace spans. When `opentelemetry-api` is installed
and an exporter is configured, spans are exported normally. When it's missing,
all calls become zero-cost no-ops.

Environment variables (standard OTel):
    OTEL_SERVICE_NAME          — defaults to "nexus"
    OTEL_EXPORTER_OTLP_ENDPOINT — gRPC endpoint for the collector
    OTEL_TRACES_SAMPLER        — sampler name (e.g. parentbased_traceidratio)
"""

from __future__ import annotations

import contextlib
import logging
from contextlib import contextmanager
from typing import Any, Generator

logger = logging.getLogger(__name__)

_OTEL_AVAILABLE = False

try:
    from opentelemetry import trace as _otel_trace
    from opentelemetry.trace import StatusCode as _StatusCode

    _OTEL_AVAILABLE = True
except ImportError:
    pass


class _NoopSpan:
    """Minimal span interface that does nothing."""

    def set_attribute(self, key: str, value: Any) -> None:
        pass

    def set_status(self, status: Any, description: str | None = None) -> None:
        pass

    def record_exception(self, exception: BaseException) -> None:
        pass

    def end(self) -> None:
        pass

    def __enter__(self) -> "_NoopSpan":
        return self

    def __exit__(self, *args: Any) -> None:
        pass


class _NoopTracer:
    """Tracer that always returns no-op spans."""

    @contextmanager
    def start_as_current_span(
        self, name: str, **kwargs: Any
    ) -> Generator[_NoopSpan, None, None]:
        yield _NoopSpan()

    def start_span(self, name: str, **kwargs: Any) -> _NoopSpan:
        return _NoopSpan()


_noop_tracer = _NoopTracer()


def get_tracer(name: str = "nexus") -> Any:
    """Return an OTel tracer if available, otherwise a no-op tracer.

    Args:
        name: Instrumentation scope name (e.g. "nexus.orchestrator").

    Returns:
        A tracer object with .start_as_current_span() support.
    """
    if _OTEL_AVAILABLE:
        return _otel_trace.get_tracer(name)
    return _noop_tracer


def trace_span(tracer_name: str, span_name: str):
    """Decorator that wraps an async function in a trace span.

    Usage:
        @trace_span("nexus.nodes", "execute_node")
        async def execute_node(...):
            ...
    """

    def decorator(fn):
        import asyncio
        import functools

        if asyncio.iscoroutinefunction(fn):

            @functools.wraps(fn)
            async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
                tracer = get_tracer(tracer_name)
                with tracer.start_as_current_span(span_name) as span:
                    try:
                        result = await fn(*args, **kwargs)
                        return result
                    except Exception as exc:
                        span.record_exception(exc)
                        if _OTEL_AVAILABLE:
                            span.set_status(_StatusCode.ERROR, str(exc))
                        raise

            return async_wrapper
        else:

            @functools.wraps(fn)
            def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
                tracer = get_tracer(tracer_name)
                with tracer.start_as_current_span(span_name) as span:
                    try:
                        result = fn(*args, **kwargs)
                        return result
                    except Exception as exc:
                        span.record_exception(exc)
                        if _OTEL_AVAILABLE:
                            span.set_status(_StatusCode.ERROR, str(exc))
                        raise

            return sync_wrapper

    return decorator
