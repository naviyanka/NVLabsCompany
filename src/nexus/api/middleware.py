"""Governance middleware for NEXUS API.

Provides request-level governance enforcement including:
- Policy evaluation
- Tenant isolation enforcement
- Rate limiting headers
- Audit logging for mutating requests
- Kill switch check
- Budget pre-check for expensive operations
- Request cost estimation

TODO: This middleware currently provides request-level structure but enforcement
is pending integration with actual domain managers (PolicyEngine, RateLimiter,
TenantGuard, PersistentAuditLogger, etc.) in a future phase. Each stub method
documents what it needs to connect to.
"""

import logging
import time
import uuid
from threading import Lock

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

logger = logging.getLogger(__name__)

# Methods considered mutating and subject to audit logging
MUTATING_METHODS = {"POST", "PUT", "PATCH", "DELETE"}

# Default rate limit values
DEFAULT_RATE_LIMIT = 100
DEFAULT_RATE_WINDOW_SECONDS = 60


class _KillSwitchRegistry:
    """Singleton registry tracking which companies have the kill switch active.

    This is the authoritative in-memory state for the kill switch. Other
    parts of the system (admin routes, incident manager) should call
    activate/deactivate on the global instance to control company access.
    """

    _instance: "_KillSwitchRegistry | None" = None
    _lock: Lock = Lock()

    def __new__(cls) -> "_KillSwitchRegistry":
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance._killed_companies: set[uuid.UUID] = set()
            return cls._instance

    def activate(self, company_id: uuid.UUID) -> None:
        """Activate the kill switch for a company."""
        self._killed_companies.add(company_id)

    def deactivate(self, company_id: uuid.UUID) -> None:
        """Deactivate the kill switch for a company."""
        self._killed_companies.discard(company_id)

    def is_killed(self, company_id: uuid.UUID) -> bool:
        """Check if a company's kill switch is active."""
        return company_id in self._killed_companies

    def reset(self) -> None:
        """Reset all kill switches (for testing)."""
        self._killed_companies.clear()


# Global kill switch instance - use this to activate/deactivate companies
kill_switch_registry = _KillSwitchRegistry()


