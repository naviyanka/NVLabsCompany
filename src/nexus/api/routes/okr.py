"""OKR Management API routes.

Provides REST endpoints for managing Objectives and Key Results,
including creation, progress updates, and risk detection.
"""

import uuid
from typing import Any

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from nexus.api.deps import CurrentCompanyId
from nexus.company.okr import OKRManager

router = APIRouter(tags=["okr"])

# In-memory OKR manager instances per company.
# NOTE: This is an in-memory store and will not persist across restarts or
# share state across multiple workers (e.g., uvicorn --workers > 1). This is
# consistent with other services in this codebase that use in-memory state.
# A persistent backend (database) should replace this for production use.
_managers: dict[uuid.UUID, OKRManager] = {}


def _get_manager(company_id: uuid.UUID) -> OKRManager:
    """Get or create an OKR manager for a company.

    Args:
        company_id: The company UUID to scope the manager.

    Returns:
        OKRManager instance for the given company.
    """
    if company_id not in _managers:
        _managers[company_id] = OKRManager(company_id=company_id)
    return _managers[company_id]


# --- Request/Response Models ---


class CreateObjectiveRequest(BaseModel):
    """Request body for creating an objective."""

    title: str = Field(..., description="Title of the objective")
    description: str = Field("", description="Detailed description")
    owner_agent_id: uuid.UUID = Field(..., description="Agent responsible for this objective")
    time_frame: str = Field("Q1 2025", description="Time frame for completion")


class AddKeyResultRequest(BaseModel):
    """Request body for adding a key result."""

    title: str = Field(..., description="Title of the key result")
    target_value: float = Field(..., description="Target value to achieve")
    unit: str = Field("percent", description="Unit of measurement")


class UpdateProgressRequest(BaseModel):
    """Request body for updating key result progress."""

    current_value: float = Field(..., description="Current progress value")


class KeyResultResponse(BaseModel):
    """Response model for a key result."""

    id: uuid.UUID
    objective_id: uuid.UUID
    title: str
    target_value: float
    current_value: float
    unit: str
    status: str
    updated_at: str


class ObjectiveResponse(BaseModel):
    """Response model for an objective."""

    id: uuid.UUID
    title: str
    description: str
    owner_agent_id: uuid.UUID
    time_frame: str
    status: str
    key_results: list[KeyResultResponse]
    created_at: str
    progress: float = 0.0


class ObjectiveListResponse(BaseModel):
    """Response model for listing objectives."""

    objectives: list[ObjectiveResponse]


class AtRiskResponse(BaseModel):
    """Response model for at-risk objectives."""

    at_risk_objectives: list[ObjectiveResponse]
    time_elapsed_fraction: float


def _serialize_objective(
    objective: Any, manager: OKRManager
) -> dict[str, Any]:
    """Serialize an Objective to a response dict.

    Args:
        objective: The Objective instance to serialize.
        manager: The OKRManager for progress computation.

    Returns:
        Dict suitable for ObjectiveResponse.
    """
    key_results = [
        {
            "id": kr.id,
            "objective_id": kr.objective_id,
            "title": kr.title,
            "target_value": kr.target_value,
            "current_value": kr.current_value,
            "unit": kr.unit,
            "status": kr.status,
            "updated_at": kr.updated_at.isoformat(),
        }
        for kr in objective.key_results
    ]

    progress = manager.compute_objective_progress(objective.id)

    return {
        "id": objective.id,
        "title": objective.title,
        "description": objective.description,
        "owner_agent_id": objective.owner_agent_id,
        "time_frame": objective.time_frame,
        "status": objective.status,
        "key_results": key_results,
        "created_at": objective.created_at.isoformat(),
        "progress": progress,
    }


# --- Route Handlers ---


