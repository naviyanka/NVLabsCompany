"""Workspace API — multi-project workspace management."""

import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select, update

from nexus.api.deps import CurrentCompanyId, DbSession
from nexus.models.workspace import Workspace

router = APIRouter(tags=["workspaces"])


class WorkspaceCreate(BaseModel):
    name: str
    path: str
    description: str | None = None


class WorkspaceResponse(BaseModel):
    id: uuid.UUID
    company_id: uuid.UUID
    name: str
    path: str
    description: str | None
    is_active: bool
    is_git_repo: bool
    default_branch: str | None
    created_at: datetime


@router.get("/api/v1/companies/{company_id}/workspaces", response_model=list[WorkspaceResponse])
async def list_workspaces(company_id: uuid.UUID, db: DbSession) -> Any:
    """List all workspaces for a company."""
    stmt = select(Workspace).where(Workspace.company_id == company_id).order_by(Workspace.created_at.desc())
    result = await db.execute(stmt)
    return list(result.scalars().all())


@router.post("/api/v1/companies/{company_id}/workspaces", status_code=status.HTTP_201_CREATED, response_model=WorkspaceResponse)
async def create_workspace(company_id: uuid.UUID, body: WorkspaceCreate, db: DbSession) -> Any:
    """Register a new workspace directory."""
    ws_path = Path(body.path)
    is_git = (ws_path / ".git").exists() if ws_path.exists() else False

    workspace = Workspace(
        company_id=company_id,
        name=body.name,
        path=body.path,
        description=body.description,
        is_git_repo=is_git,
        default_branch="main" if is_git else None,
    )
    db.add(workspace)
    await db.flush()
    return workspace


@router.post("/api/v1/workspaces/{workspace_id}/activate")
async def activate_workspace(workspace_id: uuid.UUID, db: DbSession, company_id: CurrentCompanyId) -> dict[str, Any]:
    """Set a workspace as the active workspace (deactivates others)."""
    # Deactivate all
    await db.execute(
        update(Workspace).where(Workspace.company_id == company_id).values(is_active=False)
    )
    # Activate the target
    stmt = select(Workspace).where(Workspace.id == workspace_id, Workspace.company_id == company_id)
    result = await db.execute(stmt)
    ws = result.scalar_one_or_none()
    if not ws:
        raise HTTPException(status_code=404, detail="Workspace not found")
    ws.is_active = True
    ws.last_accessed_at = datetime.utcnow()
    db.add(ws)
    await db.flush()
    return {"workspace_id": str(ws.id), "name": ws.name, "active": True}


@router.delete("/api/v1/workspaces/{workspace_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_workspace(workspace_id: uuid.UUID, db: DbSession, company_id: CurrentCompanyId) -> None:
    """Remove a workspace registration."""
    from sqlalchemy import delete as sa_delete
    await db.execute(sa_delete(Workspace).where(Workspace.id == workspace_id, Workspace.company_id == company_id))
