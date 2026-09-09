"""Tier 1 gateway ceiling admin (WP-22f / M9).

The company-wide wall is owned by the gateway itself: one management key, one
monthly USD ceiling, enforced last. NEXUS sets it via the management API
(POST /api/usage/budget) using the Connection's mgmt_key_ref — never the
inference key, which the /api/* routes reject.

NEXUS stores a soft warning as ``warn_percent`` (0..100); the gateway wants
``warningThreshold`` (0..1). This is the one conversion worth getting right.

No vendor name in behaviour (R9): the endpoint path is the gateway's documented
management surface, reached via the Connection's base_url.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class CeilingResult:
    """Outcome of setting the gateway ceiling."""

    ok: bool
    monthly_limit_usd: float | None = None
    warning_threshold: float | None = None
    error: str | None = None


def _admin_base(base_url: str) -> str:
    """Strip the /v1 inference suffix to reach the /api management surface."""
    root = base_url.rstrip("/")
    if root.endswith("/v1"):
        root = root[: -len("/v1")]
    return root


def build_budget_body(
    api_key_id: str,
    monthly_limit_usd: float,
    warn_percent: int = 80,
    reset_interval: str = "monthly",
    reset_time: str = "00:00",
) -> dict[str, Any]:
    """Build the POST /api/usage/budget body, converting warn_percent -> 0..1.

    Kept pure so the conversion is unit-testable without a live gateway.
    """
    return {
        "apiKeyId": api_key_id,
        "monthlyLimitUsd": monthly_limit_usd,
        "warningThreshold": round(warn_percent / 100, 4),
        "resetInterval": reset_interval,
        "resetTime": reset_time,
    }


async def set_company_ceiling(
    base_url: str,
    mgmt_key: str,
    api_key_id: str,
    monthly_limit_usd: float,
    warn_percent: int = 80,
) -> CeilingResult:
    """Set the gateway's monthly ceiling for one API key. Requires the mgmt key.

    Fail-safe: any transport/HTTP error returns ok=False with the reason rather
    than raising, so a Tier 1 provisioning failure never crashes the caller.
    """
    import httpx

    url = f"{_admin_base(base_url)}/api/usage/budget"
    body = build_budget_body(api_key_id, monthly_limit_usd, warn_percent)
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(
                url,
                json=body,
                headers={"Authorization": f"Bearer {mgmt_key}"},
            )
            resp.raise_for_status()
            data = resp.json()
    except Exception as exc:  # noqa: BLE001
        return CeilingResult(ok=False, error=f"{type(exc).__name__}: {exc}")

    budget = data.get("budget", {}) if isinstance(data, dict) else {}
    return CeilingResult(
        ok=bool(data.get("success", True)),
        monthly_limit_usd=budget.get("monthlyLimitUsd"),
        warning_threshold=budget.get("warningThreshold"),
    )
