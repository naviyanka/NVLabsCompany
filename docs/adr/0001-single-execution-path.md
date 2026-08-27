# ADR 0001 — Temporal is the single authoritative execution path

**Status:** Accepted
**Date:** 2026-08-26
**Relates to:** `docs/FEATURE_PLAN.md` Phase 0.4, enforced by `scripts/arch_guard.py` rule R3

## Context

The project currently runs work through three independent paths that do not share a state
model:

1. `src/nexus/runtime/orchestrator.py` — a background asyncio task started at app lifespan,
   composing the pure modules in `src/nexus/orchestration/` (planner, router, parallel,
   retry, critic) into a goal-pursuit loop.
2. `src/nexus/temporal/` — `GoalPursuitWorkflow` and `PipelineExecutionWorkflow`, with
   activities wrapping the same orchestration modules. State is persisted by Temporal.
3. `src/nexus/workflows/` — `task_flow.py`, `pipeline.py`, and `company_flow.py`, each
   holding execution state in module-level Python dicts (`_executions`, `_results`,
   `_traces`, `_stages`) that are lost on restart.

Trigger dispatch is duplicated the same way: `src/nexus/runtime/scheduler.py` is DB-backed
with a 60-second tick, while `src/nexus/triggers/scheduler.py` keeps a `_triggers` dict in
memory.

Every reference implementation surveyed in `docs/COMPARISON_REPORT.md` converges on exactly
one authoritative execution state machine. Clawith makes this a constitutional rule with CI
enforcement: API and product code must submit through `RuntimeCommandIntake` and must never
touch checkpoint tables or invoke graph nodes directly, precisely so that a second state
machine cannot appear. paperclip achieves the same result with a Postgres run ledger plus a
recovery service, and OpenCompany with Temporal workflows whose bodies contain no I/O.

Three paths produce concrete defects rather than merely untidy code. A run started on one
path is invisible to the other two, so budget enforcement, audit logging, heartbeat
liveness, and crash recovery each see a partial picture of what the system is doing. Two
schedulers can fire the same trigger twice, or lose it entirely after a restart depending on
which one owns it.

## Decision

Temporal is the authoritative execution path. Specifically:

- **Temporal owns execution state.** Workflow bodies contain orchestration logic only. Every
  operation that touches an LLM, the database, a socket, or a subprocess is an activity.
  Activities that incur billing use a once-only retry policy, because LLM calls are not
  idempotent.
- **`runtime/orchestrator.py` is the only driver.** It decides what work should exist and
  starts workflows. It does not execute work itself.
- **`workflows/` become thin façades.** `TaskFlow`, `PipelineEngine`, and `CompanyWorkflow`
  keep their public signatures so callers do not break, but delegate to Temporal activities.
  Their in-memory dicts are removed once activities own the state.
- **One scheduler.** The DB-backed `runtime/scheduler.py` survives. The capabilities unique
  to `triggers/` — `classifier.py`, `context_trigger.py`, `history.py` — fold into it, and
  `triggers/scheduler.py`'s in-memory store is deleted. `TriggerConfig` survives as a DTO.
- **A local fallback runner, not a second path.** When Temporal is unreachable, an in-process
  executor runs the same activity functions in sequence. This is one code path with two
  runners, which is different from two code paths.
- **`orchestration/` stays pure.** The planner, router, critic, and retry modules remain free
  of DB and I/O imports so that both runners can call them. `arch_guard.py` rule R5 enforces
  this.

## Consequences

**Positive.** Budget enforcement, audit logging, heartbeat liveness, and crash recovery each
observe every run rather than a subset. Crash resumption comes from Temporal's event history
instead of hand-rolled checkpoint reconciliation. `runtime/checkpoint.py`'s
`recover_interrupted()` becomes a narrow safety net rather than the primary mechanism.

**Negative.** Temporal becomes a hard operational dependency for full durability, and local
development leans on the fallback runner. Workflow code must respect Temporal's determinism
constraints, which is a real constraint on how orchestration logic may be written. Migrating
`company_flow.py` in particular touches the approval and budget gates, so it carries the most
risk in Phase 0.4.

**Neutral.** The façade classes stay in place, so this is mostly invisible to API routes.

**Enforcement.** `scripts/arch_guard.py` rule R3 fails CI when `src/nexus/workflows/` imports
`AsyncSession` directly, and rule R4 fails when a module named `*_persistent.py` does not.
Rule R5 keeps `orchestration/` free of DB imports. Pre-existing violations are recorded in
`scripts/arch_guard_baseline.json`, each annotated with the phase that removes it; the file
shrinks as Wave 0 lands.

## Alternatives considered

**Keep `runtime/orchestrator.py` authoritative and drop Temporal.** This is what paperclip
does, and it works — but it means hand-writing the watchdog, retry, and recovery machinery
that Temporal provides. paperclip needs roughly 8,000 lines across `heartbeat.ts`,
`recovery/service.ts`, and `task-watchdogs.ts` to get there. Temporal is already wired here.

**Keep `workflows/` authoritative and treat Temporal as optional.** Rejected because the
in-memory dicts are the specific defect being fixed; promoting that path would mean
reimplementing durability inside it.

**Leave all three and document which to use when.** Rejected. The reference implementations
that stayed healthy at scale all chose one, and Clawith's decision to make it a CI-enforced
invariant rather than a documented convention reflects how quickly a second state machine
reappears otherwise.
