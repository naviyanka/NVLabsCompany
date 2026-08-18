"""Compliance Framework - compliance rule checking, health monitoring, and reporting.

Defines compliance rules, performs health checks, detects violations,
and generates compliance reports with data classification enforcement.
"""

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any


class DataClassification(str, Enum):
    """Data classification levels."""

    public = "public"
    internal = "internal"
    confidential = "confidential"
    restricted = "restricted"


class ComplianceStatus(str, Enum):
    """Status of a compliance check."""

    compliant = "compliant"
    non_compliant = "non_compliant"
    warning = "warning"
    unknown = "unknown"


@dataclass
class ComplianceRule:
    """A compliance rule that must be satisfied.

    Attributes:
        id: Unique rule identifier.
        name: Human-readable rule name.
        description: What the rule checks.
        category: Rule category (audit, data_handling, retention, access).
        is_mandatory: Whether this rule is required for compliance.
        check_function_name: Name of the check to perform.
        parameters: Configuration for the rule check.
        enabled: Whether the rule is active.
    """

    id: uuid.UUID = field(default_factory=uuid.uuid4)
    name: str = ""
    description: str = ""
    category: str = "general"
    is_mandatory: bool = True
    check_function_name: str = ""
    parameters: dict[str, Any] = field(default_factory=dict)
    enabled: bool = True


@dataclass
class ComplianceViolation:
    """A detected compliance violation.

    Attributes:
        id: Unique violation identifier.
        rule_id: The rule that was violated.
        rule_name: Name of the violated rule.
        severity: Severity level (critical, high, medium, low).
        description: Description of the violation.
        detected_at: When the violation was detected.
        company_id: Company where the violation occurred.
        resource_id: Affected resource identifier.
        remediation: Suggested fix.
    """

    id: uuid.UUID = field(default_factory=uuid.uuid4)
    rule_id: uuid.UUID = field(default_factory=uuid.uuid4)
    rule_name: str = ""
    severity: str = "medium"
    description: str = ""
    detected_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    company_id: uuid.UUID | None = None
    resource_id: str | None = None
    remediation: str = ""


@dataclass
class ComplianceReport:
    """A compliance health report.

    Attributes:
        id: Unique report identifier.
        generated_at: When the report was generated.
        overall_status: Overall compliance status.
        total_rules: Total number of rules checked.
        rules_passed: Number of rules passing.
        rules_failed: Number of rules failing.
        violations: List of current violations.
        company_id: Company this report covers.
        details: Additional report details.
    """

    id: uuid.UUID = field(default_factory=uuid.uuid4)
    generated_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    overall_status: ComplianceStatus = ComplianceStatus.unknown
    total_rules: int = 0
    rules_passed: int = 0
    rules_failed: int = 0
    violations: list[ComplianceViolation] = field(default_factory=list)
    company_id: uuid.UUID | None = None
    details: dict[str, Any] = field(default_factory=dict)


@dataclass
class DataHandlingRule:
    """Rules for handling data of a specific classification.

    Attributes:
        classification: The data classification this applies to.
        encryption_required: Whether encryption is required.
        audit_access: Whether access must be audited.
        retention_days: Maximum retention period.
        allowed_exports: Where data can be exported.
        requires_approval: Whether access requires approval.
    """

    classification: DataClassification = DataClassification.internal
    encryption_required: bool = False
    audit_access: bool = True
    retention_days: int = 365
    allowed_exports: list[str] = field(default_factory=list)
    requires_approval: bool = False


