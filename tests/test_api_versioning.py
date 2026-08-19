"""Tests for API Versioning Strategy."""

from datetime import date

import pytest
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from nexus.api.versioning import APIVersionMiddleware, VersionedRouter


@pytest.fixture
def app() -> FastAPI:
    """Create a test FastAPI app with version middleware."""
    test_app = FastAPI()
    test_app.add_middleware(APIVersionMiddleware, version="1.0")
    return test_app


@pytest.fixture
def client(app: FastAPI) -> TestClient:
    """Create a test client for the app."""
    return TestClient(app)


class TestAPIVersionMiddleware:
    """Tests for APIVersionMiddleware."""

    def test_version_header_added(
        self, app: FastAPI, client: TestClient
    ) -> None:
        """Test that X-API-Version header is added to responses."""

        @app.get("/test")
        async def test_endpoint() -> dict[str, str]:
            """Test endpoint."""
            return {"status": "ok"}

        response = client.get("/test")
        assert response.status_code == 200
        assert response.headers.get("X-API-Version") == "1.0"

    def test_version_header_on_404(
        self, app: FastAPI, client: TestClient
    ) -> None:
        """Test that version header is added even on 404 responses."""
        response = client.get("/nonexistent")
        assert response.headers.get("X-API-Version") == "1.0"

    def test_custom_version_string(self) -> None:
        """Test middleware with a custom version string."""
        test_app = FastAPI()
        test_app.add_middleware(APIVersionMiddleware, version="2.0")

        @test_app.get("/test")
        async def test_endpoint() -> dict[str, str]:
            """Test endpoint."""
            return {"version": "check"}

        test_client = TestClient(test_app)
        response = test_client.get("/test")
        assert response.headers.get("X-API-Version") == "2.0"


class TestVersionedRouter:
    """Tests for VersionedRouter."""

    def test_default_prefix(self) -> None:
        """Test that default prefix is /api/v1."""
        router = VersionedRouter(version=1)
        assert router.prefix == "/api/v1"

    def test_custom_version(self) -> None:
        """Test that version number is reflected in prefix."""
        router = VersionedRouter(version=2)
        assert router.prefix == "/api/v2"

    def test_routes_accessible_at_versioned_path(self) -> None:
        """Test that routes are accessible under the versioned prefix."""
        test_app = FastAPI()
        router = VersionedRouter(version=1)

        @router.get("/items")
        async def list_items() -> dict[str, str]:
            """List items endpoint."""
            return {"items": "list"}

        test_app.include_router(router)
        test_client = TestClient(test_app)

        response = test_client.get("/api/v1/items")
        assert response.status_code == 200
        assert response.json() == {"items": "list"}

    def test_routes_not_accessible_without_prefix(self) -> None:
        """Test that routes are not accessible without version prefix."""
        test_app = FastAPI()
        router = VersionedRouter(version=1)

        @router.get("/items")
        async def list_items() -> dict[str, str]:
            """List items endpoint."""
            return {"items": "list"}

        test_app.include_router(router)
        test_client = TestClient(test_app)

        response = test_client.get("/items")
        assert response.status_code == 404

    def test_deprecated_route_returns_sunset_header(self) -> None:
        """Test that deprecated routes include Sunset header."""
        test_app = FastAPI()
        router = VersionedRouter(version=1)
        sunset = date(2025, 12, 31)

        async def old_endpoint(request: Request) -> JSONResponse:
            """Old endpoint."""
            return JSONResponse(content={"legacy": True})

        router.add_deprecated_route(
            "/old-items",
            old_endpoint,
            sunset_date=sunset,
            methods=["GET"],
        )

        test_app.include_router(router)
        test_client = TestClient(test_app)

        response = test_client.get("/api/v1/old-items")
        assert response.status_code == 200
        assert response.headers.get("Sunset") == "2025-12-31"
        assert response.headers.get("Deprecation") == "true"

    def test_deprecated_route_content(self) -> None:
        """Test that deprecated routes still return correct content."""
        test_app = FastAPI()
        router = VersionedRouter(version=1)
        sunset = date(2025, 6, 1)

        async def legacy_endpoint(request: Request) -> JSONResponse:
            """Legacy endpoint."""
            return JSONResponse(content={"data": "legacy-data"})

        router.add_deprecated_route(
            "/legacy",
            legacy_endpoint,
            sunset_date=sunset,
            methods=["GET"],
        )

        test_app.include_router(router)
        test_client = TestClient(test_app)

        response = test_client.get("/api/v1/legacy")
        assert response.json() == {"data": "legacy-data"}

    def test_get_deprecated_routes(self) -> None:
        """Test retrieving the list of deprecated routes."""
        router = VersionedRouter(version=1)
        sunset1 = date(2025, 6, 1)
        sunset2 = date(2025, 12, 31)

        async def ep1(request: Request) -> JSONResponse:
            """Endpoint 1."""
            return JSONResponse(content={})

        async def ep2(request: Request) -> JSONResponse:
            """Endpoint 2."""
            return JSONResponse(content={})

        router.add_deprecated_route("/old1", ep1, sunset_date=sunset1)
        router.add_deprecated_route("/old2", ep2, sunset_date=sunset2)

        deprecated = router.get_deprecated_routes()
        assert "/old1" in deprecated
        assert "/old2" in deprecated
        assert deprecated["/old1"] == sunset1
        assert deprecated["/old2"] == sunset2

    def test_version_middleware_with_versioned_router(self) -> None:
        """Test that version middleware works with versioned router routes."""
        test_app = FastAPI()
        test_app.add_middleware(APIVersionMiddleware, version="1.0")
        router = VersionedRouter(version=1)

        @router.get("/data")
        async def get_data() -> dict[str, str]:
            """Get data endpoint."""
            return {"data": "value"}

        test_app.include_router(router)
        test_client = TestClient(test_app)

        response = test_client.get("/api/v1/data")
        assert response.status_code == 200
        assert response.headers.get("X-API-Version") == "1.0"
        assert response.json() == {"data": "value"}

    def test_api_version_attribute(self) -> None:
        """Test that the router exposes its version number."""
        router = VersionedRouter(version=3)
        assert router.api_version == 3
