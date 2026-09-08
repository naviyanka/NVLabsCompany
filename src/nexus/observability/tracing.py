"""OpenTelemetry distributed tracing engine for NEXUS.

Provides:
- Distributed tracing with W3C traceparent context propagation across HTTP, Redis, and background tasks
- OpenTelemetry GenAI semantic conventions for LLM calls and tool executions
- Decorators and helpers for zero-overhead span management
- Safe in-memory/console fallback for local development and unit tests
- Auto-instrumentation hooks for FastAPI and HTTPX

Environment variables (standard OTel):
    OTEL_SERVICE_NAME           — defaults to "nexus"
    OTEL_EXPORTER_OTLP_ENDPOINT — OTLP/HTTP collector endpoint.
    OTEL_EXPORTER_TYPE          — "otlp" (default) or "in_memory" (for tests).
    OTEL_TRACES_SAMPLER         — sampler name (e.g. parentbased_traceidratio), read by SDK.
"""

from __future__ import annotations

import contextlib
import functools
import logging
import os
import uuid
from contextlib import contextmanager
from typing import Any, Callable, Generator

logger = logging.getLogger(__name__)

_OTEL_AVAILABLE = False
_INITIALIZED = False
_IN_MEMORY_EXPORTER: Any | None = None

DEFAULT_TRACE_ID = "00000000000000000000000000000000"
DEFAULT_SPAN_ID = "0000000000000000"

try:
    from opentelemetry import context as _otel_context
    from opentelemetry import propagate as _otel_propagate
    from opentelemetry import trace as _otel_trace
    from opentelemetry.trace import SpanContext as _SpanContext
    from opentelemetry.trace import StatusCode as _StatusCode
    from opentelemetry.trace.propagation.tracecontext import (
        TraceContextTextMapPropagator as _TraceContextPropagator,
    )

    _OTEL_AVAILABLE = True
except ImportError:
    pass


class _NoopSpanContext:
    """Fallback span context when tracing is inactive."""

    def __init__(
        self,
        trace_id: int = 0,
        span_id: int = 0,
        is_valid: bool = False,
    ) -> None:
        self.trace_id = trace_id
        self.span_id = span_id
        self.is_valid = is_valid


class _NoopSpan:
    """Minimal span interface that degrades safely with zero overhead."""

    def __init__(self, name: str = "noop") -> None:
        self.name = name
        self._attributes: dict[str, Any] = {}
        self._context = _NoopSpanContext()

    def set_attribute(self, key: str, value: Any) -> None:
        self._attributes[key] = value

    def set_attributes(self, attributes: dict[str, Any]) -> None:
        self._attributes.update(attributes)

    def set_status(self, status: Any, description: str | None = None) -> None:
        pass

    def add_event(self, name: str, attributes: Any = None) -> None:
        pass

    def record_exception(self, exception: BaseException) -> None:
        pass

    def is_recording(self) -> bool:
        return False

    def get_span_context(self) -> Any:
        return self._context

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
        span = _NoopSpan(name)
        if "attributes" in kwargs and isinstance(kwargs["attributes"], dict):
            span.set_attributes(kwargs["attributes"])
        yield span

    def start_span(self, name: str, **kwargs: Any) -> _NoopSpan:
        span = _NoopSpan(name)
        if "attributes" in kwargs and isinstance(kwargs["attributes"], dict):
            span.set_attributes(kwargs["attributes"])
        return span


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


def init_tracing(force_in_memory: bool = False) -> bool:
    """Install a real TracerProvider exporting over OTLP/HTTP or in-memory for testing.

    Args:
        force_in_memory: If True, forces an InMemorySpanExporter for testing.

    Returns:
        True when an active exporting provider is installed.
    """
    global _INITIALIZED, _IN_MEMORY_EXPORTER
    if _INITIALIZED and not force_in_memory:
        return True

    if not _OTEL_AVAILABLE:
        logger.debug("OpenTelemetry packages not available; tracing remains inactive.")
        return False

    endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "")
    exporter_type = os.getenv("OTEL_EXPORTER_TYPE", "otlp").lower()

    if not endpoint and not force_in_memory and exporter_type != "in_memory":
        # Zero-cost fallback in local dev without collector
        return False

    try:
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import (
            BatchSpanProcessor,
            SimpleSpanProcessor,
        )

        service = os.getenv("OTEL_SERVICE_NAME", "nexus")
        resource = Resource.create({
            "service.name": service,
            "service.version": "0.1.0",
            "deployment.environment": os.getenv("NEXUS_ENV", "production"),
        })
        provider = TracerProvider(resource=resource)

        if force_in_memory or exporter_type == "in_memory":
            from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
                InMemorySpanExporter,
            )

            _IN_MEMORY_EXPORTER = InMemorySpanExporter()
            provider.add_span_processor(SimpleSpanProcessor(_IN_MEMORY_EXPORTER))
            logger.info("OpenTelemetry initialized with in-memory exporter for testing.")
        else:
            from opentelemetry.exporter.otlp.proto.http.trace_exporter import (
                OTLPSpanExporter,
            )

            exporter = OTLPSpanExporter(endpoint=f"{endpoint}/v1/traces" if not endpoint.endswith("/v1/traces") else endpoint)
            provider.add_span_processor(BatchSpanProcessor(exporter))
            logger.info("OpenTelemetry tracing enabled for service '%s' via OTLP (%s)", service, endpoint)

        _otel_trace._TRACER_PROVIDER = provider
        if hasattr(_otel_trace, "_TRACER_PROVIDER_SET_ONCE"):
            _otel_trace._TRACER_PROVIDER_SET_ONCE._done = True
        _INITIALIZED = True
        return True
    except Exception as exc:
        logger.warning("Failed to initialize OpenTelemetry TracerProvider: %s", exc)
        return False


