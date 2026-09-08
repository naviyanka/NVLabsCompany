"""Enterprise acceptance tests for OpenTelemetry Tracing, Prometheus Metrics, and Structured Logging."""

import json
import logging
import uuid
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient
from httpx import ASGITransport, AsyncClient

from nexus.logging_config import JSONFormatter, configure_logging, get_correlation_id
from nexus.main import app
from nexus.observability.metrics import (
    generate_metrics_response,
    nexus_circuit_breaker_trips_total,
    nexus_llm_cost_cents_total,
    nexus_llm_tokens_total,
    record_budget_exhausted,
    record_checkpoint_recovery,
    record_checkpoint_save,
    record_circuit_breaker_trip,
    record_http_request,
    record_llm_metrics,
    record_orchestrator_tick,
    record_task_metrics,
    set_active_reservations,
    set_running_tasks,
)
from nexus.observability.tracing import (
    DEFAULT_SPAN_ID,
    DEFAULT_TRACE_ID,
    current_span_context,
    current_span_id,
    current_trace_id,
    extract_trace_context,
    get_in_memory_spans,
    get_tracer,
    init_tracing,
    inject_trace_context,
    record_llm_usage,
    reset_tracing,
    start_llm_span,
    start_tool_span,
    trace_span,
)


@pytest.fixture(autouse=True)
def setup_test_tracing():
    """Ensure in-memory OpenTelemetry tracer is initialized for test verification."""
    init_tracing(force_in_memory=True)
    reset_tracing()
    yield
    reset_tracing()


# ---------------------------------------------------------------------------
# 1. W3C Traceparent Context Propagation Tests
# ---------------------------------------------------------------------------


class TestW3CTraceContextPropagation:
    """Verifies W3C traceparent (00-{trace_id}-{span_id}-{flags}) injection and extraction."""

    def test_w3c_traceparent_injection_and_extraction(self):
        """Inject active span context into headers and extract into child span context."""
        tracer = get_tracer("nexus.test")

        with tracer.start_as_current_span("parent_operation") as parent_span:
            # 1. Inject context into outbound carrier headers
            carrier = inject_trace_context({"x-custom-header": "test-val"})
            assert "traceparent" in carrier
            traceparent = carrier["traceparent"]

            # Validate W3C traceparent format: version-trace_id-span_id-trace_flags
            parts = traceparent.split("-")
            assert len(parts) == 4
            assert parts[0] == "00"  # Version
            assert len(parts[1]) == 32  # 32-hex trace ID
            assert len(parts[2]) == 16  # 16-hex span ID
            assert len(parts[3]) == 2  # Trace flags (2 hex chars)

            assert parts[1] == current_trace_id()
            assert parts[2] == current_span_id()

            # 2. Extract context on receiving boundary
            extracted_context = extract_trace_context(carrier)
            assert extracted_context is not None

            # 3. Create child span with extracted context
            with tracer.start_as_current_span("child_operation", context=extracted_context) as child_span:
                assert current_trace_id() == parts[1]  # Same trace ID
                assert current_span_id() != parts[2]  # New unique span ID


# ---------------------------------------------------------------------------
# 2. OpenTelemetry GenAI Semantic Conventions Tests
# ---------------------------------------------------------------------------


