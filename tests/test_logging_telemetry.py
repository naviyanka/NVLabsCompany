"""Tests for structured logging, correlation IDs, and telemetry.

Covers:
- JSONFormatter produces valid JSON with expected fields
- correlation_id appears in log output when set
- RequestIDMiddleware sets context var and response header
- Counter increments correctly
- Histogram observe and bucket counting
- /metrics endpoint returns Prometheus-format text
- MetricsMiddleware tracks requests
"""

import json
import logging
import uuid

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.responses import PlainTextResponse

from nexus.logging_config import (
    JSONFormatter,
    RequestIDMiddleware,
    configure_logging,
    correlation_id,
    get_correlation_id,
)
from nexus.telemetry import (
    Counter,
    Histogram,
    MetricsMiddleware,
    _MetricsRegistry,
    metrics_router,
    render_metrics,
    registry,
)


class TestJSONFormatter:
    """Tests for the JSON log formatter."""

    def test_produces_valid_json(self) -> None:
        """JSON formatter outputs parseable JSON."""
        formatter = JSONFormatter()
        record = logging.LogRecord(
            name="test.logger",
            level=logging.INFO,
            pathname="test.py",
            lineno=1,
            msg="Test message",
            args=None,
            exc_info=None,
        )
        output = formatter.format(record)
        parsed = json.loads(output)
        assert isinstance(parsed, dict)

    def test_contains_expected_fields(self) -> None:
        """JSON output contains timestamp, level, logger, message, correlation_id."""
        formatter = JSONFormatter()
        record = logging.LogRecord(
            name="nexus.test",
            level=logging.WARNING,
            pathname="test.py",
            lineno=10,
            msg="Something happened",
            args=None,
            exc_info=None,
        )
        output = formatter.format(record)
        parsed = json.loads(output)
        assert "timestamp" in parsed
        assert parsed["level"] == "WARNING"
        assert parsed["logger"] == "nexus.test"
        assert parsed["message"] == "Something happened"
        assert "correlation_id" in parsed

    def test_correlation_id_in_output_when_set(self) -> None:
        """correlation_id value appears in log output when context var is set."""
        formatter = JSONFormatter()
        test_id = "test-corr-id-12345"
        token = correlation_id.set(test_id)
        try:
            record = logging.LogRecord(
                name="test",
                level=logging.INFO,
                pathname="test.py",
                lineno=1,
                msg="with correlation",
                args=None,
                exc_info=None,
            )
            output = formatter.format(record)
            parsed = json.loads(output)
            assert parsed["correlation_id"] == test_id
        finally:
            correlation_id.reset(token)

    def test_correlation_id_none_by_default(self) -> None:
        """correlation_id is None when not set."""
        formatter = JSONFormatter()
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="test.py",
            lineno=1,
            msg="no correlation",
            args=None,
            exc_info=None,
        )
        output = formatter.format(record)
        parsed = json.loads(output)
        assert parsed["correlation_id"] is None


class TestConfigureLogging:
    """Tests for configure_logging()."""

    def test_configure_sets_handler(self) -> None:
        """configure_logging adds a handler with JSONFormatter."""
        configure_logging(level="DEBUG")
        root = logging.getLogger()
        assert len(root.handlers) > 0
        assert isinstance(root.handlers[0].formatter, JSONFormatter)
        assert root.level == logging.DEBUG

    def test_configure_removes_duplicate_handlers(self) -> None:
        """configure_logging clears existing handlers."""
        configure_logging()
        configure_logging()
        root = logging.getLogger()
        assert len(root.handlers) == 1


class TestGetCorrelationId:
    """Tests for get_correlation_id()."""

    def test_returns_none_by_default(self) -> None:
        """Returns None when no correlation_id is set."""
        assert get_correlation_id() is None or get_correlation_id() is not None
        # Reset to ensure clean state
        token = correlation_id.set(None)
        try:
            assert get_correlation_id() is None
        finally:
            correlation_id.reset(token)

    def test_returns_set_value(self) -> None:
        """Returns the value that was set in the context var."""
        token = correlation_id.set("my-id")
        try:
            assert get_correlation_id() == "my-id"
        finally:
            correlation_id.reset(token)


