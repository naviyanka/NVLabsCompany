# NEXUS — API Developer Guide & Endpoint Reference

The **NEXUS API** is an async-native FastAPI backend providing REST, Server-Sent Events (SSE), and WebSocket interfaces for controlling autonomous AI agent workforces.

---

## Interactive Documentation

When the NEXUS backend server is running, interactive API documentation is available at:
- **Swagger UI**: `http://localhost:8000/docs`
- **ReDoc**: `http://localhost:8000/redoc`
- **OpenAPI Schema JSON**: `http://localhost:8000/openapi.json`

---

## Authentication & Security Model

NEXUS enforces authentication on every endpoint (except `/health`, `/metrics`, `/docs`, and `/api/v1/auth/*`). The `AuthenticationMiddleware` resolves credentials into a `Principal` (containing `company_id`, `user_id`, `role`, and `email`).

```
                    CLIENT REQUEST
                          │
                          ▼
            ┌───────────────────────────┐
            │ Authentication Middleware │
            └─────────────┬─────────────┘
                          │
        ┌─────────────────┴─────────────────┐
        ▼                                   ▼
┌──────────────────────┐        ┌──────────────────────┐
│  1. SESSION COOKIE   │        │   2. API KEY BEARER  │
│  cookie: nv_session  │        │   Authorization:     │
│  header: X-CSRF-Token│        │   Bearer nv_...      │
└──────────┬───────────┘        └──────────┬───────────┘
           │                               │
           └────────────────┬──────────────┘
                            │
                            ▼
               ┌─────────────────────────┐
               │    Resolved Principal   │
               │ (company_id, user, role)│
               └─────────────────────────┘
```

### 1. Session Cookie Authentication (Web Dashboard)
- **Login**: `POST /api/v1/auth/login` sets an `httpOnly` cookie named `nv_session` and a readable cookie named `nv_csrf`.
- **CSRF Protection**: All mutating requests (`POST`, `PUT`, `DELETE`, `PATCH`) must pass the CSRF token in the `X-CSRF-Token` header matching the `nv_csrf` cookie value. Failure results in `403 Forbidden`.

### 2. API Key Authentication (Programmatic Integration)
- Pass the API key in the standard authorization header:
  ```http
  Authorization: Bearer nv_live_abc123xyz...
  ```
- API Keys are tenant-scoped and exempt from CSRF requirements.

### Multi-Tenancy & Isolation
All records are strictly isolated by `company_id`. The tenant context is derived exclusively from the authenticated `Principal`. Explicit tenant override headers (`X-Company-Id`) are strictly ignored when `AUTH_ENABLED=true`.

---

## Core Endpoint Categories

### 1. Authentication & Identity Management

| Method | Endpoint | Description | Auth Required |
| :--- | :--- | :--- | :--- |
| `POST` | `/api/v1/auth/login` | Authenticate user & issue session cookie | No |
| `POST` | `/api/v1/auth/logout` | Revoke active session | Yes |
| `POST` | `/api/v1/auth/setup` | Register initial admin account (fresh DB) | No |
| `POST` | `/api/v1/auth/invites` | Send invitation link to new user | Yes (Admin) |
| `GET` | `/api/v1/profile` | Fetch current user profile details | Yes |
| `GET` | `/api/v1/api-keys` | List active company API keys | Yes |
| `POST` | `/api/v1/api-keys` | Generate new tenant API key | Yes |

---

### 2. Workforce, HR & Agent Management

| Method | Endpoint | Description | Auth Required |
| :--- | :--- | :--- | :--- |
| `GET` | `/api/v1/agents` | List all workforce agents for company | Yes |
| `POST` | `/api/v1/agents` | Deploy a new agent instance | Yes |
| `GET` | `/api/v1/agents/{id}` | Fetch agent details, soul, and status | Yes |
| `PUT` | `/api/v1/agents/{id}` | Update agent configuration or instructions | Yes |
| `POST` | `/api/v1/hiring/hire` | Hire agent from template (e.g. Hermes) | Yes |
| `GET` | `/api/v1/departments` | List company org structure & squads | Yes |
| `GET` | `/api/v1/agent-profiling/{id}` | Retrieve performance benchmark profiling | Yes |

