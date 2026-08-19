"""Tests for Alembic migration completeness and validity."""

import ast
from pathlib import Path

import pytest
from sqlalchemy import inspect
from sqlmodel import SQLModel, create_engine

# Import all models to ensure they are registered in SQLModel.metadata
import nexus.models  # noqa: F401


ALEMBIC_VERSIONS_DIR = Path(__file__).resolve().parent.parent / "alembic" / "versions"

EXPECTED_TABLES = {
    "action_items",
    "agent_skills",
    "agent_versions",
    "agents",
    "approvals",
    "audit_log",
    "budget_policies",
    "circuit_breaker_records",
    "companies",
    "company_memberships",
    "cost_events",
    "decision_queues",
    "decisions",
    "departments",
    "events",
    "evolution_evaluations",
    "evolution_proposals",
    "experience_records",
    "goals",
    "group_members",
    "groups",
    "incident_actions",
    "incident_events",
    "incidents",
    "kill_switch_records",
    "knowledge_chunks",
    "knowledge_pages",
    "meeting_minutes",
    "meeting_participants",
    "meetings",
    "memory_records",
    "messages",
    "policies",
    "policy_rules",
    "policy_versions",
    "projects",
    "secret_accesses",
    "secret_bindings",
    "secret_versions",
    "secrets",
    "skill_versions",
    "skills",
    "tasks",
    "teams",
    "tool_access",
    "tools",
    "trigger_executions",
    "triggers",
}

MIGRATION_FILES = [
    "db96cb66effc_initial_schema.py",
    "ca7238bc6797_add_kill_switch_records_table.py",
    "a1b2c3d4e5f6_add_circuit_breaker_records_table.py",
]

# Expected migration chain: None -> db96cb66effc -> ca7238bc6797 -> a1b2c3d4e5f6
MIGRATION_CHAIN = [
    ("db96cb66effc_initial_schema.py", None, "db96cb66effc"),
    (
        "ca7238bc6797_add_kill_switch_records_table.py",
        "db96cb66effc",
        "ca7238bc6797",
    ),
    (
        "a1b2c3d4e5f6_add_circuit_breaker_records_table.py",
        "ca7238bc6797",
        "a1b2c3d4e5f6",
    ),
]


class TestModelMetadata:
    """Verify all SQLModel tables are discoverable in metadata."""

    def test_all_expected_tables_in_metadata(self) -> None:
        """Import all models and confirm metadata contains all 48 expected tables."""
        actual_tables = set(SQLModel.metadata.tables.keys())
        assert len(actual_tables) == 48, (
            f"Expected 48 tables, found {len(actual_tables)}: "
            f"missing={EXPECTED_TABLES - actual_tables}, "
            f"extra={actual_tables - EXPECTED_TABLES}"
        )
        assert actual_tables == EXPECTED_TABLES

    def test_circuit_breaker_records_in_metadata(self) -> None:
        """Verify circuit_breaker_records table is registered in metadata."""
        assert "circuit_breaker_records" in SQLModel.metadata.tables


class TestMigrationFiles:
    """Verify all migration files exist and are valid Python."""

    @pytest.mark.parametrize("filename", MIGRATION_FILES)
    def test_migration_file_exists(self, filename: str) -> None:
        """Verify each migration file exists in alembic/versions/."""
        filepath = ALEMBIC_VERSIONS_DIR / filename
        assert filepath.exists(), f"Migration file not found: {filepath}"

    @pytest.mark.parametrize("filename", MIGRATION_FILES)
    def test_migration_file_is_valid_python(self, filename: str) -> None:
        """Verify each migration file is syntactically valid Python via ast.parse."""
        filepath = ALEMBIC_VERSIONS_DIR / filename
        source = filepath.read_text()
        try:
            ast.parse(source)
        except SyntaxError as e:
            pytest.fail(f"Migration file {filename} has syntax error: {e}")


class TestMigrationChain:
    """Verify the migration chain is consistent."""

    @pytest.mark.parametrize("filename,expected_down,expected_rev", MIGRATION_CHAIN)
    def test_migration_chain_consistency(
        self, filename: str, expected_down: str | None, expected_rev: str
    ) -> None:
        """Verify each migration's down_revision points to the previous one."""
        filepath = ALEMBIC_VERSIONS_DIR / filename
        source = filepath.read_text()
        tree = ast.parse(source)

        revision_value = None
        down_revision_value = None

        for node in ast.walk(tree):
            # Handle annotated assignments (e.g., revision: str = 'abc')
            if isinstance(node, ast.AnnAssign):
                if isinstance(node.target, ast.Name):
                    if node.target.id == "revision":
                        if isinstance(node.value, ast.Constant):
                            revision_value = node.value.value
                    elif node.target.id == "down_revision":
                        if isinstance(node.value, ast.Constant):
                            down_revision_value = node.value.value
            # Handle plain assignments (e.g., revision = 'abc')
            elif isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        if target.id == "revision":
                            if isinstance(node.value, ast.Constant):
                                revision_value = node.value.value
                        elif target.id == "down_revision":
                            if isinstance(node.value, ast.Constant):
                                down_revision_value = node.value.value

        assert revision_value == expected_rev, (
            f"In {filename}: expected revision={expected_rev!r}, got {revision_value!r}"
        )
        assert down_revision_value == expected_down, (
            f"In {filename}: expected down_revision={expected_down!r}, "
            f"got {down_revision_value!r}"
        )


class TestSchemaCreation:
    """Verify full schema can be created in SQLite in-memory database."""

    def test_create_all_with_sqlite(self) -> None:
        """Use SQLite in-memory engine with SQLModel.metadata.create_all()."""
        engine = create_engine("sqlite:///:memory:")
        SQLModel.metadata.create_all(engine)

        # Verify tables were created by inspecting the engine
        inspector = inspect(engine)
        created_tables = set(inspector.get_table_names())
        assert "circuit_breaker_records" in created_tables
        assert "kill_switch_records" in created_tables
        assert "agents" in created_tables
        assert len(created_tables) == 48
