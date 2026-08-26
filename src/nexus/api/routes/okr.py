"""OKR Management API routes — DB-backed.

Provides REST endpoints for managing Objectives and Key Results,
persisted in okr_objectives / okr_key_results tables.
"""

import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from nexus.api.deps import CurrentCompanyId, DbSession
from nexus.models.okr import OKRKeyResult, OKRObjective

router = APIRouter(tags=["okr"])


class CreateObjectiveRequest(BaseModel):
    title: str = Field(..., description="Title of the objective")
    description: str = Field("", description="Detailed description")
    owner_agent_id: uuid.UUID = Field(..., description="Agent responsible for this objective")
    time_frame: str = Field("Q1 2025", description="Time frame for completion")


class AddKeyResultRequest(BaseModel):
    title: str = Field(..., description="Title of the key result")
    target_value: float = Field(..., description="Target value to achieve")
    unit: str = Field("percent", description="Unit of measurement")


class UpdateProgressRequest(BaseModel):
    current_value: float = Field(..., description="Current progress value")


class KeyResultResponse(BaseModel):
    id: uuid.UUID
    objective_id: uuid.UUID
    title: str
    target_value: float
    current_value: float
    unit: str
    status: str
    updated_at: str


class ObjectiveResponse(BaseModel):
    id: uuid.UUID
    title: str
    description: str
    owner_agent_id: uuid.UUID | None
    time_frame: str
    status: str
    key_results: list[KeyResultResponse]
    created_at: str
    progress: float = 0.0


class ObjectiveListResponse(BaseModel):
    objectives: list[ObjectiveResponse]


class AtRiskResponse(BaseModel):
    at_risk_objectives: list[ObjectiveResponse]
    time_elapsed_fraction: float


def _compute_progress(key_results: list[OKRKeyResult]) -> float:
    if not key_results:
        return 0.0
    total = 0.0
    for kr in key_results:
        if kr.target_value > 0:
            total += min(kr.current_value / kr.target_value, 1.0)
    return total / len(key_results)


def _serialize_objective(obj: OKRObjective, key_results: list[OKRKeyResult]) -> dict[str, Any]:
    progress = _compute_progress(key_results)
    return {
        "id": obj.id,
        "title": obj.title,
        "description": obj.description or "",
        "owner_agent_id": obj.owner_agent_id,
        "time_frame": obj.time_frame,
        "status": obj.status,
        "key_results": [
            {
                "id": kr.id,
                "objective_id": kr.objective_id,
                "title": kr.title,
                "target_value": kr.target_value,
                "current_value": kr.current_value,
                "unit": kr.unit,
                "status": kr.status,
                "updated_at": kr.updated_at.isoformat() if kr.updated_at else "",
            }
            for kr in key_results
        ],
        "created_at": obj.created_at.isoformat() if obj.created_at else "",
        "progress": progress,
    }


@router.post(
    "/okrs/objectives",
    response_model=ObjectiveResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_objective(
    request: CreateObjectiveRequest,
    company_id: CurrentCompanyId,
    db: DbSession,
) -> dict[str, Any]:
    obj = OKRObjective(
        company_id=company_id,
        title=request.title,
        description=request.description,
        owner_agent_id=request.owner_agent_id,
        time_frame=request.time_frame,
        status="active",
    )
    db.add(obj)
    await db.commit()
    await db.refresh(obj)
    return _serialize_objective(obj, [])


@router.get("/okrs/objectives", response_model=ObjectiveListResponse)
async def list_objectives(
    company_id: CurrentCompanyId,
    db: DbSession,
) -> dict[str, Any]:
    result = await db.execute(
        select(OKRObjective).where(OKRObjective.company_id == company_id)
    )
    objectives = result.scalars().all()

    serialized = []
    for obj in objectives:
        kr_result = await db.execute(
            select(OKRKeyResult).where(OKRKeyResult.objective_id == obj.id)
        )
        krs = kr_result.scalars().all()
        serialized.append(_serialize_objective(obj, krs))

    return {"objectives": serialized}


@router.get("/okrs/objectives/{objective_id}", response_model=ObjectiveResponse)
async def get_objective(
    objective_id: uuid.UUID,
    company_id: CurrentCompanyId,
    db: DbSession,
) -> dict[str, Any]:
    result = await db.execute(
        select(OKRObjective).where(
            OKRObjective.id == objective_id,
            OKRObjective.company_id == company_id,
        )
    )
    obj = result.scalar_one_or_none()
    if obj is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Objective {objective_id} not found",
        )

    kr_result = await db.execute(
        select(OKRKeyResult).where(OKRKeyResult.objective_id == obj.id)
    )
    krs = kr_result.scalars().all()
    return _serialize_objective(obj, krs)


