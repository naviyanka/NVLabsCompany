"""The canonical-ingest migration backfills legacy memory rows deterministically."""

import hashlib
import uuid
from datetime import datetime

import sqlalchemy as sa
from alembic.config import Config

from alembic import command

PREVIOUS = "e7a1c2d3f407"
CURRENT = "f1b7c9d2a508"
COMPANY, OTHER = uuid.uuid4(), uuid.uuid4()
NOW = datetime(2026, 1, 2, 3, 4, 5)


def _cfg(db_file) -> Config:
    cfg = Config("alembic.ini")
    cfg.set_main_option("sqlalchemy.url", f"sqlite+aiosqlite:///{db_file.as_posix()}")
    return cfg


def _table(engine) -> sa.Table:
    """memory_records with real UUID columns (reflection reads SQLite's CHAR(32) as text)."""
    uuids = [sa.Column("id", sa.Uuid, primary_key=True), sa.Column("company_id", sa.Uuid)]
    if "supersedes_id" in {c["name"] for c in sa.inspect(engine).get_columns("memory_records")}:
        uuids.append(sa.Column("supersedes_id", sa.Uuid))
    return sa.Table("memory_records", sa.MetaData(), *uuids, autoload_with=engine)


def _row(scope, content, meta=None, **kw):
    return {
        "id": kw.pop("id", uuid.uuid4()),
        "company_id": kw.pop("company_id", COMPANY),
        "agent_id": None,
        "scope": scope,
        "scope_id": None,
        "content": content,
        "metadata": meta,
        "importance": 0.5,
        "access_count": 0,
        "tier": "warm",
        "created_at": NOW,
        "updated_at": NOW,
        **kw,
    }


def _legacy_rows():
    parent = _row(
        "executive", "Old plan", {"type": "decision", "status": "superseded", "origin": "human"}
    )
    return {
        "plain": _row("agent", "Deploys go out on Tuesdays"),
        "candidate": _row(
            "l2_agent", "User likes tea", {"trust": "untrusted_candidate", "origin": "chat"}
        ),
        "api": _row("agent", "Operator note", {"origin": "api", "trust": "operator_supplied"}),
        "guideline": _row("guidelines", "Always review"),
        "chat_source": _row(
            "agent", "From a turn", {"source": {"turn_id": "turn-7", "message_id": "msg-9"}}
        ),
        "parent": parent,
        "successor": _row(
            "executive",
            "New plan",
            {
                "type": "decision",
                "status": "active",
                "origin": "human",
                "supersedes": str(parent["id"]),
            },
        ),
        "foreign_link": _row(
            "executive",
            "Points elsewhere",
            {"type": "decision", "supersedes": str(uuid.uuid4())},
        ),
        "resolved": _row("executive", "Done thing", {"type": "commitment", "status": "resolved"}),
    }


def test_backfill_is_deterministic_and_lossless(tmp_path):
    db_file = tmp_path / "backfill.db"
    cfg = _cfg(db_file)
    command.upgrade(cfg, PREVIOUS)

    rows = _legacy_rows()
    engine = sa.create_engine(f"sqlite:///{db_file.as_posix()}")
    table = _table(engine)
    with engine.begin() as conn:
        conn.execute(table.insert(), list(rows.values()))

    command.upgrade(cfg, CURRENT)

    table = _table(engine)
    with engine.connect() as conn:
        got = {r.id: r for r in conn.execute(table.select())}
    assert len(got) == len(rows)  # nothing deleted, nothing merged

    def after(key):
        return got[rows[key]["id"]]

    for key, legacy in rows.items():
        r = after(key)
        assert r.content == legacy["content"]  # never rewritten
        assert r.content_hash == hashlib.sha256(legacy["content"].encode()).hexdigest()
        assert r.ingestion_key == f"legacy:{legacy['id']}"

    assert (after("plain").status, after("plain").trust_state) == ("active", "untrusted")
    assert (after("candidate").status, after("candidate").trust_state) == ("candidate", "untrusted")
    assert after("api").trust_state == "asserted"
    assert after("guideline").memory_type == "directive"
    assert after("plain").memory_type == "unknown"
    assert after("parent").memory_type == "decision"

    # Source only where the row itself names a real message or turn; never invented.
    assert (after("chat_source").source_type, after("chat_source").source_id) == (
        "chat_message",
        "msg-9",
    )
    assert after("plain").source_type is None and after("plain").source_id is None
    assert after("candidate").source_id is None

    # Executive semantics survive: closed entries keep their state; the link stays in-company.
    assert after("parent").status == "superseded"
    assert after("resolved").status == "archived"
    assert after("successor").supersedes_id == rows["parent"]["id"]
    assert after("foreign_link").supersedes_id is None

    # Downgrade drops only the new columns; the rows and their text remain.
    command.downgrade(cfg, PREVIOUS)
    table = _table(engine)
    assert "status" not in table.c and "content_hash" not in table.c
    with engine.connect() as conn:
        assert {r.content for r in conn.execute(table.select())} == {
            r["content"] for r in rows.values()
        }
    engine.dispose()


def test_backfill_survives_an_empty_table_and_upgrades_again(tmp_path):
    cfg = _cfg(tmp_path / "empty.db")
    command.upgrade(cfg, PREVIOUS)
    command.upgrade(cfg, CURRENT)
    command.downgrade(cfg, PREVIOUS)
    command.upgrade(cfg, CURRENT)
