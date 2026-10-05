# Project Facts Auditor

`python scripts/project_facts.py` is a small, read-only auditor that measures objective
repository facts and reports stale or contradictory documentation claims. It performs
static repository inspection only: it never imports the NEXUS application, reads settings,
connects to a database, starts containers, calls Azure or GitHub, or makes any network
request. It shells out only to local read-only git plumbing (`rev-parse`, `status`,
`ls-files`, `tag`) and reads tracked files from the checkout it is pointed at, with
`--repo PATH` (default: the current directory).

## What is measured

- **Git state**: HEAD SHA, branch, a dirty/clean boolean, and the names of tracked dirty
  paths. The dirty boolean includes untracked files; the path list deliberately does not.
  File contents are never reported.
- **Backend** (`src/nexus`): Python file count, LOC, top-level package count, broad
  exception handlers (`except Exception`, `except BaseException`, bare `except`),
  standalone `pass` statements (a `pass` that is the only statement of its block).
- **Database**: Alembic migration count, revision IDs, heads, branch points, revision
  cycles and dangling `down_revision` references - all derived statically from
  `revision` / `down_revision` assignments parsed with `ast`; migration modules are never
  imported. Plus the count of SQLModel classes declared with `table=True`.
- **API** (`src/nexus/api`): route modules, route functions, counts by HTTP method,
  `company_id` parameter forms (see below).
- **Frontend**: TypeScript/TSX file count and LOC, dashboard page components
  (`dashboard/src/pages`), dashboard unit-test files, Playwright e2e files, and
  `MOCK_*` declarations or explicit "mock data" comments outside test files (relative
  paths only).
- **Tests**: Python test-file count, statically detected test functions, files carrying
  `pytest.mark.postgres` (decorator or `pytestmark` assignment), dashboard test files.
- **CI** (`.github/workflows`): workflow count, names, job names, action-reference
  classification, the backend pytest command and whether `-x` is present, and the
  PostgreSQL file split (backend `--ignore=` list vs `postgres-integration` file list)
  cross-checked against the statically marked files.
- **Release hygiene**: local git tag count and presence of LICENSE, SECURITY.md,
  CHANGELOG.md, CODEOWNERS, `.github/dependabot.yml`, a release workflow, and any SBOM
  configuration signal.
- **Documentation claims** in README.md, ARCHITECTURE.md, FEATURES.md and
  docs/FINAL-STATUS-SUMMARY.md: numeric claims about tables, routers, routes/endpoints,
  pages, migrations and tests, plus categorical readiness claims.

## What is only a static approximation

Every count here is a static approximation of a runtime truth, and the report says so
next to the numbers it affects.

**Table classes vs physical tables.** The auditor counts Python class definitions
carrying a literal `table=True` keyword. That is a source-level fact. It is not a
physical-table count: Alembic migrations can create or drop tables the models no longer
declare, a model can map to a table that fails to migrate, and SQL-side objects (views,
tables created by raw SQL in migrations) never appear as classes at all. The two numbers
answer different questions - "what does the ORM declare today" versus "what exists in a
migrated database" - and only a real migration run against a real database answers the
second.

**Static test functions vs pytest totals.** A test function is counted once, even when
`@pytest.mark.parametrize` would expand it into many collected items at runtime. The
static count is therefore a floor on collected items and has no relation to pass/fail
outcomes; it must never be quoted as "N tests passed". Conversely, a documentation claim
of "N tests" is compared against this floor: a claim below the static count is impossible
and stale, a claim equal to it can match, and a claim above it may be explained by
parametrization and is reported as not statically verifiable rather than as a match.

**Route and mock detection.** Route decorators are recognized syntactically
(`@<something>.get/post/...`), so unusual wiring (routers built dynamically, routes
added outside `src/nexus/api`) is not counted. Mock detection greps for `MOCK_*`
identifiers and the phrase "mock data" outside test files; it can neither prove a mock
reaches production code paths nor find every simulation.

## Raw `company_id` findings

Routes that take a `company_id` parameter annotated with the tenant-scoped helpers
(`CurrentCompanyId`, `PathCompanyId` from `nexus.api.deps`) are counted as scoped. A
route whose `company_id` parameter is annotated with anything else (typically
`uuid.UUID`) is listed as a raw finding. A raw finding is an **audit signal, not proof of
a vulnerability**: the parameter may be scoped downstream (a tenant-scoped session, an
explicit filter assembled across statements), and the dedicated arch-guard rule R5
enforces query-level scoping separately. Treat the list as a starting point for review.

## Output modes

- Default: human-readable text on stdout.
- `--json PATH`: full report as JSON with an explicit `schema_version` (currently 1).
  This is the canonical, machine-readable form; all paths are repository-relative and all
  lists are sorted, so identical repository states produce byte-identical output.
- `--markdown PATH`: the same report as stable Markdown.
- Output files are created exclusively (`O_EXCL` semantics). Replacing an existing file
  requires an explicit `--overwrite`, which rewrites only the exact requested path; no
  output file is ever deleted first. Paths that escape the current working directory or
  pass through a symlink are refused.
- Scanning is bounded: tracked files only (untracked files and `.env*` are never read),
  oversized files are skipped, binaries are skipped, symlinks resolving outside the
  repository are refused, and no environment values, absolute paths, hostnames or
  timestamps appear in any output.

## `--check-docs`

`--check-docs` exits nonzero only when at least one claim is **stale** - an objectively
comparable numeric claim that disagrees with the measured fact. Claims classified as
`subjective` (for example "production-ready", "enterprise-grade") and
`not_statically_verifiable` are reported but never alone make the check fail, because
neither can be adjudicated by static measurement. Unverifiable claims are never reported
as matches.

## Why the auditor does not rewrite documentation

A stale claim usually needs a human decision, not a mechanical substitution: the
documentation may be describing a milestone, a target, or a differently scoped metric
(ORM classes vs migrated tables; collected items vs test functions). Auto-rewriting risks
silently replacing one wrong number with another wrong-but-current number and destroys
the audit trail of what was claimed. The auditor's job is to surface the contradiction
with evidence (file, line, quoted claim, measured value); fixing the prose stays with the
author.

## Why this does not prove production readiness

Everything here is a count, and counts are not readiness. Zero raw `company_id` findings
does not mean tenant isolation holds; one Alembic head does not mean migrations succeed
against production data; 5,000 static test functions says nothing about coverage, pass
rates, or whether the tested behavior is the behavior production needs. Readiness is a
judgment built on runtime evidence - test runs, migrations, observability, incident
history - none of which a static auditor can see.