class ComplianceFramework:
    """Compliance checking framework.

    Manages compliance rules, performs health checks, detects violations,
    and generates compliance reports. Integrates data classification with
    handling rules.
    """

    def __init__(self) -> None:
        """Initialize the compliance framework."""
        self._rules: dict[uuid.UUID, ComplianceRule] = {}
        self._violations: list[ComplianceViolation] = []
        self._data_handling_rules: dict[DataClassification, DataHandlingRule] = {}
        self._policy_status: dict[str, bool] = {}
        self._data_classifications: dict[str, DataClassification] = {}

        # Initialize default data handling rules
        self._init_default_handling_rules()

    def _init_default_handling_rules(self) -> None:
        """Set up default data handling rules per classification."""
        self._data_handling_rules[DataClassification.public] = DataHandlingRule(
            classification=DataClassification.public,
            encryption_required=False,
            audit_access=False,
            retention_days=365 * 10,
            allowed_exports=["json", "csv", "api"],
            requires_approval=False,
        )
        self._data_handling_rules[DataClassification.internal] = DataHandlingRule(
            classification=DataClassification.internal,
            encryption_required=False,
            audit_access=True,
            retention_days=365 * 3,
            allowed_exports=["json", "csv"],
            requires_approval=False,
        )
        self._data_handling_rules[DataClassification.confidential] = DataHandlingRule(
            classification=DataClassification.confidential,
            encryption_required=True,
            audit_access=True,
            retention_days=365,
            allowed_exports=["json"],
            requires_approval=True,
        )
        self._data_handling_rules[DataClassification.restricted] = DataHandlingRule(
            classification=DataClassification.restricted,
            encryption_required=True,
            audit_access=True,
            retention_days=90,
            allowed_exports=[],
            requires_approval=True,
        )

    def add_rule(self, rule: ComplianceRule) -> ComplianceRule:
        """Add a compliance rule to the framework.

        Args:
            rule: The rule to add.

        Returns:
            The added rule.
        """
        self._rules[rule.id] = rule
        return rule

    def remove_rule(self, rule_id: uuid.UUID) -> bool:
        """Remove a compliance rule.

        Args:
            rule_id: The rule to remove.

        Returns:
            True if removed, False if not found.
        """
        if rule_id in self._rules:
            del self._rules[rule_id]
            return True
        return False

    def set_policy_status(self, policy_name: str, is_active: bool) -> None:
        """Record whether a policy is currently active.

        Used by check_compliance_health to verify required policies.

        Args:
            policy_name: Name of the policy.
            is_active: Whether the policy is active.
        """
        self._policy_status[policy_name] = is_active

    def check_compliance_health(
        self,
        company_id: uuid.UUID | None = None,
    ) -> ComplianceReport:
        """Perform a compliance health check.

        Verifies all mandatory rules are satisfied and all required
        policies are active.

        Args:
            company_id: Company to check (None for system-wide).

        Returns:
            ComplianceReport with overall status and violations.
        """
        violations: list[ComplianceViolation] = []
        rules_passed = 0
        rules_failed = 0

        for rule in self._rules.values():
            if not rule.enabled:
                continue

            passed = self._evaluate_rule(rule, company_id)
            if passed:
                rules_passed += 1
            else:
                rules_failed += 1
                if rule.is_mandatory:
                    violation = ComplianceViolation(
                        rule_id=rule.id,
                        rule_name=rule.name,
                        severity="critical" if rule.is_mandatory else "medium",
                        description=f"Rule '{rule.name}' is not satisfied",
                        company_id=company_id,
                    )
                    violations.append(violation)

        total_rules = rules_passed + rules_failed

        if rules_failed == 0 and total_rules > 0:
            status = ComplianceStatus.compliant
        elif any(v.severity == "critical" for v in violations):
            status = ComplianceStatus.non_compliant
        elif rules_failed > 0:
            status = ComplianceStatus.warning
        else:
            status = ComplianceStatus.unknown

        report = ComplianceReport(
            overall_status=status,
            total_rules=total_rules,
            rules_passed=rules_passed,
            rules_failed=rules_failed,
            violations=violations,
            company_id=company_id,
        )

        # Store violations for later querying
        self._violations.extend(violations)

        return report

    def detect_violations(
        self,
        company_id: uuid.UUID | None = None,
    ) -> list[ComplianceViolation]:
        """Detect current compliance violations.

        Args:
            company_id: Company to check (None for all).

        Returns:
            List of detected violations.
        """
        violations: list[ComplianceViolation] = []
        for rule in self._rules.values():
            if not rule.enabled:
                continue
            if not self._evaluate_rule(rule, company_id):
                violation = ComplianceViolation(
                    rule_id=rule.id,
                    rule_name=rule.name,
                    severity="critical" if rule.is_mandatory else "medium",
                    description=f"Violation of rule '{rule.name}': {rule.description}",
                    company_id=company_id,
                    remediation=f"Ensure {rule.check_function_name} passes",
                )
                violations.append(violation)
        return violations

    def generate_report(
        self,
        company_id: uuid.UUID | None = None,
    ) -> ComplianceReport:
        """Generate a comprehensive compliance report.

        Args:
            company_id: Company to report on.

        Returns:
            Full ComplianceReport.
        """
        report = self.check_compliance_health(company_id)
        report.details = {
            "total_rules_configured": len(self._rules),
            "mandatory_rules": sum(
                1 for r in self._rules.values() if r.is_mandatory
            ),
            "enabled_rules": sum(
                1 for r in self._rules.values() if r.enabled
            ),
            "active_policies": sum(
                1 for active in self._policy_status.values() if active
            ),
            "total_policies_tracked": len(self._policy_status),
            "data_classifications_in_use": len(self._data_classifications),
            "historical_violations": len(self._violations),
        }
        return report

    def classify_data(
        self,
        resource_id: str,
        classification: DataClassification,
    ) -> None:
        """Assign a data classification to a resource.

        Args:
            resource_id: The resource to classify.
            classification: The classification level.
        """
        self._data_classifications[resource_id] = classification

    def get_data_classification(
        self,
        resource_id: str,
    ) -> DataClassification | None:
        """Get the classification for a resource.

        Args:
            resource_id: The resource to look up.

        Returns:
            The DataClassification, or None if not classified.
        """
        return self._data_classifications.get(resource_id)

    def get_data_handling_rules(
        self,
        classification: DataClassification,
    ) -> DataHandlingRule:
        """Get handling rules for a data classification.

        Args:
            classification: The classification level.

        Returns:
            DataHandlingRule for the classification.
        """
        return self._data_handling_rules[classification]

    def set_data_handling_rules(
        self,
        classification: DataClassification,
        rules: DataHandlingRule,
    ) -> None:
        """Update handling rules for a data classification.

        Args:
            classification: The classification level.
            rules: The new handling rules.
        """
        self._data_handling_rules[classification] = rules

    def get_violations(
        self,
        company_id: uuid.UUID | None = None,
        severity: str | None = None,
        limit: int = 100,
    ) -> list[ComplianceViolation]:
        """Get recorded violations with optional filters.

        Args:
            company_id: Filter by company.
            severity: Filter by severity level.
            limit: Maximum entries to return.

        Returns:
            List of ComplianceViolation objects.
        """
        results: list[ComplianceViolation] = []
        for violation in reversed(self._violations):
            if company_id and violation.company_id != company_id:
                continue
            if severity and violation.severity != severity:
                continue
            results.append(violation)
            if len(results) >= limit:
                break
        return results

    def _evaluate_rule(
        self,
        rule: ComplianceRule,
        company_id: uuid.UUID | None = None,
    ) -> bool:
        """Evaluate a single compliance rule.

        Checks based on the rule's check_function_name:
        - policy_active: Checks if a named policy is active.
        - audit_enabled: Checks if audit logging is active.
        - encryption_required: Checks classification-based encryption.
        - retention_configured: Checks if retention policy exists.

        Args:
            rule: The rule to evaluate.
            company_id: Company context.

        Returns:
            True if the rule passes, False if violated.
        """
        check = rule.check_function_name
        params = rule.parameters

        if check == "policy_active":
            policy_name = params.get("policy_name", "")
            return self._policy_status.get(policy_name, False)

        if check == "audit_enabled":
            return self._policy_status.get("audit_logging", False)

        if check == "encryption_required":
            classification_str = params.get("classification", "confidential")
            try:
                classification = DataClassification(classification_str)
            except ValueError:
                return False
            handling = self._data_handling_rules.get(classification)
            if handling:
                return handling.encryption_required
            return False

        if check == "retention_configured":
            return self._policy_status.get("retention_policy", False)

        if check == "data_classified":
            # Check that specific resources have classifications
            resource_ids = params.get("resource_ids", [])
            if not resource_ids:
                return True
            return all(
                r in self._data_classifications for r in resource_ids
            )

        # Unknown check - default to passing for non-mandatory, fail for mandatory
        return not rule.is_mandatory
