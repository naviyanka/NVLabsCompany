"""Policy management API endpoints."""

import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select, update

from nexus.api.deps import CurrentCompanyId, DbSession
from nexus.models.policy import Policy, PolicyVersion

router = APIRouter(tags=["policies"])


# --- Request/Response Models ---


class PolicyCreate(BaseModel):
    """Request body for creating a policy."""

    name: str
    description: str | None = None
    rules: dict[str, Any] | None = None
    priority: int = 0
    enabled: bool = True


class PolicyUpdate(BaseModel):
    """Request body for updating a policy."""

    name: str | None = None
    description: str | None = None
    rules: dict[str, Any] | None = None
    priority: int | None = None
    enabled: bool | None = None


class PolicyEvaluateRequest(BaseModel):
    """Request body for testing policy evaluation."""

    context: dict[str, Any]
    action: str
    resource_type: str | None = None
    resource_id: str | None = None


class PolicyEvaluateResponse(BaseModel):
    """Response from policy evaluation."""

    allowed: bool
    matching_policies: list[dict[str, Any]]
    reason: str | None = None


class PolicyResponse(BaseModel):
    """Response model for a policy."""

    id: uuid.UUID
    company_id: uuid.UUID
    name: str
    description: str | None = None
    rules: dict[str, Any] | None = None
    priority: int
    enabled: bool
    version: int
    created_at: datetime
    updated_at: datetime


# --- Routes ---


@router.get(
    "/api/v1/policies",
    response_model=list[PolicyResponse],
)
async def list_policies(
    db: DbSession,
    company_id: CurrentCompanyId,
    enabled_only: bool = True,
    limit: int = 100,
    offset: int = 0,
) -> Any:
    """List active policies for the current company."""
    stmt = select(Policy).where(Policy.company_id == company_id)
    if enabled_only:
        stmt = stmt.where(Policy.enabled == True)  # noqa: E712
    stmt = stmt.order_by(Policy.priority.desc()).offset(offset).limit(limit)
    result = await db.execute(stmt)
    return list(result.scalars().all())


@router.post(
    "/api/v1/policies",
    status_code=status.HTTP_201_CREATED,
    response_model=PolicyResponse,
)
async def create_policy(
    body: PolicyCreate,
    db: DbSession,
    company_id: CurrentCompanyId,
) -> Any:
    """Create a new governance policy."""
    policy = Policy(
        company_id=company_id,
        name=body.name,
        description=body.description,
        rules=body.rules,
        priority=body.priority,
        enabled=body.enabled,
    )
    db.add(policy)
    await db.flush()

    # Create initial policy version
    version = PolicyVersion(
        policy_id=policy.id,
        version_number=1,
        rules_snapshot=body.rules,
        changed_by=str(company_id),
    )
    db.add(version)
    await db.flush()

    return policy


@router.put(
    "/api/v1/policies/{policy_id}",
    response_model=PolicyResponse,
)
async def update_policy(
    policy_id: uuid.UUID,
    body: PolicyUpdate,
    db: DbSession,
    company_id: CurrentCompanyId,
) -> Any:
    """Update an existing policy."""
    stmt = select(Policy).where(
        Policy.id == policy_id, Policy.company_id == company_id
    )
    result = await db.execute(stmt)
    policy = result.scalar_one_or_none()

    if not policy:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Policy {policy_id} not found",
        )

    # Apply updates
    update_data: dict[str, Any] = {"updated_at": datetime.now(timezone.utc)}
    if body.name is not None:
        update_data["name"] = body.name
    if body.description is not None:
        update_data["description"] = body.description
    if body.rules is not None:
        update_data["rules"] = body.rules
    if body.priority is not None:
        update_data["priority"] = body.priority
    if body.enabled is not None:
        update_data["enabled"] = body.enabled

    # Increment version if rules changed
    if body.rules is not None:
        update_data["version"] = policy.version + 1

    stmt_update = (
        update(Policy)
        .where(Policy.id == policy_id)
        .values(**update_data)
    )
    await db.execute(stmt_update)

    # Record version snapshot if rules changed
    if body.rules is not None:
        version = PolicyVersion(
            policy_id=policy_id,
            version_number=policy.version + 1,
            rules_snapshot=body.rules,
            changed_by=str(company_id),
        )
        db.add(version)
        await db.flush()

    # Return updated policy
    result = await db.execute(
        select(Policy).where(Policy.id == policy_id)
    )
    return result.scalar_one()


@router.delete(
    "/api/v1/policies/{policy_id}",
    status_code=status.HTTP_200_OK,
)
async def disable_policy(
    policy_id: uuid.UUID,
    db: DbSession,
    company_id: CurrentCompanyId,
) -> Any:
    """Disable (soft-delete) a policy."""
    stmt = (
        update(Policy)
        .where(Policy.id == policy_id, Policy.company_id == company_id)
        .values(enabled=False, updated_at=datetime.now(timezone.utc))
    )
    result = await db.execute(stmt)
    if result.rowcount == 0:  # type: ignore[union-attr]
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Policy {policy_id} not found",
        )
    return {"detail": "Policy disabled", "policy_id": str(policy_id)}


@router.post(
    "/api/v1/policies/evaluate",
    response_model=PolicyEvaluateResponse,
)
async def evaluate_policies(
    body: PolicyEvaluateRequest,
    db: DbSession,
    company_id: CurrentCompanyId,
) -> Any:
    """Test policy evaluation against a hypothetical action.

    Evaluates all active policies for the company and returns whether
    the action would be allowed.
    """
    # Fetch active policies ordered by priority
    stmt = (
        select(Policy)
        .where(Policy.company_id == company_id, Policy.enabled == True)  # noqa: E712
        .order_by(Policy.priority.desc())
    )
    result = await db.execute(stmt)
    policies = list(result.scalars().all())

    matching_policies: list[dict[str, Any]] = []
    allowed = True

    for policy in policies:
        if policy.rules:
            # Check if the policy applies to this action
            applicable_actions = policy.rules.get("actions", [])
            if applicable_actions and body.action in applicable_actions:
                matching_policies.append({
                    "id": str(policy.id),
                    "name": policy.name,
                    "priority": policy.priority,
                    "rules": policy.rules,
                })
                # Check deny rules
                if policy.rules.get("effect") == "deny":
                    allowed = False

    reason = None
    if not allowed:
        reason = "Denied by policy"

    return PolicyEvaluateResponse(
        allowed=allowed,
        matching_policies=matching_policies,
        reason=reason,
    )
