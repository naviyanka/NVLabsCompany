"""Tests for the degradation dashboard endpoint."""

from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from nexus.api.routes.degradation import (
    _check_docker,
    _check_embedding,
    _check_llm,
    _check_mempalace,
    _check_redis,
    router,
)
import nexus.api.routes.degradation as degradation_module


@pytest.fixture(autouse=True)
def reset_redis_singleton():
    """Reset the module-level Redis client singleton between tests."""
    degradation_module._redis_client = None
    degradation_module._redis_client_initialized = False
    yield
    degradation_module._redis_client = None
    degradation_module._redis_client_initialized = False


class TestCheckRedis:
    """Tests for Redis connectivity check."""

    async def test_redis_available(self) -> None:
        """Test Redis check when connection succeeds."""
        with patch("redis.asyncio.from_url") as mock_from_url:
            mock_redis = AsyncMock()
            mock_redis.ping = AsyncMock(return_value=True)
            mock_from_url.return_value = mock_redis

            result = await _check_redis()
            assert result["status"] == "full"
            assert "PING" in result["detail"]

    async def test_redis_unavailable(self) -> None:
        """Test Redis check when connection fails."""
        with patch("redis.asyncio.from_url") as mock_from_url:
            mock_redis = AsyncMock()
            mock_redis.ping = AsyncMock(side_effect=ConnectionError("refused"))
            mock_from_url.return_value = mock_redis

            result = await _check_redis()
            assert result["status"] == "unavailable"

    async def test_redis_import_error(self) -> None:
        """Test Redis check when redis module raises."""
        with patch(
            "redis.asyncio.from_url",
            side_effect=Exception("cannot connect"),
        ):
            result = await _check_redis()
            assert result["status"] == "unavailable"


class TestCheckDocker:
    """Tests for Docker availability check."""

    def test_docker_available(self) -> None:
        """Test Docker check when binary is found."""
        with patch("shutil.which", return_value="/usr/bin/docker"):
            result = _check_docker()
            assert result["status"] == "full"
            assert "/usr/bin/docker" in result["detail"]

    def test_docker_not_available(self) -> None:
        """Test Docker check when binary is not found."""
        with patch("shutil.which", return_value=None):
            result = _check_docker()
            assert result["status"] == "unavailable"


class TestCheckLLM:
    """Tests for LLM provider check."""

    def test_both_keys_configured(self) -> None:
        """Test LLM check with both API keys set."""
        with patch(
            "nexus.api.routes.degradation.settings"
        ) as mock_settings:
            mock_settings.openai_api_key = "sk-test"
            mock_settings.anthropic_api_key = "sk-ant-test"

            result = _check_llm()
            assert result["status"] == "full"
            assert "Both" in result["detail"]

    def test_only_openai_configured(self) -> None:
        """Test LLM check with only OpenAI key set."""
        with patch(
            "nexus.api.routes.degradation.settings"
        ) as mock_settings:
            mock_settings.openai_api_key = "sk-test"
            mock_settings.anthropic_api_key = ""

            result = _check_llm()
            assert result["status"] == "degraded"
            assert "OpenAI" in result["detail"]

    def test_only_anthropic_configured(self) -> None:
        """Test LLM check with only Anthropic key set."""
        with patch(
            "nexus.api.routes.degradation.settings"
        ) as mock_settings:
            mock_settings.openai_api_key = ""
            mock_settings.anthropic_api_key = "sk-ant-test"

            result = _check_llm()
            assert result["status"] == "degraded"
            assert "Anthropic" in result["detail"]

    def test_no_keys_configured(self) -> None:
        """Test LLM check with no API keys set."""
        with patch(
            "nexus.api.routes.degradation.settings"
        ) as mock_settings:
            mock_settings.openai_api_key = ""
            mock_settings.anthropic_api_key = ""

            result = _check_llm()
            assert result["status"] == "unavailable"


