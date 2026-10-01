"""Legacy Slack and Telegram inbound routes create nothing, whoever calls them.

An API key (or, with ``auth_enabled`` off, an ``X-Company-Id`` header) names a
company, never the human who sent the Slack or Telegram message. The legacy
schema has no verified link from a provider sender to an active NEXUS user, so
both routes fail closed: a stable 410, no body read, no row written.
"""

import logging
import uuid

import httpx
import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlmodel import SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession

from nexus import database
from nexus.auth import middleware as auth_middleware
from nexus.auth.users import DEFAULT_COMPANY_ID
from nexus.config import settings
from nexus.models.agent import Agent
from nexus.models.api_key import ApiKey
from nexus.models.company import Company

SLACK = "/api/v1/channels/slack/events"
TELEGRAM = "/api/v1/channels/telegram/webhook"
SLACK_MENTION = {
    "type": "event_callback",
    "event": {"type": "app_mention", "text": "hi", "user": "U1"},
}
TELEGRAM_TASK = {"message": {"text": "/task write the report", "chat": {"id": 7}}}
PAYLOADS = [
    (SLACK, SLACK_MENTION),
    (SLACK, {"type": "url_verification", "challenge": "abc123"}),
    (TELEGRAM, TELEGRAM_TASK),
    (TELEGRAM, {"message": {"text": "/agents", "chat": {"id": 7}}}),
    (TELEGRAM, {"message": {"text": "/status", "chat": {"id": 7}}}),
    (TELEGRAM, {"message": {"text": "/help", "chat": {"id": 7}}}),
    (TELEGRAM, {"message": {"text": "/frobnicate now", "chat": {"id": 7}}}),
]
DISABLED = {
    SLACK: {
        "detail": "Legacy Slack inbound events are disabled.",
        "code": "LEGACY_CHANNEL_INGRESS_DISABLED",
    },
    TELEGRAM: {
        "detail": "Legacy Telegram inbound commands are disabled.",
        "code": "LEGACY_CHANNEL_INGRESS_DISABLED",
    },
}


@pytest.fixture()
async def factory(tmp_path, monkeypatch):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'channels.db'}")
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    monkeypatch.setattr(database, "async_session_factory", maker)
    monkeypatch.setattr(auth_middleware, "async_session_factory", maker)  # API-key lookup
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123456:SECRET-BOT-TOKEN")
    yield maker
    await engine.dispose()


@pytest.fixture()
async def client():
    from nexus.main import app

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as c:
        yield c


async def _seed(factory) -> tuple[uuid.UUID, str]:
    """The default company, a caller company with an agent, and a caller API key."""
    caller = uuid.uuid4()
    raw_key = ApiKey.generate_key()
    async with factory() as db:
        db.add(Company(id=DEFAULT_COMPANY_ID, name="Default"))
        db.add(Company(id=caller, name="Caller Corp"))
        await db.commit()
        db.add(Agent(company_id=caller, name="SecretAgentName", role="spy", status="active"))
        db.add(
            ApiKey(
                company_id=caller,
                name="svc",
                key_prefix=ApiKey.get_prefix(raw_key),
                key_hash=ApiKey.hash_key(raw_key),
                role="admin",
            )
        )
        await db.commit()
    return caller, raw_key


async def _snapshot(factory) -> dict[str, int]:
    """Row count of every table, so any new Task/Goal/ChatTurn/... shows up."""
    async with factory() as db:
        return {
            table.name: (await db.execute(sa.select(sa.func.count()).select_from(table))).scalar()
            for table in SQLModel.metadata.sorted_tables
        }


@pytest.mark.parametrize("path, body", PAYLOADS)
async def test_an_api_key_caller_creates_nothing(factory, client, path, body):
    _, key = await _seed(factory)
    before = await _snapshot(factory)
    headers = {"Authorization": f"Bearer {key}"}

    first = await client.post(path, json=body, headers=headers)
    duplicate = await client.post(path, json=body, headers=headers)  # replayed delivery

    assert first.status_code == duplicate.status_code == 410
    assert first.json() == duplicate.json() == DISABLED[path]
    assert await _snapshot(factory) == before


