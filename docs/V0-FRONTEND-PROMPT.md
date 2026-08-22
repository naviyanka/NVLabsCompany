# NEXUS Mission Control — Complete Frontend Design Prompt for V0.dev

## PROJECT OVERVIEW

Build a complete dark-themed Mission Control dashboard for **NEXUS** — an Autonomous AI Company Operating System. This is a full-stack React application where AI agents work as employees in a virtual company. The dashboard manages agents, tasks, pipelines, memory, knowledge, meetings, budgets, governance, and a 3D office visualization.

**Tech Stack:**
- React 19 + TypeScript
- Vite 6
- Tailwind CSS 3.4
- React Router v7
- Recharts (charts)
- Lucide React (icons)
- Babylon.js (3D office — separate module)

**Backend API:** FastAPI at `http://localhost:8000` with 178 REST endpoints. All requests include `X-Company-Id` header for multi-tenant isolation. Company ID: `00000000-0000-4000-8000-000000000001`.

---

## DESIGN SYSTEM

### Theme
- **Background:** `#020817` (near-black navy)
- **Surface:** `#0B1626` (cards, panels)
- **Border:** `rgba(255,255,255,0.06-0.08)`
- **Text Primary:** `#FFFFFF`
- **Text Secondary:** `#9CA3AF` (gray-400)
- **Text Muted:** `#6B7280` (gray-500)
- **Primary:** `#6366F1` (indigo-500)
- **Success:** `#22C55E` (green-500)
- **Warning:** `#F59E0B` (amber-500)
- **Danger:** `#EF4444` (red-500)
- **Info:** `#3B82F6` (blue-500)
- **Accent:** `#14B8A6` (teal-500)

### Typography
- Font: Inter (system fallback: -apple-system, sans-serif)
- Headings: Bold, white
- Body: text-sm (14px)
- Labels: text-xs (12px), text-[10px] for micro-labels
- Monospace: JetBrains Mono for IDs, code, timestamps

### Component Patterns
- Cards: `bg-white/[0.03] border border-white/[0.06] rounded-xl`
- Buttons: `px-4 py-2 rounded-lg text-sm font-medium`
- Inputs: `bg-[#020817] border border-white/[0.08] rounded-lg px-3 py-2 text-white text-sm`
- Badges: `px-2 py-0.5 text-[10px] rounded-full`
- Toggles: `w-9 h-5 rounded-full` with sliding dot
- Tables: No visible borders, `border-b border-white/[0.04]` between rows

---

## LAYOUT STRUCTURE

### Sidebar (fixed left, 264px wide)
- Logo: "NVLABS" with "Mission Control" subtitle
- Navigation links with icons:
  - Overview (dashboard icon)
  - Office (building icon)
  - HR Room (users icon) — with "New" badge
  - Agents (robot icon) — expandable
  - Tasks (list icon) — expandable
  - Pipelines (workflow icon) — expandable
  - Memory (brain icon)
  - Git Repos (git icon)
  - Knowledge Base (book icon)
  - Activity (activity icon)
  - Notifications (bell icon) — with count badge "12"
  - Settings (gear icon)
- System Status section at bottom:
  - Gateway: Online (green dot)
  - WebSocket: Connected (green dot)
  - Database: Healthy (green dot)
  - Memory Store: Healthy (green dot)
  - Vector DB: Healthy (green dot)
- User avatar + name "Navi Yanka" / "Administrator" at very bottom

### Header (top bar)
- Search bar: "Search agents, tasks, pipelines..." with Ctrl+K shortcut badge
- Tab switcher: "Dashboard" | "Office" (pill toggle)
- User avatar + name on right

### Main Content Area
- `ml-[264px]` offset for sidebar
- `p-6` padding
- Pages render here via React Router

---

## PAGES (24 total)

---

### 1. DASHBOARD (Overview) — `/`

