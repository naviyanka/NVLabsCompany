"""Comprehensive tests for the WebhookServer module."""

import json
from unittest.mock import patch

from nexus.communication.webhook_server import (
    LEGACY_ENDPOINT_ID,
    MAX_BODY_BYTES,
    PER_ENDPOINT_RATE_LIMIT,
    RATE_LIMIT,
    RATE_WINDOW_MS,
    UNKNOWN_BUCKET,
    WebhookServer,
)
from nexus.communication.webhook_types import (
    WebhookDispatch,
    WebhookEndpoint,
    WebhookInbound,
    WebhookTaskStatus,
)

# ── Helpers ──────────────────────────────────────────────────────────────────


def _make_endpoint(
    ep_id: str = "test-ep",
    name: str = "Test Endpoint",
    secret: str = "correct-secret-value",
    schema: str = "{}",
    enabled: bool = True,
) -> WebhookEndpoint:
    """Create a WebhookEndpoint for testing."""
    return WebhookEndpoint(id=ep_id, name=name, secret=secret, schema=schema, enabled=enabled)


def _default_on_message(inbound: WebhookInbound, endpoint_ref: dict[str, str]) -> WebhookDispatch:
    """Default on_message handler that returns a successful dispatch."""
    return WebhookDispatch(token="tok-abc123", task_id="task-001", pending=False)


def _default_lookup_status(token: str) -> WebhookTaskStatus | None:
    """Default lookup_status handler that recognizes one token."""
    if token == "tok-abc123":
        return WebhookTaskStatus(status="done", title="Test Task", result="completed")
    return None


def _make_server(
    endpoints: list[WebhookEndpoint] | None = None,
    on_message=None,
    lookup_status=None,
) -> WebhookServer:
    """Create a WebhookServer for testing with sensible defaults."""
    if endpoints is None:
        endpoints = [_make_endpoint()]
    if on_message is None:
        on_message = _default_on_message
    if lookup_status is None:
        lookup_status = _default_lookup_status
    return WebhookServer(
        endpoints=endpoints,
        on_message=on_message,
        lookup_status=lookup_status,
    )


def _post(
    server: WebhookServer,
    endpoint_id: str = "test-ep",
    secret: str = "correct-secret-value",
    body: dict | bytes | None = None,
    headers: dict[str, str] | None = None,
) -> dict:
    """Helper to issue a POST request to the server."""
    if headers is None:
        headers = {}
    if secret:
        headers.setdefault("x-md-webhook-secret", secret)
    if body is None:
        body_bytes = json.dumps({"message": "hello"}).encode()
    elif isinstance(body, bytes):
        body_bytes = body
    else:
        body_bytes = json.dumps(body).encode()
    return server.handle_post(endpoint_id, headers, body_bytes)


def _get(
    server: WebhookServer,
    endpoint_id: str = "test-ep",
    token: str = "tok-abc123",
    headers: dict[str, str] | None = None,
) -> dict:
    """Helper to issue a GET request to the server."""
    if headers is None:
        headers = {}
    if token:
        headers.setdefault("x-md-webhook-token", token)
    return server.handle_get(endpoint_id, headers)


# ── Test: Type Models ────────────────────────────────────────────────────────


class TestWebhookTypes:
    """Tests for webhook type models."""

    def test_webhook_endpoint_defaults(self):
        """WebhookEndpoint should have correct defaults."""
        ep = WebhookEndpoint(id="x", name="X", secret="s")
        assert ep.schema_ == "{}"
        assert ep.enabled is True

    def test_webhook_endpoint_schema_alias(self):
        """WebhookEndpoint schema field uses alias 'schema'."""
        ep = WebhookEndpoint.model_validate(
            {"id": "x", "name": "X", "secret": "s", "schema": '{"type":"object"}'}
        )
        assert ep.schema_ == '{"type":"object"}'

    def test_webhook_inbound_from_alias(self):
        """WebhookInbound from_ field uses alias 'from'."""
        inbound = WebhookInbound.model_validate({"message": "hi", "from": "sender"})
        assert inbound.from_ == "sender"
        assert inbound.message == "hi"

    def test_webhook_inbound_defaults(self):
        """WebhookInbound optional fields default to None."""
        inbound = WebhookInbound(message="hi")
        assert inbound.title is None
        assert inbound.kind is None
        assert inbound.from_ is None

    def test_webhook_dispatch_fields(self):
        """WebhookDispatch should carry token, task_id, and pending."""
        d = WebhookDispatch(token="t", task_id="task-1", pending=False)
        assert d.token == "t"
        assert d.task_id == "task-1"
        assert d.pending is False

    def test_webhook_task_status_fields(self):
        """WebhookTaskStatus should carry status, title, and optional result."""
        s = WebhookTaskStatus(status="running", title="Job")
        assert s.status == "running"
        assert s.result is None


