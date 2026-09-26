"""ws03: legacy chat_messages are mapped onto backfilled agent_sessions.

Runs the real migration chain on SQLite: upgrade to ws02, seed pre-session
chat history, upgrade to ws03, check the documented mapping rules, then
downgrade and check the rows are restored to their pre-backfill state.
"""

import uuid
from datetime import datetime, timedelta

import sqlalchemy as sa
from alembic.config import Config

from alembic import command

WS02, WS03 = "d5e1a0c3b702", "d5e1a0c3b703"
T0 = datetime(2026, 1, 1, 12, 0, 0)

_companies = sa.table(
    "companies",
    *(
        sa.column(c)
        for c in (
            "name",
            "status",
            "budget_monthly_cents",
            "spent_monthly_cents",
            "created_at",
            "updated_at",
        )
    ),
    sa.column("id", sa.Uuid()),
)
_agents = sa.table(
    "agents",
    *(
        sa.column(c)
        for c in (
            "name",
            "role",
            "status",
            "adapter_type",
            "budget_monthly_cents",
            "spent_monthly_cents",
            "created_at",
            "updated_at",
        )
    ),
    sa.column("id", sa.Uuid()),
    sa.column("company_id", sa.Uuid()),
)
_messages = sa.table(
    "chat_messages",
    sa.column("id", sa.Uuid()),
    sa.column("company_id", sa.Uuid()),
    sa.column("agent_id", sa.Uuid()),
    sa.column("session_id", sa.Uuid()),
    *(
        sa.column(c)
        for c in ("sender", "text", "conversation_id", "model_used", "tokens_used", "seq", "kind")
    ),
    sa.column("created_at", sa.DateTime()),
)
_sessions = sa.table(
    "agent_sessions",
    sa.column("id", sa.Uuid()),
    sa.column("company_id", sa.Uuid()),
    sa.column("agent_id", sa.Uuid()),
    sa.column("metadata", sa.JSON()),
    *(sa.column(c) for c in ("status", "adapter_type", "model", "title", "event_seq")),
    sa.column("started_at", sa.DateTime()),
    sa.column("last_activity_at", sa.DateTime()),
)


def _cfg(db_file) -> Config:
    cfg = Config("alembic.ini")
    cfg.set_main_option("sqlalchemy.url", f"sqlite+aiosqlite:///{db_file.as_posix()}")
    return cfg


def _seed(conn):
    """Two companies, three agents, a deleted agent and a cross-company row."""
    c1, c2 = uuid.uuid4(), uuid.uuid4()
    a1, a2, b1 = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    for cid in (c1, c2):
        conn.execute(
            _companies.insert().values(
                id=cid,
                name="c",
                status="active",
                budget_monthly_cents=0,
                spent_monthly_cents=0,
                created_at=T0,
                updated_at=T0,
            )
        )
    for aid, cid in ((a1, c1), (a2, c1), (b1, c2)):
        conn.execute(
            _agents.insert().values(
                id=aid,
                company_id=cid,
                name="a",
                role="r",
                status="idle",
                adapter_type="ollama",
                budget_monthly_cents=0,
                spent_monthly_cents=0,
                created_at=T0,
                updated_at=T0,
            )
        )

    def msg(cid, aid, sender, minutes, conversation_id=None, model=None, tokens=0):
        mid = uuid.uuid4()
        conn.execute(
            _messages.insert().values(
                id=mid,
                company_id=cid,
                agent_id=aid,
                sender=sender,
                text=f"{sender}@{minutes}",
                conversation_id=conversation_id,
                model_used=model,
                tokens_used=tokens,
                created_at=T0 + timedelta(minutes=minutes),
            )
        )
        return mid

    ids = {
        # a1: inserted out of chronological order to prove ordering is by created_at.
        "a1_late": msg(c1, a1, "agent", 5, model="m1", tokens=42),
        "a1_early": msg(c1, a1, "user", 1),
        "a1_mid": msg(c1, a1, "user", 3),
        "a1_tie_x": msg(c1, a1, "user", 7),
        "a1_tie_y": msg(c1, a1, "agent", 7),
        # a1 with an explicit conversation id: its own session.
        "a1_conv": msg(c1, a1, "user", 2, conversation_id="conv-9"),
        "a2_only": msg(c1, a2, "user", 4),
        "b1_only": msg(c2, b1, "user", 6),
        # Unassociable: agent row missing / agent belongs to another company.
        "orphan": msg(c1, uuid.uuid4(), "user", 8),
        "cross_company": msg(c2, a1, "user", 9),
    }
    return {"c1": c1, "c2": c2, "a1": a1, "a2": a2, "b1": b1}, ids


