"""Durable replay protection for inbound webhook deliveries.

Rows live in ``idempotency_records`` (company-scoped, FORCE RLS), keyed
``webhook:{trigger_id}:{Idempotency-Key}``, so one tenant's key never meets
another's and one trigger's key never meets another trigger's. The ledger stores
a payload hash, never the payload.

A delivery moves ``in_flight`` -> ``complete``. ``expires_at`` is the lease while
``in_flight`` and the retention deadline once ``complete``. It doubles as the
fencing token: a worker finishes or releases a claim only while ``expires_at``
still equals the value it wrote, so a worker whose lease was taken over cannot
record a second effect. No database transaction is open while the model runs;
:func:`begin`, :func:`finish` and :func:`release` each use their own short one.
"""

from __future__ import annotations

import enum
import json
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import delete, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from nexus.database import tenant_session
from nexus.models.idempotency import IdempotencyRecord

LEASE = timedelta(minutes=5)  # a crashed worker is reclaimable after this
RETENTION = timedelta(hours=24)  # a finished delivery replays for this long
ENDPOINT_PREFIX = "/api/v1/webhooks/"


class Outcome(enum.Enum):
    CLAIMED = "claimed"  # this request owns the delivery and must run it
    REPLAY = "replay"  # the delivery already finished; answer from the record
    CONFLICT = "conflict"  # same key, different payload
    BUSY = "busy"  # another worker holds a live lease; poll again


@dataclass(frozen=True)
class Claim:
    record_id: uuid.UUID
    fence: datetime


@dataclass(frozen=True)
class Begin:
    outcome: Outcome
    claim: Claim | None = None
    status_code: int | None = None
    body: str | None = None


def _now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def ledger_key(trigger_id: uuid.UUID, key: str) -> str:
    return f"webhook:{trigger_id}:{key}"


async def begin(
    company_id: uuid.UUID, trigger_id: uuid.UUID, key: str, request_hash: str
) -> Begin:
    """Claim the delivery, or report what already happened to it."""
    now = _now()
    fence = now + LEASE
    ikey = ledger_key(trigger_id, key)
    endpoint = f"{ENDPOINT_PREFIX}{trigger_id}"
    async with tenant_session(company_id) as session:
        # ponytail: purge per claim; move to a janitor past ~1e5 deliveries/day/tenant.
        await session.execute(
            delete(IdempotencyRecord).where(
                IdempotencyRecord.company_id == company_id,
                IdempotencyRecord.endpoint.startswith(ENDPOINT_PREFIX),
                (
                    (IdempotencyRecord.state == "complete") & (IdempotencyRecord.expires_at < now)
                )
                | (
                    (IdempotencyRecord.state == "in_flight")
                    & (IdempotencyRecord.expires_at < now - RETENTION)
                ),
            )
        )
        record = IdempotencyRecord(
            company_id=company_id,
            idem_key=ikey,
            endpoint=endpoint,
            request_hash=request_hash,
            state="in_flight",
            created_at=now,
            expires_at=fence,
        )
        record_id = record.id
        session.add(record)
        try:
            await session.commit()
            return Begin(Outcome.CLAIMED, claim=Claim(record_id, fence))
        except IntegrityError:
            await session.rollback()

        existing = (
            await session.execute(
                select(IdempotencyRecord).where(
                    IdempotencyRecord.company_id == company_id,
                    IdempotencyRecord.idem_key == ikey,
                )
            )
        ).scalars().first()
        if existing is None:  # released between our insert and our read
            return Begin(Outcome.BUSY)
        if existing.request_hash != request_hash:
            return Begin(Outcome.CONFLICT)
        if existing.state == "complete":
            return Begin(
                Outcome.REPLAY, status_code=existing.status_code, body=existing.response_body
            )
        if existing.expires_at > now:
            return Begin(Outcome.BUSY)

        # Lease expired: the worker crashed or stalled. Take over, fenced on the
        # old lease so only one contender wins.
        taken = await session.execute(
            update(IdempotencyRecord)
            .where(
                IdempotencyRecord.id == existing.id,
                IdempotencyRecord.state == "in_flight",
                IdempotencyRecord.expires_at == existing.expires_at,
            )
            .values(expires_at=fence)
        )
        await session.commit()
        if taken.rowcount == 1:
            return Begin(Outcome.CLAIMED, claim=Claim(existing.id, fence))
        return Begin(Outcome.BUSY)


async def finish(
    company_id: uuid.UUID,
    claim: Claim,
    effect: Callable[[AsyncSession], Awaitable[None]],
    status_code: int,
    body: dict[str, Any],
) -> bool:
    """Record the effect and complete the delivery in one transaction.

    ``False`` means the lease was lost; nothing was recorded and the caller must
    not report success for this claim.
    """
    async with tenant_session(company_id) as session:
        done = await session.execute(
            update(IdempotencyRecord)
            .where(
                IdempotencyRecord.id == claim.record_id,
                IdempotencyRecord.state == "in_flight",
                IdempotencyRecord.expires_at == claim.fence,
            )
            .values(
                state="complete",
                status_code=status_code,
                response_body=json.dumps(body, sort_keys=True, separators=(",", ":")),
                expires_at=_now() + RETENTION,
            )
        )
        if done.rowcount != 1:
            await session.rollback()
            return False
        await effect(session)
        await session.commit()
        return True


async def release(company_id: uuid.UUID, claim: Claim) -> None:
    """Give up an unfinished claim so a retry can run it at once."""
    async with tenant_session(company_id) as session:
        await session.execute(
            delete(IdempotencyRecord).where(
                IdempotencyRecord.id == claim.record_id,
                IdempotencyRecord.state == "in_flight",
                IdempotencyRecord.expires_at == claim.fence,
            )
        )
        await session.commit()
