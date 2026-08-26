# NEXUS — Installation & Setup Guide

This guide provides comprehensive instructions for installing, configuring, and running **NEXUS — The Autonomous AI Company Operating System**.

---

## Table of Contents

- [Prerequisites](#prerequisites)
- [Quick Start with Docker Compose](#quick-start-with-docker-compose)
- [Manual Local Development Setup](#manual-local-development-setup)
  - [1. Clone Repository & Setup Virtual Environment](#1-clone-repository--setup-virtual-environment)
  - [2. Install Backend Dependencies](#2-install-backend-dependencies)
  - [3. Configure Environment Variables](#3-configure-environment-variables)
  - [4. Database Migrations (Alembic)](#4-database-migrations-alembic)
  - [5. Start Backend FastAPI Server](#5-start-backend-fastapi-server)
  - [6. Setup & Start React Dashboard](#6-setup--start-react-dashboard)
- [First-Time Administrator Setup](#first-time-administrator-setup)
- [Desktop Launcher & Daemon Server](#desktop-launcher--daemon-server)
- [Environment Variables Reference](#environment-variables-reference)
- [Troubleshooting & FAQs](#troubleshooting--faqs)

---

## Prerequisites

Before installing NEXUS, ensure your environment meets the following requirements:

| Component | Minimum Version | Recommended | Notes |
| :--- | :--- | :--- | :--- |
| **Python** | 3.12+ | 3.12.x | Async-native runtime |
| **Node.js** | 18.x+ | 20.x LTS | For React Dashboard & Desktop server |
| **npm** | 9.x+ | 10.x+ | Package manager |
| **Docker** | 24.x+ | Latest | For containerized datastores |
| **Docker Compose** | v2.x+ | Latest | Multi-container management |
| **PostgreSQL** | 16.x | 16.x | Primary relational database |
| **Redis** | 7.x | 7.x | Rate limiting, pub/sub, hot-tier memory |

---

## Quick Start with Docker Compose

The fastest way to get NEXUS running locally with PostgreSQL, Redis, and the FastAPI backend is using Docker Compose.

```bash
# 1. Clone the repository
git clone https://github.com/naviyanka/NVLabsCompany.git
cd NVLabsCompany

# 2. Start all services in detached mode
docker-compose up -d
```

### Container Status & Ports

Docker Compose launches the following services:

- **NEXUS Server**: `http://localhost:8000`
- **PostgreSQL 16**: `localhost:5432` (`database: nexus`, `user: nexus`, `password: nexus_dev_password`)
- **Redis 7**: `localhost:6379`

To verify the backend health check:
```bash
curl http://localhost:8000/health
```

To stop the containers:
```bash
docker-compose down
```

---

## Manual Local Development Setup

Follow these steps for active development on both the Python backend and TypeScript React frontend.

### 1. Clone Repository & Setup Virtual Environment

```bash
git clone https://github.com/naviyanka/NVLabsCompany.git
cd NVLabsCompany

# Create a Python 3.12+ virtual environment
python -m venv .venv

# Activate virtual environment
# Windows (PowerShell):
.\.venv\Scripts\Activate.ps1
# macOS / Linux:
source .venv/bin/activate
```

### 2. Install Backend Dependencies

```bash
# Upgrade pip and install NEXUS package in editable mode with dev dependencies
python -m pip install --upgrade pip
pip install -e ".[dev]"
```

### 3. Configure Environment Variables

Create a `.env` file in the project root (or copy `.env.example` if available):

```ini
# Application Configuration
NEXUS_ENV=development
DEBUG=true
SECRET_KEY=dev-secret-key-change-in-production-min-32-chars

# Authentication Controls
AUTH_ENABLED=true

# Database Connection
# PostgreSQL (Recommended for production & local dev):
DATABASE_URL=postgresql+asyncpg://nexus:nexus_dev_password@localhost:5432/nexus
# SQLite (Alternative for quick lightweight local testing):
# DATABASE_URL=sqlite+aiosqlite:///./nexus.db

# Redis Connection
REDIS_URL=redis://localhost:6379/0

# LLM Provider API Keys (Optional - set as needed)
ANTHROPIC_API_KEY=your_anthropic_key_here
OPENAI_API_KEY=your_openai_key_here
GEMINI_API_KEY=your_gemini_key_here
AZURE_OPENAI_API_KEY=your_azure_key_here
```

### 4. Database Migrations (Alembic)

NEXUS uses SQLModel (SQLAlchemy + Pydantic) with Alembic for type-safe database schemas and migrations.

```bash
# Run all pending Alembic database migrations
alembic upgrade head
```

> [!NOTE]
> When using SQLite for local testing, the application lifespan automatically creates missing tables on startup. For PostgreSQL databases, running `alembic upgrade head` is mandatory.

### 5. Start Backend FastAPI Server

```bash
# Start Uvicorn development server with hot reloading
uvicorn nexus.main:app --reload --host 0.0.0.0 --port 8000
```

Once running:
- **Interactive OpenAPI Documentation (Swagger UI)**: `http://localhost:8000/docs`
- **ReDoc Documentation**: `http://localhost:8000/redoc`

### 6. Setup & Start React Dashboard

```bash
# Navigate to dashboard directory
cd dashboard

# Install Node dependencies
npm install

# Start Vite frontend development server
npm run dev
```

The React Dashboard will be available at `http://localhost:3000` (or `http://localhost:5173` depending on Vite port assignment).

---

## First-Time Administrator Setup

When running NEXUS for the first time on a fresh database:

1. Navigate to `http://localhost:3000/setup` in your browser.
2. Complete the initial setup form to create the primary administrator account and register your company workspace.
3. Alternatively, create an admin account via CLI:
```bash
python -m nexus.auth.bootstrap --email admin@nvlabs.ai --password "SecureAdminPass123!"
```
4. Once the first administrator account is created, `/setup` is automatically locked. Further users must be invited via `POST /api/v1/auth/invites`.

---

## Desktop Launcher & Daemon Server

NEXUS provides a unified Node.js daemon server that manages system state persistence and desktop integration.

```bash
# Build desktop & backend server scripts
npm run build:server

# Launch production server daemon
node dist/server.cjs
```

The daemon automatically restores:
- Department & Squad org structures
- Active agents & soul configurations
- Tasks, OKRs, and Workflow DAGs
- Audit trails, Budget limits, and Knowledge Plaza feeds

---

## Environment Variables Reference

| Variable | Type | Default | Description |
| :--- | :--- | :--- | :--- |
| `NEXUS_ENV` | String | `development` | Environment mode (`development`, `staging`, `production`) |
| `DEBUG` | Boolean | `false` | Enables detailed debug logs and exception tracebacks |
| `SECRET_KEY` | String | *Required* | Secret key for signing session tokens and CSRF cookies |
| `AUTH_ENABLED` | Boolean | `true` | Enables authentication middleware enforcement |
| `DATABASE_URL` | String | `sqlite+aiosqlite:///./nexus.db` | SQLAlchemy async connection URI |
| `REDIS_URL` | String | `redis://localhost:6379/0` | Redis connection URI for caching and rate limiting |
| `ANTHROPIC_API_KEY` | String | `""` | Anthropic Claude API Key |
| `OPENAI_API_KEY` | String | `""` | OpenAI GPT-4o API Key |
| `GEMINI_API_KEY` | String | `""` | Google Gemini API Key |
| `LOG_LEVEL` | String | `INFO` | Logging level (`DEBUG`, `INFO`, `WARNING`, `ERROR`) |

---

## Troubleshooting & FAQs

### 1. Alembic Table Count Mismatch (`EXPECTED_TABLES`)
- **Issue**: Running unit tests or migrations fails with table count mismatches.
- **Fix**: Ensure all 69 SQLModel models are imported in `src/nexus/models/__init__.py`.

### 2. Stream/SSE Connection Timeouts under `AUTH_ENABLED=false`
- **Issue**: SSE event stream hangs when testing without auth.
- **Fix**: Unit tests testing auth rejection must monkeypatch `settings.auth_enabled = True` explicitly so endpoints return 401 synchronously rather than opening an infinite stream.

### 3. Redis Connection Error
- **Issue**: `redis.exceptions.ConnectionError: Error 10061 connecting to localhost:6379`.
- **Fix**: Start Redis using Docker: `docker run -d -p 6379:6379 redis:7-alpine`.

### 4. CORS Error in React Dashboard
- **Issue**: Dashboard API requests blocked by CORS policy.
- **Fix**: Ensure `CORS_ORIGINS` in `.env` includes `http://localhost:3000` and `http://localhost:5173`.
