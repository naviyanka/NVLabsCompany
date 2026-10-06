# NEXUS

NEXUS is a self-hosted operating and governance system for durable AI-company and workforce execution: it organizes agents into a tenant-isolated company, runs their work as durable, reviewable orders, controls authority and spend, preserves institutional memory, and records selected governance, work and security events in a hash-chained audit log.

[![CI](https://github.com/naviyanka/NVLabsCompany/actions/workflows/test.yml/badge.svg?branch=main)](https://github.com/naviyanka/NVLabsCompany/actions/workflows/test.yml)
[![Python](https://img.shields.io/badge/python-3.12+-blue)](https://www.python.org)
[![Frontend](https://img.shields.io/badge/frontend-React%2019%20%C2%B7%20TypeScript%20%C2%B7%20Vite-087EA4)](dashboard/README.md)

NEXUS sits above model providers and agent runtimes — it is an application and control plane, not another agent framework. No tags or releases are published yet; the project is pre-release software under active development. Read [Current limitations](#current-limitations) before relying on any capability.

## Key capabilities

Implemented and tested on current `main`:

- **Tenants and organization** — companies as isolation boundaries, departments and squads, human invitations, agent hiring from templates, org snapshots.
- **Durable text-first work execution** — a human operator creates work orders, delegates them through managers, and employees execute them as work attempts that survive process restarts; managers review deliverables and verify or reject them (see [Work execution lifecycle](#work-execution-lifecycle)).
- **Governance** — RBAC, policy evaluation, autonomy levels with notifications and approval gates, tool policy with binding enforcement, kill switches and circuit breakers.
- **Budgets and cost** — per-company spending limits with pre-execution checks, chat model calls reserve an estimated hold before the request and settle it to the reported cost afterwards, or release it when nothing was billed. If the budget ledger is unreachable the call is refused unless the operator opts into `BUDGET_FAIL_OPEN`.
- **Memory** — tiered memory with search, a memory graph, and an evidence workflow with governed trust promotion.
- **Audit and incidents** — an append-only, hash-chained audit log per company for selected events (not every operation), incident tracking, activity feeds.
- **PostgreSQL tenant isolation** — forced row-level security with separated database roles; a dedicated, process-isolated system runtime is the only holder of the privileged role.
- **Durable tool-effect recovery** — tool calls inside employee chat turns are ledgered so an interrupted non-idempotent write is not automatically rerun and waits for operator recovery.
- **Dashboard and API** — a React operations dashboard over a documented REST/SSE API, with accessibility and form-reliability improvements in the login, setup, and invite flows.
- **CLI and provider integrations** — employee CLIs (including Claude Code) as execution backends, plus model adapters for major providers (see [Interfaces and providers](#interfaces-and-providers)).
- **Verification tooling** — a deterministic sequential pytest runner for memory-bounded local runs, and a read-only project-facts auditor that measures repository facts and flags stale documentation claims.

| State | Capabilities |
| :--- | :--- |
| Implemented and tested | Everything listed above, enforced by CI (backend, PostgreSQL/RLS, frontend, API parity, E2E, compose boot) |
| Present but limited or opt-in | Azure OpenAI and Azure Speech providers (disabled by default, operator-configured), Obsidian vault integration, Temporal durability, optional self-hosted LLM gateway |
| Planned or not shipped | Browser voice and channel gateways, further memory-lifecycle phases, releases and SBOMs — no voice product ships today |

## Architecture

```mermaid
flowchart TB
    subgraph client["Browser"]
        UI["React dashboard<br/>auth · operations surfaces"]
    end

    subgraph edge["API edge (FastAPI)"]
        MW["Middleware chain<br/>CORS · request ID · metrics · API version ·<br/>authentication · idempotency · governance"]
    end

    subgraph app["Tenant-bound application services"]
        GOV["Governance<br/>RBAC · policies · approvals ·<br/>kill switches · circuit breakers · audit"]
        BUD["Budgets and cost<br/>holds · settlement"]
        WORK["Work execution<br/>work orders · attempts · reviews ·<br/>durable chat turns"]
        MEM["Memory and knowledge<br/>tiered memory · evidence · RAG · vault"]
    end

    SR["System runtime<br/>separate process · BYPASSRLS credential · no ingress"]

    subgraph data["Persistence"]
        PG[("PostgreSQL<br/>forced row-level security · pgvector")]
        RD[("Redis")]
        TP["Temporal<br/>optional worker"]
    end

    subgraph providers["Adapters"]
        AD["Model adapters<br/>Anthropic · OpenAI-compatible · Azure · Gemini ·<br/>Bedrock · Ollama · Claude Code CLI · Hermes"]
        TOOLS["Tools and MCP"]
    end

    EXT["External providers"]

    UI -->|HTTPS| MW
    MW --> GOV
    MW --> BUD
    MW --> WORK
    MW --> MEM
    GOV --> PG
    BUD --> PG
    WORK --> PG
    WORK --> TP
    MEM --> PG
    app --> RD
    WORK --> AD
    WORK --> TOOLS
    SR --> PG
    AD --> EXT
    TOOLS --> EXT
```

Three database roles keep the isolation structural rather than conventional:

- **Application role (`nexus_app`)** — the runtime identity of the API and workers. It owns no schema objects and is bound by forced row-level security; every tenant-scoped query runs in a tenant session that sets the company context per transaction. The caller's tenant always comes from the authenticated credential, never from a request header.
- **Migrator role (`nexus_migrator`)** — owns the schema and runs Alembic in a one-shot migration job. A runtime process handed the migration credential refuses to start.
- **System role (`nexus_system`)** — the only identity with `BYPASSRLS`, held exclusively by the system-runtime process, which publishes no ports. It discovers which tenants need maintenance and publishes work hints; company data is only ever touched through tenant sessions.

Startup is fail-closed: the API refuses to start on a disallowed `AUTH_ENABLED=false`, a misplaced migration or system credential, or a webhook timeout that would outlive the idempotency lease.

## Security and tenant isolation

- **Authentication** — httpOnly session cookie with CSRF protection on mutating requests, or tenant-scoped API keys. Disabling authentication is refused outside test environments, and in development only with an explicit acknowledgement.
- **Tenant binding** — the tenant context is derived exclusively from the authenticated principal; explicit tenant-override headers are ignored while authentication is enabled. A record from another company is indistinguishable from one that does not exist.
- **Authorization** — RBAC roles and per-route permission requirements; the Work API accepts only human principals or service keys, while agents act exclusively through governed tools.
- **Tool policy** — tool access control with binding enforcement on by default; MCP and declared tool schemas are validated before dispatch, and undeclared external tools default to the most conservative effect class.
- **Network and secrets** — SSRF guards on outbound URLs with an operator allowlist for internal hosts; a secret backend (encrypted at rest by default) for credentials; governed Azure providers read keys only through the secret backend and authenticate with Entra by default.
- **Idempotency** — mutating requests are guarded by an idempotency middleware, and work-order creation requires an `Idempotency-Key` header (`400 IDEMPOTENCY_KEY_REQUIRED` when absent) so a retried request does not create a duplicate order.
- **Audit** — four separate records exist, and only the second is the hash-chained audit table:
  - *Request logs* — the governance middleware emits a structured `audit:` log line (method, path, company, status, duration) for mutating HTTP requests it serves. It is a log line, not a stored audit row.
  - *Persistent audit events* — selected governance, work-lifecycle, task-attempt, chat-turn, tool-effect and security-sensitive operations call the audit recorder explicitly (for example `work.created`, `work.delegated`, `work.assigned`, `work.cancelled`, `task.attempt_queued` and `tool_effect.*` recovery decisions). Each row joins its company's hash-chained, append-only log, and a row whose chain link cannot be allocated is not written unchained. Persistence is best-effort by default: a failed write is logged and the operation continues, unless the caller requires it. Work-order creation, delegation, assignment and cancellation, and the manual-recovery, resolution and retake decisions of the tool-effect ledger, do require it and fail closed; attempt, deliverable, review and chat-turn events do not. Not every operation or state change writes an audit row.
  - *Work and task-attempt state* — orders, attempts, verification results and deliverables are durable database rows of their own, whether or not an audit event was written.
  - *Tool-effect ledger* — ledgered tool calls keep their own durable rows (see [Current limitations](#current-limitations)).

## Work execution lifecycle

The text-first work loop, operated through the dashboard's Company Work surface or `POST /api/v1/work`:

1. **Create** — an operator opens a work order with a title, description, optional goal link, and priority.
2. **Delegate** — the order is assigned to a manager agent, which delegates an attempt to an employee agent through its governed `manager_assign_work` tool (idempotent by ledger key).
3. **Execute** — the work order's child tasks are created in text mode. Each attempt runs as a durable chat turn: claimed and leased in the database, renewed while it works, and recovered by another worker if a process dies. Text attempts run tool-free.
4. **Review** — a human or service key reviews through the Work API (`verify` or `reject` with a reason). An agent manager reviews through its governed `manager_review_work` tool; it must be the executing employee's manager and can never review its own work. A rejected attempt can be retried as a new attempt. Review through the Work API covers text work only.
5. **Record** — orders, attempts, verification results and deliverables are durable database rows exposed by the Work API. Selected lifecycle events also write persistent audit events (see **Audit** under [Security and tenant isolation](#security-and-tenant-isolation)); not every transition is an audit row.

The Work API does not start code attempts. Code attempts for generic tasks are a separate route, `POST /api/v1/tasks/{task_id}/attempts`, in `write` or `read_only` mode. Preparing one binds the attempt to an agent session and a Git worktree (the session's held worktree is reused, otherwise one is created), and the attempt's turn runs with that worktree as its working directory. A session whose worktree is unusable is refused rather than run somewhere else. This is a Git worktree and working-directory boundary, not an operating-system sandbox. Verification output for these attempts is stored as evidence under a per-company evidence root.

Tool effects inside chat turns are covered by the recovery ledger described under [Current limitations](#current-limitations); legacy task, goal, and orchestration surfaces remain available and behave as before.

The Work API itself (human principals and service keys only — an agent run token is refused with `403 AGENT_USES_TOOLS`, and a work order from another company is a plain 404):

| Method | Endpoint | Purpose |
| :--- | :--- | :--- |
| `POST` | `/api/v1/work` | Create a work order (requires an `Idempotency-Key` header; `400 IDEMPOTENCY_KEY_REQUIRED` without it) |
| `GET` | `/api/v1/work` | List the company's work orders |
| `GET` | `/api/v1/work/{work_id}` | Work-order detail with attempts |
| `POST` | `/api/v1/work/{work_id}/delegate` | Hand the order to a manager agent |
| `POST` | `/api/v1/work/attempts/{attempt_id}/review` | Human/service review endpoint: `verify` or `reject`, optional retry (agent managers use the `manager_review_work` tool) |
| `POST` | `/api/v1/work/{work_id}/cancel` | Cancel an order |

## Interfaces and providers

| Interface / provider | Status on `main` | Configuration | Notes |
| :--- | :--- | :--- | :--- |
| REST API + SSE | Available | Authenticated session or API key | OpenAPI docs at `/docs`; company always from the credential |
| React dashboard | Available | Local Compose port 3000; behind ingress in production | Company Work, agents, governance, budgets, memory, audit surfaces |
| Anthropic | Available | API key / company connections | Streaming chat adapter on the API chat path |
| OpenAI-compatible | Available | API key / company connections | Also the wire format for self-hosted gateways |
| Azure OpenAI (native) | Disabled by default | Operator-only `AZURE_OPENAI_*`, Entra default | Governed streaming tool loop; Entra scope and one end-to-end call live-validated ([acceptance record](docs/testing/evidence/azure-openai-entra/ACCEPTANCE.md)); production enablement is a separate decision |
| Azure OpenAI (legacy adapter) | Present, not recommended | API-key header | Non-streaming, not eligible for governed tool use |
| Azure Speech (STT/TTS) | Disabled by default, no consumer yet | Operator-only `AZURE_SPEECH_*`, Entra only | Transport foundation only, optional `speech` extra; live-validated scope ([acceptance record](docs/testing/evidence/azure-speech-provider/ACCEPTANCE.md)); no voice product ships today |
| Google Gemini / AWS Bedrock | Adapter present | Company connections | Not live-validated |
| Ollama | Adapter present | Local endpoint | Local and open-weight models |
| Claude Code CLI and employee CLIs | Available | Installed CLI binary | Execution backends for code attempts; CLI environments are allowlisted |
| Hermes | Adapter present; native governed provider disabled by default | Operator-only `HERMES_NATIVE_*` | Governed tool turns behind operator configuration (ADR 0005, proposed) |
| OmniRoute gateway | Optional (`gateway` compose profile) | Company connection + SSRF allowlist | Self-hosted LLM gateway; not started by default |
| MCP / generic tools | Available | Tool registry, MCP bindings | External tools default to the most conservative effect class |

## Quick start for local development

Requirements: Docker and Docker Compose v2. (A manual Python/Node setup is documented in [INSTALLATION.md](INSTALLATION.md).)

```bash
git clone https://github.com/naviyanka/NVLabsCompany.git
cd NVLabsCompany
docker compose up -d
```

This starts PostgreSQL (with pgvector), Redis, Temporal with its UI, a one-shot migration service, the API, the Temporal worker, the system runtime, and the dashboard. Migrations run before the API accepts traffic.

```bash
# Verify the API is up
curl http://localhost:8000/health
```

| Surface | URL |
| :--- | :--- |
| Dashboard | http://localhost:3000 |
| First-run setup | http://localhost:3000/setup |
| API | http://localhost:8000 |
| API docs (Swagger) | http://localhost:8000/docs |
| Temporal UI | http://localhost:8088 |

Open the dashboard and complete setup to create the first administrator; `/setup` locks afterwards and further users join by invitation. On first start the server seeds a default company with demo data for evaluation. To stop and keep data: `docker compose down`. To discard volumes: `docker compose down -v`. An optional self-hosted LLM gateway is available behind the `gateway` profile: `docker compose --profile gateway up`.

## Configuration and credentials

- **Development Compose** — `docker-compose.yml` ships development-only default database and Redis credentials so the stack boots with no configuration. Never reuse them outside local evaluation; they are not production values.
- **Production Compose** — `docker-compose.prod.yml` requires four administrator-provisioned env files (`.env.postgres`, `.env.migration`, `.env.production`, `.env.system`; examples at the repository root) that keep the bootstrap, migration, application, and system credentials apart. The API and worker must never receive the migration or system credentials — the processes refuse to start if they do.
- **Application settings** — environment variables or a root `.env` file (pydantic-settings); the session/CSRF cookie names, session lifetime, password minimum length, CORS origins, and logging level are all configurable. See [docs/ENVIRONMENT.md](docs/ENVIRONMENT.md).
- **Provider credentials** — Azure and Hermes-native providers are operator-only settings; agent configuration cannot aim provider settings or keys at a host. Secrets live in the secret backend (`fernet`-encrypted rows by default; OS keyring and read-only env backends available).
- **Filesystem roots** — workspace, repository, worktree, and task-evidence directories are per-company templates under `./data/...` by default and must be pinned for production.

## Testing and verification

CI (`.github/workflows/test.yml`) is authoritative:

- **Backend** — the pytest suite on SQLite, excluding PostgreSQL-marked files.
- **PostgreSQL integration** — the PostgreSQL/RLS/migration files against a real pgvector service, including a full Alembic `upgrade → downgrade → upgrade` cycle, role-separation and tenant-isolation proofs, and work-execution durability.
- **Frontend** — TypeScript typecheck, Vitest, and a production Vite build.
- **API parity** — the same endpoint spec run against a mock server and the real FastAPI backend.
- **End-to-end** — a separate Playwright workflow.
- **Compose boot smoke** — the stack must boot and report healthy.
- **Container and security checks** — offline Azure Speech SDK smoke, multi-architecture production image build with a Trivy scan, ruff (ratcheted), bandit, hadolint, Helm lint/kubeconform, and the architecture, generated-artifact, and test-invocation guard scripts.

For memory-bounded local runs, use the sequential chunk runner:

```bash
python scripts/run_pytest_chunks.py            # default: excludes PostgreSQL-marked files
python scripts/run_pytest_chunks.py --list     # show the plan without running
python scripts/run_pytest_chunks.py --postgres-only   # needs external PostgreSQL setup
```

It runs one pytest subprocess per chunk, strictly sequentially, and validates that no parallel options arrive through the environment or repository config. It is a local helper, not a CI replacement. Documentation: [docs/testing/PYTEST_CHUNK_RUNNER.md](docs/testing/PYTEST_CHUNK_RUNNER.md).

For documentation drift, the read-only auditor measures repository facts and reports stale claims:

```bash
python scripts/project_facts.py            # report only
python scripts/project_facts.py --check-docs   # exit 1 on objectively stale claims
```

It is a static scanner: it never imports the application or touches a network. Documentation: [docs/testing/PROJECT_FACTS_AUDITOR.md](docs/testing/PROJECT_FACTS_AUDITOR.md). No test totals are quoted in this README by design — static test-function counts are not "tests passed", and CI results are the source of truth.

## Deployment options

- **Local evaluation** — the default Compose stack above; self-contained, with development credentials and demo data.
- **Production Compose** — [docker-compose.prod.yml](docker-compose.prod.yml) with the four credential files, healthchecks, resource limits, and the system runtime as the single privileged process. There is no one-command production deployment: roles must be provisioned first (see the [database-roles runbook](docs/runbooks/database-roles.md)), and migration/rollback review is the operator's responsibility.
- **Helm** — [deploy/helm/nexus](deploy/helm/nexus) renders API, worker, system-runtime, and frontend deployments with a migration job, ingress, and secrets; linted and schema-validated in CI.
- **Before planning rollbacks**, read the [tool-effect recovery runbook](docs/runbooks/tool-effect-recovery.md): the ledger's downgrade is refused while recovery records exist.

## Current limitations

- **Pre-release** — no tags, no releases, no release workflow, and no SBOM signal exist in the repository.
- **Tool-effect recovery boundaries** — the ledger covers chat-turn paths only. REST node calls and background task attempts are outside that guarantee (task attempts carry their own idempotency keys). A client that retries with a new idempotency key creates a new logical write. A call whose lease lapses is treated as interrupted and follows recovery semantics: proven-idempotent calls may be retried automatically under the ledger and lease rules, while an ambiguous non-idempotent write is not rerun and waits for an operator decision through admin-only routes.
- **Notifications are at-most-once** — a crash between marking and sending loses the notification; nothing resends it. The ledger rows, not the notification channel, are the recovery record.
- **Voice is not a product** — browser voice and channel gateways are not implemented; the Azure Speech transport has no consumer. Azure experiments and acceptance probes do not constitute an available feature.
- **Memory lifecycle is phased** — evidence and governed trust promotion are implemented; later phases of the memory lifecycle are not yet on main.
- **Providers default to off** — Azure OpenAI and Azure Speech are disabled by default, and their production enablement (managed identity, service principals) is unvalidated.
- **Supply-chain hygiene is partial** — CI action references are mutable: two `trivy-action@master` branch references and 32 major-tag references remain, with no SHA-pinned actions.
- **Documentation drift exists outside this README** — some other documents still carry stale objective claims (counts, readiness language); the auditor's `--check-docs` reports them, and they are corrected outside this README.
- **Evaluation artifacts** — startup seeds demo data, and some dashboard surfaces include demo or fallback content.
- **No certification** — external production operation has not been certified, and no third-party security review is claimed.

## Status, roadmap, and documentation

- **Repository layout** — `src/nexus` (backend: API routes, adapters, governance, memory, runtime, orchestration, tools, knowledge, voice, system runtime) · `dashboard` (React app) · `alembic` (migrations) · `tests` (pytest; PostgreSQL-marked files run in the CI integration job) · `deploy` (Helm chart, role provisioning, monitoring config) · `docker` (container support files) · `docs` (ADRs, runbooks, provider and testing documentation) · `scripts` (guards, chunk runner, facts auditor, operator utilities) · `e2e` (Playwright specs)
- **Architecture decisions** — [ADRs](docs/adr/): [0001 single execution path](docs/adr/0001-single-execution-path.md), [0002 knowledge ownership](docs/adr/0002-knowledge-ownership-boundary.md), [0003 CEO control plane](docs/adr/0003-ceo-control-plane.md), [0005 Hermes governed tools](docs/adr/0005-hermes-native-governed-tools.md), [0006 Azure conversational CEO](docs/adr/0006-azure-conversational-ceo.md) (proposed).
- **Architecture reference** — [ARCHITECTURE.md](ARCHITECTURE.md) · [component matrix](docs/architecture/component-matrix.md)
- **Guides** — [INSTALLATION.md](INSTALLATION.md) · [API_GUIDE.md](API_GUIDE.md) · [FEATURES.md](FEATURES.md) · [dashboard/README.md](dashboard/README.md)
- **Runbooks** — [database roles](docs/runbooks/database-roles.md) · [system runtime](docs/runbooks/system-runtime.md) · [tool-effect recovery](docs/runbooks/tool-effect-recovery.md)
- **Security notes** — [tenant session audit](docs/security/TENANT_SESSION_AUDIT.md) · [ingress auth and webhooks](docs/security/INGRESS_AUTH_AND_WEBHOOKS.md) · [legacy channel ingress](docs/security/LEGACY_CHANNEL_INGRESS.md)
- **Provider references** — [Azure OpenAI](docs/azure-openai-provider.md) · [Azure Speech](docs/azure-speech-provider.md)
- **Verification evidence** — [acceptance records](docs/testing/evidence/) · [suite inventory](docs/testing/TEST_SUITE_INVENTORY.md) · [known baseline failures](docs/testing/KNOWN_BASELINE_FAILURES.md) · [CI baseline](docs/CI_BASELINE.md)

`docs/` also contains dated planning and audit documents (for example [docs/FINAL-STATUS-SUMMARY.md](docs/FINAL-STATUS-SUMMARY.md), [docs/PRODUCTION-READINESS-AUDIT.md](docs/PRODUCTION-READINESS-AUDIT.md), [docs/COMPARISON_REPORT.md](docs/COMPARISON_REPORT.md)). These are historical records of past points in time and are not maintained as current status; where they disagree with the auditor or with source, they are wrong.

## Contributing and support

See [CONTRIBUTING.md](CONTRIBUTING.md). In short:

- Changes require tests; CI is authoritative.
- Migrations must keep a single Alembic head; CI replays the full chain against real PostgreSQL.
- Security and tenant isolation are mandatory review dimensions, enforced by guard scripts and RLS tests rather than convention.
- Run the project-facts auditor before changing documentation claims.

There is no dedicated support channel or service-level commitment; open a GitHub issue on the repository.

## License

There is no `LICENSE` file at the repository root yet. Package metadata currently declares MIT; until a license file is added, the repository is not cleanly licensed for redistribution and no license badge is shown here.