@router.post(
    "/okrs/objectives",
    response_model=ObjectiveResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_objective(
    request: CreateObjectiveRequest,
    company_id: CurrentCompanyId,
) -> dict[str, Any]:
    """Create a new objective.

    Args:
        request: The objective creation request body.
        company_id: Authenticated company UUID from header.

    Returns:
        The created objective with initial progress.
    """
    manager = _get_manager(company_id)
    objective = manager.create_objective(
        title=request.title,
        description=request.description,
        owner_agent_id=request.owner_agent_id,
        time_frame=request.time_frame,
    )
    return _serialize_objective(objective, manager)


@router.get("/okrs/objectives", response_model=ObjectiveListResponse)
async def list_objectives(
    company_id: CurrentCompanyId,
) -> dict[str, Any]:
    """List all objectives for the company.

    Args:
        company_id: Authenticated company UUID from header.

    Returns:
        List of all objectives with progress information.
    """
    manager = _get_manager(company_id)
    objectives = manager.get_company_okrs()
    return {
        "objectives": [
            _serialize_objective(obj, manager) for obj in objectives
        ]
    }


@router.get("/okrs/objectives/{objective_id}", response_model=ObjectiveResponse)
async def get_objective(
    objective_id: uuid.UUID,
    company_id: CurrentCompanyId,
) -> dict[str, Any]:
    """Get a single objective with progress.

    Args:
        objective_id: UUID of the objective to retrieve.
        company_id: Authenticated company UUID from header.

    Returns:
        The objective with current progress.

    Raises:
        HTTPException: If the objective is not found.
    """
    manager = _get_manager(company_id)
    objective = manager.get_objective(objective_id)
    if objective is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Objective {objective_id} not found",
        )
    return _serialize_objective(objective, manager)


@router.post(
    "/okrs/objectives/{objective_id}/key-results",
    response_model=KeyResultResponse,
    status_code=status.HTTP_201_CREATED,
)
async def add_key_result(
    objective_id: uuid.UUID,
    request: AddKeyResultRequest,
    company_id: CurrentCompanyId,
) -> dict[str, Any]:
    """Add a key result to an objective.

    Args:
        objective_id: UUID of the parent objective.
        request: The key result creation request body.
        company_id: Authenticated company UUID from header.

    Returns:
        The created key result.

    Raises:
        HTTPException: If the objective is not found.
    """
    manager = _get_manager(company_id)
    try:
        kr = manager.add_key_result(
            objective_id=objective_id,
            title=request.title,
            target_value=request.target_value,
            unit=request.unit,
        )
    except KeyError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Objective {objective_id} not found",
        )

    return {
        "id": kr.id,
        "objective_id": kr.objective_id,
        "title": kr.title,
        "target_value": kr.target_value,
        "current_value": kr.current_value,
        "unit": kr.unit,
        "status": kr.status,
        "updated_at": kr.updated_at.isoformat(),
    }


@router.put(
    "/okrs/key-results/{key_result_id}/progress",
    response_model=KeyResultResponse,
)
async def update_key_result_progress(
    key_result_id: uuid.UUID,
    request: UpdateProgressRequest,
    company_id: CurrentCompanyId,
) -> dict[str, Any]:
    """Update the progress of a key result.

    Args:
        key_result_id: UUID of the key result to update.
        request: The progress update request body.
        company_id: Authenticated company UUID from header.

    Returns:
        The updated key result.

    Raises:
        HTTPException: If the key result is not found.
    """
    manager = _get_manager(company_id)
    try:
        kr = manager.update_progress(
            key_result_id=key_result_id,
            current_value=request.current_value,
        )
    except KeyError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"KeyResult {key_result_id} not found",
        )

    return {
        "id": kr.id,
        "objective_id": kr.objective_id,
        "title": kr.title,
        "target_value": kr.target_value,
        "current_value": kr.current_value,
        "unit": kr.unit,
        "status": kr.status,
        "updated_at": kr.updated_at.isoformat(),
    }


@router.get("/okrs/at-risk", response_model=AtRiskResponse)
async def get_at_risk_objectives(
    company_id: CurrentCompanyId,
    time_elapsed_fraction: float = 0.75,
) -> dict[str, Any]:
    """Get objectives that are at risk of not being met.

    Args:
        company_id: Authenticated company UUID from header.
        time_elapsed_fraction: Fraction of time elapsed (default 0.75).

    Returns:
        List of at-risk objectives and the time fraction used.
    """
    manager = _get_manager(company_id)
    at_risk = manager.detect_at_risk_objectives(
        time_elapsed_fraction=time_elapsed_fraction
    )
    return {
        "at_risk_objectives": [
            _serialize_objective(obj, manager) for obj in at_risk
        ],
        "time_elapsed_fraction": time_elapsed_fraction,
    }
