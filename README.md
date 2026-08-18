# NEXUS - Autonomous AI Company Operating System

NEXUS transforms multiple open-source agent frameworks into a unified system that operates as a real autonomous AI company. It combines organizational structure, durable agent execution, persistent identity, proactive behavior, and self-evolution into a single coherent platform.

## Architecture

NEXUS is built on:

- **Python 3.12+** with **FastAPI** (async throughout)
- **SQLModel** (SQLAlchemy + Pydantic) for type-safe database models
- **PostgreSQL** as the primary database
- **Redis** for caching, pub/sub, and hot-tier memory
- **Alembic** for database migrations
- **Docker Compose** for local development

For detailed architecture documentation, see the `docs/` directory:
- `docs/architecture/nexus-v1.md` - Full v1 architecture plan
- `docs/architecture/component-matrix.md` - Component source mapping
- `docs/repository-analysis/` - Source repository analysis

## Quick Start

### Prerequisites

- Docker and Docker Compose
- Python 3.12+ (for local development without Docker)

### Start with Docker Compose

```bash
docker-compose up -d
```

This starts:
- **PostgreSQL 16** on port 5432
- **Redis 7** on port 6379
- **NEXUS server** on port 8000

The API will be available at http://localhost:8000. Check health at http://localhost:8000/health.

### Local Development (without Docker)

1. Create a virtual environment:
```bash
python -m venv .venv
source .venv/bin/activate
```

2. Install dependencies:
```bash
pip install -e ".[dev]"
```

3. Set environment variables (or create a `.env` file):
```bash
export DATABASE_URL=postgresql+asyncpg://nexus:nexus_dev_password@localhost:5432/nexus
export REDIS_URL=redis://localhost:6379/0
export SECRET_KEY=your-secret-key
```

4. Run database migrations:
```bash
alembic upgrade head
```

5. Start the server:
```bash
uvicorn nexus.main:app --reload --host 0.0.0.0 --port 8000
```

## Project Structure

```
src/nexus/
  __init__.py          # Package with version
  main.py              # FastAPI app setup (lifespan, middleware, routers)
  config.py            # Settings via pydantic-settings
  database.py          # Async SQLAlchemy engine and session factory
  models/              # SQLModel table definitions
    __init__.py        # Re-exports all models for Alembic discovery
    company.py         # Company, CompanyMembership, Department, Team
    agent.py           # Agent (the core autonomous employee)
    task.py            # Goal, Project, Task
    budget.py          # BudgetPolicy, CostEvent
    governance.py      # Approval, Decision, DecisionQueue, AuditLog
    skill.py           # Skill, AgentSkill
    tool.py            # Tool, ToolAccess
    memory.py          # MemoryRecord (3-temperature memory)
    trigger.py         # Trigger, TriggerExecution
  api/
    __init__.py
    deps.py            # Common dependencies (session, company context)
    routes/
      __init__.py
      health.py        # GET /health endpoint

alembic/               # Database migration infrastructure
  env.py               # Async migration environment
  versions/            # Migration scripts (auto-generated)

docs/                  # Architecture documentation (DO NOT DELETE)
  architecture/        # System design documents
  repository-analysis/ # Source repo analysis
```

## Key Concepts

### Multi-Tenancy

Every record belongs to a `company_id`. All queries are scoped to the current tenant. Companies are fully isolated.

### Agents

Agents are autonomous AI employees with:
- Persistent identity (soul description, memory namespace)
- Configurable runtime (adapter type, model, tools)
- Organizational placement (department, team, manager)
- Budget constraints and performance tracking

### Governance

All significant operations go through governance:
- **Approvals** gate high-risk actions
- **Decisions** collect options for human/auto resolution
- **Budget policies** enforce spending limits
- **Audit log** records every mutation

### 3-Temperature Memory

- **Hot** (Redis): Frequently accessed working memory
- **Warm** (PostgreSQL): Standard persistent memory
- **Cold** (Archive): Rarely accessed historical memory

## API Documentation

When the server is running, visit:
- Swagger UI: http://localhost:8000/docs
- ReDoc: http://localhost:8000/redoc

## License

MIT
