"""A stored notification lists without error and keeps its metadata."""

import uuid

from fastapi.encoders import jsonable_encoder
from pydantic import TypeAdapter

from nexus.api.routes.notifications import NotificationResponse
from nexus.models.notification import Notification


def test_a_stored_notification_validates_and_keeps_its_metadata() -> None:
    row = Notification(
        company_id=uuid.uuid4(), title="t", notification_type="approval", module="hr",
        priority="high", notification_metadata={"approval_id": "a1"},
    )
    row.id = row.id or uuid.uuid4()
    # FastAPI validates a returned ORM row from its attributes, as the list route does.
    [out] = TypeAdapter(list[NotificationResponse]).validate_python([row], from_attributes=True)
    assert jsonable_encoder(out)["metadata"] == {"approval_id": "a1"}
