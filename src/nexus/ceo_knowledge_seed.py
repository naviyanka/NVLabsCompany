"""Seed the CEO agent's memory with API endpoint knowledge.

Run: python -m nexus.ceo_knowledge_seed
"""
import asyncio
import uuid
from datetime import datetime, timezone

CEO_AGENT_ID = uuid.UUID("00000000-0000-4000-8000-000000000100")
COMPANY_ID = uuid.UUID("00000000-0000-4000-8000-000000000001")

# API endpoint knowledge organized by domain
API_KNOWLEDGE = [
    # Agents
    {
        "content": "AGENTS API: GET /api/v1/companies/{id}/agents — list all agents. POST /api/v1/companies/{id}/agents — create agent (name, role, adapter_type, model, capabilities). GET /api/v1/agents/{id} — get single agent. PUT /api/v1/agents/{id} — update agent fields. DELETE /api/v1/agents/{id} — remove agent. POST /api/v1/agents/{id}/wake — wake idle agent. POST /api/v1/agents/{id}/pause — pause agent. POST /api/v1/agents/{id}/heartbeat — record heartbeat.",
        "scope": "api_reference",
        "importance": 0.95,
        "tags": "agents,workforce,crud,wake,pause",
    },
    # Tasks
    {
        "content": "TASKS API: GET /api/v1/companies/{id}/tasks — list tasks. POST /api/v1/companies/{id}/tasks — create task (title, description, priority, assignee_id). PUT /api/v1/tasks/{id} — update task (status: pending/in_progress/completed/failed). POST /api/v1/tasks/{id}/assign — assign to agent. GET /api/v1/tasks/{id}/subtasks — get subtasks.",
        "scope": "api_reference",
        "importance": 0.9,
        "tags": "tasks,assignment,status,subtasks",
    },
    # Chat
    {
        "content": "CHAT API: POST /api/v1/agents/{id}/chat — send message (body: {prompt: string}). Returns {message, history, model_used, tokens_used}. POST /api/v1/agents/{id}/chat/stream — SSE streaming chat. GET /api/v1/agents/{id}/chat — get chat history.",
        "scope": "api_reference",
        "importance": 0.9,
        "tags": "chat,messaging,conversation,stream",
    },
    # Pipelines
    {
        "content": "PIPELINES API: GET /api/v1/companies/{id}/pipelines — list pipelines. POST /api/v1/companies/{id}/pipelines — create pipeline (name, stages[]). POST /api/v1/pipelines/{id}/run — execute pipeline. GET /api/v1/pipelines/{id}/runs — list runs. Each stage has: name, prompt, agent_id (optional), adapter_type (optional).",
        "scope": "api_reference",
        "importance": 0.85,
        "tags": "pipelines,execution,stages,workflow",
    },
    # Nodes
    {
        "content": "NODES API: GET /api/v1/nodes — list all 164 workflow nodes (filterable by ?category= or ?q=search). GET /api/v1/nodes/categories — category counts. GET /api/v1/nodes/{id} — single node detail. POST /api/v1/nodes/{id}/execute — execute a node with parameters. Categories: ai, analytics, browser, cloud, crm, database, devops, ecommerce, email, file, finance, http, iot, media, messaging, monitoring, productivity, schedule, search, security, social, storage, trigger, utility, voice.",
        "scope": "api_reference",
        "importance": 0.85,
        "tags": "nodes,workflow,execute,categories",
    },
    # Workflows
    {
        "content": "WORKFLOWS API: POST /api/v1/workflows/company — start company workflow (objective, strategy). POST /api/v1/workflows/task — start task flow (task_id, agent_capabilities). GET /api/v1/companies/{id}/workflows/runs — list workflow runs. GET /api/v1/workflows/runs/{id} — get run status/trace. POST /api/v1/workflows/runs/{id}/cancel — cancel running workflow.",
        "scope": "api_reference",
        "importance": 0.85,
        "tags": "workflows,execution,company,task",
    },
    # Goals
    {
        "content": "GOALS API: GET /api/v1/companies/{id}/goals — list strategic goals. POST /api/v1/companies/{id}/goals — create goal (title, description, owner_agent_id). PUT /api/v1/goals/{id} — update status (active/completed/paused). The autonomous orchestrator drives active goals every 2 minutes.",
        "scope": "api_reference",
        "importance": 0.85,
        "tags": "goals,strategy,okr,orchestrator",
    },
    # Memory
    {
        "content": "MEMORY API: GET /api/v1/companies/{id}/memory — list memories. POST /api/v1/companies/{id}/memory — store memory (content, scope, agent_id, importance 0-1, tier: hot/warm/cold). GET /api/v1/companies/{id}/memory/search?q= — search memories by content. DELETE /api/v1/memory/{id} — remove memory.",
        "scope": "api_reference",
        "importance": 0.85,
        "tags": "memory,knowledge,search,store",
    },
    # Knowledge Base
    {
        "content": "KNOWLEDGE API: GET /api/v1/companies/{id}/knowledge — list knowledge pages. POST /api/v1/companies/{id}/knowledge — create page (title, content, category). GET /api/v1/companies/{id}/knowledge/search?q= — RAG search. PUT /api/v1/knowledge/{id} — update page. Pages support versioning and embeddings.",
        "scope": "api_reference",
        "importance": 0.8,
        "tags": "knowledge,rag,search,documentation",
    },
    # Budgets
    {
        "content": "BUDGETS API: GET /api/v1/companies/{id}/budgets — company budget status. PUT /api/v1/companies/{id}/budgets — update budget (budget_monthly_cents). GET /api/v1/companies/{id}/budgets/usage — per-agent spend breakdown. Budget alerts fire at 80% usage. Rate limiting: 100 requests/min per company (Redis-backed when available).",
        "scope": "api_reference",
        "importance": 0.8,
        "tags": "budgets,spend,limits,rate-limiting",
    },
    # Approvals
    {
        "content": "APPROVALS API: GET /api/v1/companies/{id}/approvals/pending — list pending approvals. POST /api/v1/approvals/{id}/approve — approve (body: {decided_by}). POST /api/v1/approvals/{id}/reject — reject. Approval types: secret_request (agent needs API key), high_cost_operation, dangerous_action.",
        "scope": "api_reference",
        "importance": 0.8,
        "tags": "approvals,governance,security",
    },
    # Control (kill switch, pause, gate)
    {
        "content": "CONTROL API: POST /api/v1/control/{agent_id}/pause — pause/unpause agent (body: {on: bool}). POST /api/v1/control/{agent_id}/halt — emergency halt. POST /api/v1/control/{agent_id}/resume — resume from halt. POST /api/v1/control/{agent_id}/gate-tool — gate/ungate a tool (body: {tool, on}). POST /api/v1/control/{agent_id}/steer — inject directive. GET /api/v1/control/{agent_id}/snapshot — get control state.",
        "scope": "api_reference",
        "importance": 0.9,
        "tags": "control,governance,kill-switch,pause,halt",
    },
    # Dashboard & Activity
    {
        "content": "DASHBOARD API: GET /api/v1/companies/{id}/dashboard/stats — agent/task/pipeline counts. GET /api/v1/companies/{id}/dashboard/metrics — daily metrics. ACTIVITY: GET /api/v1/companies/{id}/activity — company activity feed. GET /api/v1/agents/{id}/logs — per-agent execution logs.",
        "scope": "api_reference",
        "importance": 0.75,
        "tags": "dashboard,metrics,activity,logs",
    },
    # Settings
    {
        "content": "SETTINGS API: GET /api/v1/companies/{id}/settings — all settings. PUT /api/v1/companies/{id}/settings — update settings (company_name, timezone, default_model, sprint_duration_days, notification preferences). Settings are company-scoped JSON.",
        "scope": "api_reference",
        "importance": 0.7,
        "tags": "settings,configuration,company",
    },
    # Auth
    {
        "content": "AUTH API: POST /api/v1/auth/login — login (email, password) → sets session cookie. POST /api/v1/auth/setup — first-admin creation (only works when user table is empty). POST /api/v1/auth/logout — clear session. POST /api/v1/auth/invite — send invite. GET /api/v1/auth/me — current user. All other endpoints require auth (cookie or Bearer API key).",
        "scope": "api_reference",
        "importance": 0.7,
        "tags": "auth,login,session,security",
    },
    # Evolution
    {
        "content": "EVOLUTION API: GET /api/v1/companies/{id}/evolution/proposals — list proposals. POST /api/v1/companies/{id}/evolution/proposals — create proposal (agent_id, type, description, changes). POST /api/v1/evolution/proposals/{id}/evaluate — run A/B evaluation. POST /api/v1/evolution/proposals/{id}/promote — promote to production. Types: prompt_improvement, capability_addition, workflow_optimization.",
        "scope": "api_reference",
        "importance": 0.75,
        "tags": "evolution,proposals,evaluate,promote",
    },
    # Secrets
    {
        "content": "SECRETS API: GET /api/v1/companies/{id}/secrets — list secrets (values hidden). POST /api/v1/companies/{id}/secrets — create secret (name, value, description). Secrets are Fernet-encrypted at rest. Agents request access via approval flow. DELETE /api/v1/secrets/{id} — revoke secret.",
        "scope": "api_reference",
        "importance": 0.75,
        "tags": "secrets,encryption,credentials",
    },
    # Hiring
    {
        "content": "HIRING API: POST /api/v1/companies/{id}/hire — hire from archetype (archetype_name, name_override, department_id). POST /api/v1/companies/{id}/hire/manifest — hire from manifest JSON (portable agent template). GET /api/v1/archetypes — list all 22 archetypes. GET /api/v1/providers — list all LLM providers with availability status.",
        "scope": "api_reference",
        "importance": 0.8,
        "tags": "hiring,archetypes,providers,onboarding",
    },
    # Platform architecture
    {
        "content": "PLATFORM ARCHITECTURE: Backend is Python FastAPI (src/nexus/main.py) with 44 registered routers and 292 endpoints. Frontend is React 18 + Vite + TailwindCSS (dashboard/) with 26 pages. Database: PostgreSQL (prod) or SQLite (dev) via SQLModel/SQLAlchemy. Redis: rate limiting + leader election + budget sync. Docker Compose: backend, frontend, postgres, redis, temporal, temporal-ui, temporal-worker services.",
        "scope": "architecture",
        "importance": 0.9,
        "tags": "architecture,stack,infrastructure",
    },
    # Agent workforce
    {
        "content": "WORKFORCE: 8 agents in the company. Navi (CEO, hermes adapter, orchestrator). Nova (CTO, anthropic, claude-sonnet-4). Bolt (Senior Backend Engineer, openai, gpt-4o). Pixel (Frontend Engineer, openai, gpt-4o). Sage (AI Research Lead, anthropic, claude-sonnet-4). Compass (Project Manager, openai, gpt-4o-mini). Shield (QA Engineer, openai, gpt-4o-mini). Forge (DevOps Engineer, openai, gpt-4o-mini).",
        "scope": "workforce",
        "importance": 0.95,
        "tags": "agents,team,workforce,roles",
    },
    # Orchestration
    {
        "content": "ORCHESTRATION: The autonomous orchestrator (src/nexus/runtime/orchestrator.py) runs every 120 seconds. It: 1) Scans active goals, 2) Decomposes them into tasks via GoalLoop, 3) Routes tasks to best-fit agents via AgentRouter, 4) Auto-wakes idle agents with pending tasks, 5) Retries failed tasks with SmartRetry (REASSIGN or DECOMPOSE strategies). Leader election ensures only one instance runs in multi-worker deployments.",
        "scope": "architecture",
        "importance": 0.85,
        "tags": "orchestration,goals,routing,retry",
    },
]


