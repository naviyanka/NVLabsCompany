---
name: navi-ceo-orchestrator
description: Master CEO orchestration skill for Navi. Grants complete operational knowledge, architectural topology, API route maps, DB persistence mechanisms, and execution protocols for managing the entire NVLabsCompany platform on demand.
---

# Navi CEO & System Orchestration Skill

This skill defines the complete operational knowledge base, execution protocols, and architectural topology for **Navi (Chief Executive Officer & Principal System Orchestrator)**.

---

## 🏛️ 1. Platform Architecture & Topology

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                           FRONTEND UI (React 18 + Vite)                         │
│                           URL: http://localhost:3000                            │
│  25 Pages: Agents, Tasks, Pipelines, Workflows, Memory, Knowledge, Budgets, ... │
└──────────────────────────────────────┬──────────────────────────────────────────┘
                                       │ HTTP / REST / SSE Stream
                                       ▼
┌─────────────────────────────────────────────────────────────────────────────────┐
│                    EXPRESS SERVER DAEMON (dashboard/server.ts)                  │
│                                PID: Auto-Daemon                                 │
│  • Listens on port 3000                                                         │
│  • Persists disk state to dashboard/data/*.json (15 JSON DBs)                  │
│  • Serves production build (dist/index.html & dist/server.cjs)                  │
│  • SSE Real-Time Stream (/api/v1/agents/:id/chat/stream)                        │
│  • Proxies API calls to Python FastAPI when PROXY_API=true                      │
└──────────────────────────────────────┬──────────────────────────────────────────┘
                                       │ HTTP Proxy / Direct API
                                       ▼
┌─────────────────────────────────────────────────────────────────────────────────┐
│                     PYTHON FASTAPI ENGINE (src/nexus/main.py)                   │
│                           URL: http://localhost:8000                            │
│  44 Routers, 50+ Endpoints, SQLAlchemy Async DB, Governance & Circuit Breaker   │
└─────────────────────────────────────────────────────────────────────────────────┘
```

---

## 🔌 2. Complete API Endpoint Reference Map

### A. Agents & Workforce Management (`src/nexus/api/routes/agents.py`, `hiring.py`)
- `GET /api/v1/companies/{company_id}/agents` — List all company agents.
- `POST /api/v1/companies/{company_id}/agents` — Create a single agent.
- `GET /api/v1/companies/{company_id}/agents/{agent_id}` — Get agent details.
- `PUT /api/v1/companies/{company_id}/agents/{agent_id}` — Update agent configuration/status.
- `DELETE /api/v1/companies/{company_id}/agents/{agent_id}` — Permanently fire agent.
- `POST /api/v1/agents/{agent_id}/wake` — Wake agent from idle/paused state.
- `POST /api/v1/agents/{agent_id}/pause` — Pause agent execution.
- `POST /api/v1/companies/{company_id}/agents/hire-team` — Batch-hire a team squad.
- `POST /api/v1/companies/{company_id}/agents/hire-from-manifest` — Import agent from manifest JSON.

### B. Chat & SSE Streaming (`src/nexus/api/routes/chat.py`, `dashboard/server.ts`)
- `POST /api/v1/agents/{agent_id}/chat` — Direct LLM chat endpoint (returns canned or adapter response).
- `POST /api/v1/agents/{agent_id}/chat/stream` — Real-time SSE word-by-word streaming endpoint.
- `GET /api/v1/agents/{agent_id}/chat` — Retrieve session conversation history.
- `DELETE /api/v1/agents/{agent_id}/chat` — Clear session conversation history.

### C. Tasks & Autonomous Orchestration (`src/nexus/api/routes/tasks.py`)
- `GET /api/v1/companies/{company_id}/tasks` — List tasks with status, priority, and agent assignment filters.
- `POST /api/v1/companies/{company_id}/tasks` — Create task (auto-assigned via `AgentRouter` if `assigned_agent_id` is omitted).
- `GET /api/v1/companies/{company_id}/tasks/{task_id}` — Get task details and subtasks.
- `PATCH /api/v1/companies/{company_id}/tasks/{task_id}` — Update status (`todo`, `in_progress`, `review`, `completed`, `failed`).
- `DELETE /api/v1/companies/{company_id}/tasks/{task_id}` — Delete task.

### D. Pipelines & Background Stages (`src/nexus/api/routes/pipelines.py`)
- `GET /api/v1/companies/{company_id}/pipelines` — List pipeline definitions.
- `POST /api/v1/companies/{company_id}/pipelines` — Create pipeline.
- `POST /api/v1/pipelines/{pipeline_id}/run` — Trigger background stage runner via `BackgroundTasks`.
- `GET /api/v1/pipelines/{pipeline_id}/runs` — Get pipeline run history.

### E. Workflows & Visual Automation (`src/nexus/api/routes/workflows.py`)
- `GET /api/v1/companies/{company_id}/workflows` — List workflows.
- `POST /api/v1/companies/{company_id}/workflows` — Create workflow with trigger and action nodes.
- `POST /api/v1/workflows/{workflow_id}/execute` — Trigger visual workflow execution graph.

### F. Memory & Context Graph (`src/nexus/api/routes/memory.py`, `memory_global.py`)
- `GET /api/v1/agents/{agent_id}/memory` — Query per-agent L1-L3 memory records.
- `POST /api/v1/agents/{agent_id}/memory` — Store explicit memory record.
- `GET /api/v1/companies/{company_id}/memory/graph` — Retrieve global company knowledge graph nodes & edges.

### G. Knowledge Base & Hybrid RAG Search (`src/nexus/api/routes/knowledge.py`)
- `GET /api/v1/companies/{company_id}/knowledge/pages` — List knowledge pages.
- `POST /api/v1/companies/{company_id}/knowledge/search` — Perform hybrid BM25 + vector similarity search via `RAGPipeline`.

### H. Git Repositories & Worktrees (`src/nexus/api/routes/repositories.py`)
- `GET /api/v1/companies/{company_id}/repos` — List tracked git repositories.
- `POST /api/v1/companies/{company_id}/repos/{repo_id}/worktree` — Create isolated git worktree (`agent/<name>-<id>`).

### I. Governance, Budgets & Approvals (`src/nexus/api/routes/budgets.py`, `approvals.py`)
- `GET /api/v1/companies/{company_id}/billing/budgets` — Query monthly agent budgets & spend.
- `GET /api/v1/companies/{company_id}/approvals` — List pending governance approvals.
- `POST /api/v1/companies/{company_id}/approvals/{id}/approve` — Approve pending action.

---

## 🛠️ 3. Execution Protocols & Operating Directives

1. **Task Assignment & Auto-Routing Protocol**:
   - When a task is created without an explicit agent assignment, `AgentRouter.route_task()` calculates candidate scores:
     $$\text{Score} = 0.4 \cdot \text{SkillMatch} + 0.25 \cdot \text{Capacity} + 0.20 \cdot \text{Performance} + 0.15 \cdot \text{Budget}$$
   - Assign the highest-scoring candidate and update status to `in_progress`.

2. **Git Branch Isolation Protocol**:
   - For all code edits, ensure `WorktreeManager.create_worktree()` has isolated a clean git branch (`agent/<name>-<id>`). Never commit broken code directly to main.

3. **Build Verification Protocol**:
   - Before completing any task, execute:
     - `npx tsc --noEmit --skipLibCheck` (TypeScript verification).
     - `npm run build` (Production bundle verification).
     - `python -m py_compile <modified_python_files>` (Python syntax compilation).
     - `npx gitnexus detect-changes` (Impact & regression review).

4. **Interactive Slash Commands Protocol**:
   - `/help` — Output list of available commands.
   - `/status` — Render agent name, role, title, provider, model, capabilities, and monthly budget.
   - `/clear` — Wipe session history.
   - `/export` — Download conversation transcript as Markdown (`.md`).
   - `/model` — Show active model and provider adapter.
