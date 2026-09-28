# Employee work execution: manual acceptance evidence

Recorded 2026-09-27 on branch `feat/employee-work-execution`. Real Claude Code (`claude` backend) and Antigravity
(`agy` backend) CLI employees were used. Nothing was mocked.

## Rig

- One PostgreSQL 16 database, migrated with `alembic upgrade head` from empty. The backend ran as the RLS-bound app
  role.
- A single backend ran on one port. S4 used a second process to restart it.
- `AUTH_ENABLED=false`.
- A local git repository `calc-demo` held one `init` commit. Each attempt ran in its own git worktree, under a
  worktree root that is separate from the repository.
- `drive.py` is the API client that produced every `*.txt` file.
  - It calls only the public HTTP API: create task, start, retry, list attempts, evidence.
  - Each line has a UTC timestamp.
  - `watch` prints an attempt only when its visible state changed.
- `dump.py` read the durable rows at the end (`db_dump.json`), through the system role.
  - It lists attempts, work effects (the idempotency keys of side effects), chat turns, and audit action counts for
    each task.
  - Its DSN comes from `ACCEPTANCE_SYSTEM_DSN`.
- `spec1.json`…`spec4.json` are the `work_spec` bodies of the tasks.
- Sanitisation:
  - The worker host name is replaced with `<host>`.
  - The server already reports paths as `<worktree>` and `<evidence>`.
  - These files contain no credentials, environment variables or provider auth data.

## Results

| Scenario | Backend | Files | Result |
|---|---|---|---|
| S1: write calculator and tests | claude | `s1r2_*` | PASS |
| S2: read-only review of S1's diff | agy | `s2_*` | PASS |
| S3: verification fails, retry fixes it | claude | `s3r2_*` | PASS |
| S4: backend killed mid-run, restarted | claude | `s4r2_*` | PASS |
| All: no duplicated effects | n/a | `db_dump.json` | PASS |

