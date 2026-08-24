# /activity Page — Wiring Plan

## Summary

The Activity page is a real-time audit log and telemetry dashboard showing system events, agent tool dispatches, pipeline runs, policy checks, memory operations, and git events. It has three view modes (List, Terminal, Analytics) with filtering, search, live streaming, and JSON/CSV export.

---

## 1. What the Frontend Currently Expects

### Data Shape (`ActivityLog` interface)

```typescript
interface ActivityLog {
  id: string;                          // unique event id
  event: string;                       // event title/name
  type: ActivityCategory;              // 'Task' | 'Pipeline' | 'Agent' | 'System' | 'Git' | 'Policy' | 'Memory'
  description: string;                 // human-readable description
  agent: string;                       // agent display name (e.g. "Dwight (QA Lead)")
  time: string;                        // relative time label (e.g. "2m ago")
  timestamp: number;                   // unix epoch ms
  status: ActivityStatus;              // 'success' | 'failed' | 'in_progress'
  severity: ActivitySeverity;          // 'info' | 'warning' | 'error' | 'critical'
  latency_ms: number;                  // execution time in ms
  metadata?: string;                   // optional metadata string
  raw_payload?: Record<string, unknown>; // raw JSON payload for detail drawer
}
```

### API Call Made by Frontend

```typescript
GET /api/v1/companies/{company_id}/activity
// Expects: { items: ActivityLog[] }
```

### Frontend Features Requiring Backend Support

| Feature | Description | Backend Needed |
|---------|-------------|----------------|
| Initial load | Fetch paginated activity logs | GET endpoint returning `ActivityLog[]` shape |
| Live streaming | Real-time events pushed to client every ~4s | SSE or WebSocket stream |
| Category filter | Filter by type: Task, Pipeline, Agent, System, Git, Policy, Memory | Query param or server-side filter |
| Severity filter | Filter by severity: info, warning, error, critical | Query param |
| Status filter | Filter by status: success, failed, in_progress | Query param |
| Search | Full-text search across event, description, agent, id | Query param |
| Analytics: Event Velocity | Time-bucketed event counts over last 20min | Aggregation endpoint or client-side compute |
| Analytics: Severity Breakdown | Count by severity level | Aggregation endpoint or client-side compute |
| Analytics: Agent Leaderboard | Top 5 agents by event count | Aggregation endpoint or client-side compute |
| Export JSON/CSV | Download filtered logs | Client-side (already works with data) |
| Detail Drawer | Show full raw_payload JSON for a selected event | Included in list response |

---

## 2. What Already Exists in Backend

### Existing Endpoint: `GET /api/v1/companies/{company_id}/activity`

**File:** `src/nexus/api/routes/activity.py`

**Current Response Shape:**
```python
[
  {
    "id": str,
    "type": "audit",              # always "audit" — no category mapping
    "actor_type": str,            # "agent" | "user" | "system"
    "actor_id": str | None,
    "action": str,                # e.g. "agent.hired", "task.completed"
    "resource_type": str | None,  # e.g. "agent", "task", "pipeline"
    "resource_id": str | None,
    "details": dict | None,       # JSON blob
    "created_at": str (ISO),
  }
]
```

**Gap Analysis:**
- Returns a flat `list[dict]` — frontend expects `{ items: [...] }` wrapper
- No `event` (human-readable title) — has `action` (machine key like "agent.hired")
- No `severity` field — would need to be inferred from action type or added to model
- No `status` field — would need to be derived or stored
- No `latency_ms` — not tracked in `AuditLog` model
- No `agent` display name — only has `actor_id` UUID
- No `timestamp` as epoch ms — has `created_at` as ISO string
- No `description` — only `action` key
- No category mapping — always returns `"type": "audit"`
- No pagination metadata (total count)
- No filtering query params (category, severity, status, search)

### Existing Endpoint: `GET /events/stream` (SSE)

**File:** `src/nexus/api/routes/events.py`

**Supports:**
- Server-Sent Events streaming
- Filter by event_type (comma-separated)
- Filter by channel
- Tenant-scoped (company_id isolation)
- Keepalive every 30s

**Gap:** The SSE stream delivers `RealtimeEvent` objects which have `event_type`, `payload`, and `source_agent_id` but not the full `ActivityLog` shape the frontend expects.

### Existing Model: `AuditLog`

**File:** `src/nexus/models/governance.py`

| Column | Type | Maps to Frontend |
|--------|------|-----------------|
| id | UUID | `id` (convert to string) |
| company_id | UUID | (filter key) |
| actor_type | str(50) | partial → `type` category |
| actor_id | str(255) | need to resolve → `agent` name |
| action | str(255) | need to map → `event` title |
| resource_type | str(100) | helps determine `type` category |
| resource_id | str(255) | (for detail links) |
| details | JSON | → `raw_payload` |
| created_at | datetime | → `timestamp` (epoch ms) + `time` (relative) |

