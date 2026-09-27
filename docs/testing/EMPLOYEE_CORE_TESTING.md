# Employee core testing

This page covers how to test the employee path: hiring a CLI employee, the
chat adapter it resolves to, the `CLIAdapter` subprocess call, and several
employee chats running at the same time. It has five profiles, from a quick
edit loop to real installed CLIs.

All backend commands run from the repository root. They use a throwaway SQLite
file, so they never touch a developer database:

```bash
export DATABASE_URL=sqlite+aiosqlite:///./test.db AUTH_ENABLED=false
```

(PowerShell: `$env:DATABASE_URL="sqlite+aiosqlite:///./test.db"; $env:AUTH_ENABLED="false"`)

`test.db` is git-ignored. When two runs overlap, give each its own file.

## Markers

Registered in `pyproject.toml`:

| Marker | Meaning |
|--------|---------|
| `core_employee` | Fast employee chat, session, adapter and CLI checks. Everything in profile 1. |
| `integration` | Exercises a real external service or several subsystems together. |
| `slow` | Takes several seconds. Deselect with `-m "not slow"`. |
| `postgres` | Needs PostgreSQL (`TEST_DATABASE_URL` or testcontainers). |
| `real_cli` | Spawns an installed employee CLI. Skipped unless `NEXUS_REAL_CLI=1` (see `tests/conftest.py`). |

`real_cli` tests are never run by CI. The hook in `tests/conftest.py` adds a skip
marker to them unless the variable is set, so a normal `pytest` invocation
cannot reach a paid provider account.

## Profile 1: fast core (run on every edit)

```bash
python -m pytest tests/test_cli_employee_foundation.py tests/test_chat_adapter_resolution.py \
  tests/test_cli_adapter.py tests/test_cli_adapter_interactive.py \
  tests/test_concurrent_employee_chat.py -q
```

Or by marker: `python -m pytest -m core_employee -q`. It selects the same five
files.

| File | What it proves |
|------|----------------|
| `test_cli_employee_foundation.py` | Catalog (unique IDs, aliases, command candidates, no bypass flags), provider endpoints, probe endpoint, hiring validation (canonical config, alias normalization, unavailable backend, executable paths, secrets), version probing, Windows `.cmd` detection, prompt transports, env allowlist. |
| `test_chat_adapter_resolution.py` | `adapter_type="cli"` + `backend` and every legacy ID resolve to `CLIAdapter` with the right backend. Unknown IDs fail closed and never fall back to Anthropic. Hermes CLI and Hermes API stay distinct, as do Claude Code and the Anthropic API. |
| `test_cli_adapter.py` | Golden argv table for each executable backend, session lifecycle, timeouts, non-zero exit, bounded output, execution metadata. |
| `test_cli_adapter_interactive.py` | Interactive mode, approval gating, forbidden extra args. |
| `test_concurrent_employee_chat.py` | Two employees chatting at once, per-session ordering held in the database (another worker cannot claim a later turn), bulkhead saturation as `202` with a queued turn that runs when capacity frees, isolated cancellation, user message persisted before the CLI runs, `execution_id` in responses and audit rows. |

Runtime on the development machine (Windows 11, Python 3.12): see
"Measured runtimes" below.

## Profile 2: frontend chat

```bash
cd dashboard
npx vitest run src/components/chat src/components/agents src/pages/__tests__/Workspace.test.tsx
```

This covers `ConcurrentChat.test.tsx` (the 15 concurrent-chat scenarios: tab
strip, per-chat status, Retry, unread badges, per-request Cancel, closing the
dock without aborting, agent list never disabled), `HireAgentModal.test.tsx`,
and the Workspace page. The tests use deterministic deferred promises and no
timers or sleeps.

The whole dashboard suite is `npm test`. CI also runs `npx tsc --noEmit` and
`npx vite build`.

## Profile 3: full backend regression

This is the same command as the `backend` job in `.github/workflows/test.yml`,
without `-x`, so every failure is listed:

```bash
python -m pytest tests/ --ignore=tests/test_postgres_integration.py -q
```

Compare the `FAILED` node IDs against
[KNOWN_BASELINE_FAILURES.md](KNOWN_BASELINE_FAILURES.md). Any ID that is not
on that list is a regression.

## Profile 4: PostgreSQL