Three earlier runs are kept as the evidence for the bugs they found (`s1_*`, `s3_*`, `s4_*`). See
[Bugs found](#bugs-found-by-the-real-runs).

### S1: Claude writes a calculator with tests (task `7141d465`)

1. `s1r2_start.txt` called `start` three times:
   - the first call returned `201` for attempt `778703ae`;
   - the second, with the same `Idempotency-Key`, got the stored `201` replayed;
   - the third, with a different key, returned `200` `created: false` for the same attempt, which was running by
     then.

   One attempt was created.
2. Claude wrote `src/calculator.py` and `tests/test_calculator.py`, ran pytest itself, and wrote progress reports
   (`report_seq` 3, final `state: completed`).
3. The server did not take the report's word for it:
   - it re-ran `pytest tests/test_calculator.py` in the worktree;
   - it checked both deliverables and the `pattern_count` criterion (5 `def test_` ≥ 4);
   - it hashed both artifacts;
   - it committed them once, as `dca3db1` "Task attempt 1 for task 7141d465…".

   The artifacts show `validation: verified` with that commit.
4. Outcome: task `completed`, `completion_reason: goal`. The commit contains only the two deliverables: no
   `__pycache__`, `.pytest_cache`, `.nexus/` or `.claude/`.

### S2: Agy reviews Claude's diff read-only (task `8fc0e17b`)

- `spec2.json` has `mode: read_only` and `review_of_task_id: 7141d465`.
- Agy ran in its own worktree of S1's commit, ran the tests, and reported a summary starting with `REVIEW:`.
- Verification checks, all passed:
  - `command:0:pytest`
  - `criterion:report mentions 'REVIEW'`
  - `read_only_worktree_clean` (0 changed paths)
  - `reviewed_worktree_unchanged` (S1's worktree head unchanged, 0 changed paths)
- A read-only attempt commits nothing.

### S3: failed verification, then a retry fixes it (task `6ac0dcac`)

The failure was scripted. `spec3.json`'s objective tells the employee that this is a drill: on attempt 1 it writes only
`src/calculator.py`, skips the tests, and still reports `completed`. The purpose is to show that a completed report
with a clean CLI exit is not enough. Claude followed the instruction.

1. Attempt 1 (`bd675134`) reported `state: completed` and the CLI exited 0. The server failed it with
   `completion_reason: verification_failed`. Failed checks:
   - `deliverable:tests/test_calculator.py`
   - `command:0:pytest` (exit 4)
   - `criterion:… 'def test_' at least 4 times` (found 0)
   - `criterion:pytest passes`

   Nothing was committed.
2. `s3r2_retry.txt`: `retry` was called twice. The first call returned `201` for attempt 2 (`54eb4ba8`); the second
   returned `200` with the same attempt.
3. Attempt 2 received the failed checks in its prompt, wrote the tests, and passed every check. It committed once, as
   `c42922d` "Task attempt 2 …" (`s3r2_git.txt`: one commit on top of `init`).
4. `GET …/attempts` and the evidence endpoint still return attempt 1 with its failed checks, report and command logs.

### S4: backend hard-killed while Claude is running (task `8b0c7576`)

1. Attempt `f3a47561` was claimed by worker `<host>:11228:…`, and Claude started as a child of the backend
   (`s4r2_before_kill.txt`: CLI pid 27032, parent 11228).
2. The backend process was hard-killed.
   - `s4r2_kill.txt`: the CLI process disappeared with it. The backend puts the CLI process tree in a Windows Job
     Object that has kill-on-close set, so no orphaned employee kept writing into the worktree.
   - `s4r2_worktree_after_kill.txt` shows the worktree state at that moment.
3. A new backend process started (`<host>:24964:…`).
   - After the lease expired, the attempt went back to `queued` with `recoveries: 1`.
   - It was re-claimed on the same session and the same chat turn, with a new execution id (`9d06fdc1`).
4. The attempt then completed with `goal`. `s4r2_git.txt` shows exactly one commit `681dd0b` on top of `init`,
   containing only `src/stats.py` and `tests/test_stats.py`, and a clean `git status`.
5. `db_dump.json` for this task:
   - `task.attempt_recovered: 1`
   - `task.attempt_completed: 1`
   - no duplicate effect keys

Recovery is lease-based and stored in PostgreSQL. It does not depend on in-memory state of the dead process.

### Durable rows (`db_dump.json`)

For every task:

- `duplicate_effect_keys` is empty;
- there is one `task.attempt_completed` per task;
- the only `task.attempt_failed` is S3 attempt 1.

## Bugs found by the real runs

Each bug was fixed, and each fix has a regression test in `tests/test_employee_work.py` that fails without it.

1. **`s1_*`: Windows long paths and test caches.**
   - Staging the worktree failed with `git add failed (rc=128)`, because Windows path-length limits hit the deep
     test-cache paths.
   - The attempt was recovered three times and then failed with `ATTEMPTS_EXHAUSTED` (`s1_watch.txt`).
   - Fix:
     - the git runner sets `core.longPaths=true`;
     - generated cache directories are removed and never staged.
2. **`s3_*`: stale progress report on retry.**
   - A retry reuses the session's worktree.
   - Attempt 2 therefore read attempt 1's `.nexus/report.json` as its own report.
   - Fix: the progress file is deleted before a fresh turn starts.
3. **`s4_*`: leftover CLI instruction file committed.**
   - After the hard kill, the killed run's `.claude/CLAUDE.md` was never cleaned up.
   - When the session ended, the worktree snapshot committed it as `ddec51c` "Work left in worktree …"
     (`s4_git.txt`).
   - Fix: after verification, untracked files under the server-owned top-level directories (`.nexus`, `.claude`) are
     removed along with the test caches.
   - `s4r2_*` is the same scenario after the fix.

## Limitations

- S3's first failure was scripted through the objective. It was not an organic model mistake.
- The instruction-file leftover is now handled for every session, not only task attempts.
  - The first line of the file NEXUS writes records the writing process id.
  - One finalizer in `CLIAdapter._do_execute` removes the file on every exit.
  - A file whose writer died is recovered in three places: at the next write, at session termination and before the
    session-end snapshot (`tests/test_instruction_file_lifecycle.py`).
  - The real-CLI runs above predate this change.
- These runs are manual. Real CLI tests do not run in CI.
