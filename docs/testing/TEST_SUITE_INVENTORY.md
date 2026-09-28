# Test suite inventory

Snapshot: 2026-09-27. Counts come from
`python -m pytest tests/ --collect-only -q` after the changes in this phase.

- Backend: **200** test files, **5,073** collected tests (including
  `tests/test_postgres_integration.py`, which skips without PostgreSQL).
- Dashboard: **11** vitest files under `dashboard/src`.

The groups below are by subsystem. The number after each file is its test
count. File names drop the `test_` prefix.

### Employee core: CLI adapters, chat, sessions (5 files, 143 tests)

`chat_adapter_resolution` (11), `cli_adapter` (46), `cli_adapter_interactive` (19), `cli_employee_foundation` (59), `concurrent_employee_chat` (8)

### Chat and agent sessions (8 files, 128 tests)

`agent_sessions` (25), `canvas_api` (11), `chat_durable_memory` (8), `chat_session_compat` (6), `chat_stream_persistence` (4), `mcp_bindings_api` (11), `session_compaction` (52), `workspace_api` (11)

### Adapters and providers (12 files, 254 tests)

`adapter_tool_guarding` (13), `adapters` (35), `claude_code_adapter` (27), `connections_wp22b` (4), `http_adapter_webhook` (24), `llm_circuit_breaker` (17), `openai_adapter_wp22a` (2), `provider_adapters` (29), `provider_presets` (34), `provider_registry` (21), `semantic_fallback` (31), `smart_retry` (17)

### Knowledge, memory, RAG, Obsidian (39 files, 1161 tests)

`ab_testing` (19), `chunk_source_migration` (6), `embedding_dimension_guard_wp22j` (5), `embeddings` (35), `evaluation_framework` (75), `evolution` (54), `failure_alchemy` (18), `integration_registry` (28), `knowledge` (25), `knowledge_graph` (31), `knowledge_plaza_collab` (29), `knowledge_rag_search_route` (3), `layered_memory` (60), `layered_memory_l1` (9), `layered_memory_persistence` (16), `leftovers_channels_temporal_evolution` (9), `llm_critic` (18), `llm_evolution` (18), `llm_extract` (12), `llm_planner` (10), `llm_proposer` (7), `memory` (25), `memory_graph_frontend_contract` (21), `memory_reflector` (66), `obsidian_api` (40), `obsidian_indexer` (36), `obsidian_rag_integration` (18), `obsidian_scanner` (21), `obsidian_smoke_authenticated` (6), `obsidian_temporal` (65), `obsidian_vault` (51), `obsidian_wikilinks` (56), `obsidian_writeback_preconditions` (127), `obsidian_writer` (8), `pgvector_search` (3), `rag_pipeline_enhanced` (81), `semantic_memory` (20), `statistical` (19), `statistical_failure_analyzer` (11)

### Agents, hiring, archetypes, company (13 files, 596 tests)

`agents` (17), `archetypes` (195), `closing_time` (56), `communication` (38), `company` (40), `company_portability` (14), `demo` (28), `hire_manifest` (60), `identity` (35), `meetings` (23), `okr` (25), `scim` (48), `templates` (17)

### Worktrees, git, sandboxes (12 files, 628 tests)

`docker_sandbox` (11), `isolated_sandbox` (12), `p6_0_security_prereqs` (29), `p6_1_git_runner` (74), `p6_2_agent_worktree` (54), `p6_3_worktree_service` (171), `p6_4_worktree_api` (126), `p6_5_git_worktrees` (67), `p6_5_hardening` (39), `repository_clone` (6), `sandbox_backends` (23), `worktree` (16)

### Runtime: orchestrator, scheduler, workflows, recovery (38 files, 716 tests)

