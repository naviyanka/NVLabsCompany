# Cross-Page Dependency Map

This file tracks which pages depend on other pages being wired up first, and which backend features are shared across pages.

---

## Dependency Graph Overview

```
Legend:
  A → B  means "A depends on B" (B should be wired before A, or A will have partial data)
  A ⇄ B  means "mutual dependency" (they share data, wire either first)

                    ┌─────────────┐
                    │   Agents    │  (CORE — almost everything depends on this)
                    └──────┬──────┘
                           │
          ┌────────────────┼────────────────────────────────┐
          │                │                                │
          ▼                ▼                ▼               ▼
    ┌───────────┐   ┌───────────┐   ┌───────────┐   ┌───────────┐
    │   Tasks   │   │   Tools   │   │  Pipelines │   │  Meetings │
    └─────┬─────┘   └─────┬─────┘   └─────┬─────┘   └───────────┘
          │                │               │
          ▼                ▼               ▼
    ┌───────────────────────────────────────────┐
    │              Activity Page                 │  (consumes events from all)
    └───────────────────────────────────────────┘
          ▲                ▲               ▲
          │                │               │
    ┌───────────┐   ┌───────────┐   ┌───────────┐
    │  Memory   │   │ Git Repos │   │  Budgets  │
    └───────────┘   └───────────┘   └───────────┘
```

---

## Per-Page Dependencies

### `/activity` (Activity)

| Depends On | Why | Hard/Soft | Notes |
|------------|-----|-----------|-------|
| `/agents` (Agents) | Needs agent names resolved from UUIDs for display | **Hard** | Without agents table populated, activity shows UUIDs instead of names |
| `/tasks` (Tasks) | Task-type activity events come from task lifecycle | Soft | Activity still works, just no Task-category events |
| `/pipelines` (Pipelines) | Pipeline-type events from pipeline_runs | Soft | Missing Pipeline category if not wired |
| `/tools` (Tools) | Tool dispatch events from tool_invocations | Soft | Missing tool dispatch latency data |
| `/memory` (Memory) | Memory-category events | Soft | Missing Memory category |
| `/git-repos` (Git Repos) | Git-type events (webhooks, PRs) | Soft | Missing Git category |
| `/budgets` (Budgets) | Policy/budget threshold events | Soft | Missing Policy category severity |

### `/agents` (Agents)

| Depends On | Why | Hard/Soft | Notes |
|------------|-----|-----------|-------|
| `/organization` (Organization) | Agents have department_id, team_id | Soft | Agent list works without org structure, just missing department labels |
| (None critical) | Agents is a foundational entity | — | Can be wired first |

### `/tasks` (Tasks)

| Depends On | Why | Hard/Soft | Notes |
|------------|-----|-----------|-------|
| `/agents` (Agents) | Tasks are assigned to agents | **Hard** | Need agent IDs to assign/display tasks |
| `/pipelines` (Pipelines) | Some tasks are pipeline steps | Soft | Tasks work standalone |

### `/pipelines` (Pipelines)

| Depends On | Why | Hard/Soft | Notes |
|------------|-----|-----------|-------|
| `/agents` (Agents) | Pipeline stages may reference executing agents | Soft | Pipelines run without agent display names |

### `/tools` (Tools)

| Depends On | Why | Hard/Soft | Notes |
|------------|-----|-----------|-------|
| `/agents` (Agents) | Tools are invoked by agents, invocation logs reference agent_id | Soft | Tool list works, invocation history needs agents |

### `/memory` (Memory)

| Depends On | Why | Hard/Soft | Notes |
|------------|-----|-----------|-------|
| `/agents` (Agents) | Memory entries are namespaced per agent | **Hard** | Need agent memory_namespace to query |
| `/knowledge` (Knowledge Base) | Memory graph may reference knowledge nodes | Soft | Core memory works without KB |

### `/budgets` (Budgets)

| Depends On | Why | Hard/Soft | Notes |
|------------|-----|-----------|-------|
| `/agents` (Agents) | Budget tracking per agent (budget_monthly_cents, spent_monthly_cents) | **Hard** | Budget data lives on agent model |
| `/tools` (Tools) | Tool invocations have cost_cents for spend tracking | Soft | Budget totals work from agent model alone |

### `/approvals` (Approvals)

| Depends On | Why | Hard/Soft | Notes |
|------------|-----|-----------|-------|
| `/agents` (Agents) | Approvals reference requesting agent | **Hard** | Need agent names for display |
| `/tasks` (Tasks) | Some approvals gate task execution | Soft | Approvals work standalone |

### `/goals` (Goals)

| Depends On | Why | Hard/Soft | Notes |
|------------|-----|-----------|-------|
| `/agents` (Agents) | Goals assigned to agents | Soft | Goals have their own model |
| `/tasks` (Tasks) | Goals may link to tasks for progress tracking | Soft | Goals work independently |