**Missing columns for full ActivityLog support:**
- `severity` (info/warning/error/critical)
- `status` (success/failed/in_progress)
- `latency_ms` (execution duration)
- `description` (human-readable summary)

### Other Relevant Data Sources

| Source | Model/Table | Useful For |
|--------|-------------|------------|
| `ToolInvocation` | `tool_invocations` | Task-type events with `status`, `duration_ms`, agent_id |
| `TriggerExecution` | `trigger_executions` | Agent execution events with `status`, `started_at`, `completed_at` |
| `PipelineRun` | `pipeline_runs` | Pipeline-type events with `status` |
| `Event` (communication) | `events` | System events with `event_type`, `payload` |

---

## 3. What Can Be Wired Up Directly (No Backend Changes)

### 3a. Use existing `/api/v1/companies/{company_id}/activity` with client-side transform

The frontend already tries to call this endpoint. We can add a transform layer that maps the current response to `ActivityLog[]`:

```typescript
// Transform backend AuditLog → frontend ActivityLog
function transformAuditLog(item: BackendActivity): ActivityLog {
  return {
    id: item.id,
    event: humanizeAction(item.action),           // "agent.hired" → "Agent Hired"
    type: mapCategory(item.resource_type, item.actor_type), // "agent" → "Agent"
    description: buildDescription(item),           // from details JSON
    agent: item.actor_id || 'System',             // UUID for now (resolve later)
    time: relativeTime(item.created_at),          // "2m ago"
    timestamp: new Date(item.created_at).getTime(),
    status: inferStatus(item.details),            // from details.status or default 'success'
    severity: inferSeverity(item.action, item.details), // heuristic
    latency_ms: item.details?.duration_ms || 0,
    raw_payload: item.details,
  };
}
```

**Limitation:** This gives us basic data but with poor quality — agent names are UUIDs, severity is guessed, latency is often 0.

### 3b. Use existing SSE `/events/stream` for live updates

The frontend currently simulates live events with `setInterval`. We can replace this with the real SSE endpoint:

```typescript
const eventSource = new EventSource(`/events/stream?company_id=${companyId}`);
eventSource.onmessage = (e) => {
  const event = JSON.parse(e.data);
  const log = transformRealtimeEvent(event);
  setLogs(prev => [log, ...prev.slice(0, 49)]);
};
```

**Limitation:** SSE events don't carry all fields needed (no latency, no severity, no agent name).

---

## 4. What Needs to Be Added in Backend

### 4a. Enhanced Activity Endpoint (HIGH PRIORITY)

**Change:** Rewrite `GET /api/v1/companies/{company_id}/activity` to return the full shape.

**New response format:**
```python
{
  "items": [ActivityLogResponse],
  "total": int,
  "limit": int,
  "offset": int
}
```

**New query params:**
```
?limit=50          # pagination
&offset=0          # pagination
&type=Agent        # category filter (Task|Pipeline|Agent|System|Git|Policy|Memory)
&severity=error    # severity filter
&status=failed     # status filter
&search=keyword    # full-text search across event, description, agent name
```

**Implementation approach:**
- Query `AuditLog` as primary source
- JOIN with `agents` table to resolve `actor_id` → agent name + title
- Add computed fields: `severity` (from action patterns), `status`, `latency_ms`
- Map `resource_type` to frontend category
- Add full-text search on `action` + `details`

### 4b. Add Missing Columns to AuditLog Model (MEDIUM PRIORITY)

**File to modify:** `src/nexus/models/governance.py`

Add optional fields:
```python
severity: Optional[str] = Field(default="info", max_length=20)    # info|warning|error|critical
status: Optional[str] = Field(default="success", max_length=20)   # success|failed|in_progress
duration_ms: Optional[int] = Field(default=None)                   # execution latency
description: Optional[str] = Field(default=None)                   # human-readable summary
category: Optional[str] = Field(default=None, max_length=50)       # Task|Pipeline|Agent|System|Git|Policy|Memory
```

**Requires:** Alembic migration

### 4c. Unified Activity Feed Service (MEDIUM PRIORITY)

Create a service that aggregates multiple sources into a single activity stream:

**New file:** `src/nexus/services/activity_feed.py`

Sources to aggregate:
1. `AuditLog` — all audit entries
2. `ToolInvocation` — tool dispatch events (has `duration_ms`, `status`)
3. `TriggerExecution` — trigger fires (has `status`, timing)
4. `PipelineRun` — pipeline executions (has `status`, timing)
5. `Event` (communication) — system events

Each source maps to a category:
| Source | → Category |
|--------|-----------|
| AuditLog (action starts with "agent.") | Agent |
| AuditLog (action starts with "task.") | Task |
| AuditLog (action starts with "policy.") | Policy |
| ToolInvocation | Task |
| TriggerExecution | Agent |
| PipelineRun | Pipeline |
| Event (event_type = "system_alert") | System |
| Event (event_type contains "git") | Git |
| AuditLog (resource_type = "memory") | Memory |

### 4d. Activity-Specific SSE Channel (LOW PRIORITY)

