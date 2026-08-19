"""Tests for the configuration validator module.

Verifies that validate_config() correctly identifies and warns about
misconfigurations without blocking application startup.
"""

import logging
from unittest.mock import AsyncMock, patch

import pytest


@pytest.mark.asyncio
async def test_validate_config_warns_missing_openai_key(caplog: pytest.LogCaptureFixture) -> None:
    """Warn when openai_api_key is empty."""
    with patch("nexus.config_validator.settings") as mock_settings:
        mock_settings.openai_api_key = ""
        mock_settings.anthropic_api_key = "sk-ant-test"
        mock_settings.database_url = "sqlite+aiosqlite:///test.db"
        mock_settings.redis_url = ""

        with caplog.at_level(logging.WARNING):
            from nexus.config_validator import validate_config
            await validate_config()

        assert "OPENAI_API_KEY is not set" in caplog.text


@pytest.mark.asyncio
async def test_validate_config_warns_missing_anthropic_key(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Warn when anthropic_api_key is empty."""
    with patch("nexus.config_validator.settings") as mock_settings:
        mock_settings.openai_api_key = "sk-test"
        mock_settings.anthropic_api_key = ""
        mock_settings.database_url = "sqlite+aiosqlite:///test.db"
        mock_settings.redis_url = ""

        with caplog.at_level(logging.WARNING):
            from nexus.config_validator import validate_config
            await validate_config()

        assert "ANTHROPIC_API_KEY is not set" in caplog.text


@pytest.mark.asyncio
async def test_validate_config_warns_invalid_db_scheme(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Warn about unsupported database URL schemes."""
    with patch("nexus.config_validator.settings") as mock_settings:
        mock_settings.openai_api_key = "sk-test"
        mock_settings.anthropic_api_key = "sk-ant-test"
        mock_settings.database_url = "mysql://localhost/db"
        mock_settings.redis_url = ""

        with caplog.at_level(logging.WARNING):
            from nexus.config_validator import validate_config
            await validate_config()

        assert "may not be supported" in caplog.text


@pytest.mark.asyncio
async def test_validate_config_warns_empty_db_url(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Warn when database URL is empty."""
    with patch("nexus.config_validator.settings") as mock_settings:
        mock_settings.openai_api_key = "sk-test"
        mock_settings.anthropic_api_key = "sk-ant-test"
        mock_settings.database_url = ""
        mock_settings.redis_url = ""

        with caplog.at_level(logging.WARNING):
            from nexus.config_validator import validate_config
            await validate_config()

        assert "DATABASE_URL is empty" in caplog.text


@pytest.mark.asyncio
async def test_validate_config_no_warnings_when_valid(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """No warnings when all configuration is valid."""
    with patch("nexus.config_validator.settings") as mock_settings:
        mock_settings.openai_api_key = "sk-test-key"
        mock_settings.anthropic_api_key = "sk-ant-test-key"
        mock_settings.database_url = "postgresql+asyncpg://user:pass@localhost:5432/db"
        mock_settings.redis_url = "redis://localhost:6379/0"

        # Mock Redis connectivity to succeed
        with patch("nexus.config_validator._check_redis_connectivity", new_callable=AsyncMock):
            with caplog.at_level(logging.WARNING):
                from nexus.config_validator import (
                    _check_api_keys,
                    _check_data_directory,
                    _check_database_url,
                )
                _check_api_keys()
                _check_database_url()
                _check_data_directory()

            warnings = [r for r in caplog.records if r.levelno >= logging.WARNING]
            assert len(warnings) == 0


@pytest.mark.asyncio
async def test_validate_config_does_not_raise() -> None:
    """validate_config never raises exceptions, regardless of config state."""
    with patch("nexus.config_validator.settings") as mock_settings:
        mock_settings.openai_api_key = ""
        mock_settings.anthropic_api_key = ""
        mock_settings.database_url = "not-a-valid-url"
        mock_settings.redis_url = "redis://nonexistent:6379"

        # Should not raise
        from nexus.config_validator import validate_config
        await validate_config()


@pytest.mark.asyncio
async def test_validate_config_redis_warning_on_failure(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Log warning when Redis is unreachable."""
    with patch("nexus.config_validator.settings") as mock_settings:
        mock_settings.openai_api_key = "sk-test"
        mock_settings.anthropic_api_key = "sk-ant-test"
        mock_settings.database_url = "sqlite+aiosqlite:///test.db"
        mock_settings.redis_url = "redis://nonexistent-host:6379"

        with caplog.at_level(logging.WARNING):
            from nexus.config_validator import validate_config
            await validate_config()

        # Either redis not installed or connection failed
        redis_logs = [
            r for r in caplog.records
            if "redis" in r.getMessage().lower() or "Redis" in r.getMessage()
        ]
        assert len(redis_logs) > 0


@pytest.mark.asyncio
async def test_validate_config_data_dir_warning(
    caplog: pytest.LogCaptureFixture, tmp_path,
) -> None:
    """Warn when NEXUS_DATA_DIR does not exist."""
    with patch("nexus.config_validator.settings") as mock_settings:
        mock_settings.openai_api_key = "sk-test"
        mock_settings.anthropic_api_key = "sk-ant-test"
        mock_settings.database_url = "sqlite+aiosqlite:///test.db"
        mock_settings.redis_url = ""

        fake_dir = str(tmp_path / "nonexistent_dir")
        with patch.dict("os.environ", {"NEXUS_DATA_DIR": fake_dir}):
            with caplog.at_level(logging.WARNING):
                from nexus.config_validator import validate_config
                await validate_config()

            assert "does not exist" in caplog.text


@pytest.mark.asyncio
async def test_validate_config_sqlite_url_accepted(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """SQLite URLs are accepted without warnings."""
    with patch("nexus.config_validator.settings") as mock_settings:
        mock_settings.openai_api_key = "sk-test"
        mock_settings.anthropic_api_key = "sk-ant-test"
        mock_settings.database_url = "sqlite+aiosqlite:///./nexus.db"
        mock_settings.redis_url = ""

        with caplog.at_level(logging.WARNING):
            from nexus.config_validator import validate_config
            await validate_config()

        db_warnings = [
            r for r in caplog.records
            if r.levelno >= logging.WARNING and "DATABASE" in r.getMessage()
        ]
        assert len(db_warnings) == 0