### `/workflows` (Workflows)

| Depends On | Why | Hard/Soft | Notes |
|------------|-----|-----------|-------|
| `/agents` (Agents) | Workflow steps reference agents | Soft | Workflow definitions work standalone |
| `/tasks` (Tasks) | Workflows generate tasks | Soft | Can define workflows without tasks |

### `/meetings` (Meetings)

| Depends On | Why | Hard/Soft | Notes |
|------------|-----|-----------|-------|
| `/agents` (Agents) | Meeting participants are agents | **Hard** | Need agent list for attendee display |

### `/evolution` (Evolution)

| Depends On | Why | Hard/Soft | Notes |
|------------|-----|-----------|-------|
| `/agents` (Agents) | Evolution tracks agent performance over time | **Hard** | Needs agent data |
| `/tasks` (Tasks) | Performance derived from task completion | Soft | Can show evolution with mock scores |

### `/skills` (Skills)

| Depends On | Why | Hard/Soft | Notes |
|------------|-----|-----------|-------|
| `/agents` (Agents) | Skills belong to agents | **Hard** | Need agent context |

### `/notifications` (Notifications)

| Depends On | Why | Hard/Soft | Notes |
|------------|-----|-----------|-------|
| `/agents` (Agents) | Notifications reference agents | Soft | Can show system notifications without agents |
| `/activity` (Activity) | Some notifications derive from activity events | Soft | Independent notification model exists |

### `/organization` (Organization)

| Depends On | Why | Hard/Soft | Notes |
|------------|-----|-----------|-------|
| `/agents` (Agents) | Org chart shows agents in departments/teams | **Hard** | Core of org page is agent hierarchy |

### `/settings` (Settings)

| Depends On | Why | Hard/Soft | Notes |
|------------|-----|-----------|-------|
| (None) | Settings is self-contained (company config) | — | Can be wired anytime |

### `/git-repos` (Git Repos)

| Depends On | Why | Hard/Soft | Notes |
|------------|-----|-----------|-------|
| (None critical) | Repositories are independent entities | — | Can be wired anytime |

### `/knowledge` (Knowledge Base)

| Depends On | Why | Hard/Soft | Notes |
|------------|-----|-----------|-------|
| `/agents` (Agents) | KB entries may reference authoring agent | Soft | KB works without agent names |

### `/dashboard` (Dashboard / Overview)

| Depends On | Why | Hard/Soft | Notes |
|------------|-----|-----------|-------|
| `/agents` (Agents) | Shows agent count, active agents | **Hard** | Core dashboard metric |
| `/tasks` (Tasks) | Shows task counts, completion rates | **Hard** | Core dashboard metric |
| `/budgets` (Budgets) | Shows spend overview | Soft | Dashboard works with partial data |
| `/activity` (Activity) | May show recent activity feed | Soft | Dashboard has its own summary |

---

## Recommended Wiring Order

Based on the dependency graph, the optimal order to wire pages is:

```
Phase 1 — Foundations (no dependencies)
  1. /agents          ← Almost everything depends on this
  2. /settings        ← Self-contained
  3. /git-repos       ← Self-contained

Phase 2 — Core Operations (depend on Agents)
  4. /tasks           ← Depends on Agents
  5. /tools           ← Depends on Agents
  6. /pipelines       ← Depends on Agents (soft)
  7. /memory          ← Depends on Agents
  8. /approvals       ← Depends on Agents

Phase 3 — Higher-Level Features (depend on Phase 2)
  9. /activity        ← Consumes from Agents, Tasks, Pipelines, Tools, Memory, Git
  10. /budgets        ← Depends on Agents + Tools
  11. /workflows      ← Depends on Agents + Tasks
  12. /meetings       ← Depends on Agents
  13. /goals          ← Depends on Agents + Tasks
  14. /organization   ← Depends on Agents
  15. /skills         ← Depends on Agents

Phase 4 — Aggregation & Polish
  16. /dashboard      ← Depends on Agents + Tasks + Budgets + Activity
  17. /evolution      ← Depends on Agents + Tasks
  18. /notifications  ← Depends on Agents + Activity
  19. /knowledge      ← Soft dependencies only
```

---

## Shared Backend Services

These backend components are used by multiple pages and should be built/verified early:

| Service/Component | Used By | Status |
|-------------------|---------|--------|
| Agent name resolver (id → name + title) | Activity, Tasks, Approvals, Meetings, Budgets, Dashboard | Needs: JOIN helper or denormalization |
| Company-scoped query base | All pages | EXISTS: `CurrentCompanyId` dependency |
| Pagination wrapper `{ items, total, limit, offset }` | All list pages | Needs: Standardized across routes |
| SSE event bus | Activity, Dashboard, Notifications | EXISTS: `RealtimeEventBus` |
| Audit log writer | Activity, all mutation endpoints | EXISTS: `AuditLog` model |