**API Endpoints Used:**
- `GET /api/v1/companies/{id}/stats` — agent/task/budget counts
- `GET /api/v1/companies/{id}/metrics/daily` — 7-day chart data
- `GET /api/v1/companies/{id}/dashboard/top-agents` — top performers
- `GET /api/v1/companies/{id}/dashboard/pipelines-summary` — active pipelines
- `GET /api/v1/companies/{id}/dashboard/token-usage` — 24h token chart
- `GET /api/v1/companies/{id}/activity` — recent activity feed

**Layout:** Single page with stat cards + charts + activity feed

**Components:**
1. **5 Stat Cards** (horizontal grid):
   - Active Agents: count/total, +X% change, purple icon
   - Active Tasks: count/total, +X% change, blue icon
   - Pipelines: count/total, +X% change, green icon
   - Token Usage (24h): number, change %, amber icon
   - Est. Spend (24h): $amount, change %, pink icon

2. **Token & Cost Chart** (large, takes 60% width):
   - ComposedChart with area (tokens) + line (cost)
   - 24-hour X-axis, dual Y-axes
   - Gradient fill under token area

3. **Active Pipelines** (right sidebar card):
   - Pipeline name + progress bar (colored per pipeline)
   - 4-5 items

4. **Live Activity Feed** (card):
   - Icon + text + timestamp per row
   - Green checkmarks, orange flames, purple brain, blue git, red alerts
   - 5-6 recent items with "View All" link

5. **Recent Tasks** (card):
   - Task name, assigned agent, progress bar, timestamp
   - 4 items

6. **Top Agents** (card):
   - Agent name, score bar, model name
   - 4 items with gradient score indicators

7. **Quick Actions** (bottom):
   - "Add Agent" → navigates to /agents (hire modal)
   - "Create Task" → navigates to /tasks
   - "New Pipeline" → navigates to /pipelines
   - "Open HR Room" → navigates to /hr-room

**Every stat card is clickable** → navigates to the relevant page.

---

### 2. AGENTS — `/agents`

**API Endpoints:**
- `GET /api/v1/companies/{id}/agents?page_size=50` — list agents
- `POST /api/v1/companies/{id}/agents` — create agent
- `POST /api/v1/agents/{id}/wake` — wake agent
- `POST /api/v1/agents/{id}/pause` — pause agent
- `DELETE /api/v1/agents/{id}` — delete agent
- `GET /api/v1/adapters/cli-backends` — installed IDE backends

**Layout:** Stats row + search/filter + agent card grid

**Components:**
1. **Header**: "Agents" title + "X agents in your workforce" + green "Hire Agent" button
2. **Stats Row** (5 cards): Total, Working, Idle, Paused, Error — each with count in its status color
3. **Search Bar** + Status dropdown filter
4. **Agent Cards Grid** (3 columns):
   - Each card: avatar initial (colored by status), name, title, status badge, model, capabilities tags (max 3 + "+N"), Wake/Pause/Delete buttons at bottom
   - Click card → navigate to `/agents/{id}`

5. **"Hire Agent" Modal** (on button click):
   - Agent Type toggle: "LLM Provider" | "IDE / CLI Agent"
   - If LLM: Provider dropdown (OpenAI/Anthropic/Ollama) + Model dropdown (contextual to provider)
   - If CLI: Shows list of backends fetched from API with green/red installed status dots, version, and path
   - Form fields: Name*, Title, Role (select), Budget, Responsibilities, Capabilities (tag input)
   - "Hire Agent" submit button → calls POST create

---

### 3. AGENT DETAIL — `/agents/:id`

**API Endpoints:**
- `GET /api/v1/agents/{id}` — agent data
- `PUT /api/v1/agents/{id}` — update agent
- `POST /api/v1/agents/{id}/wake` — wake
- `POST /api/v1/agents/{id}/pause` — pause
- `DELETE /api/v1/agents/{id}` — delete

**Layout:** Profile header + tab navigation + 3-column content

**Profile Header:**
- Large avatar (gradient circle with initial)
- Name + status badge + role pill
- Description (soul_description or responsibilities)
- Meta: Role | Model | Joined date
- "Talk to Agent" button (opens chat modal)
- "Actions ▾" dropdown (Wake/Pause/Assign Task/View Memory/Edit/Delete)

