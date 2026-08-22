"""Company CRUD API endpoints.

A company is a tenant boundary, so these routes are scoped to the caller rather
than to whatever UUID appears in the URL:

* listing returns only the companies the caller is a member of, not every row in
  the table;
* reading, updating and deleting operate on the caller's active company, which
  is the one their session or API key is bound to — switching companies goes
  through ``POST /api/v1/auth/switch-company``;
* creating and destroying tenants requires the administrator role, and the
  creator is granted membership of the new company so it does not become an
  orphan no one can reach.
"""

import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import delete, select, update

from nexus.api.deps import CurrentPrincipal, DbSession, PathCompanyId, RequireAdmin
from nexus.auth.users import grant_membership
from nexus.models._time import utcnow
from nexus.models.company import Company, CompanyMembership

router = APIRouter(prefix="/api/v1/companies", tags=["companies"])


class CompanyCreate(BaseModel):
    """Request body for creating a company."""

    name: str
    description: str | None = None
    budget_monthly_cents: int = 0
    issue_prefix: str | None = None


class CompanyUpdate(BaseModel):
    """Request body for updating a company."""

    name: str | None = None
    description: str | None = None
    status: str | None = None
    budget_monthly_cents: int | None = None
    issue_prefix: str | None = None


class CompanyResponse(BaseModel):
    """Response model for a company."""

    id: uuid.UUID
    name: str
    description: str | None = None
    status: str
    budget_monthly_cents: int
    spent_monthly_cents: int
    issue_prefix: str | None = None
    created_at: datetime
    updated_at: datetime


@router.post("", status_code=status.HTTP_201_CREATED, response_model=CompanyResponse)
async def create_company(
    body: CompanyCreate, db: DbSession, principal: RequireAdmin
) -> Any:
    """Create a new company.

    The creator becomes an administrator of it. Without that membership the new
    tenant would be unreachable: nothing in the API can switch into a company
    the caller does not belong to, and there is no cross-tenant super-user.
    """
    company = Company(
        name=body.name,
        description=body.description,
        budget_monthly_cents=body.budget_monthly_cents,
        issue_prefix=body.issue_prefix,
    )
    db.add(company)
    await db.flush()

    if principal.user_id is not None:
        await grant_membership(
            db, user_id=principal.user_id, company_id=company.id, role="admin"
        )
    return company


@router.get("", response_model=list[CompanyResponse])
async def list_companies(
    db: DbSession,
    principal: CurrentPrincipal,
    limit: int = 100,
    offset: int = 0,
) -> Any:
    """List the companies the caller belongs to.

    A service principal has no membership rows — an API key is issued for one
    company — so it sees exactly that company.
    """
    if principal.user_id is None:
        stmt = select(Company).where(Company.id == principal.company_id)
    else:
        stmt = (
            select(Company)
            .join(CompanyMembership, CompanyMembership.company_id == Company.id)
            .where(CompanyMembership.user_id == principal.user_id)
            .offset(offset)
            .limit(limit)
            .order_by(Company.created_at.desc())
        )
    result = await db.execute(stmt)
    return list(result.scalars().all())


@router.get("/{company_id}", response_model=CompanyResponse)
async def get_company(company_id: PathCompanyId, db: DbSession) -> Any:
    """Get the caller's active company by ID."""
    stmt = select(Company).where(Company.id == company_id)
    result = await db.execute(stmt)
    company = result.scalar_one_or_none()
    if company is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Company {company_id} not found",
        )
    return company


@router.put("/{company_id}", response_model=CompanyResponse)
async def update_company(
    company_id: PathCompanyId,
    body: CompanyUpdate,
    db: DbSession,
    principal: RequireAdmin,
) -> Any:
    """Update the caller's active company."""
    updates = body.model_dump(exclude_unset=True)
    if not updates:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No fields to update",
        )
    updates["updated_at"] = utcnow()
    stmt = update(Company).where(Company.id == company_id).values(**updates)
    await db.execute(stmt)

    result = await db.execute(select(Company).where(Company.id == company_id))
    company = result.scalar_one_or_none()
    if company is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Company {company_id} not found",
        )
    return company


@router.delete("/{company_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_company(
    company_id: PathCompanyId, db: DbSession, principal: RequireAdmin
) -> None:
    """Delete the caller's active company."""
    stmt = delete(Company).where(Company.id == company_id)
    result = await db.execute(stmt)
    if result.rowcount == 0:  # type: ignore[union-attr]
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Company {company_id} not found",
        )
