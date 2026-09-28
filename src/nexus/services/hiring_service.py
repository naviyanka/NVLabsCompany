"""Controlled hiring: a manager asks for a new direct report, and policy decides.

A hiring request is an :class:`~nexus.models.governance.Approval` of type
``hire_employee``, created and decided through :class:`ApprovalService`, so it
shows up in the existing approval queue and uses its conditional status
updates. Nothing here is a second approval, budget or hiring system:

* The request's fields are validated by :class:`HireRequest`, which forbids
  anything else. Company, requesting manager, status, decision and the
  resulting employee are always set here, never taken from the request.
* The hiring rules are ``rules["hiring"]`` on the company's highest-priority
  enabled :class:`~nexus.models.policy.Policy`. With none, every request needs
  a human. Auto-approval needs an explicit, bounded ``auto_approve`` rule, and
  the approval records which policy version authorized it.
* The requesting manager must also be allowed ``manager_request_hire`` by
  ToolPolicy, exactly as the MCP tool is.
* Headcount and budget are checked against live agents plus approved hires
  not yet materialized, under a per-company lock, so concurrent requests or
  approvals cannot overshoot a limit. Approval re-evaluates the policy.
* The employee is created by the same :func:`normalize_cli_employee` as every
  other hiring path, with an ID derived from the request, so a retried or
  concurrent materialization yields the same single employee. No CLI or model
  runs; nothing executable or secret is stored.
* The approval's ``amount_cents`` is the first-year commitment,
  ``one_time + 12 * monthly`` (:func:`commitment_cents`), so a hire takes part
  in the existing signature quorum (``required_signatures_for``). A request that
  needs a quorum is never auto-approved, and approval recomputes the amount
  from the stored request rather than trusting the stored total.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any, Literal

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select, text, update
from sqlalchemy.exc import IntegrityError

from nexus.api.routes.agents import normalize_cli_employee
from nexus.governance.approval_signing import SignatureError, required_signatures_for
from nexus.models.agent import Agent
from nexus.models.company import Company
from nexus.models.governance import Approval
from nexus.models.notification import Notification
from nexus.models.policy import Policy
from nexus.services import manager_service as ms
from nexus.services.approval_service import ApprovalService

HIRE = "hire_employee"
TOOL = "manager_request_hire"
AUTO_APPROVED, APPROVAL_REQUIRED, REJECTED = "auto_approved", "approval_required", "rejected"
_NAMESPACE = uuid.UUID("5d0b6c0e-2f4a-4b8e-9d3c-6a1f0e7b9c21")
_PRIORITY = {"low": "low", "normal": "medium", "high": "high", "critical": "critical"}
_error = ms._error
# Fits a signed 32-bit integer; the request's own bounds keep totals far below it.
MAX_COMMITMENT_CENTS = 2**31 - 1


class HireRequest(BaseModel):
    """What a manager may ask for. Everything else is set by the server."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    role: str = Field(min_length=1, max_length=100)
    title: str = Field(min_length=1, max_length=255)
    reason: str = Field(min_length=1, max_length=2000)
    backend: str = Field(min_length=1, max_length=80)
    model: str | None = Field(default=None, max_length=255)
    responsibilities: str = Field(default="", max_length=4000)
    estimated_monthly_cents: int = Field(ge=0, le=100_000_000)
    estimated_one_time_cents: int = Field(default=0, ge=0, le=100_000_000)
    urgency: Literal["low", "normal", "high", "critical"] = "normal"
    idempotency_key: str = Field(min_length=1, max_length=200)
    # Hire onto a backend that is not installed; the employee is stored as
    # ``configuration_required`` and always needs a human approval.
    allow_configuration_required: bool = False


def commitment_cents(req: HireRequest) -> int:
    """The hire's approval amount: total first-year commitment, in integer cents.

    ``estimated_one_time_cents + 12 * estimated_monthly_cents``.
    """
    total = req.estimated_one_time_cents + 12 * req.estimated_monthly_cents
    if not 0 <= total <= MAX_COMMITMENT_CENTS:
        raise _error(422, "HIRING_AMOUNT_OUT_OF_RANGE",
                     f"First-year commitment {total} is out of range")
    return total


