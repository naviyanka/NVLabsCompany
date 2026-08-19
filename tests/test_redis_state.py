"""Tests for Redis-backed State Backend (nexus.governance.redis_state)."""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from nexus.governance.redis_state import (
    FileStateBackend,
    RedisStateBackend,
    StateBackend,
    create_state_backend,
)


class TestFileStateBackend:
    """Tests for the file-based state backend."""

    async def test_set_and_get(self, tmp_path: Path) -> None:
        """Test basic set and get operations."""
        backend = FileStateBackend(tmp_path / "state")
        await backend.set("key1", {"hello": "world"})
        result = await backend.get("key1")
        assert result == {"hello": "world"}

    async def test_get_nonexistent_key(self, tmp_path: Path) -> None:
        """Test that getting a nonexistent key returns None."""
        backend = FileStateBackend(tmp_path / "state")
        result = await backend.get("nonexistent")
        assert result is None

    async def test_delete_existing_key(self, tmp_path: Path) -> None:
        """Test deleting an existing key returns True."""
        backend = FileStateBackend(tmp_path / "state")
        await backend.set("key1", "value1")
        result = await backend.delete("key1")
        assert result is True
        assert await backend.get("key1") is None

    async def test_delete_nonexistent_key(self, tmp_path: Path) -> None:
        """Test deleting a nonexistent key returns False."""
        backend = FileStateBackend(tmp_path / "state")
        result = await backend.delete("nonexistent")
        assert result is False

    async def test_list_keys(self, tmp_path: Path) -> None:
        """Test listing all keys."""
        backend = FileStateBackend(tmp_path / "state")
        await backend.set("alpha", 1)
        await backend.set("beta", 2)
        await backend.set("gamma", 3)
        keys = await backend.list_keys()
        assert len(keys) == 3
        assert set(keys) == {"alpha", "beta", "gamma"}

    async def test_list_keys_with_pattern(self, tmp_path: Path) -> None:
        """Test listing keys with a glob pattern."""
        backend = FileStateBackend(tmp_path / "state")
        await backend.set("user:1", "a")
        await backend.set("user:2", "b")
        await backend.set("config:x", "c")
        keys = await backend.list_keys("user:*")
        assert len(keys) == 2

    async def test_set_overwrites_value(self, tmp_path: Path) -> None:
        """Test that setting a key again overwrites the value."""
        backend = FileStateBackend(tmp_path / "state")
        await backend.set("key1", "value1")
        await backend.set("key1", "value2")
        result = await backend.get("key1")
        assert result == "value2"

    async def test_stores_complex_values(self, tmp_path: Path) -> None:
        """Test storing complex JSON-serializable values."""
        backend = FileStateBackend(tmp_path / "state")
        value = {"nested": {"list": [1, 2, 3], "null": None}}
        await backend.set("complex", value)
        result = await backend.get("complex")
        assert result == value

    async def test_conforms_to_protocol(self, tmp_path: Path) -> None:
        """Test that FileStateBackend conforms to StateBackend protocol."""
        backend = FileStateBackend(tmp_path / "state")
        assert isinstance(backend, StateBackend)


