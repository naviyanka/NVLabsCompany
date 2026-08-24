"""Tests for middleware-level authentication enforcement.

The policy lives in :func:`nexus.auth.middleware.rejection_for` rather than in
route dependencies, because a route that forgets to ask about identity is the
normal failure mode. These tests cover the decision directly and then confirm it
reaches the wire through the real application's middleware stack.
"""

import uuid

import pytest
from fastapi.testclient import TestClient

from nexus.auth.middleware import is_public_path, rejection_for
from nexus.auth.principal import Principal
from nexus.config import settings

COMPANY_ID = uuid.UUID("00000000-0000-4000-8000-000000000001")
OTHER_COMPANY_ID = uuid.UUID("11111111-1111-4111-8111-111111111111")


def _principal(company_id: uuid.UUID = COMPANY_ID) -> Principal:
    """A user principal scoped to one company."""
    return Principal(
        kind="user",
        company_id=company_id,
        role="admin",
        user_id=uuid.uuid4(),
        email="operator@example.com",
    )


class TestPublicPaths:
    """Which paths answer without a credential."""

    @pytest.mark.parametrize(
        "path",
        [
            "/health",
            "/health/live",
            "/health/ready",
            "/metrics",
            "/docs",
            "/redoc",
            "/openapi.json",
            "/favicon.ico",
            "/api/v1/auth",
            "/api/v1/auth/login",
            "/api/v1/auth/setup",
            "/api/v1/auth/setup-required",
            "/api/v1/auth/invites/accept",
        ],
    )
    def test_public(self, path: str):
        """Login, setup, health, metrics and the docs need no caller."""
        assert is_public_path(path) is True

    @pytest.mark.parametrize(
        "path",
        [
            "/api/v1/companies",
            f"/api/v1/companies/{COMPANY_ID}/agents",
            "/api/v1/agents",
            "/events/stream",
            "/system/degradation",
            # The auth prefix requires its trailing slash, so a route that merely
            # starts with the same letters is not public.
            "/api/v1/authorized-keys",
        ],
    )
    def test_not_public(self, path: str):
        """Everything else requires a credential."""
        assert is_public_path(path) is False


class TestAnonymousRejection:
    """An anonymous request to a protected path is a 401."""

    def test_returns_401_with_www_authenticate(self):
        """The response names Bearer so non-browser clients know how to retry."""
        response = rejection_for("/api/v1/agents", None)

        assert response is not None
        assert response.status_code == 401
        assert response.headers["www-authenticate"] == "Bearer"
        assert b"Authentication required" in response.body

    def test_public_path_passes(self):
        """A public path is never rejected, credential or not."""
        assert rejection_for("/health/live", None) is None

    def test_legacy_mode_passes(self, monkeypatch: pytest.MonkeyPatch):
        """With AUTH_ENABLED=false an anonymous request continues as before."""
        monkeypatch.setattr(settings, "auth_enabled", False)

        assert rejection_for("/api/v1/agents", None) is None


class TestTenantScoping:
    """A company id in the URL must match the caller's own."""

    def test_mismatch_returns_403(self):
        """Substituting another tenant's UUID is forbidden, not silently served."""
        response = rejection_for(
            f"/api/v1/companies/{OTHER_COMPANY_ID}/agents", _principal()
        )

        assert response is not None
        assert response.status_code == 403
        assert b"TENANT_MISMATCH" in response.body

    def test_match_passes(self):
        """The caller's own company is served."""
        assert (
            rejection_for(f"/api/v1/companies/{COMPANY_ID}/agents", _principal())
            is None
        )

    def test_bare_company_path_passes(self):
        """``/api/v1/companies`` names no tenant, so there is nothing to compare."""
        assert rejection_for("/api/v1/companies", _principal()) is None

    def test_non_uuid_segment_passes(self):
        """A malformed id is routing's problem — a 404 or 422, not a 403."""
        assert rejection_for("/api/v1/companies/not-a-uuid/agents", _principal()) is None

    def test_uuid_shaped_but_invalid_segment_passes(self):
        """36 characters of the right alphabet still may not parse as a UUID."""
        placeholder = "-" * 36

        assert rejection_for(f"/api/v1/companies/{placeholder}/agents", _principal()) is None

    def test_other_paths_pass_for_authenticated_caller(self):
        """Paths without a company segment are left to the route."""
        assert rejection_for("/api/v1/agents", _principal()) is None


class TestThroughTheApp:
    """The same policy, exercised through the real middleware stack."""

    @pytest.fixture()
    def client(self):
        """A client over the application, without running its lifespan.

        The rejections under test happen before any route or database access, so
        no startup work is needed to observe them.
        """
        from nexus.main import app

        return TestClient(app, raise_server_exceptions=False)

    def test_protected_route_rejects_anonymous(self, client: TestClient):
        """A router that never declared a dependency is still protected."""
        response = client.get(f"/api/v1/companies/{COMPANY_ID}/agents")

        assert response.status_code == 401
        assert response.json()["code"] == "UNAUTHENTICATED"

    def test_company_id_header_is_not_a_credential(self, client: TestClient):
        """The header the API used to trust no longer authenticates anything."""
        response = client.get(
            f"/api/v1/companies/{COMPANY_ID}/agents",
            headers={"X-Company-Id": str(COMPANY_ID)},
        )

        assert response.status_code == 401

    def test_health_probe_stays_open(self, client: TestClient):
        """Liveness must answer without a credential for orchestrators."""
        response = client.get("/health/live")

        assert response.status_code == 200