`a2a_router` (39), `checkpoint` (12), `collab_correctness` (18), `completion_reasons` (16), `context_trigger_conditions` (41), `decision_queue_persistence` (22), `delegation_isolation` (16), `delegation_permits` (3), `durable_checkpoint_recovery` (10), `execution_context` (35), `goal_loop` (25), `graceful_shutdown` (6), `heartbeat_persistence` (16), `hive_backend` (21), `hive_manager` (11), `hive_protocol` (7), `hive_router` (9), `leader_election` (3), `node_executor` (10), `orchestrator_recovery` (7), `phase_machine` (24), `pipeline_execution_context` (10), `pipeline_save` (10), `reasoning` (24), `replay_engine` (32), `rollback` (20), `run_tokens` (18), `scheduler_persistence` (25), `temporal_activity_layer` (9), `triggers` (40), `watchdog` (31), `watchdog_escalation` (7), `webhook_intake` (14), `webhook_queue` (28), `webhook_server` (58), `workflow_routes` (11), `workflows` (27), `ws03_backfill` (1)

### Governance: budget, policy, tools, audit, approvals (46 files, 947 tests)

`approval_signing` (10), `approvals_persistence` (11), `audit_service_chain` (8), `autonomy_policy` (22), `breaker_trip_propagation` (10), `budget` (18), `budget_failclosed_wp22e` (2), `budget_incidents` (34), `budget_read_path_wp23c` (6), `budget_reservation` (11), `budget_tier2_wp22g` (3), `bulkhead` (4), `catalog_wp22c` (4), `circuit_breaker_advanced` (37), `compliance` (28), `config_governance_encryption` (6), `config_validator` (14), `control_registry` (35), `control_registry_persistence` (3), `cost_alerting` (23), `cost_micros_wp22d` (3), `degradation_endpoint` (15), `enforcement_matrix` (90), `governance` (15), `guardrails` (69), `idempotency_middleware` (2), `incidents` (23), `mcp_catalog_wp22h` (4), `mcp_server` (28), `mcp_stdio` (27), `middleware_rate_limiting` (6), `persistent_circuit_breaker` (15), `plugin_sdk` (48), `policies` (41), `preflight_budget` (14), `pricing` (47), `rate_limiter` (23), `skill_policy` (6), `skill_policy_wiring` (5), `skills_catalog` (13), `skills_discovery` (17), `tool_access` (39), `tool_audit` (39), `tool_catalog` (27), `tool_factory` (6), `tool_governance` (36)

### Security, auth, tenancy, secrets (15 files, 268 tests)

`api_versioning` (12), `arch_guard` (20), `auth_enforcement` (31), `gateway_admin_wp22f` (3), `gateway_headers_wp22i` (4), `prework_security_fixes` (22), `review_fixes` (16), `secret_backend_persistence` (32), `secret_rotation` (18), `secrets` (21), `secrets_key_schedule` (7), `ssrf_protection` (48), `tenant_guard` (20), `tenant_isolation` (11), `utcnow_removal` (3)

### Persistence, migrations, infra, observability (12 files, 232 tests)

`alembic_migration` (7), `devops_enterprise` (18), `health_probes` (14), `logging_telemetry` (30), `models` (26), `observability_enterprise` (14), `persistence` (23), `postgres_integration` (6), `realtime_sse` (16), `realtime_websocket` (44), `redis_state` (25), `tracing` (9)

### Dashboard (vitest)

`components/agents/__tests__/HireAgentModal`, `components/canvas/__tests__/CanvasView`,
`components/chat/__tests__/ConcurrentChat`, `components/pipelines/__tests__/PipelineBuilderCanvas`,
`hooks/useEventStream`, `pages/__tests__/Activity`, `AppRoutes`, `Approvals`,
`Pipelines`, `Tasks`, `Workspace`.

## Markers

| Marker | Applied to |
|--------|-----------|
| `core_employee` | `test_cli_employee_foundation`, `test_chat_adapter_resolution`, `test_cli_adapter`, `test_cli_adapter_interactive`, `test_concurrent_employee_chat` (module-level `pytestmark`) |
| `postgres`, `integration` | `test_postgres_integration` |
| `slow` | Registered, not yet applied (see "Slowest files") |
| `real_cli` | Registered, no tests yet. Skipped unless `NEXUS_REAL_CLI=1`. The real-CLI checks live in `scripts/cli_employee_smoke.py` and `scripts/cli_employee_concurrency_smoke.py`. |

See [EMPLOYEE_CORE_TESTING.md](EMPLOYEE_CORE_TESTING.md) for the profiles that
use them.

## Slowest files

