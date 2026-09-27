"""P6.2: the agent_worktrees table (model and migration only).

Row-level tests run on SQLite with foreign keys switched on; SQLite leaves them
off by default, and the app never switches them on, so these tests do it on
their own engine. The migration tests run the real Alembic chain.
"""

import logging
import uuid
from pathlib import Path

import pytest
from alembic.config import Config
from sqlalchemy import event, inspect, text
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, SQLModel, create_engine, select

import nexus.models  # noqa: F401  (registers every table)
from alembic import command
from nexus.models import AgentWorktree
from nexus.models.agent import Agent
from nexus.models.agent_session import AgentSessionRecord
from nexus.models.agent_worktree import SESSION_HOLDING_STATUSES, WORKTREE_STATUSES
from nexus.models.company import Company
from nexus.models.governance import Approval
from nexus.models.repository import Repository
from nexus.models.task import Task

MIGRATION = (
    Path(__file__).resolve().parent.parent
    / "alembic"
    / "versions"
    / "d5e1a0c3b706_add_agent_worktrees.py"
)
SHA = "a" * 40


@pytest.fixture(autouse=True)
def _restore_loggers():
    """alembic/env.py runs logging.config.fileConfig, which disables every
    logger that already exists. Put them back so later tests that assert on
    log output (caplog) still receive records."""
    loggers = [
        lg for lg in logging.root.manager.loggerDict.values() if isinstance(lg, logging.Logger)
    ]
    root = logging.getLogger()
    saved = [(lg, lg.disabled) for lg in loggers], root.level, list(root.handlers)
    yield
    flags, level, handlers = saved
    for lg, disabled in flags:
        lg.disabled = disabled
    root.setLevel(level)
    root.handlers[:] = handlers


@pytest.fixture
def engine(tmp_path):
    eng = create_engine(f"sqlite:///{(tmp_path / 'wt.db').as_posix()}")

    @event.listens_for(eng, "connect")
    def _fk_on(dbapi_conn, _record):
        dbapi_conn.execute("PRAGMA foreign_keys=ON")

    SQLModel.metadata.create_all(eng)
    yield eng
    eng.dispose()


@pytest.fixture
def world(engine):
    """Two companies, each with a repository, agent, session, task and approval."""
    ids = {}
    with Session(engine) as s:
        for key in ("a", "b"):
            company = Company(name=f"co-{key}")
            s.add(company)
            s.flush()
            repo = Repository(company_id=company.id, name="r", url="u")
            agent = Agent(company_id=company.id, name="ag", role="dev")
            s.add_all([repo, agent])
            s.flush()
            session = AgentSessionRecord(company_id=company.id, agent_id=agent.id)
            task = Task(company_id=company.id, title="t")
            approval = Approval(company_id=company.id, type="worktree_merge")
            s.add_all([session, task, approval])
            s.flush()
            ids[key] = {
                "company": company.id,
                "repo": repo.id,
                "agent": agent.id,
                "session": session.id,
                "task": task.id,
                "approval": approval.id,
            }
        s.commit()
    return ids


def _wt(ids, **overrides) -> AgentWorktree:
    fields = {
        "company_id": ids["company"],
        "repository_id": ids["repo"],
        "agent_id": ids["agent"],
        "branch": f"nexus/wt-{uuid.uuid4().hex[:8]}",
        "base_ref": "main",
        "base_commit": SHA,
        "relative_path": f"wt-{uuid.uuid4().hex[:8]}",
        "created_by": "user:admin@example.test",
    }
    fields.update(overrides)
    return AgentWorktree(**fields)


def _insert(engine, *rows) -> None:
    with Session(engine, expire_on_commit=False) as s:
        s.add_all(rows)
        s.commit()


def _raises_integrity(engine, *rows) -> None:
    with pytest.raises(IntegrityError):
        _insert(engine, *rows)


# ── Creation and field contract ──────────────────────────────────────────


def test_minimal_worktree_gets_defaults(engine, world):
    wt = _wt(world["a"])
    _insert(engine, wt)
    with Session(engine) as s:
        row = s.get(AgentWorktree, wt.id)
    assert row.status == "created"
    assert row.session_id is None and row.task_id is None and row.approval_id is None
    assert row.head_commit is None and row.merged_commit is None
    assert row.created_at is not None and row.updated_at is not None


