"""Secret rotation API endpoints.

Provides routes for triggering secret rotation and viewing rotation status
from the FernetSecretBackend.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel

from nexus.governance.secret_backend import FernetSecretBackend, RotationPolicy

router = APIRouter(prefix="/api/v1/rotation", tags=["rotation"])

# Module-level backend instance (set during app startup or for testing)
_backend: FernetSecretBackend | None = None


def set_backend(backend: FernetSecretBackend) -> None:
    """Set the secret backend instance for rotation routes.

    Args:
        backend: The FernetSecretBackend to use for rotation operations.
    """
    global _backend
    _backend = backend


def _get_backend() -> FernetSecretBackend:
    """Get the configured secret backend.

    Returns:
        The configured FernetSecretBackend instance.

    Raises:
        HTTPException: If no backend is configured.
    """
    if _backend is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Secret backend not configured",
        )
    return _backend


# --- Request/Response Models ---


class RotationPolicyRequest(BaseModel):
    """Request body for setting a rotation policy."""

    ref: str
    max_age_days: int = 90
    auto_rotate: bool = False


class RotationStatusResponse(BaseModel):
    """Response model for rotation status of a secret."""

    ref: str
    needs_rotation: bool
    last_rotated: str | None = None
    policy_max_age_days: int | None = None
    policy_auto_rotate: bool | None = None


class RotationTriggerRequest(BaseModel):
    """Request body for triggering a secret rotation."""

    ref: str
    new_value: str


class RotationTriggerResponse(BaseModel):
    """Response model for a completed rotation."""

    ref: str
    rotated_at: str
    success: bool


# --- Routes ---


@router.post(
    "/policy",
    status_code=status.HTTP_200_OK,
)
async def set_rotation_policy(body: RotationPolicyRequest) -> dict[str, Any]:
    """Set rotation policy for a secret reference.

    Args:
        body: The rotation policy configuration.

    Returns:
        Confirmation of the policy being set.
    """
    backend = _get_backend()
    policy = RotationPolicy(
        max_age_days=body.max_age_days,
        auto_rotate=body.auto_rotate,
    )
    backend.set_rotation_policy(body.ref, policy)
    return {
        "ref": body.ref,
        "policy": {
            "max_age_days": policy.max_age_days,
            "auto_rotate": policy.auto_rotate,
        },
    }


@router.get(
    "/status/{ref}",
    response_model=RotationStatusResponse,
)
async def get_rotation_status(ref: str) -> RotationStatusResponse:
    """Get rotation status for a secret reference.

    Args:
        ref: The secret reference to check.

    Returns:
        Rotation status including whether rotation is needed.
    """
    backend = _get_backend()

    if not backend.has(ref):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Secret '{ref}' not found",
        )

    needs_rotation = backend.check_rotation_needed(ref)
    last_rotated_dt = backend.rotation_history.get(ref)
    policy = backend._rotation_policies.get(ref)

    return RotationStatusResponse(
        ref=ref,
        needs_rotation=needs_rotation,
        last_rotated=(
            last_rotated_dt.isoformat() if last_rotated_dt else None
        ),
        policy_max_age_days=policy.max_age_days if policy else None,
        policy_auto_rotate=policy.auto_rotate if policy else None,
    )


@router.post(
    "/trigger",
    response_model=RotationTriggerResponse,
    status_code=status.HTTP_200_OK,
)
async def trigger_rotation(
    body: RotationTriggerRequest,
) -> RotationTriggerResponse:
    """Trigger rotation of a specific secret.

    Stores the new value and records the rotation timestamp.

    Args:
        body: The rotation trigger request with new value.

    Returns:
        Confirmation of the rotation result.
    """
    backend = _get_backend()

    if not backend.has(body.ref):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Secret '{body.ref}' not found",
        )

    # Perform rotation: store new value and record timestamp
    success = backend.encrypt(body.ref, body.new_value)
    now = datetime.now(timezone.utc)

    if success:
        backend.rotation_history[body.ref] = now

    return RotationTriggerResponse(
        ref=body.ref,
        rotated_at=now.isoformat(),
        success=success,
    )


@router.get(
    "/needs-rotation",
    response_model=list[str],
)
async def list_needs_rotation() -> list[str]:
    """List all secrets that need rotation.

    Returns:
        List of secret references that need rotation.
    """
    backend = _get_backend()
    return backend.get_secrets_needing_rotation()
