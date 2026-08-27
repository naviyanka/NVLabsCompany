"""Tests for Compliance Framework - rules, health checks, and violations.

Tests compliance rule evaluation, health check functionality, violation
detection, data classification rules, and report generation.
"""

import asyncio
import importlib.util
import sys
import uuid
from datetime import timedelta
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlmodel import SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession

# Add src to path for direct execution
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from nexus.governance.compliance import (
    ComplianceFramework,
    ComplianceRule,
    ComplianceStatus,
    DataClassification,
    DataHandlingRule,
)
from nexus.governance.audit_persistent import PersistentAuditLogger
from nexus.models.governance import AuditLog, AuditLogArchive


def run_async(coro):
    """Helper to run async coroutines in tests."""
    return asyncio.run(coro)


_MIGRATION = (
    Path(__file__).parent.parent
    / "alembic"
    / "versions"
    / "e1a7b4c93d20_audit_log_hash_chain.py"
)


def _load_migration():
    """Load the Phase 0.1 migration so tests use its real guard SQL."""
    spec = importlib.util.spec_from_file_location("_audit_chain_mig", _MIGRATION)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


async def _make_audit_db(db_path: Path):
    """Create a SQLite audit DB with the append-only guard installed.

    Returns an (engine, session_factory) pair. The guard SQL is taken from the
    migration module so the test exercises the shipped statements.
    """
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}")
    mig = _load_migration()

    async with engine.begin() as conn:
        await conn.run_sync(
            SQLModel.metadata.create_all,
            tables=[AuditLog.__table__, AuditLogArchive.__table__],
        )
        await conn.execute(
            text(mig._SQLITE_GUARD_UPDATE.format(
                conditions=mig._sqlite_update_conditions()
            ))
        )
        await conn.execute(text(mig._SQLITE_GUARD_DELETE))

    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    return engine, factory


@pytest.fixture
async def audit_db(tmp_path):
    """A fresh file-backed audit database per test."""
    engine, factory = await _make_audit_db(tmp_path / "audit.db")
    try:
        yield factory
    finally:
        await engine.dispose()


@pytest.fixture
async def audit_logger(audit_db):
    """A PersistentAuditLogger bound to the test database."""
    return PersistentAuditLogger(session_factory=audit_db)