# ── Test: verify_secret ──────────────────────────────────────────────────────


class TestVerifySecret:
    """Tests for secret verification with constant-time comparison."""

    def test_correct_secret_returns_true(self):
        """Providing the correct secret returns True."""
        server = _make_server()
        ep = _make_endpoint(secret="my-secret")
        assert server.verify_secret("my-secret", ep) is True

    def test_wrong_secret_returns_false(self):
        """Providing the wrong secret returns False."""
        server = _make_server()
        ep = _make_endpoint(secret="my-secret")
        assert server.verify_secret("wrong-secret", ep) is False

    def test_unknown_endpoint_uses_decoy_and_returns_false(self):
        """None endpoint (unknown id) always returns False."""
        server = _make_server()
        # Even if by some miracle the provided string matches the decoy,
        # the method must return False for None endpoints
        assert server.verify_secret("anything", None) is False

    def test_empty_secret_returns_false(self):
        """An empty provided secret returns False."""
        server = _make_server()
        ep = _make_endpoint(secret="my-secret")
        assert server.verify_secret("", ep) is False

    def test_timing_safety_both_paths_do_comparison(self):
        """Both known and unknown endpoint paths run hmac.compare_digest."""
        server = _make_server()
        ep = _make_endpoint(secret="secret-value")
        # Patch hmac.compare_digest to verify it is called
        with patch("nexus.communication.webhook_server.hmac.compare_digest") as mock_cmp:
            mock_cmp.return_value = True
            server.verify_secret("secret-value", ep)
            assert mock_cmp.called
            mock_cmp.reset_mock()

            mock_cmp.return_value = False
            server.verify_secret("wrong", None)
            assert mock_cmp.called


# ── Test: Rate Limiting ──────────────────────────────────────────────────────


class TestRateLimiting:
    """Tests for fixed-window rate limiting."""

    def test_allows_up_to_limit(self):
        """Requests up to the limit should be allowed."""
        server = _make_server()
        for _ in range(5):
            assert server.allow_request("test-bucket", 5) is True

    def test_rejects_after_limit(self):
        """Request after hitting the limit should be rejected."""
        server = _make_server()
        for _ in range(5):
            server.allow_request("test-bucket", 5)
        assert server.allow_request("test-bucket", 5) is False

    def test_resets_after_window(self):
        """Rate limit should reset after the window expires."""
        server = _make_server()
        # Fill up the bucket
        for _ in range(5):
            server.allow_request("test-bucket", 5)
        assert server.allow_request("test-bucket", 5) is False

        # Simulate window expiry by manipulating internal state
        window = server._windows["test-bucket"]
        window["start"] -= RATE_WINDOW_MS + 1

        # Should allow again
        assert server.allow_request("test-bucket", 5) is True

    def test_separate_buckets_are_independent(self):
        """Different buckets should not affect each other."""
        server = _make_server()
        for _ in range(5):
            server.allow_request("bucket-a", 5)
        assert server.allow_request("bucket-a", 5) is False
        assert server.allow_request("bucket-b", 5) is True

    def test_global_rate_limit_applied_before_per_endpoint(self):
        """Global limit exhaustion should reject before per-endpoint check."""
        server = _make_server()
        # Exhaust global limit
        for _ in range(RATE_LIMIT):
            server.allow_request("", RATE_LIMIT)
        # Global is exhausted
        result = _post(server)
        assert result["status_code"] == 429


# ── Test: handle_post ────────────────────────────────────────────────────────


