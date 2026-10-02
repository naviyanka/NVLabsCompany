"""Tests for Alembic migration completeness and validity.

Everything is driven off Alembic's own ScriptDirectory. Hardcoded
file lists are what let the revision map rot once before (duplicate
id shipped, heads OK but upgrade broken) — never reintroduce one.
"""

import ast
import os
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import inspect
from sqlmodel import SQLModel, create_engine

# Import all models to ensure they are registered in SQLModel.metadata
import nexus.models  # noqa: F401


ALEMBIC_VERSIONS_DIR = Path(__file__).resolve().parent.parent / "alembic" / "versions"

# env.py is async: it needs an async driver. aiosqlite is a dev dep.
SQLITE_URL = "sqlite+aiosqlite:///./_wp23b_chain.db"

EXPECTED_TABLES = {
    "action_items",
    "agent_sessions",
    "agent_skills",
    "agent_worktrees",
    "agent_versions",
    "agents",
    "api_keys",
    "approval_signatures",
    "approval_signer_keys",
    "approvals",
    "audit_log",
    "audit_log_archive",
    "auth_invites",
    "budget_policies",
    "chat_messages",
    "chat_turns",
    "circuit_breaker_records",
    "companies",
    "company_memberships",
    "company_settings",
    "cost_events",
    "decision_queue_items",
    "decision_queues",
    "decisions",
    "departments",
    "events",
    "evolution_evaluations",
    "execution_checkpoints",
    "evolution_proposals",
    "experience_records",
    "goals",
    "group_members",
    "groups",
    "heartbeat_runs",
    "hr_performance_reviews",
    "hr_training_curricula",
    "idempotency_records",
    "incident_actions",
    "incident_events",
    "incidents",
    "kill_switch_records",
    "knowledge_chunks",
    "knowledge_pages",
    "llm_connections",
    "mcp_bindings",
    "meeting_minutes",
    "meeting_participants",
    "meetings",
    "memory_evidence",
    "memory_operations",
    "memory_records",
    "governance_grant_uses",
    "governance_policy_drafts",
    "governance_policy_versions",
    "governance_restrictions",
    "governance_temp_access",
    "messages",
    "notification_preferences",
    "notifications",
    "obsidian_documents",
    "okr_key_results",
    "okr_objectives",
    "organization_snapshot_state",
    "organization_snapshots",
    "pipeline_runs",
    "pipelines",
    "plaza_posts",
    "policies",
    "policy_rules",
    "policy_versions",
    "projects",
    "repositories",
    "secret_accesses",
    "secret_bindings",
    "secret_versions",
    "secrets",
    "skill_versions",
    "skills",
    "task_attempts",
    "tasks",
    "teams",
    "tool_access",
    "tool_catalog_entries",
    "tool_connections",
    "tool_invocations",
    "tool_policies",
    "tool_profile_bindings",
    "tool_profiles",
    "tools",
    "trigger_executions",
    "triggers",
    "user_profiles",
    "user_sessions",
    "vault_write_grants",
    "work_effects",
    "workflow_runs",
    "workspaces",
}


def _alembic_cfg(db_url: str | None = None) -> Config:
    cfg = Config("alembic.ini")
    if db_url:
        cfg.set_main_option("sqlalchemy.url", db_url)
    return cfg


class TestModelMetadata:
    """Verify all SQLModel tables are discoverable in metadata."""

    def test_all_expected_tables_in_metadata(self) -> None:
        """Metadata contains exactly the expected tables (diff shown on failure)."""
        actual_tables = set(SQLModel.metadata.tables.keys())
        missing = EXPECTED_TABLES - actual_tables
        extra = actual_tables - EXPECTED_TABLES
        assert not missing, f"Missing tables in metadata: {sorted(missing)}"
        assert not extra, f"Unexpected tables in metadata: {sorted(extra)}"

    def test_circuit_breaker_records_in_metadata(self) -> None:
        """Verify circuit_breaker_records table is registered in metadata."""
        assert "circuit_breaker_records" in SQLModel.metadata.tables