class TestComplianceFramework:
    """Tests for the ComplianceFramework."""

    def test_add_rule(self):
        fw = ComplianceFramework()
        rule = ComplianceRule(
            name="audit_required",
            description="Audit logging must be enabled",
            category="audit",
            check_function_name="audit_enabled",
        )
        added = fw.add_rule(rule)
        assert added.name == "audit_required"

    def test_remove_rule(self):
        fw = ComplianceFramework()
        rule = ComplianceRule(name="test_rule")
        fw.add_rule(rule)
        assert fw.remove_rule(rule.id) is True
        assert fw.remove_rule(uuid.uuid4()) is False

    def test_health_check_all_compliant(self):
        fw = ComplianceFramework()
        fw.set_policy_status("audit_logging", True)
        rule = ComplianceRule(
            name="audit_required",
            check_function_name="audit_enabled",
            is_mandatory=True,
        )
        fw.add_rule(rule)

        report = fw.check_compliance_health()
        assert report.overall_status == ComplianceStatus.compliant
        assert report.rules_passed == 1
        assert report.rules_failed == 0

    def test_health_check_non_compliant(self):
        fw = ComplianceFramework()
        fw.set_policy_status("audit_logging", False)
        rule = ComplianceRule(
            name="audit_required",
            check_function_name="audit_enabled",
            is_mandatory=True,
        )
        fw.add_rule(rule)

        report = fw.check_compliance_health()
        assert report.overall_status == ComplianceStatus.non_compliant
        assert report.rules_failed == 1
        assert len(report.violations) == 1

    def test_policy_active_check(self):
        fw = ComplianceFramework()
        fw.set_policy_status("encryption_policy", True)
        rule = ComplianceRule(
            name="encryption_active",
            check_function_name="policy_active",
            parameters={"policy_name": "encryption_policy"},
        )
        fw.add_rule(rule)

        report = fw.check_compliance_health()
        assert report.rules_passed == 1

    def test_detect_violations(self):
        fw = ComplianceFramework()
        fw.set_policy_status("audit_logging", False)
        fw.set_policy_status("retention_policy", False)
        fw.add_rule(ComplianceRule(
            name="audit_required",
            check_function_name="audit_enabled",
            is_mandatory=True,
        ))
        fw.add_rule(ComplianceRule(
            name="retention_required",
            check_function_name="retention_configured",
            is_mandatory=True,
        ))

        violations = fw.detect_violations()
        assert len(violations) == 2

    def test_generate_report_includes_details(self):
        fw = ComplianceFramework()
        fw.set_policy_status("audit_logging", True)
        fw.add_rule(ComplianceRule(
            name="audit_required",
            check_function_name="audit_enabled",
        ))

        report = fw.generate_report()
        assert "total_rules_configured" in report.details
        assert "mandatory_rules" in report.details
        assert "active_policies" in report.details
        assert report.details["active_policies"] == 1

    def test_data_classification(self):
        fw = ComplianceFramework()
        fw.classify_data("user_passwords", DataClassification.restricted)
        fw.classify_data("public_docs", DataClassification.public)

        assert fw.get_data_classification("user_passwords") == DataClassification.restricted
        assert fw.get_data_classification("public_docs") == DataClassification.public
        assert fw.get_data_classification("unknown") is None

    def test_data_handling_rules_per_classification(self):
        fw = ComplianceFramework()

        # Restricted data requires encryption
        rules = fw.get_data_handling_rules(DataClassification.restricted)
        assert rules.encryption_required is True
        assert rules.audit_access is True
        assert rules.requires_approval is True

        # Public data does not require encryption
        rules = fw.get_data_handling_rules(DataClassification.public)
        assert rules.encryption_required is False
        assert rules.requires_approval is False

    def test_custom_data_handling_rules(self):
        fw = ComplianceFramework()
        custom_rule = DataHandlingRule(
            classification=DataClassification.internal,
            encryption_required=True,
            audit_access=True,
            retention_days=30,
            requires_approval=True,
        )
        fw.set_data_handling_rules(DataClassification.internal, custom_rule)

        rules = fw.get_data_handling_rules(DataClassification.internal)
        assert rules.encryption_required is True
        assert rules.retention_days == 30

    def test_data_classified_check(self):
        fw = ComplianceFramework()
        fw.classify_data("resource-1", DataClassification.internal)
        rule = ComplianceRule(
            name="data_must_be_classified",
            check_function_name="data_classified",
            parameters={"resource_ids": ["resource-1"]},
        )
        fw.add_rule(rule)

        report = fw.check_compliance_health()
        assert report.rules_passed == 1

    def test_data_classified_check_fails_for_unclassified(self):
        fw = ComplianceFramework()
        rule = ComplianceRule(
            name="data_must_be_classified",
            check_function_name="data_classified",
            parameters={"resource_ids": ["unclassified-resource"]},
            is_mandatory=True,
        )
        fw.add_rule(rule)

        report = fw.check_compliance_health()
        assert report.rules_failed == 1

    def test_get_violations_with_filters(self):
        fw = ComplianceFramework()
        company = uuid.uuid4()
        fw.set_policy_status("audit_logging", False)
        fw.add_rule(ComplianceRule(
            name="audit_required",
            check_function_name="audit_enabled",
            is_mandatory=True,
        ))
        fw.check_compliance_health(company_id=company)

        violations = fw.get_violations(company_id=company)
        assert len(violations) >= 1
        assert violations[0].company_id == company

    def test_disabled_rules_are_skipped(self):
        fw = ComplianceFramework()
        rule = ComplianceRule(
            name="disabled_rule",
            check_function_name="audit_enabled",
            enabled=False,
        )
        fw.add_rule(rule)

        report = fw.check_compliance_health()
        assert report.total_rules == 0


