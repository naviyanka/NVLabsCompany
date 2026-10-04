# System runtime

The system runtime (`python -m nexus.system_runtime`) is the one process that holds the
`nexus_system` credential, which bypasses row level security. The API and ordinary workers hold
only `nexus_app` and refuse to start if `SYSTEM_DATABASE_URL` reaches them. This page is the
operation catalogue, the threat model, the credential and process matrices, and the deploy,
upgrade, rotation and incident procedures. Role provisioning is in
[database-roles.md](database-roles.md).

## Why it exists

Some work has to find companies before it can act for them: which companies have an expired
budget reservation, a stranded task, an expired chat-turn lease, an organization snapshot due.
Row level security hides every company from a connection that has not chosen one, so that
discovery needs a role that bypasses it. Before this change the API, the worker and the
scheduler all held that role in production Compose, and in Helm the paths that needed it had
none. A bug or a prompt injection in a public process could then read every tenant.

The rule now is narrow: `nexus_system` finds company ids with bounded, fixed queries, and the
work runs through `tenant_session` on `nexus_app`, bound to one company. A company's failure
cannot reach another company's rows, and the privileged connection cannot change the schema or
any protection (it owns nothing and has DML only).

## Process matrix

| Process | Credentials it holds | Network | Does |
| --- | --- | --- | --- |
| API (`nexus.main`) | `DATABASE_URL` (`nexus_app`) | Public | Serves requests. Budget and policy state load per company, lazily, in `tenant_session`. No cross-tenant startup work |
| Worker / Temporal worker | `DATABASE_URL` | None | Claims jobs for a company id derived on the server, runs them in `tenant_session`. Missing company context fails closed |
| Orchestrator and chat/task-attempt workers | `DATABASE_URL` | None | Learn which companies have work from Redis hints; no tenant enumeration |
| Migration job | `MIGRATION_DATABASE_URL` (`nexus_migrator`) | None | Runs Alembic once, then exits |
| **System runtime** | `SYSTEM_DATABASE_URL` (`nexus_system`), `DATABASE_URL`, `REDIS_URL` | None: no Service, Ingress or port | Runs the catalogue below |

## Credential matrix

| Credential | API | Worker | Migration job | System runtime |
| --- | --- | --- | --- | --- |
| `DATABASE_URL` (`nexus_app`) | yes | yes | no | yes (tenant-bound work only) |
| `SYSTEM_DATABASE_URL` (`nexus_system`) | **refused at start** | **refused at start** | no | yes |
| `MIGRATION_DATABASE_URL` (`nexus_migrator`) | refused at start | refused at start | yes | refused at start |

## Threat model

| Threat | Control |
| --- | --- |
| A public process is compromised and reaches the BYPASSRLS credential | It is not in that process's environment. Compose: separate env file read by one service. Helm: separate Secret referenced by one Deployment. The API and workers exit with `SYSTEM_CREDENTIAL_IN_RUNTIME` if it appears |
| The system runtime is steered into arbitrary reads or writes | No port, no request handler, no prompt or tool input. Operations are fixed functions in `system_runtime/ops.py`; none takes a table, query or id from outside. `discovery_session` accepts only a catalogued operation name and only in a process that called `bootstrap()`. Discovery queries are bounded `SELECT DISTINCT company_id ... LIMIT n` |
| An agent or model invokes an operation | Nothing outside `nexus.system_runtime` imports the catalogue or the runner (checked by a test). Operations are scheduled only by the runtime's own tick |
| The privileged role is used to damage the schema | It owns nothing, has DML only, and cannot `CREATE`, `DROP`, `TRUNCATE`, `ALTER` or disable RLS (checked against a real PostgreSQL). The runtime refuses to start if the role owns objects, can create in `public`, or is a superuser |
| Identities swapped or collapsed in configuration | Role attributes are read from `pg_roles`, not parsed from URLs. `DATABASE_URL` that bypasses RLS, `SYSTEM_DATABASE_URL` that does not, the same role on both, and a URL equal to the other are all refused |
| One company's data error stops or leaks into another | Each company pass runs in its own `tenant_session`; a failing company is counted and skipped, and logged as an exception class name only |
| Secrets or tenant content in logs | Audit events carry a fixed set of numeric fields and short codes; anything else is dropped. Refusals print a stable code and a fixed message. Driver errors, which can contain a connection string, are never echoed |
| Two runtime replicas act at once | A Redis lease per operation (`system_runtime:<name>`). Operations are idempotent per company, so a lost lease costs duplicated work at worst |

