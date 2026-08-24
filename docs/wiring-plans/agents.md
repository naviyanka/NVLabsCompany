# /agents Page — Wiring Plan

## Summary

The Agents page is the workforce directory — lists all agents with search/filter, status badges, and a "Hire Agent" modal for creating new agents. This page is the **foundational entity** that almost every other page depends on. The current frontend has a basic hire modal (name, role, model, title, responsibilities). The backend has a much richer system with hire manifests, archetypes, templates, CLI backend detection, and provider presets that are NOT yet exposed through the frontend.

---

## 1. What the Frontend Currently Has

### Current Features

| Feature | Implementation | Status |
|---------|---------------|--------|
| Agent list (grid/list view) | `AgentList` component with `AgentCard` | Working with mock data |
| Search & filter by status | Client-side filter on name, title, role, model | Working |
| Status filter (active/idle/busy/offline) | Dropdown select | Working |
| Click to detail page | `navigate(/agents/${agent.id})` | Working |
| Hire Agent modal (basic) | Modal with name, role, model, title, responsibilities | Working, calls POST API |

### Current "Hire Agent" Modal Fields

```typescript
// Current fields in the modal
name: string              // "Agent Call Sign / Name" — free text
role: select              // "Role Classification" — 5 options: engineer, researcher, qa, devops, pm
model: select             // "Model Engine" — 3 options: claude-3-7-sonnet, gpt-4o, gpt-4o-mini
title: string             // "Title & Specialization" — free text
responsibilities: textarea // "Primary Responsibilities & Scope" — free text
```

### Current API Calls

```typescript
// List agents
GET /api/v1/companies/00000000-0000-4000-8000-000000000001/agents
// Expects: { items: Agent[] }

// Create agent
POST /api/v1/companies/00000000-0000-4000-8000-000000000001/agents
// Body: { name, title, role, model, responsibilities }
```

### Frontend Agent Type

```typescript
interface Agent {
  id: UUID;
  company_id: UUID;
  name: string;
  title: string;
  role: string;
  department_id: UUID | null;
  team_id: UUID | null;
  manager_id: UUID | null;
  status: AgentStatus;        // 'active' | 'idle' | 'busy' | 'offline' | ...
  adapter_type: string;
  model: string;
  capabilities: string[];
  responsibilities: string;
  objectives: string;
  budget_monthly_cents: number;
  spent_monthly_cents: number;
  performance_score?: number;
  soul_description: string;
  last_heartbeat_at: DateTimeString | null;
  created_at: DateTimeString;
  updated_at: DateTimeString;
}
```

---

## 2. What Already Exists in Backend

### 2a. Agent CRUD Endpoints (FULLY WORKING)

**File:** `src/nexus/api/routes/agents.py`

| Endpoint | Method | Status |
|----------|--------|--------|
| `/api/v1/companies/{id}/agents` | GET | Working — returns `list[AgentResponse]` (NOT wrapped in `{items}`) |
| `/api/v1/companies/{id}/agents` | POST | Working — creates agent with full `AgentCreate` body |
| `/api/v1/agents/{agent_id}` | GET | Working |
| `/api/v1/agents/{agent_id}` | PUT | Working |
| `/api/v1/agents/{agent_id}` | DELETE | Working |
| `/api/v1/agents/{agent_id}/wake` | POST | Working — transitions idle/paused → ready |
| `/api/v1/agents/{agent_id}/pause` | POST | Working — transitions → paused |
| `/api/v1/agents/{agent_id}/heartbeat` | POST | Working |

**Backend `AgentCreate` accepts more fields than the frontend sends:**
```python
class AgentCreate(BaseModel):
    name: str
    role: str
    title: str | None = None
    department_id: uuid.UUID | None = None
    team_id: uuid.UUID | None = None
    adapter_type: str = "langchain"      # ← frontend doesn't send this
    adapter_config: dict | None = None    # ← frontend doesn't send this
    model: str | None = None
    capabilities: list[str] | None = None # ← frontend doesn't send this
    responsibilities: str | None = None
    objectives: str | None = None         # ← frontend doesn't send this
    soul_description: str | None = None   # ← frontend doesn't send this
    budget_monthly_cents: int = 0         # ← frontend doesn't send this
```

### 2b. Hire Manifest System (NOT EXPOSED VIA API)