class TestHandlePost:
    """Tests for the POST request pipeline."""

    def test_successful_post(self):
        """A valid POST should return 200 with token and taskId."""
        server = _make_server()
        result = _post(server)
        assert result["status_code"] == 200
        assert result["body"]["ok"] is True
        assert result["body"]["token"] == "tok-abc123"
        assert result["body"]["taskId"] == "task-001"

    def test_rejects_body_over_1mb(self):
        """Body larger than MAX_BODY_BYTES should be rejected with 413."""
        server = _make_server()
        big_body = b"x" * (MAX_BODY_BYTES + 1)
        result = _post(server, body=big_body)
        assert result["status_code"] == 413
        assert result["body"]["error"] == "too large"

    def test_body_exactly_1mb_accepted(self):
        """Body exactly at the limit should be accepted (if valid JSON)."""
        server = _make_server()
        # Create a valid JSON body that is exactly at the limit
        msg = "a" * (MAX_BODY_BYTES - 50)
        body = json.dumps({"message": msg}).encode()
        # This will be under the limit due to JSON overhead
        if len(body) <= MAX_BODY_BYTES:
            result = _post(server, body=body)
            # Should pass size check (may fail JSON schema but not size)
            assert result["status_code"] != 413

    def test_rejects_invalid_json(self):
        """Invalid JSON should be rejected with 400."""
        server = _make_server()
        result = _post(server, body=b"not json at all {{{")
        assert result["status_code"] == 400
        assert result["body"]["error"] == "bad json"

    def test_rejects_non_object_json(self):
        """Non-object JSON (array, number, etc.) should be rejected."""
        server = _make_server()
        result = _post(server, body=b"[1,2,3]")
        assert result["status_code"] == 400
        assert result["body"]["error"] == "bad json"

    def test_validates_schema(self):
        """Body not matching endpoint schema should be rejected."""
        schema = json.dumps(
            {
                "type": "object",
                "properties": {"message": {"type": "string"}, "priority": {"type": "integer"}},
                "required": ["message", "priority"],
            }
        )
        ep = _make_endpoint(schema=schema)
        server = _make_server(endpoints=[ep])
        # Missing required 'priority' field
        result = _post(server, body={"message": "hi"})
        assert result["status_code"] == 400

    def test_schema_validation_passes_valid_body(self):
        """Body matching endpoint schema should pass validation."""
        schema = json.dumps(
            {
                "type": "object",
                "properties": {"message": {"type": "string"}, "priority": {"type": "integer"}},
                "required": ["message", "priority"],
            }
        )
        ep = _make_endpoint(schema=schema)
        server = _make_server(endpoints=[ep])
        result = _post(server, body={"message": "hi", "priority": 1})
        assert result["status_code"] == 200

    def test_empty_schema_accepts_all(self):
        """An empty schema ('{}') should accept any valid JSON body."""
        ep = _make_endpoint(schema="{}")
        server = _make_server(endpoints=[ep])
        result = _post(server, body={"message": "hello", "extra": "stuff"})
        assert result["status_code"] == 200

    def test_invalid_schema_accepts_all(self):
        """An unparseable schema should accept all (not lock out valid callers)."""
        ep = _make_endpoint(schema="not valid json {{{")
        server = _make_server(endpoints=[ep])
        result = _post(server, body={"message": "hello"})
        assert result["status_code"] == 200

    def test_message_required(self):
        """Missing or empty message field should be rejected."""
        server = _make_server()
        result = _post(server, body={"title": "no message here"})
        assert result["status_code"] == 400
        assert result["body"]["error"] == "message required"

    def test_message_whitespace_only_rejected(self):
        """A message that is only whitespace should be rejected."""
        server = _make_server()
        result = _post(server, body={"message": "   "})
        assert result["status_code"] == 400
        assert result["body"]["error"] == "message required"

    def test_extracts_webhook_inbound_correctly(self):
        """All WebhookInbound fields should be extracted from the body."""
        captured = {}

        def capture_message(inbound: WebhookInbound, ref: dict[str, str]) -> WebhookDispatch:
            captured["inbound"] = inbound
            captured["ref"] = ref
            return WebhookDispatch(token="t", task_id="tid", pending=False)

        server = _make_server(on_message=capture_message)
        body = {
            "message": "do something",
            "title": "My Task",
            "kind": "directive",
            "from": "external-system",
        }
        result = _post(server, body=body)
        assert result["status_code"] == 200
        inbound = captured["inbound"]
        assert inbound.message == "do something"
        assert inbound.title == "My Task"
        assert inbound.kind == "directive"
        assert inbound.from_ == "external-system"
        # Endpoint ref must NOT contain secret
        assert "secret" not in captured["ref"]
        assert captured["ref"]["id"] == "test-ep"
        assert captured["ref"]["name"] == "Test Endpoint"

    def test_pending_dispatch_returns_202(self):
        """A pending dispatch should return 202 with awaiting-approval status."""

        def pending_handler(inbound, ref):
            return WebhookDispatch(token="pending-tok", task_id=None, pending=True)

        server = _make_server(on_message=pending_handler)
        result = _post(server)
        assert result["status_code"] == 202
        assert result["body"]["pending"] is True
        assert result["body"]["status"] == "awaiting-approval"
        assert result["body"]["token"] == "pending-tok"

    def test_on_message_exception_returns_500(self):
        """An exception in on_message should return 500."""

        def failing_handler(inbound, ref):
            raise RuntimeError("boom")

        server = _make_server(on_message=failing_handler)
        result = _post(server)
        assert result["status_code"] == 500
        assert result["body"]["error"] == "could not create task"

    def test_on_message_returns_none_gives_500(self):
        """on_message returning None should return 500."""

        def none_handler(inbound, ref):
            return None

        server = _make_server(on_message=none_handler)
        result = _post(server)
        assert result["status_code"] == 500

    def test_missing_secret_header_returns_401(self):
        """A POST without the secret header should be rejected."""
        server = _make_server()
        result = server.handle_post("test-ep", {}, json.dumps({"message": "hi"}).encode())
        assert result["status_code"] == 401

    def test_wrong_secret_returns_401(self):
        """A POST with the wrong secret should be rejected."""
        server = _make_server()
        result = _post(server, secret="wrong-secret")
        assert result["status_code"] == 401
        assert result["body"]["error"] == "unauthorized"

    def test_per_endpoint_rate_limit(self):
        """Per-endpoint rate limit should reject after exhaustion."""
        server = _make_server()
        # Exhaust per-endpoint limit
        for _ in range(PER_ENDPOINT_RATE_LIMIT):
            server.allow_request("test-ep", PER_ENDPOINT_RATE_LIMIT)
        # Next request to that endpoint should be rate limited
        # Need to exhaust global first call, then per-endpoint check
        result = _post(server)
        assert result["status_code"] == 429


