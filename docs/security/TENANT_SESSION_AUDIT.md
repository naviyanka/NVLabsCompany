# Tenant session audit

`async_session_factory()` opens a session with no RLS tenant. On PostgreSQL,
connected as the application role, such a session reads nothing from a
tenant-owned table, and every insert into one fails the policy's `WITH CHECK`.
Background code often only logs that failure, so the work silently disappears.

This audit covers every function under `src/nexus` that opened a raw session.
Each one was classified as one of the following.

- **tenant**: tenant-owned work. It now uses `tenant_session(company_id)` or
  `tenant_session_factory(company_id)`, which set `nexus.company_id` on every
  transaction.
- **system**: cross-tenant maintenance. `system_session` no longer exists. Finding
  which companies have work is done only by the system runtime process, through
  `system_runtime.db.discovery_session(op)`; the work itself is a tenant session.
  See [system-runtime.md](../runbooks/system-runtime.md).
- **allowed raw**: not tenant work (discovery, global tables, bootstrap). The
  raw session stays, and the reason is recorded in `ALLOWED` in
  `tests/test_tenant_session_guard.py`.

The guard test parses the source tree and fails when a function outside
`ALLOWED` names `async_session_factory`, or when an `ALLOWED` entry no longer
uses it. A new raw session therefore needs a stated reason, reviewed with the
change.

## Callers changed to tenant sessions

All of these previously used a raw session (`async_session_factory`).

| Caller | Models accessed | Change | Test coverage |
|---|---|---|---|
| `api/routes/chat.py::_fetch_shared_knowledge` | `MemoryRecord` (L3 shared) | `tenant_session_factory(company_id)` passed to `PersistentLayeredMemory` | `test_chat_durable_memory.py` |
| `api/routes/chat.py::_remember_response` | `MemoryRecord` | `tenant_session_factory(agent.company_id)` | `test_chat_durable_memory.py`, `test_concurrent_employee_chat.py` |
| `api/routes/chat.py::_call_llm` (Hermes tool registration) | `Tool`, `ToolAccess`, `ToolInvocation`, vault grants, `AuditLog` | `ToolRegistry` and `ObsidianNoteReplaceTool` get `tenant_session_factory(agent.company_id)` | `test_enforcement_matrix.py`, `test_obsidian_writer.py`, chat tests |
| `api/routes/identity.py::update_agent_soul` | `Agent` | Takes `CurrentCompanyId`, uses `tenant_session(company_id)`, and scopes the `UPDATE` to `Agent.company_id` | guard test only |
| `api/routes/nodes.py::execute_node_endpoint` (audit) | `AuditLog` | The hand-built `AuditLog` row (which had no chain links, used a nonexistent `actor` field and swallowed every error) was replaced by `record_audit` | `test_enforcement_matrix.py::test_path_matrix[node_rest-*]` checks the entry, its company and its chain links |
| `api/routes/pipelines.py::_execute_pipeline_bg` | `PipelineRun`, `Pipeline`, `Agent` | `tenant_session(company_id)`; run and pipeline lookups also filter on `company_id` | `test_pipeline_save.py`, `test_pipeline_execution_context.py` |
| `api/routes/workflows.py::_persist_completion` | `WorkflowRun` | `tenant_session(company_id)` | `test_workflow_routes.py` |
| `api/routes/workflows.py::_register_company_agents` | `Agent` | `tenant_session(company_uuid)` | guard test only |
| `api/routes/slack_events.py::slack_events`, `api/routes/telegram_bot.py::telegram_webhook` | none | Legacy inbound routes disabled; they open no session and write nothing (see [Legacy channel ingress](LEGACY_CHANNEL_INGRESS.md)) | `test_channel_tenant_binding.py`; PostgreSQL: `test_legacy_channel_webhooks_create_no_task_in_any_company[slack\|telegram]` |
| `api/routes/audit.py::verify_audit_chain` | `AuditLog` | `PersistentAuditLogger(session_factory=tenant_session_factory(company_id), company_id=company_id)`; verifies that company's chain only | PostgreSQL: `test_concurrent_audit_writes_form_one_valid_chain_per_company` |
| `runtime/event_bridge.py::_handle_task_failure` | `Task`, `EvolutionProposal` | `tenant_session(company_uuid)`; both counts also filter on `company_id` | guard test only (fire-and-forget analysis) |
| `temporal/activities.py::call_llm_activity` | `Agent`, memories | `tenant_session(company_uuid)`. The session now closes before the model call, so no transaction is held while the model runs. | `test_temporal_activity_layer.py`, `test_pipeline_execution_context.py` |
| `temporal/activities.py::route_task_activity` | `Agent` | `tenant_session(company_uuid)` | guard test only |
| `temporal/obsidian_activities.py::list_pending_obsidian_documents_activity` | `VaultDocument` (via `VaultIndexer`) | `tenant_session(company_id)` | `test_obsidian_temporal.py` |