def employee_id_for(request_id: uuid.UUID) -> uuid.UUID:
    """The one employee a hiring request can ever create."""
    return uuid.uuid5(request_id, "employee")


async def _lock(db: Any, company_id: uuid.UUID) -> None:
    """Serialize this company's hiring decisions until the transaction ends.

    Called first in a fresh transaction. On SQLite the no-op write takes the
    database write lock, which is as wide as it gets there.
    """
    if db.get_bind().dialect.name == "postgresql":
        await db.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
            {"key": f"hiring:{company_id}"},
        )
    else:
        await db.execute(
            update(Company).where(Company.id == company_id).values(updated_at=Company.updated_at)
        )


async def _get(db: Any, company_id: uuid.UUID, request_id: uuid.UUID) -> Approval | None:
    return (
        await db.execute(
            select(Approval)
            .where(Approval.id == request_id, Approval.company_id == company_id,
                   Approval.type == HIRE)
            .execution_options(populate_existing=True)
        )
    ).scalar_one_or_none()


async def get_request(
    db: Any, company_id: uuid.UUID, request_id: uuid.UUID, manager_id: uuid.UUID | None = None
) -> Approval:
    """The hiring request in this company (and of this manager, if given), or 404."""
    approval = await _get(db, company_id, request_id)
    if approval is None or manager_id not in (None, approval.requested_by_agent_id):
        raise _error(404, "HIRING_REQUEST_NOT_FOUND", f"Hiring request {request_id} not found")
    return approval


async def _policy(db: Any, company_id: uuid.UUID) -> tuple[Policy | None, dict[str, Any]]:
    rows = (
        await db.execute(
            select(Policy)
            .where(Policy.company_id == company_id, Policy.enabled == True)  # noqa: E712
            .order_by(Policy.priority.desc(), Policy.created_at, Policy.id)
        )
    ).scalars().all()
    for policy in rows:
        rules = (policy.rules or {}).get("hiring")
        if isinstance(rules, dict):
            return policy, rules
    return None, {}


def _limit(rules: dict[str, Any], key: str) -> int | None:
    value = rules.get(key)
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None


async def _committed(
    db: Any, company_id: uuid.UUID, exclude: uuid.UUID | None
) -> list[dict[str, Any]]:
    """Approved hires whose employee does not exist yet: already spent, not yet counted.

    ponytail: scans every approved hire of the company; keep a materialized
    flag on the request if that ever gets large.
    """
    approved = (
        await db.execute(
            select(Approval).where(
                Approval.company_id == company_id,
                Approval.type == HIRE,
                Approval.status == "approved",
            )
        )
    ).scalars().all()
    pending = {employee_id_for(a.id): a for a in approved if a.id != exclude}
    if not pending:
        return []
    existing = set(
        (await db.execute(select(Agent.id).where(Agent.id.in_(pending)))).scalars().all()
    )
    return [
        {**a.payload["request"], "manager_id": a.requested_by_agent_id}
        for eid, a in pending.items()
        if eid not in existing
    ]


async def _hired_this_month(db: Any, company_id: uuid.UUID, exclude: uuid.UUID | None) -> int:
    now = datetime.now(UTC).replace(tzinfo=None)
    start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    rows = (
        await db.execute(
            select(Approval).where(
                Approval.company_id == company_id,
                Approval.type == HIRE,
                Approval.status == "approved",
                Approval.decided_at >= start,
            )
        )
    ).scalars().all()
    return sum(a.payload["request"]["estimated_one_time_cents"] for a in rows if a.id != exclude)


