# API Gaps Plan — Frontend Features Missing Backend Endpoints

> **STALE — do not trust status claims in this document.**
> Last verified against commit: never. Superseded by `docs/GAP-CLOSURE-PLAN.md`
> (verified against commit `1bbad4a`, 2026-08-26), which is the single source of
> truth for what is actually wired. Percentages and "complete" markers below are
> historical intent, not measured state.

## Current State
- **105 API endpoints** exist in the backend
- **24 dashboard pages** exist in the frontend
- Several pages use hardcoded mock data instead of API calls

---

## Pages Already Wired to Backend ✅

| Page | API Used | Status |
|------|----------|--------|
| Agents (list) | `GET /api/v1/companies/{id}/agents` | ✅ Working |
| Agent Detail | `GET /api/v1/agents/{id}`, PUT, DELETE, wake, pause | ✅ Working |
| Office (3D) | No API needed (static 3D scene) | ✅ Working |
| Settings | Client-side only (no persistence API) | ⚠️ No backend |
| Notifications | Client-side only (no persistence API) | ⚠️ No backend |

---

## APIs Needed Per Feature

### 1. Notifications System
**Currently:** Client-side state only, mock data  
**Needs:**

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/api/v1/companies/{id}/notifications` | GET | List notifications (paginated, filterable) |
| `/api/v1/notifications/{id}/read` | POST | Mark single notification as read |
| `/api/v1/notifications/read-all` | POST | Mark all as read |
| `/api/v1/notifications/{id}` | DELETE | Dismiss notification |
| `/api/v1/notifications/preferences` | GET/PUT | Get/update notification preferences |

**Model needed:** `Notification` (id, company_id, title, description, type, module, priority, read, created_at)

---

### 2. Dashboard Overview
**Currently:** Hardcoded mock stats and charts  
**Needs:**

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/api/v1/companies/{id}/stats` | GET | Agent counts by status, task counts, budget usage |
| `/api/v1/companies/{id}/activity-feed` | GET | Recent activity items (agent actions, task completions) |
| `/api/v1/companies/{id}/metrics/daily` | GET | Daily metrics for charts (tasks/day, cost/day, tokens) |

---

### 3. Tasks Page
**Currently:** Mock data  
**Needs:** Already has endpoints but page isn't wired

| Endpoint | Exists? | Wire to Page |
|----------|---------|--------------|
| `GET /api/v1/companies/{id}/tasks` | ✅ | Wire to Tasks page |
| `POST /api/v1/companies/{id}/tasks` | ✅ | Wire create button |
| `PUT /api/v1/tasks/{id}/status` | ✅ | Wire status changes |
| `PUT /api/v1/tasks/{id}/assign` | ✅ | Wire assign dropdown |

---

### 4. Pipelines Page
**Currently:** Fully mock  
**Needs:**

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/api/v1/companies/{id}/pipelines` | GET | List pipelines |
| `/api/v1/companies/{id}/pipelines` | POST | Create pipeline |
| `/api/v1/pipelines/{id}` | GET | Pipeline detail with stages |
| `/api/v1/pipelines/{id}/run` | POST | Trigger pipeline execution |
| `/api/v1/pipelines/{id}/runs` | GET | Execution history |
| `/api/v1/pipelines/{id}/runs/{run_id}` | GET | Run detail with step results |

**Model needed:** `Pipeline`, `PipelineStage`, `PipelineRun`  
**Note:** `src/nexus/workflows/pipeline.py` exists with `PipelineCase` model — wire to API route

---

### 5. Memory Page
**Currently:** Mock data  
**Needs:** Endpoints exist but page isn't wired

| Endpoint | Exists? | Wire to Page |
|----------|---------|--------------|
| `GET /api/v1/agents/{id}/memory` | ✅ | Wire to memory list |
| `GET /api/v1/agents/{id}/memory/search` | ✅ | Wire to search |
| `POST /api/v1/agents/{id}/memory` | ✅ | Wire to create |

**Additional needed:**
| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/api/v1/companies/{id}/memory/stats` | GET | Memory tier stats (hot/warm/cold counts, sizes) |
| `/api/v1/companies/{id}/memory/search` | POST | Cross-agent memory search |

---

### 6. Knowledge Base Page
**Currently:** Mock data  
**Needs:** Endpoints exist but page isn't wired

| Endpoint | Exists? | Wire to Page |
|----------|---------|--------------|
| `GET /api/v1/companies/{id}/knowledge` | ✅ | Wire to page list |
| `POST /api/v1/companies/{id}/knowledge` | ✅ | Wire to publish |
| `GET /api/v1/knowledge/{id}` | ✅ | Wire to page detail |
| `PUT /api/v1/knowledge/{id}` | ✅ | Wire to edit |
| `POST /api/v1/companies/{id}/knowledge/search` | ✅ | Wire to search |

---