class TestRedisStateBackend:
    """Tests for the Redis-backed state backend with mocked Redis."""

    async def test_get_success(self) -> None:
        """Test successful get from Redis."""
        with patch("redis.asyncio.from_url") as mock_from_url:
            mock_redis = AsyncMock()
            mock_redis.get = AsyncMock(return_value='{"key": "value"}')
            mock_from_url.return_value = mock_redis

            backend = RedisStateBackend("redis://localhost:6379/0")
            result = await backend.get("test_key")
            assert result == {"key": "value"}

    async def test_get_returns_none_for_missing_key(self) -> None:
        """Test that get returns None for missing keys."""
        with patch("redis.asyncio.from_url") as mock_from_url:
            mock_redis = AsyncMock()
            mock_redis.get = AsyncMock(return_value=None)
            mock_from_url.return_value = mock_redis

            backend = RedisStateBackend("redis://localhost:6379/0")
            result = await backend.get("missing")
            assert result is None

    async def test_set_without_ttl(self) -> None:
        """Test setting a value without TTL."""
        with patch("redis.asyncio.from_url") as mock_from_url:
            mock_redis = AsyncMock()
            mock_redis.set = AsyncMock()
            mock_from_url.return_value = mock_redis

            backend = RedisStateBackend("redis://localhost:6379/0")
            await backend.set("key1", {"data": 42})
            mock_redis.set.assert_called_once()

    async def test_set_with_ttl(self) -> None:
        """Test setting a value with TTL."""
        with patch("redis.asyncio.from_url") as mock_from_url:
            mock_redis = AsyncMock()
            mock_redis.setex = AsyncMock()
            mock_from_url.return_value = mock_redis

            backend = RedisStateBackend("redis://localhost:6379/0")
            await backend.set("key1", "val", ttl=60)
            mock_redis.setex.assert_called_once()

    async def test_delete_existing(self) -> None:
        """Test deleting an existing key."""
        with patch("redis.asyncio.from_url") as mock_from_url:
            mock_redis = AsyncMock()
            mock_redis.delete = AsyncMock(return_value=1)
            mock_from_url.return_value = mock_redis

            backend = RedisStateBackend("redis://localhost:6379/0")
            result = await backend.delete("key1")
            assert result is True

    async def test_delete_nonexistent(self) -> None:
        """Test deleting a nonexistent key."""
        with patch("redis.asyncio.from_url") as mock_from_url:
            mock_redis = AsyncMock()
            mock_redis.delete = AsyncMock(return_value=0)
            mock_from_url.return_value = mock_redis

            backend = RedisStateBackend("redis://localhost:6379/0")
            result = await backend.delete("missing")
            assert result is False

    async def test_graceful_degradation_on_error(self) -> None:
        """Test that operations return defaults when Redis fails."""
        with patch("redis.asyncio.from_url") as mock_from_url:
            mock_redis = AsyncMock()
            mock_redis.get = AsyncMock(side_effect=ConnectionError("down"))
            mock_from_url.return_value = mock_redis

            backend = RedisStateBackend("redis://localhost:6379/0")
            result = await backend.get("key1")
            assert result is None
            assert backend._available is False

    async def test_unavailable_state_skips_operations(self) -> None:
        """Test that operations are skipped when backend is unavailable within cooldown."""
        with patch("redis.asyncio.from_url") as mock_from_url:
            mock_redis = AsyncMock()
            # Recovery ping will fail, keeping backend unavailable
            mock_redis.ping = AsyncMock(side_effect=ConnectionError("down"))
            mock_from_url.return_value = mock_redis

            backend = RedisStateBackend(
                "redis://localhost:6379/0",
                recovery_cooldown_seconds=0.0,  # Zero cooldown triggers recovery
            )
            backend._available = False
            # Set failure time to now so cooldown has elapsed
            import time
            backend._last_failure_time = time.monotonic()

            assert await backend.get("key") is None
            await backend.set("key", "value")
            assert await backend.delete("key") is False
            assert await backend.list_keys() == []

    async def test_health_check_success(self) -> None:
        """Test health check when Redis is responsive."""
        with patch("redis.asyncio.from_url") as mock_from_url:
            mock_redis = AsyncMock()
            mock_redis.ping = AsyncMock(return_value=True)
            mock_from_url.return_value = mock_redis

            backend = RedisStateBackend("redis://localhost:6379/0")
            result = await backend.health_check()
            assert result is True
            assert backend._available is True

    async def test_health_check_failure(self) -> None:
        """Test health check when Redis is down."""
        with patch("redis.asyncio.from_url") as mock_from_url:
            mock_redis = AsyncMock()
            mock_redis.ping = AsyncMock(side_effect=ConnectionError("down"))
            mock_from_url.return_value = mock_redis

            backend = RedisStateBackend("redis://localhost:6379/0")
            result = await backend.health_check()
            assert result is False
            assert backend._available is False

    async def test_recovery_after_cooldown(self) -> None:
        """Test that backend recovers after cooldown period."""
        with patch("redis.asyncio.from_url") as mock_from_url:
            mock_redis = AsyncMock()
            mock_redis.ping = AsyncMock(return_value=True)
            mock_redis.get = AsyncMock(return_value='{"data": "hello"}')
            mock_from_url.return_value = mock_redis

            backend = RedisStateBackend(
                "redis://localhost:6379/0",
                recovery_cooldown_seconds=0.0,
            )
            # Simulate a failure
            backend._available = False
            import time
            backend._last_failure_time = time.monotonic() - 1.0

            # After cooldown elapsed, should recover
            result = await backend.get("key")
            assert result == {"data": "hello"}
            assert backend._available is True

    async def test_no_recovery_within_cooldown(self) -> None:
        """Test that backend does not attempt recovery within cooldown."""
        with patch("redis.asyncio.from_url") as mock_from_url:
            mock_redis = AsyncMock()
            mock_redis.ping = AsyncMock(return_value=True)
            mock_from_url.return_value = mock_redis

            backend = RedisStateBackend(
                "redis://localhost:6379/0",
                recovery_cooldown_seconds=9999.0,
            )
            # Simulate a recent failure
            backend._available = False
            import time
            backend._last_failure_time = time.monotonic()

            # Should not recover - cooldown not elapsed
            result = await backend.get("key")
            assert result is None
            assert backend._available is False

    async def test_conforms_to_protocol(self) -> None:
        """Test that RedisStateBackend conforms to StateBackend protocol."""
        with patch("redis.asyncio.from_url"):
            backend = RedisStateBackend("redis://localhost:6379/0")
            assert isinstance(backend, StateBackend)


class TestCreateStateBackend:
    """Tests for the factory function."""

    async def test_creates_redis_backend_when_available(self) -> None:
        """Test that factory returns Redis backend when available."""
        with patch("redis.asyncio.from_url") as mock_from_url:
            mock_redis = AsyncMock()
            mock_redis.ping = AsyncMock(return_value=True)
            mock_from_url.return_value = mock_redis

            backend = await create_state_backend(redis_url="redis://localhost:6379/0")
            assert isinstance(backend, RedisStateBackend)

    async def test_falls_back_to_file_when_redis_unavailable(
        self, tmp_path: Path
    ) -> None:
        """Test that factory falls back to file backend when Redis fails."""
        with patch("redis.asyncio.from_url") as mock_from_url:
            mock_redis = AsyncMock()
            mock_redis.ping = AsyncMock(side_effect=ConnectionError("down"))
            mock_from_url.return_value = mock_redis

            backend = await create_state_backend(
                redis_url="redis://localhost:6379/0",
                file_path=tmp_path / "state",
            )
            assert isinstance(backend, FileStateBackend)

    async def test_creates_file_backend_when_no_redis_url(
        self, tmp_path: Path
    ) -> None:
        """Test that factory returns file backend when no Redis URL given."""
        backend = await create_state_backend(file_path=tmp_path / "state")
        assert isinstance(backend, FileStateBackend)