"Guard test only" means no behaviour test drives that function against
PostgreSQL. The guard test proves it no longer opens a raw session, and the
PostgreSQL RLS tests below prove that `tenant_session` itself scopes correctly.

## Slack and Telegram tenant resolution

Neither webhook payload carries a tenant. There is also no installation table
that maps a Slack workspace or a Telegram bot to a company. Binding the routes
to the company of the calling API key fixed the tenant, but not the sender: an
API key names a company, not the person who wrote the message, so every sender
was treated as an authorized operator. The legacy Slack and Telegram inbound
routes are therefore disabled outright. They return 410
`LEGACY_CHANNEL_INGRESS_DISABLED`, read no body and write nothing. See
[Legacy channel ingress](LEGACY_CHANNEL_INGRESS.md).

## Callers that used system sessions (removed)

These ran cross-tenant discovery or recovery through `system_session(reason)`, so the
API and worker processes held a `BYPASSRLS` credential. `system_session` and the
second engine behind it are deleted. Each caller moved as follows.

| Former caller | Now |
|---|---|
| `main.py::lifespan` (budget tracker and policy cache seeding, recovery reconcile) | Removed from the lifespan. Budget state loads lazily per company; recovery is the system runtime's `task_recovery`, `chat_turn_recovery` and `task_attempt_recovery` operations. The lifespan refuses to start if `SYSTEM_DATABASE_URL` is set. |
| `runtime/chat_turns.py` sweep | `chat_turns.recover_company(company_id)` in a tenant session, driven by the `chat_turn_recovery` operation |
| `runtime/orchestrator.py` goal discovery | The `goal_discovery` operation publishes company ids as work hints; the orchestrator reads hints and runs each company in `tenant_session`. Without hints it does nothing; it never enumerates tenants. |
| `runtime/scheduler.py` reservation reaping | `budget_reservation_reap`, per company, with an explicit `company_id` filter because `cost_events` has no RLS policy |
| `runtime/scheduler.py` due-trigger lookup | Trigger rows are not under RLS and are read with the application role; each firing runs in `tenant_session` |
| `runtime/task_attempts.py` sweep | `task_attempts.recover_company(company_id)`, driven by `task_attempt_recovery` |
| `runtime/watchdog_service.py` patrol | The `watchdog_patrol` operation discovers agents; the patrol of each agent runs in `tenant_session` |
| `runtime/org_snapshot.py` refresh | `org_snapshot_refresh`: discovery returns company ids, each snapshot is built in `tenant_session` |

The static guard `tests/test_system_runtime_process.py` fails if any file outside the
system runtime reads `SYSTEM_DATABASE_URL`, or imports its operations or runner.

## Justified raw sessions (`ALLOWED`)

