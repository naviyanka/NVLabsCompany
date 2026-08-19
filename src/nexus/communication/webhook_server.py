"""WebhookServer - production-grade inbound HTTP handler for external integrations.

Provides per-endpoint secret gating (constant-time comparison), fixed-window rate
limiting, body size cap, JSON schema validation, and capability token lookup.

Security properties:
- Secret comparison uses hmac.compare_digest for constant-time safety.
- Unknown endpoint IDs are answered identically to wrong secrets (no enumeration).
- A decoy secret comparison runs for unknown endpoints so timing is identical.
- Secrets never appear in responses or dispatch data.
- Body size cap (1MB) enforced BEFORE parsing.
- Global rate limit (120/min) + per-endpoint rate limit (60/min) with fixed windows.
- Unknown endpoints share a single rate-limit bucket (:unknown).
"""

import hmac
import json
import secrets
import time
from collections.abc import Callable
from typing import Any

import jsonschema

from nexus.communication.webhook_types import (
    WebhookDispatch,
    WebhookEndpoint,
    WebhookInbound,
    WebhookTaskStatus,
)

# --- Constants ---

MAX_BODY_BYTES: int = 1_048_576  # 1 MB
"""Reject bodies larger than this before parsing."""

RATE_LIMIT: int = 120
"""Global rate limit: max requests per window."""

PER_ENDPOINT_RATE_LIMIT: int = 60
"""Per-endpoint rate limit: max requests per window for a single endpoint."""

RATE_WINDOW_MS: int = 60_000
"""Rate limit window in milliseconds (1 minute)."""

LEGACY_ENDPOINT_ID: str = "legacy"
"""Bare POST / maps to this endpoint id for backwards compatibility."""

UNKNOWN_BUCKET: str = ":unknown"
"""Rate-limit bucket shared by all unknown endpoint IDs."""


