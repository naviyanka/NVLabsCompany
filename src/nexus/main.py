"""NEXUS FastAPI application entry point."""

import os
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from datetime import UTC

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from nexus import __version__
from nexus.api.middleware import GovernanceMiddleware
from nexus.api.routes.adapters import router as adapters_router
from nexus.api.routes.agents import router as agents_router
from nexus.api.routes.approvals import router as approvals_router
from nexus.api.routes.budgets import router as budgets_router
from nexus.api.routes.communication import router as communication_router
from nexus.api.routes.companies import router as companies_router
from nexus.api.routes.company_sim import router as company_sim_router
from nexus.api.routes.degradation import router as degradation_router
from nexus.api.routes.evolution import router as evolution_router
from nexus.api.routes.goals import router as goals_router
from nexus.api.routes.health import router as health_router
from nexus.api.routes.identity import router as identity_router
from nexus.api.routes.incidents import router as incidents_router
from nexus.api.routes.knowledge import router as knowledge_router
from nexus.api.routes.meetings import router as meetings_router
from nexus.api.routes.memory import router as memory_router
from nexus.api.routes.policies import router as policies_router
from nexus.api.routes.rotation import router as rotation_router
from nexus.api.routes.secrets import router as secrets_router
from nexus.api.routes.skills import router as skills_router
from nexus.api.routes.tasks import router as tasks_router
from nexus.api.routes.tools import router as tools_router
from nexus.api.routes.triggers import router as triggers_router
from nexus.api.routes.workflows import router as workflows_router
from nexus.api.versioning import APIVersionMiddleware
from nexus.config import settings
from nexus.logging_config import RequestIDMiddleware, configure_logging
from nexus.telemetry import MetricsMiddleware, metrics_router

# Configure structured JSON logging at module level
configure_logging()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Application lifespan handler for startup and shutdown events."""
    import uuid

    from nexus.config import settings
    from nexus.database import async_session_factory, engine

    # Startup: create tables if using SQLite (for local dev convenience)
    if settings.database_url.startswith("sqlite"):
        from sqlmodel import SQLModel

        import nexus.models  # noqa: F401 - register all models
        async with engine.begin() as conn:
            await conn.run_sync(SQLModel.metadata.create_all)

    # Seed default company for the dashboard
    from datetime import datetime

    from sqlalchemy import select

    from nexus.models.company import Company
    default_company_id = uuid.UUID("00000000-0000-4000-8000-000000000001")
    async with async_session_factory() as session:
        result = await session.execute(
            select(Company).where(Company.id == default_company_id)
        )
        if result.scalar_one_or_none() is None:
            now = datetime.now(UTC)
            company = Company(
                id=default_company_id,
                name="NVLabs",
                description="Default development company",
                status="active",
                created_at=now,
                updated_at=now,
            )
            session.add(company)
            await session.commit()

    # Seed demo data (agents, tasks, etc.)
    from nexus.demo.seed import seed_database
    async with async_session_factory() as session:
        counts = await seed_database(session)
        if any(v > 0 for v in counts.values()):
            import logging
            logging.getLogger(__name__).info("Seeded demo data: %s", counts)

    # Load governance state from DB (kill switches, circuit breakers)
    import logging
    _logger = logging.getLogger(__name__)
    try:
        from nexus.governance.persistent_circuit_breaker import PersistentCircuitBreaker
        from nexus.governance.persistent_kill_switch import PersistentKillSwitch

        persistent_ks = PersistentKillSwitch(async_session_factory)
        loaded_count = await persistent_ks.load_active()

        persistent_cb = PersistentCircuitBreaker(async_session_factory)
        cb_states = await persistent_cb.load_state()

        _logger.info(
            "Governance state loaded from DB (%d active kill switches, "
            "%d open circuit breakers)",
            loaded_count,
            len(cb_states),
        )
    except Exception as exc:
        _logger.warning(
            "Could not load governance state from DB (table may not exist yet): %s",
            exc,
        )

    # Run configuration validation (non-blocking, logs warnings only)
    from nexus.config_validator import validate_config
    await validate_config()

    yield

    # Shutdown: flush telemetry, persist state, close connections
    import logging
    shutdown_logger = logging.getLogger(__name__)
    shutdown_logger.info("NEXUS shutdown initiated - flushing state...")

    # Flush telemetry metrics
    try:
        from nexus.telemetry import registry as telemetry_registry
        telemetry_registry.reset()
        shutdown_logger.info("Telemetry metrics flushed")
    except Exception as exc:
        shutdown_logger.warning("Failed to flush telemetry: %s", exc)

    # Persist ControlRegistry state if persistence is configured
    try:
        from pathlib import Path

        from nexus.governance.control_registry import ControlRegistry

        persist_path_env = os.environ.get("NEXUS_CONTROL_STATE_PATH", "")
        if persist_path_env:
            cr = ControlRegistry(persist_path=Path(persist_path_env))
            cr._persist()
            shutdown_logger.info(
                "ControlRegistry state persisted to %s", persist_path_env
            )
    except Exception as exc:
        shutdown_logger.warning(
            "Failed to persist ControlRegistry state: %s", exc
        )

    # Log Redis connection status
    try:
        redis_url = settings.redis_url
        if redis_url:
            shutdown_logger.info(
                "Redis connection closing (url=%s)",
                redis_url.split("@")[-1] if "@" in redis_url else redis_url,
            )
    except Exception as exc:
        shutdown_logger.warning("Error during Redis shutdown logging: %s", exc)

    shutdown_logger.info("NEXUS shutdown complete - all resources released")


app = FastAPI(
    title="NEXUS",
    description="Autonomous AI Company Operating System",
    version=__version__,
    lifespan=lifespan,
)

# CORS middleware - restrict to configured origins
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in settings.cors_origins.split(",")],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Governance middleware for policy enforcement, audit logging, and rate limiting
app.add_middleware(GovernanceMiddleware)

# API version middleware for X-API-Version header
app.add_middleware(APIVersionMiddleware, version="1.0")

# Metrics middleware for HTTP request tracking
app.add_middleware(MetricsMiddleware)

# Request ID middleware (added last = outermost in ASGI stack)
app.add_middleware(RequestIDMiddleware)

# Include route modules
app.include_router(health_router)
app.include_router(metrics_router)
app.include_router(companies_router)
app.include_router(agents_router)
app.include_router(tasks_router)
app.include_router(goals_router)
app.include_router(skills_router)
app.include_router(tools_router)
app.include_router(approvals_router)
app.include_router(budgets_router)
app.include_router(memory_router)
app.include_router(triggers_router)
app.include_router(communication_router)
app.include_router(knowledge_router)
app.include_router(meetings_router)
app.include_router(company_sim_router)
app.include_router(evolution_router)
app.include_router(adapters_router)
app.include_router(workflows_router)
app.include_router(identity_router)
app.include_router(policies_router)
app.include_router(secrets_router)
app.include_router(incidents_router)
app.include_router(degradation_router)
app.include_router(rotation_router)