**Files:**
- `src/nexus/templates/hire_manifest.py` — `HireManifest` Pydantic model (portable agent role JSON)
- `src/nexus/templates/hire_registry.py` — `ManifestRegistry` (filesystem load/save/import)
- `src/nexus/templates/hire_security.py` — Security validation (flag allowlist, model ID sanitization)

**HireManifest fields:**
```python
spec: str               # "nexus/hire@1"
name: str               # max 40 chars
description: str        # max 200 chars
goal: str               # max 4000 chars — the agent's operational goal
provider: str           # "claude" | "codex" | "grok" | "kimi" | "antigravity" | "qwen" | "opencode" | "crush" | "pi" | "copilot"
model: str              # max 80 chars — e.g. "claude-sonnet-4-6[1m]"
command_flags: list[str] # CLI flags (validated against safe allowlist)
capabilities: list[str]  # max 12 items
isolate: bool           # run in isolation
token_cap: int          # budget cap (max 10B)
author: str             # who created this manifest
homepage: str           # https URL
```

**Key security:** Manifests are untrusted input. Command flags use default-deny allowlist (only `--model`, `--max-turns`, `--output-format`, `--verbose`). Model IDs reject shell metacharacters.

### 2c. Agent Archetypes (NOT EXPOSED VIA API)

**File:** `src/nexus/templates/archetypes.py`

20 pre-built role archetypes as frozen dataclasses:

| # | Name | Role ID | Interaction Style |
|---|------|---------|-------------------|
| 1 | Software Architect | software-architect | analytical |
| 2 | Backend Engineer | backend-engineer | methodical |
| 3 | Frontend Engineer | frontend-engineer | creative |
| 4 | QA Engineer | qa-engineer | methodical |
| 5 | DevOps Engineer | devops-engineer | directive |
| 6 | Security Engineer | security-engineer | analytical |
| 7 | Data Engineer | data-engineer | methodical |
| 8 | ML Engineer | ml-engineer | analytical |
| 9 | Product Manager | product-manager | collaborative |
| 10 | Technical Writer | tech-writer | supportive |
| 11 | Designer | designer | creative |
| 12 | Researcher | researcher | analytical |
| 13 | Project Manager | project-manager | directive |
| 14 | Scrum Master | scrum-master | supportive |
| 15 | Site Reliability Engineer | site-reliability-engineer | methodical |
| 16 | Database Administrator | database-admin | methodical |
| 17 | Mobile Developer | mobile-developer | creative |
| 18 | Performance Engineer | performance-engineer | analytical |
| 19 | Accessibility Specialist | accessibility-specialist | supportive |
| 20 | Team Lead | team-lead | collaborative |

Each archetype has: `capabilities[]`, `constraints[]`, `system_prompt`, `tools_allowed[]`, `interaction_style`, `description`.

**ArchetypeRegistry** provides: `list_archetypes()`, `get_archetype(name)`, `get_archetypes_by_role(role)`.

### 2d. Agent Template Files (NOT EXPOSED VIA API)

**Directory:** `src/nexus/templates/agents/`

10 Markdown templates with YAML frontmatter:
- backend-engineer.md, code-reviewer.md, data-engineer.md, devops-engineer.md,
  frontend-engineer.md, product-manager.md, qa-engineer.md, security-engineer.md,
  software-architect.md, sre.md

Each contains: `name`, `description`, rules, process, and detailed system prompt content.

**TemplateRegistry** provides: `load_from_directory()`, `list_templates()`, `get_template(name)`.

### 2e. CLI Backend Registry (PARTIALLY EXPOSED)

**File:** `src/nexus/adapters/cli_registry.py`

6 registered CLI backends:
| ID | Name | Command | Stability |
|----|------|---------|-----------|
| claude | Claude Code | `claude` | stable |
| codex | OpenAI Codex CLI | `codex` | beta |
| kiro-cli | Kiro CLI | `kiro` | beta |
| aider | Aider | `aider` | stable |
| opencode | OpenCode | `opencode` | experimental |
| agy | Agy | `agy` | experimental |

**Existing API:** `GET /api/v1/adapters/cli-backends` — returns installed status + version probing.

### 2f. Provider Presets (NOT EXPOSED VIA API)

**File:** `src/nexus/adapters/provider_presets.py`

