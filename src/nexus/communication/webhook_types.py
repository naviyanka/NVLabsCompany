"""Webhook type definitions for inbound HTTP endpoint handling."""

from pydantic import BaseModel, Field


class WebhookEndpoint(BaseModel):
    """Configuration for a single webhook endpoint."""

    id: str
    name: str
    secret: str
    schema_: str = Field(default="{}", alias="schema")
    enabled: bool = True

    model_config = {"populate_by_name": True}


class WebhookInbound(BaseModel):
    """Validated inbound message extracted from a webhook POST body."""

    message: str
    title: str | None = None
    kind: str | None = None
    from_: str | None = Field(default=None, alias="from")

    model_config = {"populate_by_name": True}


class WebhookDispatch(BaseModel):
    """Result returned by the on_message handler after dispatching work."""

    token: str
    task_id: str | None = None
    pending: bool


class WebhookTaskStatus(BaseModel):
    """Public status of a task associated with a capability token."""

    status: str
    title: str
    result: str | None = None
