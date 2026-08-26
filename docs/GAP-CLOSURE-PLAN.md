# NVLabsCompany — Gap Closure Plan

> **Scope:** Everything partially built or not built, excluding Office 3D (explicitly deferred).
> **Basis:** Code-verified audit of `src/nexus/`, `dashboard/src/`, `e2e/` against all `/docs` plans.
> **Legend:** Effort S < 2h · M = 0.5–2d · L = 3–5d · XL > 1w. Priority P0 (correctness) → P3 (backlog).
> **Last verified against commit:** `1bbad4a` — 2026-08-26 — **Phase 0 COMPLETE**; **Phase 1**: W-01/02/03/04/05/06/07/08/09 done, plus K-01 (knowledge search reaches the RAG pipeline); **Phase 2**: R-01 partial (live surface met), R-02/R-03/R-04/R-05/R-06 done. **Phase 3 re-verified — E-02/E-05 shipped, E-04/E-06 shipped untested, E-03 is dead code, E-01 lacks a migration, and K-02 (chunk indexing) is a P0 break.** Backend: **3,184 tests passing, 1 skipped**. Frontend: `tsc --noEmit` clean.

---

## Phase 0 — Correctness Fixes ✅ DONE (2026-08-26)

Small items that were wrong and cheap to fix. All items below are complete unless noted.

| ID | Item | Status | Notes |
|----|------|--------|-------|
| F-01 | Hermes CEO unreachable via chat | ✅ FIXED | `_resolve_adapter_type()` now delegates to UASTL; `hermes` provider added with correct config keys (`ollama_host` + `openrouter_api_key`). Legacy `claude`→anthropic mapping preserved so existing agents don't silently switch to CLI subprocesses. Covered by `tests/test_chat_adapter_resolution.py`. |
| F-02 | Control router never mounted | ✅ FIXED | Mounted at `/api/v1/control/*`; paths prefixed in `control.py`; `test_control_registry.py` updated to mounted routes + mount regression test added. |
| F-03 | Dead code `uastl.py` | ✅ WIRED | Chat resolution is the single consumer; module no longer orphaned. |
| F-04 | Fabricated repo data | ✅ FIXED | Commits derived from real `git log` when a clone path exists; PRs/contributors return honest empty lists. Also fixed latent `timedelta` NameError in the old placeholder endpoints. |
| F-05 | Approvals page fake seed | ✅ FIXED | Mock deleted; page hits real `/approvals/pending` + `/approve|/reject` (old PATCH target never existed), renders secret-request payloads, shows error banner instead of silent fallback. |
| F-06 | Synthesized frontend fields | ✅ FIXED | Activity latencies → `—`; Evolution fabricated p-values/generation charts/random proposal creation → real `POST .../evolution/proposals` + live agent list + guarded evals panel; KnowledgeBase invented chunks/refCount/tags/dates removed; Budgets spend distribution computed from real agent spend, fake stat cards honest. **Amended 2026-08-26:** the KnowledgeBase claim was only partly true — the RAG tester still scored with `Math.random()`, `handleCreateDoc` still invented `chunks`/`refCount`/`created_at` and silently "saved" locally on API failure, and the loader fabricated `created_at`. Now fixed (see K-01). |
| F-07 | Hardcoded seed UUIDs | ✅ FIXED | Dashboard pipeline trigger, Budgets cap update, Approvals URLs all use `getActiveCompanyId()`. |
| F-08 | CORS wide open | ✅ ALREADY DONE | Verified `main.py` uses `settings.cors_origins` (never `*`) — the PRODUCTION-READINESS-AUDIT finding was stale. No change needed. |
| F-09 | Missing nav links | ✅ FIXED | "Approval Gate" and "Agent Terminal" added to sidebar groups. |
| F-10 | Dual schema management | ✅ FIXED | `create_all` gated to SQLite dev only; docker-compose backend runs `alembic upgrade head && uvicorn`. |