**Tabs:** Overview | Skills | Memory | Tasks | Performance | Settings | Logs | Activity

**Overview Tab (3 columns):**
- LEFT: 5 metric cards + Current Workload (active task progress + task queue) + Skills table
- CENTER: Performance line chart (7 days) + mini stats + Recent Activity timeline
- RIGHT: Agent Information table + Resource Usage bars + Capabilities tags + Quick Actions grid

**Skills Tab:** Skills table with proficiency bars + all capabilities
**Memory Tab:** Memory entries with tier indicators (hot/warm/cold)
**Tasks Tab:** Task queue table with status/priority/progress
**Performance Tab:** Line chart + bar chart + metric cards
**Settings Tab:** Editable form (name, title, role, model, budget, responsibilities) with Save button
**Logs Tab:** Terminal-style log viewer with timestamps and color-coded levels
**Activity Tab:** Timeline with icons, categories, timestamps

---

### 4. OFFICE (3D) — `/office`

**No API needed** — Babylon.js 3D scene

**Layout:** Full-height canvas with overlay panels

**Components:**
- Top stats bar: "3D Office" label + green dot + control instructions
- Babylon.js canvas (isometric view of office floor plan)
- Agent panel (on agent click): name, role, status, task
- Room panel (on room click): name, type, access, agent count
- 16 rooms: 6 team cabins, manager cabin, meeting hall, 2 discussion rooms, server room, storage, utility, reception, waiting area, open workspace
- 12 robot agents walking between rooms
- Interactive doors (click to open/close)
- Camera: drag=rotate, scroll=zoom, right-drag=pan

---

### 5. TASKS — `/tasks`

**API Endpoints:**
- `GET /api/v1/companies/{id}/tasks` — list tasks
- `GET /api/v1/companies/{id}/tasks/stats` — statistics
- `POST /api/v1/companies/{id}/tasks` — create task
- `PUT /api/v1/tasks/{id}/status` — update status
- `PUT /api/v1/tasks/{id}/assign` — assign agent
- `POST /api/v1/tasks/{id}/reassign` — reassign
- `POST /api/v1/tasks/{id}/cancel` — cancel
- `GET /api/v1/tasks/{id}/subtasks` — subtasks
- `POST /api/v1/tasks/{id}/subtasks` — create subtask

**Layout:** Stats + tabs + table + detail panel (right sidebar)

**Components:**
1. Stats row: Total, Completed, In Progress, Pending, Failed/Blocked
2. Tab bar: All Tasks | My Tasks | Assigned to Agents | Completed | Blocked
3. Filter bar: Search + Status/Agent/Pipeline/Priority dropdowns + "Create Task" button
4. Task table: Checkbox, name+category, pipeline badge, agent, priority (colored dot), status badge, progress bar, time
5. Detail side panel (on row click): Task name, status, agent, progress bar, tabs (Overview/Subtasks/Artifacts/Logs), activity timeline
6. Status distribution donut chart (right sidebar)
7. Priority bar chart
8. Top agents by task count

---

### 6. PIPELINES — `/pipelines`

**API Endpoints:**
- `GET /api/v1/companies/{id}/pipelines` — list
- `GET /api/v1/companies/{id}/pipelines/stats` — stats
- `GET /api/v1/companies/{id}/pipelines/templates` — templates
- `POST /api/v1/companies/{id}/pipelines` — create
- `GET /api/v1/pipelines/{id}` — detail
- `POST /api/v1/pipelines/{id}/run` — execute
- `POST /api/v1/pipelines/{id}/pause` — pause
- `POST /api/v1/pipelines/{id}/stop` — stop
- `GET /api/v1/pipelines/{id}/runs` — execution history

**Layout:** Stats + pipeline flow visualization + execution history

**Components:**
1. Stats row: Total Pipelines, Active, Completed (24h), Failed (24h), Avg Execution Time, Success Rate
2. Pipeline Studio (large center): Visual flow diagram showing connected nodes (stages), play/pause/stop controls, zoom
3. Recent executions table (below): pipeline name, status, duration, steps completed
4. Templates sidebar: browsable pipeline templates with "Use Template" button
5. "New Pipeline" button opens create form

