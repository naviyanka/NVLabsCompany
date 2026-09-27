# Known baseline failures

Snapshot: 2026-09-27, `main` after `1f4a494`.

Before this phase the full backend suite had exactly **14** failing tests. They
reproduce on a clean checkout and predate the employee chat work. One of them
(the bulkhead test) sits on the chat concurrency path and was fixed in this
phase. The other 13 are still failing and are listed below with the next action.

Full-suite command (from `.github/workflows/test.yml`):

```bash
DATABASE_URL=sqlite+aiosqlite:///./test.db AUTH_ENABLED=false \
  python -m pytest tests/ --ignore=tests/test_postgres_integration.py -q
```

Every phase should compare the exact `FAILED` node IDs against this list. A new
ID is a regression. A missing ID means someone fixed it, so update this file.

## Summary

| # | Test | Subsystem | First failing commit | Employee/CLI related | Status |
|---|------|-----------|----------------------|----------------------|--------|
| 1 | `tests/test_bulkhead.py::test_tenant_bulkhead_enforces_global_cap` | governance / bulkhead (used by chat concurrency) | `ef0fe16` (2026-09-09, WP-19d) | Yes | **Fixed in this phase** |
| 2 | `tests/test_completion_reasons.py::test_goal_reason_on_successful_subtask` | runtime / orchestrator | `ef0fe16` | No | Fix later |
| 3 | `tests/test_completion_reasons.py::test_no_tool_calls_reason_on_empty_output` | runtime / orchestrator | `ef0fe16` | No | Fix later |
| 4 | `tests/test_completion_reasons.py::test_timeout_reason_when_llm_exceeds_budget` | runtime / orchestrator | `ef0fe16` | No | Fix later |
| 5 | `tests/test_completion_reasons.py::test_budget_exhausted_reason_blocks_before_the_call` | runtime / orchestrator | `ef0fe16` | No | Fix later |
| 6 | `tests/test_completion_reasons.py::test_needs_help_reason_when_agent_escalates` | runtime / orchestrator | `ef0fe16` | No | Fix later |
| 7 | `tests/test_completion_reasons.py::test_error_reason_on_unhandled_failure` | runtime / orchestrator | `ef0fe16` | No | Fix later |
| 8 | `tests/test_completion_reasons.py::test_max_iterations_reason_when_tick_budget_runs_out` | runtime / orchestrator | `ef0fe16` | No | Fix later |
| 9 | `tests/test_durable_checkpoint_recovery.py::TestOrchestratorResumptionAndAuditTrail::test_execute_subtasks_resumes_from_checkpoint_and_emits_audit` | runtime / orchestrator | `ef0fe16` | No | Fix later |
| 10 | `tests/test_orchestrator_recovery.py::TestSubtaskClaim::test_crash_mid_execution_leaves_the_task_claimed` | runtime / orchestrator | `ef0fe16` | No | Fix later |
| 11 | `tests/test_orchestrator_recovery.py::TestSubtaskClaim::test_successful_execution_still_ends_terminal` | runtime / orchestrator | `ef0fe16` | No | Fix later |
| 12 | `tests/test_pgvector_search.py::test_search_pushes_distance_into_sql` | knowledge / RAG | `6814424` (2026-09-09, WP-7..14) | No | Fix later |
| 13 | `tests/test_scheduler_persistence.py::TestCronTriggerSurvivesRestart::test_due_trigger_fires_on_a_fresh_scheduler_tick` | runtime / scheduler | `ef0fe16` | No | Fix later |
| 14 | `tests/test_scheduler_persistence.py::TestCronTriggerSurvivesRestart::test_one_shot_trigger_deactivates_after_firing` | runtime / scheduler | `ef0fe16` | No | Fix later |

None of these was marked `skip` or `xfail`, and none was deleted.

Final full run at the end of this phase (after `58320f1` and the test-profile
changes): **13 failed, 5,047 passed, 8 skipped** in 13 min 25 s. The 13 failing IDs
are exactly rows 2 to 14 above. There are no new failures.

## Details

### 1. Bulkhead global cap (fixed)