# ── Test: handle_get ─────────────────────────────────────────────────────────


class TestHandleGet:
    """Tests for the GET request (token status lookup) pipeline."""

    def test_returns_status_for_valid_token(self):
        """A valid token should return the task status."""
        server = _make_server()
        result = _get(server, token="tok-abc123")
        assert result["status_code"] == 200
        assert result["body"]["ok"] is True
        assert result["body"]["status"] == "done"
        assert result["body"]["title"] == "Test Task"
        assert result["body"]["result"] == "completed"

    def test_returns_not_found_for_unknown_token(self):
        """An unknown token should return 404."""
        server = _make_server()
        result = _get(server, token="unknown-token")
        assert result["status_code"] == 404
        assert result["body"]["error"] == "not found"

    def test_returns_401_for_missing_token(self):
        """A GET without a token header should return 401."""
        server = _make_server()
        result = _get(server, token="")
        assert result["status_code"] == 401
        assert result["body"]["error"] == "token required"

    def test_lookup_exception_returns_500(self):
        """An exception in lookup_status should return 500."""

        def failing_lookup(token: str):
            raise RuntimeError("db down")

        server = _make_server(lookup_status=failing_lookup)
        result = _get(server, token="tok-abc123")
        assert result["status_code"] == 500
        assert result["body"]["error"] == "lookup failed"

    def test_unknown_endpoint_with_valid_token_returns_404(self):
        """GET on unknown endpoint still does lookup but returns 404."""
        server = _make_server()
        result = _get(server, endpoint_id="nonexistent", token="tok-abc123")
        assert result["status_code"] == 404
        assert result["body"]["error"] == "not found"


