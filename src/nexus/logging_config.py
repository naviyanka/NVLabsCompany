"""Structured JSON logging with correlation IDs for NEXUS.

Provides:
- JSONFormatter: logging.Formatter subclass that outputs JSON lines
- correlation_id: ContextVar for request-scoped correlation IDs
- configure_logging(): sets up root logger with JSON formatter
- get_correlation_id(): retrieves the current correlation ID
- RequestIDMiddleware: ASGI middleware that propagates X-Request-ID
"""

import json
import logging
import uuid
from contextvars import ContextVar
from datetime import datetime, timezone
from typing import Any

from starlette.types import ASGIApp, Message, Receive, Scope, Send

# ContextVar for request-scoped correlation IDs
correlation_id: ContextVar[str | None] = ContextVar("correlation_id", default=None)


def get_correlation_id() -> str | None:
    """Retrieve the current correlation ID from context.

    Returns:
        The correlation ID string, or None if not set.
    """
    return correlation_id.get()


class JSONFormatter(logging.Formatter):
    """Logging formatter that outputs each record as a single JSON line.

    Fields emitted: timestamp, level, logger, message, correlation_id.
    Extra fields from the log record are included when present.
    """

    def format(self, record: logging.LogRecord) -> str:
        """Format the log record as a JSON string.

        Args:
            record: The log record to format.

        Returns:
            A single-line JSON string representing the log event.
        """
        # Ensure record.message is populated
        message = record.getMessage()

        # Retrieve active OpenTelemetry trace and span IDs (or standard zeroes when inactive)
        from nexus.observability.tracing import current_span_context

        trace_id, span_id = current_span_context()

        log_entry: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(
                record.created, tz=timezone.utc
            ).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": message,
            "correlation_id": correlation_id.get(),
            "trace_id": trace_id,
            "span_id": span_id,
        }

        # Include exception info if present
        if record.exc_info and record.exc_info[0] is not None:
            log_entry["exception"] = self.formatException(record.exc_info)

        return json.dumps(log_entry, default=str)


def configure_logging(level: str = "INFO") -> None:
    """Configure the root logger with JSON structured output.

    Sets up a StreamHandler with the JSONFormatter on the root logger.
    Removes existing handlers to avoid duplicate output.

    Args:
        level: The logging level string (e.g., 'DEBUG', 'INFO', 'WARNING').
    """
    root_logger = logging.getLogger()
    root_logger.setLevel(getattr(logging, level.upper(), logging.INFO))

    # Remove existing handlers to avoid duplicates
    root_logger.handlers.clear()

    handler = logging.StreamHandler()
    handler.setFormatter(JSONFormatter())
    root_logger.addHandler(handler)


class RequestIDMiddleware:
    """ASGI middleware that propagates X-Request-ID and W3C traceparent headers.

    Extracts or generates X-Request-ID, extracts W3C trace context, sets
    the correlation_id context var, records HTTP latency metrics, and attaches
    correlation headers (X-Request-ID, X-Trace-ID, traceparent) to the response.
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

        import time
        from nexus.observability.metrics import record_http_request
        from nexus.observability.tracing import (
            current_span_id,
            current_trace_id,
            extract_trace_context,
            get_tracer,
        )

        headers_raw = dict(scope.get("headers", []))
        headers_str = {
            k.decode("latin1").lower(): v.decode("latin1")
            for k, v in headers_raw.items()
        }

        # Extract or generate X-Request-ID
        request_id = headers_str.get("x-request-id") or str(uuid.uuid4())

        # Set correlation ID
        token = correlation_id.set(request_id)
        start_time = time.time()
        status_code = 500

        parent_ctx = extract_trace_context(headers_str)
        method = scope.get("method", "GET")
        path = scope.get("path", "/")

        tracer = get_tracer("nexus.http")
        with tracer.start_as_current_span(
            f"HTTP {method} {path}",
            context=parent_ctx,
            attributes={
                "http.method": method,
                "http.target": path,
                "http.request_id": request_id,
            },
        ) as span:

            async def send_wrapper(message: Message) -> None:
                nonlocal status_code
                if message["type"] == "http.response.start":
                    status_code = message.get("status", 500)
                    response_headers = list(message.get("headers", []))
                    response_headers.append(
                        (b"x-request-id", request_id.encode("utf-8"))
                    )

                    tid = current_trace_id()
                    sid = current_span_id()
                    if tid:
                        response_headers.append(
                            (b"x-trace-id", tid.encode("utf-8"))
                        )
                        if sid:
                            response_headers.append(
                                (b"traceparent", f"00-{tid}-{sid}-01".encode("utf-8"))
                            )

                    message = {**message, "headers": response_headers}
                await send(message)

            try:
                await self.app(scope, receive, send_wrapper)
            finally:
                duration = time.time() - start_time
                correlation_id.reset(token)
                record_http_request(method, path, status_code, duration)
                if span is not None:
                    span.set_attribute("http.status_code", status_code)