class TestRevisionGraph:
    """Structural checks derived from the live ScriptDirectory, not a list."""

    def test_revision_ids_are_unique(self) -> None:
        """No two version files may declare the same revision id.

        R14 guard. A duplicate id makes ScriptDirectory raise
        (duplicate-revision-identifier) at map-build time, so every
        alembic command — heads, history, upgrade — fails.
        """
        ids: list[str] = []
        for path in ALEMBIC_VERSIONS_DIR.glob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                value = None
                if isinstance(node, ast.Assign) and any(
                    getattr(t, "id", None) == "revision" for t in node.targets
                ):
                    if isinstance(node.value, ast.Constant):
                        value = node.value.value
                elif isinstance(node, ast.AnnAssign) and getattr(
                    node.target, "id", None
                ) == "revision":
                    if isinstance(node.value, ast.Constant):
                        value = node.value.value
                if value is not None:
                    ids.append(value)

        dupes = {rid for rid in ids if ids.count(rid) > 1}
        assert not dupes, f"Duplicate revision ids: {sorted(dupes)}"

    def test_revision_graph_is_a_single_chain(self) -> None:
        """Exactly one head; every revision reachable walking back from it.

        A second head or an unreachable revision means the graph has a
        fork that `alembic upgrade head` silently ignores.
        """
        from alembic.script import ScriptDirectory

        sd = ScriptDirectory.from_config(Config("alembic.ini"))
        heads = sd.get_heads()
        assert len(heads) == 1, f"Expected exactly one head, got {heads}"

        walkable = {r.revision for r in sd.walk_revisions()}
        all_files = {
            p.name for p in ALEMBIC_VERSIONS_DIR.glob("*.py") if p.name != "__init__.py"
        }
        # every version file on disk is part of the walkable lineage
        unreachable = all_files - {Path(r.path).name for r in sd.walk_revisions()}
        assert not unreachable, f"Version files not in lineage: {sorted(unreachable)}"