def get_in_memory_spans() -> list[Any]:
    """Retrieve captured spans if in-memory tracing is active (useful for tests)."""
    if _IN_MEMORY_EXPORTER is not None:
        return list(_IN_MEMORY_EXPORTER.get_finished_spans())
    return []


def reset_tracing() -> None:
    """Clear captured in-memory spans for isolated test cases."""
    global _IN_MEMORY_EXPORTER
    if _IN_MEMORY_EXPORTER is not None:
        _IN_MEMORY_EXPORTER.clear()


def current_trace_id() -> str | None:
    """Return the active span's trace ID as a 32-hex string, or None if outside a span."""
    if not _OTEL_AVAILABLE:
        return None
    span = _otel_trace.get_current_span()
    ctx = span.get_span_context()
    if not ctx or not ctx.is_valid:
        return None
    return format(ctx.trace_id, "032x")


def current_span_id() -> str | None:
    """Return the active span's span ID as a 16-hex string, or None if outside a span."""
    if not _OTEL_AVAILABLE:
        return None
    span = _otel_trace.get_current_span()
    ctx = span.get_span_context()
    if not ctx or not ctx.is_valid:
        return None
    return format(ctx.span_id, "016x")


def current_span_context() -> tuple[str, str]:
    """Return (trace_id, span_id) formatted strings for log injection and correlation.

    Returns:
        A tuple of (32-hex trace_id, 16-hex span_id). When outside an active span,
        returns DEFAULT_TRACE_ID and DEFAULT_SPAN_ID.
    """
    if not _OTEL_AVAILABLE:
        return DEFAULT_TRACE_ID, DEFAULT_SPAN_ID
    span = _otel_trace.get_current_span()
    ctx = span.get_span_context()
    if not ctx or not ctx.is_valid:
        return DEFAULT_TRACE_ID, DEFAULT_SPAN_ID
    return format(ctx.trace_id, "032x"), format(ctx.span_id, "016x")


# ---------------------------------------------------------------------------
# W3C Context Propagation (traceparent)
# ---------------------------------------------------------------------------


def inject_trace_context(carrier: dict[str, str] | None = None) -> dict[str, str]:
    """Inject active trace context into a carrier dictionary (HTTP headers, Redis payload).

    Uses W3C traceparent standard (00-{trace_id}-{span_id}-{flags}).

    Args:
        carrier: Optional existing dictionary. If None, a new dict is created.

    Returns:
        The carrier dictionary containing injected traceparent headers.
    """
    out = dict(carrier) if carrier is not None else {}
    if _OTEL_AVAILABLE:
        _TraceContextPropagator().inject(out)
    else:
        # Manual fallback if OTel is absent
        tid = current_trace_id()
        sid = current_span_id()
        if tid and sid:
            out["traceparent"] = f"00-{tid}-{sid}-01"
    return out


def extract_trace_context(carrier: dict[str, str]) -> Any:
    """Extract W3C trace context from carrier dictionary headers.

    Args:
        carrier: Dictionary of HTTP headers or metadata.

    Returns:
        An OpenTelemetry Context object containing the parent span context.
    """
    if not _OTEL_AVAILABLE:
        return None
    # Normalize headers to lowercase keys for case-insensitive extraction
    norm_carrier = {k.lower(): v for k, v in carrier.items()}
    return _TraceContextPropagator().extract(norm_carrier)


# ---------------------------------------------------------------------------
# OpenTelemetry GenAI Semantic Conventions
# ---------------------------------------------------------------------------


