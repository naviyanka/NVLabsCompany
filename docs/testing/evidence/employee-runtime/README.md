# Employee runtime durability: manual acceptance evidence

Recorded 2026-09-27 on branch `feat/employee-runtime-durability`. The test used real Claude Code (`claude` backend) and
Antigravity (`agy` backend) CLI employees. No mocks were involved.

## Rig

- One PostgreSQL 16 database. Migrations were applied with `alembic upgrade head` on a fresh database.
- Two backend processes ran against it: worker A on `:8000` and worker B on `:8001`. Each had its own chat-turn
  worker loop, a 30 s lease and a 1 s poll.
- The dashboard ran on `:3100` in `PROXY_API` mode and proxied to worker A.
- AUTH was disabled, so actors show as `service` or `user` without a user id.
- Worker ids have the form `host:pid:random`.
- Timestamps are UTC.
- `*-db.txt` files are read-only dumps of `chat_turns`, `chat_messages` and `audit_log`, limited to the scenario's
  time window. Message text is truncated to 70 characters.
- Driver files (`*-post.txt`, `*-reattach*.txt`, …) are the raw SSE frames seen by a Python client. `chunk` frames are
  reduced to their length.
- These files contain no credentials, environment variables or provider auth data.

## Results

| Scenario | Backend(s) | Result |
|---|---|---|
| A: browser refresh | claude | PASS |
| B: backend restart and lease recovery | agy | PASS |
| C: ordering across two workers | claude ×2, agy | PASS |
| D: SSE disconnect and reconnect | claude | PASS |
| E: explicit cancellation | claude (cancelled), agy | PASS |

### A: browser refresh (`A*.png`, `A-refresh-db.txt`)

1. A long Claude turn was started from the dashboard, and the browser page was reloaded while the turn was `running`.
2. After the reload, the page re-attached to the same turn id and showed it as pending.
3. The turn finished once:
   - one `chat_turns` row, `attempt_count` 1, `completed`
   - one agent message
   - audit rows: `turn_queued`, `turn_claimed`, `turn_started`, `message_sent`, `response_generated`, `turn_completed`
     (backend `claude`)
4. The backend label survived the refresh.

### B: backend restart and lease recovery (`B-restart-*`)

1. A long Agy turn was posted and claimed by worker `…:11488:…` (attempt 1).
2. At 18:58:12.70, both backend processes were hard-killed. This was a process kill, not a graceful shutdown.
3. `B-restart-db-after-kill.txt` shows the turn still `running`, held by the dead worker, with a lease in the future.
4. The backends were restarted:
   - At 18:58:50.36 a new worker wrote `chat.turn_recovered` with reason `lease_expired`.
   - The turn was re-claimed by `…:18464:…` (attempt 2) and completed at 18:59:42.
5. Outcome:
   - exactly one agent message
   - `response_message_id` is set
   - `lease_expires_at` was cleared on completion

Note: recovery re-runs the CLI prompt. Execution is at-least-once. The stored response is exactly-once.

### C: same-session ordering across workers (`C-ordering-*`)

1. Two Claude turns in the same session were posted 6 ms apart: turn 1 to worker A (`:8000`) and turn 2 to worker B
   (`:8001`).
2. An Agy turn in a different session followed on `:8000`.
3. Ordering results:
   - Claude turn 1 ran from 19:00:03.06 to 19:00:16.88.
   - Claude turn 2 started at 19:00:16.92, after turn 1 was terminal.
   - The Agy turn ran from 19:00:05.52 to 19:00:29.13, overlapping both Claude turns.
4. Each turn has one agent message. The watcher (`C-ordering-watch.txt`) shows turn 2 `queued` while turn 1 was
   `running`.

### D: SSE disconnect and reconnect (`D-sse-*`)

1. A Claude turn was posted to `:8000` with an `Idempotency-Key`. The response was HTTP 200.
2. The client disconnected right after the `running` frame.
3. The turn kept running. The client re-attached with `GET …/turns/{id}/events` on the other worker (`:8001`).
4. It then resumed on `:8000` with `Last-Event-ID: 1900`. The replay started after character offset 1900 and did not
   duplicate any text.
5. The final `done` frame carries `turn_id`, `session_id`, `execution_id`, `adapter_used` = `cli` and `backend_used` =
   `claude`.
6. The database holds one turn (attempt 1), one agent message and six audit rows.

### E: explicit cancellation (`E-cancel-*`)

1. A Claude turn was posted to `:8000` (worker A) and an Agy turn to `:8001` (worker B), both at 19:00:53.
2. The Claude turn was cancelled through worker B's endpoint at 19:00:58. This tested a cross-worker cancel through
   the database flag.
3. Claude turn outcome:
   - `cancelled`, error code `CANCELLED`, at 19:01:03.48
   - no agent message
   - audit rows `chat.turn_cancel_requested` then `chat.turn_cancelled`
4. The Agy turn was not affected. It completed at 19:01:22 with one agent message.

## Known warts visible in this evidence

- With AUTH disabled, `cancelled_by` records `service:None`.
- `chat.response_generated` has `resource_id` `"None"`. This is the pre-existing chat audit shape; the turn id is in
  `chat.turn_completed`.
- `model_used` is empty because the employees use the CLI's default model.