class TestGenAISemanticConventions:
    """Verifies OpenTelemetry GenAI semantic conventions on LLM and tool spans."""

    def test_gen_ai_llm_span_attributes(self):
        """Verify start_llm_span and record_llm_usage populate standard GenAI attributes."""
        company_id = uuid.uuid4()
        agent_id = uuid.uuid4()
        model_name = "gpt-4o"
        provider = "openai"

        with start_llm_span(
            model=model_name,
            provider=provider,
            company_id=company_id,
            agent_id=agent_id,
            prompt="Analyze quarterly financial report",
        ) as span:
            record_llm_usage(
                span=span,
                input_tokens=250,
                output_tokens=100,
                cost_cents=1.75,
                finish_reason="stop",
                model=model_name,
            )

        spans = get_in_memory_spans()
        assert len(spans) >= 1
        llm_span = spans[-1]

        assert "gen_ai.chat gpt-4o" in llm_span.name
        attributes = dict(llm_span.attributes)

        # Standard GenAI Semantic Conventions
        assert attributes.get("gen_ai.system") == "openai"
        assert attributes.get("gen_ai.request.model") == "gpt-4o"
        assert attributes.get("gen_ai.operation.name") == "chat"
        assert attributes.get("gen_ai.usage.input_tokens") == 250
        assert attributes.get("gen_ai.usage.output_tokens") == 100
        assert attributes.get("gen_ai.usage.total_tokens") == 350
        assert attributes.get("gen_ai.usage.cost_cents") == 1.75
        assert attributes.get("gen_ai.response.finish_reasons") == ("stop",)

        # Multi-tenant NEXUS attributes
        assert attributes.get("nexus.company_id") == str(company_id)
        assert attributes.get("nexus.agent_id") == str(agent_id)

    def test_tool_execution_span_attributes(self):
        """Verify start_tool_span records tool execution semantics."""
        agent_id = uuid.uuid4()
        task_id = uuid.uuid4()

        with start_tool_span(
            tool_name="rag_search",
            agent_id=agent_id,
            task_id=task_id,
        ):
            pass

        spans = get_in_memory_spans()
        assert len(spans) >= 1
        tool_span = spans[-1]

        assert tool_span.name == "tool.execute rag_search"
        attributes = dict(tool_span.attributes)
        assert attributes.get("gen_ai.tool.name") == "rag_search"
        assert attributes.get("nexus.tool_name") == "rag_search"
        assert attributes.get("nexus.agent_id") == str(agent_id)
        assert attributes.get("nexus.task_id") == str(task_id)


# ---------------------------------------------------------------------------
# 3. Prometheus Metrics Registry & /metrics Endpoint Tests
# ---------------------------------------------------------------------------


class TestPrometheusMetricsRegistry:
    """Verifies Prometheus counters, histograms, gauges, and /metrics endpoint."""

    @pytest.mark.asyncio
    async def test_metrics_increment_and_export(self):
        """Record metrics and assert Prometheus text exposition endpoint returns valid counts."""
        company_id = uuid.uuid4()
        agent_id = uuid.uuid4()

        # 1. Record various metrics
        record_llm_metrics(
            company_id=company_id,
            agent_id=agent_id,
            provider="anthropic",
            model="claude-3-5-sonnet",
            input_tokens=1000,
            output_tokens=500,
            cost_cents=4.5,
            duration_seconds=1.85,
        )

        record_task_metrics(agent_id=agent_id, status="completed", duration_seconds=12.4)
        record_circuit_breaker_trip(service="openai_adapter")
        record_budget_exhausted(company_id=company_id, scope="monthly")
        record_checkpoint_save(status="active")
        record_checkpoint_recovery(status="success")
        record_http_request(method="GET", endpoint="/api/v1/health", status_code=200, duration_seconds=0.012)
        set_active_reservations(company_id=company_id, cents=150)
        set_running_tasks(status="in_progress", count=4)
        record_orchestrator_tick()

        # 2. Generate metrics response
        body_bytes, content_type = generate_metrics_response()
        output_text = body_bytes.decode("utf-8")

        assert "text/plain" in content_type

        # 3. Verify standard Prometheus metric lines
        assert "nexus_llm_tokens_total" in output_text
        assert 'token_type="input"' in output_text
        assert 'token_type="output"' in output_text
        assert 'model="claude-3-5-sonnet"' in output_text

        assert "nexus_llm_cost_cents_total" in output_text
        assert 'provider="anthropic"' in output_text

        assert "nexus_circuit_breaker_trips_total" in output_text
        assert 'service="openai_adapter"' in output_text

        assert "nexus_http_request_duration_seconds" in output_text
        assert "nexus_task_execution_duration_seconds" in output_text
        assert "nexus_active_reservations_cents" in output_text
        assert "nexus_running_tasks_count" in output_text
        assert "nexus_orchestrator_tick_last_timestamp_seconds" in output_text

    @pytest.mark.asyncio
    async def test_metrics_http_endpoint(self):
        """Assert /metrics endpoint returns HTTP 200 with Prometheus payload."""
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/metrics")
            assert response.status_code == 200
            assert "text/plain" in response.headers.get("content-type", "")
            assert "nexus_" in response.text or "HELP" in response.text


