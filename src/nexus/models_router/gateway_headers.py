"""Parse gateway routing-decision response headers (WP-22i / M12).

An OpenAI-compatible gateway stamps every completion response with routing
provenance: which strategy chose which upstream, after how many failovers, at
what cost, cache hit or miss. Persisting these alongside the hash-chained audit
record gives verifiable provenance of every model call.

This is the pure parser. It is wired into the adapter + audit write only once a
Connection actually routes traffic through such a gateway; until then there are
no headers to capture, so threading them through TaskResult + record_audit
would be scaffolding for a path with no callers. No vendor name in behaviour
(R9): header keys are matched case-insensitively by suffix, not a literal.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping


@dataclass(frozen=True)
class RoutingDecision:
    """Routing provenance extracted from a completion response's headers."""

    strategy: str | None = None
    provider: str | None = None
    latency_ms: int | None = None
    request_id: str | None = None
    cache_hit: bool | None = None
    fallback_attempts: int | None = None
    response_cost_micros: int | None = None

    def is_empty(self) -> bool:
        """True when no routing header was present (a non-gateway provider)."""
        return all(
            v is None
            for v in (
                self.strategy,
                self.provider,
                self.latency_ms,
                self.request_id,
                self.cache_hit,
                self.fallback_attempts,
                self.response_cost_micros,
            )
        )


def _get(headers: Mapping[str, str], suffix: str) -> str | None:
    """Case-insensitive lookup of a header whose name ends with ``suffix``."""
    s = suffix.lower()
    for k, v in headers.items():
        if k.lower().endswith(s):
            return v
    return None


def _parse_decision_field(decision: str) -> dict[str, str]:
    """Split ``strategy=auto; provider=kr; latency_ms=2356`` into a dict."""
    out: dict[str, str] = {}
    for part in decision.split(";"):
        if "=" in part:
            k, _, v = part.partition("=")
            out[k.strip()] = v.strip()
    return out


def parse_routing_headers(headers: Mapping[str, str]) -> RoutingDecision:
    """Extract a RoutingDecision from response headers. Absent fields stay None.

    Cost arrives as a decimal-USD string (e.g. ``0.0000000000``) and is stored
    as integer micro-USD (R11), never a float or inflated cent.
    """
    decision_raw = _get(headers, "-decision")
    parts = _parse_decision_field(decision_raw) if decision_raw else {}

    def _int(v: str | None) -> int | None:
        try:
            return int(v) if v is not None else None
        except ValueError:
            return None

    latency = parts.get("latency_ms") or _get(headers, "-latency-ms")
    cache_hit_raw = _get(headers, "-cache-hit")
    fallback_raw = _get(headers, "-fallback-attempts")
    cost_raw = _get(headers, "-response-cost")

    cost_micros: int | None = None
    if cost_raw is not None:
        try:
            import math

            cost_micros = math.ceil(float(cost_raw) * 1_000_000)
        except ValueError:
            cost_micros = None

    cache_hit: bool | None = None
    if cache_hit_raw is not None:
        cache_hit = cache_hit_raw.strip().lower() == "true"

    return RoutingDecision(
        strategy=parts.get("strategy"),
        provider=parts.get("provider") or _get(headers, "-provider"),
        latency_ms=_int(latency),
        request_id=_get(headers, "-request-id"),
        cache_hit=cache_hit,
        fallback_attempts=_int(fallback_raw),
        response_cost_micros=cost_micros,
    )
