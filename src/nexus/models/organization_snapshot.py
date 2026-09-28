"""Organization snapshot: a precomputed, versioned picture of one company.

``organization_snapshots`` holds immutable versions. Each row is the
canonical JSON payload built by :mod:`nexus.services.org_snapshot`, its
SHA-256 and the time it was generated. A version is never updated; a newer
picture is a new row with the next ``version``.

``organization_snapshot_state`` is one mutable row per company: whether the
company changed since the last version (``dirty_since``), whether a
generation is running (``generating_until``, a lease) and the last refresh
error. Keeping it apart from the versions means a failed refresh never
touches the last good snapshot.
"""

import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import JSON, Column, Text, UniqueConstraint
from sqlmodel import Field, SQLModel


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)  # noqa: UP017


class OrganizationSnapshot(SQLModel, table=True):
    """One immutable version of a company's snapshot."""

    __tablename__ = "organization_snapshots"
    # The version constraint doubles as the latest-version index.
    __table_args__ = (
        UniqueConstraint("company_id", "version", name="uq_organization_snapshots_version"),
        UniqueConstraint(
            "company_id", "generation_key", name="uq_organization_snapshots_generation"
        ),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    company_id: uuid.UUID = Field(foreign_key="companies.id")
    version: int
    schema_version: int
    # "<schema>:<payload hash>:<previous version>": the same content on top of
    # the same predecessor is one version, however many workers race for it.
    generation_key: str = Field(max_length=128)
    payload_hash: str = Field(max_length=64)
    generated_at: datetime = Field(default_factory=_utcnow)
    data_as_of: datetime | None = None
    payload: dict[str, Any] = Field(sa_column=Column(JSON, nullable=False))


class OrganizationSnapshotState(SQLModel, table=True):
    """Refresh bookkeeping for one company's snapshot."""

    __tablename__ = "organization_snapshot_state"

    company_id: uuid.UUID = Field(foreign_key="companies.id", primary_key=True)
    # First and latest change seen since the last successful generation.
    dirty_since: datetime | None = None
    last_dirty_at: datetime | None = None
    # A generation in progress holds this lease; one per company.
    generating_until: datetime | None = None
    generating_by: str | None = Field(default=None, max_length=64)
    # Last generation that confirmed the latest version (new or unchanged).
    verified_at: datetime | None = None
    # Last generation started, successful or not: paces reconciliation.
    attempted_at: datetime | None = None
    last_error: str | None = Field(default=None, sa_column=Column(Text))
    last_error_at: datetime | None = None
