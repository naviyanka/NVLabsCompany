# Full Frontend → API Audit

> Every page reviewed. Every button, list, and action cataloged.
> **Current state: 137 endpoints exist. ~55 additional endpoints needed.**

---

## Already Wired (no work needed)

| Page | Status |
|------|--------|
| Agents | ✅ Full CRUD + lifecycle |
| Agent Detail | ✅ All tabs working |
| Activity | ✅ Real API + SSE stream |
| Organization | ✅ Partial (needs dept names) |
| Budgets | ✅ Partial (needs cost trend) |
| Office (3D) | ✅ No API needed |
| Settings | ✅ Full API coverage |
| Notifications | ✅ Full API coverage |

---

## NEW ENDPOINTS NEEDED

### Dashboard (Priority: HIGH)
Already exists: `GET /companies/{id}/stats`, `GET /companies/{id}/metrics/daily`

Still needed:
| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/api/v1/companies/{id}/dashboard/pipelines-summary` | GET | Top 4 active pipelines with progress % |
| `/api/v1/companies/{id}/dashboard/top-agents` | GET | Top agents by performance score |
| `/api/v1/companies/{id}/dashboard/token-usage` | GET | Hourly token/cost data for chart (24h) |

### Tasks (Priority: HIGH)
Already exists: `GET /companies/{id}/tasks`, `POST /companies/{id}/tasks`, `PUT /tasks/{id}/status`, `PUT /tasks/{id}/assign`

Still needed:
| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/api/v1/companies/{id}/tasks/stats` | GET | Task counts by status, by priority, by agent |
| `/api/v1/tasks/{id}/subtasks` | GET | List subtasks |
| `/api/v1/tasks/{id}/subtasks` | POST | Create subtask |
| `/api/v1/tasks/{id}/reassign` | POST | Reassign to different agent |
| `/api/v1/tasks/{id}/cancel` | POST | Cancel a running task |

### Memory (Priority: HIGH)
Already exists: `GET /agents/{id}/memory`, `POST /agents/{id}/memory`, `GET /agents/{id}/memory/search`

Still needed:
| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/api/v1/companies/{id}/memory` | GET | All memories across agents (paginated, filterable) |
| `/api/v1/companies/{id}/memory/stats` | GET | Total count, size, sources breakdown, top agents |
| `/api/v1/memory/{id}` | GET | Single memory detail |
| `/api/v1/memory/{id}` | PATCH | Update memory (tags, importance) |
| `/api/v1/memory/{id}` | DELETE | Delete a memory |
| `/api/v1/memory/{id}/archive` | POST | Archive a memory |
| `/api/v1/companies/{id}/memory/health` | GET | Duplicates, stale, low-relevance counts |

### Knowledge Base (Priority: HIGH)
Already exists: `GET /companies/{id}/knowledge`, `POST /companies/{id}/knowledge`, `GET /knowledge/{id}`, `PUT /knowledge/{id}`, `POST /companies/{id}/knowledge/search`

Still needed:
| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/api/v1/companies/{id}/knowledge/stats` | GET | Article count, categories, content types, AI usage |
| `/api/v1/companies/{id}/knowledge/categories` | GET | List all categories with counts |
| `/api/v1/knowledge/{id}` | DELETE | Delete an article |
| `/api/v1/companies/{id}/knowledge/import` | POST | Bulk import documents |

### Pipelines (Priority: HIGH)
Already exists: `GET /companies/{id}/pipelines`, `POST /companies/{id}/pipelines`, `GET /pipelines/{id}`, `POST /pipelines/{id}/run`, `GET /pipelines/{id}/runs`

Still needed:
| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/api/v1/companies/{id}/pipelines/stats` | GET | Pipeline counts, execution stats |
| `/api/v1/companies/{id}/pipelines/templates` | GET | Pipeline template catalog |
| `/api/v1/pipelines/{id}/pause` | POST | Pause running pipeline |
| `/api/v1/pipelines/{id}/stop` | POST | Stop/cancel pipeline |
| `/api/v1/companies/{id}/pipelines/import` | POST | Import pipeline definition |

### HR Room (Priority: HIGH)
Already exists: `POST /companies/{id}/hiring/create-agent`, `POST /companies/{id}/hiring/job-description`

Still needed:
| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/api/v1/companies/{id}/agents/performance-summary` | GET | All agents with performance scores |
| `/api/v1/agents/{id}/train` | POST | Start training session |
| `/api/v1/agents/{id}/enhance` | POST | Add skills/capabilities |
| `/api/v1/companies/{id}/training-queue` | GET | List agents in training |
| `/api/v1/companies/{id}/evaluations` | GET | Recent agent evaluations |