async def evaluate(
    db: Any,
    company_id: uuid.UUID,
    manager: Agent,
    req: HireRequest,
    exclude: uuid.UUID | None = None,
) -> dict[str, Any]:
    """The policy decision for ``req`` from ``manager``; deterministic, no side effects.

    ``exclude`` is the request being approved, so it does not count against itself.
    """
    from nexus.tools.access import DENIED, check_tool_access
    from nexus.tools.context import INBOUND_MCP, ExecutionContext

    policy, rules = await _policy(db, company_id)
    source = f"policy:{policy.id}:v{policy.version}" if policy else "policy:default"
    rejected: list[dict[str, str]] = []
    held: list[dict[str, str]] = []

    def no(code: str, message: str) -> None:
        rejected.append({"code": code, "message": message})

    if manager.company_id != company_id or manager.status == "terminated":
        no("MANAGER_INACTIVE", "The requesting manager is not an active agent of this company")

    ctx = ExecutionContext(
        company_id=company_id, principal_id=f"agent:{manager.id}", principal_role="agent",
        source=INBOUND_MCP, agent_id=manager.id,
    )
    access = await check_tool_access(db, ctx, tool_name=TOOL, default_risk="write")
    if access.outcome == DENIED:
        no("TOOL_POLICY_DENIED", f"ToolPolicy does not allow {TOOL} for this manager")

    backend, override = req.backend, None
    try:
        config, override = normalize_cli_employee(
            "cli", {"backend": req.backend}, req.model, req.allow_configuration_required
        )
        backend = config["backend"]
    except HTTPException as exc:
        no(exc.detail["code"], exc.detail["message"])
    if override:
        held.append({"code": "CONFIGURATION_REQUIRED",
                     "message": f"{backend} is not ready here; the hire needs setup"})

    for key, value, code in (
        ("allowed_roles", req.role, "ROLE_NOT_ALLOWED"),
        ("allowed_backends", backend, "BACKEND_NOT_ALLOWED"),
        ("allowed_models", (req.model or "").strip(), "MODEL_NOT_ALLOWED"),
    ):
        allowed = rules.get(key)
        if isinstance(allowed, list) and value not in allowed:
            no(code, f"'{value}' is not in the policy's {key}")

    live = (
        await db.execute(
            select(Agent.manager_id, Agent.budget_monthly_cents).where(
                Agent.company_id == company_id, Agent.status != "terminated"
            )
        )
    ).all()
    committed = await _committed(db, company_id, exclude)

    cap = _limit(rules, "max_headcount")
    if cap is not None and len(live) + len(committed) + 1 > cap:
        no("HEADCOUNT_LIMIT", f"Headcount would exceed {cap}")
    cap = _limit(rules, "max_direct_reports")
    reports = sum(1 for m, _ in live if m == manager.id)
    reports += sum(1 for c in committed if c["manager_id"] == manager.id)
    if cap is not None and reports + 1 > cap:
        no("DIRECT_REPORTS_LIMIT", f"The manager would exceed {cap} direct reports")

    cap = _limit(rules, "max_recurring_monthly_cents")
    if cap is None:
        company = await db.get(Company, company_id)
        cap = company.budget_monthly_cents if company and company.budget_monthly_cents > 0 else None
    recurring = sum(b or 0 for _, b in live) + sum(c["estimated_monthly_cents"] for c in committed)
    if cap is not None and recurring + req.estimated_monthly_cents > cap:
        no("RECURRING_BUDGET_EXCEEDED", f"Monthly agent budget would exceed {cap} cents")
    cap = _limit(rules, "hiring_budget_monthly_cents")
    if cap is not None:
        spent = await _hired_this_month(db, company_id, exclude)
        if spent + req.estimated_one_time_cents > cap:
            no("HIRING_BUDGET_EXCEEDED",
               f"This month's hiring budget of {cap} cents would be exceeded")

    amount = commitment_cents(req)
    quorum = required_signatures_for(HIRE, {"amount_cents": amount})
    if quorum > 1:
        # Policy cannot stand in for a signature quorum.
        held.append({"code": "SIGNATURE_QUORUM_REQUIRED",
                     "message": f"A first-year commitment of {amount} cents needs "
                                f"{quorum} signatures"})

    auto = rules.get("auto_approve") if isinstance(rules.get("auto_approve"), dict) else {}
    max_monthly, max_once = _limit(auto, "max_monthly_cents"), _limit(auto, "max_one_time_cents")
    # Auto-approval only under an explicit rule with both bounds set.
    auto_ok = (
        policy is not None
        and auto.get("enabled") is True
        and max_monthly is not None
        and max_once is not None
        and req.estimated_monthly_cents <= max_monthly
        and req.estimated_one_time_cents <= max_once
    )
    outcome, rule = APPROVAL_REQUIRED, f"{source}:hiring"
    if rejected:
        outcome = REJECTED
    elif not held and auto_ok:
        outcome, rule = AUTO_APPROVED, f"{source}:hiring.auto_approve"
    elif not held:
        held.append({"code": "HUMAN_APPROVAL_REQUIRED",
                     "message": "No bounded auto-approval rule covers this request"})
    return {
        "outcome": outcome,
        "rule": rule,
        "reasons": rejected or held,
        "backend": backend,
        "configuration_required": bool(override),
        "amount_cents": amount,
        "required_signatures": quorum,
        "evaluated_at": datetime.now(UTC).isoformat(),
    }