Out of scope: a compromised system runtime pod. It can read every tenant through its own
credential. The controls above make that pod small, port-less and fixed-function; they do not
make its credential harmless. Treat its secret as the most sensitive one after the migrator's.

## Operation catalogue

Every operation has a stable name, an interval, a bounded batch (companies per run), a timeout,
an audit entry, and is idempotent and restart safe. "Discovery" is the only use of
`nexus_system`; everything else is `nexus_app` inside `tenant_session`.

| Operation | Interval | Batch | Timeout | Discovery (system role) | Tenant work (app role) |
| --- | --- | --- | --- | --- | --- |
| `budget_reservation_reap` | 60 s | 50 | 60 s | Companies with an expired `reserved` cost event | Release the company's expired holds and restore its policy's `reserved_cents` |
| `task_recovery` | 120 s | 20 | 120 s | Companies with `in_progress` or `needs_recovery` tasks, or `in_progress` goals | Reap stale subtasks, hand stranded goals back, re-enqueue recoverable tasks |
| `goal_discovery` | 60 s | 20 | 30 s | Companies with active goals that have an owner, or tasks in progress | None. Publishes company ids as work hints; the orchestrator reads goals in each company's session |
| `chat_turn_recovery` | 15 s | 50 | 60 s | Companies with expired chat-turn leases or stale queued turns; queued counts | `chat_turns.recover_company`. Publishes hints for companies with queued turns |
| `task_attempt_recovery` | 15 s | 50 | 60 s | Same, for task attempts | `task_attempts.recover_company`. Publishes hints |
| `watchdog_patrol` | 60 s | 20 | 60 s | Distinct company ids that have agents, 20 per run, resuming after the last one handled (a rotating cursor). Ids only | Read the company's agents and active runs, patrol, file escalations and close confirmed-dead runs, all in its tenant session |
| `org_snapshot_refresh` | 60 s | 20 | 120 s | Company ids with their snapshot state, to find those due; at most 20 are regenerated per run | Regenerate the snapshot per company |

Interval is the minimum time between starts. The runtime wakes every 5 seconds and runs what is
due; it has no polling loop of its own (it shares the scheduler loop through its `ticks` hook,
which keeps `scripts/arch_guard.py` rule R2 satisfied).

Not in the catalogue, deliberately: trigger firing. The `triggers` table is not RLS protected,
so the scheduler lists due triggers on the application role and fires each one inside its own
tenant session. It runs in the API/worker process and needs no system role.

### Leader lease

Each operation runs under a Redis lease named for it, fenced by a per-run token. The lease fails
closed:

- Two runtimes racing for one operation: exactly one acquires it. The other records
  `op_skipped_not_leader`.
- Redis unreachable or slow: the operation does not run. The runtime records
  `op_skipped_lease_unavailable` with the code `LEASE_STORE_UNAVAILABLE`, reports
  `lease_store: unavailable` in its status record, and retries on the next tick. There is no
  fallback that grants the lease without Redis.
- Release deletes the key only if it still holds this run's token (one atomic script), so a
  stale owner can never release a newer owner's lease. A clean shutdown or a timeout releases
  it; after a crash it expires after the operation timeout plus 30 s.
- Before a run is recorded as a success the runtime re-checks that it still holds the lease. If
  it expired and someone else took it, the run is recorded as `op_failed` with `LEASE_LOST`, and
  `last_success` does not move. The work already done is safe to repeat because every operation
  is idempotent per company.

### Watchdog tenant boundary

`watchdog_patrol` crosses tenants only to list company ids. For each id, `patrol_company` reads
that company's agents and runs, runs the stateless `Watchdog`, files escalations, and closes runs
that stalled past the critical threshold, all inside `tenant_session(company_id)`. No mutation
runs under `nexus_system`, and agent output is never kept after a company's pass (the watchdog
holds fingerprint hashes of the last output, not text).

- Escalation queues are per company (`watchdog_escalations:<company id>`). Queue names are
  looked up globally, so a shared name would have filed one company's items in another's queue.
- Escalations are de-duplicated against the database (a decision-queue item for the same
  agent or run already exists), so a restart does not file them again. `_escalated` is only a
  per-process fast path in front of that check, and the discovery cursor is process-local: a
  restart only changes which companies are visited first.