---

### 7. MEMORY — `/memory`

**API Endpoints:**
- `GET /api/v1/companies/{id}/memory` — list all memories
- `GET /api/v1/companies/{id}/memory/stats` — statistics
- `GET /api/v1/companies/{id}/memory/health` — health metrics
- `GET /api/v1/memory/{id}` — detail
- `PATCH /api/v1/memory/{id}` — update
- `DELETE /api/v1/memory/{id}` — delete
- `POST /api/v1/memory/{id}/archive` — archive

**Layout:** Stats + tabs + memory list + detail panel

**Components:**
1. Stats row: Total Memories, Agents with Memory, Memory Size, Avg Relevance Score, Top Source, Retention
2. Tab bar: Overview | Agent Memories | Shared Knowledge | Conversations | Embeddings | Settings
3. Memory sources donut chart (sidebar)
4. Top agents by memory count
5. Memory health card: Duplicates, Low Relevance, Stale (90d+) — with "Review"/"Archive" action buttons
6. Memory entries list: title, description snippet, tags, priority indicator, date, star toggle
7. Detail panel (on click): Full content, metadata, tags, linked entities, actions (Edit/Link/Share/Archive/Delete)
8. Search bar + Agent/Type/Source/Time filters
9. Pagination: page numbers + per-page selector

---

### 8. KNOWLEDGE BASE — `/knowledge-base`

**API Endpoints:**
- `GET /api/v1/companies/{id}/knowledge` — list pages
- `GET /api/v1/companies/{id}/knowledge/stats` — stats
- `GET /api/v1/companies/{id}/knowledge/categories` — categories
- `POST /api/v1/companies/{id}/knowledge` — create page
- `GET /api/v1/knowledge/{id}` — page detail
- `PUT /api/v1/knowledge/{id}` — update
- `DELETE /api/v1/knowledge/{id}` — delete
- `POST /api/v1/companies/{id}/knowledge/search` — search
- `POST /api/v1/companies/{id}/knowledge/import` — bulk import

**Layout:** Stats + filter bar + article grid/list + sidebar

---

### 9. GIT REPOS — `/git-repos`

**API Endpoints:**
- `GET /api/v1/companies/{id}/repos` — list repos
- `GET /api/v1/companies/{id}/repos/stats` — stats
- `POST /api/v1/companies/{id}/repos` — connect repo
- `GET /api/v1/repos/{id}` — detail
- `DELETE /api/v1/repos/{id}` — disconnect
- `POST /api/v1/repos/{id}/sync` — sync
- `GET /api/v1/repos/{id}/commits` — commits
- `GET /api/v1/repos/{id}/pull-requests` — PRs
- `GET /api/v1/repos/{id}/contributors` — contributors

---

### 10. HR ROOM — `/hr-room`

**API Endpoints:**
- `GET /api/v1/companies/{id}/agents/performance-summary` — all agents with perf
- `POST /api/v1/agents/{id}/train` — start training
- `POST /api/v1/agents/{id}/enhance` — add capabilities
- `GET /api/v1/companies/{id}/training-queue` — training queue
- `GET /api/v1/companies/{id}/evaluations` — recent evaluations

**Layout:** Tabs (Overview/Enhance/Skills/Memory/Performance/Templates/Evaluations/Settings) + agent table + detail panel

---

### 11. NOTIFICATIONS — `/notifications`

**API Endpoints:**
- `GET /api/v1/companies/{id}/notifications` — list (filterable)
- `POST /api/v1/notifications/{id}/read` — mark read
- `POST /api/v1/companies/{id}/notifications/read-all` — mark all read
- `DELETE /api/v1/notifications/{id}` — dismiss
- `GET /api/v1/companies/{id}/notifications/count` — counts
- `GET /api/v1/companies/{id}/notifications/preferences` — get prefs
- `PUT /api/v1/companies/{id}/notifications/preferences` — update prefs

**Layout:** Category tabs + search/filter + notification list + right sidebar (summary donut, priority breakdown, recent unread, preferences)

