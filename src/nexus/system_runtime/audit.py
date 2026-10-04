"""Content-free audit events for the system runtime.

An event carries a stable name and a fixed set of numeric or code fields. Anything else is
dropped, so a database URL, a password, a prompt, task or memory text, or a provider token
cannot reach a log line through this path even by mistake. A failing subscriber is counted
and ignored: auditing never aborts an operation.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable

from nexus.observability.metrics import record_system_runtime_event

logger = logging.getLogger("nexus.system_runtime.audit")

EVENTS = frozenset(
    {
        "runtime_started",
        "runtime_stopped",
        "runtime_refused",
        "op_started",
        "op_completed",
        "op_failed",
        "op_skipped_not_leader",
    }
)
# Only these fields are ever recorded. Values must be numbers or a short code.
FIELDS = frozenset(
    {
        "operation",
        "companies_seen",
        "companies_processed",
        "companies_failed",
        "batches",
        "duration_ms",
        "code",
        "ops_enabled",
    }
)

_subscribers: list[Callable[[dict], None]] = []


def subscribe(fn: Callable[[dict], None]) -> None:
    """Register an extra consumer (a test, or a SIEM forwarder)."""
    _subscribers.append(fn)


def clear_subscribers() -> None:
    _subscribers.clear()


def _clean(fields: dict) -> dict:
    out: dict = {}
    for key, value in fields.items():
        if key not in FIELDS:
            continue
        if isinstance(value, bool | int | float):
            out[key] = value
        elif isinstance(value, str) and len(value) <= 64 and value.replace("_", "").isalnum():
            out[key] = value
    return out


def emit(event: str, **fields: object) -> dict:
    """Record one audit event and return what was recorded."""
    if event not in EVENTS:
        raise ValueError(f"unknown audit event: {event!r}")
    entry = {"event": event, **_clean(fields)}
    logger.info("system_runtime_audit %s", json.dumps(entry, sort_keys=True))
    for fn in list(_subscribers):
        try:
            fn(dict(entry))
        except Exception:  # noqa: BLE001 - auditing must not abort the operation
            record_system_runtime_event("audit_subscriber_failure")
    return entry
