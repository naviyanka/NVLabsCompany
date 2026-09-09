"""LLM Connection model — a user-created inference endpoint.

A Connection is a generic, vendor-neutral record pointing NEXUS at any
OpenAI- or Anthropic-compatible endpoint (a self-hosted gateway, Ollama,
vLLM, OpenRouter, ...). NEXUS ships two wire-format adapters and zero vendor
adapters: a Connection is resolved to the matching wire-format adapter and
its ``base_url`` is injected as the per-session ``api_base``.

The raw API key is NEVER stored here. ``api_key_ref`` / ``mgmt_key_ref`` are
foreign keys into ``secrets.id``; values are resolved through the secret
backend at dispatch time and never serialized back to a client.
"""

import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlmodel import Field, SQLModel

# Supported wire formats. A Connection speaks exactly one of these; it maps to
# the "openai" or "anthropic" adapter registry key at resolution time.
WIRE_FORMATS = ("openai", "anthropic")


class LLMConnection(SQLModel, table=True):
    """A tenant-scoped inference endpoint the user added."""

    __tablename__ = "llm_connections"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    company_id: uuid.UUID = Field(foreign_key="companies.id", index=True)
    name: str = Field(max_length=255)
    base_url: str = Field(max_length=1024)
    # "openai" | "anthropic" — validated at the API boundary against WIRE_FORMATS.
    wire_format: str = Field(max_length=50)
    # Secret-backend name of the inference key (used for /v1/*). Resolved via
    # SecretBackend.decrypt(ref) at dispatch time; never the raw key.
    api_key_ref: Optional[str] = Field(default=None, max_length=255)
    # Secret-backend name of the management key (used for gateway /api/* in
    # Tier 1). NULL means Tier 1 features render as unavailable; inference
    # still works.
    mgmt_key_ref: Optional[str] = Field(default=None, max_length=255)
    is_active: bool = Field(default=True)
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc).replace(tzinfo=None)
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc).replace(tzinfo=None)
    )
