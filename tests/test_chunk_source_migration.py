"""Data-integrity regression test for the knowledge_chunks source model.

Migration d8e3b6c04a90 renames ``page_id`` to ``source_id`` and adds
``source_type`` (ADR 0002 §12, Option B). The risk it carries is silent data
loss: a chunk that loses its parent identity is unreachable but still returned by
RAG search, and nothing errors.

So this runs the real ``upgrade()`` against a pre-migration SQLite table holding
real rows, and pins that every row keeps its parent.
"""

from __future__ import annotations

import importlib.util
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, inspect, text

MIGRATION_PATH = (
    Path(__file__).resolve().parent.parent
    / "alembic"
    / "versions"
    / "d8e3b6c04a90_chunk_source_type.py"
)

PAGE_A = uuid.UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
PAGE_B = uuid.UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")
COMPANY = uuid.UUID("cccccccc-cccc-cccc-cccc-cccccccccccc")

# The pre-migration shape, from db96cb66effc_initial_schema.py:567.
_PRE_MIGRATION_DDL = """
CREATE TABLE knowledge_chunks (
    id CHAR(32) NOT NULL,
    company_id CHAR(32) NOT NULL,
    page_id CHAR(32) NOT NULL,
    content VARCHAR NOT NULL,
    chunk_index INTEGER NOT NULL,
    metadata JSON,
    embedding_vector JSON,
    created_at DATETIME NOT NULL,
    PRIMARY KEY (id)
)
"""


def _load_migration() -> Any:
    """Import the migration module by path (it is not on the import path)."""
    spec = importlib.util.spec_from_file_location("mig_d8e3b6c04a90", MIGRATION_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def seeded_engine():
    """A SQLite engine holding the pre-migration table with five chunk rows."""
    engine = create_engine("sqlite:///:memory:")
    with engine.begin() as conn:
        conn.execute(text(_PRE_MIGRATION_DDL))
        conn.execute(
            text("CREATE INDEX ix_knowledge_chunks_page_id ON knowledge_chunks (page_id)")
        )
        conn.execute(
            text("CREATE INDEX ix_knowledge_chunks_company_id ON knowledge_chunks (company_id)")
        )
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        rows = [
            {
                "id": uuid.uuid4().hex,
                "company_id": COMPANY.hex,
                "page_id": (PAGE_A if index < 3 else PAGE_B).hex,
                "content": f"chunk {index}",
                "chunk_index": index,
                "metadata": None,
                "embedding_vector": None,
                "created_at": now,
            }
            for index in range(5)
        ]
        conn.execute(
            text(
                "INSERT INTO knowledge_chunks "
                "(id, company_id, page_id, content, chunk_index, metadata, "
                " embedding_vector, created_at) VALUES "
                "(:id, :company_id, :page_id, :content, :chunk_index, :metadata, "
                " :embedding_vector, :created_at)"
            ),
            rows,
        )
    return engine


def _run(engine, direction: str) -> None:
    """Execute the migration's upgrade() or downgrade() against ``engine``."""
    module = _load_migration()
    with engine.begin() as conn:
        context = MigrationContext.configure(conn)
        with Operations.context(context):
            getattr(module, direction)()


def test_upgrade_preserves_every_chunk_and_its_parent(seeded_engine) -> None:
    """No chunk is lost, and each keeps the exact parent id it had."""
    with seeded_engine.begin() as conn:
        before = conn.execute(
            text("SELECT id, page_id FROM knowledge_chunks ORDER BY chunk_index")
        ).all()
    assert len(before) == 5

    _run(seeded_engine, "upgrade")

    with seeded_engine.begin() as conn:
        after = conn.execute(
            text(
                "SELECT id, source_id, source_type FROM knowledge_chunks "
                "ORDER BY chunk_index"
            )
        ).all()

    assert len(after) == len(before), "chunk count changed"
    for (old_id, old_page), (new_id, new_source, source_type) in zip(before, after):
        assert new_id == old_id
        assert new_source == old_page, "parent identity changed"
        assert source_type == "knowledge_page"


def test_upgrade_leaves_no_null_source_columns(seeded_engine) -> None:
    """Both halves of the polymorphic pair are populated for every row."""
    _run(seeded_engine, "upgrade")
    with seeded_engine.begin() as conn:
        nulls = conn.execute(
            text(
                "SELECT COUNT(*) FROM knowledge_chunks "
                "WHERE source_type IS NULL OR source_id IS NULL"
            )
        ).scalar_one()
    assert nulls == 0


def test_upgrade_backfills_existing_chunks_as_knowledge_pages(seeded_engine) -> None:
    """Every pre-existing chunk belongs to a knowledge page, not a vault note."""
    _run(seeded_engine, "upgrade")
    with seeded_engine.begin() as conn:
        types = conn.execute(
            text("SELECT DISTINCT source_type FROM knowledge_chunks")
        ).scalars().all()
    assert types == ["knowledge_page"]


def test_upgrade_groups_chunks_by_parent_unchanged(seeded_engine) -> None:
    """The parent grouping survives: three chunks under A, two under B."""
    _run(seeded_engine, "upgrade")
    with seeded_engine.begin() as conn:
        counts = dict(
            conn.execute(
                text(
                    "SELECT source_id, COUNT(*) FROM knowledge_chunks "
                    "GROUP BY source_id"
                )
            ).all()
        )
    assert counts[PAGE_A.hex] == 3
    assert counts[PAGE_B.hex] == 2


def test_upgrade_creates_the_lookup_indexes(seeded_engine) -> None:
    """Phase 1B looks chunks up by (source_type, source_id); index it."""
    _run(seeded_engine, "upgrade")
    names = {ix["name"] for ix in inspect(seeded_engine).get_indexes("knowledge_chunks")}
    assert "ix_knowledge_chunks_source" in names
    assert "ix_knowledge_chunks_source_id" in names
    assert "ix_knowledge_chunks_source_type" in names
    assert "ix_knowledge_chunks_page_id" not in names


def test_downgrade_restores_page_id_without_losing_rows(seeded_engine) -> None:
    """A downgrade is survivable while every chunk is a knowledge-page chunk."""
    _run(seeded_engine, "upgrade")
    _run(seeded_engine, "downgrade")

    with seeded_engine.begin() as conn:
        rows = conn.execute(
            text("SELECT page_id FROM knowledge_chunks ORDER BY chunk_index")
        ).scalars().all()
    assert len(rows) == 5
    assert rows[:3] == [PAGE_A.hex] * 3
    assert rows[3:] == [PAGE_B.hex] * 2

    columns = {c["name"] for c in inspect(seeded_engine).get_columns("knowledge_chunks")}
    assert "source_type" not in columns
    assert "source_id" not in columns
