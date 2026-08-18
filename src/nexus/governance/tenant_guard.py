"""Tenant Guard - Hard tenant isolation enforcement.

Provides middleware-style validation that ensures every operation is scoped
to the correct company_id. Cannot be bypassed or opted out of.
"""

import uuid
import contextvars
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


# Context variable for propagating tenant context through async calls
_current_tenant: contextvars.ContextVar[uuid.UUID | None] = contextvars.ContextVar(
    "current_tenant", default=None
)


class TenantViolation(Exception):
    """Raised when a tenant isolation violation is detected.

    Attributes:
        requesting_tenant: The tenant making the request.
        target_tenant: The tenant whose data was accessed.
        resource_type: Type of resource involved.
        resource_id: Identifier of the resource involved.
        detail: Human-readable description.
    """

    def __init__(
        self,
        requesting_tenant: uuid.UUID | None,
        target_tenant: uuid.UUID | None = None,
        resource_type: str = "",
        resource_id: str = "",
        detail: str = "",
    ) -> None:
        self.requesting_tenant = requesting_tenant
        self.target_tenant = target_tenant
        self.resource_type = resource_type
        self.resource_id = resource_id
        self.detail = detail or "Tenant isolation violation detected"
        super().__init__(self.detail)


@dataclass
class TenantViolationRecord:
    """Record of a detected tenant isolation violation.

    Attributes:
        id: Unique identifier for this violation record.
        requesting_tenant: The tenant that attempted the access.
        target_tenant: The tenant whose data was targeted.
        resource_type: Type of resource involved.
        resource_id: Identifier of the resource.
        violation_type: Category of violation (cross_access, missing_tenant, data_leak).
        timestamp: When the violation was detected.
        blocked: Whether the violation was blocked.
    """

    id: uuid.UUID = field(default_factory=uuid.uuid4)
    requesting_tenant: uuid.UUID | None = None
    target_tenant: uuid.UUID | None = None
    resource_type: str = ""
    resource_id: str = ""
    violation_type: str = ""
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    blocked: bool = True


@dataclass
class ResourceOwnership:
    """Tracks ownership of a resource.

    Attributes:
        resource_type: Type of resource.
        resource_id: Unique identifier of the resource.
        company_id: The tenant that owns this resource.
    """

    resource_type: str
    resource_id: str
    company_id: uuid.UUID