### Bonus fix discovered during Phase 0
Chat's missing-API-key flow ("secret proposals") was **silently broken**: it instantiated
`Approval(approval_type=..., title=..., description=...)`, but the model only has
`type`/`payload` columns — the TypeError was swallowed by try/except, so no proposal was
ever created. Fixed to write real columns; dedupe query corrected to `Approval.type`.
The seeded Hermes CEO now produces a working approval-gated key request instead of
nothing.

---

## Phase 1 — Finish Partially Built Subsystems (~3 weeks)

### W-01 Workflows API ↔ real engines ✅ DONE (2026-08-26)
`routes/workflows.py` rewritten from demo shell to real execution:
- New `WorkflowRun` SQLModel (`workflow_runs` table) + migration `a3f7c2d91b40`.
- `POST /workflows/company|task` create a persisted row and spawn the real
  `CompanyWorkflow.execute()` / `TaskFlow.execute_task()` as background tasks;
  runners write trace steps, status, cost, and errors back via their own session.
- Task flows register the company's real agents from DB and execute through the
  real `AdapterRegistry`.
- Status/trace/list/cancel all read from DB (tenant-scoped); cancel marks the row
  terminal first so a late engine finish cannot resurrect it.
- **Bonus fix:** the Alembic chain had two never-merged heads (auth branch vs
  workspaces branch) — `alembic upgrade head` failed. Added merge revision
  `m0001branch00`; full chain verified from scratch on a clean SQLite DB.
- Tests: `tests/test_workflow_routes.py` (11 tests) + migration-chain test updated.

### W-09 Repository clone path + real git history ✅ DONE (2026-08-26)
- `Repository.local_path` column added (+ migration `b5e8f3a72c10`); accepted on
  connect/update, exposed in responses.
- `/sync` now validates the clone exists and is a git repo (400 otherwise).
- `/tree` and `/diff` no longer fall back to the server's CWD — explicit
  "No local clone" results instead of silently reading the wrong repository.
- Tests: `tests/test_repository_clone.py` (6 tests).

### W-08 Chat cache cross-worker sync ✅ DONE (2026-08-26)
- `_get_history_fresh()` re-reads history from DB when the per-process cache is
  older than 5s; both chat endpoints use it. Bounded staleness replaces
  forever-stale cross-worker views. Covered by test in
  `test_chat_adapter_resolution.py`.
- (Original plan suggested Redis pub/sub; the TTL approach was chosen first —
  dependency-free and satisfies the acceptance bar. Redis invalidation can be
  layered on when R-02 lands.)

### W-02 Node library execution layer (XL, P1) — ✅ DONE (2026-08-26)
- New `nodes/executor.py`: `NodeExecutor`/`ExecutorRegistry` + timeout-enforced `execute_node()`.
- 14 real executors bound to catalog IDs: `ai-chat`, `ai-summarize`, `ai-translate`,
  `ai-sentiment` (UASTL-routed LLM), `http-request` + `msg-webhook-notify`
  (httpx with SSRFGuard URL blocking), `file-json-parse`, `file-csv-parse`,
  `db-redis-get`, `db-redis-set`, `db-sqlite-query`, `msg-slack-send`,
  `msg-discord-send`, `msg-telegram-send`.
- New endpoint `POST /api/v1/nodes/{id}/execute`: 404 unknown, 503 defined-but-not-executable, structured result otherwise.
- AuditLog recorded on every execution (company-scoped, action=`node_execute:{id}`).
- OTel trace span wraps `execute_node()` (no-op fallback when SDK absent).
- Tests: `tests/test_node_executor.py` (10 tests incl. SSRF block + timeout).

### W-03 Temporal integration — RESOLVED: intentionally optional + observable (2026-08-26)
- Decision: **keep** Temporal. The package was already feature-flagged (`USE_TEMPORAL`) with lazy SDK imports and an out-of-process worker in docker-compose; it only lacked observability and tests.
- Added a `temporal` entry to `GET /system/degradation`: full (enabled + SDK), degraded (enabled but temporalio not installed), unavailable (disabled).
- Tests cover default-off behavior and the degradation entry.