class TestChainExecution:
    """The map building is not the chain executing. Execute it."""

    def teardown_method(self) -> None:
        db_path = Path("./_wp23b_chain.db")
        if db_path.exists():
            db_path.unlink()
        for suffix in ("-journal", "-wal", "-shm"):
            p = Path(str(db_path) + suffix)
            if p.exists():
                p.unlink()

    def test_full_chain_upgrades_from_empty(self, tmp_path, monkeypatch) -> None:
        """`alembic upgrade head` runs the whole chain from an empty database.

        This is what the compose migrate one-shot runs — the only test
        that proves the chain executes, not just that the map builds.
        Dialect-guarded migrations (is_pg) are skipped branches on
        sqlite; the RLS statements only run against real Postgres in
        CI (postgres-integration job) and test_postgres_integration.py.
        """
        db_file = tmp_path / "chain.db"
        cfg = Config("alembic.ini")
        cfg.set_main_option("sqlalchemy.url", f"sqlite+aiosqlite:///{db_file.as_posix()}")
        command.upgrade(cfg, "head")

        engine = create_engine(f"sqlite:///{db_file.as_posix()}")
        created = set(inspect(engine).get_table_names())
        engine.dispose()

        missing = EXPECTED_TABLES - created
        assert not missing, f"Tables missing after full upgrade: {sorted(missing)}"
        unexpected = created - EXPECTED_TABLES - {"alembic_version"}
        assert not unexpected, f"Unexpected tables created: {sorted(unexpected)}"

    def test_downgrade_one_then_upgrade_again(self, tmp_path) -> None:
        """Downgrade one step from head, then upgrade back to head.

        The only thing that ever exercises a downgrade() body.
        """
        db_file = tmp_path / "chain.db"
        cfg = Config("alembic.ini")
        cfg.set_main_option("sqlalchemy.url", f"sqlite+aiosqlite:///{db_file.as_posix()}")
        command.upgrade(cfg, "head")
        command.downgrade(cfg, "-1")
        command.upgrade(cfg, "head")

    def test_memory_evidence_triggers_hold_on_a_migrated_database(self, tmp_path) -> None:
        """Evidence rows are append-only and cannot name another company's memory.

        Tests build tables with create_all, which has no triggers: only the migration
        creates them, so this is the SQLite proof (the PostgreSQL one is in
        test_memory_evidence_postgres.py). Downgrading one step removes them again.
        """
        import uuid

        from sqlalchemy import text
        from sqlalchemy.exc import DatabaseError

        from nexus.models.memory import MemoryRecord

        db_file = tmp_path / "chain.db"
        url = f"sqlite:///{db_file.as_posix()}"
        cfg = Config("alembic.ini")
        cfg.set_main_option("sqlalchemy.url", f"sqlite+aiosqlite:///{db_file.as_posix()}")
        command.upgrade(cfg, "head")

        acme, other, memory = (str(uuid.uuid4()) for _ in range(3))
        insert = text(
            "INSERT INTO memory_evidence (id, company_id, memory_id, evidence_kind, source_type,"
            " source_id, reason_code, grade, source_digest, policy_version, idempotency_key,"
            " created_by, created_at) VALUES (:id, :c, :m, 'chat_turn', 'chat_turn', 's', '',"
            " 'none', 'd', 'memory-evidence-v1', :k, 'user:u', CURRENT_TIMESTAMP)"
        )
        engine = create_engine(url)
        with engine.begin() as conn:
            conn.execute(
                MemoryRecord.__table__.insert().values(
                    id=uuid.UUID(memory),
                    company_id=uuid.UUID(acme),
                    agent_id=uuid.uuid4(),
                    scope="l2_agent",
                    content="x",
                    status="active",
                )
            )
        # SQLite stores a UUID as 32 hex digits, so raw SQL must spell it that way.
        hexed = {name: uuid.UUID(v).hex for name, v in (("c", acme), ("m", memory), ("o", other))}
        row = {"id": uuid.uuid4().hex, "c": hexed["c"], "m": hexed["m"], "k": "k1"}
        with engine.begin() as conn:
            conn.execute(insert, row)
        for statement, params in (
            ("UPDATE memory_evidence SET grade = 'verify'", {}),
            ("DELETE FROM memory_evidence", {}),
            (insert.text, {**row, "id": uuid.uuid4().hex, "c": hexed["o"], "k": "k2"}),  # foreign
        ):
            with pytest.raises(DatabaseError), engine.begin() as conn:
                conn.execute(text(statement), params)
        with engine.connect() as conn:
            assert conn.execute(text("SELECT count(*) FROM memory_evidence")).scalar() == 1
        engine.dispose()

        command.downgrade(cfg, "-1")
        engine = create_engine(url)
        with engine.connect() as conn:
            left = conn.execute(
                text("SELECT name FROM sqlite_master WHERE name LIKE 'trg_memory_%'")
            ).fetchall()
        engine.dispose()
        assert not left, left
        command.upgrade(cfg, "head")

    def test_migrated_schema_matches_the_models(self, tmp_path) -> None:
        """A database built only by migrations has every model table and column.

        Tests build tables with create_all, so a model column without a
        migration went unnoticed until the startup seed failed on a fresh
        database ("table agents has no column named focus_items"). Tables and
        columns must match exactly. The FK/index differences below predate this
        check and are listed one by one, so any new drift still fails.
        """
        from alembic.autogenerate import compare_metadata
        from alembic.migration import MigrationContext

        db_file = tmp_path / "chain.db"
        cfg = Config("alembic.ini")
        cfg.set_main_option("sqlalchemy.url", f"sqlite+aiosqlite:///{db_file.as_posix()}")
        command.upgrade(cfg, "head")

        engine = create_engine(f"sqlite:///{db_file.as_posix()}")
        with engine.connect() as conn:
            ctx = MigrationContext.configure(conn, opts={"compare_type": False})
            diffs = compare_metadata(ctx, SQLModel.metadata)
        engine.dispose()

        def key(diff) -> tuple:
            kind, obj = diff[0], diff[-1]
            if kind in ("add_column", "remove_column"):
                return (kind, diff[2], obj.name)
            if kind in ("add_table", "remove_table"):
                return (kind, obj.name, ())
            table = obj.table.name
            cols = tuple(sorted(c.name for c in getattr(obj, "columns", [])))
            return (kind, table, cols)

        found = {key(d) for d in diffs if isinstance(d, tuple)}
        known = {
            ("add_fk", "api_keys", ("created_by",)),
            ("add_fk", "cost_events", ("policy_id",)),
            ("remove_fk", "cost_events", ("policy_id",)),
            ("add_fk", "tasks", ("goal_id",)),
            ("remove_fk", "knowledge_chunks", ("source_id",)),
            ("remove_index", "knowledge_chunks", ("source_id", "source_type")),
            ("remove_index", "workflow_runs", ("status",)),
            ("remove_index", "obsidian_documents", ("company_id", "vault_path")),
            ("add_constraint", "obsidian_documents", ("company_id", "vault_path")),
        }
        assert not [d for d in diffs if not isinstance(d, tuple)], "column type/nullability diffs"
        assert found - known == set(), f"Schema drift between models and migrations: {sorted(found - known)}"


class TestSchemaCreation:
    """Verify full schema can be created in SQLite in-memory database."""

    def test_create_all_with_sqlite(self) -> None:
        """Use SQLite in-memory engine with SQLModel.metadata.create_all()."""
        engine = create_engine("sqlite:///:memory:")
        SQLModel.metadata.create_all(engine)

        inspector = inspect(engine)
        created_tables = set(inspector.get_table_names())
        assert "circuit_breaker_records" in created_tables
        assert "kill_switch_records" in created_tables
        assert "agents" in created_tables
