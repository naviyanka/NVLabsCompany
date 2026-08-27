"""An external service must be able to fire a webhook trigger, and only that.

Every other trigger route requires an authenticated company, which an external
caller does not have. This route authenticates with a per-trigger secret instead.
The tests that matter here are the negative ones: a wrong secret, an unknown
trigger and a malformed id must all be answered identically, or the endpoint
becomes a way to discover which triggers exist.
"""

from __future__ import annotations

import json
import uuid
from typing import Any
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlmodel import SQLModel, select

import nexus.models  # noqa: F401 -- registers every table on SQLModel.metadata
from nexus.api.routes import webhooks as wh
from nexus.models.agent import Agent
from nexus.models.company import Company
from nexus.models.trigger import Trigger, TriggerExecution

SECRET = "s3cret-inbound-token"


class FakeRequest:
    """Stands in for a Starlette request; only body and headers are read."""

    def __init__(self, body: bytes = b"", secret: str | None = SECRET) -> None:
        self._body = body
        self.headers = {"X-Webhook-Secret": secret} if secret is not None else {}

    async def body(self) -> bytes:
        return self._body


@pytest.fixture(autouse=True)
def fresh_rate_limits(monkeypatch: pytest.MonkeyPatch):
    """Each test gets its own rate-limit windows.

    The server instance is process-wide by design, so without this one test's
    requests would consume another's allowance.
    """
    monkeypatch.setattr(wh, "_server", None)


@pytest.fixture(autouse=True)
def stub_llm(monkeypatch: pytest.MonkeyPatch):
    """Never call a real model; record that the agent would have run."""
    calls: list[tuple[Any, ...]] = []

    async def fake_call(agent, system_prompt, message, history, **kwargs):
        calls.append((agent.id, message))
        return ("handled", "test-model", 42)

    import nexus.api.routes.chat as chat

    monkeypatch.setattr(chat, "_call_llm", fake_call)
    monkeypatch.setattr(chat, "_build_system_prompt", lambda *a, **k: "sys")
    return calls


@pytest.fixture
async def db(tmp_path):
    """A company with one agent and one webhook trigger carrying a secret."""
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'wh.db'}")
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)

    company = Company(name="Acme")
    agent = Agent(company_id=company.id, name="Responder", role="ops", model="m")
    trigger = Trigger(
        company_id=company.id,
        agent_id=agent.id,
        trigger_type="webhook",
        name="inbound-alerts",
        config={"inbound_secret": SECRET, "prompt": "Triage this alert"},
    )
    async with factory() as session:
        session.add_all([company, agent, trigger])
        await session.commit()

    yield factory, trigger, agent
    await engine.dispose()


async def executions(factory) -> list[TriggerExecution]:
    """Every execution row recorded so far."""
    async with factory() as session:
        return list((await session.execute(select(TriggerExecution))).scalars())


class TestSuccessfulIntake:
    """The happy path has to actually run the agent and record it."""

    async def test_correct_secret_fires_the_trigger(self, db, stub_llm) -> None:
        factory, trigger, agent = db
        async with factory() as session:
            response = await wh.receive_webhook(
                str(trigger.id),
                FakeRequest(body=json.dumps({"severity": "high"}).encode()),
                session,
            )

        assert response.status_code == 202
        rows = await executions(factory)
        assert len(rows) == 1
        assert rows[0].status == "success"
        assert [agent_id for agent_id, _ in stub_llm] == [agent.id]

    async def test_payload_reaches_the_agent(self, db, stub_llm) -> None:
        factory, trigger, _agent = db
        async with factory() as session:
            await wh.receive_webhook(
                str(trigger.id),
                FakeRequest(body=json.dumps({"severity": "high"}).encode()),
                session,
            )

        _, message = stub_llm[0]
        assert "Triage this alert" in message
        assert "severity" in message

    async def test_non_json_body_is_still_delivered(self, db, stub_llm) -> None:
        """A caller sending plain text should not be silently dropped."""
        factory, trigger, _agent = db
        async with factory() as session:
            response = await wh.receive_webhook(
                str(trigger.id), FakeRequest(body=b"disk full on host 3"), session
            )

        assert response.status_code == 202
        _, message = stub_llm[0]
        assert "disk full" in message


