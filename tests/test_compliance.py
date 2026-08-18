"""Tests for Compliance Framework - rules, health checks, and violations.

Tests compliance rule evaluation, health check functionality, violation
detection, data classification rules, and report generation.
"""

import asyncio
import sys
import uuid
from pathlib import Path

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


def run_async(coro):
    """Helper to run async coroutines in tests."""
    return asyncio.run(coro)


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

    def test_log_entry_creates_hash_chain(self):
        logger = PersistentAuditLogger()
        e1 = run_async(logger.log_entry("agent", "a1", "action1"))
        e2 = run_async(logger.log_entry("agent", "a1", "action2"))

        assert e1.entry_hash != ""
        assert e2.entry_hash != ""
        assert e2.previous_hash == e1.entry_hash
        assert e1.previous_hash == "genesis"

    def test_hash_chain_integrity_valid(self):
        logger = PersistentAuditLogger()
        run_async(logger.log_entry("agent", "a1", "action1"))
        run_async(logger.log_entry("agent", "a1", "action2"))
        run_async(logger.log_entry("user", "u1", "action3"))

        assert logger.verify_chain_integrity() is True

    def test_hash_chain_detects_tampering(self):
        logger = PersistentAuditLogger()
        run_async(logger.log_entry("agent", "a1", "action1"))
        e2 = run_async(logger.log_entry("agent", "a1", "action2"))

        # Tamper with an entry
        e2.action = "tampered_action"

        # Force flush to move from buffer to entries for verification
        run_async(logger.flush_buffer())
        assert logger.verify_chain_integrity() is False

    def test_buffer_flushes_at_capacity(self):
        logger = PersistentAuditLogger(buffer_size=3)
        run_async(logger.log_entry("agent", "a1", "action1"))
        run_async(logger.log_entry("agent", "a1", "action2"))
        assert logger.buffer_count == 2
        assert logger.total_entries == 0

        run_async(logger.log_entry("agent", "a1", "action3"))
        # Buffer should have flushed
        assert logger.buffer_count == 0
        assert logger.total_entries == 3

    def test_query_by_actor(self):
        logger = PersistentAuditLogger()
        run_async(logger.log_entry("agent", "agent-1", "deploy"))
        run_async(logger.log_entry("agent", "agent-2", "build"))
        run_async(logger.log_entry("agent", "agent-1", "test"))

        results = logger.query_by_actor("agent-1")
        assert len(results) == 2
        assert all(e.actor_id == "agent-1" for e in results)

    def test_query_by_time_range(self):
        logger = PersistentAuditLogger()
        from datetime import datetime, timedelta, timezone
        now = datetime.now(timezone.utc)

        run_async(logger.log_entry("agent", "a1", "action1"))
        run_async(logger.log_entry("agent", "a1", "action2"))

        start = now - timedelta(minutes=1)
        end = now + timedelta(minutes=1)
        results = logger.query_by_time_range(start, end)
        assert len(results) == 2

    def test_export_json(self):
        import json
        logger = PersistentAuditLogger()
        run_async(logger.log_entry("agent", "a1", "deploy"))

        exported = logger.export_json()
        data = json.loads(exported)
        assert len(data) == 1
        assert data[0]["actor_id"] == "a1"
        assert data[0]["action"] == "deploy"

    def test_export_csv(self):
        logger = PersistentAuditLogger()
        run_async(logger.log_entry("agent", "a1", "deploy"))

        csv = logger.export_csv()
        lines = csv.strip().split("\n")
        assert len(lines) == 2  # header + 1 entry
        assert "actor_type" in lines[0]
        assert "a1" in lines[1]

    def test_retention_policy_archives_old(self):
        from datetime import timedelta
        logger = PersistentAuditLogger(buffer_size=100)
        # Create an old entry
        e1 = run_async(logger.log_entry("agent", "a1", "old_action"))
        e1.timestamp = e1.timestamp - timedelta(days=100)

        # Create a recent entry
        run_async(logger.log_entry("agent", "a1", "new_action"))

        # Flush to storage
        run_async(logger.flush_buffer())

        # Set retention to 30 days
        logger.set_retention_policy(max_age_days=30)
        archived = run_async(logger.enforce_retention())
        assert archived == 1
        assert logger.total_entries == 1
        assert len(logger.get_archived_entries()) == 1

    def test_sequence_numbers_increment(self):
        logger = PersistentAuditLogger()
        e1 = run_async(logger.log_entry("agent", "a1", "action1"))
        e2 = run_async(logger.log_entry("agent", "a1", "action2"))
        e3 = run_async(logger.log_entry("agent", "a1", "action3"))

        assert e1.sequence_number == 1
        assert e2.sequence_number == 2
        assert e3.sequence_number == 3


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
