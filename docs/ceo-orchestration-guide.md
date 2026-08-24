# NVLabsCompany CEO Orchestration Guide & System Manual

**Author**: NVLabs System Architecture Team  
**Target Audience**: Navi (CEO) & Autonomous Workforce Agents  
**Version**: 2.0 (100% Fully Wired)

---

## 🧭 1. Executive Summary

This manual serves as the authoritative blueprint and operational handbook for **Navi (Chief Executive Officer)**. It outlines the complete technical topology of NVLabsCompany, the exact REST API contract endpoints, persistence mechanisms, execution pipelines, and multi-agent coordination protocols.

---

## 🏛️ 2. Architecture Overview

NVLabsCompany operates on a decoupled 3-tier architecture:

### Tier 1: Web Dashboard Frontend (React 18 + Vite)
- **Location**: `dashboard/`
- **URL**: `http://localhost:3000`
- **Pages**: 25 fully wired pages covering Agents Directory, Tasks Kanban, Pipelines Execution, Workflows Builder, Memory Graph, Knowledge Base, Git Repositories, Budgets, Approvals, and System Telemetry.

### Tier 2: Express Server Daemon (`dashboard/server.ts`)
- **Location**: `dashboard/server.ts` -> `dist/server.cjs`
- **Port**: `3000`
- **Role**:
  - Serves static production web assets (`dist/`).
  - Handles mock disk persistence under `dashboard/data/*.json` (15 JSON files).
  - Provides SSE streaming handler `/api/v1/agents/:agentId/chat/stream`.
  - Proxies requests to the Python FastAPI backend when `PROXY_API=true`.

### Tier 3: Python FastAPI Engine (`src/nexus/main.py`)
- **Location**: `src/nexus/`
- **URL**: `http://localhost:8000`
- **Role**:
  - Registers 44 active API routers.
  - Interacts with SQLite / PostgreSQL databases via SQLAlchemy.
  - Controls LLM adapters (OpenAI, Anthropic, Ollama, CLI, etc.).
  - Executes background pipeline stage runs, hybrid vector RAG search, and git worktrees.

---

## 🔌 3. Endpoint Reference Cheat Sheet

| Domain | HTTP Method | Endpoint | Description |
|---|---|---|---|
| **Agents** | `GET` | `/api/v1/companies/{id}/agents` | List company agents |
| **Agents** | `POST` | `/api/v1/companies/{id}/agents` | Create an agent |
| **Agents** | `DELETE` | `/api/v1/companies/{id}/agents/{id}` | Fire an agent |
| **Agents** | `POST` | `/api/v1/agents/{id}/wake` | Wake agent |
| **Agents** | `POST` | `/api/v1/agents/{id}/pause` | Pause agent |
| **Chat** | `POST` | `/api/v1/agents/{id}/chat` | Non-streaming LLM chat |
| **Chat** | `POST` | `/api/v1/agents/{id}/chat/stream` | Real SSE word-by-word streaming |
| **Tasks** | `GET` | `/api/v1/companies/{id}/tasks` | List task backlog |
| **Tasks** | `POST` | `/api/v1/companies/{id}/tasks` | Create task (auto-routed via `AgentRouter`) |
| **Tasks** | `PATCH` | `/api/v1/companies/{id}/tasks/{id}` | Update task status |
| **Pipelines** | `POST` | `/api/v1/pipelines/{id}/run` | Execute pipeline background worker |
| **Workflows** | `POST` | `/api/v1/workflows/{id}/execute` | Run visual workflow graph |
| **Memory** | `GET` | `/api/v1/agents/{id}/memory` | Query L1-L3 agent memories |
| **Knowledge**| `POST` | `/api/v1/companies/{id}/knowledge/search` | Hybrid RAG search (BM25 + vector similarity) |
| **Git Repos** | `POST` | `/api/v1/companies/{id}/repos/{id}/worktree` | Create isolated git worktree branch |
| **Budgets** | `GET` | `/api/v1/companies/{id}/billing/budgets` | Query monthly USD budget & spend |

---

## 🎯 4. CEO Delegation & Subsystem Protocols

### Protocol 1: Task Decomposition & Multi-Agent Routing
When a complex project or feature is requested:
1. Use `TaskPlanner` logic to decompose the request into discrete subtasks.
2. Submit subtasks to `POST /api/v1/companies/{id}/tasks`.
3. Allow `AgentRouter` to evaluate skill match, current capacity, performance index, and budget availability to assign the best agent.

### Protocol 2: Git Worktree Isolation
Before making changes to codebase files:
1. Create a dedicated worktree branch using `WorktreeManager.create_worktree()`.
2. Edit files cleanly within the worktree directory (`agent/<name>-<id>`).
3. Verify that changes compile and pass tests before merging to main.

### Protocol 3: Full Quality Verification
Run verification commands in order:
```bash
# 1. Check Python compilation
python -m py_compile src/nexus/api/routes/*.py

# 2. Check TypeScript compilation
npx tsc --noEmit --skipLibCheck

# 3. Verify production asset build
npm run build

# 4. Check change impact via GitNexus
npx gitnexus detect-changes
```
