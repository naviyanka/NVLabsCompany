"""Tests for the optional OpenTelemetry tracing layer.

Runs with or without the OTel SDK installed: the point is that tracing is
inert unless it is both installed and configured, and that the wrapper never
raises into the code it instruments.
"""

import json
import logging

from nexus.logging_config import JSONFormatter
from nexus.observability import tracing
from nexus.observability.tracing import (
    DEFAULT_SPAN_ID,
    DEFAULT_TRACE_ID,
    current_trace_id,
    get_tracer,
    init_tracing,
    instrument_app,
    trace_span,
)


class TestInitTracing:
    """init_tracing() only installs a provider when configured."""

    def test_no_endpoint_is_noop(self, monkeypatch) -> None:
        monkeypatch.delenv("OTEL_EXPORTER_OTLP_ENDPOINT", raising=False)
        monkeypatch.setattr(tracing, "_INITIALIZED", False)
        assert init_tracing() is False
        assert tracing._INITIALIZED is False

    def test_endpoint_without_sdk_is_noop(self, monkeypatch) -> None:
        """A configured endpoint must not crash startup when the SDK is absent."""
        monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://localhost:4318")
        monkeypatch.setattr(tracing, "_INITIALIZED", False)
        monkeypatch.setattr(tracing, "_OTEL_AVAILABLE", False)
        assert init_tracing() is False

    def test_idempotent(self, monkeypatch) -> None:
        monkeypatch.setattr(tracing, "_INITIALIZED", True)
        assert init_tracing() is True


class TestSpans:
    """Spans are usable whether or not the SDK is present."""

    def test_tracer_span_context_manager(self) -> None:
        with get_tracer("nexus.test").start_as_current_span("unit") as span:
            span.set_attribute("key", "value")

    def test_trace_span_returns_value(self) -> None:
        @trace_span("nexus.test", "sync_op")
        def add(a: int, b: int) -> int:
            return a + b

        assert add(2, 3) == 5

    async def test_trace_span_async_reraises(self) -> None:
        @trace_span("nexus.test", "async_op")
        async def boom() -> None:
            raise ValueError("boom")

        try:
            await boom()
        except ValueError as exc:
            assert str(exc) == "boom"
        else:
            raise AssertionError("exception was swallowed by the span wrapper")


class TestInstrumentApp:
    def test_uninitialized_is_noop(self, monkeypatch) -> None:
        monkeypatch.setattr(tracing, "_INITIALIZED", False)
        instrument_app(object())  # must not raise on a non-app


class TestLogCorrelation:
    """JSON logs carry trace/span IDs so a log line pivots to its trace."""

    def _format(self, msg: str) -> dict:
        record = logging.LogRecord(
            name="nexus.test",
            level=logging.INFO,
            pathname="test.py",
            lineno=1,
            msg=msg,
            args=None,
            exc_info=None,
        )
        return json.loads(JSONFormatter().format(record))

    def test_zero_ids_when_no_active_span(self) -> None:
        assert current_trace_id() is None
        parsed = self._format("no trace")
        assert parsed["trace_id"] == DEFAULT_TRACE_ID
        assert parsed["span_id"] == DEFAULT_SPAN_ID

    def test_ids_match_active_span(self) -> None:
        """Inside a span the log line must carry that span's real IDs."""
        with get_tracer("nexus.test").start_as_current_span("logged"):
            tid = current_trace_id()
            parsed = self._format("in trace")
            if tid is None:  # SDK absent or no provider: stays inert
                assert parsed["trace_id"] == DEFAULT_TRACE_ID
            else:
                assert parsed["trace_id"] == tid
                assert parsed["span_id"] != DEFAULT_SPAN_ID
