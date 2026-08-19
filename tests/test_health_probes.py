"""Tests for health check and readiness probe endpoints."""

from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from nexus.main import app


@pytest.fixture
def anyio_backend():
    """Use asyncio backend for anyio."""
    return "asyncio"


@pytest.fixture
async def client():
    """Create an async HTTP client for testing."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


def _mock_engine_connected():
    """Create a mock engine whose connect() yields a working connection."""
    mock_conn = AsyncMock()
    mock_conn.execute = AsyncMock()

    @asynccontextmanager
    async def _connect():
        yield mock_conn

    mock_engine = AsyncMock()
    mock_engine.connect = _connect
    return mock_engine


def _mock_engine_disconnected():
    """Create a mock engine whose connect() raises an exception."""

    @asynccontextmanager
    async def _connect():
        raise Exception("Connection refused")
        yield  # pragma: no cover

    mock_engine = AsyncMock()
    mock_engine.connect = _connect
    return mock_engine


@pytest.mark.asyncio
async def test_liveness_returns_200(client):
    """GET /health/live always returns 200 with status alive."""
    response = await client.get("/health/live")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "alive"


@pytest.mark.asyncio
async def test_readiness_returns_200_when_db_connected(client):
    """GET /health/ready returns 200 when DB is reachable."""
    mock_engine = _mock_engine_connected()

    with patch("nexus.api.routes.health.engine", mock_engine):
        response = await client.get("/health/ready")

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ready"
    assert data["db"] == "connected"


@pytest.mark.asyncio
async def test_readiness_returns_503_when_db_unreachable(client):
    """GET /health/ready returns 503 when DB is unreachable."""
    mock_engine = _mock_engine_disconnected()

    with patch("nexus.api.routes.health.engine", mock_engine):
        response = await client.get("/health/ready")

    assert response.status_code == 503
    data = response.json()
    assert data["status"] == "not_ready"
    assert data["db"] == "disconnected"


@pytest.mark.asyncio
async def test_health_comprehensive_status(client):
    """GET /health returns comprehensive status with all expected fields."""
    mock_engine = _mock_engine_connected()

    with patch("nexus.api.routes.health.engine", mock_engine):
        response = await client.get("/health")

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
    assert "uptime_seconds" in data
    assert isinstance(data["uptime_seconds"], (int, float))
    assert data["uptime_seconds"] >= 0
    assert data["db"] == "connected"
    assert "memory_mb" in data
    assert isinstance(data["memory_mb"], (int, float))
    assert "version" in data
    assert data["version"]  # non-empty


@pytest.mark.asyncio
async def test_health_shows_degraded_when_db_fails(client):
    """GET /health shows degraded status when DB is unreachable."""
    mock_engine = _mock_engine_disconnected()

    with patch("nexus.api.routes.health.engine", mock_engine):
        response = await client.get("/health")

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "degraded"
    assert data["db"] == "disconnected"


@pytest.mark.asyncio
async def test_cors_origins_not_wildcard():
    """CORS middleware should not use wildcard origins."""
    from nexus.config import settings

    origins = [o.strip() for o in settings.cors_origins.split(",")]
    assert "*" not in origins
    assert len(origins) > 0
    for origin in origins:
        assert origin.startswith("http")