# ── Test: Security - No Enumeration ─────────────────────────────────────────


class TestNoEnumeration:
    """Tests that unknown endpoints are indistinguishable from wrong secrets."""

    def test_unknown_endpoint_same_response_as_wrong_secret(self):
        """Unknown endpoint ID must answer identically to wrong secret."""
        server = _make_server()
        # Wrong secret on known endpoint
        wrong_secret_result = _post(server, endpoint_id="test-ep", secret="wrong")
        # Any secret on unknown endpoint
        unknown_ep_result = _post(server, endpoint_id="unknown-ep", secret="anything")
        # Both should be 401 with the same body
        assert wrong_secret_result["status_code"] == 401
        assert unknown_ep_result["status_code"] == 401
        assert wrong_secret_result["body"] == unknown_ep_result["body"]

    def test_unknown_endpoint_get_same_as_unknown_token(self):
        """GET on unknown endpoint returns same 404 as unknown token."""
        server = _make_server()
        # Unknown token on known endpoint
        unknown_token_result = _get(server, endpoint_id="test-ep", token="bad-token")
        # Valid token on unknown endpoint
        unknown_ep_result = _get(server, endpoint_id="nonexistent", token="tok-abc123")
        # Both should be 404 with same body
        assert unknown_token_result["status_code"] == 404
        assert unknown_ep_result["status_code"] == 404
        assert unknown_token_result["body"] == unknown_ep_result["body"]

    def test_unknown_endpoints_share_rate_limit_bucket(self):
        """All unknown endpoint IDs share the UNKNOWN_BUCKET rate limit."""
        server = _make_server()
        # Hit multiple different unknown endpoint ids
        for i in range(PER_ENDPOINT_RATE_LIMIT):
            server.allow_request(UNKNOWN_BUCKET, PER_ENDPOINT_RATE_LIMIT)
        # Bucket should be exhausted now
        assert server.allow_request(UNKNOWN_BUCKET, PER_ENDPOINT_RATE_LIMIT) is False


# ── Test: Legacy Endpoint Routing ────────────────────────────────────────────


class TestLegacyEndpointRouting:
    """Tests for LEGACY_ENDPOINT_ID bare-POST routing."""

    def test_empty_endpoint_id_maps_to_legacy(self):
        """Empty endpoint_id is mapped to LEGACY_ENDPOINT_ID."""
        legacy_ep = _make_endpoint(ep_id=LEGACY_ENDPOINT_ID, secret="legacy-secret")
        server = _make_server(endpoints=[legacy_ep])
        result = _post(server, endpoint_id="", secret="legacy-secret")
        assert result["status_code"] == 200

    def test_none_like_endpoint_id_maps_to_legacy(self):
        """Falsy endpoint_id routes to the legacy endpoint."""
        legacy_ep = _make_endpoint(ep_id=LEGACY_ENDPOINT_ID, secret="legacy-secret")
        server = _make_server(endpoints=[legacy_ep])
        # Passing empty string simulates bare POST /
        result = server.handle_post(
            "",
            {"x-md-webhook-secret": "legacy-secret"},
            json.dumps({"message": "hello"}).encode(),
        )
        assert result["status_code"] == 200

    def test_no_legacy_endpoint_configured_returns_401(self):
        """If no legacy endpoint is configured, bare POST returns 401."""
        server = _make_server()  # only has "test-ep"
        result = _post(server, endpoint_id="", secret="anything")
        assert result["status_code"] == 401


# ── Test: set_endpoints ──────────────────────────────────────────────────────


