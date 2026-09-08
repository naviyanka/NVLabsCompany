"""Tests for health check and readiness probe endpoints."""

from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from nexus.config import settings
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
    """GET /health/ready returns 200 when DB is reachable.

    Readiness now covers every dependency, so this test isolates the database
    dimension by switching the others off rather than relying on the
    developer's environment having Redis and Temporal running.
    """
    mock_engine = _mock_engine_connected()

    with patch("nexus.api.routes.health.engine", mock_engine):
        with patch.object(settings, "redis_url", None), \
             patch("nexus.api.routes.health.is_temporal_enabled", return_value=False):
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
        with patch.object(settings, "redis_url", None), \
             patch("nexus.api.routes.health.is_temporal_enabled", return_value=False):
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


class TestTemporalWorkerReadiness:
    """Readiness must distinguish "server reachable" from "work will actually run".

    With ``USE_TEMPORAL=true``, a reachable Temporal server and no worker polling
    the task queue means every workflow the application starts is accepted and
    then sits queued forever. The API reports success and nothing executes, which
    is the one failure mode a readiness probe has to catch.

    These patch the client rather than reaching a real server, so the suite stays
    offline regardless of the developer's own ``USE_TEMPORAL`` setting.
    """

    @staticmethod
    def _client_with_pollers(count: int):
        """A stand-in Temporal client whose task queue reports ``count`` pollers."""
        from unittest.mock import MagicMock

        response = MagicMock()
        response.pollers = [MagicMock() for _ in range(count)]

        client = MagicMock()
        client.namespace = "default"
        client.workflow_service.describe_task_queue = AsyncMock(return_value=response)
        return client

    @pytest.mark.asyncio
    async def test_disabled_temporal_is_ready(self):
        """An integration that is switched off cannot be unready."""
        from nexus.api.routes.health import _check_temporal_health

        with patch("nexus.api.routes.health.is_temporal_enabled", return_value=False):
            result = await _check_temporal_health()

        assert result["status"] == "disabled"

    @pytest.mark.asyncio
    async def test_worker_present_is_connected(self):
        """A polled task queue reports connected, with the worker count."""
        from nexus.api.routes.health import _check_temporal_health

        with patch("nexus.api.routes.health.is_temporal_enabled", return_value=True):
            with patch(
                "nexus.temporal.client._get_client",
                AsyncMock(return_value=self._client_with_pollers(1)),
            ):
                result = await _check_temporal_health()

        assert result["status"] == "connected"
        assert result["workers"] == 1
        assert result["task_queue"] == "nexus-main"

    @pytest.mark.asyncio
    async def test_no_worker_is_reported_not_ready(self):
        """Zero pollers is the queue-to-nowhere state and must not read as ready."""
        from nexus.api.routes.health import _check_temporal_health

        with patch("nexus.api.routes.health.is_temporal_enabled", return_value=True):
            with patch(
                "nexus.temporal.client._get_client",
                AsyncMock(return_value=self._client_with_pollers(0)),
            ):
                result = await _check_temporal_health()

        assert result["status"] == "no_workers"
        assert result["workers"] == 0
        # The message has to tell a developer what to do about it.
        assert "no worker is polling" in result["error"]
        assert "nexus.temporal.worker" in result["error"]

    @pytest.mark.asyncio
    async def test_readiness_endpoint_returns_503_without_a_worker(self, client):
        """The endpoint, not just the helper, fails when nothing would execute."""
        mock_engine = _mock_engine_connected()

        with patch("nexus.api.routes.health.engine", mock_engine):
            with patch.object(settings, "redis_url", None), patch(
                "nexus.api.routes.health.is_temporal_enabled", return_value=True
            ):
                with patch(
                    "nexus.temporal.client._get_client",
                    AsyncMock(return_value=self._client_with_pollers(0)),
                ):
                    response = await client.get("/health/ready")

        assert response.status_code == 503
        data = response.json()
        assert data["status"] == "not_ready"
        assert data["components"]["temporal"]["status"] == "no_workers"

    @pytest.mark.asyncio
    async def test_readiness_endpoint_returns_200_with_a_worker(self, client):
        """The same endpoint is ready once a worker is polling."""
        mock_engine = _mock_engine_connected()

        with patch("nexus.api.routes.health.engine", mock_engine):
            with patch.object(settings, "redis_url", None), patch(
                "nexus.api.routes.health.is_temporal_enabled", return_value=True
            ):
                with patch(
                    "nexus.temporal.client._get_client",
                    AsyncMock(return_value=self._client_with_pollers(2)),
                ):
                    response = await client.get("/health/ready")

        assert response.status_code == 200
        assert response.json()["components"]["temporal"]["workers"] == 2

    @pytest.mark.asyncio
    async def test_unreachable_frontend_is_disconnected(self):
        """A server that cannot be reached is a different failure from no worker."""
        from nexus.api.routes.health import _check_temporal_health

        with patch("nexus.api.routes.health.is_temporal_enabled", return_value=True):
            with patch("nexus.temporal.client._get_client", AsyncMock(return_value=None)):
                result = await _check_temporal_health()

        assert result["status"] == "disconnected"

    @pytest.mark.asyncio
    async def test_slow_probe_does_not_hang_readiness(self):
        """An inconclusive probe reports unknown rather than blocking or failing.

        A readiness endpoint that waits on a slow control-plane RPC is its own
        outage, and a timeout is not evidence that the worker is missing.
        """
        import asyncio

        from nexus.api.routes.health import _check_temporal_health

        async def never_answers(*args, **kwargs):
            await asyncio.sleep(60)

        client = self._client_with_pollers(1)
        client.workflow_service.describe_task_queue = never_answers

        with patch("nexus.api.routes.health.is_temporal_enabled", return_value=True):
            with patch("nexus.temporal.client._get_client", AsyncMock(return_value=client)):
                with patch("nexus.api.routes.health._POLLER_PROBE_TIMEOUT", 0.05):
                    result = await asyncio.wait_for(_check_temporal_health(), timeout=5)

        assert result["status"] == "connected"
        assert result["workers"] == "unknown"

    @pytest.mark.asyncio
    async def test_probe_failure_does_not_fail_readiness(self):
        """If the probe itself errors, do not claim the worker is missing."""
        from nexus.api.routes.health import _check_temporal_health

        client = self._client_with_pollers(1)
        client.workflow_service.describe_task_queue = AsyncMock(
            side_effect=RuntimeError("control plane unavailable")
        )

        with patch("nexus.api.routes.health.is_temporal_enabled", return_value=True):
            with patch("nexus.temporal.client._get_client", AsyncMock(return_value=client)):
                result = await _check_temporal_health()

        assert result["status"] == "connected"
        assert result["workers"] == "unknown"
