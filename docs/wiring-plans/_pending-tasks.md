# Pending Tasks — Blocked by Other Pages

This file tracks features from each page that cannot be fully completed until another page is wired up. When a blocking page gets completed, come back here and resolve the pending items.

---

## How to Use

1. When wiring a page, if you hit a feature that needs another page's data, add it here.
2. Mark the **source page** (where the feature lives), the **blocking page** (what needs to be done first), and a brief description.
3. Once the blocking page is wired, check this file and resolve all items it unblocks.
4. Move resolved items to the "Completed" section at the bottom with a date.

---

# Pending Tasks — Blocked by Other Pages

This file tracks features from each page across the system. All tracked pending tasks have been **fully resolved and verified**.

---

## Active Pending Tasks

*(None — 100% of all tracked pending tasks are resolved.)*

---

## Completed (Resolved)

| ID | Feature | Resolved Date | Notes |
|----|---------|---------------|-------|
| ACT-1 | Agent name display | 2026-08-24 | Activity logs resolve agent UUIDs to human-readable names via Agents Registry. |
| ACT-2 | Task-category events | 2026-08-24 | Task lifecycle (create, status update, assign) emits structured AuditLog entries. |
| ACT-3 | Pipeline-category events | 2026-08-24 | Pipeline runs write execution events to AuditLog. |
| ACT-4 | Tool dispatch events with latency | 2026-08-24 | Tool invocations recorded with `duration_ms` telemetry. |
| ACT-5 | Memory-category events | 2026-08-24 | Memory node operations emit audit log entries. |
| ACT-6 | Git-category events | 2026-08-24 | Git events write audit log entries on push/merge. |
| ACT-7 | Policy/Budget threshold events | 2026-08-24 | Budget monitoring emits warning events on threshold approach. |
| ACT-8 | Real-time live stream | 2026-08-24 | Dedicated activity stream formatting live event data. |
| ACT-9 | Analytics: accurate agent leaderboard | 2026-08-24 | Leaderboard displays resolved agent names and performance metrics. |
| DASH-1 | Active agents count | 2026-08-24 | Dashboard stat card fetches real agent status counts. |
| DASH-2 | Task completion rate | 2026-08-24 | Task metrics calculate real completion rates. |
| DASH-3 | Recent activity feed | 2026-08-24 | Embedded mini activity feed wired to live endpoints. |
| DASH-4 | Budget burn rate | 2026-08-24 | Spend widget renders real budget data. |
| AGT-1 | Agent activity tab | 2026-08-24 | Agent detail drawer displays formatted per-agent telemetry events. |
| AGT-2 | Agent memory entries | 2026-08-24 | Memory tab wired to `LayeredMemoryStore` per-agent memories. |
| AGT-3 | Agent budget spend chart | 2026-08-24 | Telemetry tab renders token consumption and USD spend. |
| AGT-4 | Department/Team selector in hire modal | 2026-08-24 | Hire modal populated with live departments and teams. |
| AGT-5 | Manager selector in hire modal | 2026-08-24 | Manager dropdown populated with active agents. |
| AGT-6 | Agent lifecycle buttons (wake/pause) | 2026-08-24 | Wake/Pause buttons connected to `/agents/{id}/wake` and `/pause`. |
| ORG-1 | Org chart with real agents | 2026-08-24 | Org chart hierarchy renders live agent nodes. |
| NOTIF-1 | Activity-derived notifications | 2026-08-24 | Error and critical events generate bell notifications. |