### W-04 Comms channels — ✅ DONE (2026-08-26)
- All three placeholder senders replaced with real HTTP calls: **WebhookChannel** posts JSON signed with `X-Nexus-Signature` (HMAC-SHA256 over exact body bytes) and enqueues failures into `WebhookDeliveryQueue` for retry/dead-letter; **SlackChannel** posts via incoming webhook; **DiscordChannel** posts via bot-token REST (`/channels/{id}/messages`).
- Unconfigured channels now return `False` honestly (two old tests asserting fake success updated).
- **Inbound**: Slack Events API endpoint (`POST /api/v1/channels/slack/events`) handles `url_verification` challenge and `app_mention` events → creates a Task. Email notifications via `EmailChannel` (SMTP with TLS, async thread offload).
- OTel trace span on `ChannelRouter.route_outbound()`.
- Per-company token storage deferred to Phase 3 (secret_backend already supports it).

### W-05 HRRoom persistence (M, P2) — ✅ DONE (2026-08-26)
- Models: `TrainingCurriculum`, `PerformanceReview` (SQLModel + migration `c7d9e1f4a520`).
- Routes: CRUD under `/api/v1/companies/{id}/hr/curricula` and `/hr/reviews`.
- Frontend: 8KB of fabricated `DEFAULT_HR_AGENTS`/`DEFAULT_CURRICULA` deleted; agents loaded from real API; curricula fetched from `/hr/curricula`; `handleEnroll` POSTs to backend; `handleSaveAppraisal` POSTs reviews; all `|| 95` / `|| 'Graduated'` / `|| ['Standard Operator v1']` / `|| 'Nominal performance'` defaults replaced with honest `'—'`.
- **Accept (met):** no HR data lost across reload.

### W-06 Theme system wiring ✅ DONE (2026-08-26)
- `ThemeTab` imported into `OtherSettingsTabs`; the `appearance` nav entry was
  previously rendering the wrong tab entirely (fell through to DataAuditTab).
- Saved theme now restored at boot in `main.tsx` (no flash of default theme).

### K-01 Knowledge search actually reaches the RAG pipeline ✅ DONE (2026-08-26)
Found while verifying F-06's KnowledgeBase claim. Three defects, all masked by
swallowed exceptions:
- **`get_session()` yielded a SQLAlchemy `AsyncSession`, which has no `.exec()`.**
  Eight call sites across `knowledge/rag.py`, `knowledge/plaza.py`, and
  `knowledge/experience.py` call `await self.db.exec(statement)`, so every one of
  them raised `AttributeError` in production. The tests passed because their mock
  sessions stub `session.exec`. Fixed at the source: the factory now yields
  SQLModel's `AsyncSession` (a subclass of the SQLAlchemy one, so `.execute()`
  callers are unaffected) — one line, all eight sites.
- **`rag_search` read ORM attributes off `RAGPipeline.search()` results**, but
  `search()` returns dicts (`{"chunk", "bm25_score", "vector_score",
  "combined_score"}`). The `AttributeError` was caught by a bare `except`, so
  every search silently degraded to the `ilike` substring fallback — the hybrid
  BM25 + vector path was unreachable. Now unpacks the dicts, exposes
  `combined_score` as `score` on `RAGSearchResult`, and logs a warning when it
  does fall back.
- **The dashboard RAG tester never called the backend at all**: it scored docs
  with `0.45 + Math.random() * 0.2` behind a 400 ms fake-latency `setTimeout` and
  displayed the result as "% Vector Match". Now POSTs to
  `/knowledge/search` and renders the real `combined_score` (an unbounded BM25
  blend, so it is labelled `score N.NNN`, not a percentage) plus the chunk index.
- Also in `KnowledgeBase.tsx`: `handleCreateDoc` sent invented `chunks`/`version`
  the API does not accept and, on failure, wrote a fake "Operator (Local)" doc
  into state so a failed publish looked successful — replaced with an error
  banner. Loader no longer stamps `created_at = now()` on records that have none.
- Tests: `tests/test_knowledge_rag_search_route.py` (3 tests: real-path unpacking
  with score, fallback on pipeline failure, and a guard that app sessions expose
  `exec`). Full suite green: 3184 passed, 1 skipped.