def _message_rows(conn):
    return {r.id: r for r in conn.execute(sa.select(_messages)).all()}


def test_ws03_backfill_maps_history_and_downgrade_restores(tmp_path):
    db_file = tmp_path / "ws03.db"
    cfg = _cfg(db_file)
    command.upgrade(cfg, WS02)

    engine = sa.create_engine(f"sqlite:///{db_file.as_posix()}")
    with engine.begin() as conn:
        keys, ids = _seed(conn)
        before = _message_rows(conn)

    command.upgrade(cfg, WS03)

    with engine.connect() as conn:
        rows = _message_rows(conn)
        sessions = {s.id: s for s in conn.execute(sa.select(_sessions)).all()}

    # Rule 2: unattributable rows stay unassociated.
    for name in ("orphan", "cross_company"):
        assert rows[ids[name]].session_id is None and rows[ids[name]].seq is None

    # Rule 3: one session per (company, agent, conversation_id).
    assert len(sessions) == 4
    a1_rolling = rows[ids["a1_early"]].session_id
    assert rows[ids["a1_conv"]].session_id not in (None, a1_rolling)
    assert rows[ids["a2_only"]].session_id not in (None, a1_rolling)
    assert sessions[rows[ids["b1_only"]].session_id].company_id == keys["c2"]

    # Rule 5: seq follows created_at; ties are broken deterministically by id.
    tie = sorted([ids["a1_tie_x"], ids["a1_tie_y"]], key=lambda i: i.hex)
    ordered = [ids["a1_early"], ids["a1_mid"], ids["a1_late"], *tie]
    assert [rows[i].session_id for i in ordered] == [a1_rolling] * 5
    assert [rows[i].seq for i in ordered] == [1, 2, 3, 4, 5]

    # Rule 4: session fields are derived, never fabricated.
    s = sessions[a1_rolling]
    assert (s.status, s.adapter_type, s.model, s.title) == ("idle", "unknown", None, None)
    assert s.event_seq == 5
    assert s.started_at == T0 + timedelta(minutes=1)
    assert s.last_activity_at == T0 + timedelta(minutes=7)
    assert s.metadata == {"legacy": True, "backfill": "ws03"}
    assert sessions[rows[ids["a1_conv"]].session_id].metadata["legacy_conversation_id"] == "conv-9"

    # Rule 6: message content and accounting are untouched.
    for mid, old in before.items():
        new = rows[mid]
        assert (
            new.sender,
            new.text,
            new.model_used,
            new.tokens_used,
            new.created_at,
            new.kind,
        ) == (
            old.sender,
            old.text,
            old.model_used,
            old.tokens_used,
            old.created_at,
            "message",
        )

    # A session created after the backfill must survive the downgrade.
    live = uuid.uuid4()
    with engine.begin() as conn:
        conn.execute(
            _sessions.insert().values(
                id=live,
                company_id=keys["c1"],
                agent_id=keys["a2"],
                status="active",
                adapter_type="ollama",
                event_seq=0,
                metadata=None,
                started_at=T0,
                last_activity_at=T0,
            )
        )

    command.downgrade(cfg, WS02)

    with engine.connect() as conn:
        rows = _message_rows(conn)
        remaining = [r.id for r in conn.execute(sa.select(_sessions.c.id)).all()]
    engine.dispose()

    assert remaining == [live]
    assert all(r.session_id is None and r.seq is None for r in rows.values())