- **Error:** `nexus.governance.bulkhead.GlobalSaturated: Global concurrency cap reached`
- **Root cause:** WP-19d (`ef0fe16`) added a separate `GlobalSaturated`
  exception for the process-wide cap. The test still expected
  `TenantSaturated` when a third tenant, which is still under its own cap, hits
  the global cap. The code is right: that case is global saturation.
- **Why it matters here:** direct employee chat takes a bulkhead slot per turn
  (`_chat_turn_slot`), and a saturated bulkhead becomes `429 CHAT_CONCURRENCY_LIMIT`.
- **Fix:** the test now expects `GlobalSaturated`. `tests/test_bulkhead.py` passes 4/4.

### 2–11. Orchestrator `_execute_subtasks` signature (10 tests)

- **Error:** `TypeError: _execute_subtasks() takes 2 positional arguments but 3 were given`
- **Root cause:** WP-19a (`ef0fe16`) changed `Orchestrator._execute_subtasks`
  to `(tasks, company_id)`. Each subtask now opens its own tenant-scoped
  session instead of sharing the caller's `db`. These tests still call
  `_execute_subtasks(db, tasks, company_id)`.
- **Next action:** drop the `db` argument in the calls and monkeypatch
  `nexus.database.async_session_factory` (or the orchestrator's session
  factory) to the test's `session_factory`, so the per-task sessions see the
  test database. This is a test-only change. Owner: runtime.

### 12. pgvector distance pushdown

- **Error:** `AttributeError: 'tuple' object has no attribute 'content'` (in `nexus/knowledge/rag.py`, hybrid BM25 channel)
- **Root cause:** WP-7..14 (`6814424`) added a BM25 channel that runs a second
  query (`all_chunks = list(result.all())`) and expects chunk rows.
  `FakePGSession` in the test returns `(chunk, distance)` tuples for every
  query, so the BM25 path receives tuples.
- **Next action:** make the fake session answer the vector query and the
  chunk-listing query differently, or patch the BM25 channel off for this
  SQL-shape test. Owner: knowledge.

### 13–14. Cron trigger survives restart

- **Error:** `sqlalchemy.exc.OperationalError: (sqlite3.OperationalError) no such table: triggers`
- **Root cause:** since `ef0fe16` the scheduler's `_tick` reads triggers
  through `system_session(...)`, which uses the global system session factory.
  It ignores the `session_factory` the test passes in, so it queries a database
  that has no tables.
- **Next action:** monkeypatch `nexus.database.async_session_factory` and
  `_system_session_factory` to the test's factory. Owner: runtime.

## Order-dependent failure found and fixed in this phase

- **Test:** `tests/test_audit_service_chain.py::TestConcurrentWriters::test_concurrent_writes_do_not_duplicate_a_sequence`
- **Symptom:** `assert 1 == 8`. It failed in the full suite and passed alone.
  The warning log showed `Audit log write failed: <asyncio.locks.Lock ...> is bound to a different event loop`.
- **Root cause:** `audit_service._chain_lock` was a module-level
  `asyncio.Lock`. An asyncio lock binds to the first event loop that has to
  wait on it. After concurrent employee turns (`33be4f9`) made
  `tests/test_agent_sessions.py` contend the lock, every contended write in a
  later test's loop raised. `record_audit` swallows write errors by design, so
  7 of the 8 rows were dropped silently. At `056976c` the pair
  `test_agent_sessions.py` + `test_audit_service_chain.py` passes; at `1f4a494`
  it fails.
- **Fix:** `58320f1` keeps one lock per running loop. A new regression test
  runs a contended burst on a separate loop first, then checks that every row
  of a burst on the test loop is kept.

## Related environment issue (fixed)

`alembic upgrade head` on a fresh database used to fail at the seed step:
`table agents has no column named focus_items`. Two model columns never got a
migration: `agents.focus_items` (added in `0be6843`) and
`user_profiles.oidc_sub`. Tests build tables with `create_all`, so the suite
did not notice. Migration `e7a1c2d3f401` adds both (only when missing, so hand
patched databases are fine). `tests/test_alembic_migration.py::TestChainExecution::test_migrated_schema_matches_the_models`
now builds a database from migrations alone and fails on any model table or
column the migrations do not create. Older FK and index differences are listed
in that test one by one.