### W-07 Evolution loop completion ✅ DONE (2026-08-26)
- The orchestrator's auto-evaluate job existed but **fabricated scores** (constant 0.55 baseline, hardcoded 10% improvement, `passed=True`). Rewritten to compute real scores via the same LLMEvolutionAdvisor path as the manual evaluate endpoint (with conservative heuristic fallback).
- Auto-promotion now requires explicit `EVOLUTION_AUTO_PROMOTE=true` — default matches the documented policy that promotion never happens automatically (the old code silently promoted at confidence ≥0.8, contradicting the promote route's governance gate).
- Tests in `tests/test_leftovers_channels_temporal_evolution.py`.

---

## Phase 2 — Production Hardening (~4 weeks)

These match the open items in `PRODUCTION-READINESS-AUDIT.md` §3 that are still true today.

### R-01 Persist in-memory orchestration state — IN PROGRESS
Code-verified reality (2026-08-26) differs from the original audit:
- **ControlRegistry ✅ DONE** — persistence was fully built (`_persist()` on every mutation + load-on-init) but the singleton was constructed with no path, so it silently no-op'd. Now wired via new `data_dir` setting → `data/control_registry.json`; restart-survival covered by `tests/test_control_registry_persistence.py`.
- **LayeredMemoryStore** — also has complete file persistence (`persist_path`, L1 separate file) but is **instantiated nowhere** in production code; chat memory reads are already DB-first (`MemoryRecord`). No live gap unless/until something adopts it.
- **PhaseMachine** — dead code path: zero imports outside its own module; persistence moot until wired.
- **GoalLoop / Orchestrator** — GoalLoop is per-request/transient; the orchestrator loop is DB-first per tick (`_drive_goal` re-reads goal rows). Restart mid-request loses at most one iteration — acceptable.
- **Accept (met for the live surface):** pause/gate/steer/halt state survives process restart via `tests/test_control_registry_persistence.py`.

### R-02 Redis-backed distributed primitives, enabled by config — ✅ DONE (2026-08-26)
- **Company rate limiting ✅**: `GovernanceMiddleware._check_rate_limit()` prefers `RedisRateLimiter` (sliding-window sorted sets, mirrors in-memory 100/min limits, burst 0) whenever `REDIS_URL` yields a working limiter; falls back to the in-memory limiter on absence/error so single-process deployments are unchanged. Covered by `tests/test_middleware_rate_limiting.py`.
- **Leader election ✅**: `governance/leader_election.py` — Redis `SET NX EX` lease with `NoopLeaderElection` fallback; scheduler, orchestrator, and watchdog loops gated via `is_leader()`. Tests: `tests/test_leader_election.py` (3 tests).
- **Budget tracker ✅**: `_BudgetTracker.record_spend()` now fires Redis `INCRBY` for cross-worker spend visibility (best-effort, non-blocking); falls back to in-memory accumulation when Redis is unavailable.
- Degradation endpoint reports rate-limiter backend (Redis/in-memory).

### R-03 Observability completion — ✅ DONE (2026-08-26)
`logging_config.py` already ships: JSON line formatter, request-scoped `correlation_id` ContextVar, and `RequestIDMiddleware` propagating `X-Request-ID` inbound→outbound.
- New `nexus/observability/tracing.py`: thin OTel wrapper that uses real spans when `opentelemetry-api` is installed and degrades to zero-cost no-op spans otherwise. Provides `get_tracer()` and `@trace_span()` decorator.
- Instrumented: `execute_node()` (node_id + success attributes), `ChannelRouter.route_outbound()` (route_key + channel + delivered).
- No hard dependency added — OTel packages remain optional (`pip install opentelemetry-api opentelemetry-sdk` enables export).

### R-04 Real sandbox isolation for evolution experiments (L, P2) — ✅ DONE (verified 2026-08-26)
`isolated_sandbox.py` provides both layers:
- `IsolatedSandbox`: logical resource tracking (cost/duration/memory accumulators) with `ResourceLimitExceeded` on breach.
- `DockerSandbox`: container-isolated execution via `docker run --rm --memory --cpus --network=none --read-only --tmpfs /tmp` with `asyncio.wait_for` timeout; auto-detects Docker availability at init and falls back to `IsolatedSandbox` when absent.
- **Accept (met):** experiment exceeding mem cap is killed in-container; host unaffected; verdict recorded. Degradation entry already exists for Docker availability.

### R-05 Governance encryption placeholder ✅ DONE (2026-08-26)
- `config_governance.encrypt_sensitive_value` now uses Fernet (AES-CBC + HMAC) with a PBKDF2-derived key (distinct salt from the secret backend), plus new `decrypt_sensitive_value`. Fail-closed: raises when no key can be derived. Tamper/missing → None.
- Covered by `tests/test_config_governance_encryption.py` (6 tests).

### R-06 Duplicate route definitions cleanup ✅ DONE (2026-08-26)
- Runtime audit found 10 duplicate method+path registrations across `knowledge.py`, `meetings.py`, `tools.py`, and `tasks.py` (later same-module redefinitions; FastAPI kept the first, so behavior is unchanged).
- **Bonus bug:** `tasks.py` had a dangling `@router.post(.../subtasks)` decorator with no function — Python attached it to the *next* def, so `POST /tasks/{id}/subtasks` returned task statistics. Removed.
- Verified: 0 duplicate method+path pairs across all routes (312 registrations as of 2026-08-26; the count grows as routes land — re-verify, do not trust the number).

---

## Phase 3 — Enterprise & Integration Gaps

**Re-verified against code 2026-08-26 (commit `1bbad4a`).** The table below was
written from `FINAL-STATUS-SUMMARY.md` and had gone stale in the optimistic
direction *and* the pessimistic one: E-02/E-05 shipped, E-04/E-06 shipped
untested, and E-03 shipped a module nothing calls. Statuses are now code-checked.

| ID | Item | Verified status | Remaining work | Pri |
|----|------|-----------------|----------------|-----|
| K-02 | **Knowledge chunk indexing** | ❌ **BROKEN** — `RAGPipeline.index_chunks()` has zero production callers; nothing writes `knowledge_chunks`. `publish_page` and `/knowledge/import` store page rows only, so RAG search (fixed in K-01) queries a permanently empty table. | Call chunk+index on publish/import/update; backfill existing pages | **P0** |
| E-01 | OKR relational model | ⚠️ **PARTIAL** — schema is done: `models/okr.py` (`okr_objectives`, `okr_key_results`), `routes/okr.py` DB-backed via `DbSession`, and migration `b4e44200443e_add_okr_tables.py` creates both tables with a working downgrade (single head `b4e44200443e`). What remains is a **duplicate store**: `company/okr.py`'s `OKRManager` still reads *and writes* `data/okrs_database.json` with its own dataclasses, and is exported from `company/__init__.py`. | JSON importer + retire or rebase `OKRManager` | **P1** |
| E-02 | SSO/OAuth (OIDC) federation | ✅ **DONE** — `auth/oidc.py`, `routes/sso.py` (`/auth/sso/login`, `/auth/sso/callback`), `oidc_*` settings, feature-flagged off by default; 8 test files reference it. | — | — |
| E-03 | Document conversion (PDF/DOCX) | ⚠️ **PARTIAL** — `knowledge/document_converter.py` ships `PDFParser`/`DOCXParser` (pypdfium2 + python-docx, graceful import failure), but **nothing imports it** and no endpoint accepts `UploadFile`. Dead code. | Upload endpoint → converter → chunk/index (pairs with K-02) | **P1** |
| E-04 | SCIM/LDAP directory sync | ⚠️ **UNTESTED** — `routes/scim.py` implements SCIM v2 `/Users` (GET/POST/PUT/PATCH) and is mounted, but **0 test files** reference it. | Test coverage; confirm auth on the SCIM surface | P2 |
| E-05 | Multi-workspace switching UI | ✅ **DONE** — `routes/workspaces.py` (list/create/activate/delete) + `WorkspaceSwitcher` rendered in `layout/Header.tsx`; 4 test files. | — | — |
| E-06 | Telegram remote control | ⚠️ **UNTESTED** — `routes/telegram_bot.py` handles `/webhook` with status/agents/task commands, mounted, but **0 test files**. | Test coverage; webhook secret verification | P2 |
| E-07 | Desktop Tauri app | ⚠️ **SCAFFOLD ONLY** — `desktop/src-tauri/tauri.conf.json` exists (productName NEXUS, identifier `com.nvlabs.nexus`, devUrl `http://localhost:5173`, 1400×900 window) and `desktop/package.json` has a `cargo tauri dev` script with no dependencies. Never built or run; no CI. | Verify it builds, or delete the scaffold rather than leave it implying a shipped app | P3 |
| E-08 | Agent performance profiling view | ❌ Not started — no `routes/usage.py`, no usage/metric models, no profiling page. The "existing usage tables" this item assumed **do not exist**. | Needs a data source first; scope before building | P3 |

---

## Phase 4 — QA, Release & Docs Truthfulness (~2 weeks)

### Q-01 Playwright suite for real (L, P1)
Current state: untouched scaffold config (no `webServer`), smoke spec asserts `true`, example spec tests playwright.dev, one auth spec self-skips without creds.
- Enable `webServer` block: boot docker-compose deps + backend + dashboard dev server.
- Specs: login/session+CSRF, setup-first-admin, agent hire→wake→chat(SSE)→pause, task assign→run, pipeline run, approval gate blocks ungoverned action, tenant isolation (company B gets 404), kill switch 503.
- CI job running suite on PRs (12.6).
- **Accept:** suite green locally and in CI without manual stack prep.

### Q-02 Backend test coverage for new work
Zero tests currently reference `temporal` or the node library. Every Phase 0–2 item above ships with tests (project norm: ~2,900 existing tests, keep it that way).

### Q-03 Docs reconciliation (S per doc, P1)
The docs tree actively lies in both directions — future sessions will trust stale plans:
- `wiring-plans/TASKS.md`: mark completed items `[x]` (sections 10.6/10.7, 11.x, 12.x partial, 13–19 where commits landed); delete or archive superseded TODOs.
- `API-GAPS-PLAN.md`: rewrite against current reality (most Phase A/B items done).
- `PRODUCTION-READINESS-AUDIT.md` §3.3: CORS finding resolved upstream long ago — annotate as fixed so future readers don't re-audit it.
- `ceo-orchestration-guide.md` ("100% Fully Wired") and `nvlabsorg-comparison.md` ("25/25"): correct percentages or add staleness banner.
- `ARCHITECTURE.md`: fix known inaccuracies — office-babylon doesn't exist (it's office2d + mock-grid office3d), memory/dedup cycle status, control-router mount status post-F-02.
- Adopt one rule going forward: **status lives in code-checked docs or not at all** — every plan doc gets a "Last verified against commit" header.

### Deferred (per decision)
- **Office 3D** entire program: `FloorPlan.md` Babylon build, `OFFICE-3D-MICRO-PHASES.md`, office3d mock-grid replacement, Pixi subtree fate, unused three.js deps removal. Revisit only after Phase 0–2.

---

## Suggested Execution Order

```
Week 1      Phase 0 (F-01..F-10)            ← ✅ DONE 2026-08-26
Weeks 2-4   Phase 1: W-01 ✅ · W-09 ✅ · W-06 ✅ · W-08 ✅ · W-03 resolved · W-04 ✅
            W-07 ✅ · W-02 ✅ · W-05 ✅
Weeks 5-8   Phase 2: R-05 ✅ · R-06 ✅ · R-01 ✅ · R-02 ✅ · R-03 ✅ · R-04 ✅
Week 9      Q-01/Q-03                       ← release gate
Post-prod   Phase 3 backlog in P2→P3 order
```

Dependency notes:
- W-02 depends on nothing; unlocks real workflow value alongside W-01.
- R-01 should precede R-02 (persist locally first, share second).
- E-05 (workspace switcher) touches same files as F-07 — do after F-07.
- Q-01 specs encode acceptance criteria of F-02, W-01, R-01 — write specs alongside, not after.
