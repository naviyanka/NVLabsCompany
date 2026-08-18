"""NEXUS FastAPI application entry point."""

from contextlib import asynccontextmanager
from collections.abc import AsyncGenerator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from nexus import __version__
from nexus.api.routes.health import router as health_router
from nexus.api.routes.companies import router as companies_router
from nexus.api.routes.agents import router as agents_router
from nexus.api.routes.tasks import router as tasks_router
from nexus.api.routes.goals import router as goals_router
from nexus.api.routes.skills import router as skills_router
from nexus.api.routes.tools import router as tools_router
from nexus.api.routes.approvals import router as approvals_router
from nexus.api.routes.budgets import router as budgets_router
from nexus.api.routes.memory import router as memory_router
from nexus.api.routes.triggers import router as triggers_router


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Application lifespan handler for startup and shutdown events."""
    # Startup: initialize connections, caches, etc.
    yield
    # Shutdown: close connections, flush buffers, etc.


app = FastAPI(
    title="NEXUS",
    description="Autonomous AI Company Operating System",
    version=__version__,
    lifespan=lifespan,
)

# CORS middleware for development
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include route modules
app.include_router(health_router)
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