class WebhookServer:
    """Inbound webhook HTTP handler with secret gating, rate limiting, and schema validation.

    Manages multiple endpoints, each with its own secret and optional JSON schema.
    Provides constant-time secret comparison and identical responses for unknown
    endpoints to prevent enumeration attacks.
    """

    def __init__(
        self,
        endpoints: list[WebhookEndpoint],
        on_message: Callable[[WebhookInbound, dict[str, str]], WebhookDispatch | None],
        lookup_status: Callable[[str], WebhookTaskStatus | None],
    ) -> None:
        """Initialize the webhook server.

        Args:
            endpoints: List of endpoint configurations to serve.
            on_message: Callback invoked with (inbound, endpoint_ref) when a valid
                POST arrives. endpoint_ref contains only 'id' and 'name' (never
                the secret). Returns a WebhookDispatch or None on failure.
            lookup_status: Callback to resolve a capability token to its task status.
                Returns None when the token maps to nothing.
        """
        self._on_message = on_message
        self._lookup_status = lookup_status
        self._decoy_secret: str = secrets.token_hex(32)
        self._endpoints: dict[str, WebhookEndpoint] = {}
        self._windows: dict[str, dict[str, Any]] = {}
        self.set_endpoints(endpoints)

    def set_endpoints(self, endpoints: list[WebhookEndpoint]) -> None:
        """Swap the served endpoint list without restarting the server.

        Rebuilds the internal map wholesale so a removed id stops resolving
        on the very next request.

        Args:
            endpoints: New list of endpoint configurations.
        """
        next_map: dict[str, WebhookEndpoint] = {}
        for ep in endpoints:
            if ep.id and ep.secret and ep.enabled:
                next_map[ep.id] = ep
        self._endpoints = next_map
        # Drop rate-limit state for ids we no longer serve; keep global and unknown
        # buckets so a swap cannot be used to reset an in-flight flood.
        keys_to_drop = [
            key
            for key in self._windows
            if key != "" and key != UNKNOWN_BUCKET and key not in next_map
        ]
        for key in keys_to_drop:
            del self._windows[key]

    def verify_secret(self, provided: str, endpoint: WebhookEndpoint | None) -> bool:
        """Constant-time secret comparison using hmac.compare_digest.

        When endpoint is None (unknown id), the comparison still runs against
        the decoy secret so timing is identical, then returns False unconditionally.

        Args:
            provided: The secret string provided by the caller.
            endpoint: The endpoint configuration, or None for unknown endpoints.

        Returns:
            True only if provided matches the endpoint's secret and endpoint is not None.
        """
        expected = endpoint.secret if endpoint is not None else self._decoy_secret
        # hmac.compare_digest handles strings directly in constant time
        equal = hmac.compare_digest(provided, expected)
        # For unknown endpoints, always return False regardless of comparison result
        if endpoint is None:
            return False
        return equal

    def allow_request(self, bucket: str, limit: int) -> bool:
        """Fixed-window rate limiter.

        Bounds total work before any parse or crypto runs. Each bucket tracks
        a window start time and a request count within that window.

        Args:
            bucket: The rate limit bucket identifier ('' for global, endpoint id,
                or UNKNOWN_BUCKET for unknown endpoints).
            limit: Maximum number of requests allowed per window.

        Returns:
            True if the request is within the rate limit, False otherwise.
        """
        now_ms = int(time.time() * 1000)
        window = self._windows.get(bucket)
        if window is None or now_ms - window["start"] > RATE_WINDOW_MS:
            self._windows[bucket] = {"start": now_ms, "count": 1}
            return True
        window["count"] += 1
        return window["count"] <= limit

    def handle_post(
        self,
        endpoint_id: str,
        headers: dict[str, str],
        body: bytes,
    ) -> dict[str, Any]:
        """Handle an inbound POST request through the full pipeline.

        Pipeline: global rate limit -> per-endpoint rate limit -> verify secret ->
        validate body size -> parse JSON -> validate schema -> extract inbound ->
        call on_message.

        If endpoint_id is empty or None, it is mapped to LEGACY_ENDPOINT_ID for
        backwards-compatible bare-POST handling.

        Args:
            endpoint_id: The endpoint identifier from the request path.
            headers: Request headers (expects 'x-md-webhook-secret').
            body: Raw request body bytes.

        Returns:
            Dict with 'status_code' and 'body' keys representing the HTTP response.
        """
        # Map empty/None endpoint_id to the legacy endpoint for bare-POST compat.
        if not endpoint_id:
            endpoint_id = LEGACY_ENDPOINT_ID

        # Global rate limit first - cheapest rejection
        if not self.allow_request("", RATE_LIMIT):
            return {"status_code": 429, "body": {"ok": False, "error": "rate limited"}}

        endpoint = self._endpoints.get(endpoint_id)

        # Per-endpoint rate limit (unknown endpoints share one bucket)
        bucket = endpoint.id if endpoint else UNKNOWN_BUCKET
        if not self.allow_request(bucket, PER_ENDPOINT_RATE_LIMIT):
            return {"status_code": 429, "body": {"ok": False, "error": "rate limited"}}

        # Verify secret - runs constant-time comparison even for unknown endpoints
        provided_secret = headers.get("x-md-webhook-secret", "")
        if not provided_secret or not self.verify_secret(provided_secret, endpoint):
            return {"status_code": 401, "body": {"ok": False, "error": "unauthorized"}}

        # Body size cap enforced BEFORE parsing
        if len(body) > MAX_BODY_BYTES:
            return {"status_code": 413, "body": {"ok": False, "error": "too large"}}

        # Parse JSON
        try:
            parsed = json.loads(body)
        except (json.JSONDecodeError, UnicodeDecodeError):
            return {"status_code": 400, "body": {"ok": False, "error": "bad json"}}

        if not isinstance(parsed, dict):
            return {"status_code": 400, "body": {"ok": False, "error": "bad json"}}

        # Validate against endpoint schema
        assert endpoint is not None  # guaranteed by verify_secret returning True
        schema_error = _validate_schema(parsed, endpoint.schema_)
        if schema_error is not None:
            return {"status_code": 400, "body": {"ok": False, "error": schema_error}}

        # Extract message (always required regardless of schema)
        message = parsed.get("message", "")
        if not isinstance(message, str) or not message.strip():
            return {"status_code": 400, "body": {"ok": False, "error": "message required"}}

        # Build WebhookInbound
        inbound_data: dict[str, Any] = {"message": message.strip()}
        title = parsed.get("title")
        if isinstance(title, str) and title.strip():
            inbound_data["title"] = title.strip()
        kind = parsed.get("kind")
        if isinstance(kind, str) and kind.strip():
            inbound_data["kind"] = kind.strip()
        from_val = parsed.get("from")
        if isinstance(from_val, str) and from_val.strip():
            inbound_data["from"] = from_val.strip()

        inbound = WebhookInbound.model_validate(inbound_data)

        # Dispatch - endpoint ref excludes secret
        endpoint_ref = {"id": endpoint.id, "name": endpoint.name}
        try:
            dispatch = self._on_message(inbound, endpoint_ref)
        except Exception:
            return {
                "status_code": 500,
                "body": {"ok": False, "error": "could not create task"},
            }

        if dispatch is None:
            return {
                "status_code": 500,
                "body": {"ok": False, "error": "could not create task"},
            }

        if dispatch.pending:
            return {
                "status_code": 202,
                "body": {
                    "ok": True,
                    "pending": True,
                    "status": "awaiting-approval",
                    "token": dispatch.token,
                },
            }

        return {
            "status_code": 200,
            "body": {
                "ok": True,
                "token": dispatch.token,
                "taskId": dispatch.task_id,
            },
        }

    def handle_get(
        self,
        endpoint_id: str,
        headers: dict[str, str],
    ) -> dict[str, Any]:
        """Handle a GET request for token-based task status lookup.

        The lookup runs even when the endpoint id is unknown, and the answer is
        then the same 404 the unknown-token case gives. This prevents enumeration.

        Args:
            endpoint_id: The endpoint identifier from the request path.
            headers: Request headers (expects 'x-md-webhook-token').

        Returns:
            Dict with 'status_code' and 'body' keys representing the HTTP response.
        """
        token = headers.get("x-md-webhook-token", "").strip()
        if not token:
            return {"status_code": 401, "body": {"ok": False, "error": "token required"}}

        endpoint = self._endpoints.get(endpoint_id)

        # Always perform the lookup (even for unknown endpoints) to prevent
        # timing-based enumeration of endpoint ids
        try:
            status = self._lookup_status(token)
        except Exception:
            return {"status_code": 500, "body": {"ok": False, "error": "lookup failed"}}

        # Return 404 for unknown token OR unknown endpoint - identical response
        if status is None or endpoint is None:
            return {"status_code": 404, "body": {"ok": False, "error": "not found"}}

        return {
            "status_code": 200,
            "body": {
                "ok": True,
                "status": status.status,
                "title": status.title,
                "result": status.result,
            },
        }


def _validate_schema(data: dict[str, Any], schema_str: str) -> str | None:
    """Validate data against a JSON Schema string.

    Invalid or empty schemas mean "accept all" - a mistyped schema must never
    lock out a caller with a valid secret.

    Args:
        data: The parsed JSON body to validate.
        schema_str: The JSON Schema string from the endpoint configuration.

    Returns:
        An error message string if validation fails, None if it passes.
    """
    if not schema_str or not schema_str.strip() or schema_str.strip() == "{}":
        return None

    try:
        schema = json.loads(schema_str)
    except (json.JSONDecodeError, TypeError):
        # Unparseable schema = accept all (don't lock out valid callers)
        return None

    if not isinstance(schema, dict) or not schema:
        return None

    try:
        jsonschema.validate(instance=data, schema=schema)
    except jsonschema.ValidationError as exc:
        return str(exc.message)
    except jsonschema.SchemaError:
        # Invalid schema definition = accept all
        return None

    return None
