"""Policy drafts, versions, publish and rollback.

The active rules stay in ``tool_policies``: there is one engine and one rule table. A version
is an immutable snapshot of that rule set taken when a draft is published or rolled back.

- Publish is one short transaction with no outside call. It checks the draft's base version
  against the current one, marks the draft published with a conditional UPDATE, swaps the active
  rules and inserts the next version. ``(company_id, version_number)`` is unique, so of two
  publishes racing from the same base the second fails and rolls back as a whole.
- A change that **loosens** access (see :func:`is_loosening`) is published by someone other than
  its author, and by a listed reviewer when the draft names any.
- Rolling back to a version that tightens, or does not change, access applies at once. One that
  would loosen access becomes a draft and goes through review like any other change.
"""

from __future__ import annotations

import uuid
from typing import Any

from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, update
from sqlalchemy.exc import IntegrityError
from sqlmodel import select

from nexus.models.governance_studio import GovernancePolicyDraft, GovernancePolicyVersion
from nexus.models.tool import ToolPolicy
from nexus.services.governance_studio import risk
from nexus.services.governance_studio.audit import actor_of, audit, clip
from nexus.services.governance_studio.errors import fail
from nexus.services.governance_studio.rules import MAX_RULES, RuleBody, to_dict
from nexus.tools import governance_overlay as overlay

PAGE_MAX = 100
_COMPARED = ("effect", "priority", "conditions")


class DraftBody(BaseModel):
    rules: list[RuleBody] = Field(max_length=MAX_RULES)
    reason: str = Field(min_length=5, max_length=500)
    ticket_ref: str | None = Field(default=None, max_length=255)
    reviewers: list[str] = Field(default_factory=list, max_length=10)

    @field_validator("rules")
    @classmethod
    def _unique_names(cls, value: list[RuleBody]) -> list[RuleBody]:
        names = [r.name for r in value]
        if len(names) != len(set(names)):
            raise ValueError("rule names must be unique")
        return value


class PublishBody(BaseModel):
    reason: str | None = Field(default=None, max_length=500)


class RollbackBody(BaseModel):
    reason: str = Field(min_length=5, max_length=500)
    expected_version: int = Field(ge=0)


# --- reading -------------------------------------------------------------------------------


async def live_rules(db: Any, company_id: uuid.UUID) -> list[dict[str, Any]]:
    rows = (
        await db.execute(
            select(ToolPolicy)
            .where(ToolPolicy.company_id == company_id, ToolPolicy.is_active == True)  # noqa: E712
            .order_by(ToolPolicy.priority, ToolPolicy.name, ToolPolicy.id)
        )
    ).scalars().all()
    return [
        {"name": r.name, "effect": r.effect, "priority": r.priority,
         "description": r.description, "conditions": r.conditions or {}}
        for r in rows
    ]


async def current_version(db: Any, company_id: uuid.UUID) -> int:
    top = (
        await db.execute(
            select(func.max(GovernancePolicyVersion.version_number)).where(
                GovernancePolicyVersion.company_id == company_id
            )
        )
    ).scalar()
    return top or 0