- Stall detection needs two patrols of a company (a baseline, then a flag), so a company is
  visited at least once per `ceil(companies / 20)` runs.
- A run silent for more than four hours is closed (`confirmed_dead`) and its agent parked in
  `needs_recovery`, once, in the company's session. This replaces the old startup PID check
  (below).
- Not yet fixed: the decision and its queue item are committed in two transactions, so a crash
  between them can leave an unqueued decision, and the retry then files a second one. A queue
  item is never duplicated. No external notification is sent from this path today (nothing
  consumes `needs_notification`), so this cannot produce a duplicate external action. If a
  consumer is added, make the filing a single transaction first.

### Heartbeat orphan recovery

The API no longer calls `reclaim_orphans()` at startup. It ran with an unscoped session, so on
PostgreSQL it saw no tenant's runs, and a PID is only meaningful in the process namespace that
started the run, which a separate system runtime container does not share. Recovery of a run
whose process died is now the watchdog's staleness rule above: bounded per company, tenant-bound
and idempotent. Nothing in production creates heartbeat runs yet, so there is no recovery gap
today. `PersistentHeartbeatService.reclaim_orphans` remains for a caller that shares the
namespace with its runs; no deployed process uses it.

### New companies

A company created while the API is running needs nothing from the system runtime. Governance is
loaded lazily, per company, on the first request: until that load succeeds the request gets
`503 GOVERNANCE_UNAVAILABLE` (fail closed). A failed load backs off for 30 s so a broken company
does not hammer the database, but the backoff only suppresses retries: once readiness is recorded
the company is served at once, with no restart. One company failing to load never blocks
another. The removed startup step only warmed this cache; it wrote nothing.

### Work hints

The runtime publishes company ids, and only ids, to short-lived Redis sets
(`nexus:hints:goals`, `nexus:hints:chat_turns`, `nexus:hints:task_attempts`). Ordinary workers
claim a few ids at a time and work them in `tenant_session`. Hints are an optimisation, never
the source of truth. Without Redis, or with the runtime down, workers still serve work that
arrives through their own in-process wake-ups and just learn of idle-company work late.

## Role validation

At start the runtime connects with each URL and reads the live role from `pg_roles`:

| Code | Meaning |
| --- | --- |
| `SYSTEM_CREDENTIAL_MISSING`, `APP_CREDENTIAL_MISSING` | A required variable is empty. There is no fallback to the other URL |
| `SYSTEM_URL_EQUALS_DATABASE_URL` | Both variables are the same string |
| `POSTGRES_REQUIRED` | A SQLite URL was given. The runtime is PostgreSQL only |
| `MIGRATION_CREDENTIAL_IN_RUNTIME` | The migrator URL is present in the environment |
| `ROLE_VALIDATION_UNAVAILABLE` | A role could not be checked (connection or query failed) |
| `APP_ROLE_BYPASSES_RLS` | `DATABASE_URL` is a BYPASSRLS or superuser role |
| `SYSTEM_ROLE_NOT_BYPASSRLS` | `SYSTEM_DATABASE_URL` cannot bypass RLS, so discovery would see nothing |
| `SYSTEM_ROLE_TOO_POWERFUL` | Superuser, `CREATEROLE` or `CREATEDB` |
| `SYSTEM_ROLE_CAN_CREATE` | Can create objects in `public` |
| `SYSTEM_ROLE_OWNS_OBJECTS` | Owns schema objects (the migrator, for example) |
| `APP_AND_SYSTEM_ROLE_IDENTICAL` | Both URLs resolve to one role |

A refusal exits with status 2, prints `CODE: fixed message` and records a `runtime_refused`
audit event. Compose and Kubernetes restart it, so a bad secret shows as a crash loop with the
code in the log, not as a silently idle process.

## Observability

- **Audit events** (structured log lines, `nexus.system_runtime.audit` logger):
  `runtime_started`, `runtime_stopped`, `runtime_refused`, `op_started`, `op_completed`,
  `op_failed`, `op_skipped_not_leader`, `op_skipped_lease_unavailable`. Fields: `operation`, `companies_seen`,
  `companies_processed`, `companies_failed`, `batches`, `duration_ms`, `code`, `ops_enabled`.
  No company id, name, prompt, task or memory text. A failing subscriber is counted and
  ignored. Audit events are log lines; forward them to your log store to retain them.