# ---------------------------------------------------------------------------
# 4. Trace-Correlated Structured Logging Tests
# ---------------------------------------------------------------------------


class TestTraceCorrelatedLogging:
    """Verifies that JSON structured logs contain active trace_id and span_id."""

    def test_log_formatter_with_active_span(self):
        """Logs emitted inside an active span must contain the corresponding trace_id and span_id."""
        formatter = JSONFormatter()
        tracer = get_tracer("nexus.logging")

        with tracer.start_as_current_span("logged_action") as span:
            expected_trace_id = current_trace_id()
            expected_span_id = current_span_id()

            record = logging.LogRecord(
                name="nexus.test",
                level=logging.INFO,
                pathname="test.py",
                lineno=10,
                msg="Executing subtask with trace correlation",
                args=(),
                exc_info=None,
            )

            formatted_json = formatter.format(record)
            log_data = json.loads(formatted_json)

            assert log_data["message"] == "Executing subtask with trace correlation"
            assert log_data["level"] == "INFO"
            assert log_data["logger"] == "nexus.test"
            assert log_data["trace_id"] == expected_trace_id
            assert log_data["span_id"] == expected_span_id
            assert len(log_data["trace_id"]) == 32
            assert len(log_data["span_id"]) == 16

    def test_log_formatter_outside_active_span(self):
        """Logs emitted outside active spans fall back to default zeroes."""
        formatter = JSONFormatter()

        record = logging.LogRecord(
            name="nexus.test",
            level=logging.WARNING,
            pathname="test.py",
            lineno=20,
            msg="System background idle log",
            args=(),
            exc_info=None,
        )

        formatted_json = formatter.format(record)
        log_data = json.loads(formatted_json)

        assert log_data["trace_id"] == DEFAULT_TRACE_ID
        assert log_data["span_id"] == DEFAULT_SPAN_ID


# ---------------------------------------------------------------------------
# 5. Function Tracing Decorator & Zero-Overhead Fallback Tests
# ---------------------------------------------------------------------------


class TestFunctionTracingDecorator:
    """Verifies @trace_span decorator on sync and async functions."""

    @pytest.mark.asyncio
    async def test_trace_span_async_decorator(self):
        """Async function wrapped with @trace_span creates a span and captures return value."""
        @trace_span("nexus.test", "async_operation", attributes={"tier": "service"})
        async def sample_async_func(x: int, y: int) -> int:
            return x + y

        result = await sample_async_func(10, 20)
        assert result == 30

        spans = get_in_memory_spans()
        assert len(spans) >= 1
        span = spans[-1]
        assert span.name == "async_operation"
        assert span.attributes.get("tier") == "service"

    def test_trace_span_sync_decorator(self):
        """Sync function wrapped with @trace_span creates a span."""
        @trace_span("nexus.test", "sync_operation", attributes={"component": "governance"})
        def sample_sync_func(name: str) -> str:
            return f"hello {name}"

        result = sample_sync_func("world")
        assert result == "hello world"

        spans = get_in_memory_spans()
        assert len(spans) >= 1
        span = spans[-1]
        assert span.name == "sync_operation"
        assert span.attributes.get("component") == "governance"

    @pytest.mark.asyncio
    async def test_trace_span_records_exceptions(self):
        """Exceptions raised in @trace_span wrapped functions are recorded on the span."""
        @trace_span("nexus.test", "failing_operation")
        async def failing_func():
            raise ValueError("simulated processing error")

        with pytest.raises(ValueError, match="simulated processing error"):
            await failing_func()

        spans = get_in_memory_spans()
        assert len(spans) >= 1
        span = spans[-1]
        assert span.name == "failing_operation"
        assert len(span.events) >= 1
        assert span.events[0].name == "exception"


# ---------------------------------------------------------------------------
# 6. HTTP Middleware Request ID & Tracing Headers
# ---------------------------------------------------------------------------