async def submit(
    db: Any, company_id: uuid.UUID, manager_id: uuid.UUID, req: HireRequest, actor: str
) -> tuple[Approval, bool]:
    """File ``req`` for ``manager_id``; ``(request, created)``. Idempotent per key.

    Commits. An auto-approved request is materialized before this returns.
    """
    request_id = uuid.uuid5(_NAMESPACE, f"{company_id}:{manager_id}:{req.idempotency_key}")
    body = req.model_dump()

    def same(existing: Approval) -> Approval:
        if existing.requested_by_agent_id != manager_id or existing.payload["request"] != body:
            raise _error(409, "IDEMPOTENCY_KEY_REUSED",
                         "This idempotency key was used for a different hiring request")
        return existing

    manager = await ms.get_agent(db, company_id, manager_id)
    existing = await _get(db, company_id, request_id)
    if existing is not None:
        return same(existing), False

    await db.commit()
    await _lock(db, company_id)
    existing = await _get(db, company_id, request_id)
    if existing is not None:
        await db.commit()
        return same(existing), False

    decision = await evaluate(db, company_id, manager, req)
    service = ApprovalService(db)
    approval = await service.request_approval(
        company_id, HIRE, manager_id,
        {"request": body, "amount_cents": decision["amount_cents"], "policy": decision},
        approval_id=request_id,
    )
    common = {"manager_id": str(manager_id), "role": req.role, "backend": decision["backend"]}
    await ms.audit(db, company_id, "hiring.request_submitted", actor, "approval", request_id,
                   **common, urgency=req.urgency,
                   estimated_monthly_cents=req.estimated_monthly_cents,
                   estimated_one_time_cents=req.estimated_one_time_cents)
    await ms.audit(db, company_id, "hiring.policy_evaluated", actor, "approval", request_id,
                   stage="submission", outcome=decision["outcome"], rule=decision["rule"],
                   reasons=decision["reasons"])
    note = "; ".join(r["message"] for r in decision["reasons"])
    if decision["outcome"] == AUTO_APPROVED:
        await service.approve(request_id, decision["rule"], "Auto-approved by policy")
        await ms.audit(db, company_id, "hiring.auto_approved", decision["rule"], "approval",
                       request_id, **common, rule=decision["rule"])
    elif decision["outcome"] == REJECTED:
        await service.reject(request_id, decision["rule"], note)
        await ms.audit(db, company_id, "hiring.rejected", decision["rule"], "approval",
                       request_id, **common, reason=note, by="policy")
    else:
        db.add(Notification(
            company_id=company_id,
            agent_id=manager_id,
            title=f"Hiring request needs approval: {req.title}",
            description=f"{manager.name} asks to hire a {req.role} on {decision['backend']}: "
                        f"{req.reason[:300]}",
            notification_type="warning",
            module="agents",
            priority=_PRIORITY[req.urgency],
            notification_metadata={"approval_id": str(request_id), **common,
                                   "reasons": decision["reasons"]},
        ))
    await db.commit()
    approval = await get_request(db, company_id, request_id)
    if approval.status == "approved":
        await materialize(db, approval, decision["rule"])
    return approval, True


