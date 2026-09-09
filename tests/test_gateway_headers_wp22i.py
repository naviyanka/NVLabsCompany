"""WP-22i / M12: parse gateway routing-decision headers.

Pure parser for the routing provenance a gateway stamps on completion
responses. Wiring into the adapter + audit write is deferred until a Connection
actually routes traffic (no headers to capture before then).

R1: tests invoke parse_routing_headers. Header shape verified live against
OmniRoute 3.8.50.
"""

from nexus.models_router.gateway_headers import (
    RoutingDecision,
    parse_routing_headers,
)

# Captured live from a real completion response.
_LIVE_HEADERS = {
    "x-omniroute-decision": "strategy=auto; provider=kr; latency_ms=2356",
    "x-omniroute-latency-ms": "2356",
    "x-omniroute-provider": "kr",
    "x-omniroute-request-id": "4f15ae69-cb62-4542-9759-b2d7e291a11f",
    "x-omniroute-cache-hit": "false",
    "x-omniroute-response-cost": "0.0000000000",
    "x-omniroute-version": "3.8.50",
}


def test_parses_live_decision_header():
    d = parse_routing_headers(_LIVE_HEADERS)
    assert d.strategy == "auto"
    assert d.provider == "kr"
    assert d.latency_ms == 2356
    assert d.request_id == "4f15ae69-cb62-4542-9759-b2d7e291a11f"
    assert d.cache_hit is False
    assert d.response_cost_micros == 0  # $0 free-tier, not inflated (R11)
    assert not d.is_empty()


def test_fallback_attempts_and_cache_hit_true():
    d = parse_routing_headers(
        {
            "X-OmniRoute-Decision": "strategy=cost; provider=openai; latency_ms=90",
            "X-OmniRoute-Cache-Hit": "true",
            "X-OmniRoute-Fallback-Attempts": "2",
            "X-OmniRoute-Response-Cost": "0.0021",
        }
    )
    assert d.strategy == "cost"
    assert d.cache_hit is True
    assert d.fallback_attempts == 2
    assert d.response_cost_micros == 2100  # 0.0021 USD -> 2100 micro-USD


def test_non_gateway_response_is_empty():
    d = parse_routing_headers({"content-type": "application/json"})
    assert d.is_empty()
    assert d == RoutingDecision()


def test_provider_falls_back_to_dedicated_header_without_decision():
    d = parse_routing_headers({"x-omniroute-provider": "anthropic"})
    assert d.provider == "anthropic"
    assert d.strategy is None