def test_fully_linked_worktree_round_trips(engine, world):
    a = world["a"]
    wt = _wt(
        a,
        session_id=a["session"],
        task_id=a["task"],
        approval_id=a["approval"],
        head_commit="b" * 40,
        merged_commit="c" * 64,
        status="merged",
    )
    _insert(engine, wt)
    with Session(engine) as s:
        row = s.get(AgentWorktree, wt.id)
    assert (row.session_id, row.task_id, row.approval_id) == (
        a["session"],
        a["task"],
        a["approval"],
    )
    assert row.merged_commit == "c" * 64


def test_required_and_nullable_columns():
    cols = AgentWorktree.__table__.c
    required = {
        "id",
        "company_id",
        "repository_id",
        "agent_id",
        "branch",
        "base_ref",
        "base_commit",
        "relative_path",
        "status",
        "created_by",
        "created_at",
        "updated_at",
    }
    nullable = {"session_id", "task_id", "head_commit", "merged_commit", "approval_id"}
    assert {c.name for c in cols} == required | nullable
    assert {c.name for c in cols if not c.nullable} == required
    assert {c.name for c in cols if c.nullable} == nullable


@pytest.mark.parametrize(
    "column", ["branch", "base_ref", "base_commit", "relative_path", "created_by"]
)
def test_required_text_column_rejects_null(engine, world, column):
    row = _wt(world["a"])
    setattr(row, column, None)
    _raises_integrity(engine, row)


# ── Foreign keys ─────────────────────────────────────────────────────────


def test_foreign_key_targets_and_delete_actions():
    fks = {
        fk.parent.name: (fk.column.table.name, fk.ondelete)
        for fk in AgentWorktree.__table__.foreign_keys
    }
    assert fks == {
        "company_id": ("companies", None),
        "repository_id": ("repositories", "RESTRICT"),
        "agent_id": ("agents", "RESTRICT"),
        "session_id": ("agent_sessions", "SET NULL"),
        "task_id": ("tasks", "SET NULL"),
        "approval_id": ("approvals", "SET NULL"),
    }


@pytest.mark.parametrize(
    "column",
    ["company_id", "repository_id", "agent_id", "session_id", "task_id", "approval_id"],
)
def test_dangling_reference_is_rejected(engine, world, column):
    _raises_integrity(engine, _wt(world["a"], **{column: uuid.uuid4()}))


@pytest.mark.parametrize("table,key", [("repositories", "repo"), ("agents", "agent")])
def test_owner_cannot_be_deleted_while_it_has_worktrees(engine, world, table, key):
    _insert(engine, _wt(world["a"]))
    with pytest.raises(IntegrityError), engine.begin() as conn:
        conn.execute(text(f"DELETE FROM {table} WHERE id = :id"), {"id": world["a"][key].hex})


@pytest.mark.parametrize(
    "table,key,column",
    [
        ("agent_sessions", "session", "session_id"),
        ("tasks", "task", "task_id"),
        ("approvals", "approval", "approval_id"),
    ],
)
def test_deleting_a_link_clears_it_and_keeps_the_worktree(engine, world, table, key, column):
    a = world["a"]
    wt = _wt(a, session_id=a["session"], task_id=a["task"], approval_id=a["approval"])
    _insert(engine, wt)
    with engine.begin() as conn:
        conn.execute(text(f"DELETE FROM {table} WHERE id = :id"), {"id": a[key].hex})
    with Session(engine) as s:
        row = s.get(AgentWorktree, wt.id)
    assert row is not None
    assert getattr(row, column) is None


# ── Tenant ownership ─────────────────────────────────────────────────────


def test_company_id_is_required(engine, world):
    _raises_integrity(engine, _wt(world["a"], company_id=None))


def test_company_scoped_queries_see_only_their_own_rows(engine, world):
    mine, theirs = _wt(world["a"]), _wt(world["b"])
    _insert(engine, mine, theirs)
    with Session(engine) as s:
        rows = s.exec(
            select(AgentWorktree).where(AgentWorktree.company_id == world["a"]["company"])
        ).all()
    assert [r.id for r in rows] == [mine.id]


