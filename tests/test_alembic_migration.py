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
    "agent_skills",
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
    "meeting_minutes",
    "meeting_participants",
    "meetings",
    "memory_records",
    "messages",
    "notification_preferences",
    "notifications",
    "obsidian_documents",
    "okr_key_results",
    "okr_objectives",
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
