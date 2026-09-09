"""Budget Service - budget enforcement, cost tracking, and usage reporting."""

import uuid
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from typing import Any

from sqlalchemy import and_, case, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from nexus.models.budget import BudgetPolicy, CostEvent

# How long a hold counts against the budget before it stops being trusted. Long
# enough for the slowest streaming provider call, short enough that a killed
# worker's hold clears without an operator.
RESERVATION_TTL_SECONDS = 900


class BudgetExceeded(Exception):
    """Raised when an atomic budget reservation or spend exceeds available budget."""

    def __init__(self, message: str = "Budget exceeded", code: str = "BUDGET_EXCEEDED", http_status: int = 429) -> None:
        super().__init__(message)
        self.message = message
        self.code = code
        self.http_status = http_status


@dataclass
class BudgetCheckResult:
    """Result of a budget check operation."""

    allowed: bool
    remaining_cents: int
    used_cents: int
    limit_cents: int
    warn_threshold_reached: bool
    policy_id: uuid.UUID | None = None
    message: str = ""


@dataclass
class UsageSummary:
    """Summary of budget usage for a scope."""

    scope_type: str
    scope_id: uuid.UUID
    total_cost_cents: int
    total_input_tokens: int
    total_output_tokens: int
    event_count: int
    window_start: datetime
    window_end: datetime


def _calculate_window_start(window_kind: str, now: datetime) -> datetime:
    """Calculate the start timestamp for a given budget window."""
    if window_kind == "daily":
        return now.replace(hour=0, minute=0, second=0, microsecond=0)
    elif window_kind == "weekly":
        days_since_monday = now.weekday()
        return (now - timedelta(days=days_since_monday)).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
    else:  # monthly
        return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