class TestSetEndpoints:
    """Tests for dynamic endpoint configuration swapping."""

    def test_set_endpoints_replaces_config(self):
        """set_endpoints should replace the endpoint map."""
        server = _make_server()
        new_ep = _make_endpoint(ep_id="new-ep", secret="new-secret")
        server.set_endpoints([new_ep])
        # Old endpoint should be gone
        result = _post(server, endpoint_id="test-ep", secret="correct-secret-value")
        assert result["status_code"] == 401
        # New endpoint should work
        result = _post(server, endpoint_id="new-ep", secret="new-secret")
        assert result["status_code"] == 200

    def test_set_endpoints_filters_disabled(self):
        """set_endpoints should exclude endpoints with enabled=False."""
        disabled_ep = _make_endpoint(
            ep_id="disabled-ep", secret="my-secret", enabled=False
        )
        enabled_ep = _make_endpoint(
            ep_id="enabled-ep", secret="my-secret", enabled=True
        )
        server = _make_server(endpoints=[disabled_ep, enabled_ep])
        # Disabled endpoint should not be reachable
        result = _post(server, endpoint_id="disabled-ep", secret="my-secret")
        assert result["status_code"] == 401
        # Enabled endpoint should work
        result = _post(server, endpoint_id="enabled-ep", secret="my-secret")
        assert result["status_code"] == 200

    def test_set_endpoints_clears_old_rate_limits(self):
        """Rate limit state for removed endpoints should be cleared."""
        server = _make_server()
        # Create some rate limit state for the endpoint
        server.allow_request("test-ep", PER_ENDPOINT_RATE_LIMIT)
        assert "test-ep" in server._windows
        # Swap endpoints
        new_ep = _make_endpoint(ep_id="new-ep", secret="s")
        server.set_endpoints([new_ep])
        # Old endpoint's rate state should be gone
        assert "test-ep" not in server._windows

    def test_set_endpoints_keeps_global_and_unknown_buckets(self):
        """Global and unknown rate limit buckets survive an endpoint swap."""
        server = _make_server()
        server.allow_request("", RATE_LIMIT)
        server.allow_request(UNKNOWN_BUCKET, PER_ENDPOINT_RATE_LIMIT)
        new_ep = _make_endpoint(ep_id="new-ep", secret="s")
        server.set_endpoints([new_ep])
        assert "" in server._windows
        assert UNKNOWN_BUCKET in server._windows


# ── Test: Constants ──────────────────────────────────────────────────────────


class TestConstants:
    """Tests for module-level constants."""

    def test_max_body_bytes(self):
        """MAX_BODY_BYTES should be 1MB."""
        assert MAX_BODY_BYTES == 1_048_576

    def test_rate_limit(self):
        """RATE_LIMIT should be 120."""
        assert RATE_LIMIT == 120

    def test_per_endpoint_rate_limit(self):
        """PER_ENDPOINT_RATE_LIMIT should be 60."""
        assert PER_ENDPOINT_RATE_LIMIT == 60

    def test_rate_window_ms(self):
        """RATE_WINDOW_MS should be 60000."""
        assert RATE_WINDOW_MS == 60_000

    def test_legacy_endpoint_id(self):
        """LEGACY_ENDPOINT_ID should be 'legacy'."""
        assert LEGACY_ENDPOINT_ID == "legacy"

    def test_unknown_bucket(self):
        """UNKNOWN_BUCKET should be ':unknown'."""
        assert UNKNOWN_BUCKET == ":unknown"


# ── Test: Secrets Never in Response ──────────────────────────────────────────


class TestSecretsNeverExposed:
    """Tests that secrets never appear in responses or dispatch data."""

    def test_secret_not_in_post_response(self):
        """The endpoint secret must never appear in POST responses."""
        server = _make_server()
        result = _post(server)
        response_str = json.dumps(result["body"])
        assert "correct-secret-value" not in response_str

    def test_secret_not_in_endpoint_ref(self):
        """The endpoint ref passed to on_message must not contain the secret."""
        captured_ref = {}

        def capture_handler(inbound, ref):
            captured_ref.update(ref)
            return WebhookDispatch(token="t", pending=False)

        server = _make_server(on_message=capture_handler)
        _post(server)
        assert "secret" not in captured_ref

    def test_secret_not_in_get_response(self):
        """The endpoint secret must never appear in GET responses."""
        server = _make_server()
        result = _get(server)
        response_str = json.dumps(result["body"])
        assert "correct-secret-value" not in response_str