11 provider presets with spawn configuration:
- `claude`, `codex`, `grok`, `kimi`, `antigravity`, `qwen`, `opencode`, `crush`, `pi`, `copilot`, `custom`

Each preset has: `label`, `default_command`, `auto_mode_flag`, `model_flag`, `recommended_orchestrator_model`, `install_command`, `docs_url`.

### 2g. Hiring/Template Endpoint in company_sim

**File:** `src/nexus/api/routes/company_sim.py`

| Endpoint | What it does |
|----------|-------------|
| `POST /api/v1/companies/{id}/hiring/job-description` | Generates a JD for a role |
| `POST /api/v1/companies/{id}/hiring/create-agent` | Creates agent from `role_template` string |
| `GET /api/v1/companies/{id}/hiring/{agent_id}/onboarding` | Returns onboarding plan |

### 2h. Identity/Soul Templates (EXPOSED)

**Endpoint:** `GET /api/v1/identity/templates` — returns soul templates with personality traits, expertise.

---

## 3. What Can Be Wired Up Directly (No Backend Changes)

### 3a. Fix List Response Shape

Backend returns `list[AgentResponse]`, frontend expects `{ items: Agent[] }`.

**Fix (frontend):** Update the `useApi` call:
```typescript
const { data, loading, error, refetch } = useApi<Agent[]>(
  () => apiClient.get('/api/v1/companies/{company_id}/agents'),
  []
);
const agents = (data && data.length > 0) ? data : initialWorkforceAgents;
```

### 3b. Replace Hardcoded Company ID

Use `getActiveCompanyId()` instead of `'00000000-0000-4000-8000-000000000001'`.

### 3c. Wire CLI Backends Dropdown

Frontend can call `GET /api/v1/adapters/cli-backends` to populate a "Backend/IDE" selector in the hire modal. Shows which CLIs are installed on the system.

### 3d. Expand Create Agent Body

The POST endpoint already accepts many more fields. Frontend just needs to send them:
- `adapter_type` (from backend selection)
- `capabilities` (from archetype or custom input)
- `objectives` (text input)
- `soul_description` (text input)
- `budget_monthly_cents` (number input)

---

## 4. What Needs to Be Added in Backend

### 4a. Archetypes API Endpoint (HIGH PRIORITY)

**New endpoint:**
```
GET /api/v1/agent-archetypes
```

Returns all 20 archetypes as JSON:
```json
[{
  "name": "Backend Engineer",
  "role": "backend-engineer",
  "capabilities": ["api-design", "database-modeling", ...],
  "constraints": ["must write unit tests", ...],
  "system_prompt": "You are a backend engineer...",
  "tools_allowed": ["code-editor", "terminal", ...],
  "interaction_style": "methodical",
  "description": "Builds server-side applications..."
}]
```

**Implementation:** Instantiate `ArchetypeRegistry()` and serialize results.

### 4b. Agent Templates API Endpoint (HIGH PRIORITY)

**New endpoint:**
```
GET /api/v1/agent-templates
```

Returns markdown templates metadata:
```json
[{
  "name": "Backend Engineer",
  "description": "API design, service implementation...",
  "file_path": "templates/agents/backend-engineer.md"
}]
```

**Implementation:** Use `TemplateRegistry.load_from_directory()` and serialize.

### 4c. Provider Presets API Endpoint (MEDIUM PRIORITY)

**New endpoint:**
```
GET /api/v1/agent-providers
```

Returns available providers with their configuration:
```json
[{
  "id": "claude",
  "label": "Claude Code",
  "default_command": "claude",
  "supports_model": true,
  "model_flag": "--model",
  "recommended_model": "claude-opus-4-8[1m]",
  "install_command": "npm install -g @anthropic-ai/claude-code",
  "docs_url": "https://docs.claude.com/...",
  "installed": true
}]
```

**Implementation:** Combine `PROVIDER_PRESETS` with `CLIRegistry.detect_available()`.

### 4d. Hire from Manifest Endpoint (MEDIUM PRIORITY)

**New endpoint:**
```
POST /api/v1/companies/{id}/agents/hire-from-manifest
Body: HireManifest JSON
```

Validates the manifest, creates an agent with all fields mapped, and returns the created agent.

**Implementation:** Use `validate_hire_manifest()` → map to `Agent` model fields → create.

### 4e. Batch Hire (Team Creation) Endpoint (MEDIUM PRIORITY)

