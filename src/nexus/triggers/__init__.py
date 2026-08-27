"""Trigger/Aware system - proactive agent activation via cron, interval, webhook, and events."""

from nexus.triggers.webhook import WebhookHandler
from nexus.triggers.executor import TriggerExecutor
from nexus.triggers.types import (
    TriggerConfig,
    TriggerMode,
    InboundKind,
    is_auto_allowed,
    DEFAULT_TRIGGER_MODE,
)
from nexus.triggers.classifier import classify_inbound_kind
from nexus.triggers.context_trigger import (
    ContextRule,
    ContextTriggerConfig,
    DEFAULT_CONTEXT_TRIGGER,
)
from nexus.triggers.history import (
    TriggerHistoryEntry,
    TriggerHistoryLedger,
    TRIGGER_HISTORY_LIMIT,
)
from nexus.triggers.schema_validator import validate_against_schema

__all__ = [
    "WebhookHandler",
    "TriggerExecutor",
    "TriggerConfig",
    "TriggerMode",
    "InboundKind",
    "is_auto_allowed",
    "DEFAULT_TRIGGER_MODE",
    "classify_inbound_kind",
    "ContextRule",
    "ContextTriggerConfig",
    "DEFAULT_CONTEXT_TRIGGER",
    "TriggerHistoryEntry",
    "TriggerHistoryLedger",
    "TRIGGER_HISTORY_LIMIT",
    "validate_against_schema",
]
