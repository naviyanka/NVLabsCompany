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

        log_entry: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(
                record.created, tz=timezone.utc
            ).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": message,
            "correlation_id": correlation_id.get(),
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
    """ASGI middleware that propagates X-Request-ID as a correlation ID.

    Reads the X-Request-ID header from the incoming request. If absent,
    generates a new UUID4. Sets the correlation_id context var and adds
    the X-Request-ID header to the response.
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

        # Extract X-Request-ID from headers
        headers = dict(scope.get("headers", []))
        request_id_bytes = headers.get(b"x-request-id")

        if request_id_bytes:
            request_id = request_id_bytes.decode("utf-8", errors="replace")
        else:
            request_id = str(uuid.uuid4())

        # Set the correlation_id context var
        token = correlation_id.set(request_id)

        async def send_wrapper(message: Message) -> None:
            if message["type"] == "http.response.start":
                response_headers = list(message.get("headers", []))
                response_headers.append(
                    (b"x-request-id", request_id.encode("utf-8"))
                )
                message = {**message, "headers": response_headers}
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            correlation_id.reset(token)
