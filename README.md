# NEXUS — Autonomous AI Company Operating System

[![Python 3.12+](https://img.shields.io/badge/python-3.12+-blue.svg)](https://python.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115+-009688.svg)](https://fastapi.tiangolo.com)
[![React 18](https://img.shields.io/badge/React-18.x-61DAFB.svg)](https://reactjs.org)
[![Three.js](https://img.shields.io/badge/Three.js-3D-black.svg)](https://threejs.org)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Tests Passing](https://img.shields.io/badge/tests-3232%20passed-brightgreen.svg)](tests/)

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
- **Interactive Floor Plan**: Grid-based workstation assignment and spatial room demarcations. See **[docs/FloorPlan.md](docs/FloorPlan.md)**.

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

## Complete Documentation Index

### Core System Guides
- 📖 **[INSTALLATION.md](INSTALLATION.md)** — Step-by-step setup for Docker Compose, local Python/Node development, database migrations, and environment variables.
- 🎯 **[FEATURES.md](FEATURES.md)** — Exhaustive feature breakdown across all 28 UI pages and 54 API backend routers.
- 🏗️ **[ARCHITECTURE.md](ARCHITECTURE.md)** — In-depth 4-band system architecture, data models map, and execution flow diagrams.
- 🔌 **[API_GUIDE.md](API_GUIDE.md)** — Complete API integration reference, auth specifications, and code samples.
- 🤝 **[CONTRIBUTING.md](CONTRIBUTING.md)** — Developer workflow, code intelligence protocols (GitNexus & CodeGraph), and test execution instructions.
- 📊 **[docs/FINAL-STATUS-SUMMARY.md](docs/FINAL-STATUS-SUMMARY.md)** — Verified status summary (3,232 passed tests).

### Specialized Architectural Specs
- 🗺️ **[docs/FloorPlan.md](docs/FloorPlan.md)** — 3D Virtual Office floor plan layout and workstation specs.
- ⚡ **[docs/OFFICE-3D-MICRO-PHASES.md](docs/OFFICE-3D-MICRO-PHASES.md)** — 3D Office rendering micro-phases & pathfinding details.
- 🔍 **[docs/GAP-CLOSURE-PLAN.md](docs/GAP-CLOSURE-PLAN.md)** — Comprehensive subsystem gap closure analysis.
- 🛠️ **[docs/ENVIRONMENT.md](docs/ENVIRONMENT.md)** — System environment matrix & port assignments.
- 📋 **[docs/PRODUCTION-READINESS-AUDIT.md](docs/PRODUCTION-READINESS-AUDIT.md)** — Enterprise production readiness audit.
- 👑 **[docs/ceo-orchestration-guide.md](docs/ceo-orchestration-guide.md)** — Navi CEO orchestration protocols.

### Workspace & Agent Guidelines
- 👥 **[AGENTS.md](AGENTS.md)** — GitNexus Code Intelligence & mandatory impact analysis rules.
- 🤖 **[CLAUDE.md](CLAUDE.md)** — Workspace commands, conventions, and architectural rules.
- ♊ **[GEMINI.md](GEMINI.md)** — Graphify knowledge graph rules.
- 🖥️ **[dashboard/README.md](dashboard/README.md)** — Frontend React dashboard overview & component structure.

---

## Dashboard Sitemap (28 UI Pages)

Every page in the React dashboard is wired directly to its component source code below:

| Page | Route Path | Source Component | Key Capabilities |
| :--- | :--- | :--- | :--- |
| **Dashboard** | `/` | [`Dashboard.tsx`](dashboard/src/pages/Dashboard.tsx) | System overview, active agent count, live metrics, quick actions |
| **3D Office** | `/office` | [`Office.tsx`](dashboard/src/pages/Office.tsx) | Three.js & Babylon.js 3D virtual office view & pathfinding |
| **HR & Recruitment** | `/hr` | [`HRRoom.tsx`](dashboard/src/pages/HRRoom.tsx) | Org chart, squad placement, Hermes agent template hiring |
| **Agents** | `/agents` | [`Agents.tsx`](dashboard/src/pages/Agents.tsx) | Workforce list, status indicators, quick deployment |
| **Agent Detail** | `/agents/:id` | [`AgentDetailPage.tsx`](dashboard/src/pages/AgentDetailPage.tsx) | Agent soul, memory inspection, live logs, profiling |
| **Tasks** | `/tasks` | [`Tasks.tsx`](dashboard/src/pages/Tasks.tsx) | Task backlog, execution status, DAG visualization |
| **Goals** | `/goals` | [`Goals.tsx`](dashboard/src/pages/Goals.tsx) | Autonomous GoalLoop runners, planner/critic feedback |
| **Knowledge Plaza** | `/plaza` | [`PlazaFeed.tsx`](dashboard/src/pages/PlazaFeed.tsx) | Shared feed, 1-click reaction toggles, post creation |
| **Knowledge Base** | `/knowledge` | [`KnowledgeBase.tsx`](dashboard/src/pages/KnowledgeBase.tsx) | RAG document ingestion, hybrid vector search |
| **Memory** | `/memory` | [`Memory.tsx`](dashboard/src/pages/Memory.tsx) | 3-temperature memory tier inspection & compaction |
| **Memory Graph** | `/memory/graph` | [`MemoryGraph.tsx`](dashboard/src/pages/MemoryGraph.tsx) | Visual memory node graph & path finder |
| **Evolution** | `/evolution` | [`Evolution.tsx`](dashboard/src/pages/Evolution.tsx) | Failure alchemy, sandbox test runs, A/B prompt splits |
| **Workflows** | `/workflows` | [`Workflows.tsx`](dashboard/src/pages/Workflows.tsx) | DAG workflow builder & execution graphs |
| **Pipelines** | `/pipelines` | [`Pipelines.tsx`](dashboard/src/pages/Pipelines.tsx) | CI/CD pipeline runs & log outputs |
| **Approvals** | `/approvals` | [`Approvals.tsx`](dashboard/src/pages/Approvals.tsx) | Governance approval queue for gated actions |
| **Budgets** | `/budgets` | [`Budgets.tsx`](dashboard/src/pages/Budgets.tsx) | Cost tracking, spending limits, policy enforcement |
| **Activity** | `/activity` | [`Activity.tsx`](dashboard/src/pages/Activity.tsx) | System-wide real-time audit event timeline |
| **Notifications** | `/notifications` | [`Notifications.tsx`](dashboard/src/pages/Notifications.tsx) | Agent and system alert center |
| **Git Repos** | `/repos` | [`GitRepos.tsx`](dashboard/src/pages/GitRepos.tsx) | Connected Git repository mappings |
| **Skills Catalog** | `/skills` | [`Skills.tsx`](dashboard/src/pages/Skills.tsx) | Executable agent skill discovery & catalog |
| **Tools Catalog** | `/tools` | [`Tools.tsx`](dashboard/src/pages/Tools.tsx) | Tool execution permissions & MCP client configs |
| **Meetings** | `/meetings` | [`Meetings.tsx`](dashboard/src/pages/Meetings.tsx) | Autonomous meeting conductor, agenda & minutes |
| **Organization** | `/organization` | [`Organization.tsx`](dashboard/src/pages/Organization.tsx) | Department management & squad allocation |
| **Node Library** | `/nodes` | [`NodeLibrary.tsx`](dashboard/src/pages/NodeLibrary.tsx) | Visual workflow node catalog & connector registry |
| **Settings** | `/settings` | [`Settings.tsx`](dashboard/src/pages/Settings.tsx) | System preferences & secret management |
| **Setup** | `/setup` | [`Setup.tsx`](dashboard/src/pages/Setup.tsx) | First-time admin bootstrap |
| **Login** | `/login` | [`Login.tsx`](dashboard/src/pages/Login.tsx) | User session login |
| **Accept Invite** | `/invite` | [`AcceptInvite.tsx`](dashboard/src/pages/AcceptInvite.tsx) | Account invitation redemption |

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

For detailed manual local setup on Python 3.12+ and React, see **[INSTALLATION.md](INSTALLATION.md)**.

---

## Tech Stack & Architecture

- **Backend Framework**: Python 3.12+, FastAPI, Uvicorn, Pydantic v2
- **ORM & Database**: SQLModel (SQLAlchemy 2.0 async), Alembic, PostgreSQL 16
- **Cache & Realtime**: Redis 7, Server-Sent Events (SSE), WebSockets
- **Frontend Dashboard**: React 18, TypeScript, Vite, TailwindCSS, Lucide Icons
- **3D Visualization**: Three.js, Babylon.js
- **Testing**: Pytest (3,232+ tests), Playwright (E2E)

---

## License

Distributed under the MIT License. See `LICENSE` for details.