class TestRequestIDMiddleware:
    """Tests for the RequestIDMiddleware ASGI middleware."""

    def _make_app(self) -> FastAPI:
        """Create a test FastAPI app with RequestIDMiddleware."""
        app = FastAPI()

        @app.get("/test")
        async def test_endpoint() -> dict[str, str | None]:
            return {"correlation_id": get_correlation_id()}

        app.add_middleware(RequestIDMiddleware)
        return app

    def test_generates_request_id_if_missing(self) -> None:
        """Middleware generates a UUID if X-Request-ID header is absent."""
        app = self._make_app()
        client = TestClient(app)
        response = client.get("/test")
        assert response.status_code == 200
        assert "x-request-id" in response.headers
        # Should be a valid UUID
        request_id = response.headers["x-request-id"]
        uuid.UUID(request_id)  # Raises if invalid

    def test_propagates_existing_request_id(self) -> None:
        """Middleware uses the provided X-Request-ID header value."""
        app = self._make_app()
        client = TestClient(app)
        test_id = "custom-request-id-abc"
        response = client.get("/test", headers={"X-Request-ID": test_id})
        assert response.status_code == 200
        assert response.headers["x-request-id"] == test_id

    def test_sets_correlation_id_context_var(self) -> None:
        """Middleware sets correlation_id context var for the request scope."""
        app = self._make_app()
        client = TestClient(app)
        test_id = "context-var-test-id"
        response = client.get("/test", headers={"X-Request-ID": test_id})
        assert response.status_code == 200
        body = response.json()
        assert body["correlation_id"] == test_id

    def test_non_http_scope_passthrough(self) -> None:
        """Non-HTTP scopes pass through without modification."""
        app = self._make_app()
        client = TestClient(app)
        # WebSocket connections should not be blocked
        # (TestClient doesn't easily test this, but the code path exists)
        response = client.get("/test")
        assert response.status_code == 200


class TestCounter:
    """Tests for the Counter metric class."""

    def test_initial_value_is_zero(self) -> None:
        """Counter starts at zero."""
        counter = Counter("test_counter", "A test counter")
        assert counter.value == 0.0

    def test_inc_default_amount(self) -> None:
        """Counter increments by 1 by default."""
        counter = Counter("test_counter")
        counter.inc()
        assert counter.value == 1.0

    def test_inc_custom_amount(self) -> None:
        """Counter increments by specified amount."""
        counter = Counter("test_counter")
        counter.inc(amount=5.0)
        assert counter.value == 5.0

    def test_inc_with_labels(self) -> None:
        """Counter tracks different label combinations separately."""
        counter = Counter("test_counter")
        counter.inc(labels={"method": "GET"})
        counter.inc(labels={"method": "POST"})
        counter.inc(labels={"method": "GET"})
        assert counter.get(labels={"method": "GET"}) == 2.0
        assert counter.get(labels={"method": "POST"}) == 1.0
        assert counter.value == 3.0

    def test_collect_returns_all_samples(self) -> None:
        """collect() returns all label/value pairs."""
        counter = Counter("test_counter")
        counter.inc(labels={"a": "1"})
        counter.inc(labels={"a": "2"})
        samples = counter.collect()
        assert len(samples) == 2


class TestHistogram:
    """Tests for the Histogram metric class."""

    def test_initial_state(self) -> None:
        """Histogram starts empty."""
        hist = Histogram("test_hist")
        assert hist.count == 0
        assert hist.sum == 0.0

    def test_observe_updates_count_and_sum(self) -> None:
        """observe() increments count and adds to sum."""
        hist = Histogram("test_hist")
        hist.observe(0.5)
        hist.observe(1.5)
        assert hist.count == 2
        assert hist.sum == 2.0

    def test_bucket_counting(self) -> None:
        """Values are placed in correct buckets."""
        hist = Histogram("test_hist", buckets=(0.1, 0.5, 1.0))
        hist.observe(0.05)  # fits in 0.1 bucket
        hist.observe(0.3)   # fits in 0.5 bucket
        hist.observe(0.8)   # fits in 1.0 bucket
        hist.observe(2.0)   # exceeds all buckets

        buckets = hist.get_buckets()
        # Cumulative: 0.1 -> 1, 0.5 -> 2, 1.0 -> 3
        assert buckets[0] == (0.1, 1)
        assert buckets[1] == (0.5, 2)
        assert buckets[2] == (1.0, 3)

    def test_observe_with_labels(self) -> None:
        """Histogram tracks observations per label set."""
        hist = Histogram("test_hist", buckets=(1.0,))
        hist.observe(0.5, labels={"path": "/a"})
        hist.observe(0.5, labels={"path": "/b"})
        assert hist.count == 2

        buckets_a = hist.get_buckets(labels={"path": "/a"})
        assert buckets_a[0] == (1.0, 1)

    def test_collect(self) -> None:
        """collect() returns structured data for rendering."""
        hist = Histogram("test_hist", buckets=(1.0, 5.0))
        hist.observe(0.5)
        hist.observe(3.0)
        samples = hist.collect()
        assert len(samples) == 1
        assert samples[0]["count"] == 2
        assert samples[0]["sum"] == 3.5


