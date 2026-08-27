"""NEXUS FastAPI application entry point."""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from nexus import __version__
from nexus.api.middleware import GovernanceMiddleware
from nexus.auth.middleware import AuthenticationMiddleware
from nexus.api.routes.adapters import router as adapters_router
from nexus.api.routes.archetypes import router as archetypes_router
from nexus.api.routes.chat import router as chat_router
from nexus.api.routes.hiring import router as hiring_router
from nexus.api.routes.providers import router as providers_router
from nexus.api.routes.agents import router as agents_router
from nexus.api.routes.approvals import router as approvals_router
from nexus.api.routes.auth import router as auth_router
from nexus.api.routes.budgets import router as budgets_router
from nexus.api.routes.communication import router as communication_router
from nexus.api.routes.companies import router as companies_router
from nexus.api.routes.control import router as control_router
from nexus.api.routes.company_sim import router as company_sim_router
from nexus.api.routes.degradation import router as degradation_router
from nexus.api.routes.events import router as events_router
from nexus.api.routes.okr import router as okr_router
from nexus.api.routes.plaza import router as plaza_router
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
from nexus.api.routes.ws import router as ws_router
from nexus.api.routes.notifications import router as notifications_router
from nexus.api.routes.dashboard import router as dashboard_router
from nexus.api.routes.activity import router as activity_router
from nexus.api.routes.agent_logs import router as agent_logs_router
from nexus.api.routes.settings import router as settings_router
from nexus.api.routes.pipelines import router as pipelines_router
from nexus.api.routes.repositories import router as repositories_router
from nexus.api.routes.api_keys import router as api_keys_router
from nexus.api.routes.profile import router as profile_router
from nexus.api.routes.audit import router as audit_router
from nexus.api.routes.memory_global import router as memory_global_router
from nexus.api.routes.hr import router as hr_router
from nexus.api.routes.departments import router as departments_router
from nexus.api.routes.workspaces import router as workspaces_router
from nexus.api.routes.nodes import router as nodes_router
from nexus.api.routes.slack_events import router as slack_events_router
from nexus.api.routes.sso import router as sso_router
from nexus.api.routes.scim import router as scim_router
from nexus.api.routes.telegram_bot import router as telegram_bot_router
from nexus.api.routes.agent_profiling import router as agent_profiling_router
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

    # Startup: create tables only for SQLite dev databases. PostgreSQL and
    # other production databases are managed exclusively through Alembic
    # migrations (`alembic upgrade head` — docker-compose runs it before
    # uvicorn), so schema drift cannot hide between create_all and the
    # migration history.
    from sqlmodel import SQLModel
    import nexus.models  # noqa: F401 - register all models
    if settings.database_url.startswith("sqlite"):
        async with engine.begin() as conn:
            await conn.run_sync(SQLModel.metadata.create_all)

    # Seed default company for the dashboard
    from nexus.models._time import utcnow

    from sqlalchemy import select

    from nexus.models.company import Company
    default_company_id = uuid.UUID("00000000-0000-4000-8000-000000000001")
    async with async_session_factory() as session:
        result = await session.execute(
            select(Company).where(Company.id == default_company_id)
        )
        if result.scalar_one_or_none() is None:
            now = utcnow()
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

    # Seed budget tracker with company budget data
    try:
        from nexus.api.middleware import _budget_tracker, _policy_cache
        from nexus.models.company import Company as CompanyModel
        from nexus.models.policy import Policy as PolicyModel

        async with async_session_factory() as session:
            from sqlalchemy import select as sa_select
            result = await session.execute(sa_select(CompanyModel))
            for company in result.scalars().all():
                _budget_tracker.set_budget(
                    company.id,
                    company.budget_monthly_cents,
                    company.spent_monthly_cents,
                )

            # Load active policies into cache
            policy_result = await session.execute(
                sa_select(PolicyModel).where(PolicyModel.enabled == True)  # noqa: E712
            )
            for policy in policy_result.scalars().all():
                if policy.company_id not in _policy_cache:
                    _policy_cache[policy.company_id] = []
                _policy_cache[policy.company_id].append({
                    "name": policy.name,
                    "rules": policy.rules,
                    "priority": policy.priority,
                })

        _logger.info("Budget tracker and policy cache seeded from DB")
    except Exception as exc:
        _logger = logging.getLogger(__name__)
        _logger.warning("Could not seed budget/policy data: %s", exc)

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

    # Secret vault: DB-backed by default so stored secrets survive a restart
    try:
        from nexus.api.routes.rotation import set_backend
        from nexus.governance.secret_backend import make_secret_backend

        secret_backend = make_secret_backend(async_session_factory)
        app.state.secret_backend = secret_backend
        set_backend(secret_backend)
        _logger.info(
            "Secret backend initialized (%s)", type(secret_backend).__name__
        )
    except Exception as exc:
        _logger.warning("Could not initialize secret backend: %s", exc)

    # Initialize Plugin SDK (empty registry - plugins are not auto-loaded)
    from nexus.plugins import PluginRegistry, HookManager

    hook_manager = HookManager()
    plugin_registry = PluginRegistry(hook_manager=hook_manager)
    app.state.hook_manager = hook_manager
    app.state.plugin_registry = plugin_registry
    _logger.info("Plugin SDK initialized (registry empty, awaiting plugin loads)")

    # Run configuration validation (non-blocking, logs warnings only)
    from nexus.config_validator import validate_config
    await validate_config()

    # Reclaim heartbeat runs whose process died while we were down (Phase 1.3.4)
    try:
        from nexus.runtime.heartbeat_persistent import PersistentHeartbeatService
        reclaimed = await PersistentHeartbeatService(async_session_factory).reclaim_orphans()
        if reclaimed:
            _logger.warning("Reclaimed %d orphaned heartbeat run(s)", len(reclaimed))
    except Exception as exc:
        _logger.warning("Heartbeat orphan reclaim failed: %s", exc)

    # Start the background scheduler for cron/schedule triggers
    from nexus.runtime.scheduler import start_scheduler, stop_scheduler
    await start_scheduler(async_session_factory)

    # Start the autonomous orchestration coordinator
    from nexus.runtime.orchestrator import start_orchestrator, stop_orchestrator
    await start_orchestrator(async_session_factory)

    # The watchdog patrol rides the scheduler tick (see runtime/scheduler.py); it
    # detects stuck agents and silently stalled runs, and files a human decision
    # for stalls it cannot explain (Phase 1.4). Only shutdown needs wiring here.
    from nexus.runtime.watchdog_service import stop_watchdog

    # Register event bridge handlers (connects EventBus → orchestration)
    try:
        from nexus.runtime.event_bridge import register_event_handlers
        from nexus.communication.event_bus import EventBus
        app.state.event_bus = EventBus(company_id=default_company_id)
        register_event_handlers(app.state.event_bus)
    except Exception as exc:
        _logger.warning("Event bridge registration failed: %s", exc)

    yield

    # Shutdown: stop orchestrator, stop scheduler, persist state, close connections
    await stop_orchestrator()
    await stop_scheduler()
    await stop_watchdog()

    # Flush accumulated budget spend to DB
    try:
        from nexus.api.middleware import _budget_tracker
        from nexus.models.company import Company as CompanyModel
        from sqlalchemy import update as sa_update

        async with async_session_factory() as flush_db:
            for cid, amount in list(_budget_tracker._pending_spend.items()):
                if amount > 0:
                    await flush_db.execute(
                        sa_update(CompanyModel)
                        .where(CompanyModel.id == cid)
                        .values(spent_monthly_cents=CompanyModel.spent_monthly_cents + amount)
                    )
            await flush_db.commit()
            _budget_tracker._pending_spend.clear()
        logging.getLogger(__name__).info("Budget spend flushed to DB")
    except Exception as exc:
        logging.getLogger(__name__).warning("Budget flush failed: %s", exc)

    import logging
    shutdown_logger = logging.getLogger(__name__)
    shutdown_logger.info("NEXUS shutdown initiated - persisting state...")

    # Note: telemetry metrics are NOT reset on shutdown. The Prometheus
    # scrape model collects metrics externally; clearing them here would
    # destroy unscraped data. registry.reset() is a test-only helper.

    # Persist ControlRegistry state using the runtime singleton
    try:
        from nexus.api.routes.control import get_registry

        cr = get_registry()
        cr._persist()
        shutdown_logger.info("ControlRegistry state persisted")
    except Exception as exc:
        shutdown_logger.warning(
            "Failed to persist ControlRegistry state: %s", exc
        )

    shutdown_logger.info("NEXUS shutdown complete - all resources released")


