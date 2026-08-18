"""Tests for TenantGuard - Hard tenant isolation enforcement.

Tests validation enforcement, cross-tenant blocking, resource ownership
checks, and verifies that the guard cannot be bypassed.
"""

import uuid

import pytest

from nexus.governance.tenant_guard import (
    TenantGuard,
    TenantViolation,
    TenantViolationRecord,
)


class TestCompanyIdValidation:
    """Tests that company_id validation cannot be bypassed."""

    def test_valid_uuid_passes(self):
        """A valid UUID company_id passes validation."""
        guard = TenantGuard()
        company_id = uuid.uuid4()
        result = guard.validate_company_id(company_id)
        assert result == company_id

    def test_valid_uuid_string_passes(self):
        """A valid UUID string passes validation."""
        guard = TenantGuard()
        company_id = uuid.uuid4()
        result = guard.validate_company_id(str(company_id))
        assert result == company_id

    def test_none_raises_violation(self):
        """None company_id raises TenantViolation."""
        guard = TenantGuard()
        with pytest.raises(TenantViolation) as exc_info:
            guard.validate_company_id(None)
        assert "required" in exc_info.value.detail

    def test_empty_string_raises_violation(self):
        """Empty string raises TenantViolation."""
        guard = TenantGuard()
        with pytest.raises(TenantViolation):
            guard.validate_company_id("")

    def test_invalid_uuid_raises_violation(self):
        """Invalid UUID format raises TenantViolation."""
        guard = TenantGuard()
        with pytest.raises(TenantViolation) as exc_info:
            guard.validate_company_id("not-a-uuid")
        assert "not a valid UUID" in exc_info.value.detail

    def test_no_opt_out_mechanism(self):
        """There is no way to disable or bypass validation."""
        guard = TenantGuard()
        # No disable method exists
        assert not hasattr(guard, "disable")
        assert not hasattr(guard, "bypass")
        assert not hasattr(guard, "skip_validation")
        # Validation always raises on None
        with pytest.raises(TenantViolation):
            guard.validate_company_id(None)


class TestResourceOwnership:
    """Tests for resource ownership validation."""

    def test_resource_belongs_to_tenant(self):
        """Resource check passes when resource belongs to requesting tenant."""
        guard = TenantGuard()
        company_id = uuid.uuid4()
        guard.register_resource("task", "task-123", company_id)

        result = guard.check_resource_ownership(company_id, "task", "task-123")
        assert result is True

    def test_cross_tenant_resource_access_blocked(self):
        """Access to another tenant's resource raises TenantViolation."""
        guard = TenantGuard()
        tenant_a = uuid.uuid4()
        tenant_b = uuid.uuid4()
        guard.register_resource("task", "task-456", tenant_a)

        with pytest.raises(TenantViolation) as exc_info:
            guard.check_resource_ownership(tenant_b, "task", "task-456")

        assert exc_info.value.requesting_tenant == tenant_b
        assert exc_info.value.target_tenant == tenant_a
        assert "belongs to tenant" in exc_info.value.detail

    def test_unregistered_resource_allowed(self):
        """Access to an unregistered resource is allowed (may be new)."""
        guard = TenantGuard()
        company_id = uuid.uuid4()
        result = guard.check_resource_ownership(company_id, "task", "new-task")
        assert result is True

    def test_ownership_with_invalid_company_id_raises(self):
        """Resource ownership check with invalid company_id raises."""
        guard = TenantGuard()
        with pytest.raises(TenantViolation):
            guard.check_resource_ownership(None, "task", "task-123")


class TestCrossTenantDetection:
    """Tests for cross-tenant data leak detection."""

    def test_clean_response_passes(self):
        """Response with only the requesting tenant's data passes."""
        guard = TenantGuard()
        company_id = uuid.uuid4()
        response = {"company_id": str(company_id), "data": "safe"}

        result = guard.detect_cross_tenant_access(company_id, response)
        assert result is True

    def test_foreign_tenant_data_blocked(self):
        """Response containing another tenant's data is blocked."""
        guard = TenantGuard()
        tenant_a = uuid.uuid4()
        tenant_b = uuid.uuid4()
        response = {
            "results": [
                {"company_id": str(tenant_a), "name": "mine"},
                {"company_id": str(tenant_b), "name": "foreign"},
            ]
        }

        with pytest.raises(TenantViolation) as exc_info:
            guard.detect_cross_tenant_access(tenant_a, response)
        assert "foreign tenant" in exc_info.value.detail

    def test_response_without_company_id_passes(self):
        """Response without company_id fields passes (no leakage)."""
        guard = TenantGuard()
        company_id = uuid.uuid4()
        response = {"name": "hello", "count": 42}

        result = guard.detect_cross_tenant_access(company_id, response)
        assert result is True

    def test_nested_foreign_data_detected(self):
        """Deeply nested foreign tenant data is detected."""
        guard = TenantGuard()
        tenant_a = uuid.uuid4()
        tenant_b = uuid.uuid4()
        response = {
            "level1": {
                "level2": {
                    "items": [{"company_id": str(tenant_b)}]
                }
            }
        }

        with pytest.raises(TenantViolation):
            guard.detect_cross_tenant_access(tenant_a, response)


class TestQueryFilterInjection:
    """Tests for query filter injection."""

    def test_filter_contains_company_id(self):
        """Injected filter includes company_id."""
        guard = TenantGuard()
        company_id = uuid.uuid4()
        filter_condition = guard.inject_query_filter(company_id)

        assert "company_id" in filter_condition
        assert filter_condition["company_id"] == company_id

    def test_filter_with_invalid_id_raises(self):
        """Filter injection with invalid company_id raises."""
        guard = TenantGuard()
        with pytest.raises(TenantViolation):
            guard.inject_query_filter(None)


class TestTenantContextPropagation:
    """Tests for tenant context propagation through async calls."""

    def test_set_and_get_context(self):
        """Tenant context can be set and retrieved."""
        guard = TenantGuard()
        company_id = uuid.uuid4()

        token = guard.propagate_tenant_context(company_id)
        result = guard.get_current_tenant()
        assert result == company_id

    def test_no_context_raises_violation(self):
        """Getting tenant without context set raises TenantViolation."""
        guard = TenantGuard()
        # Reset context to None by using a new guard without setting context
        from nexus.governance.tenant_guard import _current_tenant
        token = _current_tenant.set(None)
        try:
            with pytest.raises(TenantViolation) as exc_info:
                guard.get_current_tenant()
            assert "No tenant context" in exc_info.value.detail
        finally:
            _current_tenant.reset(token)


class TestViolationTracking:
    """Tests that violations are properly recorded."""

    def test_violations_are_recorded(self):
        """Failed validations record violation records."""
        guard = TenantGuard()

        try:
            guard.validate_company_id(None)
        except TenantViolation:
            pass

        assert guard.get_violation_count() == 1
        violations = guard.get_violations()
        assert len(violations) == 1
        assert violations[0].violation_type == "missing_tenant"
        assert violations[0].blocked is True

    def test_cross_tenant_violation_recorded(self):
        """Cross-tenant access attempts are recorded."""
        guard = TenantGuard()
        tenant_a = uuid.uuid4()
        tenant_b = uuid.uuid4()
        guard.register_resource("task", "t1", tenant_a)

        try:
            guard.check_resource_ownership(tenant_b, "task", "t1")
        except TenantViolation:
            pass

        violations = guard.get_violations(tenant_b)
        assert len(violations) == 1
        assert violations[0].violation_type == "cross_access"
