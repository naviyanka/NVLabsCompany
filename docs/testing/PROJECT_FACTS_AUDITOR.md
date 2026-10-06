# Project Facts Auditor

`python scripts/project_facts.py` is a small, read-only auditor that measures objective
repository facts and reports stale or contradictory documentation claims. It performs
static repository inspection only: it never imports the NEXUS application, reads settings,
connects to a database, starts containers, calls Azure or GitHub, or makes any network
request. It shells out only to local read-only git plumbing (`rev-parse`, `status`,
`ls-files`, `tag`) — every invocation runs as `git --no-optional-locks …`, so a read-only
audit can never trigger an index refresh or take an optional lock, and no environment is
constructed, passed or logged — and reads tracked files from the checkout it is pointed
at, with `--repo PATH` (default: the current directory).

## Claim status model

Five statuses with non-overlapping meanings:

- `matches` - the claim and the measured fact have the same defined unit and scope, and
  the numbers agree.
- `stale` - the claim is comparable (same unit and scope) but disagrees with the measured
  fact. This is the only status that makes `--check-docs` exit nonzero.
- `not_statically_verifiable` - the claim describes runtime semantics (collected or passed
  tests, totals produced by collection hooks) that static scanning cannot adjudicate.
- `not_statically_comparable` - the claim's unit differs from every metric the auditor
  derives (for example generic "database tables" or "UI pages" claims), so no comparison
  is attempted rather than a wrong one being made.
- `subjective` - judgment language ("production-ready", "enterprise-grade"), reported for
  visibility but never objectively matched.

Where several patterns can fire on one line, the explicit unit-matched wording wins and
the generic wording is suppressed, so a line produces at most one claim per span. Rule
statuses are also authoritative over metrics: a rule explicitly marked incomparable never
compares, even when it carries a metric that could be resolved. Concretely for the API
surface, "N router modules" and "N route functions" compare with their corresponding
metrics, while generic "N routes" / "N endpoints" wording does not (its unit is not the
route-function count) and is always `not_statically_comparable`.

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
  imported. Plus `sqlmodel_table_class_count` (see below). No physical-table-name
  approximation is derived at all: `__tablename__` overrides, SQLModel default naming and
  migration-side DDL each contribute table sources the auditor deliberately does not try
  to unify.
- **API** (`src/nexus/api`): route modules, route functions, counts by HTTP method,
  `company_id` parameter forms (see below).
- **Frontend**: TypeScript/TSX file count and LOC, `page_component_file_count`
  (`dashboard/src/pages`, tests excluded), `mounted_route_count` and
  `unique_mounted_page_components` derived by statically scanning `dashboard/src/App.tsx`
  route registrations (see below), dashboard unit-test files, Playwright e2e files, and
  `MOCK_*` declarations or explicit "mock data" comments outside test files (relative
  paths only).
- **Tests**: Python test-file count, `static_test_function_count`, files carrying
  `pytest.mark.postgres` (decorator or `pytestmark` assignment), dashboard test files.
- **CI** (`.github/workflows`): workflow count, names, job names, GitHub action
  references with per-file/line provenance and an eight-way classification (see below),
  the backend pytest command and whether `-x` is present, and the PostgreSQL file split
  (backend `--ignore=` list vs `postgres-integration` file list) cross-checked against
  the statically marked files.
- **Release hygiene**: local git tag count and presence of LICENSE, SECURITY.md,
  CHANGELOG.md, CODEOWNERS, `.github/dependabot.yml`, a release workflow, and any SBOM
  configuration signal.
- **Documentation claims** in README.md, ARCHITECTURE.md, FEATURES.md and
  docs/FINAL-STATUS-SUMMARY.md, classified with the status model above.

## What is only a static approximation

Every count here is a static approximation of a runtime truth, and the report says so
next to the numbers it affects.

**Static test functions vs test totals.** `static_test_function_count` is the count of
Python functions named `test_*` in test files. Parametrization is not expanded: one
function can become many collected items (or none, if collection fails), fixtures and
hooks affect totals, frontend and e2e suites are separate, and "passed" is a runtime
result that static scanning can neither measure nor imply. The count is therefore never
labeled collected, executed, passed or baseline. Documentation claims are treated
accordingly: "N tests", "N+ tests" and "N tests passed/passing" are runtime claims and
are always `not_statically_verifiable`, even as floor claims. Only a claim that
explicitly counts "N static test functions" is compared with the static count.

