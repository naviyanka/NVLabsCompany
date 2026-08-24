# Pending Tasks — Blocked by Other Pages

This file tracks features from each page that cannot be fully completed until another page is wired up. When a blocking page gets completed, come back here and resolve the pending items.

---

## How to Use

1. When wiring a page, if you hit a feature that needs another page's data, add it here.
2. Mark the **source page** (where the feature lives), the **blocking page** (what needs to be done first), and a brief description.
3. Once the blocking page is wired, check this file and resolve all items it unblocks.
4. Move resolved items to the "Completed" section at the bottom with a date.

---

## Active Pending Tasks

### From: `/activity`

| ID | Feature | Blocked By | Description | Priority |
|----|---------|------------|-------------|----------|
| ACT-1 | Agent name display | `/agents` wired + agents in DB | Activity logs show agent UUIDs instead of human-readable names like "Dwight (QA Lead)". Need agents table populated and a JOIN or lookup in the activity endpoint. | HIGH |
| ACT-2 | Task-category events | `/tasks` generating audit logs | No Task-type activity events will appear until the tasks system writes to AuditLog on task create/complete/fail. | MEDIUM |
| ACT-3 | Pipeline-category events | `/pipelines` generating audit logs | No Pipeline-type events until pipeline runs write to AuditLog or we aggregate from `pipeline_runs` table. | MEDIUM |
| ACT-4 | Tool dispatch events with latency | `/tools` invocations being recorded | Tool dispatch events with real `duration_ms` require `tool_invocations` records. Currently the ToolInvocation model exists but needs active recording. | MEDIUM |
| ACT-5 | Memory-category events | `/memory` operations generating events | Memory graph operations (node add, contradiction detection) need to emit events or audit log entries. | LOW |
| ACT-6 | Git-category events | `/git-repos` webhook integration | Git events (push, PR, merge) require webhook receiver to write audit entries when git events arrive. | LOW |
| ACT-7 | Policy/Budget threshold events | `/budgets` threshold monitoring | Policy-category events about budget thresholds need budget monitoring to emit warnings when limits are approached. | LOW |
| ACT-8 | Real-time live stream (proper format) | SSE activity channel built | The live stream currently would use raw `RealtimeEvent` format. Need a dedicated activity SSE channel that emits properly shaped `ActivityLog` events. | MEDIUM |
| ACT-9 | Analytics: accurate agent leaderboard | `/agents` wired | Agent leaderboard in analytics view needs resolved agent names, not UUIDs. | LOW |

---

### From: `/dashboard` (future — when we wire dashboard)

| ID | Feature | Blocked By | Description | Priority |
|----|---------|------------|-------------|----------|
| DASH-1 | Active agents count | `/agents` wired | Dashboard "Active Agents" stat card needs real agent status data. | HIGH |
| DASH-2 | Task completion rate | `/tasks` wired | Dashboard task metrics need real task data. | HIGH |
| DASH-3 | Recent activity feed | `/activity` wired | Dashboard may embed a mini activity feed. | MEDIUM |
| DASH-4 | Budget burn rate | `/budgets` wired | Dashboard spend widget needs real budget data. | LOW |

---

### From: `/agents` (future — when we wire agents detail page)

| ID | Feature | Blocked By | Description | Priority |
|----|---------|------------|-------------|----------|
| AGT-1 | Agent activity tab | `/activity` per-agent endpoint | AgentDetailPage has a telemetry tab that needs `GET /api/v1/agents/{id}/activity` returning formatted events. | MEDIUM |
| AGT-2 | Agent memory entries | `/memory` wired | AgentDetailPage "Context Memory Entries" tab needs memory API per agent. | MEDIUM |
| AGT-3 | Agent budget spend chart | `/budgets` + `/tools` wired | Token consumption telemetry tab needs tool invocation cost data. | LOW |

---

### From: `/agents`

| ID | Feature | Blocked By | Description | Priority |
|----|---------|------------|-------------|----------|
| AGT-4 | Department/Team selector in hire modal | `/organization` wired (departments + teams API) | Hire modal needs to list available departments and teams for assignment. Without it, agents are created without org placement. | MEDIUM |
| AGT-5 | Manager selector in hire modal | Agents already in DB | The manager dropdown needs existing agents to choose from. First-run scenario has no agents to pick. | LOW |
| AGT-6 | Agent lifecycle buttons (wake/pause) | None — ready now | API exists (`/agents/{id}/wake`, `/agents/{id}/pause`), just needs frontend buttons. No blocker. | HIGH |

### From: `/organization` (future)

| ID | Feature | Blocked By | Description | Priority |
|----|---------|------------|-------------|----------|
| ORG-1 | Org chart with real agents | `/agents` wired | Org chart hierarchy needs agents with department_id, team_id, manager_id populated. | HIGH |

---

### From: `/notifications` (future)

| ID | Feature | Blocked By | Description | Priority |
|----|---------|------------|-------------|----------|
| NOTIF-1 | Activity-derived notifications | `/activity` wired | Some notifications (errors, critical events) should auto-generate from activity stream. | LOW |

---

## Resolution Checklist

When you complete wiring a page, check which pending tasks it unblocks:

| Page Completed | Unblocks |
|----------------|----------|
| `/agents` | ACT-1, ACT-9, AGT-5, DASH-1, AGT-1, AGT-2, AGT-3, ORG-1 |
| `/organization` | AGT-4 |
| `/tasks` | ACT-2, DASH-2 |
| `/pipelines` | ACT-3 |
| `/tools` | ACT-4, AGT-3 |
| `/memory` | ACT-5, AGT-2 |
| `/git-repos` | ACT-6 |
| `/budgets` | ACT-7, DASH-4, AGT-3 |
| `/activity` (full) | DASH-3, AGT-1, NOTIF-1 |
| SSE activity channel | ACT-8 |

---

## Completed (Resolved)

_Move items here once the blocking page is wired and the feature is implemented._

| ID | Feature | Resolved Date | Notes |
|----|---------|---------------|-------|
| — | — | — | _(none yet)_ |