class TestRejectionsAreIndistinguishable:
    """The core security property: rejections must not leak existence."""

    async def test_wrong_secret_is_refused(self, db, stub_llm) -> None:
        factory, trigger, _agent = db
        async with factory() as session:
            response = await wh.receive_webhook(
                str(trigger.id), FakeRequest(secret="wrong"), session
            )

        assert response.status_code == 401
        assert stub_llm == [], "agent ran despite a bad secret"
        assert await executions(factory) == []

    async def test_unknown_trigger_matches_wrong_secret(self, db, stub_llm) -> None:
        factory, trigger, _agent = db
        async with factory() as session:
            unknown = await wh.receive_webhook(
                str(uuid.uuid4()), FakeRequest(), session
            )
            wrong = await wh.receive_webhook(
                str(trigger.id), FakeRequest(secret="wrong"), session
            )

        assert unknown.status_code == wrong.status_code
        assert unknown.body == wrong.body

    async def test_malformed_id_matches_wrong_secret(self, db, stub_llm) -> None:
        factory, trigger, _agent = db
        async with factory() as session:
            malformed = await wh.receive_webhook("not-a-uuid", FakeRequest(), session)
            wrong = await wh.receive_webhook(
                str(trigger.id), FakeRequest(secret="wrong"), session
            )

        assert malformed.status_code == wrong.status_code
        assert malformed.body == wrong.body

    async def test_missing_secret_header_is_refused(self, db, stub_llm) -> None:
        factory, trigger, _agent = db
        async with factory() as session:
            response = await wh.receive_webhook(
                str(trigger.id), FakeRequest(secret=None), session
            )

        assert response.status_code == 401
        assert stub_llm == []

    async def test_trigger_without_a_secret_cannot_be_fired(
        self, db, stub_llm
    ) -> None:
        """A trigger with no inbound_secret is not reachable from outside."""
        factory, trigger, agent = db
        async with factory() as session:
            open_trigger = Trigger(
                company_id=trigger.company_id,
                agent_id=agent.id,
                trigger_type="webhook",
                name="no-secret",
                config={},
            )
            session.add(open_trigger)
            await session.commit()

            response = await wh.receive_webhook(
                str(open_trigger.id), FakeRequest(secret=""), session
            )

        assert response.status_code == 401
        assert stub_llm == []

    async def test_inactive_trigger_is_refused(self, db, stub_llm) -> None:
        factory, trigger, _agent = db
        async with factory() as session:
            row = (
                await session.execute(select(Trigger).where(Trigger.id == trigger.id))
            ).scalar_one()
            row.is_active = False
            await session.commit()

            response = await wh.receive_webhook(
                str(trigger.id), FakeRequest(), session
            )

        assert response.status_code == 401
        assert stub_llm == []

    async def test_non_webhook_trigger_is_refused(self, db, stub_llm) -> None:
        """A cron trigger's secret must not make it externally firable."""
        factory, trigger, agent = db
        async with factory() as session:
            cron = Trigger(
                company_id=trigger.company_id,
                agent_id=agent.id,
                trigger_type="cron",
                name="nightly",
                config={"inbound_secret": SECRET},
            )
            session.add(cron)
            await session.commit()

            response = await wh.receive_webhook(str(cron.id), FakeRequest(), session)

        assert response.status_code == 401
        assert stub_llm == []


class TestLimits:
    """Bounds that keep a hostile caller cheap to absorb."""

    async def test_oversized_body_is_rejected(self, db, stub_llm) -> None:
        factory, trigger, _agent = db
        oversized = b"x" * (wh.MAX_BODY_BYTES + 1)
        async with factory() as session:
            response = await wh.receive_webhook(
                str(trigger.id), FakeRequest(body=oversized), session
            )

        assert response.status_code == 413
        assert stub_llm == []

    async def test_burst_is_rate_limited(self, db, stub_llm) -> None:
        factory, trigger, _agent = db
        statuses = []
        async with factory() as session:
            for _ in range(wh.PER_ENDPOINT_RATE_LIMIT + 5):
                response = await wh.receive_webhook(
                    str(trigger.id), FakeRequest(), session
                )
                statuses.append(response.status_code)

        assert 429 in statuses, "rate limit never engaged"

    async def test_unknown_ids_do_not_consume_a_real_trigger_allowance(
        self, db, stub_llm
    ) -> None:
        """Probing must not be able to starve a legitimate trigger."""
        factory, trigger, _agent = db
        async with factory() as session:
            for _ in range(wh.PER_ENDPOINT_RATE_LIMIT + 5):
                await wh.receive_webhook(str(uuid.uuid4()), FakeRequest(), session)

            response = await wh.receive_webhook(
                str(trigger.id), FakeRequest(), session
            )

        assert response.status_code == 202


class TestFailureRecording:
    """A failed run is still an execution an operator should see."""

    async def test_agent_error_records_a_failed_execution(
        self, db, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        factory, trigger, _agent = db
        import nexus.api.routes.chat as chat

        monkeypatch.setattr(
            chat, "_call_llm", AsyncMock(side_effect=RuntimeError("provider down"))
        )

        async with factory() as session:
            response = await wh.receive_webhook(
                str(trigger.id), FakeRequest(), session
            )

        assert response.status_code == 202, "the caller is not told our agent failed"
        rows = await executions(factory)
        assert len(rows) == 1
        assert rows[0].status == "failed"
        assert "provider down" in rows[0].error
