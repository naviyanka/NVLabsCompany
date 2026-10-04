"""Per-company governance readiness: a company's budget and policies must be loaded before
any of its requests is governed.

The API holds only the tenant-bound role, so it cannot list companies and seed every
company's state at startup. Instead the first authenticated request of a company loads that
company's budget and enabled policies, inside that company's own ``tenant_session``, into the
in-memory caches the governance middleware reads. This module is the one place that does it.

Fail closed. A company whose state is not loaded (the load failed, timed out, found no such
company, or is being retried after a failure) raises :class:`GovernanceUnavailable`, and the
middleware refuses the request with a 503. Nothing here synthesizes an allow-all policy or an
unlimited budget. A failed load only suppresses further attempts for a short back-off; every
request in that window is still refused.

The load is read-only, so it is idempotent by construction, a failure at any point leaves no
policy, budget or audit row behind, and the caches are written only after every read
succeeded. Concurrent first requests of one company share one load.
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid

logger = logging.getLogger(__name__)

BACKOFF_SECONDS = 30
LOAD_TIMEOUT_SECONDS = 3


class GovernanceUnavailable(Exception):  # noqa: N818 - a state, named for the 503 it maps to
    """The company's governance state is not loaded, so the request cannot be governed."""


_ready: set[uuid.UUID] = set()
_retry_at: dict[uuid.UUID, float] = {}
_locks: dict[uuid.UUID, asyncio.Lock] = {}


def reset() -> None:
    """Forget all readiness state (tests)."""
    _ready.clear()
    _retry_at.clear()
    _locks.clear()


def is_ready(company_id: uuid.UUID) -> bool:
    return company_id in _ready


async def _load(company_id: uuid.UUID) -> tuple[int, int, list[dict]]:
    from sqlalchemy import select

    from nexus.database import tenant_session
    from nexus.models.company import Company
    from nexus.models.policy import Policy

    async with tenant_session(company_id) as session:
        company = (
            await session.execute(select(Company).where(Company.id == company_id))
        ).scalar_one_or_none()
        if company is None:
            raise LookupError("company not found")
        policies = (
            (
                await session.execute(
                    select(Policy).where(
                        Policy.company_id == company_id,
                        Policy.enabled == True,  # noqa: E712
                    )
                )
            )
            .scalars()
            .all()
        )
        return (
            company.budget_monthly_cents,
            company.spent_monthly_cents,
            [{"name": p.name, "rules": p.rules, "priority": p.priority} for p in policies],
        )


async def ensure_company_governance_ready(company_id: uuid.UUID) -> None:
    """Load ``company_id``'s budget and policies once, or raise :class:`GovernanceUnavailable`.

    ``company_id`` must come from the authenticated principal, never from the request.
    """
    if company_id in _ready:
        return
    lock = _locks.setdefault(company_id, asyncio.Lock())
    async with lock:
        if company_id in _ready:  # another request finished the load while this one waited
            return
        if time.monotonic() < _retry_at.get(company_id, 0.0):
            raise GovernanceUnavailable("backoff")
        try:
            budget, spent, policies = await asyncio.wait_for(
                _load(company_id), LOAD_TIMEOUT_SECONDS
            )
            from nexus.api.middleware import _budget_tracker, _policy_cache

            # Spend recorded before the load (by this process) is not in the stored figure yet.
            pending = _budget_tracker._pending_spend.get(company_id, 0)
            _budget_tracker.set_budget(company_id, budget, spent + pending)
            _policy_cache[company_id] = policies
        except Exception as exc:  # noqa: BLE001 - any failure leaves the company unready
            _retry_at[company_id] = time.monotonic() + BACKOFF_SECONDS
            logger.warning("Company governance state unavailable (%s)", type(exc).__name__)
            raise GovernanceUnavailable(type(exc).__name__) from exc
        _ready.add(company_id)
        _retry_at.pop(company_id, None)