- **Metrics**: system runtime operation counters, durations and company counts, plus event
  counters for lock contention, role-validation failure, missing credential and audit
  subscriber failure (see `nexus/observability/metrics.py`).
- **Status** without the credential: `python -m nexus.system_runtime status` prints the record
  the runtime publishes to Redis (180 s expiry). `GET /health/ready` includes the same record as
  an informational `system_runtime` component. Neither connects with the system credential.
  A missing record reads `SYSTEM_RUNTIME_NOT_REPORTING`, no Redis reads
  `STATUS_STORE_UNAVAILABLE`, a failed role check reads `ROLE_VALIDATION_FAILED`. The API stays
  ready when the runtime is unavailable.
- **Liveness**: `python -m nexus.system_runtime healthcheck` exits 0 if the runtime ticked in
  the last 180 seconds. Compose and the Kubernetes startup and liveness probes run it.

## Fresh deploy

1. Provision the three roles ([database-roles.md](database-roles.md)).
2. **Compose**: copy `.env.system.example` to `.env.system` and fill in the `nexus_system` URL,
   the `nexus_app` URL and the Redis URL. Keep `SYSTEM_DATABASE_URL` out of `.env.production`.
   `docker compose -f docker-compose.prod.yml up -d` starts `migrate`, then `api`, `worker`
   and `system-runtime`.
   **Helm**: create the Secret with key `SYSTEM_DATABASE_URL` and set
   `systemRuntime.existingSecret`. Rendering fails without it.
3. Confirm: `docker compose -f docker-compose.prod.yml logs system-runtime` shows
   `runtime_started` and no `runtime_refused`; `python -m nexus.system_runtime status` (run in
   the system-runtime container or any pod with Redis access) shows `"available": true`.

Development: `docker-compose.yml` has a `system-runtime` service with its own URLs; the backend
and Temporal worker services have no system credential. Provision the dev roles with
`provision-roles.sql` as in production if you want the runtime to start; without it the
runtime refuses with a role code and the backend keeps working.

## Upgrade from the PR #67 legacy carve-out

PR #67 left `SYSTEM_DATABASE_URL` in `.env.production` for the API, worker and scheduler. The
new API and worker refuse to start with it, so remove it first.

1. Create `.env.system` from `.env.system.example` using the same `nexus_system` URL that was
   in `.env.production`, plus `DATABASE_URL` (`nexus_app`) and `REDIS_URL`.
2. Delete the `SYSTEM_DATABASE_URL` line from `.env.production`.
3. Deploy. The old `scheduler` service no longer exists: its tick (triggers) runs in the API
   process, and its cross-tenant work is the system runtime's. Remove the old service
   (`docker compose ... up -d --remove-orphans`).
4. Helm: add `systemRuntime.existingSecret`. The chart's former `scheduler` Deployment is
   replaced by `system-runtime`.
5. Verify with the checks below.

No migration and no database change is involved; roles are unchanged.

## Verify that no public pod holds `nexus_system`

Kubernetes:

```bash
# Only the system-runtime workload may reference the system Secret.
kubectl -n <ns> get pods -o json | jq -r '.items[] | select(
  [.spec.containers[].env[]?.valueFrom.secretKeyRef.name, .spec.containers[].envFrom[]?.secretRef.name]
  | index("<system secret name>")) | .metadata.name'
# expect only <fullname>-system-runtime-*

# No Service or Ingress selects it, and it declares no port.
kubectl -n <ns> get svc,ingress -o wide
kubectl -n <ns> get deploy <fullname>-system-runtime -o jsonpath='{.spec.template.spec.containers[0].ports}'

# The running API has no such variable.
kubectl -n <ns> exec deploy/<fullname>-api -- sh -c 'test -z "$SYSTEM_DATABASE_URL" && echo clean'
```

Compose:

```bash
docker compose -f docker-compose.prod.yml config --format json \
  | jq -r '.services | to_entries[] | select(.value.environment.SYSTEM_DATABASE_URL != null) | .key'
# expect only: system-runtime
docker compose -f docker-compose.prod.yml exec api sh -c 'test -z "$SYSTEM_DATABASE_URL" && echo clean'
docker compose -f docker-compose.prod.yml config --format json | jq '.services["system-runtime"].ports'
# expect null
```

