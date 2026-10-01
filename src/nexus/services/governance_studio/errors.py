"""Stable error shape for every Governance Studio route: ``{"code", "message"}``."""

from __future__ import annotations

from typing import Any, NoReturn

from fastapi import HTTPException

from nexus.services import ceo_service


def fail(status_code: int, code: str, message: str) -> NoReturn:
    raise HTTPException(status_code=status_code, detail={"code": code, "message": message})


def require_reader(principal: Any) -> None:
    """A person (any role). Agents and API keys never see governance state."""
    if not ceo_service.is_human(principal):
        fail(403, "HUMAN_REQUIRED", "Governance Studio is for people")


def can_write(principal: Any) -> bool:
    """The one write predicate: a human administrator of the caller's own company.

    The principal is built by the auth middleware from the session, the user's active flag
    and the membership row (re-read on every request), never from anything the browser sends.
    ``require_admin_human`` and ``GET /governance/me`` both call this, so the screen and the
    runtime cannot disagree.
    """
    return ceo_service.is_human(principal) and principal.role == "admin"


def require_admin_human(principal: Any) -> None:
    """A human administrator, for every write."""
    if not can_write(principal):
        fail(403, "HUMAN_ADMIN_REQUIRED", "Only a human administrator may change governance")
