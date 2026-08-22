"""Company CRUD API endpoints."""

import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select, update, delete

from nexus.api.deps import DbSession
from nexus.models.company import Company

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
async def create_company(body: CompanyCreate, db: DbSession) -> Any:
    """Create a new company."""
    company = Company(
        name=body.name,
        description=body.description,
        budget_monthly_cents=body.budget_monthly_cents,
        issue_prefix=body.issue_prefix,
    )
    db.add(company)
    await db.flush()
    return company


@router.get("", response_model=list[CompanyResponse])
async def list_companies(
    db: DbSession,
    limit: int = 100,
    offset: int = 0,
) -> Any:
    """List all companies."""
    stmt = select(Company).offset(offset).limit(limit).order_by(Company.created_at.desc())
    result = await db.execute(stmt)
    return list(result.scalars().all())


@router.get("/{company_id}", response_model=CompanyResponse)
async def get_company(company_id: uuid.UUID, db: DbSession) -> Any:
    """Get a company by ID."""
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
    company_id: uuid.UUID, body: CompanyUpdate, db: DbSession
) -> Any:
    """Update a company."""
    updates = body.model_dump(exclude_unset=True)
    if not updates:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No fields to update",
        )
    updates["updated_at"] = datetime.utcnow()
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
async def delete_company(company_id: uuid.UUID, db: DbSession) -> None:
    """Delete a company."""
    stmt = delete(Company).where(Company.id == company_id)
    result = await db.execute(stmt)
    if result.rowcount == 0:  # type: ignore[union-attr]
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Company {company_id} not found",
        )
