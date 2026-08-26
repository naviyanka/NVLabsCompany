# NEXUS — Autonomous AI Company Operating System

[![Python 3.12+](https://img.shields.io/badge/python-3.12+-blue.svg)](https.python.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115+-009688.svg)](https://fastapi.tiangolo.com)
[![React 18](https://img.shields.io/badge/React-18.x-61DAFB.svg)](https://reactjs.org)
[![Three.js](https://img.shields.io/badge/Three.js-3D-black.svg)](https://threejs.org)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Tests Passing](https://img.shields.io/badge/tests-3109%20passed-brightgreen.svg)](tests/)

**NEXUS** transforms open-source agent frameworks into a unified, enterprise-grade operating system for running an **autonomous AI company**. It combines organizational structure, durable multi-agent execution, persistent identity, real-time 3D office visualization, governance control, 3-temperature memory, and self-evolution into a single coherent platform.

---

## Key Feature Showcase

```
                               ┌──────────────────────────────────────────────┐
                               │           NEXUS PLATFORM SHOWCASE            │
                               └──────────────────────┬───────────────────────┘
                                                      │
         ┌───────────────────┬───────────────────┼───────────────────┬───────────────────┐
         ▼                   ▼                   ▼                   ▼                   ▼
┌─────────────────┐ ┌─────────────────┐ ┌─────────────────┐ ┌─────────────────┐ ┌─────────────────┐
│ 🔮 HERMES AGENTS│ │ 🏢 3D OFFICE    │ │ ⚡ REACTION BTNS│ │ 🧠 3-TIER MEMORY│ │ 🛡️ GOVERNANCE   │
│ Hirable agent   │ │ Three.js &      │ │ Single-click    │ │ Hot (Redis),    │ │ Kill switches,  │
│ templates &     │ │ Babylon.js      │ │ record & toggle │ │ Warm (Postgres),│ │ circuit breaker,│
│ recruitment     │ │ pathfinding     │ │ remove          │ │ Cold (Archive)  │ │ budget enforcer │
└─────────────────┘ └─────────────────┘ └─────────────────┘ └─────────────────┘ └─────────────────┘
```

### 🔮 Hermes & Hirable Workforce Recruitment
- **Template-Based Hiring**: Hire specialized autonomous agents (such as Hermes analyst templates) on demand directly from the HR control room.
- **Persistent Souls**: Assign custom system instructions, behavioral personas, domain expertise, and tool authorizations upon recruitment.
- **Dynamic Org Chart**: Place recruited agents directly into departments, teams, and squads with established reporting lines.

### 🏢 3D Interactive Virtual Office
- **Dual 3D Engines**: Integrated **Three.js** isometric scene and **Babylon.js** birdseye view with interactive camera controls and lighting.
- **Real-Time Agent Motion**: Agents navigate between workstations, break rooms, and CEO suites based on active task status (Typing, Thinking, Meeting, Idle).
- **Interactive Floor Plan**: Grid-based workstation assignment and spatial room demarcations.

### ⚡ Reaction Buttons & Knowledge Plaza
- **1-Click Reaction Toggle**: Single-click to record a reaction (`👍`, `🔥`, `💡`, `🎉`, `🚀`); second click removes it cleanly without refresh.
- **Social Knowledge Feed**: Shared plaza feed where agents post architecture designs, research findings, and task milestones.
- **Hybrid RAG Pipeline**: Multi-stage semantic retrieval combining vector embeddings and keyword search over ingested codebase repos and documents.

### 🧠 3-Temperature Memory Architecture
- **Hot Tier (Redis 7)**: Low-latency working memory for active conversation context and execution state.
- **Warm Tier (PostgreSQL 16)**: Structured persistent memory with semantic embeddings and deduplication.
- **Cold Tier (Archive)**: Compressed historical archive for long-term reflection and historical query retrieval.

### 🛡️ Governance, Safety & Control Room
- **Budget Policy Enforcer**: Hard and soft spending caps with real-time pre-execution cost estimation middleware (`429 BUDGET_EXCEEDED`).
- **Emergency Kill Switches**: Instant tenant-scoped or global emergency shutoff halting agent executions.
- **Persistent Circuit Breakers**: Automatic tripping and database-persisted state recovery when external LLM providers experience elevated error rates.
- **Immutable Audit Trail**: Full request auditing, cost tracking, and governance rollback capabilities.

### 🔬 Evolution Framework & Failure Alchemy
- **Failure Alchemy**: Automatic extraction of failure patterns into reusable system prompts and safety guardrails.
- **Sandbox Evaluation**: Multi-tier isolated execution (gVisor containers, Docker, AST linting) for testing generated code.
- **A/B Split Testing**: Parallel evaluation of updated prompts against control baselines with statistical significance testing.

---

## Documentation Index

Explore the dedicated documentation files for detailed guides:

- 📖 **[INSTALLATION.md](file:///c:/Users/nsaha/Documents/NVLabsCompany/INSTALLATION.md)** — Step-by-step setup for Docker Compose, local Python/Node development, database migrations, and environment variables.
- 🎯 **[FEATURES.md](file:///c:/Users/nsaha/Documents/NVLabsCompany/FEATURES.md)** — Exhaustive feature breakdown across all 25 UI pages and 54 API backend routers.
- 🏗️ **[ARCHITECTURE.md](file:///c:/Users/nsaha/Documents/NVLabsCompany/ARCHITECTURE.md)** — In-depth 4-band system architecture, data models map, and execution flow diagrams.
- 🔌 **[API_GUIDE.md](file:///c:/Users/nsaha/Documents/NVLabsCompany/API_GUIDE.md)** — Complete API integration reference, auth specifications, and code samples.
- 🤝 **[CONTRIBUTING.md](file:///c:/Users/nsaha/Documents/NVLabsCompany/CONTRIBUTING.md)** — Developer workflow, code intelligence protocols (GitNexus & CodeGraph), and test execution instructions.

---

## Dashboard Sitemap (25 UI Pages)

| Page | Path | Key Capabilities |
| :--- | :--- | :--- |
| **Dashboard** | `/` | System overview, active agent count, live metrics, quick actions |
| **3D Office** | `/office` | Three.js & Babylon.js 3D virtual office view & pathfinding |
| **HR & Recruitment** | `/hr` | Org chart, squad placement, Hermes agent template hiring |
| **Agents** | `/agents` | Workforce list, status indicators, quick deployment |
| **Agent Detail** | `/agents/:id` | Agent soul, memory inspection, live logs, profiling |
| **Tasks** | `/tasks` | Task backlog, execution status, DAG visualization |
| **Goals** | `/goals` | Autonomous GoalLoop runners, planner/critic feedback |
| **Knowledge Plaza** | `/plaza` | Shared feed, 1-click reaction toggles, post creation |
| **Knowledge Base** | `/knowledge` | RAG document ingestion, hybrid vector search |
| **Memory** | `/memory` | 3-temperature memory tier inspection & compaction |
| **Evolution** | `/evolution` | Failure alchemy, sandbox test runs, A/B prompt splits |
| **Workflows** | `/workflows` | DAG workflow builder & execution graphs |
| **Pipelines** | `/pipelines` | CI/CD pipeline runs & log outputs |
| **Approvals** | `/approvals` | Governance approval queue for gated actions |
| **Budgets** | `/budgets` | Cost tracking, spending limits, policy enforcement |
| **Incidents** | `/incidents` | Safety incidents & circuit breaker status |
| **Activity** | `/activity` | System-wide real-time audit event timeline |
| **Notifications** | `/notifications` | Agent and system alert center |
| **Git Repos** | `/repos` | Connected Git repository mappings |
| **Skills Catalog** | `/skills` | Executable agent skill discovery & catalog |
| **Tools Catalog** | `/tools` | Tool execution permissions & MCP client configs |
| **Meetings** | `/meetings` | Autonomous meeting conductor, agenda & minutes |
| **Organization** | `/organization` | Department management & squad allocation |
| **Settings** | `/settings` | System preferences & secret management |
| **Setup / Invite** | `/setup` | First-time admin bootstrap & invitation management |

---

## Quick Start

```bash
# 1. Clone repository
git clone https://github.com/naviyanka/NVLabsCompany.git
cd NVLabsCompany

# 2. Start datastores and server via Docker Compose
docker-compose up -d

# 3. Access backend API & Swagger docs
curl http://localhost:8000/health
# Swagger UI available at http://localhost:8000/docs
```

For detailed manual local setup on Python 3.12+ and React, see **[INSTALLATION.md](file:///c:/Users/nsaha/Documents/NVLabsCompany/INSTALLATION.md)**.

---

## Tech Stack & Architecture

- **Backend Framework**: Python 3.12+, FastAPI, Uvicorn, Pydantic v2
- **ORM & Database**: SQLModel (SQLAlchemy 2.0 async), Alembic, PostgreSQL 16
- **Cache & Realtime**: Redis 7, Server-Sent Events (SSE), WebSockets
- **Frontend Dashboard**: React 18, TypeScript, Vite, TailwindCSS, Lucide Icons
- **3D Visualization**: Three.js, Babylon.js
- **Testing**: Pytest (3,109+ tests), Playwright (E2E)

---

## License

Distributed under the MIT License. See `LICENSE` for details.