def test_migration_puts_the_table_under_tenant_rls():
    source = MIGRATION.read_text()
    assert "ALTER TABLE agent_worktrees ENABLE ROW LEVEL SECURITY;" in source
    assert "ALTER TABLE agent_worktrees FORCE ROW LEVEL SECURITY;" in source
    assert "CREATE POLICY tenant_isolation ON agent_worktrees" in source
    assert "WITH CHECK (company_id = NULLIF(current_setting('nexus.company_id', true)" in source


def test_cross_company_references_are_not_a_database_constraint(engine, world):
    """Recorded debt: the service must check that every link shares company_id.

    There is no composite (id, company_id) key to point at, so the database
    accepts a worktree whose repository belongs to another company. If this
    ever starts failing, the constraint was added and the P6.3 checks can lean
    on it.
    """
    _insert(engine, _wt(world["a"], repository_id=world["b"]["repo"]))


# ── Uniqueness ───────────────────────────────────────────────────────────


def test_branch_is_unique_per_repository(engine, world):
    a = world["a"]
    _insert(engine, _wt(a, branch="nexus/x"))
    _raises_integrity(engine, _wt(a, branch="nexus/x"))


def test_same_branch_name_is_allowed_in_another_repository(engine, world):
    _insert(engine, _wt(world["a"], branch="nexus/x"), _wt(world["b"], branch="nexus/x"))


@pytest.mark.parametrize("status", ["archived", "merged"])
def test_finished_worktree_still_reserves_its_branch(engine, world, status):
    """Unmerged branches are never deleted, so the name stays taken in git."""
    a = world["a"]
    _insert(engine, _wt(a, branch="nexus/x", status=status))
    _raises_integrity(engine, _wt(a, branch="nexus/x"))


@pytest.mark.parametrize("held", SESSION_HOLDING_STATUSES)
@pytest.mark.parametrize("other", SESSION_HOLDING_STATUSES)
def test_session_holds_one_created_or_active_worktree(engine, world, held, other):
    a = world["a"]
    _insert(engine, _wt(a, session_id=a["session"], status=held))
    _raises_integrity(engine, _wt(a, session_id=a["session"], status=other))


@pytest.mark.parametrize("finished", ["review", "approved", "merged", "archived"])
def test_session_history_does_not_block_a_new_worktree(engine, world, finished):
    a = world["a"]
    _insert(
        engine,
        _wt(a, session_id=a["session"], status=finished),
        _wt(a, session_id=a["session"], status=finished),
        _wt(a, session_id=a["session"], status="active"),
    )


def test_worktrees_without_a_session_are_unbounded(engine, world):
    a = world["a"]
    _insert(engine, *(_wt(a, status="active") for _ in range(3)))


def test_different_sessions_each_hold_a_worktree(engine, world):
    a = world["a"]
    with Session(engine) as s:
        second = AgentSessionRecord(company_id=a["company"], agent_id=a["agent"])
        s.add(second)
        s.commit()
        second_id = second.id
    _insert(
        engine,
        _wt(a, session_id=a["session"], status="active"),
        _wt(a, session_id=second_id, status="active"),
    )


# ── Status vocabulary ────────────────────────────────────────────────────


def test_status_vocabulary_is_exactly_the_agreed_lifecycle():
    assert WORKTREE_STATUSES == ("created", "active", "review", "approved", "merged", "archived")
    assert SESSION_HOLDING_STATUSES == ("created", "active")


@pytest.mark.parametrize("status", WORKTREE_STATUSES)
def test_every_lifecycle_status_is_accepted(engine, world, status):
    _insert(engine, _wt(world["a"], status=status))


@pytest.mark.parametrize("status", ["failed", "abandoned", "deleted", "ACTIVE", ""])
def test_other_statuses_are_rejected(engine, world, status):
    _raises_integrity(engine, _wt(world["a"], status=status))


# ── Migration ────────────────────────────────────────────────────────────


def _alembic(db_file: Path) -> Config:
    cfg = Config("alembic.ini")
    cfg.set_main_option("sqlalchemy.url", f"sqlite+aiosqlite:///{db_file.as_posix()}")
    return cfg


