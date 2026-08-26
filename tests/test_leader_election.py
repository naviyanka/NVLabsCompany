"""Tests for leader election (R-02 remainder)."""

import pytest

from nexus.governance import leader_election as le


def test_noop_elects_everyone():
    election = le.NoopLeaderElection()

    @pytest.mark.asyncio
    async def check():
        assert await election.try_acquire("scheduler") is True
        await election.release("scheduler")

    import asyncio

    asyncio.run(check())


@pytest.mark.asyncio
async def test_is_leader_falls_back_to_true_on_error(monkeypatch):
    class _Exploding:
        async def try_acquire(self, name, ttl=30):
            raise RuntimeError("redis down")

    monkeypatch.setattr(le, "get_leader_election", lambda: _Exploding())
    assert await le.is_leader("scheduler") is True


@pytest.mark.asyncio
async def test_get_leader_election_solo_without_redis(monkeypatch):
    """No REDIS_URL configured -> NoopLeaderElection singleton."""
    monkeypatch.setattr(le, "_initialized", False)
    monkeypatch.setattr(le, "_election", None)

    class _FakeSettings:
        redis_url = ""

    import nexus.config as cfg

    monkeypatch.setattr(cfg, "settings", _FakeSettings())

    election = le.get_leader_election()
    assert isinstance(election, le.NoopLeaderElection)
    # Second call returns the cached instance
    assert le.get_leader_election() is election