Enhance the SSE stream to emit activity-formatted events:

**Approach:** When any of the source tables gets a new row, publish a `RealtimeEvent` with `event_type="activity_log"` and payload matching `ActivityLog` shape.

This lets the frontend subscribe to `GET /events/stream?event_types=activity_log` and get properly formatted live updates.

### 4e. Activity Summary/Stats Endpoint (LOW PRIORITY)

```
GET /api/v1/companies/{company_id}/activity/stats
```

Returns pre-computed aggregates for the analytics view:
```json
{
  "total_events": 1284,
  "success_rate": 94.2,
  "avg_latency_ms": 142,
  "active_categories": 7,
  "severity_breakdown": { "info": 980, "warning": 210, "error": 80, "critical": 14 },
  "top_agents": [{ "agent_id": "...", "name": "Atlas-01", "count": 312 }],
  "velocity_buckets": [{ "bucket": "0-2min", "events": 12, "errors": 1 }]
}
```

---

## 5. Implementation Order

### Phase 1: Quick Wire-Up (frontend changes only)

1. **Fix response shape expectation** — The backend returns `list[dict]`, not `{ items: [...] }`. Update the frontend `useEffect` to handle both:
   ```typescript
   const data = await apiClient.get<ActivityLog[] | { items: ActivityLog[] }>(...);
   const items = Array.isArray(data) ? data : data.items;
   ```

2. **Add client-side transform** — Map the current backend response fields to `ActivityLog` shape.

3. **Replace hardcoded company ID** — Use `getActiveCompanyId()` instead of `'00000000-0000-4000-8000-000000000001'`.

4. **Wire up SSE for live updates** — Replace `setInterval` mock with real `/events/stream` EventSource.

### Phase 2: Backend Enhancements (backend changes)

5. **Add query params to activity endpoint** — `type`, `severity`, `status`, `search`, proper `limit`/`offset`.

6. **Add columns to AuditLog** — `severity`, `status`, `duration_ms`, `description`, `category`. Create Alembic migration.

7. **Join agent names** — Resolve `actor_id` to agent `name` + `title` in the response.

8. **Wrap response** — Return `{ items: [...], total, limit, offset }` instead of bare list.

### Phase 3: Rich Activity Feed (new service)

9. **Create `ActivityFeedService`** — Aggregate from AuditLog + ToolInvocation + TriggerExecution + PipelineRun + Event.

10. **Add activity SSE channel** — Publish formatted activity events on data changes.

11. **Add `/activity/stats` endpoint** — Pre-computed analytics data.

### Phase 4: Frontend Final Polish

12. **Update frontend to use new response format** — Remove transforms, use server data directly.

13. **Connect filters to API query params** — Instead of client-side filtering, pass to API.

14. **Replace mock live stream with SSE activity channel.**

---

## 6. Dependencies on Other Pages

| Dependency | Why | Status |
|------------|-----|--------|
| **Agents page** | Need agent names resolved from UUIDs. The agents table must be populated. | Agents API exists (`GET /api/v1/companies/{id}/agents`) |
| **Pipelines page** | Pipeline category events come from `pipeline_runs` table | Pipeline API exists (`GET /api/v1/companies/{id}/pipelines`) |
| **Tasks page** | Task events come from task completions | Tasks API exists |
| **Tools page** | Tool dispatch events come from `tool_invocations` | Tools API exists |
| **Memory page** | Memory category events | Memory API exists |
| **Git Repos page** | Git-type events (webhook, PR) | Git repos API exists |

**Key Insight:** The Activity page is primarily a **consumer** of data from other pages/modules. It doesn't block any other page but benefits from all of them being active. The only hard dependency is having agents in the database so we can resolve names.

---

## 7. Files to Create/Modify

### Backend
| File | Action | Purpose |
|------|--------|---------|
| `src/nexus/models/governance.py` | MODIFY | Add severity, status, duration_ms, description, category to AuditLog |
| `alembic/versions/xxx_add_activity_fields.py` | CREATE | Migration for new columns |
| `src/nexus/api/routes/activity.py` | MODIFY | Add query params, join agents, wrap response, unified feed |
| `src/nexus/services/activity_feed.py` | CREATE | Unified activity aggregation service |

### Frontend
| File | Action | Purpose |
|------|--------|---------|
| `dashboard/src/pages/Activity.tsx` | MODIFY | Fix API call, add transforms, wire SSE, use dynamic company ID |
| `dashboard/src/api/activity.ts` | CREATE | Dedicated activity API module with types and transforms |

---

## 8. Risk Assessment

| Risk | Impact | Mitigation |
|------|--------|------------|
| AuditLog table has no data yet | Page shows empty | Keep fallback to mock data if API returns empty |
| Agent name resolution slows query | Latency on load | Add JOIN or denormalize agent name into audit log |
| SSE connection drops | Live feed stops | Auto-reconnect with exponential backoff |
| Migration breaks existing data | Data loss | Migration only adds nullable columns |