**New endpoint:**
```
POST /api/v1/companies/{id}/agents/hire-team
Body: {
  "team_name": "Backend Squad",
  "department_id": "dept-eng",
  "agents": [
    { "archetype": "Backend Engineer", "name": "Bolt-03", "model": "gpt-4o" },
    { "archetype": "QA Engineer", "name": "Shield-07", "model": "gpt-4o-mini" },
    { "archetype": "DevOps Engineer", "name": "Forge-06", "model": "claude-3-7-sonnet" }
  ]
}
```

Creates a team + multiple agents in a single transaction.

**Implementation:**
1. Create or find the team
2. For each agent entry, resolve archetype → get capabilities, system_prompt, constraints
3. Create Agent records with `team_id` set
4. Return all created agents

### 4f. Wrap List Response (LOW PRIORITY)

Change `GET /api/v1/companies/{id}/agents` to return:
```json
{
  "items": [...],
  "total": 7,
  "limit": 100,
  "offset": 0
}
```

### 4g. Hire Manifest Registry API (LOW PRIORITY)

**New endpoints:**
```
GET  /api/v1/hire-manifests           # List saved manifests
POST /api/v1/hire-manifests           # Import/save a manifest
GET  /api/v1/hire-manifests/{name}    # Get one manifest
```

Uses `ManifestRegistry` to manage persistent manifest files.

---

## 5. Enhanced Hire Agent Frontend — Feature Plan

### 5a. Hire Mode Selection (Step 1 of modal)

The enhanced modal should start with a mode selection:

```
┌─────────────────────────────────────────────────────┐
│  How would you like to hire?                         │
│                                                     │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐         │
│  │ 🧑 Manual │  │ 📋 From  │  │ 👥 Hire  │         │
│  │   Hire   │  │ Template │  │  a Team  │         │
│  └──────────┘  └──────────┘  └──────────┘         │
│                                                     │
│  Manual: Configure agent from scratch               │
│  Template: Choose from 20 pre-built archetypes      │
│  Team: Select multiple agents and deploy together   │
└─────────────────────────────────────────────────────┘
```

### 5b. Manual Hire (Enhanced Current Modal)

Add these fields to the existing modal:

| Field | Type | Source |
|-------|------|--------|
| Name | text | user input |
| Title | text | user input |
| Role | select | expanded roles (from archetypes: 20 options) |
| Provider/Backend | select | from `GET /api/v1/agent-providers` |
| Model | select | dynamic based on provider |
| Capabilities | multi-select / tags | from archetype defaults, editable |
| Objectives | textarea | user input |
| Soul Description | textarea | user input or from archetype system_prompt |
| Budget (monthly) | number | user input (cents → display as $) |
| Department | select | from departments list |
| Team | select | from teams list |
| Manager | select | from existing agents |
| CLI Flags | advanced toggle | from manifest safe flags |
| Token Cap | number | optional |

### 5c. Hire from Template

1. Show grid of 20 archetypes (cards with name, description, capabilities preview)
2. User selects one → auto-fills: role, capabilities, system_prompt, tools, constraints
3. User customizes: name, model/provider, budget, department, team
4. Submit

### 5d. Hire a Team

1. User enters team name and department
2. Shows archetype grid — user picks multiple (checkbox selection)
3. For each selected, shows inline row: name (editable), model (select), provider
4. "Deploy Team" button → calls batch hire endpoint
5. Returns success with all created agents

### 5e. Import from Manifest File

1. User can drag-and-drop or upload a `.json` manifest file
2. Frontend validates against `HireManifest` shape
3. Shows preview of what will be created
4. "Deploy" button creates the agent

---

## 6. Implementation Order

### Phase 1: Quick Wire-Up (frontend only)

1. **Fix response shape** — handle both `list` and `{ items: [...] }` from backend
2. **Replace hardcoded company ID** — use `getActiveCompanyId()`
3. **Send all available fields** in the create POST body (capabilities, objectives, etc.)
4. **Add adapter_type/model selection** — call existing `GET /api/v1/adapters/cli-backends`

### Phase 2: Backend API Additions

5. **Add `GET /api/v1/agent-archetypes`** — expose the 20 archetypes
6. **Add `GET /api/v1/agent-templates`** — expose the 10 markdown templates
7. **Add `GET /api/v1/agent-providers`** — merge presets + installed detection
8. **Add `POST /api/v1/companies/{id}/agents/hire-from-manifest`** — manifest-based hire
9. **Add `POST /api/v1/companies/{id}/agents/hire-team`** — batch team creation