def _keyed(items: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for item in items:
        key, n = item["name"], 1
        while key in out:
            n += 1
            key = f"{item['name']}#{n}"
        out[key] = item
    return out


def diff(old: list[dict[str, Any]], new: list[dict[str, Any]]) -> dict[str, Any]:
    a, b = _keyed(old), _keyed(new)
    changed = []
    for name in a.keys() & b.keys():
        fields = [f for f in _COMPARED if a[name].get(f) != b[name].get(f)]
        if fields:
            changed.append({"name": name, "fields": fields, "before": a[name], "after": b[name]})
    return {
        "added": [b[n] for n in b.keys() - a.keys()],
        "removed": [a[n] for n in a.keys() - b.keys()],
        "changed": changed,
    }


def is_loosening(d: dict[str, Any]) -> bool:
    """Conservative: a new allow, a dropped deny, or any edit to a rule's effect or scope."""
    return (
        any(r["effect"] == "allow" for r in d["added"])
        or any(r["effect"] == "deny" for r in d["removed"])
        or bool(d["changed"])
    )


def _date(value: Any) -> str | None:
    return value.isoformat() if value else None


def draft_view(
    d: GovernancePolicyDraft, live: list[dict[str, Any]], version: int
) -> dict[str, Any]:
    change = diff(live, d.proposed_rules)
    return {
        "id": str(d.id),
        "status": d.status,
        "base_version": d.base_version,
        "stale": d.status == "draft" and d.base_version != version,
        "rules": d.proposed_rules,
        "reason": d.reason,
        "ticket_ref": d.ticket_ref,
        "created_by": d.created_by,
        "reviewers": d.reviewers,
        "published_version": d.published_version,
        "created_at": _date(d.created_at),
        "updated_at": _date(d.updated_at),
        "diff": change,
        "loosens": is_loosening(change),
        "findings": risk.rule_findings(
            d.proposed_rules, author=d.created_by, reviewers=d.reviewers
        ),
    }


def version_view(v: GovernancePolicyVersion, *, rules_too: bool = False) -> dict[str, Any]:
    out = {
        "version": v.version_number,
        "status": v.status,
        "base_version": v.base_version,
        "published_by": v.published_by,
        "reason": v.reason,
        "rollback_of": v.rollback_of,
        "rule_count": len(v.rules_snapshot),
        "created_at": _date(v.created_at),
    }
    if rules_too:
        out["rules"] = v.rules_snapshot
    return out


async def overview(db: Any, company_id: uuid.UUID) -> dict[str, Any]:
    version = await current_version(db, company_id)
    return {"version": version, "rules": await live_rules(db, company_id)}


async def _draft(db: Any, company_id: uuid.UUID, draft_id: uuid.UUID) -> GovernancePolicyDraft:
    row = (
        await db.execute(
            select(GovernancePolicyDraft).where(
                GovernancePolicyDraft.id == draft_id, GovernancePolicyDraft.company_id == company_id
            )
        )
    ).scalars().first()
    if row is None:
        fail(404, "DRAFT_NOT_FOUND", "No such draft")
    return row


async def _view(db: Any, company_id: uuid.UUID, d: GovernancePolicyDraft) -> dict[str, Any]:
    return draft_view(d, await live_rules(db, company_id), await current_version(db, company_id))


async def get_draft(db: Any, company_id: uuid.UUID, draft_id: uuid.UUID) -> dict[str, Any]:
    return await _view(db, company_id, await _draft(db, company_id, draft_id))


async def list_drafts(
    db: Any, company_id: uuid.UUID, *, status: str | None, limit: int, offset: int
) -> dict[str, Any]:
    query = select(GovernancePolicyDraft).where(GovernancePolicyDraft.company_id == company_id)
    if status:
        query = query.where(GovernancePolicyDraft.status == status)
    rows = (
        await db.execute(
            query.order_by(GovernancePolicyDraft.updated_at.desc(), GovernancePolicyDraft.id)
            .limit(limit)
            .offset(offset)
        )
    ).scalars().all()
    live, version = await live_rules(db, company_id), await current_version(db, company_id)
    return {"items": [draft_view(d, live, version) for d in rows], "limit": limit, "offset": offset}


async def list_versions(
    db: Any, company_id: uuid.UUID, *, limit: int, offset: int
) -> dict[str, Any]:
    rows = (
        await db.execute(
            select(GovernancePolicyVersion)
            .where(GovernancePolicyVersion.company_id == company_id)
            .order_by(GovernancePolicyVersion.version_number.desc())
            .limit(limit)
            .offset(offset)
        )
    ).scalars().all()
    return {"items": [version_view(v) for v in rows], "limit": limit, "offset": offset}


async def _version(db: Any, company_id: uuid.UUID, number: int) -> GovernancePolicyVersion:
    row = (
        await db.execute(
            select(GovernancePolicyVersion).where(
                GovernancePolicyVersion.company_id == company_id,
                GovernancePolicyVersion.version_number == number,
            )
        )
    ).scalars().first()
    if row is None:
        fail(404, "VERSION_NOT_FOUND", "No such version")
    return row


async def get_version(db: Any, company_id: uuid.UUID, number: int) -> dict[str, Any]:
    v = await _version(db, company_id, number)
    previous = (
        await _version(db, company_id, number - 1) if number > 1 else None
    )
    out = version_view(v, rules_too=True)
    out["diff_from_previous"] = diff(previous.rules_snapshot if previous else [], v.rules_snapshot)
    return out


# --- drafts --------------------------------------------------------------------------------


async def create_draft(
    db: Any, company_id: uuid.UUID, principal: Any, body: DraftBody
) -> dict[str, Any]:
    draft = GovernancePolicyDraft(
        company_id=company_id,
        base_version=await current_version(db, company_id),
        proposed_rules=[to_dict(r) for r in body.rules],
        reason=clip(body.reason),
        ticket_ref=body.ticket_ref,
        created_by=actor_of(principal),
        reviewers=body.reviewers,
    )
    db.add(draft)
    await db.flush()
    await audit(db, company_id, principal, "draft.created", "policy_draft", draft.id,
                {"base_version": draft.base_version, "reason": draft.reason,
                 "rule_count": len(draft.proposed_rules)})
    return await _view(db, company_id, draft)


async def update_draft(
    db: Any, company_id: uuid.UUID, principal: Any, draft_id: uuid.UUID, body: DraftBody
) -> dict[str, Any]:
    draft = await _draft(db, company_id, draft_id)
    if draft.status != "draft":
        fail(409, "DRAFT_NOT_OPEN", "Only an open draft can be edited")
    if draft.created_by != actor_of(principal):
        fail(403, "NOT_AUTHOR", "Only the author edits a draft; propose a new one instead")
    draft.proposed_rules = [to_dict(r) for r in body.rules]
    draft.reason = clip(body.reason)
    draft.ticket_ref, draft.reviewers = body.ticket_ref, body.reviewers
    draft.updated_at = overlay.now()
    db.add(draft)
    await db.flush()
    await audit(db, company_id, principal, "draft.updated", "policy_draft", draft.id,
                {"rule_count": len(draft.proposed_rules)})
    return await _view(db, company_id, draft)


async def discard_draft(
    db: Any, company_id: uuid.UUID, principal: Any, draft_id: uuid.UUID
) -> dict[str, Any]:
    result = await db.execute(
        update(GovernancePolicyDraft)
        .where(
            GovernancePolicyDraft.id == draft_id,
            GovernancePolicyDraft.company_id == company_id,
            GovernancePolicyDraft.status == "draft",
        )
        .values(status="discarded", updated_at=overlay.now())
    )
    if not result.rowcount:
        await _draft(db, company_id, draft_id)
        fail(409, "DRAFT_NOT_OPEN", "Only an open draft can be discarded")
    await audit(db, company_id, principal, "draft.discarded", "policy_draft", draft_id)
    return await get_draft(db, company_id, draft_id)


# --- publish and rollback ------------------------------------------------------------------


async def _apply(
    db: Any,
    company_id: uuid.UUID,
    principal: Any,
    *,
    new_rules: list[dict[str, Any]],
    base_version: int,
    live: list[dict[str, Any]],
    reason: str,
    rollback_of: int | None = None,
) -> int:
    """Swap the active rules and record the next version. The caller commits."""
    who = actor_of(principal)
    number = base_version + 1
    try:
        await db.execute(
            update(GovernancePolicyVersion)
            .where(GovernancePolicyVersion.company_id == company_id,
                   GovernancePolicyVersion.status == "active")
            .values(status="superseded")
        )
        if base_version == 0:
            db.add(GovernancePolicyVersion(
                company_id=company_id, version_number=1, status="superseded", rules_snapshot=live,
                base_version=0, published_by=who, reason="Rules in force before the first publish",
            ))
            number = 2
        db.add(GovernancePolicyVersion(
            company_id=company_id, version_number=number, status="active", rules_snapshot=new_rules,
            base_version=base_version, published_by=who, reason=reason, rollback_of=rollback_of,
        ))
        await db.execute(
            update(ToolPolicy)
            .where(ToolPolicy.company_id == company_id, ToolPolicy.is_active == True)  # noqa: E712
            .values(is_active=False, updated_at=overlay.now())
        )
        for r in new_rules:
            db.add(ToolPolicy(
                company_id=company_id, name=r["name"], description=r.get("description"),
                priority=r["priority"], effect=r["effect"], conditions=r["conditions"],
            ))
        await db.flush()
    except IntegrityError:
        await db.rollback()
        fail(409, "VERSION_CONFLICT", "Another publish landed first; review the new version")
    return number


def _check_reviewer(d: dict[str, Any], author: str, publisher: str, reviewers: list[str]) -> None:
    if not is_loosening(d):
        return
    if publisher == author:
        fail(403, "REVIEWER_REQUIRED",
             "This change loosens access, so someone other than its author must publish it")
    if reviewers and publisher not in reviewers:
        fail(403, "NOT_A_REVIEWER", "Only a reviewer named on the draft may publish this change")


async def publish(
    db: Any, company_id: uuid.UUID, principal: Any, draft_id: uuid.UUID, body: PublishBody
) -> dict[str, Any]:
    draft = await _draft(db, company_id, draft_id)
    if draft.status != "draft":
        fail(409, "DRAFT_NOT_OPEN", "This draft is already published or discarded")
    base = await current_version(db, company_id)
    if draft.base_version != base:
        fail(409, "STALE_BASE", f"The rules moved to version {base}; rebase this draft on it")
    live = await live_rules(db, company_id)
    change = diff(live, draft.proposed_rules)
    _check_reviewer(change, draft.created_by, actor_of(principal), draft.reviewers)
    claimed = await db.execute(
        update(GovernancePolicyDraft)
        .where(GovernancePolicyDraft.id == draft.id, GovernancePolicyDraft.company_id == company_id,
               GovernancePolicyDraft.status == "draft")
        .values(status="published", updated_at=overlay.now())
    )
    if not claimed.rowcount:
        fail(409, "DRAFT_NOT_OPEN", "This draft was published or discarded meanwhile")
    number = await _apply(
        db, company_id, principal, new_rules=draft.proposed_rules, base_version=base, live=live,
        reason=clip(body.reason) or draft.reason,
    )
    await db.execute(
        update(GovernancePolicyDraft)
        .where(GovernancePolicyDraft.id == draft.id)
        .values(published_version=number)
    )
    findings = risk.rule_findings(draft.proposed_rules, author=draft.created_by,
                                  reviewers=draft.reviewers)
    await audit(db, company_id, principal, "policy.published", "policy_version", number,
                {"draft_id": str(draft.id), "base_version": base, "loosens": is_loosening(change),
                 "findings": sorted({f["code"] for f in findings}), "reason": clip(body.reason)})
    await db.refresh(draft)
    return await _view(db, company_id, draft)


async def rollback(
    db: Any, company_id: uuid.UUID, principal: Any, number: int, body: RollbackBody
) -> dict[str, Any]:
    target = await _version(db, company_id, number)
    base = await current_version(db, company_id)
    if body.expected_version != base:
        fail(409, "STALE_BASE", f"The rules moved to version {base}; check before rolling back")
    live = await live_rules(db, company_id)
    change = diff(live, target.rules_snapshot)
    if is_loosening(change):
        draft = GovernancePolicyDraft(
            company_id=company_id, base_version=base, proposed_rules=target.rules_snapshot,
            reason=clip(f"Rollback to version {number}: {body.reason}"),
            created_by=actor_of(principal),
        )
        db.add(draft)
        await db.flush()
        await audit(db, company_id, principal, "rollback.drafted", "policy_draft", draft.id,
                    {"target_version": number, "base_version": base, "reason": clip(body.reason)})
        return {"applied": False, "draft": await _view(db, company_id, draft)}
    new = await _apply(
        db, company_id, principal, new_rules=target.rules_snapshot, base_version=base, live=live,
        reason=clip(body.reason), rollback_of=number,
    )
    await audit(db, company_id, principal, "policy.rolled_back", "policy_version", new,
                {"target_version": number, "base_version": base, "reason": clip(body.reason)})
    return {"applied": True, "version": new}