def _inspect(db_file: Path):
    eng = create_engine(f"sqlite:///{db_file.as_posix()}")
    try:
        insp = inspect(eng)
        tables = set(insp.get_table_names())
        if "agent_worktrees" not in tables:
            return tables, None
        with eng.connect() as conn:
            partial_sql = conn.execute(
                text(
                    "SELECT sql FROM sqlite_master WHERE type = 'index' "
                    "AND name = 'uq_agent_worktrees_session_holding'"
                )
            ).scalar_one()
        detail = {
            "columns": {c["name"]: c["nullable"] for c in insp.get_columns("agent_worktrees")},
            "indexes": {
                i["name"]: (tuple(i["column_names"]), bool(i["unique"]))
                for i in insp.get_indexes("agent_worktrees")
            },
            "uniques": {
                u["name"]: tuple(u["column_names"])
                for u in insp.get_unique_constraints("agent_worktrees")
            },
            "checks": {c["name"] for c in insp.get_check_constraints("agent_worktrees")},
            "fks": {
                fk["constrained_columns"][0]: (
                    fk["referred_table"],
                    fk["options"].get("ondelete"),
                )
                for fk in insp.get_foreign_keys("agent_worktrees")
            },
            "partial_sql": partial_sql,
        }
        return tables, detail
    finally:
        eng.dispose()


def test_migration_revision_follows_previous_head():
    source = MIGRATION.read_text()
    assert 'revision: str = "d5e1a0c3b706"' in source
    assert 'down_revision: str | None = "d5e1a0c3b705"' in source


def test_migration_upgrade_builds_the_model_schema(tmp_path):
    db_file = tmp_path / "chain.db"
    command.upgrade(_alembic(db_file), "head")
    tables, d = _inspect(db_file)
    assert "agent_worktrees" in tables

    model_cols = {c.name: c.nullable for c in AgentWorktree.__table__.c}
    assert d["columns"] == model_cols
    assert d["uniques"] == {"uq_agent_worktrees_repository_branch": ("repository_id", "branch")}
    assert d["checks"] == {"ck_agent_worktrees_status"}
    assert d["fks"] == {
        "company_id": ("companies", None),
        "repository_id": ("repositories", "RESTRICT"),
        "agent_id": ("agents", "RESTRICT"),
        "session_id": ("agent_sessions", "SET NULL"),
        "task_id": ("tasks", "SET NULL"),
        "approval_id": ("approvals", "SET NULL"),
    }
    assert d["indexes"] == {
        "ix_agent_worktrees_company_id": (("company_id",), False),
        "ix_agent_worktrees_session_id": (("session_id",), False),
        "ix_agent_worktrees_company_status": (("company_id", "status"), False),
        "ix_agent_worktrees_company_agent": (("company_id", "agent_id"), False),
        "uq_agent_worktrees_session_holding": (("session_id",), True),
    }
    assert "WHERE session_id IS NOT NULL AND status IN ('created', 'active')" in d["partial_sql"]


def test_migration_indexes_match_the_model():
    """create_all (tests) and the migration (production) name the same indexes."""
    model_indexes = {i.name for i in AgentWorktree.__table__.indexes}
    assert model_indexes == {
        "ix_agent_worktrees_company_id",
        "ix_agent_worktrees_session_id",
        "ix_agent_worktrees_company_status",
        "ix_agent_worktrees_company_agent",
        "uq_agent_worktrees_session_holding",
    }


def test_migration_downgrade_removes_only_this_table_and_reapplies(tmp_path):
    db_file = tmp_path / "chain.db"
    cfg = _alembic(db_file)
    command.upgrade(cfg, "head")
    at_head, _ = _inspect(db_file)
    # Later migrations add their own tables; compare against this revision only.
    command.downgrade(cfg, "d5e1a0c3b706")
    at_revision, _ = _inspect(db_file)

    command.downgrade(cfg, "d5e1a0c3b705")
    after_down, detail = _inspect(db_file)
    assert detail is None
    assert after_down == at_revision - {"agent_worktrees"}

    command.upgrade(cfg, "head")
    reapplied, detail = _inspect(db_file)
    assert reapplied == at_head
    assert detail is not None
