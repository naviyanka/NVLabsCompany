"""Tests for IdempotencyMiddleware (F3)."""

import asyncio
import json
import uuid
import pytest
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, StreamingResponse
from starlette.routing import Route
from starlette.testclient import TestClient
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from nexus.api.idempotency_middleware import IdempotencyMiddleware
from nexus.auth.principal import Principal
from nexus.database import engine
from nexus.models.company import Company
from nexus.models.idempotency import IdempotencyRecord
from sqlmodel import SQLModel

call_count = 0

async def sample_endpoint(request: Request):
    global call_count
    call_count += 1
    data = await request.json()
    return JSONResponse({"status": "created", "echo": data.get("name"), "count": call_count}, status_code=201)

async def sample_stream(request: Request):
    global call_count
    call_count += 1

    async def events():
        await asyncio.sleep(0)  # a real stream awaits the DB before its first event
        yield "data: one\n\n"
        yield "data: two\n\n"

    return StreamingResponse(events(), media_type="text/event-stream")


routes = [
    Route("/api/v1/test/resource", sample_endpoint, methods=["POST"]),
    Route("/api/v1/test/stream", sample_stream, methods=["POST"]),
    Route("/api/v1/agents/{agent_id}/chat/stream", sample_stream, methods=["POST"]),
]

class FakeAuthMiddleware:
    def __init__(self, app: ASGIApp, principal: Principal) -> None:
        self.app = app
        self.principal = principal

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http":
            scope.setdefault("state", {})["principal"] = self.principal
        await self.app(scope, receive, send)

@pytest.fixture(autouse=True)
async def init_tables():
    global call_count
    call_count = 0
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all, tables=[Company.__table__, IdempotencyRecord.__table__])

def create_app(principal: Principal):
    app = Starlette(routes=routes)
    # Starlette wraps middlewares in reverse order:
    # Outer FakeAuthMiddleware runs first and injects scope["principal"],
    # then IdempotencyMiddleware runs and accesses the principal.
    app.add_middleware(IdempotencyMiddleware)
    app.add_middleware(FakeAuthMiddleware, principal=principal)
    return app

def test_idempotent_request_replays_cached_response():
    cid = uuid.uuid4()
    p = Principal(kind="user", company_id=cid, role="admin", email="test@nvlabs.com")
    app = create_app(p)
    client = TestClient(app)

    idem_key = f"key-{uuid.uuid4()}"
    headers = {"Idempotency-Key": idem_key}
    payload = {"name": "Test Item"}

    # First call
    resp1 = client.post("/api/v1/test/resource", headers=headers, json=payload)
    assert resp1.status_code == 201
    body1 = resp1.json()
    assert body1["count"] == 1
    assert "Idempotent-Replay" not in resp1.headers

    # Duplicate call with same key and body
    resp2 = client.post("/api/v1/test/resource", headers=headers, json=payload)
    assert resp2.status_code == 201
    body2 = resp2.json()
    assert body2["count"] == 1  # Handler was NOT executed again!
    assert resp2.headers.get("Idempotent-Replay") == "true"

def test_idempotency_key_reuse_with_different_body_is_rejected():
    cid = uuid.uuid4()
    p = Principal(kind="user", company_id=cid, role="admin", email="test@nvlabs.com")
    app = create_app(p)
    client = TestClient(app)

    idem_key = f"key-{uuid.uuid4()}"
    headers = {"Idempotency-Key": idem_key}

    resp1 = client.post("/api/v1/test/resource", headers=headers, json={"name": "Item A"})
    assert resp1.status_code == 201

    # Same key, different body
    resp2 = client.post("/api/v1/test/resource", headers=headers, json={"name": "Item B"})
    assert resp2.status_code == 422
    assert resp2.json()["code"] == "IDEMPOTENCY_KEY_REUSED"


def test_streaming_response_with_key_is_not_cut_off():
    """The client is still connected after the body: a stream must not see a disconnect."""
    p = Principal(kind="user", company_id=uuid.uuid4(), role="admin", email="test@nvlabs.com")
    app = create_app(p)

    async def as_uvicorn(scope: Scope, receive: Receive, send: Send) -> None:
        # uvicorn says ASGI 2.3, so StreamingResponse watches receive() for a
        # disconnect (TestClient says 2.4, which skips that).
        await app({**scope, "asgi": {"version": "3.0", "spec_version": "2.3"}}, receive, send)

    client = TestClient(as_uvicorn)

    resp = client.post("/api/v1/test/stream", headers={"Idempotency-Key": f"key-{uuid.uuid4()}"}, json={})
    assert resp.status_code == 200
    assert resp.text == "data: one\n\ndata: two\n\n"


def test_chat_turn_routes_bypass_the_generic_cache():
    """Chat turn POSTs dedupe on ChatTurn.idempotency_key and re-attach on retry.

    The generic cache would answer a retry with 409 while the stream runs, or
    with an empty cached body after it ends.
    """
    p = Principal(kind="user", company_id=uuid.uuid4(), role="admin", email="test@nvlabs.com")
    client = TestClient(create_app(p))
    headers = {"Idempotency-Key": f"key-{uuid.uuid4()}"}

    first = client.post(f"/api/v1/agents/{uuid.uuid4()}/chat/stream", headers=headers, json={"prompt": "hi"})
    retry = client.post(f"/api/v1/agents/{uuid.uuid4()}/chat/stream", headers=headers, json={"prompt": "hi"})
    assert first.status_code == retry.status_code == 200
    assert retry.text == "data: one\n\ndata: two\n\n"
    assert "Idempotent-Replay" not in retry.headers
    # The route saw both requests; its own turn table decides what is a duplicate.
    assert call_count == 2
