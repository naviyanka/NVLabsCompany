import uuid
from datetime import datetime, timezone
from typing import Optional
from sqlalchemy import UniqueConstraint
from sqlmodel import Field, SQLModel

class IdempotencyRecord(SQLModel, table=True):
    """Stores executed mutating requests for idempotency protection (F3)."""

    __tablename__ = "idempotency_records"
    __table_args__ = (
        UniqueConstraint("company_id", "idem_key", name="uq_idempotency_company_key"),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    company_id: uuid.UUID = Field(foreign_key="companies.id", index=True)
    idem_key: str = Field(index=True, max_length=255)
    endpoint: str = Field(max_length=512)
    request_hash: str = Field(max_length=64)  # sha256 hex
    response_body: Optional[str] = Field(default=None)  # serialized json
    status_code: Optional[int] = Field(default=None)
    state: str = Field(default="in_flight", max_length=32)  # in_flight | complete
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc).replace(tzinfo=None)
    )
    expires_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc).replace(tzinfo=None)
    )