### Phase 3: Enhanced Frontend Hire Modal

10. **Add hire mode selector** — Manual / Template / Team tabs
11. **Template hire flow** — archetype grid → customize → deploy
12. **Team hire flow** — multi-select archetypes → configure each → batch deploy
13. **Manifest import** — file upload → preview → deploy
14. **Enhanced manual hire** — all fields, provider-dependent model options

### Phase 4: Polish & Advanced

15. **Wrap response in pagination** — `{ items, total, limit, offset }`
16. **Manifest registry API** — save/list/import manifests
17. **Agent lifecycle actions in list** — wake/pause/terminate buttons per agent
18. **Real-time status via SSE** — agent status changes reflected live

---

## 7. Dependencies on Other Pages

| Dependency | Why | Hard/Soft | Status |
|------------|-----|-----------|--------|
| `/organization` | Need departments and teams list for hire modal | Soft | Departments/teams tables exist but may not have API for listing them independently |
| `/settings` | Company-level defaults (default model, default budget) | Soft | Settings page is self-contained |

**Key Insight:** The Agents page is a **provider** — it doesn't depend on other pages meaningfully. Other pages depend on IT. This makes it the ideal first page to wire up.

---

## 8. Files to Create/Modify

### Backend

| File | Action | Purpose |
|------|--------|---------|
| `src/nexus/api/routes/agents.py` | MODIFY | Optionally wrap response in `{items}`, add more query filters |
| `src/nexus/api/routes/archetypes.py` | CREATE | New route exposing ArchetypeRegistry |
| `src/nexus/api/routes/agent_templates.py` | CREATE | New route exposing TemplateRegistry + provider presets |
| `src/nexus/api/routes/agents.py` | MODIFY | Add `hire-from-manifest` and `hire-team` endpoints |
| `src/nexus/main.py` | MODIFY | Register new routers |

### Frontend

| File | Action | Purpose |
|------|--------|---------|
| `dashboard/src/pages/Agents.tsx` | MODIFY | Fix API call, enhance hire modal, dynamic company ID |
| `dashboard/src/components/agents/HireAgentModal.tsx` | CREATE | New multi-mode hire modal component |
| `dashboard/src/components/agents/ArchetypeGrid.tsx` | CREATE | Grid of selectable archetype cards |
| `dashboard/src/components/agents/TeamHireFlow.tsx` | CREATE | Multi-agent team configuration |
| `dashboard/src/api/agents.ts` | CREATE | Dedicated agents API module |

---

## 9. Backend Features Summary Table

| Backend Feature | Exists | Has API | Frontend Uses | Action Needed |
|-----------------|--------|---------|---------------|---------------|
| Agent CRUD | YES | YES | Partially (missing fields) | Wire remaining fields |
| Agent lifecycle (wake/pause) | YES | YES | NO | Add buttons to list |
| Archetypes (20 roles) | YES | NO | NO | Create API endpoint |
| Templates (10 .md files) | YES | NO | NO | Create API endpoint |
| Provider Presets (11) | YES | NO | NO | Create API endpoint |
| CLI Backends (6, auto-detect) | YES | YES | NO | Wire to hire modal |
| Hire Manifests (validation) | YES | NO | NO | Create API + import UI |
| Manifest Registry (filesystem) | YES | NO | NO | Create API + manage UI |
| Batch team hire | NO | NO | NO | Create both |
| Job Description Generator | YES | YES (company_sim) | NO | Wire to hire flow |
| Onboarding Plan | YES | YES (company_sim) | NO | Show post-hire |
| Soul Templates (identity) | YES | YES | NO | Wire to hire flow |

---

## 10. Risk Assessment

| Risk | Impact | Mitigation |
|------|--------|------------|
| Response shape mismatch (list vs {items}) | Page crash | Handle both in frontend |
| No agents in DB initially | Empty page | Keep mock data fallback |
| CLI backend detection slow | Hire modal delay | Cache backend detection, lazy load |
| Manifest security bypass | CLI injection | Backend already validates (allowlist), frontend just displays |
| Team hire partial failure | Some agents created, some fail | Use DB transaction, rollback all on any failure |