def start_llm_span(
    model: str,
    provider: str,
    company_id: Any | None = None,
    agent_id: Any | None = None,
    operation: str = "chat",
    prompt: str | None = None,
    tracer_name: str = "nexus.llm",
    parent_context: Any | None = None,
) -> Any:
    """Start an OpenTelemetry span adhering to GenAI Semantic Conventions.

    Conventions:
        gen_ai.system: Provider name (e.g. openai, anthropic, hermes, ollama)
        gen_ai.request.model: The target model name
        gen_ai.operation.name: Operation type (chat, completion)
        nexus.company_id: Multi-tenant company context
        nexus.agent_id: Executing agent context

    Args:
        model: Target model name (e.g. 'gpt-4o', 'hermes3:8b').
        provider: Provider identifier (e.g. 'openai', 'anthropic', 'hermes').
        company_id: Optional company UUID.
        agent_id: Optional agent UUID.
        operation: 'chat', 'completion', or 'embeddings'.
        prompt: Optional prompt text (sanitized/truncated).
        tracer_name: Instrumentation scope name.
        parent_context: Optional parent OpenTelemetry context.

    Returns:
        The started span (use as context manager or call .end() manually).
    """
    tracer = get_tracer(tracer_name)
    span_name = f"gen_ai.{operation} {model}"

    attributes: dict[str, Any] = {
        "gen_ai.system": provider,
        "gen_ai.request.model": model,
        "gen_ai.operation.name": operation,
    }
    if company_id:
        attributes["nexus.company_id"] = str(company_id)
    if agent_id:
        attributes["nexus.agent_id"] = str(agent_id)
    if prompt:
        attributes["gen_ai.prompt.length"] = len(prompt)

    return tracer.start_as_current_span(
        span_name,
        attributes=attributes,
        context=parent_context,
    )


def record_llm_usage(
    span: Any,
    input_tokens: int = 0,
    output_tokens: int = 0,
    cost_cents: float | int = 0,
    finish_reason: str | None = None,
    model: str | None = None,
) -> None:
    """Record token counts, cost, and finish reason on an active GenAI span.

    Args:
        span: The active GenAI span.
        input_tokens: Number of prompt/input tokens.
        output_tokens: Number of completion/output tokens.
        cost_cents: Estimated cost in cents.
        finish_reason: Termination reason (e.g. 'stop', 'tool_calls', 'length').
        model: Actual model returned in provider response (if different).
    """
    if span is None:
        return

    span.set_attribute("gen_ai.usage.input_tokens", input_tokens)
    span.set_attribute("gen_ai.usage.output_tokens", output_tokens)
    span.set_attribute("gen_ai.usage.total_tokens", input_tokens + output_tokens)
    span.set_attribute("gen_ai.usage.cost_cents", float(cost_cents))

    if finish_reason:
        span.set_attribute("gen_ai.response.finish_reasons", [finish_reason])
    if model:
        span.set_attribute("gen_ai.response.model", model)


def start_tool_span(
    tool_name: str,
    agent_id: Any | None = None,
    task_id: Any | None = None,
    tracer_name: str = "nexus.tool",
) -> Any:
    """Start an OpenTelemetry span for tool execution.

    Args:
        tool_name: Name of the executed tool.
        agent_id: Agent invoking the tool.
        task_id: Active task UUID.
        tracer_name: Instrumentation scope name.

    Returns:
        The started tool span.
    """
    tracer = get_tracer(tracer_name)
    span_name = f"tool.execute {tool_name}"

    attributes: dict[str, Any] = {
        "gen_ai.tool.name": tool_name,
        "nexus.tool_name": tool_name,
    }
    if agent_id:
        attributes["nexus.agent_id"] = str(agent_id)
    if task_id:
        attributes["nexus.task_id"] = str(task_id)

    return tracer.start_as_current_span(span_name, attributes=attributes)


# ---------------------------------------------------------------------------
# General Function Tracing Decorator
# ---------------------------------------------------------------------------


def trace_span(
    tracer_name: str,
    span_name: str,
    attributes: dict[str, Any] | None = None,
) -> Callable[..., Any]:
    """Decorator that wraps sync or async functions in an OpenTelemetry trace span.

    Usage:
        @trace_span("nexus.orchestrator", "reconcile_recovery", {"tier": "system"})
        async def reconcile_recovery(db):
            ...
    """

    def decorator(fn: Callable[..., Any]) -> Callable[..., Any]:
        import inspect

        attrs = attributes or {}

        if inspect.iscoroutinefunction(fn):

            @functools.wraps(fn)
            async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
                tracer = get_tracer(tracer_name)
                with tracer.start_as_current_span(span_name, attributes=attrs) as span:
                    try:
                        return await fn(*args, **kwargs)
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
                with tracer.start_as_current_span(span_name, attributes=attrs) as span:
                    try:
                        return fn(*args, **kwargs)
                    except Exception as exc:
                        span.record_exception(exc)
                        if _OTEL_AVAILABLE:
                            span.set_status(_StatusCode.ERROR, str(exc))
                        raise

            return sync_wrapper

    return decorator


def instrument_app(app: Any) -> None:
    """Auto-instrument FastAPI app and HTTPX clients when available."""
    if not _INITIALIZED:
        return
    try:
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
        from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor

        FastAPIInstrumentor.instrument_app(app, excluded_urls="/metrics,/health")
        HTTPXClientInstrumentor().instrument()
    except ImportError:
        logger.warning(
            "OTel instrumentation packages missing; spans will only cover "
            "manually traced code. Install nexus[otel]."
        )