@pytest.mark.parametrize("path, body", PAYLOADS)
async def test_a_forged_company_header_creates_nothing(factory, client, monkeypatch, path, body):
    """Legacy ``auth_enabled=False`` turns X-Company-Id into the principal; still no write."""
    caller, _ = await _seed(factory)
    before = await _snapshot(factory)
    monkeypatch.setattr(settings, "auth_enabled", False)

    for company in (caller, uuid.uuid4()):  # a real tenant and one that does not exist
        response = await client.post(path, json=body, headers={"X-Company-Id": str(company)})
        assert response.status_code == 410
        assert response.json() == DISABLED[path]
    assert await _snapshot(factory) == before


@pytest.mark.parametrize("path, body", PAYLOADS)
async def test_an_anonymous_request_is_refused_and_creates_nothing(factory, client, path, body):
    await _seed(factory)
    before = await _snapshot(factory)
    response = await client.post(path, json=body)
    assert response.status_code == 401
    assert response.json()["code"] == "UNAUTHENTICATED"
    assert await _snapshot(factory) == before


@pytest.mark.parametrize("path", [SLACK, TELEGRAM])
@pytest.mark.parametrize(
    "secret",
    [None, "", "wrong-secret", "123456:SECRET-BOT-TOKEN"],
    ids=["missing", "empty", "wrong", "bot-token"],
)
async def test_a_webhook_secret_never_unlocks_the_route(factory, client, path, secret):
    """A secret may authenticate the sending service; it does not identify the human."""
    _, key = await _seed(factory)
    before = await _snapshot(factory)
    headers = {"Authorization": f"Bearer {key}"}
    if secret is not None:
        headers["X-Telegram-Bot-Api-Secret-Token"] = secret

    response = await client.post(path, json=TELEGRAM_TASK, headers=headers)
    assert response.status_code == 410
    assert response.json() == DISABLED[path]
    assert await _snapshot(factory) == before


@pytest.mark.parametrize("path", [SLACK, TELEGRAM])
@pytest.mark.parametrize(
    "content",
    [
        b"{not json",
        b"",
        b'{"message": ',
        b"\xff\xfe\x00",
        b"[" * 5000 + b"]" * 5000,
        b"x" * 2_000_000,
    ],
    ids=["malformed", "empty", "truncated", "binary", "deep", "oversized"],
)
async def test_hostile_bodies_get_the_same_stable_refusal(factory, client, path, content):
    """The body is never read, so malformed, deep or huge payloads reach no parser."""
    _, key = await _seed(factory)
    before = await _snapshot(factory)
    response = await client.post(
        path,
        content=content,
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
    )
    assert response.status_code == 410
    assert response.json() == DISABLED[path]
    assert await _snapshot(factory) == before


@pytest.mark.parametrize("path, body", PAYLOADS)
async def test_the_refusal_reveals_nothing_about_the_tenant(factory, client, path, body):
    _, key = await _seed(factory)
    response = await client.post(path, json=body, headers={"Authorization": f"Bearer {key}"})
    for leaked in ("Caller Corp", "SecretAgentName", "spy", "SECRET-BOT-TOKEN", "abc123"):
        assert leaked not in response.text
    assert set(response.json()) == {"detail", "code"}


@pytest.mark.parametrize("path, body", PAYLOADS)
async def test_logs_hold_no_payload_headers_or_tokens(factory, client, caplog, path, body):
    _, key = await _seed(factory)
    payload = {**body, "leak": "message-body-canary", "username": "chat-user-canary"}
    with caplog.at_level(logging.DEBUG):
        await client.post(
            path,
            json=payload,
            headers={
                "Authorization": f"Bearer {key}",
                "X-Telegram-Bot-Api-Secret-Token": "header-secret-canary",
            },
        )
    for canary in (
        "message-body-canary",
        "chat-user-canary",
        "header-secret-canary",
        key,
        "SECRET-BOT-TOKEN",
        "write the report",
        "U1",
    ):
        assert canary not in caplog.text
    assert "Legacy channel ingress rejected" in caplog.text


async def test_only_post_is_routed_and_routes_are_marked_deprecated():
    from nexus.main import app

    schema = app.openapi()["paths"]
    for path in (SLACK, TELEGRAM):
        assert set(schema[path]) == {"post"}
        assert schema[path]["post"]["deprecated"] is True
