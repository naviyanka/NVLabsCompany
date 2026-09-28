"""Inbound Slack and Telegram webhooks write only into the caller's company.

Neither payload carries a tenant, and there is no installation table mapping a
Slack workspace or a Telegram bot to a company. The tenant is the company of the
credential the request arrives with. A request without one is refused, never
assigned to the default or the oldest company.
"""

import uuid

import httpx
import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlmodel import SQLModel, select
from sqlmodel.ext.asyncio.session import AsyncSession

from nexus import database
from nexus.auth.users import DEFAULT_COMPANY_ID
from nexus.config import settings
from nexus.models.company import Company
from nexus.models.task import Task

SLACK = "/api/v1/channels/slack/events"
TELEGRAM = "/api/v1/channels/telegram/webhook"
SLACK_MENTION = {
    "type": "event_callback",
    "event": {"type": "app_mention", "text": "hi", "user": "U1"},
}
TELEGRAM_TASK = {"message": {"text": "/task write the report", "chat": {"id": 7}}}


@pytest.fixture()
async def factory(tmp_path, monkeypatch):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'channels.db'}")
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    monkeypatch.setattr(database, "async_session_factory", maker)
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)  # no outbound replies
    yield maker
    await engine.dispose()


@pytest.fixture()
async def client():
    from nexus.main import app

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as c:
        yield c


async def _companies(factory) -> tuple[uuid.UUID, uuid.UUID]:
    """The seeded default company and a second tenant, which is the caller."""
    other = uuid.uuid4()
    async with factory() as db:
        db.add(Company(id=DEFAULT_COMPANY_ID, name="Default"))
        db.add(Company(id=other, name="Caller"))
        await db.commit()
    return DEFAULT_COMPANY_ID, other


async def _tasks(factory) -> list[tuple[uuid.UUID, str]]:
    async with factory() as db:
        return [(t.company_id, t.title) for t in (await db.exec(select(Task))).all()]


@pytest.mark.parametrize("auth_enabled", [True, False])
@pytest.mark.parametrize("path, body", [(SLACK, SLACK_MENTION), (TELEGRAM, TELEGRAM_TASK)])
async def test_a_request_without_a_credential_is_refused(
    factory, client, monkeypatch, auth_enabled, path, body
):
    await _companies(factory)
    monkeypatch.setattr(settings, "auth_enabled", auth_enabled)
    response = await client.post(path, json=body)
    assert response.status_code == 401
    assert await _tasks(factory) == []


@pytest.mark.parametrize(
    "path, body, title",
    [
        (SLACK, SLACK_MENTION, "Slack mention from U1"),
        (TELEGRAM, TELEGRAM_TASK, "write the report"),
    ],
)
async def test_the_task_lands_in_the_callers_company(
    factory, client, monkeypatch, path, body, title
):
    default, caller = await _companies(factory)
    # Legacy mode turns X-Company-Id into the principal; with auth on, an API key does.
    monkeypatch.setattr(settings, "auth_enabled", False)
    response = await client.post(path, json=body, headers={"X-Company-Id": str(caller)})
    assert response.status_code == 200
    assert await _tasks(factory) == [(caller, title)]