### 7. Git Repos Page
**Currently:** Fully mock  
**Needs:**

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/api/v1/companies/{id}/repos` | GET | List connected repositories |
| `/api/v1/companies/{id}/repos` | POST | Connect a repository |
| `/api/v1/repos/{id}` | GET | Repo detail (branches, stats) |
| `/api/v1/repos/{id}/commits` | GET | Recent commits |
| `/api/v1/repos/{id}/pull-requests` | GET | Open PRs |
| `/api/v1/repos/{id}/disconnect` | POST | Remove repo connection |

**Model needed:** `Repository`, `Commit`, `PullRequest`

---

### 8. HR Room Page
**Currently:** Mock hiring data  
**Needs:** Partially exists

| Endpoint | Exists? | Purpose |
|----------|---------|---------|
| `POST /api/v1/companies/{id}/hiring/create-agent` | ✅ | Create from template |
| `POST /api/v1/companies/{id}/hiring/job-description` | ✅ | Generate job desc |
| `POST /api/v1/companies/{id}/hiring/{agent_id}/onboarding` | ✅ | Onboard agent |

**Additional needed:**
| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/api/v1/companies/{id}/hiring/candidates` | GET | List hiring candidates/queue |
| `/api/v1/companies/{id}/hiring/templates` | GET | Available agent templates |

---

### 9. Goals/OKRs Page
**Currently:** Mock data  
**Needs:** Endpoints exist but page isn't wired

| Endpoint | Exists? | Wire to Page |
|----------|---------|--------------|
| `GET /api/v1/companies/{id}/goals` | ✅ | Wire to goals list |
| `POST /api/v1/companies/{id}/goals` | ✅ | Wire create |
| `GET /api/v1/goals/{id}` | ✅ | Wire detail |
| `PUT /api/v1/goals/{id}` | ✅ | Wire update |
| `GET /okrs/objectives` | ✅ | Wire OKRs |
| `POST /okrs/key-results/{id}/progress` | ✅ | Wire progress update |

---

### 10. Meetings Page
**Currently:** Mock data  
**Needs:** Endpoints exist but page isn't wired

| Endpoint | Exists? | Wire to Page |
|----------|---------|--------------|
| `GET /api/v1/companies/{id}/meetings` | ✅ | Wire to meetings list |
| `POST /api/v1/companies/{id}/meetings` | ✅ | Wire schedule |
| `GET /api/v1/meetings/{id}` | ✅ | Wire detail |
| `POST /api/v1/meetings/{id}/start` | ✅ | Wire start button |
| `POST /api/v1/meetings/{id}/end` | ✅ | Wire end button |
| `GET /api/v1/meetings/{id}/minutes` | ✅ | Wire minutes view |

---

### 11. Activity Page
**Currently:** Mock timeline  
**Needs:**

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/api/v1/companies/{id}/activity` | GET | Company-wide activity feed (paginated) |
| `/api/v1/agents/{id}/activity` | GET | Per-agent activity log |

**Model needed:** `ActivityEvent` (or use existing `AuditLog` + `Event` tables)

---

### 12. Agent Execution Logs
**Currently:** Mock logs in agent detail  
**Needs:**

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/api/v1/agents/{id}/logs` | GET | Agent execution logs (paginated, level filter) |
| `/api/v1/agents/{id}/logs/stream` | GET (SSE) | Real-time log streaming |

---

### 13. Settings Persistence
**Currently:** Client-side only  
**Needs:**

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/api/v1/companies/{id}/settings` | GET | Load company settings |
| `/api/v1/companies/{id}/settings` | PUT | Save company settings |
| `/api/v1/users/me/preferences` | GET/PUT | User preferences (theme, timezone, etc.) |

**Model needed:** `CompanySettings` (JSON blob per company), `UserPreferences`

---

### 14. Real-Time Events (WebSocket)
**Currently:** No real-time updates  
**Needs:**

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/ws/events` | WebSocket | Real-time agent status changes, task completions, notifications |

**Already exists:** `/events/stream` (SSE) — wire to frontend EventSource

---

## Priority Order

### Phase A — Wire existing endpoints to pages (no backend changes)
1. Tasks page → use existing task endpoints
2. Goals page → use existing goal endpoints
3. Meetings page → use existing meeting endpoints
4. Knowledge Base → use existing knowledge endpoints
5. Memory page → use existing memory endpoints
6. Evolution page → use existing evolution endpoints
7. Approvals page → use existing approval endpoints

### Phase B — Create missing endpoints
1. Notifications (model + CRUD + preferences)
2. Dashboard stats aggregation endpoint
3. Activity feed endpoint (aggregate from audit log)
4. Agent execution logs endpoint
5. Settings persistence (company + user)

### Phase C — New feature endpoints
1. Pipelines (model + CRUD + run)
2. Git Repos (model + CRUD + webhook)
3. Real-time WebSocket bridge

---

## Summary

| Category | Count |
|----------|-------|
| Pages needing just frontend wiring (APIs exist) | 7 |
| Pages needing new backend endpoints | 6 |
| Total new endpoints to create | ~25 |
| Total new models to create | 4 (Notification, Pipeline, Repository, ActivityEvent) |