| Caller | Category | Justification |
|---|---|---|
| `auth/middleware.py::AuthenticationMiddleware._resolve` | discovery | Resolves the credential to a principal before the tenant is known |
| `tools/mcp_server.py::authenticate` | discovery | Resolves the MCP API key before the tenant is known |
| `api/routes/webhooks.py::resolve_webhook_trigger_context` | discovery | Pre-tenant webhook trigger lookup; derives the company from an authenticated trigger before `tenant_session` is possible. See below |
| `governance/audit_persistent.py::PersistentAuditLogger._sessions` | system | Default only when no factory is passed. The one production constructor (`verify_audit_chain`) now passes a tenant factory. |
| `runtime/checkpoint.py::save_checkpoint_nonblocking` | system | `execution_checkpoints` is not tenant-scoped |
| `runtime/watchdog_service.py::_file_decision` | system | Decision queues are not tenant-scoped; the queue row carries `company_id` |
| `tools/factory.py::_access_session` | system | Used only when no company is known; `tenant_session` otherwise |
| `tools/registry.py::ToolRegistry.__init__` | system | Default for the global tools catalogue; tenant callers pass `tenant_session_factory` |
| `triggers/executor.py::TriggerExecutor._factory` | system | Default for trigger execution records, which are not tenant-scoped |
| `auth/bootstrap.py::_main` | bootstrap | First-admin CLI, run before any tenant exists |
| `demo/seed.py::_main` | bootstrap | Development seed CLI, run as the database owner |
| `main.py::lifespan` | bootstrap | Default-company seed and budget flush (`companies`), kill switch and circuit breaker (global tables), secret backend (`stored_secrets`); none is tenant-scoped |

### Webhook trigger lookup (`resolve_webhook_trigger_context`)

`POST /api/v1/webhooks/{trigger_id}` is called by an external service with no
session, so the only thing that names the tenant is the trigger. The route cannot
open `tenant_session(company_id)` before it knows the company, and `triggers` is
not under row-level security, so there is no tenant to bind first.

- **Where:** `api/routes/webhooks.py::resolve_webhook_trigger_context`. It is the
  only raw `async_session_factory` use there and the only entry the guard allows.
  `receive_webhook` is not allowlisted, and the guard fails if a raw session
  appears in it or in any other function.
- **Query scope:** one `SELECT` by primary key on `triggers`, returning id,
  company id, agent id, name, type, `is_active` and the config values it needs
  (`inbound_secret`, prompt). The helper takes no `company_id`, lists nothing,
  writes nothing and creates no task, goal, chat turn, tool invocation, memory or
  workflow row. It returns a frozen value object (the secret is excluded from its
  `repr`), never an ORM object or session, and the session is closed on return.
- **Fail closed:** an unknown, inactive, wrong-type or wrong-secret trigger gets
  the same bare 401 and reveals nothing about any tenant. The secret is checked
  before the company is used for anything.
- **After the lookup:** the idempotency claim, completion and release, the agent
  read and the execution record all use `tenant_session(company_id)`. The raw
  session is closed before the idempotency claim, prompt construction and the
  model call.
- **Tests:** `tests/test_webhook_intake.py::TestPreTenantLookup`.

## Audit writes

`record_audit(company_id, ...)` without a `db` opens `tenant_session(company_id)`.
With a `db`, it writes in the caller's session. Either way, the row is linked
into its company's own hash chain; see migration `e7a1c2d3f404`.

An audit row with `company_id=None` (a system event) is invisible to the
application role and cannot be inserted by it, because the RLS policy compares
against a non-null tenant. No process holds a general-purpose system session any
more, so `record_audit` fails closed for such a row:

- it logs the failure;
- with `raise_on_error=True`, it raises;
- it never writes an unchained row in place of the refused one.

## PostgreSQL RLS coverage

The following tests in `tests/test_postgres_integration.py` run as the
application role.

| Test | What it proves |
|---|---|
| `test_alternating_tenants_on_one_pooled_connection` | A pool of one connection alternates between two tenants, and each session sees only its own rows. A bare session afterwards sees none. |
| `test_tenant_session_keeps_tenant_context_across_commits` | The tenant is reapplied after a commit on the same session. |
| `test_background_audit_write_carries_the_tenant` | An audit write from background code carries its tenant. |
| `test_a_session_without_a_tenant_cannot_mutate_tenant_rows` | Updates and deletes affect 0 rows, and inserts are refused by row-level security. |
| `test_legacy_channel_webhooks_create_no_task_in_any_company[slack\|telegram]` | The disabled legacy webhooks create no task in the caller's company or any other. |
| `test_concurrent_audit_writes_form_one_valid_chain_per_company` | 24 racing audit writes over two companies produce two gap-free chains, both verify, and no rows leak across tenants. |
| `test_an_audit_write_without_a_tenant_is_refused_not_unchained` | An audit write without a tenant is refused rather than written unchained. |
