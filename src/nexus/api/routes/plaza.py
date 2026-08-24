"""Plaza API — shared agent knowledge feed (inspired by Clawith 'The Plaza')."""

import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from nexus.api.deps import CurrentCompanyId, DbSession
from nexus.models.plaza import PlazaPost

router = APIRouter(tags=["plaza"])


class PlazaPostCreate(BaseModel):
    agent_id: uuid.UUID
    agent_name: str = ""
    post_type: str = "observation"
    content: str = Field(..., min_length=1, max_length=5000)


class PlazaPostResponse(BaseModel):
    id: uuid.UUID
    company_id: uuid.UUID
    agent_id: uuid.UUID
    agent_name: str
    post_type: str
    content: str
    reactions: int
    created_at: datetime


@router.get("/api/v1/companies/{company_id}/plaza", response_model=list[PlazaPostResponse])
async def list_plaza_posts(
    company_id: uuid.UUID, db: DbSession, limit: int = 50, offset: int = 0
) -> Any:
    """List recent Plaza posts for the organization."""
    stmt = (
        select(PlazaPost)
        .where(PlazaPost.company_id == company_id)
        .order_by(PlazaPost.created_at.desc())
        .offset(offset)
        .limit(limit)
    )
    result = await db.execute(stmt)
    return list(result.scalars().all())


@router.post("/api/v1/companies/{company_id}/plaza", status_code=status.HTTP_201_CREATED, response_model=PlazaPostResponse)
async def create_plaza_post(
    company_id: uuid.UUID, body: PlazaPostCreate, db: DbSession
) -> Any:
    """Create a new Plaza post (agent publishes a discovery/observation)."""
    post = PlazaPost(
        company_id=company_id,
        agent_id=body.agent_id,
        agent_name=body.agent_name,
        post_type=body.post_type,
        content=body.content,
    )
    db.add(post)
    await db.flush()
    return post


@router.post("/api/v1/plaza/{post_id}/react")
async def react_to_post(post_id: uuid.UUID, db: DbSession, company_id: CurrentCompanyId) -> dict[str, Any]:
    """React to a Plaza post (acknowledge/agree)."""
    stmt = select(PlazaPost).where(PlazaPost.id == post_id, PlazaPost.company_id == company_id)
    result = await db.execute(stmt)
    post = result.scalar_one_or_none()
    if post:
        post.reactions += 1
        db.add(post)
        await db.flush()
    return {"post_id": str(post_id), "reactions": post.reactions if post else 0}
