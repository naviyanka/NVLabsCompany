"""Shared voice state: consume-once tickets, shared limits and revocation across workers.

Two ``RedisStore`` instances over one fake Redis server stand in for two API workers.
"""

from __future__ import annotations

import asyncio
import uuid

import fakeredis
import jwt
import pytest

from nexus.config import settings
from nexus.voice import shared_state
from nexus.voice.shared_state import (
    MemoryStore,
    RedisStore,
    SharedStateUnavailableError,
    get_store,
)

# Reuse the gateway test harness (fake worker, seeded tenants, WebSocket helpers).
from tests.test_voice_gateway import (  # noqa: F401
    TestSocketAuth,
    client,
    new_session,
    world,
)

pytestmark = pytest.mark.core_employee

COMPANY, OTHER, USER = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()


def workers(n=2):
    server = fakeredis.FakeServer()
    return [RedisStore(fakeredis.FakeAsyncRedis(server=server)) for _ in range(n)]


async def test_exactly_one_worker_redeems_a_ticket():
    a, b = workers()
    results = await asyncio.gather(
        *[(a if i % 2 else b).redeem(COMPANY, "jti-1", 30) for i in range(20)]
    )
    assert results.count(True) == 1


async def test_redemption_expires_with_the_ticket_and_is_per_tenant():
    a, b = workers()
    assert await a.redeem(COMPANY, "j", 30)
    ttl = await a.r.ttl(f"tenant:{COMPANY}:voice:ticket:j")
    assert 0 < ttl <= 30
    assert not await b.redeem(COMPANY, "j", 30)
    assert await b.redeem(OTHER, "j", 30)  # same jti in another tenant is a different key


async def test_rate_limits_are_shared_per_user_and_per_company(monkeypatch):
    monkeypatch.setattr(settings, "voice_utterances_per_minute", 3)
    monkeypatch.setattr(settings, "voice_company_utterances_per_minute", 5)
    a, b = workers()
    user_results = [await (a if i % 2 else b).allow("utterance", COMPANY, USER) for i in range(5)]
    assert user_results == [True, True, True, False, False]  # per-user cap across both workers
    a, b = workers()
    users = [uuid.uuid4() for _ in range(7)]
    company = [
        await (a if i % 2 else b).allow("utterance", COMPANY, u) for i, u in enumerate(users)
    ]
    assert company == [True] * 5 + [False] * 2  # per-company cap across both workers
    assert await b.allow("utterance", OTHER, USER)  # another company is unaffected


async def test_revocation_is_visible_to_every_worker():
    a, b = workers()
    assert not await b.revoked(COMPANY, "s1")
    await a.revoke(COMPANY, "s1")
    assert await b.revoked(COMPANY, "s1")
    assert not await b.revoked(OTHER, "s1")


class BrokenRedis:
    async def ping(self):
        raise OSError("down")

    def pipeline(self, **_):
        class Pipe:
            def incr(self, *a):
                pass

            expire = incr

            async def execute(self):
                raise OSError("down")

        return Pipe()

    def __getattr__(self, name):
        def boom(*a, **k):
            async def fail():
                raise OSError("down")

            return fail()

        return boom


async def test_redis_errors_fail_closed():
    store = RedisStore(BrokenRedis())
    for call in (
        store.redeem(COMPANY, "j", 30),
        store.allow("session", COMPANY, USER),
        store.revoked(COMPANY, "s"),
    ):
        with pytest.raises(SharedStateUnavailableError):
            await call


class App:
    class state:  # noqa: N801
        pass

    def __init__(self):
        self.state = type("S", (), {})()


async def test_get_store_fails_closed_unless_local_state_is_explicit(monkeypatch):
    import redis.asyncio as aioredis

    monkeypatch.setattr(aioredis, "from_url", lambda *a, **k: BrokenRedis())
    monkeypatch.setattr(settings, "voice_allow_local_state", False)
    with pytest.raises(SharedStateUnavailableError):
        await get_store(App())
    monkeypatch.setattr(settings, "voice_allow_local_state", True)
    store = await get_store(App())
    assert isinstance(store, MemoryStore) and store.shared is False


async def test_get_store_uses_redis_when_reachable(monkeypatch):
    import redis.asyncio as aioredis

    server = fakeredis.FakeServer()
    monkeypatch.setattr(
        aioredis, "from_url", lambda *a, **k: fakeredis.FakeAsyncRedis(server=server)
    )
    app = App()
    store = await get_store(app)
    assert isinstance(store, RedisStore) and await get_store(app) is store


def test_shared_state_module_is_the_only_store_interface():
    assert hasattr(shared_state, "get_store")


def _jti(ticket: str) -> str:
    return jwt.decode(ticket, options={"verify_signature": False, "verify_aud": False})["jti"]


class TestGatewayUsesSharedState:
    harness = TestSocketAuth()

    def test_ticket_redeemed_on_another_worker_is_refused(self, client, world):  # noqa: F811
        server = fakeredis.FakeServer()
        worker_a = RedisStore(fakeredis.FakeAsyncRedis(server=server))
        worker_b = RedisStore(fakeredis.FakeAsyncRedis(server=server))
        client.voice_app.state.voice_store = worker_b
        session = new_session(client).json()
        ticket = session["ticket"]
        assert asyncio.run(worker_a.redeem(world.ids["acme"], _jti(ticket), 30))
        assert self.harness.close_reason(client, ticket)["code"] == "BAD_TICKET"

    def test_revoked_session_cannot_connect(self, client, world):  # noqa: F811
        store = RedisStore(fakeredis.FakeAsyncRedis(server=fakeredis.FakeServer()))
        client.voice_app.state.voice_store = store
        session = new_session(client).json()
        assert (
            client.delete(
                f"/api/v1/voice/sessions/{session['voice_session_id']}", headers={"x-who": "acme"}
            ).status_code
            == 204
        )
        assert self.harness.close_reason(client, session["ticket"])["code"] == "BAD_TICKET"

    def test_unavailable_shared_state_fails_closed(self, client):  # noqa: F811
        client.voice_app.state.voice_store = RedisStore(BrokenRedis())
        assert new_session(client).status_code == 503
