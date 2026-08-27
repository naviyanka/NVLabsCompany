"""Decision queue item database model for persistent triage state.

The queue itself is the existing `decision_queues` table
(`nexus.models.governance.DecisionQueue`); this table holds its items so the
triage lifecycle (pending/snoozed/decided/archived) survives a restart.
"""

import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlmodel import Field, SQLModel


class DecisionQueueItemRecord(SQLModel, table=True):
    """A persisted item in a decision queue.

    Mirrors the in-memory `DecisionQueueItem` dataclass. Indexed on
    `queue_id` and `status` so pending/overdue lookups are queries rather
    than full scans of a module-level dict.
    """

    __tablename__ = "decision_queue_items"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    queue_id: uuid.UUID = Field(foreign_key="decision_queues.id", index=True)
    company_id: uuid.UUID = Field(index=True)
    decision_id: uuid.UUID = Field(index=True)
    source_kind: str = Field(default="", max_length=50)
    source_id: uuid.UUID
    priority: int = Field(default=5, index=True)
    status: str = Field(default="pending", max_length=50, index=True)
    decision_outcome: Optional[str] = Field(default=None, max_length=255)
    decide_by: Optional[datetime] = Field(default=None)
    snoozed_until: Optional[datetime] = Field(default=None)
    needs_notification: bool = Field(default=True)
    notification_delivered: bool = Field(default=False)
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc).replace(tzinfo=None)
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc).replace(tzinfo=None)
    )