app = FastAPI(
    title="NEXUS",
    description="""# NEXUS — Autonomous AI Company Operating System

A full-stack platform for managing autonomous AI agents as employees within a virtual company.

## Features
- **Agents** — Create, manage, wake, pause, and terminate AI agents with different LLM backends
- **Tasks & Goals** — Assign work, track progress, manage OKRs
- **Pipelines** — Multi-step automated workflows with execution history
- **Memory** — 3-temperature memory system (hot/warm/cold) for agent knowledge
- **Governance** — Rate limiting, kill switch, RBAC, audit logging, budget enforcement
- **Evolution** — Agent self-improvement proposals, evaluation, and promotion
- **Communication** — Inter-agent messaging, groups, events
- **Knowledge Base** — Versioned documentation with RAG search
- **Meetings** — Scheduled meetings with minutes and action items
- **Notifications** — Real-time event notifications with preferences
- **Settings** — Company-wide configuration management
- **Repositories** — Connected git repository management
- **Secrets** — Encrypted secret storage with access control

## Authentication

Every endpoint outside `/health`, `/metrics` and `/api/v1/auth` requires an
authenticated caller. Two credentials are accepted:

- **Session cookie** — `POST /api/v1/auth/login` with an email and password sets
  an httpOnly session cookie. Browser clients must also send the `X-CSRF-Token`
  header on any request that changes state; its value is the `nv_csrf` cookie
  set alongside the session.
- **API key** — `Authorization: Bearer nv_...`. A key is issued for one company
  and carries its own role, so it can be given less authority than the
  administrator who created it. API keys are exempt from the CSRF check because
  a browser will not attach them to a cross-site request on its own.

The caller's company is taken from their credential, never from a request
header. `X-Company-Id` is ignored unless `AUTH_ENABLED=false`, which exists only
to keep local development and the existing test suite working.

The first administrator is created by `python -m nexus.auth.bootstrap` or by
`POST /api/v1/auth/setup`, which only answers while the user table is empty.
Afterwards, accounts are created by invitation.
""",
    version=__version__,
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_tags=[
        {"name": "health", "description": "Health checks and readiness probes"},
        {"name": "auth", "description": "Login, sessions, invites, and first-run setup"},
        {"name": "agents", "description": "Agent CRUD and lifecycle operations (wake/pause/heartbeat)"},
        {"name": "tasks", "description": "Task management — create, assign, update status"},
        {"name": "goals", "description": "Strategic goals and OKR tracking"},
        {"name": "pipelines", "description": "Multi-step pipeline definitions and execution"},
        {"name": "notifications", "description": "Notification delivery, preferences, and read status"},
        {"name": "dashboard", "description": "Aggregated stats and daily metrics for overview"},
        {"name": "activity", "description": "Company-wide and per-agent activity feeds"},
        {"name": "agent-logs", "description": "Agent execution logs and summaries"},
        {"name": "settings", "description": "Company-wide configuration settings"},
        {"name": "repositories", "description": "Connected git repository management"},
        {"name": "memory", "description": "Agent memory store, search, and retrieval"},
        {"name": "knowledge", "description": "Knowledge base pages, RAG search, experience records"},
        {"name": "evolution", "description": "Agent self-improvement proposals and evaluations"},
        {"name": "communication", "description": "Inter-agent messaging, groups, and events"},
        {"name": "meetings", "description": "Meeting scheduling, minutes, and action items"},
        {"name": "budgets", "description": "Budget policies and usage tracking"},
        {"name": "approvals", "description": "Governance approval workflows"},
        {"name": "adapters", "description": "LLM adapter types and CLI backend detection"},
        {"name": "skills", "description": "Skill registry and agent-skill assignments"},
        {"name": "tools", "description": "Tool registry and agent tool access control"},
        {"name": "triggers", "description": "Scheduled and webhook-triggered agent activations"},
        {"name": "workflows", "description": "Company and task workflow orchestration"},
        {"name": "secrets", "description": "Encrypted secret storage with versioning"},
        {"name": "policies", "description": "Policy engine rules and evaluation"},
        {"name": "incidents", "description": "Incident tracking and resolution"},
        {"name": "companies", "description": "Company/tenant management"},
        {"name": "identity", "description": "Agent persona and soul templates"},
    ],
)

