"""Idempotency middleware for mutating requests (WP-1 / F3)."""

import hashlib
import json
import logging
import uuid
from datetime import datetime, timedelta, timezone
from starlette.datastructures import Headers
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send
from sqlalchemy import select, delete
from sqlalchemy.exc import IntegrityError

from nexus.auth.middleware import get_principal_from_scope
from nexus.database import async_session_factory
from nexus.models.idempotency import IdempotencyRecord

logger = logging.getLogger(__name__)

MUTATING_METHODS = {"POST", "PUT", "PATCH", "DELETE"}
MAX_BODY_CACHE_BYTES = 256 * 1024  # 256 KB


def _canonical_json_hash(body_bytes: bytes) -> str:
    """Compute sha256 of canonical JSON payload or raw bytes."""
    try:
        data = json.loads(body_bytes)
        canonical = json.dumps(data, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return hashlib.sha256(canonical).hexdigest()
    except Exception:
        return hashlib.sha256(body_bytes).hexdigest()


class IdempotencyMiddleware:
    """ASGI middleware providing end-to-end request idempotency."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        method = scope.get("method", "GET").upper()
        if method not in MUTATING_METHODS:
            await self.app(scope, receive, send)
            return

        headers = Headers(scope=scope)
        idem_key = headers.get("idempotency-key") or headers.get("x-idempotency-key")
        if not idem_key:
            await self.app(scope, receive, send)
            return

        principal = get_principal_from_scope(scope)
        company_id = principal.company_id if principal else None
        if not company_id:
            await self.app(scope, receive, send)
            return

        # Read the entire body
        full_body = b""
        while True:
            msg = await receive()
            if msg["type"] == "http.request":
                full_body += msg.get("body", b"")
                if not msg.get("more_body", False):
                    break

        body_hash = _canonical_json_hash(full_body)
        endpoint = scope.get("path", "")
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        expires_at = now + timedelta(hours=24)

        # 1. Query if record exists
        async with async_session_factory() as session:
            stmt = select(IdempotencyRecord).where(
                IdempotencyRecord.company_id == company_id,
                IdempotencyRecord.idem_key == idem_key,
            )
            res = await session.execute(stmt)
            existing = res.scalars().first()

            if existing:
                # Check if an expired in_flight row can be reclaimed
                if existing.state == "in_flight" and existing.expires_at <= now:
                    await session.delete(existing)
                    await session.commit()
                    existing = None
                else:
                    if existing.request_hash != body_hash:
                        resp = JSONResponse(
                            status_code=422,
                            content={
                                "code": "IDEMPOTENCY_KEY_REUSED",
                                "detail": "Idempotency key already used for a different request payload",
                            },
                        )
                        await resp(scope, receive, send)
                        return

                    if existing.state == "in_flight":
                        resp = JSONResponse(
                            status_code=409,
                            content={
                                "code": "REQUEST_IN_FLIGHT",
                                "detail": "A request with this idempotency key is currently processing",
                            },
                            headers={"Retry-After": "2"},
                        )
                        await resp(scope, receive, send)
                        return

                    if existing.state == "complete" and existing.status_code is not None:
                        try:
                            content = json.loads(existing.response_body) if existing.response_body else {}
                        except Exception:
                            content = {"message": existing.response_body or ""}
                        resp = JSONResponse(
                            status_code=existing.status_code,
                            content=content,
                            headers={"Idempotent-Replay": "true"},
                        )
                        await resp(scope, receive, send)
                        return

            # Insert in_flight record
            try:
                record = IdempotencyRecord(
                    company_id=company_id,
                    idem_key=idem_key,
                    endpoint=endpoint,
                    request_hash=body_hash,
                    state="in_flight",
                    created_at=now,
                    expires_at=expires_at,
                )
                session.add(record)
                await session.commit()
            except IntegrityError:
                await session.rollback()
                resp = JSONResponse(
                    status_code=409,
                    content={
                        "code": "REQUEST_IN_FLIGHT",
                        "detail": "A request with this idempotency key is currently processing",
                    },
                    headers={"Retry-After": "2"},
                )
                await resp(scope, receive, send)
                return

        # Prepare stream for app
        body_sent = False
        async def replay_receive() -> Message:
            nonlocal body_sent
            if not body_sent:
                body_sent = True
                return {"type": "http.request", "body": full_body, "more_body": False}
            return {"type": "http.disconnect"}

        response_status = 500
        response_headers: dict[bytes, bytes] = {}
        response_body_bytes = b""
        handler_crashed = True

        async def capture_send(message: Message) -> None:
            nonlocal response_status, response_headers, response_body_bytes
            if message["type"] == "http.response.start":
                response_status = message.get("status", 200)
                raw_headers = message.get("headers", [])
                response_headers = {k.lower(): v for k, v in raw_headers}
            elif message["type"] == "http.response.body":
                # Only capture up to limit and don't buffer streaming event-stream
                if response_headers.get(b"content-type", b"").startswith(b"text/event-stream"):
                    pass
                elif len(response_body_bytes) < MAX_BODY_CACHE_BYTES:
                    chunk = message.get("body", b"")
                    response_body_bytes += chunk[: MAX_BODY_CACHE_BYTES - len(response_body_bytes)]
            await send(message)

        try:
            await self.app(scope, replay_receive, capture_send)
            handler_crashed = False
        finally:
            async with async_session_factory() as session:
                stmt = select(IdempotencyRecord).where(
                    IdempotencyRecord.company_id == company_id,
                    IdempotencyRecord.idem_key == idem_key,
                )
                res = await session.execute(stmt)
                rec = res.scalars().first()
                if rec:
                    # If handler crashed or returned 5xx, delete row to allow client retry
                    if handler_crashed or response_status >= 500 or response_status < 200:
                        await session.delete(rec)
                        await session.commit()
                    elif 200 <= response_status < 300:
                        # Only persist complete on 2xx
                        rec.state = "complete"
                        rec.status_code = response_status
                        # Skip buffering if streaming
                        is_streaming = response_headers.get(b"content-type", b"").startswith(b"text/event-stream")
                        if is_streaming or len(response_body_bytes) >= MAX_BODY_CACHE_BYTES:
                            rec.response_body = None
                        else:
                            try:
                                rec.response_body = response_body_bytes.decode("utf-8")
                            except Exception:
                                rec.response_body = None
                        session.add(rec)
                        await session.commit()
                    else:
                        # 4xx (client error): delete so client can retry with corrected request
                        await session.delete(rec)
                        await session.commit()