PostgreSQL: which role each connection uses.

```sql
SELECT usename, application_name, count(*) FROM pg_stat_activity
 WHERE datname = 'nexus' GROUP BY 1, 2;
-- nexus_system connections come only from the system runtime's host or pod
```

## Rollback limits

- Rolling back to a build before this change brings back the old behaviour, including
  `SYSTEM_DATABASE_URL` in the API and worker, which the old code needs. Do that only as an
  emergency, and put the variable back in `.env.production` and the old Helm values knowingly;
  it undoes the isolation.
- Rolling forward again needs the variable removed from those environments first.
- Rolling back only the system runtime (stopping it) is safe: the API and workers keep serving.
  Budget holds are not reaped, stale leases are not recovered and hints are not published until
  it returns; a hold expires on its own for budget checks, and the next run reaps it.
- The audit events are log lines and cannot be recovered after rotation of the log store.

## Secret rotation

1. Store the new `nexus_system` password in the secret manager. Run `provision-roles.sql` with
   only `nexus.system_password` set (see [database-roles.md](database-roles.md)).
2. Update the Secret that holds `SYSTEM_DATABASE_URL` (`.env.system`, or the Helm Secret).
3. Restart only the system runtime. It has one replica and uses the `Recreate` strategy, so
   there is a short gap in maintenance, not in serving.
4. Confirm `runtime_started`, then revoke the old secret version.

Rotating `nexus_app` also affects the runtime, which uses the same URL: update the application
Secret and `.env.system` together.

## Incident runbook

| Signal | Meaning | Action |
| --- | --- | --- |
| `runtime_refused` with `SYSTEM_ROLE_*` or `APP_ROLE_BYPASSES_RLS` | Roles in the secrets do not match the contract | Fix the URL or re-run `provision-roles.sql`. Never relax a role to make it start |
| `SYSTEM_CREDENTIAL_IN_RUNTIME` in an API or worker | The BYPASSRLS credential reached a public environment | Remove it, rotate `nexus_system`, review the audit log for the window |
| `/health/ready` shows `SYSTEM_RUNTIME_NOT_REPORTING` | Runtime down, or Redis expiry | Check the pod or container, then its logs. Serving is unaffected |
| `op_failed` with `OP_TIMEOUT` | An operation exceeded its timeout | Look at database load and the batch size. The next run retries the same companies |
| `op_failed` with `OP_FAILED` | An operation raised | Logs name the exception class only. Reproduce against the company through a tenant session |
| `companies_failed` > 0 in `op_completed` | Some companies failed, others completed | The failed companies are picked up again next run |
| `op_skipped_not_leader` always | Another replica holds the lease | Expected with several replicas. If there is one, check for a stale lease; it expires after the operation timeout plus 30 s |
| `op_skipped_lease_unavailable` / `LEASE_STORE_UNAVAILABLE` | Redis is unreachable, so nothing runs (fail closed) | Restore Redis. Serving is unaffected; recovery and hints resume on the next tick |
| `op_failed` with `LEASE_LOST` | The run outlived its lease and another runtime took it | Raise the operation timeout or lower the batch if it recurs. Repeating the work is harmless |
| Suspected misuse of `nexus_system` | | Rotate it, run the verification SQL in [database-roles.md](database-roles.md), compare `pg_stat_activity` and the PostgreSQL log with the system runtime's host |

## Limitations

- One privileged process is a single point of maintenance. Its absence stops lease recovery and
  hint publication, not serving.
- Without Redis no operation runs (the lease fails closed) and hints are not published, so
  workers do not learn of work in idle companies. Production needs Redis.
- `cost_events` is not row level secured (its policy table, `budget_policies`, is). The reap
  operation therefore passes the company id so a company's pass releases only that company's
  holds. Securing `cost_events` needs a migration and is not part of this change.
- Audit events are structured logs, not a database table.
- `org_snapshot_refresh` discovery reads every company's id and four snapshot timestamps in one
  query, then caps regeneration at 20 per run (oldest attempt first). It holds ids and timestamps
  only, no content. Bounding the read needs an index on the state table and is a follow-up.
- The watchdog's decision and queue item are two transactions (see the watchdog section).
- With `externalSecrets.enabled`, the remote key for the application Secret must not contain
  `SYSTEM_DATABASE_URL`; the API and worker would refuse to start.
