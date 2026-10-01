"""Audit helper for Governance Studio writes.

Writes fail closed: if the audit entry cannot be persisted, the change is not committed.
Only ids, names and a bounded reason go in; never arguments, prompts, memory or secrets.
"""

from __future__ import annotations

import uuid
from typing import Any

from nexus.governance.audit_service import record_audit

REASON_MAX = 500


def actor_of(principal: Any) -> str:
    """The stable label stored as requester, approver and audit actor."""
    return principal.display_name


def clip(text: str | None) -> str:
    return (text or "").strip()[:REASON_MAX]


async def audit(
    db: Any,
    company_id: uuid.UUID,
    principal: Any,
    action: str,
    resource_type: str,
    resource_id: Any,
    details: dict[str, Any] | None = None,
) -> None:
    await record_audit(
        company_id,
        f"governance.{action}",
        actor_type="user",
        actor_id=actor_of(principal),
        resource_type=resource_type,
        resource_id=str(resource_id),
        details=details,
        db=db,
        raise_on_error=True,
    )