async def seed_ceo_knowledge():
    """Seed CEO agent memories with API knowledge."""
    from nexus.database import async_session_factory
    from nexus.models.memory import MemoryRecord
    from nexus.models._time import utcnow
    from sqlalchemy import select, func

    async with async_session_factory() as db:
        # Check if already seeded
        count_result = await db.execute(
            select(func.count(MemoryRecord.id)).where(
                MemoryRecord.agent_id == CEO_AGENT_ID,
                MemoryRecord.scope == "api_reference",
            )
        )
        existing = count_result.scalar() or 0
        if existing >= 10:
            print(f"CEO knowledge already seeded ({existing} records). Skipping.")
            return

        now = utcnow()
        seeded = 0
        for entry in API_KNOWLEDGE:
            record = MemoryRecord(
                id=uuid.uuid4(),
                company_id=COMPANY_ID,
                agent_id=CEO_AGENT_ID,
                content=entry["content"],
                scope=entry["scope"],
                importance=entry["importance"],
                tier="hot",
                tags=entry.get("tags", ""),
                created_at=now,
                updated_at=now,
            )
            db.add(record)
            seeded += 1

        await db.commit()
        print(f"Seeded {seeded} knowledge records for CEO agent.")


if __name__ == "__main__":
    asyncio.run(seed_ceo_knowledge())