From the junit report of a full run on 2026-09-27 (call phase only). The whole
run took about 13 minutes, but test bodies account for only about 160 s. The
rest is per-test fixture setup (fresh SQLite schema, app startup), so marking
individual tests `slow` would save little. `slow` is registered but not yet
applied. It is worth applying if the fixture cost is reduced first.

| Test | Call time |
|------|-----------|
| `test_temporal_activity_layer::test_run_resumes_after_the_worker_dies` | 10.1 s |
| `test_pipeline_execution_context::test_the_callers_context_survives_a_real_temporal_run` | 5.4 s |
| `test_pipeline_save::test_write_and_execute_are_granted_separately` | 5.4 s |
| `test_pipeline_save::test_a_manager_may_run_pause_and_stop` | 5.4 s |
| `test_pipeline_execution_context::test_a_manager_run_hands_temporal_the_managers_context` | 5.3 s |
| `test_watchdog::TestBackgroundPatrol::test_patrol_loop_runs_with_provider` | 4.0 s |

Slowest files by summed call time: `test_p6_5_git_worktrees` (21 s, real git),
`test_pipeline_save` (11 s), `test_pipeline_execution_context` (11 s),
`test_temporal_activity_layer` (10 s), `test_watchdog` (10 s).

## Merged and removed tests in this phase

Only duplicates were merged. No test was removed without a replacement that
asserts the same behaviour, and none of the protected areas were touched
(RLS/tenant isolation, migrations, budget/concurrency, auth, tool governance,
audit integrity, recovery/checkpoint, worktree/path security, idempotency,
provider-resolution fail-closed, employee chat attribution).

All changes are in `tests/test_cli_adapter.py`:

| Removed | Replacement |
|---------|-------------|
| `TestCLIAdapterBuildArgs::test_build_args_claude` | `test_build_args_golden_argv[claude-plain]` |
| `TestCLIAdapterBuildArgs::test_build_args_claude_with_extra` | `test_build_args_golden_argv[claude-verbose]` |
| `TestCLIAdapterBuildArgs::test_build_args_codex` | `test_build_args_golden_argv[codex-plain]` |
| `TestCLIAdapterBuildArgs::test_build_args_codex_with_extra` | `test_build_args_golden_argv[codex-model]` |
| `TestCLIAdapterBuildArgs::test_build_args_aider` | `test_build_args_golden_argv[aider-plain]` |
| `TestCLIAdapterBuildArgs::test_build_args_aider_with_extra` | `test_build_args_golden_argv[aider-model]` |
| `TestCLIAdapterBuildArgs::test_build_args_kiro_cli` | `test_build_args_golden_argv[kiro-cli]` |
| `TestCLIAdapterBuildArgs::test_build_args_opencode` | `test_build_args_golden_argv[opencode]` |
| `TestCLIAdapterBuildArgs::test_build_args_agy` | `test_build_args_golden_argv[agy]` |
| `TestCLIRegistry::test_claude_backend_build_args_via_registry` | `test_build_args_golden_argv[claude-plain]` (`CLIAdapter._build_args` delegates to `CLIBackendInfo.build_args`, so the table exercises the registry builder) |
| `TestCLIRegistry::test_aider_backend_build_args_via_registry` | `test_build_args_golden_argv[aider-verbose]` |
| `TestCLIRegistry::test_probe_version_success` | `test_cli_employee_foundation.py::test_version_probe_reads_stdout_or_stderr` (stdout, stderr and the timeout argument) |

Net: 12 tests became one parametrized test with 10 rows, and one version-probe
test was dropped as a duplicate. `tests/test_cli_adapter.py` went from 49 to 46
collected tests.

## Added in this phase

`tests/test_audit_service_chain.py::TestConcurrentWriters::test_contended_writes_survive_an_earlier_event_loop`
is a regression test for the audit chain lock fix (`58320f1`). The backend count
above was taken before it was added, so the suite now collects 5,074 tests.

## Fixed in this phase

`tests/test_bulkhead.py::test_tenant_bulkhead_enforces_global_cap` now expects
`GlobalSaturated`. See [KNOWN_BASELINE_FAILURES.md](KNOWN_BASELINE_FAILURES.md).