```bash
# Against an existing database (what CI does):
TEST_DATABASE_URL=postgresql://postgres:postgrespassword@localhost:5432/test \
  python -m pytest -m postgres -v

# Or let testcontainers start pgvector/pgvector:pg16 (needs Docker):
python -m pytest -m postgres -v
```

Without `TEST_DATABASE_URL` and without Docker, the module skips. This profile
covers the full Alembic chain, the audit-log immutability trigger and
row-level security per tenant.

## Profile 5: real CLI smoke (optional, manual)

These call the installed CLIs, so they can use the provider accounts those
CLIs are signed in to. Run them by hand, never in CI.

```bash
python scripts/cli_employee_smoke.py --backend claude
python scripts/cli_employee_smoke.py --backend agy
python scripts/cli_employee_concurrency_smoke.py --backends claude,agy
```

Each line of output starts with `[REAL]`, `[MOCK]` or `[SKIPPED]`:

- A backend whose binary is not on `PATH` is `[SKIPPED]` and the exit code is 0.
- A catalog-only backend (for example `kimi`, `freebuff`) is `[SKIPPED]`.
- `--mock` swaps the subprocess for a canned reply. It checks the adapter
  plumbing with no CLI and no provider call.

The single-backend script sends `Return JSON only: {"employee":"<id>","result":55}`
through the real `CLIAdapter` path. It passes when the CLI exits 0, the execution
metadata names the same backend, and the reply echoes the backend ID. The
concurrency script runs the backends with `asyncio.gather` and passes only if
each process's own run window (end time minus its measured duration) overlaps
the others. A run that queued behind another cannot pass.

The scripts print only the executable file name and version, never full paths,
environment variables or credentials. The adapter's environment allowlist
decides what the CLI sees.

To run `real_cli`-marked pytest tests as well: `NEXUS_REAL_CLI=1 python -m pytest -m real_cli`.

## Manual acceptance: two real employees at once

Performed on 2026-09-27 with Claude Code 2.1.283 and Agy 1.2.12, through the
dashboard at `http://localhost:5173` and the backend on `:8000`.

1. Hire one Claude Code employee and one Agy employee.
2. Open both chats. Send a prompt to Agy, then immediately to Claude.
3. Switch tabs while both are running.

Observed:

- Round 1: Claude ran 14:43:53.9 to 14:44:08.5 and Agy ran 14:44:07.0 to 14:44:34.9.
- Round 2: Agy ran 14:45:13.5 to 14:45:39.8 entirely inside Claude's
  14:45:06.8 to 14:46:21.2 turn. Tabs were switched every second for 57 s.
- Unread badges appeared on the background tab when its reply arrived.
- Neither transcript contained the other employee's messages.
- After a browser refresh, both tabs and their histories were restored.
- `chat_messages` rows carry distinct agent IDs, session IDs and
  `execution_id`s, with `backend` `claude` and `agy` respectively.

Screenshots:

| | |
|---|---|
| Agy still waiting, Claude tab unread | ![](evidence/01-agy-waiting-claude-unread.png) |
| Claude replied, Agy tab unread | ![](evidence/02-claude-reply-agy-unread.png) |
| Round 2 Agy transcript | ![](evidence/03-round2-agy-transcript.png) |
| After refresh | ![](evidence/04-after-refresh.png) |

The smoke scripts reproduce the same check without the browser:

```
[REAL] PASS claude (7.8s, exit=0, exe=claude.EXE, version=2.1.283 (Claude Code)): ...
[REAL] PASS agy (27.6s, exit=0, exe=agy.EXE, version=1.2.12): ...
[REAL] overlap PASS: 7.6s shared
```

## Measured runtimes

Measured on 2026-09-27 on the development machine (Windows 11, Python 3.14, SQLite):

| Profile | Result | Time |
|---------|--------|------|
| 1. Fast core (3 consecutive runs) | 143 passed each time | 12.0 s, 11.8 s, 13.0 s (pytest); 13.2 s, 12.9 s, 14.0 s wall |
| 1. `-m core_employee` | 143 passed, 4,931 deselected | 13.0 s |
| 2. Frontend chat (vitest) | 3 files, 28 tests passed | 4.5 s |
| 3. Full backend | see [KNOWN_BASELINE_FAILURES.md](KNOWN_BASELINE_FAILURES.md) | about 13 min |

Most of the full-suite time is fixture setup rather than test bodies. Test
calls add up to about 160 s of the 13 minutes.
