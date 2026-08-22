"""Department and team listing endpoints."""

import uuid
from typing import Any

from fastapi import APIRouter
from sqlalchemy import select

from nexus.api.deps import DbSession
from nexus.models.company import Department, Team

router = APIRouter(tags=["companies"])


@router.get("/api/v1/companies/{company_id}/departments")
async def list_departments(company_id: uuid.UUID, db: DbSession) -> list[dict[str, Any]]:
    """List all departments for a company."""
    stmt = select(Department).where(Department.company_id == company_id).order_by(Department.name)
    result = await db.execute(stmt)
    return [{"id": str(d.id), "name": d.name, "description": d.description, "budget_monthly_cents": d.budget_monthly_cents} for d in result.scalars().all()]


@router.get("/api/v1/companies/{company_id}/teams")
async def list_teams(company_id: uuid.UUID, db: DbSession) -> list[dict[str, Any]]:
    """List all teams for a company."""
    stmt = select(Team).where(Team.company_id == company_id).order_by(Team.name)
    result = await db.execute(stmt)
    return [{"id": str(t.id), "name": t.name, "description": t.description, "department_id": str(t.department_id)} for t in result.scalars().all()]
