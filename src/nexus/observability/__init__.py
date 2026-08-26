"""Observability — optional OpenTelemetry tracing integration.

Provides a thin wrapper that uses real OTel spans when the SDK is installed
and configured, and degrades to no-op spans otherwise. This lets the codebase
be instrumented without a hard dependency on opentelemetry packages.

Usage:
    from nexus.observability.tracing import get_tracer

    tracer = get_tracer("nexus.orchestrator")
    with tracer.start_as_current_span("evaluate_proposal") as span:
        span.set_attribute("proposal_id", str(proposal_id))
        ...
"""