def _require_human(principal: Any) -> None:
    # A manager (or any agent) cannot decide a hiring request, its own included.
    if principal.agent_id is not None or principal.kind == "run":
        raise _error(403, "HUMAN_DECISION_REQUIRED", "Only a human can decide a hiring request")


async def approve(
    db: Any, company_id: uuid.UUID, request_id: uuid.UUID, principal: Any, note: str | None
) -> Approval:
    """A human approves; policy is re-evaluated first. Idempotent. Commits."""
    _require_human(principal)
    approval = await get_request(db, company_id, request_id)
    if approval.status == "pending":
        await db.commit()
        await _lock(db, company_id)
        approval = await get_request(db, company_id, request_id)
    if approval.status == "pending":
        req = HireRequest(**approval.payload["request"])
        amount = commitment_cents(req)
        if (approval.payload.get("amount_cents") != amount
                or approval.required_signatures < required_signatures_for(
                    HIRE, {"amount_cents": amount})):
            await db.rollback()
            raise _error(409, "HIRING_AMOUNT_MISMATCH",
                         "The request's stored amount does not match its costs")
        manager = await ms.get_agent(db, company_id, approval.requested_by_agent_id)
        decision = await evaluate(db, company_id, manager, req, exclude=request_id)
        await ms.audit(db, company_id, "hiring.policy_evaluated", principal.display_name,
                       "approval", request_id, stage="approval", outcome=decision["outcome"],
                       rule=decision["rule"], reasons=decision["reasons"])
        if decision["outcome"] == REJECTED:
            await db.commit()
            raise HTTPException(status_code=409, detail={
                "code": "HIRING_POLICY_REJECTED",
                "message": "; ".join(r["message"] for r in decision["reasons"]),
                "reasons": decision["reasons"],
            })
        try:
            approval = await ApprovalService(db).approve(request_id, principal.display_name, note)
        except SignatureError as exc:
            await db.commit()
            raise _error(409, "APPROVAL_QUORUM_NOT_MET", str(exc)) from exc
        if approval.status != "approved":
            await db.rollback()
            raise _error(409, "HIRING_REQUEST_DECIDED", f"The request is already {approval.status}")
        approval.payload = {**approval.payload, "approval_policy": decision}
        await ms.audit(db, company_id, "hiring.approved", principal.display_name, "approval",
                       request_id, manager_id=str(approval.requested_by_agent_id),
                       rule=decision["rule"], note=note)
        await db.commit()
    if approval.status != "approved":
        raise _error(409, "HIRING_REQUEST_DECIDED", f"The request is already {approval.status}")
    await materialize(db, approval, principal.display_name)
    return approval


async def reject(
    db: Any, company_id: uuid.UUID, request_id: uuid.UUID, principal: Any, note: str | None
) -> Approval:
    """A human rejects with a reason. Idempotent. Commits."""
    _require_human(principal)
    reason = (note or "").strip()
    if not reason:
        raise _error(422, "REJECTION_REASON_REQUIRED", "A rejection needs a reason")
    approval = await get_request(db, company_id, request_id)
    if approval.status == "pending":
        approval = await ApprovalService(db).reject(request_id, principal.display_name, reason)
        if approval.status == "rejected" and approval.decided_by == principal.display_name:
            await ms.audit(db, company_id, "hiring.rejected", principal.display_name, "approval",
                           request_id, manager_id=str(approval.requested_by_agent_id),
                           reason=reason, by="human")
        await db.commit()
    if approval.status != "rejected":
        raise _error(409, "HIRING_REQUEST_DECIDED", f"The request is already {approval.status}")
    return approval