class TestCheckEmbedding:
    """Tests for embedding provider check."""

    def test_embedding_available(self) -> None:
        """Test embedding check with OpenAI key configured."""
        with patch(
            "nexus.api.routes.degradation.settings"
        ) as mock_settings:
            mock_settings.openai_api_key = "sk-test"

            result = _check_embedding()
            assert result["status"] == "full"

    def test_embedding_unavailable(self) -> None:
        """Test embedding check with no API key."""
        with patch(
            "nexus.api.routes.degradation.settings"
        ) as mock_settings:
            mock_settings.openai_api_key = ""

            result = _check_embedding()
            assert result["status"] == "unavailable"


class TestCheckMempalace:
    """Tests for mempalace availability check."""

    def test_mempalace_available(self) -> None:
        """Test mempalace check when module is importable."""
        result = _check_mempalace()
        assert result["status"] == "full"


class TestDegradationEndpoint:
    """Integration tests for the GET /system/degradation endpoint."""

    async def test_endpoint_returns_structured_json(self) -> None:
        """Test that the endpoint returns proper structured JSON."""
        from fastapi import FastAPI

        app = FastAPI()
        app.include_router(router)

        with (
            patch("redis.asyncio.from_url") as mock_from_url,
            patch("shutil.which", return_value="/usr/bin/docker"),
            patch(
                "nexus.api.routes.degradation.settings"
            ) as mock_settings,
        ):
            mock_redis = AsyncMock()
            mock_redis.ping = AsyncMock(return_value=True)
            mock_from_url.return_value = mock_redis
            mock_settings.redis_url = "redis://localhost:6379/0"
            mock_settings.openai_api_key = "sk-test"
            mock_settings.anthropic_api_key = "sk-ant"

            async with AsyncClient(
                transport=ASGITransport(app=app),
                base_url="http://test",
            ) as client:
                response = await client.get("/system/degradation")

            assert response.status_code == 200
            data = response.json()
            assert "overall_status" in data
            assert "features" in data
            assert "redis" in data["features"]
            assert "docker" in data["features"]
            assert "llm" in data["features"]
            assert "embedding" in data["features"]
            assert "mempalace" in data["features"]

    async def test_endpoint_degraded_when_redis_down(self) -> None:
        """Test that overall status is degraded when Redis is unavailable."""
        from fastapi import FastAPI

        app = FastAPI()
        app.include_router(router)

        with (
            patch("redis.asyncio.from_url") as mock_from_url,
            patch("shutil.which", return_value=None),
            patch(
                "nexus.api.routes.degradation.settings"
            ) as mock_settings,
        ):
            mock_redis = AsyncMock()
            mock_redis.ping = AsyncMock(
                side_effect=ConnectionError("refused")
            )
            mock_from_url.return_value = mock_redis
            mock_settings.redis_url = "redis://localhost:6379/0"
            mock_settings.openai_api_key = ""
            mock_settings.anthropic_api_key = ""

            async with AsyncClient(
                transport=ASGITransport(app=app),
                base_url="http://test",
            ) as client:
                response = await client.get("/system/degradation")

            assert response.status_code == 200
            data = response.json()
            assert data["overall_status"] == "degraded"
            assert data["features"]["redis"]["status"] == "unavailable"

    async def test_each_feature_has_status_and_detail(self) -> None:
        """Test that each feature in the response has status and detail."""
        from fastapi import FastAPI

        app = FastAPI()
        app.include_router(router)

        with (
            patch("redis.asyncio.from_url") as mock_from_url,
            patch("shutil.which", return_value=None),
            patch(
                "nexus.api.routes.degradation.settings"
            ) as mock_settings,
        ):
            mock_redis = AsyncMock()
            mock_redis.ping = AsyncMock(return_value=True)
            mock_from_url.return_value = mock_redis
            mock_settings.redis_url = "redis://localhost:6379/0"
            mock_settings.openai_api_key = "sk-test"
            mock_settings.anthropic_api_key = ""

            async with AsyncClient(
                transport=ASGITransport(app=app),
                base_url="http://test",
            ) as client:
                response = await client.get("/system/degradation")

            data = response.json()
            for feature_name, feature_data in data["features"].items():
                assert "status" in feature_data, (
                    f"{feature_name} missing status"
                )
                assert "detail" in feature_data, (
                    f"{feature_name} missing detail"
                )
                assert feature_data["status"] in (
                    "full",
                    "degraded",
                    "unavailable",
                )
