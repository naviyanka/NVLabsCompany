"""Kill Switch database model for persistent state."""

import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlmodel import Field, SQLModel


class KillSwitchRecord(SQLModel, table=True):
    """Persistent record of a kill switch activation/deactivation.

    Each row represents one activation event. When deactivated, the
    `is_active` flag is set to False and `deactivated_at` is populated.
    Historical records are preserved for audit trail.
    """

    __tablename__ = "kill_switch_records"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    company_id: uuid.UUID = Field(index=True)
    is_active: bool = Field(default=True)
    reason: str = Field(default="", max_length=1000)
    activated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    activated_by: Optional[str] = Field(default=None, max_length=255)
    deactivated_at: Optional[datetime] = Field(default=None)