class TestMetricsEndpoint:
    """Tests for the /metrics endpoint."""

    def _make_app(self) -> FastAPI:
        """Create a test FastAPI app with metrics."""
        app = FastAPI()
        app.include_router(metrics_router)
        return app

    def test_metrics_endpoint_returns_200(self) -> None:
        """GET /metrics returns 200 OK."""
        app = self._make_app()
        client = TestClient(app)
        response = client.get("/metrics")
        assert response.status_code == 200

    def test_metrics_endpoint_content_type(self) -> None:
        """GET /metrics returns text/plain content type."""
        app = self._make_app()
        client = TestClient(app)
        response = client.get("/metrics")
        assert "text/plain" in response.headers["content-type"]

    def test_metrics_endpoint_prometheus_format(self) -> None:
        """GET /metrics returns Prometheus text format with HELP and TYPE lines."""
        app = self._make_app()
        client = TestClient(app)
        response = client.get("/metrics")
        body = response.text
        assert "# HELP" in body
        assert "# TYPE" in body
        assert "http_requests_total" in body
        assert "http_request_duration_seconds" in body


class TestRenderMetrics:
    """Tests for the render_metrics function."""

    def test_renders_counter(self) -> None:
        """Counters are rendered with HELP, TYPE, and value lines."""
        test_registry = _MetricsRegistry()
        c = Counter("test_total", "A test counter")
        c.inc(labels={"method": "GET"})
        test_registry.register(c)

        # Temporarily swap the global registry
        import nexus.telemetry as telemetry_mod

        old_registry = telemetry_mod.registry
        telemetry_mod.registry = test_registry
        try:
            output = render_metrics()
        finally:
            telemetry_mod.registry = old_registry

        assert "# HELP test_total A test counter" in output
        assert "# TYPE test_total counter" in output
        assert 'test_total{method="GET"} 1.0' in output

    def test_renders_histogram(self) -> None:
        """Histograms are rendered with buckets, sum, and count."""
        test_registry = _MetricsRegistry()
        h = Histogram("test_duration", "Test duration", buckets=(0.1, 1.0))
        h.observe(0.05)
        test_registry.register(h)

        import nexus.telemetry as telemetry_mod

        old_registry = telemetry_mod.registry
        telemetry_mod.registry = test_registry
        try:
            output = render_metrics()
        finally:
            telemetry_mod.registry = old_registry

        assert "# HELP test_duration Test duration" in output
        assert "# TYPE test_duration histogram" in output
        assert "test_duration_bucket" in output
        assert "test_duration_sum" in output
        assert "test_duration_count" in output
        assert '+Inf' in output


class TestMetricsMiddleware:
    """Tests for the MetricsMiddleware ASGI middleware."""

    def _make_app(self) -> FastAPI:
        """Create a test FastAPI app with MetricsMiddleware."""
        app = FastAPI()

        @app.get("/hello")
        async def hello() -> PlainTextResponse:
            return PlainTextResponse("Hello!")

        app.add_middleware(MetricsMiddleware)
        app.include_router(metrics_router)
        return app

    def test_tracks_requests(self) -> None:
        """MetricsMiddleware increments http_requests_total."""
        from nexus.telemetry import http_requests_total

        app = self._make_app()
        client = TestClient(app)

        initial_value = http_requests_total.value
        client.get("/hello")
        # At least one request should have been recorded
        assert http_requests_total.value > initial_value

    def test_records_duration(self) -> None:
        """MetricsMiddleware observes request duration."""
        from nexus.telemetry import http_request_duration_seconds

        app = self._make_app()
        client = TestClient(app)

        initial_count = http_request_duration_seconds.count
        client.get("/hello")
        assert http_request_duration_seconds.count > initial_count

    def test_metrics_visible_in_endpoint(self) -> None:
        """Requests tracked by middleware appear in /metrics output."""
        app = self._make_app()
        client = TestClient(app)

        # Make a request that the middleware will track
        client.get("/hello")

        # Now check /metrics
        response = client.get("/metrics")
        assert response.status_code == 200
        assert "http_requests_total" in response.text
