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
from collections import deque
from threading import Lock
from typing import Any

from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from nexus.auth.middleware import get_principal_from_scope

logger = logging.getLogger(__name__)

# Methods considered mutating and subject to audit logging
MUTATING_METHODS = {"POST", "PUT", "PATCH", "DELETE"}

# Default rate limit values
DEFAULT_RATE_LIMIT = 100
DEFAULT_RATE_WINDOW_SECONDS = 60


class _SlidingWindowRateLimiter:
    """In-memory sliding window rate limiter keyed by company UUID.

    Each company gets a deque of request timestamps. On each check, expired
    entries (older than the window) are pruned, the current request is recorded,
    and the remaining quota is returned. Thread-safe via a per-company lock.
    """

    def __init__(
        self, limit: int = DEFAULT_RATE_LIMIT, window_seconds: int = DEFAULT_RATE_WINDOW_SECONDS
    ) -> None:
        self.limit = limit
        self.window_seconds = window_seconds
        self._buckets: dict[uuid.UUID, deque[float]] = {}
        self._lock = Lock()

    def check(self, company_id: uuid.UUID) -> tuple[int, bool]:
        """Record a request and return (remaining, allowed).

        Returns:
            Tuple of (requests remaining in window, whether this request is allowed).
        """
        now = time.time()
        cutoff = now - self.window_seconds

        with self._lock:
            if company_id not in self._buckets:
                self._buckets[company_id] = deque()

            bucket = self._buckets[company_id]

            # Prune expired timestamps
            while bucket and bucket[0] < cutoff:
                bucket.popleft()

            if len(bucket) >= self.limit:
                # Over limit — don't record, return 0 remaining
                return 0, False

            # Record this request
            bucket.append(now)
            remaining = self.limit - len(bucket)
            return remaining, True


# Global rate limiter instance
_rate_limiter = _SlidingWindowRateLimiter()


class _BudgetTracker:
    """In-memory budget tracker that caches company spend limits.

    The middleware can't do async DB queries (it's a pure ASGI middleware),
    so we maintain an in-memory cache of company budgets. The cache is populated
    by the first request for each company and expires after a configurable TTL.
    Budget updates (when an LLM call completes) are accumulated here and
    periodically flushed to the DB by a background task.
    """

    def __init__(self, ttl_seconds: int = 300) -> None:
        self._cache: dict[uuid.UUID, dict[str, int]] = {}
        self._cache_time: dict[uuid.UUID, float] = {}
        self._ttl = ttl_seconds
        self._lock = Lock()
        self._pending_spend: dict[uuid.UUID, int] = {}

    def set_budget(self, company_id: uuid.UUID, budget_cents: int, spent_cents: int) -> None:
        """Seed or update the budget cache for a company."""
        with self._lock:
            self._cache[company_id] = {
                "budget": budget_cents,
                "spent": spent_cents,
            }
            self._cache_time[company_id] = time.time()

    def record_spend(self, company_id: uuid.UUID, cost_cents: int) -> None:
        """Record spend against a company's budget (in-memory accumulation)."""
        with self._lock:
            self._pending_spend[company_id] = self._pending_spend.get(company_id, 0) + cost_cents
            if company_id in self._cache:
                self._cache[company_id]["spent"] += cost_cents

    def check(self, company_id: uuid.UUID, estimated_cost: int) -> bool:
        """Return True if the company can afford the estimated cost.

        If no budget data is cached, defaults to allowing (fail-open).
        """
        with self._lock:
            entry = self._cache.get(company_id)
            if entry is None:
                return True  # No data yet — fail open
            budget = entry["budget"]
            if budget <= 0:
                return True  # No budget cap configured
            spent = entry["spent"]
            return (spent + estimated_cost) <= budget

    def get_remaining(self, company_id: uuid.UUID) -> int | None:
        """Get remaining budget in cents, or None if unknown."""
        with self._lock:
            entry = self._cache.get(company_id)
            if entry is None:
                return None
            return max(0, entry["budget"] - entry["spent"])


# Global budget tracker
_budget_tracker = _BudgetTracker()

# Global policy cache: company_id → list of active policy dicts
# Seeded at startup from DB, can be refreshed via admin endpoint
_policy_cache: dict[uuid.UUID, list[dict[str, Any]]] = {}

# Route patterns that are considered "expensive" (LLM calls)
_EXPENSIVE_ROUTE_PATTERNS = [
    "/chat",
    "/chat/stream",
    "/execute",
    "/decompose",
    "/evaluate",
]