class TenantGuard:
    """Hard tenant isolation enforcement.

    This guard validates company_id on every request, injects query filters,
    detects cross-tenant access attempts, and blocks them. It cannot be
    bypassed or opted out of - there is no disable mechanism.

    All methods that validate tenant access will raise TenantViolation
    on any isolation breach.
    """

    def __init__(self) -> None:
        """Initialize the tenant guard."""
        self._violations: list[TenantViolationRecord] = []
        self._resource_registry: dict[tuple[str, str], uuid.UUID] = {}

    def validate_company_id(self, company_id: Any) -> uuid.UUID:
        """Validate that a company_id is present and is a valid UUID.

        This is the first line of defense - every request must have a
        valid company_id. There is no way to skip this validation.

        Args:
            company_id: The company identifier to validate.

        Returns:
            The validated UUID.

        Raises:
            TenantViolation: If company_id is None, empty, or invalid.
        """
        if company_id is None:
            violation = TenantViolationRecord(
                requesting_tenant=None,
                violation_type="missing_tenant",
            )
            self._violations.append(violation)
            raise TenantViolation(
                requesting_tenant=None,
                detail="company_id is required but was not provided",
            )

        if isinstance(company_id, uuid.UUID):
            return company_id

        try:
            return uuid.UUID(str(company_id))
        except (ValueError, AttributeError):
            violation = TenantViolationRecord(
                requesting_tenant=None,
                violation_type="invalid_tenant",
            )
            self._violations.append(violation)
            raise TenantViolation(
                requesting_tenant=None,
                detail=f"company_id is not a valid UUID: {company_id}",
            )

    def inject_query_filter(self, company_id: uuid.UUID) -> dict[str, uuid.UUID]:
        """Return a query filter condition that scopes queries to a tenant.

        This must be applied to ALL database queries to ensure tenant
        isolation at the data layer.

        Args:
            company_id: The tenant to scope queries for.

        Returns:
            A dict representing the filter condition.
        """
        validated = self.validate_company_id(company_id)
        return {"company_id": validated}

    def register_resource(
        self, resource_type: str, resource_id: str, company_id: uuid.UUID
    ) -> None:
        """Register a resource's ownership with the guard.

        Args:
            resource_type: Type of resource (task, agent, etc.).
            resource_id: Unique identifier of the resource.
            company_id: The tenant that owns the resource.
        """
        key = (resource_type, resource_id)
        self._resource_registry[key] = company_id

    def check_resource_ownership(
        self,
        company_id: uuid.UUID,
        resource_type: str,
        resource_id: str,
    ) -> bool:
        """Verify that a resource belongs to the requesting tenant.

        Args:
            company_id: The tenant claiming ownership.
            resource_type: Type of resource to check.
            resource_id: Identifier of the resource to check.

        Returns:
            True if the resource belongs to the tenant.

        Raises:
            TenantViolation: If the resource belongs to a different tenant.
        """
        validated = self.validate_company_id(company_id)
        key = (resource_type, resource_id)

        owner = self._resource_registry.get(key)
        if owner is None:
            # Resource not registered - deny access (secure-by-default behavior).
            # Unknown resources must be explicitly registered before access is
            # granted. This prevents untracked resources from being accessible
            # to all tenants.
            return False

        if owner != validated:
            violation = TenantViolationRecord(
                requesting_tenant=validated,
                target_tenant=owner,
                resource_type=resource_type,
                resource_id=resource_id,
                violation_type="cross_access",
                blocked=True,
            )
            self._violations.append(violation)
            raise TenantViolation(
                requesting_tenant=validated,
                target_tenant=owner,
                resource_type=resource_type,
                resource_id=resource_id,
                detail=(
                    f"Resource {resource_type}/{resource_id} belongs to tenant "
                    f"{owner}, not {validated}"
                ),
            )

        return True

    def detect_cross_tenant_access(
        self,
        company_id: uuid.UUID,
        response_data: dict[str, Any] | list[Any],
    ) -> bool:
        """Check if response data contains information from other tenants.

        Scans response data for company_id fields that do not match the
        requesting tenant, indicating potential data leakage.

        Args:
            company_id: The tenant making the request.
            response_data: The response data to inspect.

        Returns:
            True if the response is safe (no cross-tenant data).

        Raises:
            TenantViolation: If cross-tenant data is detected in response.
        """
        validated = self.validate_company_id(company_id)
        foreign_tenants = self._scan_for_foreign_tenants(validated, response_data)

        if foreign_tenants:
            violation = TenantViolationRecord(
                requesting_tenant=validated,
                target_tenant=foreign_tenants[0],
                violation_type="data_leak",
                blocked=True,
            )
            self._violations.append(violation)
            raise TenantViolation(
                requesting_tenant=validated,
                target_tenant=foreign_tenants[0],
                detail=(
                    f"Response contains data from {len(foreign_tenants)} "
                    f"foreign tenant(s)"
                ),
            )

        return True

    def _scan_for_foreign_tenants(
        self, company_id: uuid.UUID, data: Any, max_depth: int = 10
    ) -> list[uuid.UUID]:
        """Recursively scan data for foreign tenant IDs.

        Args:
            company_id: The expected tenant.
            data: Data structure to scan.
            max_depth: Maximum recursion depth to prevent RecursionError
                on deeply nested or circular data structures. Returns empty
                list when depth reaches 0.

        Returns:
            List of foreign tenant UUIDs found.
        """
        if max_depth <= 0:
            return []

        foreign: list[uuid.UUID] = []

        if isinstance(data, dict):
            cid = data.get("company_id")
            if cid is not None:
                try:
                    found_id = uuid.UUID(str(cid)) if not isinstance(cid, uuid.UUID) else cid
                    if found_id != company_id:
                        foreign.append(found_id)
                except (ValueError, AttributeError):
                    pass
            for value in data.values():
                foreign.extend(self._scan_for_foreign_tenants(company_id, value, max_depth - 1))
        elif isinstance(data, list):
            for item in data:
                foreign.extend(self._scan_for_foreign_tenants(company_id, item, max_depth - 1))

        return foreign

    def propagate_tenant_context(self, company_id: uuid.UUID) -> contextvars.Token:
        """Set the current tenant context for async propagation.

        This sets a context variable that propagates through async calls,
        ensuring tenant isolation even in concurrent scenarios.

        Args:
            company_id: The tenant to propagate.

        Returns:
            A token that can be used to reset the context.
        """
        validated = self.validate_company_id(company_id)
        return _current_tenant.set(validated)

    def get_current_tenant(self) -> uuid.UUID:
        """Get the current tenant from async context.

        Returns:
            The current tenant UUID.

        Raises:
            TenantViolation: If no tenant context is set.
        """
        tenant = _current_tenant.get()
        if tenant is None:
            raise TenantViolation(
                requesting_tenant=None,
                detail="No tenant context set - cannot proceed without tenant isolation",
            )
        return tenant

    def get_violations(
        self, company_id: uuid.UUID | None = None
    ) -> list[TenantViolationRecord]:
        """Get recorded violations, optionally filtered by tenant.

        Args:
            company_id: If provided, filter to violations involving this tenant.

        Returns:
            List of violation records.
        """
        if company_id is None:
            return list(self._violations)
        return [
            v
            for v in self._violations
            if v.requesting_tenant == company_id or v.target_tenant == company_id
        ]

    def get_violation_count(self) -> int:
        """Get the total number of recorded violations.

        Returns:
            Count of violations.
        """
        return len(self._violations)