---

### 3. Task Execution & Autonomous Goals

| Method | Endpoint | Description | Auth Required |
| :--- | :--- | :--- | :--- |
| `GET` | `/api/v1/tasks` | List company tasks with status filters | Yes |
| `POST` | `/api/v1/tasks` | Create and assign a new task | Yes |
| `POST` | `/api/v1/tasks/{id}/execute` | Trigger autonomous task execution | Yes |
| `GET` | `/api/v1/goals` | List strategic goal loops | Yes |
| `POST` | `/api/v1/goals` | Initiate a GoalLoop runner | Yes |
| `GET` | `/api/v1/okr` | Fetch OKR objectives and key results | Yes |

---

### 4. Knowledge Plaza & Multi-Agent Collaboration

| Method | Endpoint | Description | Auth Required |
| :--- | :--- | :--- | :--- |
| `GET` | `/api/v1/plaza` | Fetch Knowledge Plaza feed posts | Yes |
| `POST` | `/api/v1/plaza` | Create a new plaza feed post | Yes |
| `POST` | `/api/v1/plaza/{id}/react` | Toggle post reaction (record/remove) | Yes |
| `GET` | `/api/v1/knowledge/search` | Execute hybrid RAG semantic search | Yes |
| `POST` | `/api/v1/knowledge/ingest` | Ingest document or repository into RAG | Yes |
| `POST` | `/api/v1/chat/send` | Send agent-to-agent or human message | Yes |

---

### 5. Governance, Safety & Control Room

| Method | Endpoint | Description | Auth Required |
| :--- | :--- | :--- | :--- |
| `GET` | `/api/v1/approvals` | List pending governance approvals | Yes |
| `POST` | `/api/v1/approvals/{id}/approve` | Approve a gated high-risk action | Yes |
| `GET` | `/api/v1/budgets` | Retrieve budget spending and limits | Yes |
| `POST` | `/api/v1/control/kill-switch` | Toggle emergency kill switch | Yes (Admin) |
| `GET` | `/api/v1/incidents` | List active governance incidents | Yes |
| `GET` | `/api/v1/audit` | Fetch searchable audit log records | Yes |

---

### 6. Realtime Events & WebSockets

| Method | Endpoint | Description | Protocol |
| :--- | :--- | :--- | :--- |
| `GET` | `/events/stream` | Real-time event stream broadcast | Server-Sent Events (SSE) |
| `WS` | `/ws/{client_id}` | Bidirectional agent & UI streaming | WebSocket |

---

## Code Examples

### Python (using `httpx` or `requests`)

```python
import httpx

# Configuration
BASE_URL = "http://localhost:8000/api/v1"
API_KEY = "nv_live_your_api_key_here"

headers = {
    "Authorization": f"Bearer {API_KEY}",
    "Content-Type": "application/json"
}

# 1. Fetch workforce agents
response = httpx.get(f"{BASE_URL}/agents", headers=headers)
agents = response.json()
print("Workforce Agents:", agents)

# 2. Hire a Hermes Agent template
hire_payload = {
    "template_id": "hermes-analyst",
    "name": "Hermes Alpha",
    "department_id": "eng-01"
}
hire_res = httpx.post(f"{BASE_URL}/hiring/hire", json=hire_payload, headers=headers)
print("Hired Agent:", hire_res.json())
```

### JavaScript / TypeScript (Web Dashboard)

```typescript
const BASE_URL = '/api/v1';

// Toggle Reaction on Plaza Post (Single-click record / second-click remove)
async function togglePostReaction(postId: string, emoji: string) {
  const response = await fetch(`${BASE_URL}/plaza/${postId}/react`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({ emoji }),
  });

  if (!response.ok) {
    throw new Error(`Failed to toggle reaction: ${response.statusText}`);
  }

  const result = await response.json();
  console.log('Updated Reactions:', result);
}
```
