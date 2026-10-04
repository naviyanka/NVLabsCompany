"""Operator endpoints for tool effects that need a person's decision.

A non-idempotent tool call whose outcome is unknown is never rerun automatically (see
``nexus.tools.effects``). An administrator checks the external system and records whether the
effect happened; that decision, who made it and why are audited, and it is the only way such a
call becomes runnable again (``not_applied``) or returns its recorded outcome (``applied``).
"""

import uuid
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from nexus.api.deps import CurrentCompanyId, require_admin
from nexus.auth.principal import Principal
from nexus.tools import effects

router = APIRouter(tags=["tool-effects"])


class ResolveBody(BaseModel):
    """What the operator found in the external system."""

    outcome: Literal["applied", "not_applied"]
    reason: str = Field(min_length=1, max_length=500)
    note: str | None = Field(default=None, max_length=500)


@router.get("/api/v1/tool-effects/open", dependencies=[Depends(require_admin)])
async def list_open_effects(company_id: CurrentCompanyId, limit: int = 100) -> list[dict[str, Any]]:
    """Tool effects awaiting a decision: identifiers and states only, never arguments."""
    return await effects.list_open(company_id, limit=max(1, min(limit, 500)))


@router.post("/api/v1/tool-effects/{effect_id}/resolve")
async def resolve_effect(
    effect_id: uuid.UUID,
    body: ResolveBody,
    company_id: CurrentCompanyId,
    principal: Principal = Depends(require_admin),
) -> dict[str, Any]:
    """Record whether an ambiguous tool effect was applied. Admin only; audited."""
    try:
        return await effects.resolve_manual_recovery(
            company_id,
            effect_id,
            body.outcome,
            actor=principal.display_name,
            reason=body.reason,
            note=body.note,
        )
    except LookupError:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Tool effect not found") from None
    except effects.EffectStateError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from None
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from None