**Table classes vs physical tables.** `sqlmodel_table_class_count` is the number of class
definitions carrying a literal `table=True` keyword - a source-level fact. It is not a
physical-table count: link tables, shared or overridden `__tablename__` values, inherited
mappers and migration-side DDL all break any direct mapping, so the auditor derives no
physical-table metric whatsoever. A generic claim such as "69 database tables" or
"69 physical tables" is `not_statically_comparable` - never compared against the class
count, no matter how close the numbers look. Only a claim explicitly worded as
"N SQLModel table=True classes" is compared with the class count.

**Page files vs mounted pages.** `page_component_file_count` counts `.ts/.tsx` files under
`dashboard/src/pages` excluding tests - a source-file count, not the number of mounted UI
pages. Two further metrics are derived by statically reading `dashboard/src/App.tsx`
(never executed, never imported): `mounted_route_count` (each `<Route>` registration,
including parameterized and layout routes) and `unique_mounted_page_components` (distinct
page modules reachable from an `element={...}`, including lazy imports, deduplicated when
several routes point at one component). An unmounted page file is excluded from the
mounted metrics; the scan is a regex-level approximation, so if no route registrations
are found the mounted metrics are reported as unknown. Claims are compared only when the
wording matches the metric: "N page component files", "N mounted routes",
"N mounted pages" (compared with the unique mounted page-component count) and
"N mounted page components" are comparable; a generic "N React UI pages" claim matches no
single metric and is `not_statically_comparable` by documented rule.

**Route and mock detection.** API route decorators are recognized syntactically
(`@<something>.get/post/...`), so unusual wiring is not counted. Mock detection greps for
`MOCK_*` identifiers and the phrase "mock data" outside test files; it can neither prove
a mock reaches production code paths nor find every simulation.

## Raw `company_id` findings

Routes that take a `company_id` parameter annotated with the tenant-scoped helpers
(`CurrentCompanyId`, `PathCompanyId` from `nexus.api.deps`) are counted as scoped. A
route whose `company_id` parameter is annotated with anything else (typically
`uuid.UUID`) is listed as a raw finding. A raw finding is an **audit signal, not proof of
a vulnerability**: the parameter may be scoped downstream (a tenant-scoped session, an
explicit filter assembled across statements), and the dedicated arch-guard rule R5
enforces query-level scoping separately. Treat the list as a starting point for review.

## GitHub action references

Every tracked `.github/workflows/*.yml` and `*.yaml` is scanned twice for `uses:` values -
once through the YAML parser and once with a narrow source-level line regex - and the
results are deduplicated by file, line and value, so a parser quirk cannot silently drop
an action line. Each reference is reported with its relative file and line number and
classified:

- full 40-hex commit SHA -> `sha_pinned` (the only action pin the auditor calls immutable;
  a Docker digest (`docker://image@sha256:...`, kind `docker_digest`) is the other
  immutable form);
- branch names such as `main` or `master` -> `branch` (mutable);
- major tags such as `v4` -> `major_tag` (mutable);
- semantic tags such as `v4.2.1` -> `semantic_tag` (still movable - never called
  immutable);
- local paths (`./...`) -> `local`;
- Docker references without a digest -> `docker` (mutable);
- abbreviated SHAs, dynamic expressions and anything unparseable -> `unknown`
  (requiring review; in particular a short SHA is never treated as an immutable pin).

Inputs, secrets, environment values and surrounding workflow content are never printed.

## Output modes

- Default: human-readable text on stdout.
- Console safety: stdout and stderr are written through the stream's own encoding. On a
  console whose codec cannot represent a character (for example a cp1252 Windows console
  meeting an emoji in a claim excerpt), the character is emitted as a deterministic
  backslash escape instead of crashing with a traceback; nothing is dropped and UTF-8
  consoles receive the full text. JSON and Markdown files are always written as UTF-8 and
  keep full Unicode regardless of the console.
- Exit codes: `0` clean run, `1` only when `--check-docs` found objectively stale claims,
  `2` for refusals and operational failures (unsafe output paths, unwritable targets,
  missing repository) — an operational failure never masquerades as a stale finding.
- `--json PATH`: full report as JSON with an explicit `schema_version` (currently 2).
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

`--check-docs` exits nonzero only when at least one claim is `stale` - a claim whose unit
and scope match a measured fact and whose number disagrees. Runtime test-total claims are
never stale from static evidence, generic table/page claims are never stale from class or
file counts, and subjective claims are reported without ever failing the check.

## Why the auditor does not rewrite documentation

A stale claim usually needs a human decision, not a mechanical substitution: the
documentation may be describing a milestone, a target, or a differently scoped metric
(ORM classes vs migrated tables; mounted routes vs page files). Auto-rewriting risks
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
