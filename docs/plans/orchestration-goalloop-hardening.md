# Orchestration & GoalLoop hardening — deterministic crash resumption

Target: the `Orchestration & GoalLoop` row of `docs/PRODUCTION_SCORING_REPORT_AND_ROADMAP.md`
(section 2.3), currently 8.0/10. The report names one gap: interrupted work is
detected but never resumed.

## What the code actually does today

`src/nexus/runtime/orchestrator.py` drives goals on a 120s tick under Redis
leader election. `_drive_goal` reads a goal's subtasks and:

- returns early while any subtask is in `pending`, `in_progress`, or `running`
  (line 176);
- executes `pending` subtasks with an assigned agent via `_execute_subtasks`,
  which calls the LLM and then writes a terminal status.

`_execute_subtasks` never claims a task. A task goes straight from `pending` to
`completed`/`failed`; `started_at` is never set and `in_progress` is never
written by the orchestrator at all. Two consequences:

1. **Double dispatch.** A tick that crashes after the LLM call but before commit
   leaves the task `pending`, so the next tick pays for the same LLM call again.
   The `MAX_ITERATIONS_PER_GOAL` branch (line 345) also writes
   `status="pending"` for deferred tasks, so a deferred task is indistinguishable
   from a fresh one.
2. **No resumption target.** Nothing records that a task was in flight, so there
   is nothing for a resumption supervisor to find.

Separately, `_tick` selects only `Goal.status == "active"`. The Temporal path
(line 113) sets `goal.status = "in_progress"` after dispatch. If that workflow
dies, the goal is never selected again — stranded with no owner and no reaper.

The existing recovery machinery stops one step short of resumption:
`PersistentHeartbeatService.reclaim_orphans` (called from `main.py:219`) marks a
dead run's agent `needs_recovery`, and `watchdog_service.patrol_once` files a
human decision for it (commit e8a1940). Neither touches the goal/task rows, so
the work itself stays stuck. `CheckpointManager.recover_interrupted`
(`runtime/checkpoint.py:188`) reads its own in-memory list and has no production
caller — it cannot see anything a crashed process wrote.

## Scope

Close the resumption gap on the path that actually runs work (the orchestrator
tick), using the status columns that already exist. Explicitly out of scope:
`CheckpointManager` DB persistence (the unit of work is a single LLM call — a
step checkpoint has nothing to store), TLA+ verification of `PhaseMachine`, and
cryptographic idempotency keys for tool side effects.

## Micro-phases

Each phase is one commit: code, one test file or added test class, `pytest` green.

### P1 — Claim a subtask before executing it

`_execute_subtasks` sets `status="in_progress"` and `started_at=utcnow()` and
**commits** before the LLM call, so an interrupted task is identifiable as
in-flight rather than fresh. The deferred-task branch keeps its own status so it
is not confused with a claim.

Test: a task whose execution raises after the claim is left `in_progress` with
`started_at` set; a task that completes ends terminal.

### P2 — Reap stale in-flight subtasks

A task `in_progress` with `started_at` older than a stale cutoff (2x
`SUBTASK_TIMEOUT_SECONDS`) belongs to a process that is gone. Mark it `failed`
with `completion_reason=timeout` through `_finish`, which unblocks
`_drive_goal`'s `active_subtasks` early return so the goal's failure handling
runs.

Runs at the top of `_tick` (every tick covers the crash-during-run case and the
crash-while-down case; no separate startup hook needed).

Test: stale in-flight task is reaped and its goal proceeds; a fresh in-flight
task is left alone.

### P3 — Reap goals stranded by a dead Temporal workflow

A goal `in_progress` whose `updated_at` is older than a stranding cutoff is
returned to `active` so the tick picks it up again. Guarded so a live Temporal
workflow (which updates the goal as it progresses) is not clawed back.

Test: stranded goal returns to `active`; a recently-updated `in_progress` goal
does not.

### P4 — Report update

Update section 2.3 of `docs/PRODUCTION_SCORING_REPORT_AND_ROADMAP.md` to state
what now resumes and what remains (formal verification, tool-level idempotency
keys).

## Verification

`pytest tests/test_orchestrator_recovery.py tests/test_goal_loop.py
tests/test_watchdog_escalation.py -q` after each phase.