**Every notification row:** unread blue dot, icon (colored by type), title, description, module badge, priority indicator, time, checkmark button (mark read), dismiss button

---

### 12. SETTINGS — `/settings`

**API Endpoints:**
- `GET /api/v1/companies/{id}/settings` — company settings
- `PUT /api/v1/companies/{id}/settings` — update settings
- `GET /api/v1/companies/{id}/profile` — user profile
- `PUT /api/v1/companies/{id}/profile` — update profile
- `POST /api/v1/companies/{id}/profile/change-password` — change password
- `POST /api/v1/companies/{id}/profile/two-factor` — 2FA toggle
- `GET /api/v1/companies/{id}/sessions` — active sessions
- `DELETE /api/v1/sessions/{id}` — revoke session
- `GET /api/v1/companies/{id}/api-keys` — list API keys
- `POST /api/v1/companies/{id}/api-keys` — generate key
- `POST /api/v1/api-keys/{id}/revoke` — revoke key
- `DELETE /api/v1/api-keys/{id}` — delete key
- `GET /api/v1/companies/{id}/notifications/preferences` — notification prefs

**Layout:** Left nav (15 tabs) + center content + optional right sidebar

**Tabs:** General | Profile | Security | API Keys | Integrations | Teams & Users | Roles & Permissions | Billing | System Config | Notifications | Data & Storage | Backup & Restore | Audit Logs | Appearance | Advanced

**General Tab:** Workspace name/description, language/timezone selects, Agent Defaults (model, budget, retries, heartbeat), Governance Defaults (rate limit, circuit breaker), Scheduling (auto-assign, standups, sprint duration), Save button

**Profile Tab:** Avatar + name/email/title fields, Communication preferences toggles, Danger zone (deactivate/delete)

**Security Tab:** Password change form, 2FA status (enabled with reconfigure/recovery codes/hardware key), Active Sessions list (with revoke), Login history

**API Keys Tab:** Stats (total/active/expired/revoked), search+filter, table with masked keys + status + environment + actions (view/copy/revoke)

---

### 13-24. REMAINING PAGES (same pattern)

- **Activity** `/activity` — activity feed with SSE real-time stream
- **Budgets** `/budgets` — budget usage meters + per-agent cost breakdown + cost trend chart
- **Evolution** `/evolution` — proposals list + evaluations + approve/reject buttons
- **Goals** `/goals` — goals list with status/progress
- **Meetings** `/meetings` — meeting list + schedule + start/end
- **Organization** `/organization` — org chart from agent departments
- **Skills** `/skills` — skill registry grid
- **Tools** `/tools` — tool registry grid
- **Workflows** `/workflows` — workflow execution list + trace view

---

## CRITICAL REQUIREMENTS

1. **Every button must be functional** — no placeholders, no console.log stubs
2. **All data from API** — no hardcoded mock arrays in production code
3. **API client** sends `X-Company-Id` header on every request (from config)
4. **Proper loading states** — spinner while fetching
5. **Error handling** — error cards with "Try again" on API failures
6. **Real-time counts** — notification badge, agent status counts update on refetch
7. **Responsive** — works on 1920px down to 1280px (sidebar collapses on mobile)
8. **Dark theme only** — no light mode toggle needed
9. **Consistent patterns** — every list page has: stats row + search/filter + table/grid + detail panel
10. **Navigation** — clicking any entity navigates to its detail page

---

## API BASE URL

```
http://localhost:8000
```

All requests include header:
```
X-Company-Id: 00000000-0000-4000-8000-000000000001
Content-Type: application/json
```

---

## COMPONENT LIBRARY REUSE

Create shared components:
- `Card` — dark surface container
- `Button` — primary/secondary/danger variants
- `Badge` — colored status pill
- `Table` — generic sortable table with row click
- `Modal` — overlay dialog
- `Toggle` — switch component
- `Spinner` — loading indicator
- `EmptyState` — no data illustration
- `StatCard` — metric card with icon, value, change
- `SearchBar` — with icon and optional filter dropdowns
- `Tabs` — horizontal tab navigation
- `Timeline` — activity timeline with icons