@router.post(
    "/okrs/objectives/{objective_id}/key-results",
    response_model=KeyResultResponse,
    status_code=status.HTTP_201_CREATED,
)
async def add_key_result(
    objective_id: uuid.UUID,
    request: AddKeyResultRequest,
    company_id: CurrentCompanyId,
    db: DbSession,
) -> dict[str, Any]:
    result = await db.execute(
        select(OKRObjective).where(
            OKRObjective.id == objective_id,
            OKRObjective.company_id == company_id,
        )
    )
    obj = result.scalar_one_or_none()
    if obj is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Objective {objective_id} not found",
        )

    kr = OKRKeyResult(
        objective_id=objective_id,
        company_id=company_id,
        title=request.title,
        target_value=request.target_value,
        current_value=0.0,
        unit=request.unit,
        status="on_track",
    )
    db.add(kr)
    await db.commit()
    await db.refresh(kr)
    return {
        "id": kr.id,
        "objective_id": kr.objective_id,
        "title": kr.title,
        "target_value": kr.target_value,
        "current_value": kr.current_value,
        "unit": kr.unit,
        "status": kr.status,
        "updated_at": kr.updated_at.isoformat() if kr.updated_at else "",
    }


@router.put(
    "/okrs/key-results/{key_result_id}/progress",
    response_model=KeyResultResponse,
)
async def update_key_result_progress(
    key_result_id: uuid.UUID,
    request: UpdateProgressRequest,
    company_id: CurrentCompanyId,
    db: DbSession,
) -> dict[str, Any]:
    result = await db.execute(
        select(OKRKeyResult).where(
            OKRKeyResult.id == key_result_id,
            OKRKeyResult.company_id == company_id,
        )
    )
    kr = result.scalar_one_or_none()
    if kr is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"KeyResult {key_result_id} not found",
        )

    kr.current_value = request.current_value
    kr.updated_at = datetime.now(timezone.utc).replace(tzinfo=None)

    progress = kr.current_value / kr.target_value if kr.target_value > 0 else 0.0
    if progress >= 0.7:
        kr.status = "on_track"
    elif progress >= 0.3:
        kr.status = "at_risk"
    else:
        kr.status = "behind"

    await db.commit()
    await db.refresh(kr)
    return {
        "id": kr.id,
        "objective_id": kr.objective_id,
        "title": kr.title,
        "target_value": kr.target_value,
        "current_value": kr.current_value,
        "unit": kr.unit,
        "status": kr.status,
        "updated_at": kr.updated_at.isoformat() if kr.updated_at else "",
    }


@router.get("/okrs/at-risk", response_model=AtRiskResponse)
async def get_at_risk_objectives(
    company_id: CurrentCompanyId,
    db: DbSession,
    time_elapsed_fraction: float = 0.75,
) -> dict[str, Any]:
    result = await db.execute(
        select(OKRObjective).where(
            OKRObjective.company_id == company_id,
            OKRObjective.status == "active",
        )
    )
    objectives = result.scalars().all()

    at_risk = []
    for obj in objectives:
        if time_elapsed_fraction < 0.7:
            continue
        kr_result = await db.execute(
            select(OKRKeyResult).where(OKRKeyResult.objective_id == obj.id)
        )
        krs = kr_result.scalars().all()
        for kr in krs:
            progress = kr.current_value / kr.target_value if kr.target_value > 0 else 0.0
            if progress < 0.3:
                at_risk.append(_serialize_objective(obj, krs))
                break

    return {
        "at_risk_objectives": at_risk,
        "time_elapsed_fraction": time_elapsed_fraction,
    }
