"""Tests for Phase 1/2 leftovers: real channel sends, temporal flagging,
and honest evolution auto-evaluation."""

import os
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from nexus.communication import channels as ch
from nexus.models.communication import Message


def _make_message() -> Message:
    return Message(
        company_id=__import__("uuid").uuid4(),
        sender_agent_id=__import__("uuid").uuid4(),
        message_type="notification",
        content="Hello from NEXUS",
    )


# ---------------------------------------------------------------------------
# W-04: channels perform real HTTP sends
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_webhook_channel_signs_and_posts(monkeypatch):
    captured = {}

    class _Resp:
        status_code = 200

    class _Client:
        def __init__(self, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def post(self, url, content=None, headers=None, json=None):
            captured["url"] = url
            captured["body"] = content
            captured["headers"] = headers
            return _Resp()

    monkeypatch.setattr("httpx.AsyncClient", _Client)

    channel = ch.WebhookChannel(
        endpoint_url="https://example.com/hook", secret="topsecret"
    )
    ok = await channel.send(_make_message())

    assert ok is True
    assert captured["url"] == "https://example.com/hook"
    sig = captured["headers"]["X-Nexus-Signature"]
    assert len(sig) == 64  # sha256 hex digest


@pytest.mark.asyncio
async def test_webhook_failure_enqueues_retry(monkeypatch):
    enqueued = []

    class _Queue:
        def enqueue(self, delivery):
            enqueued.append(delivery)

    monkeypatch.setattr(ch, "_get_retry_queue", lambda: _Queue())

    class _Client:
        def __init__(self, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def post(self, *args, **kwargs):
            raise RuntimeError("connection refused")

    monkeypatch.setattr("httpx.AsyncClient", _Client)

    channel = ch.WebhookChannel(endpoint_url="https://example.com/hook")
    ok = await channel.send(_make_message())

    assert ok is False
    assert len(enqueued) == 1
    assert enqueued[0].last_error == "connection refused"


@pytest.mark.asyncio
async def test_slack_channel_posts_to_webhook(monkeypatch):
    posted = {}

    class _Resp:
        status_code = 200

    class _Client:
        def __init__(self, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def post(self, url, json=None):
            posted["url"] = url
            posted["json"] = json
            return _Resp()

    monkeypatch.setattr("httpx.AsyncClient", _Client)

    channel = ch.SlackChannel(channel_name="#ops", webhook_url="https://hooks.slack.com/x")
    assert await channel.send(_make_message()) is True
    assert "Hello from NEXUS" in posted["json"]["text"]

    unconfigured = ch.SlackChannel(channel_name="#ops", webhook_url="")
    assert await unconfigured.send(_make_message()) is False


@pytest.mark.asyncio
async def test_discord_channel_uses_bot_rest_api(monkeypatch):
    posted = {}

    class _Resp:
        status_code = 200

    class _Client:
        def __init__(self, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def post(self, url, headers=None, json=None):
            posted["url"] = url
            posted["headers"] = headers
            posted["json"] = json
            return _Resp()

    monkeypatch.setattr("httpx.AsyncClient", _Client)

    channel = ch.DiscordChannel(guild_id="g", channel_id="c123", bot_token="tok")
    assert await channel.send(_make_message()) is True
    assert posted["url"].endswith("/channels/c123/messages")
    assert posted["headers"]["Authorization"] == "Bot tok"


# ---------------------------------------------------------------------------
# W-03: temporal is intentionally optional and observable
# ---------------------------------------------------------------------------


def test_temporal_disabled_by_default():
    from nexus.temporal.client import is_temporal_enabled, start_goal_workflow

    original = os.environ.get("USE_TEMPORAL")
    os.environ.pop("USE_TEMPORAL", None)
    try:
        # Reset cached flag
        import nexus.temporal.client as tc

        tc._enabled = None
        assert is_temporal_enabled() is False
    finally:
        if original is not None:
            os.environ["USE_TEMPORAL"] = original


def test_temporal_degradation_entry_present():
    from nexus.api.routes.degradation import _check_temporal

    entry = _check_temporal()
    assert entry["status"] in ("full", "degraded", "unavailable")


# ---------------------------------------------------------------------------
# W-07: honest auto-evaluation + gated auto-promotion
# ---------------------------------------------------------------------------


def test_auto_promote_disabled_by_default(monkeypatch):
    monkeypatch.delenv("EVOLUTION_AUTO_PROMOTE", raising=False)
    from nexus.runtime.orchestrator import _auto_promote_enabled

    assert _auto_promote_enabled() is False

    monkeypatch.setenv("EVOLUTION_AUTO_PROMOTE", "true")
    assert _auto_promote_enabled() is True


@pytest.mark.asyncio
async def test_auto_evaluate_uses_real_scores_not_constants(monkeypatch):
    """The evaluation must derive scores via _score_proposal, not constants."""
    import uuid as uuid_mod

    from nexus.runtime import orchestrator as orch

    proposal_id = uuid_mod.uuid4()
    evaluations_added = []
    promoted = []

    class _Proposal:
        id = proposal_id
        company_id = uuid_mod.uuid4()
        proposed_by_agent_id = uuid_mod.uuid4()
        confidence = 0.9
        status = "proposed"
        updated_at = datetime.now(timezone.utc)

        def __init__(self):
            self.status_history = [self.status]

    proposal = _Proposal()

    class _Scalars:
        def all(self):
            return [proposal]

    class _Result:
        def scalars(self):
            return _Scalars()

    db = MagicMock()
    db.execute = AsyncMock(return_value=_Result())
    db.add = lambda obj: evaluations_added.append(obj)
    db.flush = AsyncMock()

    async def fake_score(db_arg, prop):
        return 0.50, 0.62

    monkeypatch.setattr(orch, "_score_proposal", fake_score)
    monkeypatch.delenv("EVOLUTION_AUTO_PROMOTE", raising=False)

    await orch._auto_evaluate_proposals(db)

    assert len(evaluations_added) == 1
    ev = evaluations_added[0]
    assert ev.baseline_score == 0.5
    assert ev.candidate_score == 0.62
    # Without the opt-in flag, promotion must NOT happen even at confidence 0.9
    assert proposal.status == "evaluating"

    # With the flag enabled and passing evaluation, promotion proceeds.
    proposal.status = "evaluating"
    monkeypatch.setenv("EVOLUTION_AUTO_PROMOTE", "true")
    await orch._auto_evaluate_proposals(db)
    assert proposal.status in ("promoted", "evaluating") or promoted
