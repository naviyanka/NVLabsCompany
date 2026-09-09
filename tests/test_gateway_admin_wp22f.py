"""WP-22f / M9: Tier 1 company ceiling on the gateway.

Sets the gateway's monthly USD ceiling for the company's API key via the
management API. R1: tests invoke build_budget_body / set_company_ceiling.
R10: the HTTP call is mocked; no network. Body shape verified live against
OmniRoute 3.8.50.
"""

import httpx

from nexus.services.gateway_admin import (
    build_budget_body,
    set_company_ceiling,
)


def test_build_budget_body_converts_warn_percent_to_threshold():
    body = build_budget_body("kid-1", 120, warn_percent=80)
    assert body["apiKeyId"] == "kid-1"
    assert body["monthlyLimitUsd"] == 120
    assert body["warningThreshold"] == 0.8  # 80 -> 0.8, not 80
    assert body["resetInterval"] == "monthly"


def _mock(handler):
    transport = httpx.MockTransport(handler)
    real_init = httpx.AsyncClient.__init__

    def _init(self, *a, **k):
        k["transport"] = transport
        real_init(self, *a, **k)

    return _init


def test_set_company_ceiling_posts_to_mgmt_api(monkeypatch):
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        import json

        seen["url"] = str(request.url)
        seen["auth"] = request.headers.get("Authorization")
        seen["body"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "success": True,
                "budget": {"monthlyLimitUsd": 120, "warningThreshold": 0.8},
            },
        )

    monkeypatch.setattr(httpx.AsyncClient, "__init__", _mock(handler))

    import asyncio

    res = asyncio.run(
        set_company_ceiling(
            "http://gw:20128/v1", "mgmt-key", "kid-1", 120, warn_percent=80
        )
    )
    assert res.ok is True
    assert res.monthly_limit_usd == 120
    assert res.warning_threshold == 0.8
    # /v1 dropped, management surface under /api, mgmt key used
    assert seen["url"] == "http://gw:20128/api/usage/budget"
    assert seen["auth"] == "Bearer mgmt-key"
    assert seen["body"]["warningThreshold"] == 0.8


def test_set_company_ceiling_fails_safe_on_error(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403)  # inference key would 403 on /api/*

    monkeypatch.setattr(httpx.AsyncClient, "__init__", _mock(handler))

    import asyncio

    res = asyncio.run(
        set_company_ceiling("http://gw:20128/v1", "wrong-key", "kid-1", 120)
    )
    assert res.ok is False
    assert res.error is not None