class BudgetService:
    """Service layer for budget enforcement, cost recording, and usage reporting.

    Provides budget checking before operations, cost event recording after
    operations, and usage summaries for reporting.
    """

    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def _roll_window_if_needed(self, policy: BudgetPolicy, now: datetime) -> None:
        """Roll spent_cents to 0 if the budget policy crossed its window boundary.

        Live reservations (reserved_cents) do NOT roll across window boundaries.
        """
        window_start = _calculate_window_start(policy.window_kind, now)
        if policy.window_started_at is None:
            policy.window_started_at = window_start
            await self._db.execute(
                update(BudgetPolicy)
                .where(BudgetPolicy.id == policy.id)
                .values(window_started_at=window_start)
            )
            return

        if policy.window_started_at < window_start:
            policy.spent_cents = 0
            policy.window_started_at = window_start
            await self._db.execute(
                update(BudgetPolicy)
                .where(
                    BudgetPolicy.id == policy.id,
                    BudgetPolicy.window_started_at < window_start,
                )
                .values(
                    spent_cents=0,
                    window_started_at=window_start,
                    updated_at=now,
                )
            )

    async def check_budget(
        self,
        scope_type: str,
        scope_id: uuid.UUID,
        amount: int,
        company_id: uuid.UUID | None = None,
    ) -> BudgetCheckResult:
        """Check if a budget allows spending the given amount.

        Looks up active budget policies for the scope and evaluates
        whether the requested amount is within limits.

        Args:
            scope_type: Type of scope (company, department, agent, project).
            scope_id: ID of the scoped entity.
            amount: Amount in cents to check.
            company_id: Optional company ID for filtering.

        Returns:
            BudgetCheckResult with allowed/denied status and details.
        """
        # Find active policies for this scope
        stmt = select(BudgetPolicy).where(
            BudgetPolicy.scope_type == scope_type,
            BudgetPolicy.scope_id == scope_id,
            BudgetPolicy.is_active == True,  # noqa: E712
        )
        if company_id:
            stmt = stmt.where(BudgetPolicy.company_id == company_id)

        # Proactively reap any expired reservations so stale holds don't block spend
        await self.reap_expired_reservations()

        result = await self._db.execute(stmt)
        policies = result.scalars().all()

        if not policies:
            # No policy means unlimited
            return BudgetCheckResult(
                allowed=True,
                remaining_cents=0,
                used_cents=0,
                limit_cents=0,
                warn_threshold_reached=False,
                message="No budget policy configured",
            )

        now = datetime.now(timezone.utc).replace(tzinfo=None)

        # Check against the most restrictive active policy
        for policy in policies:
            if policy.metric != "cost_cents":
                continue

            await self._roll_window_if_needed(policy, now)

            # Authoritative source of truth: policy counters (WP-12)
            used = policy.spent_cents + policy.reserved_cents
            remaining = policy.amount - used
            warn_threshold = policy.amount * policy.warn_percent // 100

            if policy.hard_stop_enabled and (used + amount) > policy.amount:
                return BudgetCheckResult(
                    allowed=False,
                    remaining_cents=max(0, remaining),
                    used_cents=used,
                    limit_cents=policy.amount,
                    warn_threshold_reached=used >= warn_threshold,
                    policy_id=policy.id,
                    message=f"Budget exceeded: used={used}, limit={policy.amount}",
                )

            return BudgetCheckResult(
                allowed=True,
                remaining_cents=max(0, remaining - amount),
                used_cents=used,
                limit_cents=policy.amount,
                warn_threshold_reached=(used + amount) >= warn_threshold,
                policy_id=policy.id,
            )

        # Fallback: no cost_cents policy found
        return BudgetCheckResult(
            allowed=True,
            remaining_cents=0,
            used_cents=0,
            limit_cents=0,
            warn_threshold_reached=False,
            message="No cost_cents policy found",
        )

    async def record_cost(
        self,
        company_id: uuid.UUID,
        agent_id: uuid.UUID | None = None,
        task_id: uuid.UUID | None = None,
        project_id: uuid.UUID | None = None,
        provider: str = "unknown",
        model: str | None = None,
        input_tokens: int = 0,
        output_tokens: int = 0,
        cost_cents: int = 0,
        billing_type: str = "llm_inference",
        policy_id: uuid.UUID | None = None,
    ) -> CostEvent:
        """Record a cost event.

        Args:
            company_id: The company being charged.
            agent_id: Optional agent that incurred the cost.
            task_id: Optional task this cost is associated with.
            project_id: Optional project this cost belongs to.
            provider: The service provider (e.g., openai, anthropic).
            model: Optional model identifier.
            input_tokens: Number of input tokens.
            output_tokens: Number of output tokens.
            cost_cents: Total cost in cents.
            billing_type: Type of charge.
            policy_id: Optional specific policy to charge. If None, resolves active company policy.

        Returns:
            The recorded CostEvent instance.
        """
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        target_policy = None

        if policy_id:
            p_res = await self._db.execute(select(BudgetPolicy).where(BudgetPolicy.id == policy_id))
            target_policy = p_res.scalars().first()
        else:
            p_res = await self._db.execute(
                select(BudgetPolicy).where(
                    BudgetPolicy.company_id == company_id,
                    BudgetPolicy.scope_type == "company",
                    BudgetPolicy.is_active == True,  # noqa: E712
                    BudgetPolicy.metric == "cost_cents",
                )
            )
            target_policy = p_res.scalars().first()

        if target_policy and cost_cents > 0:
            await self._roll_window_if_needed(target_policy, now)
            used = target_policy.spent_cents + target_policy.reserved_cents
            if target_policy.hard_stop_enabled and (used + cost_cents) > target_policy.amount:
                raise BudgetExceeded(
                    f"Budget exceeded: cannot record cost of {cost_cents} cents. used={used}, limit={target_policy.amount}"
                )

        event = CostEvent(
            company_id=company_id,
            agent_id=agent_id,
            task_id=task_id,
            project_id=project_id,
            policy_id=target_policy.id if target_policy else None,
            provider=provider,
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_cents=cost_cents,
            billing_type=billing_type,
            occurred_at=now,
        )
        self._db.add(event)

        if target_policy and cost_cents > 0:
            # Atomically update spent_cents on the single targeted policy
            await self._db.execute(
                update(BudgetPolicy)
                .where(BudgetPolicy.id == target_policy.id)
                .values(
                    spent_cents=BudgetPolicy.spent_cents + cost_cents,
                    updated_at=now,
                )
            )

        await self._db.flush()
        return event

    async def reserve(
        self,
        company_id: uuid.UUID,
        estimate_cents: int,
        scope_type: str = "company",
        scope_id: uuid.UUID | None = None,
        agent_id: uuid.UUID | None = None,
        provider: str = "unknown",
        model: str | None = None,
        ttl_seconds: int = RESERVATION_TTL_SECONDS,
    ) -> tuple[bool, CostEvent | None, BudgetCheckResult]:
        """Phase one of a two-phase spend: check and hold atomically in DB.

        Atomically increments reserved_cents on matching active BudgetPolicy
        guarded by spent_cents + reserved_cents + estimate_cents <= amount.
        If the policy limit is exceeded, raises BudgetExceeded (or returns denied).
        """
        target_id = scope_id or company_id
        check = await self.check_budget(
            scope_type=scope_type,
            scope_id=target_id,
            amount=estimate_cents,
            company_id=company_id,
        )
        if not check.allowed:
            return False, None, check

        amt = max(0, estimate_cents)
        matched_policy_id = check.policy_id

        if matched_policy_id and amt > 0:
            # Atomic conditional reservation on budget_policies
            stmt = (
                update(BudgetPolicy)
                .where(
                    BudgetPolicy.id == matched_policy_id,
                    BudgetPolicy.is_active == True,  # noqa: E712
                    (BudgetPolicy.spent_cents + BudgetPolicy.reserved_cents + amt) <= BudgetPolicy.amount,
                )
                .values(
                    reserved_cents=BudgetPolicy.reserved_cents + amt,
                    updated_at=datetime.now(timezone.utc).replace(tzinfo=None),
                )
                .returning(BudgetPolicy.id, BudgetPolicy.reserved_cents, BudgetPolicy.amount)
            )
            res = await self._db.execute(stmt)
            row = res.first()
            if not row:
                check.allowed = False
                check.message = "Budget exceeded (atomic reservation check failed)"
                return False, None, check

        now = datetime.now(timezone.utc).replace(tzinfo=None)
        reservation = CostEvent(
            company_id=company_id,
            agent_id=agent_id,
            policy_id=matched_policy_id,
            provider=provider,
            model=model,
            cost_cents=amt,
            status="reserved",
            expires_at=now + timedelta(seconds=ttl_seconds),
            occurred_at=now,
        )
        self._db.add(reservation)
        await self._db.commit()
        return True, reservation, check

    async def commit_reservation(
        self,
        reservation_id: uuid.UUID,
        cost_cents: int,
        input_tokens: int = 0,
        output_tokens: int = 0,
        model: str | None = None,
    ) -> bool:
        """Phase two: reconcile a hold to the exact spend.

        Atomically decrements reserved_cents and increments spent_cents on
        the associated policy (if any).
        """
        # Fetch existing reservation first
        res = await self._db.execute(
            select(CostEvent).where(CostEvent.id == reservation_id, CostEvent.status == "reserved")
        )
        event = res.scalars().first()
        if not event:
            return False

        old_hold = event.cost_cents
        actual_spend = max(0, cost_cents)
        policy_id = event.policy_id

        values: dict[str, Any] = {
            "cost_cents": actual_spend,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "status": "committed",
            "expires_at": None,
        }
        if model:
            values["model"] = model

        upd_res = await self._db.execute(
            update(CostEvent)
            .where(CostEvent.id == reservation_id, CostEvent.status == "reserved")
            .values(**values)
        )
        if upd_res.rowcount == 0:
            return False

        if policy_id:
            await self._db.execute(
                update(BudgetPolicy)
                .where(BudgetPolicy.id == policy_id)
                .values(
                    reserved_cents=case(
                        (BudgetPolicy.reserved_cents >= old_hold, BudgetPolicy.reserved_cents - old_hold),
                        else_=0,
                    ),
                    spent_cents=BudgetPolicy.spent_cents + actual_spend,
                    updated_at=datetime.now(timezone.utc).replace(tzinfo=None),
                )
            )

        await self._db.commit()
        return True

    async def release_reservation(self, reservation_id: uuid.UUID) -> bool:
        """Drop a hold for a call that never billed (provider error, refusal)."""
        res = await self._db.execute(
            select(CostEvent).where(CostEvent.id == reservation_id, CostEvent.status == "reserved")
        )
        event = res.scalars().first()
        if not event:
            return False

        old_hold = event.cost_cents
        policy_id = event.policy_id

        upd_res = await self._db.execute(
            update(CostEvent)
            .where(CostEvent.id == reservation_id, CostEvent.status == "reserved")
            .values(status="released", cost_cents=0, expires_at=None)
        )
        if upd_res.rowcount == 0:
            return False

        if policy_id and old_hold > 0:
            await self._db.execute(
                update(BudgetPolicy)
                .where(BudgetPolicy.id == policy_id)
                .values(
                    reserved_cents=case(
                        (BudgetPolicy.reserved_cents >= old_hold, BudgetPolicy.reserved_cents - old_hold),
                        else_=0,
                    ),
                    updated_at=datetime.now(timezone.utc).replace(tzinfo=None),
                )
            )

        await self._db.commit()
        return True

    async def reap_expired_reservations(self) -> int:
        """Reap and release reservations older than their expiry instant.

        Releases holds where status='reserved' and expires_at <= utcnow,
        restoring reserved_cents on policies.
        """
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        res = await self._db.execute(
            select(CostEvent).where(
                CostEvent.status == "reserved",
                CostEvent.expires_at.is_not(None),
                CostEvent.expires_at <= now,
            )
        )
        expired_events = list(res.scalars().all())
        if not expired_events:
            return 0

        for event in expired_events:
            old_hold = event.cost_cents
            policy_id = event.policy_id
            if policy_id and old_hold > 0:
                await self._db.execute(
                    update(BudgetPolicy)
                    .where(BudgetPolicy.id == policy_id)
                    .values(
                        reserved_cents=case(
                            (BudgetPolicy.reserved_cents >= old_hold, BudgetPolicy.reserved_cents - old_hold),
                            else_=0,
                        ),
                        updated_at=now,
                    )
                )

        await self._db.execute(
            update(CostEvent)
            .where(
                CostEvent.status == "reserved",
                CostEvent.expires_at.is_not(None),
                CostEvent.expires_at <= now,
            )
            .values(status="released", cost_cents=0, expires_at=None)
        )
        await self._db.commit()
        return len(expired_events)

    async def get_usage(
        self,
        scope_type: str,
        scope_id: uuid.UUID,
        window: str = "monthly",
    ) -> UsageSummary | None:
        """Get usage summary for a scope within a time window.

        Args:
            scope_type: Type of scope (company, agent, project).
            scope_id: ID of the scoped entity.
            window: Time window (monthly, weekly, daily).

        Returns:
            UsageSummary with aggregated cost data.
        """
        return await self._get_window_usage(scope_type, scope_id, window)

    async def enforce_limit(
        self,
        agent_id: uuid.UUID,
        cost_cents: int,
    ) -> bool:
        """Check if an agent can spend the given amount.

        Convenience method that combines budget lookup and check
        specifically for agent-level enforcement.

        Args:
            agent_id: The agent attempting to spend.
            cost_cents: The amount to spend in cents.

        Returns:
            True if the spend is allowed, False if it would exceed limits.
        """
        result = await self.check_budget("agent", agent_id, cost_cents)
        return result.allowed

    async def _get_window_usage(
        self,
        scope_type: str,
        scope_id: uuid.UUID,
        window: str,
    ) -> UsageSummary | None:
        """Compute usage within a time window for a scope.

        Args:
            scope_type: Scope type for filtering.
            scope_id: Scope ID for filtering.
            window: Time window kind.

        Returns:
            UsageSummary or None if no events found.
        """
        now = datetime.now(timezone.utc).replace(tzinfo=None)

        if window == "daily":
            window_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        elif window == "weekly":
            days_since_monday = now.weekday()
            window_start = (now - timedelta(days=days_since_monday)).replace(
                hour=0, minute=0, second=0, microsecond=0
            )
        else:  # monthly
            window_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

        # Build filter based on scope type
        if scope_type == "agent":
            filter_col = CostEvent.agent_id
        elif scope_type == "project":
            filter_col = CostEvent.project_id
        else:  # company
            filter_col = CostEvent.company_id

        stmt = select(
            func.coalesce(func.sum(CostEvent.cost_cents), 0),
            func.coalesce(func.sum(CostEvent.input_tokens), 0),
            func.coalesce(func.sum(CostEvent.output_tokens), 0),
            func.count(CostEvent.id),
        ).where(
            filter_col == scope_id,
            CostEvent.occurred_at >= window_start,
            # Live holds count against the budget the same as settled spend --
            # that is what stops two workers from both passing a check that only
            # one of them fits under. Released holds never count, and an expired
            # one stops counting on its own so a worker that died mid-call does
            # not pin the budget forever.
            or_(
                CostEvent.status == "committed",
                and_(
                    CostEvent.status == "reserved",
                    or_(
                        CostEvent.expires_at.is_(None),
                        CostEvent.expires_at > now.replace(tzinfo=None),
                    ),
                ),
            ),
        )

        result = await self._db.execute(stmt)
        row = result.one_or_none()

        if row is None:
            return None

        total_cost, total_input, total_output, count = row

        return UsageSummary(
            scope_type=scope_type,
            scope_id=scope_id,
            total_cost_cents=int(total_cost),
            total_input_tokens=int(total_input),
            total_output_tokens=int(total_output),
            event_count=int(count),
            window_start=window_start,
            window_end=now,
        )

    async def reconcile_budget_counters(self, company_id: uuid.UUID | None = None) -> dict[str, int]:
        """Reconcile policy spent_cents and reserved_cents against actual CostEvents.

        For each active policy, recomputes:
        - actual committed spend since policy's current window start
        - actual active (unexpired) reserved holds
        And updates policy counters if drift is detected.
        """
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        stmt = select(BudgetPolicy).where(BudgetPolicy.is_active == True)  # noqa: E712
        if company_id:
            stmt = stmt.where(BudgetPolicy.company_id == company_id)

        res = await self._db.execute(stmt)
        policies = list(res.scalars().all())

        drift_detected = 0
        reconciled_policies = 0

        for policy in policies:
            if policy.metric != "cost_cents":
                continue

            window_start = policy.window_started_at or _calculate_window_start(policy.window_kind, now)

            # 1. Sum committed spend in current window
            cost_stmt = select(func.coalesce(func.sum(CostEvent.cost_cents), 0)).where(
                CostEvent.company_id == policy.company_id,
                CostEvent.status == "committed",
                CostEvent.occurred_at >= window_start,
            )
            if policy.scope_type == "agent":
                cost_stmt = cost_stmt.where(CostEvent.agent_id == policy.scope_id)
            elif policy.scope_type == "project":
                cost_stmt = cost_stmt.where(CostEvent.project_id == policy.scope_id)

            c_res = await self._db.execute(cost_stmt)
            true_spent = int(c_res.scalar_one_or_none() or 0)

            # 2. Sum live holds
            hold_stmt = select(func.coalesce(func.sum(CostEvent.cost_cents), 0)).where(
                CostEvent.company_id == policy.company_id,
                CostEvent.status == "reserved",
                or_(CostEvent.expires_at.is_(None), CostEvent.expires_at > now),
            )
            if policy.id:
                hold_stmt = hold_stmt.where(
                    or_(CostEvent.policy_id == policy.id, CostEvent.policy_id.is_(None))
                )

            h_res = await self._db.execute(hold_stmt)
            true_reserved = int(h_res.scalar_one_or_none() or 0)

            if policy.spent_cents != true_spent or policy.reserved_cents != true_reserved:
                drift_detected += 1
                policy.spent_cents = true_spent
                policy.reserved_cents = true_reserved
                policy.updated_at = now
                await self._db.execute(
                    update(BudgetPolicy)
                    .where(BudgetPolicy.id == policy.id)
                    .values(
                        spent_cents=true_spent,
                        reserved_cents=true_reserved,
                        updated_at=now,
                    )
                )
            reconciled_policies += 1

        if drift_detected > 0:
            await self._db.commit()

        return {"policies_checked": reconciled_policies, "drift_fixed": drift_detected}