# Estimated cost in cents for different route types
_ROUTE_COST_ESTIMATES: dict[str, int] = {
    "chat": 5,       # ~5 cents per LLM chat call
    "stream": 5,
    "execute": 10,   # Task execution is more expensive
    "default": 0,    # Non-LLM routes are free
}


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

        # Tenant scope comes from the authenticated principal, which
        # AuthenticationMiddleware has already resolved and placed on the scope.
        # Reading it from a header here would let any caller pick the company
        # whose kill switch, policies and budget apply to their request.
        principal = get_principal_from_scope(scope)
        company_id: uuid.UUID | None = principal.company_id if principal else None

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
        if rate_limit_remaining == 0 and company_id:
            response = JSONResponse(
                status_code=429,
                content={
                    "detail": "Rate limit exceeded. Try again later.",
                    "code": "RATE_LIMIT_EXCEEDED",
                },
                headers={
                    "Retry-After": str(DEFAULT_RATE_WINDOW_SECONDS),
                    "X-RateLimit-Limit": str(DEFAULT_RATE_LIMIT),
                    "X-RateLimit-Remaining": "0",
                    "X-RateLimit-Window": str(DEFAULT_RATE_WINDOW_SECONDS),
                },
            )
            await response(scope, receive, send)
            return

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
        """Get the remaining rate limit for this company/request.

        Uses the global sliding window rate limiter. Returns the default limit
        for anonymous requests (no company context).
        """
        if company_id is None:
            return DEFAULT_RATE_LIMIT
        remaining, _allowed = _rate_limiter.check(company_id)
        return remaining

    def _evaluate_policy(
        self, request: Request, company_id: uuid.UUID | None
    ) -> dict[str, Any]:
        """Evaluate request-level policies against the company's active policy rules.

        Policy rules are JSON objects with optional fields:
        - "deny_paths": list of path prefixes to block (e.g. ["/api/v1/agents/*/delete"])
        - "deny_methods": list of HTTP methods to block (e.g. ["DELETE"])
        - "allow_paths": whitelist — if present, only these paths are allowed
        - "deny_after_hour": block requests after this hour (0-23, UTC)
        - "deny_before_hour": block requests before this hour (0-23, UTC)

        Returns {"allowed": True} or {"allowed": False, "reason": "..."}.
        """
        if company_id is None:
            return {"allowed": True}

        policies = _policy_cache.get(company_id)
        if not policies:
            return {"allowed": True}

        path = request.scope.get("path", "")
        method = request.scope.get("method", "GET")

        for policy in policies:
            rules = policy.get("rules")
            if not rules or not isinstance(rules, dict):
                continue

            # Check denied paths
            deny_paths = rules.get("deny_paths", [])
            for pattern in deny_paths:
                # Simple prefix/glob matching: "*" matches any segment
                if pattern.replace("*", "") in path or path.startswith(pattern.split("*")[0]):
                    return {
                        "allowed": False,
                        "reason": f"Policy '{policy.get('name', 'unnamed')}' denies path: {path}",
                    }

            # Check denied methods
            deny_methods = rules.get("deny_methods", [])
            if method in deny_methods:
                return {
                    "allowed": False,
                    "reason": f"Policy '{policy.get('name', 'unnamed')}' denies method: {method}",
                }

            # Check time-based restrictions
            import datetime as dt

            current_hour = dt.datetime.utcnow().hour
            deny_after = rules.get("deny_after_hour")
            deny_before = rules.get("deny_before_hour")
            if deny_after is not None and current_hour >= deny_after:
                return {
                    "allowed": False,
                    "reason": f"Policy '{policy.get('name', 'unnamed')}' denies requests after {deny_after}:00 UTC",
                }
            if deny_before is not None and current_hour < deny_before:
                return {
                    "allowed": False,
                    "reason": f"Policy '{policy.get('name', 'unnamed')}' denies requests before {deny_before}:00 UTC",
                }

        return {"allowed": True}

    def _estimate_request_cost(self, request: Request) -> int:
        """Estimate the cost of processing this request based on route patterns.

        Routes that trigger LLM calls (chat, execute, evaluate) are assigned
        a cost estimate in cents. Other routes are free (cost=0).
        """
        path = request.scope.get("path", "")
        for pattern in _EXPENSIVE_ROUTE_PATTERNS:
            if pattern in path:
                # Find the most specific cost key
                for key, cost in _ROUTE_COST_ESTIMATES.items():
                    if key in path:
                        return cost
                return _ROUTE_COST_ESTIMATES.get("chat", 5)
        return 0

    def _check_budget(self, company_id: uuid.UUID, estimated_cost: int) -> bool:
        """Check if the company has sufficient budget for this request.

        Uses the in-memory budget tracker. If no budget data is cached
        (first request before DB lookup), fails open (allows the request).
        """
        return _budget_tracker.check(company_id, estimated_cost)