class TestHttpMiddlewareTracing:
    """Verifies RequestIDMiddleware correlation headers on FastAPI endpoints."""

    @pytest.mark.asyncio
    async def test_inbound_traceparent_propagation_on_http_request(self):
        """Inbound traceparent is extracted and propagated to response headers."""
        custom_request_id = str(uuid.uuid4())
        custom_trace_id = "4bf92f3577b34da6a3ce929d0e0e4736"
        custom_span_id = "00f067aa0ba902b7"
        traceparent_header = f"00-{custom_trace_id}-{custom_span_id}-01"

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get(
                "/health",
                headers={
                    "x-request-id": custom_request_id,
                    "traceparent": traceparent_header,
                },
            )
            assert response.status_code == 200
            assert response.headers.get("x-request-id") == custom_request_id
            assert response.headers.get("x-trace-id") == custom_trace_id
            assert custom_trace_id in response.headers.get("traceparent", "")


# ---------------------------------------------------------------------------
# 7. Zero-Overhead Fallback Tests
# ---------------------------------------------------------------------------


class TestZeroOverheadFallback:
    """Verifies that tracing degrades gracefully to zero-cost no-op when disabled."""

    def test_noop_tracer_and_span_operations(self):
        """No-op tracer handles context managers, attribute setting, and exception recording without error."""
        from nexus.observability.tracing import _NoopSpan, _NoopTracer

        tracer = _NoopTracer()
        span = tracer.start_span("test_span")
        assert isinstance(span, _NoopSpan)
        assert span.is_recording() is False

        # All span methods must succeed safely as no-ops
        span.set_attribute("key", "val")
        span.set_attributes({"a": 1, "b": 2})
        span.add_event("event_name", {"attr": True})
        span.record_exception(RuntimeError("test error"))
        span.set_status("OK")
        span.end()

        # Context manager support
        with tracer.start_as_current_span("cm_span") as cm_span:
            cm_span.set_attribute("nested", True)

    def test_decorator_with_noop_tracer(self):
        """Decorator functions work seamlessly when tracer is no-op."""
        from nexus.observability.tracing import _NoopTracer

        with patch("nexus.observability.tracing.get_tracer", return_value=_NoopTracer()):
            @trace_span("nexus.test", "noop_decorated")
            def sync_fn(a: int, b: int) -> int:
                return a * b

            assert sync_fn(6, 7) == 42


# ---------------------------------------------------------------------------
# 8. End-to-End Adapter & Orchestrator Metrics Verification
# ---------------------------------------------------------------------------


class TestEndToEndTracingAndMetrics:
    """Verifies end-to-end instrumentation across base adapter and orchestrator."""

    @pytest.mark.asyncio
    async def test_base_adapter_task_metrics_recording(self):
        """Executing a task via BaseAdapter records task execution duration and status."""
        from nexus.adapters.base import AgentSession, AgentStatus, BaseAdapter, TaskResult

        class DummyAdapter(BaseAdapter):
            def validate_config(self, config: dict[str, Any]) -> bool:
                return True

            async def create_session(self, agent_id, config):
                session = AgentSession(
                    session_id=str(uuid.uuid4()),
                    agent_id=agent_id,
                    adapter_type="dummy",
                    status=AgentStatus.READY,
                    config=config,
                )
                self._sessions[session.session_id] = session
                return session

            async def terminate(self, session):
                return True

            async def _do_execute(self, session, task_id, payload):
                return TaskResult(
                    task_id=task_id,
                    agent_id=session.agent_id,
                    success=True,
                    output="dummy output",
                    input_tokens=100,
                    output_tokens=50,
                    cost_cents=2,
                )

        adapter = DummyAdapter()
        agent_id = uuid.uuid4()
        task_id = uuid.uuid4()
        session = await adapter.create_session(agent_id, {})

        result = await adapter.execute_task(session, task_id, {"prompt": "test"})
        assert result.success is True
        assert result.duration_ms >= 0

        # Verify metrics updated
        body, _ = generate_metrics_response()
        metrics_text = body.decode("utf-8")
        assert "nexus_task_execution_duration_seconds" in metrics_text