class GovernanceMiddleware(BaseHTTPMiddleware):
    """FastAPI middleware for governance enforcement.

    Performs the following checks on every request:
    1. Kill switch check - rejects requests if company is killed
    2. Tenant isolation enforcement - validates company context
    3. Rate limiting - injects rate limit headers
    4. Policy evaluation - evaluates request against active policies
    5. Budget pre-check - validates budget for expensive operations
    6. Audit logging - logs all mutating requests
    7. Request cost estimation - attaches cost metadata
    """

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        """Process the request through governance checks.

        Args:
            request: The incoming HTTP request.
            call_next: The next middleware or route handler.

        Returns:
            The HTTP response, possibly short-circuited by governance checks.
        """
        start_time = time.time()

        # Extract company ID from headers (if present)
        company_id_header = request.headers.get("x-company-id")
        company_id: uuid.UUID | None = None
        if company_id_header:
            try:
                company_id = uuid.UUID(company_id_header)
            except ValueError:
                pass

        # 1. Kill switch check - reject if company is killed
        if company_id and self._is_company_killed(company_id):
            return JSONResponse(
                status_code=503,
                content={
                    "detail": "Service unavailable: company operations are suspended",
                    "code": "KILL_SWITCH_ACTIVE",
                },
            )

        # 2. Tenant isolation enforcement
        if company_id:
            request.state.company_id = company_id

        # 3. Rate limiting headers (computed before processing)
        rate_limit_remaining = self._get_rate_limit_remaining(company_id)

        # 4. Policy evaluation
        policy_result = self._evaluate_policy(request, company_id)
        if not policy_result["allowed"]:
            return JSONResponse(
                status_code=403,
                content={
                    "detail": policy_result.get("reason", "Policy denied request"),
                    "code": "POLICY_DENIED",
                },
            )

        # 5. Budget pre-check for expensive operations
        if request.method in MUTATING_METHODS:
            estimated_cost = self._estimate_request_cost(request)
            if company_id and estimated_cost > 0:
                budget_ok = self._check_budget(company_id, estimated_cost)
                if not budget_ok:
                    return JSONResponse(
                        status_code=429,
                        content={
                            "detail": "Budget limit exceeded for this operation",
                            "code": "BUDGET_EXCEEDED",
                        },
                    )

        # Process the request
        response = await call_next(request)

        # Post-processing
        duration_ms = (time.time() - start_time) * 1000

        # Inject rate limiting headers
        response.headers["X-RateLimit-Limit"] = str(DEFAULT_RATE_LIMIT)
        response.headers["X-RateLimit-Remaining"] = str(rate_limit_remaining)
        response.headers["X-RateLimit-Window"] = str(DEFAULT_RATE_WINDOW_SECONDS)

        # Inject request cost header
        response.headers["X-Request-Cost-Ms"] = f"{duration_ms:.1f}"

        # 6. Audit logging for mutating requests
        if request.method in MUTATING_METHODS:
            await self._audit_log_request(request, response, company_id, duration_ms)

        return response

    def _is_company_killed(self, company_id: uuid.UUID) -> bool:
        """Check if the company kill switch is active.

        This check is wired to the _KillSwitchRegistry singleton. Other
        parts of the system (admin routes, incident auto-response) can call
        kill_switch_registry.activate(company_id) to suspend a company.

        Args:
            company_id: The company to check.

        Returns:
            True if the company is killed/suspended.
        """
        return kill_switch_registry.is_killed(company_id)

    def _get_rate_limit_remaining(self, company_id: uuid.UUID | None) -> int:
        """Get the remaining rate limit for this company/request.

        TODO: Integrate with governance.rate_limiter.RateLimiter to check
        actual token bucket state per company. Currently returns the default
        constant. Requires a shared RateLimiter instance injected at middleware
        construction or resolved from app state.

        Args:
            company_id: The company to check rate limits for.

        Returns:
            Number of remaining requests in the current window.
        """
        # TODO: Wire to RateLimiter.check_rate_limit(company_id) for real enforcement
        return DEFAULT_RATE_LIMIT

    def _evaluate_policy(
        self, request: Request, company_id: uuid.UUID | None
    ) -> dict:
        """Evaluate request-level policies.

        TODO: Integrate with governance.policies.engine.PolicyEngine to evaluate
        active policies for this request. Requires building a PolicyContext from
        the request (actor, action, resource) and calling engine.evaluate().
        Currently returns permissive default.

        Args:
            request: The incoming request.
            company_id: The company context.

        Returns:
            Dict with 'allowed' boolean and optional 'reason'.
        """
        # TODO: Wire to PolicyEngine.evaluate(context) for real policy enforcement
        return {"allowed": True}

    def _estimate_request_cost(self, request: Request) -> int:
        """Estimate the cost of processing this request.

        TODO: Implement cost estimation based on route and payload size.
        Different endpoints have different cost profiles (e.g., LLM calls
        are expensive, CRUD reads are cheap). Currently returns 0 (free).

        Args:
            request: The incoming request.

        Returns:
            Estimated cost in abstract cost units (cents).
        """
        # TODO: Wire to a cost model based on route patterns and payload
        return 0

    def _check_budget(self, company_id: uuid.UUID, estimated_cost: int) -> bool:
        """Check if the company has sufficient budget for this operation.

        TODO: Integrate with a BudgetEnforcer or company billing state to
        verify the company has not exceeded their spending limit. Currently
        returns True (always allows).

        Args:
            company_id: The company to check.
            estimated_cost: The estimated cost of the operation.

        Returns:
            True if the budget allows the operation.
        """
        # TODO: Wire to BudgetEnforcer.check(company_id, estimated_cost)
        return True

    async def _audit_log_request(
        self,
        request: Request,
        response: Response,
        company_id: uuid.UUID | None,
        duration_ms: float,
    ) -> None:
        """Log mutating requests for audit purposes.

        TODO: Integrate with governance.audit_persistent.PersistentAuditLogger
        to write entries into the hash-chained audit log instead of just
        logging to stdout. Requires a shared logger instance.

        Args:
            request: The request that was processed.
            response: The response being returned.
            company_id: The company context.
            duration_ms: How long the request took to process.
        """
        # TODO: Wire to PersistentAuditLogger.log_entry() for tamper-evident audit
        logger.info(
            "audit: method=%s path=%s company=%s status=%s duration_ms=%.1f",
            request.method,
            request.url.path,
            company_id,
            response.status_code,
            duration_ms,
        )