class TestPersistentAuditLogger:
    """Tests for PersistentAuditLogger hash chain and operations."""

    async def test_log_entry_creates_hash_chain(self, audit_logger):
        e1 = await audit_logger.log_entry("agent", "a1", "action1")
        e2 = await audit_logger.log_entry("agent", "a1", "action2")

        assert e1.entry_hash != ""
        assert e2.entry_hash != ""
        assert e2.previous_hash == e1.entry_hash
        assert e1.previous_hash == "genesis"

    async def test_hash_chain_integrity_valid(self, audit_logger):
        await audit_logger.log_entry("agent", "a1", "action1")
        await audit_logger.log_entry("agent", "a1", "action2")
        await audit_logger.log_entry("user", "u1", "action3")
        await audit_logger.flush_buffer()

        assert await audit_logger.verify_chain_integrity() is True

    async def test_hash_chain_detects_tampering(self, audit_db, audit_logger):
        await audit_logger.log_entry("agent", "a1", "action1")
        e2 = await audit_logger.log_entry("agent", "a1", "action2")
        await audit_logger.flush_buffer()

        # Tamper at the storage layer. The guard blocks a normal UPDATE, so
        # simulate an attacker with direct table access by rewriting the row
        # with the trigger dropped.
        async with audit_db() as session:
            await session.execute(text("DROP TRIGGER audit_log_no_update"))
            await session.execute(
                text("UPDATE audit_log SET action = 'tampered' WHERE id = :i"),
                {"i": e2.id.hex},
            )
            await session.commit()

        assert await audit_logger.verify_chain_integrity() is False

    async def test_buffer_flushes_at_capacity(self, audit_db):
        logger = PersistentAuditLogger(buffer_size=3, session_factory=audit_db)
        await logger.log_entry("agent", "a1", "action1")
        await logger.log_entry("agent", "a1", "action2")
        assert logger.buffer_count == 2
        assert await logger.total_entries() == 0

        await logger.log_entry("agent", "a1", "action3")
        # Buffer should have flushed
        assert logger.buffer_count == 0
        assert await logger.total_entries() == 3

    async def test_query_by_actor(self, audit_logger):
        await audit_logger.log_entry("agent", "agent-1", "deploy")
        await audit_logger.log_entry("agent", "agent-2", "build")
        await audit_logger.log_entry("agent", "agent-1", "test")
        await audit_logger.flush_buffer()

        results = await audit_logger.query_by_actor("agent-1")
        assert len(results) == 2
        assert all(e.actor_id == "agent-1" for e in results)

    async def test_query_by_time_range(self, audit_logger):
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc)

        await audit_logger.log_entry("agent", "a1", "action1")
        await audit_logger.log_entry("agent", "a1", "action2")
        await audit_logger.flush_buffer()

        start = now - timedelta(minutes=1)
        end = now + timedelta(minutes=1)
        results = await audit_logger.query_by_time_range(start, end)
        assert len(results) == 2

    async def test_export_json(self, audit_logger):
        import json
        await audit_logger.log_entry("agent", "a1", "deploy")
        await audit_logger.flush_buffer()

        exported = await audit_logger.export_json()
        data = json.loads(exported)
        assert len(data) == 1
        assert data[0]["actor_id"] == "a1"
        assert data[0]["action"] == "deploy"

    async def test_export_csv(self, audit_logger):
        await audit_logger.log_entry("agent", "a1", "deploy")
        await audit_logger.flush_buffer()

        csv = await audit_logger.export_csv()
        lines = csv.strip().split("\n")
        assert len(lines) == 2  # header + 1 entry
        assert "actor_type" in lines[0]
        assert "a1" in lines[1]

    async def test_retention_copies_and_keeps_the_chain(self, audit_db):
        """Retention archives old rows without breaking verification."""
        logger = PersistentAuditLogger(buffer_size=100, session_factory=audit_db)

        old = await logger.log_entry("agent", "a1", "old_action")
        old.timestamp = old.timestamp - timedelta(days=100)
        # Rehash so the backdated timestamp still matches its chain hash.
        old.entry_hash = logger.compute_entry_hash(old, old.previous_hash)
        logger._last_hash = old.entry_hash

        await logger.log_entry("agent", "a1", "new_action")
        await logger.flush_buffer()

        logger.set_retention_policy(max_age_days=30)
        archived = await logger.enforce_retention()

        assert archived == 1
        assert len(await logger.get_archived_entries()) == 1
        # The source row stays in audit_log — only flagged, never removed.
        assert await logger.total_entries() == 2
        assert await logger.active_entries() == 1
        assert await logger.verify_chain_integrity() is True

    async def test_sequence_numbers_increment(self, audit_logger):
        e1 = await audit_logger.log_entry("agent", "a1", "action1")
        e2 = await audit_logger.log_entry("agent", "a1", "action2")
        e3 = await audit_logger.log_entry("agent", "a1", "action3")

        assert e1.sequence_number == 1
        assert e2.sequence_number == 2
        assert e3.sequence_number == 3

    async def test_chain_survives_restart(self, audit_db):
        """Phase 0.1 acceptance: 100 entries, new process, chain still valid."""
        logger = PersistentAuditLogger(buffer_size=10, session_factory=audit_db)
        for i in range(100):
            await logger.log_entry("agent", "a1", f"action{i}")
        await logger.flush_buffer()

        # A fresh logger stands in for a restarted process.
        restarted = PersistentAuditLogger(session_factory=audit_db)
        assert await restarted.resume() == 100
        assert await restarted.verify_chain_integrity() is True
        assert await restarted.total_entries() == 100

        # Logging continues from the persisted tail rather than restarting.
        entry = await restarted.log_entry("agent", "a1", "after_restart")
        assert entry.sequence_number == 101
        await restarted.flush_buffer()
        assert await restarted.verify_chain_integrity() is True

    async def test_update_is_rejected_by_the_database(self, audit_db, audit_logger):
        """A manual UPDATE against a chain column fails."""
        entry = await audit_logger.log_entry("agent", "a1", "action1")
        await audit_logger.flush_buffer()

        async with audit_db() as session:
            with pytest.raises(Exception, match="append-only"):
                await session.execute(
                    text("UPDATE audit_log SET action = 'x' WHERE id = :i"),
                    {"i": entry.id.hex},
                )
                await session.commit()

    async def test_delete_is_rejected_by_the_database(self, audit_db, audit_logger):
        """A manual DELETE fails — the chain cannot be truncated."""
        entry = await audit_logger.log_entry("agent", "a1", "action1")
        await audit_logger.flush_buffer()

        async with audit_db() as session:
            with pytest.raises(Exception, match="append-only"):
                await session.execute(
                    text("DELETE FROM audit_log WHERE id = :i"), {"i": entry.id.hex}
                )
                await session.commit()

        assert await audit_logger.total_entries() == 1

    async def test_archived_at_remains_writable(self, audit_db, audit_logger):
        """The guard allows the one column retention needs to stamp."""
        entry = await audit_logger.log_entry("agent", "a1", "action1")
        await audit_logger.flush_buffer()

        async with audit_db() as session:
            await session.execute(
                text("UPDATE audit_log SET archived_at = :t WHERE id = :i"),
                {"t": "2026-01-01 00:00:00", "i": entry.id.hex},
            )
            await session.commit()

        assert await audit_logger.active_entries() == 0


if __name__ == "__main__":
    # Run tests directly
    passed = 0
    failed = 0

    for cls in [TestComplianceFramework, TestPersistentAuditLogger]:
        instance = cls()
        for method_name in sorted(dir(instance)):
            if method_name.startswith("test_"):
                try:
                    getattr(instance, method_name)()
                    passed += 1
                    print(f"  PASS: {cls.__name__}.{method_name}")
                except Exception as e:
                    failed += 1
                    print(f"  FAIL: {cls.__name__}.{method_name}: {e}")

    print(f"\n{passed} passed, {failed} failed")
    sys.exit(0 if failed == 0 else 1)
