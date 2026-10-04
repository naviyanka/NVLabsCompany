# The pytest chunk runner

`scripts/run_pytest_chunks.py` runs selected pytest files as a series of
deterministic, sequential chunks -- one fresh pytest subprocess per chunk,
strictly one at a time. It exists for local verification on machines where a
single monolithic pytest process causes memory pressure. It is not a CI
orchestrator: `.github/workflows/test.yml` remains the authority for what CI
runs, and this tool never talks to Docker, PostgreSQL, Azure, or any other
service.

Every command below assumes the repository root.

## Default run (no PostgreSQL, no database)

PostgreSQL-marked files (`pytestmark = pytest.mark.postgres`, the same
derivation `tests/test_ci_postgres_split.py` uses for CI) are excluded by
default. The runner never starts a database.

```console
$ python scripts/run_pytest_chunks.py
Repository commit: 641e187...
Discovered 268 test files under tests/
Included 259 file(s); PostgreSQL-marked in the suite: 9
Excluded from this run: 9
  excluded: tests/test_postgres_integration.py
  ...
```

`--list` prints the discovery, exclusion, and chunk plan and runs nothing.

## Smaller chunks

```console
$ python scripts/run_pytest_chunks.py --chunk-size 10
```

`--chunk-size` is files per pytest process (default 25). Smaller chunks bound
peak memory lower at the cost of more interpreter startups.

## Filtering files

Filters are paths, directories, or globs under `tests/`; multiple filters
union together. A requested file is never silently omitted: a filter naming a
PostgreSQL-marked file fails in default mode (use a flag below), and any
nonexistent or non-collectable path is a hard error.

```console
$ python scripts/run_pytest_chunks.py tests/test_budget.py tests/test_bulkhead.py
$ python scripts/run_pytest_chunks.py tests/test_b*.py
```

Run only certain chunks of the computed partition (1-based):

```console
$ python scripts/run_pytest_chunks.py --chunks 2,5
```

## Passing pytest arguments

Everything after `--` is forwarded to pytest verbatim as literal arguments.
Arguments that would introduce parallel execution (`-n`, `--numprocesses`,
xdist options, `--forked`, `-p xdist`, `-o addopts=-n 4`, ...) are rejected.
`-x` is never added unless you pass it yourself.

```console
$ python scripts/run_pytest_chunks.py tests/test_budget.py -- -k reservation --tb=short
```

## Environment and repository addopts

pytest merges options from `PYTEST_ADDOPTS` and from repository configuration
(`pyproject.toml`, `pytest.ini`, `setup.cfg`, `tox.ini`) into every run, so a
parallel mode can arrive without ever appearing on the command line. The
runner validates both fail-closed before the first child starts:

- `PYTEST_ADDOPTS` is supported only when it is safe and sequential. Values
  containing `-n`/`-n4`/`-nauto`, `--numprocesses`, xdist plugin loading
  (`-p xdist`, `-p xdist.plugin`), or `-o/--override-ini addopts=...` that
  carries any of these refuse the run, as does malformed quoting.
- Parallel settings from repository configuration are refused the same way.
- Ordinary safe options from either source continue to apply unchanged; the
  configuration files are inspected, never modified, and never disabled.
- The runner never records the environment value: errors name the variable
  or file, never their contents, and no console summary, JSON file, or
  manifest contains them.

## Stop-on-failure

Continuing past a failed chunk is the default so one failure cannot hide later
results. To stop at the first failing chunk instead:

```console
$ python scripts/run_pytest_chunks.py --stop-on-failure
```

Chunks that never ran are listed in the summary; the final exit code preserves
pytest semantics (the highest executed chunk exit code).

## JSON summary

```console
$ python scripts/run_pytest_chunks.py --json summary.json
```

The file is created exclusively: an existing path is refused unless
`--overwrite-json` is passed, and overwriting touches exactly that one file.
The summary holds relative paths, counts, durations, exit codes, versions,
commit SHA, and dirty-path names -- never environment values, credentials,
tracebacks, captured output, or absolute paths.

## Manifest and resume

```console
$ python scripts/run_pytest_chunks.py --manifest chunks-manifest.json
```

The manifest is rewritten atomically after every chunk with statuses, exit
codes, and parsed counts. On Ctrl+C (or SIGTERM) the active child is
terminated and waited for, the interrupted chunk is recorded, and the script
exits `128+signal` (130 for Ctrl+C). Finish the interrupted run with:

```console
$ python scripts/run_pytest_chunks.py --manifest chunks-manifest.json --resume
```

Resume refuses to start unless the repository commit, discovered file list,
chunking options, and pytest arguments all still match the manifest. Passing
chunks are never repeated; previously failed chunks are not rerun unless you
pass `--rerun-failed` (interrupted and pending chunks always are).

## PostgreSQL-only mode

```console
$ python scripts/run_pytest_chunks.py --postgres-only
```

Runs exactly the nine PostgreSQL-marked files. These tests need an external
PostgreSQL database (`TEST_DATABASE_URL` or testcontainers) -- the runner
never starts one. `--include-postgres` instead mixes them into a normal run.

## Dirty-file reporting

The suite sometimes rewrites `data/okrs_database.json`. The runner records
tracked dirty paths before the run, re-checks after every chunk, and reports
paths tests modified, clearly separated from paths that were already dirty.
`--fail-on-new-dirty` turns new tracked modifications into a stop condition.

Files are never restored automatically. Discarding uncommitted work behind the
user's back is worse than naming what changed and letting them decide; the
runner also contains no `git reset`, `git clean`, or checkout/restore paths at
all (its only git usage is `rev-parse`, `status`, and `ls-files`).

## Why memory-pressure protections are not disabled

The tool's whole purpose is to coexist with a constrained machine: it keeps
one child at a time, streams pytest output line by line instead of buffering
it, and never spawns background pollers. Disabling OS or editor memory
protections to "make room" would defeat that and put the user's session at
risk.

## Why this does not replace CI

CI runs the full suite (including PostgreSQL integration under a real
service) on every push with pinned versions. The chunk runner is a local,
on-demand subset runner: it sees only what you select, on your Python, with
your environment. Green here means "worth pushing", not "mergeable".
