"""Configuration validation for NEXUS startup.

Validates application settings on startup and logs warnings for potential
issues. ``validate_config`` is non-blocking - it never raises, only logs
warnings. ``enforce_auth_policy`` is the one deliberate exception: it refuses to
start when authentication is disabled somewhere that is not allowed.
"""

import logging
import os
from pathlib import Path
from urllib.parse import urlparse

from nexus.config import settings

logger = logging.getLogger(__name__)


class ConfigurationError(RuntimeError):
    """Startup refused: ``code`` is stable and the message never carries a value."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code


# Time kept between the end of a webhook's model run and the end of its lease:
# recording the result, releasing the claim, and clock skew between workers.
WEBHOOK_TIMEOUT_MARGIN_SECONDS = 60.0


def webhook_timeout_refusal(timeout_seconds: float, lease_seconds: float) -> str | None:
    """Stable code when the webhook timeout cannot fit inside the lease, else ``None``.

    The timeout must be positive and, with the safety margin, strictly below the
    lease. Otherwise a run could outlive its claim and a second worker could take
    the delivery over while the first is still acting.
    """
    if not 0 < timeout_seconds or timeout_seconds != timeout_seconds:
        return "WEBHOOK_TIMEOUT_INVALID"
    if timeout_seconds + WEBHOOK_TIMEOUT_MARGIN_SECONDS >= lease_seconds:
        return "WEBHOOK_TIMEOUT_NOT_BELOW_LEASE"
    return None


def enforce_webhook_timeout_policy() -> None:
    """Refuse to start when the webhook timeout does not fit inside the lease."""
    from nexus.communication.webhook_idempotency import LEASE

    code = webhook_timeout_refusal(
        settings.webhook_processing_timeout_seconds, LEASE.total_seconds()
    )
    if code is None:
        return
    raise ConfigurationError(
        code,
        "WEBHOOK_PROCESSING_TIMEOUT_SECONDS must be positive and, with a "
        f"{WEBHOOK_TIMEOUT_MARGIN_SECONDS:.0f}s safety margin, below the "
        f"{LEASE.total_seconds():.0f}s webhook idempotency lease.",
    )


def enforce_auth_policy() -> None:
    """Refuse to start when ``AUTH_ENABLED=false`` is not allowed in this environment.

    Allowed: ``NEXUS_ENV=test``, or ``development`` with
    ``NEXUS_ALLOW_INSECURE_AUTH_DISABLED=true``. Production, staging and an unset
    or unknown environment always refuse. Raises before any request is served.
    The message names the setting, never a header, company id or credential.
    """
    code = settings.auth_disabled_refusal()
    if code is None:
        return
    raise ConfigurationError(
        code,
        "AUTH_ENABLED=false is not permitted in this environment. Set NEXUS_ENV to "
        "'test', or to 'development' together with NEXUS_ALLOW_INSECURE_AUTH_DISABLED=true; "
        "production and staging must keep authentication enabled.",
    )


def enforce_no_migration_credential() -> None:
    """Refuse to start a runtime process that holds the migrator credential.

    ``MIGRATION_DATABASE_URL`` belongs to the migration job alone. A runtime process that
    can read it could connect as the schema owner and drop triggers or disable row level
    security, which is exactly what the separate application role prevents. The message
    names the variable, never its value.
    """
    if os.environ.get("MIGRATION_DATABASE_URL"):
        raise ConfigurationError(
            "MIGRATION_CREDENTIAL_IN_RUNTIME",
            "MIGRATION_DATABASE_URL must be set only for the migration job, never for "
            "the API, worker or scheduler.",
        )


def enforce_no_system_credential() -> None:
    """Refuse to start a public-facing or ordinary worker process that holds the system role.

    ``SYSTEM_DATABASE_URL`` is the BYPASSRLS ``nexus_system`` credential. It belongs to the
    privileged system runtime (``python -m nexus.system_runtime``) alone. An API, worker or
    Temporal worker that can read it could be steered, by a bug or a prompt injection, into
    reading every tenant's rows. The message names the variable, never its value.
    """
    if os.environ.get("SYSTEM_DATABASE_URL"):
        raise ConfigurationError(
            "SYSTEM_CREDENTIAL_IN_RUNTIME",
            "SYSTEM_DATABASE_URL must be set only for the system runtime, never for the "
            "API or a worker.",
        )


async def validate_config() -> None:
    """Validate application configuration and log warnings.

    Checks performed:
    - Missing or empty API keys (openai_api_key, anthropic_api_key)
    - Database URL format validation
    - Authentication and CORS settings (wildcard origins, default secret key,
      disabled auth, insecure session cookies)
    - Redis connectivity (non-blocking, logs warning on failure)
    - Data directory writability (if configured via environment)
    - Schema currency against the Alembic head (SQLite dev databases)

    This function never raises exceptions or blocks startup. All issues
    are reported as log warnings.
    """
    _check_api_keys()
    _check_database_url()
    _check_auth_settings()
    await _check_redis_connectivity()
    _check_data_directory()
    await _check_schema_currency()
    logger.info("Configuration validation complete")


async def _check_schema_currency() -> None:
    """Warn when a SQLite dev database is behind the repository's migrations.

    The lifespan runs ``SQLModel.metadata.create_all`` for SQLite, which creates
    tables that do not exist yet but never ALTERs one that does. So a developer
    who pulls a migration adding a column to an existing table gets a database
    that looks fine and fails only when that column is read — the exact silent
    drift that had ``obsidian_documents`` missing its retry columns while the
    server reported healthy.

    PostgreSQL is exempt: it is managed through ``alembic upgrade head`` and has
    no create_all shortcut to drift from.

    Logs the resolution rather than fixing it, because a migration is a decision
    for a developer to make rather than something startup should do behind their
    back.
    """
    if not settings.database_url.startswith("sqlite"):
        return

    try:
        from alembic.config import Config
        from alembic.script import ScriptDirectory
        from sqlalchemy import inspect, text

        from nexus.database import engine

        root = Path(__file__).resolve().parent.parent.parent
        script = ScriptDirectory.from_config(Config(str(root / "alembic.ini")))
        heads = set(script.get_heads())

        async with engine.connect() as conn:
            names = await conn.run_sync(lambda c: inspect(c).get_table_names())
            if "alembic_version" not in names:
                # A create_all-built database with no migration history at all.
                if names:
                    logger.warning(
                        "Development database has no alembic_version table, so its "
                        "schema history is unknown. Run: alembic stamp head (if the "
                        "schema is current) or alembic upgrade head."
                    )
                return
            result = await conn.execute(text("SELECT version_num FROM alembic_version"))
            current = {row[0] for row in result}

        if current and current != heads:
            logger.warning(
                "Development database is at Alembic revision(s) %s but the "
                "repository head is %s. create_all does not add columns to "
                "existing tables, so the schema may be silently stale. Run: "
                "alembic upgrade head",
                ", ".join(sorted(current)) or "none",
                ", ".join(sorted(heads)),
            )
    except Exception as exc:  # noqa: BLE001 - this check must never block startup
        logger.debug("Schema currency check skipped: %s", exc)


def _check_auth_settings() -> None:
    """Warn about authentication and CORS misconfigurations.

    Cookie-based sessions are only safe when the browser is allowed to send
    credentials to an explicitly enumerated set of origins. A wildcard origin
    combined with allow_credentials=True is rejected by browsers outright and
    signals a misconfigured deployment, so it is called out loudly.
    """
    origins = [o.strip() for o in settings.cors_origins.split(",") if o.strip()]
    if not origins:
        logger.warning(
            "CORS_ORIGINS is empty - the dashboard will not be able to call the API"
        )
    if "*" in origins:
        logger.warning(
            "CORS_ORIGINS contains '*', which is incompatible with "
            "credentialed cookie authentication. List the dashboard origins "
            "explicitly instead."
        )

    if settings.secret_key == "dev-secret-key-change-in-production":
        logger.warning(
            "SECRET_KEY is still the built-in development default - "
            "set a unique value before exposing this deployment"
        )

    if settings.auth_bypass_active:
        logger.warning(
            "INSECURE: AUTH_ENABLED=false in NEXUS_ENV=%s - the API trusts the "
            "X-Company-Id header and every tenant is impersonable. Local "
            "development and tests only; never expose this process.",
            settings.environment,
        )

    if not settings.session_cookie_secure:
        logger.warning(
            "SESSION_COOKIE_SECURE is False - session cookies will be sent "
            "over plain HTTP"
        )


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
