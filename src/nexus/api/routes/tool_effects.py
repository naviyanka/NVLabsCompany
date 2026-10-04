"""Operator endpoints for tool effects that need a person's decision.

A non-idempotent tool call whose outcome is unknown is never rerun automatically (see
``nexus.tools.effects``). An administrator checks the external system and records whether the
effect happened; that decision, who made it and why are audited, and it is the only way such a
call becomes runnable again (``not_applied``) or returns its recorded outcome (``applied``).

Both routes need a signed-in human administrator. An API key or service principal with the
admin role, a run token and the auth-bypass principal are refused: the decision rests on a
person's check of an external system, and a person must be accountable for it.
"""

import uuid
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from nexus.api.deps import CurrentCompanyId, require_admin, require_user
from nexus.auth.principal import Principal
from nexus.tools import effects

router = APIRouter(tags=["tool-effects"])


class ResolveBody(BaseModel):
    """What the operator found in the external system."""

    outcome: Literal["applied", "not_applied"]
    reason: str = Field(min_length=1, max_length=500)
    note: str | None = Field(default=None, max_length=500)


# require_user runs first, so any non-human principal is refused before its role is read.
@router.get(
    "/api/v1/tool-effects/open",
    dependencies=[Depends(require_user), Depends(require_admin)],
)
async def list_open_effects(
    company_id: CurrentCompanyId, limit: int = 100, cursor: str | None = None
) -> dict[str, Any]:
    """One page of tool effects awaiting a decision: identifiers and states, never arguments.

    ``next_cursor`` is ``null`` on the last page; pass it back as ``cursor`` for the next.
    """
    try:
        return await effects.list_open(company_id, limit=max(1, min(limit, 500)), after=cursor)
    except ValueError:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Invalid cursor") from None


@router.post("/api/v1/tool-effects/{effect_id}/resolve")
async def resolve_effect(
    effect_id: uuid.UUID,
    body: ResolveBody,
    company_id: CurrentCompanyId,
    _human: Principal = Depends(require_user),
    principal: Principal = Depends(require_admin),
) -> dict[str, Any]:
    """Record whether an ambiguous tool effect was applied. Human admin only; audited."""
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
