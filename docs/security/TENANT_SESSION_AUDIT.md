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
- **system**: cross-tenant maintenance. It uses `system_session(reason)`, which
  requires a role with `BYPASSRLS`.
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
| `api/routes/slack_events.py::slack_events` | `Task` | Company from the authenticated principal (`CurrentCompanyId`), not the hardcoded seed UUID; `tenant_session` | `test_channel_tenant_binding.py`; PostgreSQL: `test_channel_webhooks_write_into_the_callers_company[slack]` |
| `api/routes/telegram_bot.py::_handle_agents`, `_handle_task` | `Agent`, `Task` | Company from the authenticated principal, not `pick_setup_company` (the oldest company); `tenant_session` | `test_channel_tenant_binding.py`; PostgreSQL: `test_channel_webhooks_write_into_the_callers_company[telegram]` |
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
that maps a Slack workspace or a Telegram bot to a company. Before this change:

- Slack wrote every task into the hardcoded seed company
  `00000000-0000-4000-8000-000000000001`.
- Telegram wrote into the oldest company (`pick_setup_company`).

Both now take the company of the authenticated principal (`CurrentCompanyId`).
The authentication middleware resolves the credential, and an API key is issued
for exactly one company. A request without a credential is refused with 401
before the handler runs, and it is never assigned to a default company.

With `AUTH_ENABLED=false` (legacy development mode), `X-Company-Id` is the
principal.

## Callers that already used system sessions

These run cross-tenant discovery or recovery and hold `BYPASSRLS` through
`system_session(reason)`. They were reviewed and left unchanged, because the
discovery itself is legitimate. Each hands the tenant work it finds to a
tenant session.

- `main.py::lifespan`: seeds the budget tracker and policy cache, and
  reconciles recovery.
- `runtime/chat_turns.py`: chat turn recovery.
- `runtime/orchestrator.py`: discovers active goals.
- `runtime/scheduler.py`: reaps reservations and finds due triggers.
- `runtime/task_attempts.py`: task attempt recovery.
- `runtime/watchdog_service.py`: discovers the agent's company and runs patrol
  discovery.

## Justified raw sessions (`ALLOWED`)

| Caller | Category | Justification |
|---|---|---|
| `auth/middleware.py::AuthenticationMiddleware._resolve` | discovery | Resolves the credential to a principal before the tenant is known |
| `tools/mcp_server.py::authenticate` | discovery | Resolves the MCP API key before the tenant is known |
| `governance/audit_persistent.py::PersistentAuditLogger._sessions` | system | Default only when no factory is passed. The one production constructor (`verify_audit_chain`) now passes a tenant factory. |
| `runtime/checkpoint.py::save_checkpoint_nonblocking` | system | `execution_checkpoints` is not tenant-scoped |
| `runtime/watchdog_service.py::_file_decision` | system | Decision queues are not tenant-scoped; the queue row carries `company_id` |
| `tools/factory.py::_access_session` | system | Used only when no company is known; `tenant_session` otherwise |
| `tools/registry.py::ToolRegistry.__init__` | system | Default for the global tools catalogue; tenant callers pass `tenant_session_factory` |
| `triggers/executor.py::TriggerExecutor._factory` | system | Default for trigger execution records, which are not tenant-scoped |
| `auth/bootstrap.py::_main` | bootstrap | First-admin CLI, run before any tenant exists |
| `ceo_knowledge_seed.py::seed_ceo_knowledge` | bootstrap | Development seed of non-RLS `memory_records` |
| `demo/seed.py::_main` | bootstrap | Development seed CLI, run as the database owner |
| `main.py::lifespan` | bootstrap | Default-company seed and budget flush (`companies`), kill switch and circuit breaker (global tables), secret backend (`stored_secrets`); none is tenant-scoped |

## Audit writes

`record_audit(company_id, ...)` without a `db` opens `tenant_session(company_id)`.
With a `db`, it writes in the caller's session. Either way, the row is linked
into its company's own hash chain; see migration `e7a1c2d3f404`.

An audit row with `company_id=None` (a system event) is invisible to the
application role and cannot be inserted by it, because the RLS policy compares
against a non-null tenant. Such rows can only be written through a caller's
`system_session`. Without one, `record_audit` fails closed:

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
| `test_channel_webhooks_write_into_the_callers_company[slack\|telegram]` | Each webhook's task lands in the caller's company and nowhere else. |
| `test_concurrent_audit_writes_form_one_valid_chain_per_company` | 24 racing audit writes over two companies produce two gap-free chains, both verify, and no rows leak across tenants. |
| `test_an_audit_write_without_a_tenant_is_refused_not_unchained` | An audit write without a tenant is refused rather than written unchained. |
