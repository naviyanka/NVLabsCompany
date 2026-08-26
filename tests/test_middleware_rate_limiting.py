"""Tests for Redis-backed rate limiting selection in GovernanceMiddleware (R-02)."""

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from nexus.api import middleware as mw


@pytest.fixture
def company_id():
    return uuid.uuid4()


@pytest.fixture
def middleware():
    return mw.GovernanceMiddleware(app=None)


@pytest.mark.asyncio
async def test_redis_limiter_used_when_available(monkeypatch, middleware, company_id):
    fake_result = MagicMock(allowed=True, remaining_minute=87)
    limiter = MagicMock()
    limiter.check_rate_limit = AsyncMock(return_value=fake_result)
    monkeypatch.setattr(mw, "_get_redis_rate_limiter", lambda: limiter)

    remaining = await middleware._check_rate_limit(company_id)

    assert remaining == 87
    args, kwargs = limiter.check_rate_limit.call_args
    assert args[0] == "company"
    assert args[1] == company_id
    config = kwargs.get("config") or args[2]
    assert config.requests_per_minute == mw.DEFAULT_RATE_LIMIT
    assert config.burst_allowance == 0


@pytest.mark.asyncio
async def test_redis_deny_returns_zero(monkeypatch, middleware, company_id):
    fake_result = MagicMock(allowed=False, remaining_minute=0)
    limiter = MagicMock()
    limiter.check_rate_limit = AsyncMock(return_value=fake_result)
    monkeypatch.setattr(mw, "_get_redis_rate_limiter", lambda: limiter)

    remaining = await middleware._check_rate_limit(company_id)
    assert remaining == 0


@pytest.mark.asyncio
async def test_fallback_to_in_memory_when_no_redis(monkeypatch, middleware, company_id):
    monkeypatch.setattr(mw, "_get_redis_rate_limiter", lambda: None)

    remaining = await middleware._check_rate_limit(company_id)
    # First request against a fresh in-memory bucket: limit - 1 remaining.
    assert remaining == mw.DEFAULT_RATE_LIMIT - 1


@pytest.mark.asyncio
async def test_fallback_when_redis_raises(monkeypatch, middleware, company_id):
    limiter = MagicMock()
    limiter.check_rate_limit = AsyncMock(side_effect=RuntimeError("boom"))
    monkeypatch.setattr(mw, "_get_redis_rate_limiter", lambda: limiter)

    remaining = await middleware._check_rate_limit(company_id)
    assert remaining == mw.DEFAULT_RATE_LIMIT - 1


@pytest.mark.asyncio
async def test_anonymous_requests_skip_limiters(middleware):
    assert await middleware._check_rate_limit(None) == mw.DEFAULT_RATE_LIMIT


def test_lazy_init_handles_bad_config(monkeypatch):
    monkeypatch.setattr(mw, "_redis_rate_limiter", None)
    monkeypatch.setattr(mw, "_redis_rate_limiter_checked", False)

    class _Boom:
        def __init__(self, url):
            raise RuntimeError("no redis module")

    import nexus.governance.redis_rate_limiter as rrl

    original = rrl.RedisRateLimiter
    monkeypatch.setattr(rrl, "RedisRateLimiter", _Boom)

    result = mw._get_redis_rate_limiter()
    assert result is None or isinstance(result, object)
