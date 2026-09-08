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


class TestSchemaCurrency:
    """Startup must not silently accept a stale SQLite dev schema.

    The lifespan runs ``create_all`` for SQLite, which creates missing tables but
    never ALTERs an existing one. A developer who pulls a migration adding a
    column to a table that already exists therefore gets a database that looks
    healthy and fails only when that column is read.
    """

    @staticmethod
    def _dev_db(tmp_path, revision):
        """A SQLite database at model shape, optionally stamped at ``revision``."""
        import sqlite3

        from sqlalchemy import create_engine
        from sqlmodel import SQLModel

        import nexus.models  # noqa: F401 - register every model

        path = tmp_path / "dev.db"
        SQLModel.metadata.create_all(create_engine(f"sqlite:///{path}"))
        con = sqlite3.connect(path)
        con.execute("CREATE TABLE IF NOT EXISTS alembic_version (version_num VARCHAR(32))")
        if revision is not None:
            con.execute("INSERT INTO alembic_version (version_num) VALUES (?)", (revision,))
        else:
            con.execute("DROP TABLE alembic_version")
        con.commit()
        con.close()
        return path

    @staticmethod
    def _head():
        from pathlib import Path

        from alembic.config import Config
        from alembic.script import ScriptDirectory

        root = Path(__file__).resolve().parent.parent
        return ScriptDirectory.from_config(Config(str(root / "alembic.ini"))).get_heads()[0]

    @pytest.mark.asyncio
    async def test_warns_when_dev_db_is_behind_head(
        self, tmp_path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """A database stamped at an older revision is called out by name."""
        path = self._dev_db(tmp_path, "c2f9a4d81b70")

        with patch("nexus.config_validator.settings") as mock_settings:
            mock_settings.database_url = f"sqlite+aiosqlite:///{path.as_posix()}"
            with patch("nexus.database.engine", _engine_for(path)):
                with caplog.at_level(logging.WARNING):
                    from nexus.config_validator import _check_schema_currency
                    await _check_schema_currency()

        assert "c2f9a4d81b70" in caplog.text
        assert "alembic upgrade head" in caplog.text

    @pytest.mark.asyncio
    async def test_warns_when_dev_db_has_no_migration_history(
        self, tmp_path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """A create_all-only database has unknown history, which is worth saying."""
        path = self._dev_db(tmp_path, None)

        with patch("nexus.config_validator.settings") as mock_settings:
            mock_settings.database_url = f"sqlite+aiosqlite:///{path.as_posix()}"
            with patch("nexus.database.engine", _engine_for(path)):
                with caplog.at_level(logging.WARNING):
                    from nexus.config_validator import _check_schema_currency
                    await _check_schema_currency()

        assert "no alembic_version table" in caplog.text

    @pytest.mark.asyncio
    async def test_silent_when_dev_db_is_at_head(
        self, tmp_path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """A current database must not nag on every startup."""
        path = self._dev_db(tmp_path, self._head())

        with patch("nexus.config_validator.settings") as mock_settings:
            mock_settings.database_url = f"sqlite+aiosqlite:///{path.as_posix()}"
            with patch("nexus.database.engine", _engine_for(path)):
                with caplog.at_level(logging.WARNING):
                    from nexus.config_validator import _check_schema_currency
                    await _check_schema_currency()

        assert "Alembic revision" not in caplog.text
        assert "no alembic_version" not in caplog.text

    @pytest.mark.asyncio
    async def test_postgres_is_exempt(self, caplog: pytest.LogCaptureFixture) -> None:
        """PostgreSQL is migration-managed and has no create_all path to drift from."""
        with patch("nexus.config_validator.settings") as mock_settings:
            mock_settings.database_url = "postgresql+asyncpg://user:pass@localhost:5432/db"
            with caplog.at_level(logging.WARNING):
                from nexus.config_validator import _check_schema_currency
                await _check_schema_currency()

        assert caplog.text == ""

    @pytest.mark.asyncio
    async def test_never_raises_when_alembic_is_unreadable(
        self, tmp_path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """The check is advisory: a broken lookup must not block startup."""
        path = self._dev_db(tmp_path, "c2f9a4d81b70")

        with patch("nexus.config_validator.settings") as mock_settings:
            mock_settings.database_url = f"sqlite+aiosqlite:///{path.as_posix()}"
            with patch(
                "alembic.script.ScriptDirectory.from_config",
                side_effect=RuntimeError("alembic.ini missing"),
            ):
                from nexus.config_validator import _check_schema_currency
                await _check_schema_currency()  # must not raise


def _engine_for(path):
    """An async engine bound to ``path``, for patching nexus.database.engine."""
    from sqlalchemy.ext.asyncio import create_async_engine

    return create_async_engine(f"sqlite+aiosqlite:///{path.as_posix()}")