async def materialize(db: Any, approval: Approval, actor: str) -> Agent:
    """The approved request's employee, creating it once. Commits."""
    request_id, company_id = approval.id, approval.company_id
    employee_id = employee_id_for(request_id)
    await db.commit()
    await _lock(db, company_id)
    existing = await db.get(Agent, employee_id, populate_existing=True)
    if existing is not None:
        return existing
    req = HireRequest(**approval.payload["request"])
    try:
        config, override = normalize_cli_employee(
            "cli", {"backend": req.backend}, req.model, req.allow_configuration_required
        )
        agent = Agent(
            id=employee_id,
            company_id=company_id,
            name=req.title,
            role=req.role,
            title=req.title,
            manager_id=approval.requested_by_agent_id,
            adapter_type="cli",
            adapter_config=config,
            model=(req.model or "").strip(),
            responsibilities=req.responsibilities or None,
            budget_monthly_cents=req.estimated_monthly_cents,
            status=override or "idle",
        )
        db.add(agent)
        await db.flush()
    except IntegrityError:
        # Another worker created it first.
        await db.rollback()
        existing = await db.get(Agent, employee_id, populate_existing=True)
        if existing is not None:
            return existing
        await _failed(db, company_id, request_id, actor, "EMPLOYEE_INSERT_FAILED",
                      "The employee row was refused")
        raise _error(409, "HIRING_MATERIALIZATION_FAILED", "The employee could not be created")
    except HTTPException as exc:
        await db.rollback()
        await _failed(db, company_id, request_id, actor, exc.detail["code"], exc.detail["message"])
        raise _error(409, "HIRING_MATERIALIZATION_FAILED", exc.detail["message"]) from exc
    details = {"name": agent.name, "role": agent.role, "adapter_type": "cli",
               "cli_backend": config["backend"], "model": agent.model, "status": agent.status,
               "manager_id": str(agent.manager_id), "hiring_request_id": str(approval.id)}
    await ms.audit(db, company_id, "agent.created", actor, "agent", employee_id, **details)
    await ms.audit(db, company_id, "hiring.employee_created", actor, "approval", approval.id,
                   employee_id=str(employee_id), manager_id=str(agent.manager_id))
    await db.commit()
    return agent


async def _failed(
    db: Any, company_id: uuid.UUID, request_id: uuid.UUID, actor: str, code: str, message: str
) -> None:
    # Takes ids, not the Approval: after the rollback its attributes are expired.
    await ms.audit(db, company_id, "hiring.materialization_failed", actor, "approval",
                   request_id, code=code, message=message)
    await db.commit()


async def list_requests(db: Any, company_id: uuid.UUID, manager_id: uuid.UUID) -> list[Approval]:
    """The manager's hiring requests, newest first."""
    await ms.get_agent(db, company_id, manager_id)
    rows = await db.execute(
        select(Approval)
        .where(Approval.company_id == company_id, Approval.type == HIRE,
               Approval.requested_by_agent_id == manager_id)
        .order_by(Approval.created_at.desc(), Approval.id)
        .limit(100)
    )
    return list(rows.scalars().all())


async def view(db: Any, approval: Approval) -> dict[str, Any]:
    """The request as the API and the manager tools show it."""
    employee = None
    if approval.status == "approved":
        employee = await db.get(Agent, employee_id_for(approval.id))
    req = dict(approval.payload["request"])
    policy = approval.payload.get("policy") or {}
    state = {"pending": APPROVAL_REQUIRED, "rejected": REJECTED}.get(
        approval.status, "hired" if employee else "approved"
    )
    return {
        "id": str(approval.id),
        "status": state,
        "approval_status": approval.status,
        "manager_id": str(approval.requested_by_agent_id),
        "request": req,
        "policy_decision": policy.get("outcome"),
        "policy_rule": policy.get("rule"),
        "policy_reasons": policy.get("reasons", []),
        "amount_cents": approval.payload.get("amount_cents"),
        "required_signatures": approval.required_signatures,
        "decided_by": approval.decided_by,
        "decided_at": approval.decided_at.isoformat() if approval.decided_at else None,
        "rejection_reason": approval.decision_note if approval.status == "rejected" else None,
        "employee": ms.agent_ref(employee) if employee else None,
        "created_at": approval.created_at.isoformat(),
    }

