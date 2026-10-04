"""Entry point of the privileged system runtime.

    python -m nexus.system_runtime              run the operations (default)
    python -m nexus.system_runtime status       print the published status (no database)
    python -m nexus.system_runtime healthcheck  exit 0 if the runtime ticked recently

The runtime refuses to start unless it holds an explicit ``SYSTEM_DATABASE_URL`` and
``DATABASE_URL`` that are different identities, checked against the live PostgreSQL role
attributes. It never falls back from one to the other. It serves no network port.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import signal
import sys
import tempfile
import time
from pathlib import Path

from nexus.observability.metrics import record_system_runtime_event

logger = logging.getLogger(__name__)

HEARTBEAT_MAX_AGE_SECONDS = 180
# The scheduler loop wakes this often; each operation then checks its own interval.
LOOP_INTERVAL_SECONDS = 5.0


def _heartbeat_path() -> Path:
    default = Path(tempfile.gettempdir()) / "nexus-system-runtime.alive"
    return Path(os.environ.get("SYSTEM_RUNTIME_HEARTBEAT_FILE", str(default)))


def _refuse(code: str, message: str) -> int:
    from nexus.system_runtime import audit

    audit.emit("runtime_refused", code=code)
    print(f"{code}: {message}", file=sys.stderr)
    return 2


async def _preflight() -> tuple[object, int]:
    """Validate environment and roles. Returns (system_engine, 0) or (None, exit code)."""
    from nexus.config_validator import ConfigurationError, enforce_no_migration_credential
    from nexus.system_runtime import db

    try:
        enforce_no_migration_credential()
    except ConfigurationError as exc:
        return None, _refuse(exc.code, "MIGRATION_DATABASE_URL must not be set here.")

    system_url = os.environ.get(db.SYSTEM_URL_VARIABLE, "")
    app_url = os.environ.get("DATABASE_URL", "")
    if not system_url:
        record_system_runtime_event("missing_credential")
        return None, _refuse("SYSTEM_CREDENTIAL_MISSING", "SYSTEM_DATABASE_URL is not set.")
    if not app_url:
        record_system_runtime_event("missing_credential")
        return None, _refuse("APP_CREDENTIAL_MISSING", "DATABASE_URL is not set.")
    if system_url == app_url:
        return None, _refuse(
            "SYSTEM_URL_EQUALS_DATABASE_URL", "SYSTEM_DATABASE_URL and DATABASE_URL are identical."
        )
    if system_url.startswith("sqlite") or app_url.startswith("sqlite"):
        return None, _refuse("POSTGRES_REQUIRED", "The system runtime needs PostgreSQL.")

    from nexus.database import engine as app_engine

    system_engine = db.bootstrap()
    try:
        problems = await db.validate_roles(app_engine, system_engine)
    except Exception as exc:  # noqa: BLE001 - never echo the driver message (it can hold a DSN)
        await db.dispose()
        record_system_runtime_event("role_validation_failure")
        return None, _refuse(
            "ROLE_VALIDATION_UNAVAILABLE", f"Could not check roles ({type(exc).__name__})."
        )
    if problems:
        await db.dispose()
        record_system_runtime_event("role_validation_failure")
        return None, _refuse(
            problems[0], "Database roles do not match the contract: " + ", ".join(problems)
        )
    return system_engine, 0


async def run() -> int:
    from nexus.runtime import scheduler
    from nexus.system_runtime import audit, db
    from nexus.system_runtime.ops import OPERATIONS
    from nexus.system_runtime.runner import SystemRuntime

    engine, code = await _preflight()
    if engine is None:
        return code

    runtime = SystemRuntime(lambda name: lambda: db.discovery_session(name))
    heartbeat = _heartbeat_path()

    async def tick() -> None:
        await runtime.tick()
        heartbeat.write_text(str(time.time()))

    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(sig, stop.set)
        except NotImplementedError:  # Windows: fall back to the plain handler
            signal.signal(sig, lambda *_: loop.call_soon_threadsafe(stop.set))

    audit.emit("runtime_started", ops_enabled=len(OPERATIONS))
    await scheduler.start_scheduler(ticks=[(None, tick)], interval=LOOP_INTERVAL_SECONDS)
    try:
        await stop.wait()
    finally:
        await scheduler.stop_scheduler()
        await db.dispose()
        audit.emit("runtime_stopped")
    return 0


async def status() -> int:
    from nexus.system_runtime import status as published

    print(json.dumps(await published.read(), indent=2, sort_keys=True))
    return 0


def healthcheck() -> int:
    try:
        age = time.time() - float(_heartbeat_path().read_text())
    except (OSError, ValueError):
        return 1
    return 0 if age < HEARTBEAT_MAX_AGE_SECONDS else 1


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO)
    args = sys.argv[1:] if argv is None else argv
    command = args[0] if args else "run"
    if command == "run":
        return asyncio.run(run())
    if command == "status":
        return asyncio.run(status())
    if command == "healthcheck":
        return healthcheck()
    print(f"unknown command: {command}", file=sys.stderr)
    return 64


if __name__ == "__main__":
    sys.exit(main())
