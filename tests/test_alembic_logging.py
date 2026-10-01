"""In-process Alembic runs must leave application logging alone.

``alembic/env.py`` runs ``logging.config.fileConfig`` whenever the Config has an ini file.
Its default disables every logger that already exists, so a later test (or an embedded
upgrade) silently stops receiving that logger's records. ``env.py`` keeps existing loggers
enabled; these tests fail if that is undone.
"""

import asyncio
import logging
import uuid
from unittest.mock import MagicMock

import alembic.command
import alembic.config
import pytest
from sqlalchemy.exc import OperationalError

from nexus.knowledge.plaza import KnowledgePlaza

PLAZA = "nexus.knowledge.plaza"


@pytest.fixture
def keep_root_logging():
    """fileConfig also swaps the root handlers; put them back so this test does not leak."""
    root = logging.getLogger()
    handlers, level = list(root.handlers), root.level
    yield
    root.handlers[:] = handlers
    root.setLevel(level)


def _cfg(url: str) -> alembic.config.Config:
    cfg = alembic.config.Config("alembic.ini")  # the ini file is what triggers fileConfig
    cfg.set_main_option("sqlalchemy.url", url)
    return cfg


async def _subscriber_failure_is_logged() -> str:
    seen: list[str] = []

    class Collect(logging.Handler):
        def emit(self, record):
            seen.append(record.getMessage())

    handler = Collect(level=logging.ERROR)
    logger = logging.getLogger(PLAZA)
    logger.addHandler(handler)
    try:
        plaza = KnowledgePlaza(MagicMock())
        company = uuid.uuid4()
        plaza.subscribe(company, MagicMock(side_effect=ValueError("boom")))
        await plaza.notify_subscribers(company, company, "updated", company)
    finally:
        logger.removeHandler(handler)
    return " ".join(seen)


async def test_upgrade_does_not_disable_existing_loggers(tmp_path, keep_root_logging):
    logger = logging.getLogger(PLAZA)  # exists before the migration, as in a long test run
    assert not logger.disabled
    cfg = _cfg(f"sqlite+aiosqlite:///{(tmp_path / 'a.db').as_posix()}")
    await asyncio.to_thread(alembic.command.upgrade, cfg, "e7a1c2d3f407")
    assert not logger.disabled
    assert "failed" in await _subscriber_failure_is_logged()


async def test_failed_upgrade_does_not_disable_existing_loggers(tmp_path, keep_root_logging):
    logger = logging.getLogger(PLAZA)
    missing = (tmp_path / "no-such-dir" / "a.db").as_posix()  # fails after fileConfig ran
    with pytest.raises(OperationalError):
        await asyncio.to_thread(
            alembic.command.upgrade, _cfg(f"sqlite+aiosqlite:///{missing}"), "head"
        )
    assert not logger.disabled
    assert "failed" in await _subscriber_failure_is_logged()