### Git Repos (Priority: HIGH)
Already exists: `GET /companies/{id}/repos`, `POST /companies/{id}/repos`, `GET /repos/{id}`, `PUT /repos/{id}`, `DELETE /repos/{id}`, `POST /repos/{id}/sync`

Still needed:
| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/api/v1/companies/{id}/repos/stats` | GET | Total repos, commit activity, PR stats |
| `/api/v1/repos/{id}/commits` | GET | Recent commits (paginated) |
| `/api/v1/repos/{id}/pull-requests` | GET | Open PRs |
| `/api/v1/repos/{id}/contributors` | GET | Top contributors |

### Goals (Priority: MEDIUM)
Already exists: `GET /companies/{id}/goals`, `POST /companies/{id}/goals`, `GET /goals/{id}`, `PUT /goals/{id}`

Still needed:
| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/api/v1/goals/{id}` | DELETE | Delete a goal |
| `/api/v1/companies/{id}/goals/stats` | GET | Goal counts by status |

### Evolution (Priority: MEDIUM)
Already exists: `GET /companies/{id}/evolution/proposals`, `GET /evolution/proposals/{id}`, `POST /evolution/proposals/{id}/evaluate`, `POST /evolution/proposals/{id}/promote`, `POST /evolution/proposals/{id}/rollback`

Still needed:
| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/api/v1/companies/{id}/evolution/evaluations` | GET | List all evaluations |
| `/api/v1/evolution/proposals/{id}/approve` | POST | Approve proposal (not same as promote) |
| `/api/v1/evolution/proposals/{id}/reject` | POST | Reject proposal |

### Skills (Priority: MEDIUM)
Already exists: `GET /companies/{id}/skills`, `POST /companies/{id}/skills`, `POST /agents/{id}/skills`

Still needed:
| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/api/v1/skills/{id}` | GET | Skill detail |
| `/api/v1/skills/{id}` | PATCH | Update skill |
| `/api/v1/skills/{id}` | DELETE | Delete skill |

### Tools (Priority: MEDIUM)
Already exists: `GET /companies/{id}/tools`, `POST /companies/{id}/tools`, `POST /agents/{id}/tool-access`, `GET /agents/{id}/tools`

Still needed:
| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/api/v1/tools/{id}` | GET | Tool detail |
| `/api/v1/tools/{id}` | PATCH | Update tool |
| `/api/v1/tools/{id}` | DELETE | Delete tool |

### Meetings (Priority: LOW)
Already exists: `GET /companies/{id}/meetings`, `POST /companies/{id}/meetings`, `GET /meetings/{id}`, `POST /meetings/{id}/start`, `POST /meetings/{id}/end`, `GET /meetings/{id}/minutes`

Still needed:
| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/api/v1/meetings/{id}` | DELETE | Cancel/delete meeting |
| `/api/v1/companies/{id}/meetings/upcoming` | GET | Only upcoming meetings |

### Workflows (Priority: LOW)
Already exists: `POST /workflows/company`, `POST /workflows/task`, `GET /workflows/{id}/status`, `GET /workflows/{id}/trace`

Still needed:
| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/api/v1/companies/{id}/workflows` | GET | List all workflows |
| `/api/v1/workflows/{id}/cancel` | POST | Cancel running workflow |

### Budgets (Priority: LOW)
Already exists: `GET /companies/{id}/budget-usage`, `GET /agents/{id}/budget-usage`, `POST /companies/{id}/budget-policies`

Still needed:
| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/api/v1/companies/{id}/budgets/cost-trend` | GET | 7-day daily cost data for chart |

### Organization (Priority: LOW)
Already exists: `GET /companies/{id}/agents` (used for org chart)

Still needed:
| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/api/v1/companies/{id}/departments` | GET | List departments with names |
| `/api/v1/companies/{id}/teams` | GET | List teams |

---

## SUMMARY

| Priority | Pages | New Endpoints |
|----------|-------|---------------|
| HIGH | Dashboard, Tasks, Memory, Knowledge, Pipelines, HR Room, Git Repos | ~35 |
| MEDIUM | Goals, Evolution, Skills, Tools, Workflows | ~13 |
| LOW | Meetings, Budgets, Organization | ~7 |
| **TOTAL** | | **~55 new endpoints** |

### Current vs Target

| Metric | Current | After |
|--------|---------|-------|
| API Endpoints | 137 | ~192 |
| Pages fully wired | 8/24 | 24/24 |
| Mock data pages | 13 | 0 |
