"""Governance middleware for NEXUS API.

Provides request-level governance enforcement including:
- Policy evaluation
- Tenant isolation enforcement
- Rate limiting headers
- Audit logging for mutating requests
- Kill switch check
- Budget pre-check for expensive operations
- Request cost estimation

Implemented as a pure ASGI middleware (no BaseHTTPMiddleware) to avoid
streaming/deadlock issues with newer Starlette versions.
"""

import logging
import time
import uuid
from threading import Lock
from typing import Any

from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.types import ASGIApp, Message, Receive, Scope, Send

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


class GovernanceMiddleware:
    """Pure ASGI middleware for governance enforcement.

    Performs the following checks on every HTTP request:
    1. Kill switch check - rejects requests if company is killed
    2. Tenant isolation enforcement - validates company context
    3. Rate limiting - injects rate limit headers
    4. Policy evaluation - evaluates request against active policies
    5. Budget pre-check - validates budget for expensive operations
    6. Audit logging - logs all mutating requests
    7. Request cost estimation - attaches cost metadata
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """ASGI entry point."""
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request = Request(scope, receive)
        start_time = time.time()

        # Extract company ID from headers
        company_id_header = request.headers.get("x-company-id")
        company_id: uuid.UUID | None = None
        if company_id_header:
            try:
                company_id = uuid.UUID(company_id_header)
            except ValueError:
                pass

        # 1. Kill switch check
        if company_id and kill_switch_registry.is_killed(company_id):
            response = JSONResponse(
                status_code=503,
                content={
                    "detail": "Service unavailable: company operations are suspended",
                    "code": "KILL_SWITCH_ACTIVE",
                },
            )
            await response(scope, receive, send)
            return

        # 2. Tenant isolation - store company_id in scope state
        if company_id:
            scope.setdefault("state", {})["company_id"] = company_id

        # 3. Rate limiting check
        rate_limit_remaining = self._get_rate_limit_remaining(company_id)

        # 4. Policy evaluation
        policy_result = self._evaluate_policy(request, company_id)
        if not policy_result["allowed"]:
            response = JSONResponse(
                status_code=403,
                content={
                    "detail": policy_result.get("reason", "Policy denied request"),
                    "code": "POLICY_DENIED",
                },
            )
            await response(scope, receive, send)
            return

        # 5. Budget pre-check for mutating operations
        method = scope.get("method", "GET")
        if method in MUTATING_METHODS:
            estimated_cost = self._estimate_request_cost(request)
            if company_id and estimated_cost > 0:
                if not self._check_budget(company_id, estimated_cost):
                    response = JSONResponse(
                        status_code=429,
                        content={
                            "detail": "Budget limit exceeded for this operation",
                            "code": "BUDGET_EXCEEDED",
                        },
                    )
                    await response(scope, receive, send)
                    return

        # Wrap send to inject headers into the response
        response_started = False
        status_code = 200

        async def send_wrapper(message: Message) -> None:
            nonlocal response_started, status_code

            if message["type"] == "http.response.start":
                response_started = True
                status_code = message.get("status", 200)
                duration_ms = (time.time() - start_time) * 1000

                # Inject governance headers
                headers = list(message.get("headers", []))
                headers.append((b"x-ratelimit-limit", str(DEFAULT_RATE_LIMIT).encode()))
                headers.append((b"x-ratelimit-remaining", str(rate_limit_remaining).encode()))
                headers.append((b"x-ratelimit-window", str(DEFAULT_RATE_WINDOW_SECONDS).encode()))
                headers.append((b"x-request-cost-ms", f"{duration_ms:.1f}".encode()))
                message = {**message, "headers": headers}

                # 6. Audit logging for mutating requests
                if method in MUTATING_METHODS:
                    logger.info(
                        "audit: method=%s path=%s company=%s status=%s duration_ms=%.1f",
                        method,
                        scope.get("path", ""),
                        company_id,
                        status_code,
                        duration_ms,
                    )

            await send(message)

        await self.app(scope, receive, send_wrapper)

    def _get_rate_limit_remaining(self, company_id: uuid.UUID | None) -> int:
        """Get the remaining rate limit for this company/request."""
        # TODO: Wire to RateLimiter.check_rate_limit(company_id)
        return DEFAULT_RATE_LIMIT

    def _evaluate_policy(
        self, request: Request, company_id: uuid.UUID | None
    ) -> dict[str, Any]:
        """Evaluate request-level policies."""
        # TODO: Wire to PolicyEngine.evaluate(context)
        return {"allowed": True}

    def _estimate_request_cost(self, request: Request) -> int:
        """Estimate the cost of processing this request."""
        # TODO: Wire to cost model based on route patterns
        return 0

    def _check_budget(self, company_id: uuid.UUID, estimated_cost: int) -> bool:
        """Check if the company has sufficient budget."""
        # TODO: Wire to BudgetEnforcer.check(company_id, estimated_cost)
        return True
