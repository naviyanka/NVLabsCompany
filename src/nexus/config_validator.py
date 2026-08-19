"""Configuration validation for NEXUS startup.

Validates application settings on startup and logs warnings for potential
issues. Designed to be non-blocking - never raises exceptions or prevents
startup, only logs warnings to alert operators of misconfigurations.
"""

import logging
import os
from urllib.parse import urlparse

from nexus.config import settings

logger = logging.getLogger(__name__)


async def validate_config() -> None:
    """Validate application configuration and log warnings.

    Checks performed:
    - Missing or empty API keys (openai_api_key, anthropic_api_key)
    - Database URL format validation
    - Redis connectivity (non-blocking, logs warning on failure)
    - Data directory writability (if configured via environment)

    This function never raises exceptions or blocks startup. All issues
    are reported as log warnings.
    """
    _check_api_keys()
    _check_database_url()
    await _check_redis_connectivity()
    _check_data_directory()
    logger.info("Configuration validation complete")


def _check_api_keys() -> None:
    """Warn about missing or empty API keys."""
    if not settings.openai_api_key:
        logger.warning(
            "OPENAI_API_KEY is not set - OpenAI adapter will not function"
        )
    if not settings.anthropic_api_key:
        logger.warning(
            "ANTHROPIC_API_KEY is not set - Anthropic adapter will not function"
        )


def _check_database_url() -> None:
    """Validate database URL format."""
    db_url = settings.database_url
    if not db_url:
        logger.warning("DATABASE_URL is empty - database operations will fail")
        return

    try:
        parsed = urlparse(db_url)
        scheme = parsed.scheme.lower()
        valid_schemes = (
            "postgresql",
            "postgresql+asyncpg",
            "sqlite",
            "sqlite+aiosqlite",
        )
        if not any(scheme.startswith(s) for s in valid_schemes):
            logger.warning(
                "DATABASE_URL scheme '%s' may not be supported. "
                "Expected postgresql+asyncpg or sqlite+aiosqlite.",
                scheme,
            )
        if "postgresql" in scheme and not parsed.hostname:
            logger.warning(
                "DATABASE_URL appears to be missing a hostname"
            )
    except Exception as exc:
        logger.warning("DATABASE_URL could not be parsed: %s", exc)


async def _check_redis_connectivity() -> None:
    """Attempt Redis connection and log warning on failure.

    This check is non-blocking and best-effort. If Redis is not available,
    the application continues with degraded functionality (no caching).
    """
    redis_url = settings.redis_url
    if not redis_url:
        logger.warning("REDIS_URL is not set - caching will be unavailable")
        return

    try:
        import importlib
        redis_mod = importlib.import_module("redis.asyncio")
        client = redis_mod.from_url(redis_url, socket_connect_timeout=2)
        await client.ping()
        await client.aclose()
        logger.info("Redis connectivity check passed")
    except ImportError:
        logger.info(
            "redis package not installed - skipping connectivity check"
        )
    except Exception as exc:
        logger.warning(
            "Redis connectivity check failed (non-blocking): %s", exc
        )


def _check_data_directory() -> None:
    """Check that the data directory is writable if configured."""
    data_dir = os.environ.get("NEXUS_DATA_DIR", "")
    if not data_dir:
        return

    if not os.path.isdir(data_dir):
        logger.warning(
            "NEXUS_DATA_DIR '%s' does not exist or is not a directory",
            data_dir,
        )
        return

    if not os.access(data_dir, os.W_OK):
        logger.warning(
            "NEXUS_DATA_DIR '%s' is not writable", data_dir
        )