# Middleware stack. Starlette wraps each new middleware around the previous
# one, so the LAST call below is the OUTERMOST layer and runs first.
#
# Resulting request order:
#   CORS -> RequestID -> Metrics -> APIVersion -> Authentication -> Governance
#
# Two constraints fix this order. Authentication must sit outside Governance,
# because Governance reads the caller's company from the resolved principal to
# pick a kill switch, policy set and budget. CORS must be outermost, because a
# 401 or 403 produced by an inner layer never reaches the CORS layer otherwise
# and the browser reports it as a network error instead of the real status.

# Governance: policy enforcement, audit logging, rate limit headers
app.add_middleware(GovernanceMiddleware)

# Authentication: resolves the request's principal from cookie or API key
app.add_middleware(AuthenticationMiddleware)

# API version middleware for X-API-Version header
app.add_middleware(APIVersionMiddleware, version="1.0")

# Metrics middleware for HTTP request tracking
app.add_middleware(MetricsMiddleware)

# Request ID middleware
app.add_middleware(RequestIDMiddleware)

# CORS middleware - restrict to configured origins. Credentials are allowed
# because the dashboard authenticates with a cookie, which also means the
# origin list must stay explicit: "*" is rejected by browsers alongside
# credentials, and would defeat the purpose here anyway.
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in settings.cors_origins.split(",") if o.strip()],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include route modules
app.include_router(health_router)
app.include_router(metrics_router)
app.include_router(auth_router)
app.include_router(companies_router)
app.include_router(control_router)
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
app.include_router(ws_router)
app.include_router(notifications_router)
app.include_router(dashboard_router)
app.include_router(activity_router)
app.include_router(agent_logs_router)
app.include_router(settings_router)
app.include_router(pipelines_router)
app.include_router(repositories_router)
app.include_router(api_keys_router)
app.include_router(profile_router)
app.include_router(audit_router)
app.include_router(memory_global_router)
app.include_router(hr_router)
app.include_router(departments_router)
app.include_router(events_router)
app.include_router(okr_router)
app.include_router(archetypes_router)
app.include_router(providers_router)
app.include_router(hiring_router)
app.include_router(chat_router)
app.include_router(plaza_router)
app.include_router(workspaces_router)
app.include_router(nodes_router)
app.include_router(slack_events_router)
app.include_router(sso_router)
app.include_router(scim_router)
app.include_router(telegram_bot_router)
app.include_router(agent_profiling_router)
