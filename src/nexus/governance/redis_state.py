"""Redis-backed State Backend for horizontal scaling.

Provides a StateBackend Protocol with two implementations:
- RedisStateBackend: Uses redis.asyncio for distributed state.
- FileStateBackend: Uses atomic JSON file writes for single-node operation.

A factory function selects the appropriate backend based on Redis availability.
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

logger = logging.getLogger(__name__)


@runtime_checkable
class StateBackend(Protocol):
    """Protocol defining the state backend interface.

    All methods are async to support both file-based and Redis-based
    implementations transparently.
    """

    async def get(self, key: str) -> Any | None:
        """Retrieve a value by key.

        Args:
            key: The key to look up.

        Returns:
            The stored value, or None if the key does not exist.
        """
        ...

    async def set(self, key: str, value: Any, ttl: int | None = None) -> None:
        """Store a value under the given key.

        Args:
            key: The key to store under.
            value: The value to store (must be JSON-serializable).
            ttl: Optional time-to-live in seconds. None means no expiry.
        """
        ...

    async def delete(self, key: str) -> bool:
        """Delete a key from the store.

        Args:
            key: The key to delete.

        Returns:
            True if the key existed and was deleted, False otherwise.
        """
        ...

    async def list_keys(self, pattern: str = "*") -> list[str]:
        """List keys matching a pattern.

        Args:
            pattern: Glob-style pattern for key matching. Default is '*' (all keys).

        Returns:
            List of matching key strings.
        """
        ...


class RedisStateBackend:
    """Redis-backed state backend for distributed/multi-process state.

    Uses redis.asyncio with JSON serialization for values. Falls back
    gracefully when Redis becomes unavailable after initialization.
    After a failure, the backend will attempt to reconnect after a
    configurable cooldown period rather than staying permanently disabled.
    """

    def __init__(
        self,
        redis_url: str,
        key_prefix: str = "nexus:state",
        recovery_cooldown_seconds: float = 30.0,
    ) -> None:
        """Initialize with a Redis connection URL.

        Args:
            redis_url: Redis connection string (redis://host:port/db).
            key_prefix: Prefix for all keys in this backend.
            recovery_cooldown_seconds: Seconds to wait before retrying
                after a failure. Default is 30 seconds.
        """
        import time as _time

        import redis.asyncio as aioredis

        self._redis = aioredis.from_url(
            redis_url,
            decode_responses=True,
            socket_connect_timeout=2.0,
            socket_timeout=2.0,
        )
        self._prefix = key_prefix
        self._available = True
        self._recovery_cooldown = recovery_cooldown_seconds
        self._last_failure_time: float = 0.0

    def _full_key(self, key: str) -> str:
        """Build the full Redis key with prefix."""
        return f"{self._prefix}:{key}"

    async def _check_recovery(self) -> bool:
        """Check whether enough time has passed to attempt recovery.

        If the backend is unavailable and the cooldown has elapsed, tries
        a PING to re-enable operations.

        Returns:
            True if the backend is available (or recovered), False otherwise.
        """
        import time as _time

        if self._available:
            return True

        elapsed = _time.monotonic() - self._last_failure_time
        if elapsed < self._recovery_cooldown:
            return False

        # Attempt recovery via health check
        try:
            result = await self._redis.ping()
            if result:
                self._available = True
                logger.info("Redis state backend recovered after cooldown")
                return True
        except Exception:
            # Reset the failure timer so we wait another cooldown period
            self._last_failure_time = _time.monotonic()
        return False

    def _mark_unavailable(self) -> None:
        """Mark the backend as unavailable and record the failure time."""
        import time as _time

        self._available = False
        self._last_failure_time = _time.monotonic()

    async def get(self, key: str) -> Any | None:
        """Retrieve a value by key from Redis.

        Args:
            key: The key to look up.

        Returns:
            The deserialized value, or None if missing or Redis unavailable.
        """
        if not await self._check_recovery():
            return None
        try:
            raw = await self._redis.get(self._full_key(key))
            if raw is None:
                return None
            return json.loads(raw)
        except Exception as exc:
            logger.warning("Redis state get failed: %s", exc)
            self._mark_unavailable()
            return None

    async def set(self, key: str, value: Any, ttl: int | None = None) -> None:
        """Store a JSON-serialized value in Redis.

        Args:
            key: The key to store under.
            value: The value to store (must be JSON-serializable).
            ttl: Optional time-to-live in seconds.
        """
        if not await self._check_recovery():
            return
        try:
            full_key = self._full_key(key)
            serialized = json.dumps(value)
            if ttl is not None:
                await self._redis.setex(full_key, ttl, serialized)
            else:
                await self._redis.set(full_key, serialized)
        except Exception as exc:
            logger.warning("Redis state set failed: %s", exc)
            self._mark_unavailable()

    async def delete(self, key: str) -> bool:
        """Delete a key from Redis.

        Args:
            key: The key to delete.

        Returns:
            True if the key was deleted, False otherwise.
        """
        if not await self._check_recovery():
            return False
        try:
            result = await self._redis.delete(self._full_key(key))
            return result > 0
        except Exception as exc:
            logger.warning("Redis state delete failed: %s", exc)
            self._mark_unavailable()
            return False

    async def list_keys(self, pattern: str = "*") -> list[str]:
        """List keys matching a glob pattern in Redis.

        Args:
            pattern: Glob-style pattern for key matching.

        Returns:
            List of matching keys (without the prefix).
        """
        if not await self._check_recovery():
            return []
        try:
            full_pattern = self._full_key(pattern)
            keys = []
            async for key in self._redis.scan_iter(match=full_pattern):
                # Strip prefix to return bare keys
                bare = key[len(self._prefix) + 1:]
                keys.append(bare)
            return keys
        except Exception as exc:
            logger.warning("Redis state list_keys failed: %s", exc)
            self._mark_unavailable()
            return []

    async def health_check(self) -> bool:
        """Check if Redis is available.

        Returns:
            True if Redis responds to PING.
        """
        try:
            result = await self._redis.ping()
            self._available = True
            return bool(result)
        except Exception:
            self._mark_unavailable()
            return False


class FileStateBackend:
    """File-based state backend using atomic JSON writes.

    Stores each key as a separate JSON file in a directory. Uses the
    tempfile + os.replace pattern for atomic writes. TTL is not enforced
    (all entries persist indefinitely).

    Keys are encoded using percent-encoding (bijective) to avoid
    collisions between keys containing special characters.
    """

    def __init__(self, directory: Path) -> None:
        """Initialize with a storage directory.

        Args:
            directory: Path to the directory for storing state files.
        """
        self._dir = directory
        self._dir.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _encode_key(key: str) -> str:
        """Encode a key for safe filesystem use via percent-encoding.

        This is bijective: every unique key maps to a unique filename.
        Characters that are not alphanumeric, hyphens, or dots are
        percent-encoded.
        """
        from urllib.parse import quote

        return quote(key, safe=".-")

    @staticmethod
    def _decode_key(encoded: str) -> str:
        """Decode a percent-encoded filename back to the original key."""
        from urllib.parse import unquote

        return unquote(encoded)

    def _key_path(self, key: str) -> Path:
        """Convert a key to a filesystem path (safe for filenames)."""
        safe_key = self._encode_key(key)
        return self._dir / f"{safe_key}.json"

    async def get(self, key: str) -> Any | None:
        """Retrieve a value by key from the filesystem.

        Args:
            key: The key to look up.

        Returns:
            The deserialized value, or None if the file does not exist.
        """
        path = self._key_path(key)
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text())
            return data.get("value")
        except (json.JSONDecodeError, OSError):
            return None

    async def set(self, key: str, value: Any, ttl: int | None = None) -> None:
        """Store a value atomically as a JSON file.

        Args:
            key: The key to store under.
            value: The value to store (must be JSON-serializable).
            ttl: Ignored for file backend (no expiry support).
        """
        path = self._key_path(key)
        data = {"key": key, "value": value}
        fd, tmp = tempfile.mkstemp(dir=self._dir, suffix=".tmp")
        try:
            with os.fdopen(fd, "w") as f:
                json.dump(data, f)
            os.replace(tmp, path)
        except BaseException:
            if os.path.exists(tmp):
                os.unlink(tmp)
            raise

    async def delete(self, key: str) -> bool:
        """Delete a state file.

        Args:
            key: The key to delete.

        Returns:
            True if the file existed and was deleted, False otherwise.
        """
        path = self._key_path(key)
        if path.exists():
            path.unlink()
            return True
        return False

    async def list_keys(self, pattern: str = "*") -> list[str]:
        """List keys matching a glob pattern in the directory.

        Args:
            pattern: Glob-style pattern for key matching.

        Returns:
            List of matching key strings.
        """
        import fnmatch

        keys: list[str] = []
        for path in self._dir.glob("*.json"):
            # Reconstruct key from filename using percent-decoding
            key_name = self._decode_key(path.stem)
            if fnmatch.fnmatch(key_name, pattern):
                keys.append(key_name)
        return keys


async def create_state_backend(
    redis_url: str | None = None,
    file_path: Path | None = None,
) -> StateBackend:
    """Factory function to create the appropriate state backend.

    Tries Redis first if a URL is provided. Falls back to file-based
    backend if Redis is unavailable or no URL is given.

    Args:
        redis_url: Optional Redis connection URL.
        file_path: Optional directory for file-based state. Defaults to
            a 'state' subdirectory in the current working directory.

    Returns:
        A StateBackend instance (either Redis or File-based).
    """
    if redis_url:
        try:
            backend = RedisStateBackend(redis_url)
            if await backend.health_check():
                logger.info("Using Redis state backend")
                return backend
            logger.warning("Redis not reachable, falling back to file backend")
        except Exception as exc:
            logger.warning("Redis state init failed: %s. Using file backend.", exc)

    directory = file_path or Path("state")
    logger.info("Using file state backend at %s", directory)
    return FileStateBackend(directory)
