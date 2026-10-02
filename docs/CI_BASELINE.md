# CI baseline

This page records what CI installs and runs, so that a failure can be
reproduced locally with the same versions.

## Supported versions

| Tool | Version | Where it is set |
|---|---|---|
| Python | 3.12 (CI resolves 3.12.x) | `actions/setup-python` in every workflow; `python:3.12-slim` in `Dockerfile` and `Dockerfile.prod` |
| Node | 22.23.1 | `node-version` in `test.yml` (frontend and api-parity) and `playwright.yml`; `node:22.23.1-alpine` in the dashboard Dockerfiles (the production builder stage runs on `$BUILDPLATFORM`) |
| Node range | `^22.22.2` | `engines` in `package.json` and `dashboard/package.json` |
| npm | 10.9.x (ships with Node 22.23.1) | The lockfiles were synced with npm 10.9.8 |
| SQLModel | `>=0.0.39,<0.0.45` | `pyproject.toml` |
| ruff | 0.16.9 | `pyproject.toml` dev extra and the Security & Static Analysis job |
| bandit | 1.9.4 | Security & Static Analysis job |
| Helm | 3.14.0 | `azure/setup-helm@v4.2.0` |
| kubeconform | v0.8.0, checked against its SHA-256 | `deploy-pipeline.yml` |
| PostgreSQL | 16 with pgvector | `pgvector/pgvector:pg16` in CI and `docker-compose.yml` |

### Why Node 22

jsdom 30, undici 8, vitest 5 and @testing-library/jest-dom 7 declare
`node: ^22.22.2 || ^24.15`. Node 20 installs them with EBADENGINE warnings,
and the tests then fail with `webidl.util.markAsUncloneable is not a function`.
Every frontend job, both dashboard images and the `engines` field use the same
line. Use `npm ci`, not `npm install`, so the lockfile is not rewritten.

## The SQLModel upper bound

Every `datetime` column stores naive UTC (`nexus.models._time.utcnow`), in
`TIMESTAMP WITHOUT TIME ZONE` columns.

SQLModel 0.0.45 maps `datetime` fields to a `UTCDateTime` type with
`timezone=True`, and that type rejects naive values with "Datetime values must
have timezone information". This was checked version by version: 0.0.42, 0.0.43
and 0.0.44 pass `tests/test_agent_sessions.py`, while 0.0.45 and 0.0.46 fail
it. 0.0.47 fails the whole backend job on main.

The bound is temporary. It stays until the columns are migrated deliberately
to timezone-aware UTC (issue #44).

`tests/test_sqlmodel_compat.py` checks three things:
- the installed SQLModel is inside the declared range, and the range has an
  upper bound;
- the datetime columns are still naive;
- a naive timestamp survives a write and a read.

Because pyproject.toml is the only place the range is declared, local
installs, CI (`pip install -e ".[dev]"`) and both backend images all install
the same range.

## Jobs and their commands

### `test.yml`

| Job | Commands |
|---|---|
| arch-guard | `python scripts/arch_guard.py`, `python scripts/check_generated_artifacts.py`, `python scripts/check_test_invocations.py` |
| backend | `pip install -e ".[dev,otel,speech]"` (the observability tests assert on real spans; the `speech` extra installs the Azure Speech SDK, and the Speech tests skip when it is absent), then `pytest tests/ --ignore=tests/test_postgres_integration.py --ignore=tests/test_memory_rls_postgres.py --ignore=tests/test_memory_ingest_postgres.py -x --tb=short -q` (every PostgreSQL-marked file is ignored here and run only by postgres-integration; `tests/test_ci_postgres_split.py` enforces it) with `DATABASE_URL=sqlite+aiosqlite:///./test.db` and `AUTH_ENABLED=false` |
| speech-smoke | Builds `docker/speech-smoke/Dockerfile` (`python:3.12-slim`, the repo installed with the optional `speech` extra using `--only-binary`), then runs `scripts/speech_container_smoke.py` in it with `docker run --network none`. It imports the Azure Speech SDK and `nexus.voice.azure_speech`, builds the SDK objects without connecting, and checks that Speech is disabled by default, that no token was requested, that no audio device or ALSA library was touched, and that every loaded native library resolves under `ldd`. It uses no Azure credentials and makes no Azure call. linux/amd64 only; see [azure-speech-provider.md](azure-speech-provider.md) |
| postgres-integration | `alembic upgrade head`, `alembic downgrade base`, `alembic upgrade head`, then `pytest tests/test_postgres_integration.py -v` against the pgvector service. The pytest step sets `DATABASE_URL` as well as `TEST_DATABASE_URL`, because `IdempotencyMiddleware` uses the app's own engine |
| compose-boot | `docker compose up -d postgres`, `docker compose run --rm migrate`, `docker compose up -d backend`, then poll `http://localhost:8000/health/live`; teardown with `docker compose down -v` |
| frontend (`dashboard/`) | `npm ci`, `npx tsc --noEmit`, `npm test`, `npm run build` |
| api-parity | `npm ci` in the root and in `dashboard/`, then `pip install -e ".[dev]"`. Run `npx playwright test e2e/api-parity.spec.ts --project=chromium` twice: first against the mock server (`npx tsx server.ts`), then against uvicorn through the proxy (`PROXY_API=true`). The proxy readiness probe is `/api/v1/auth/setup-required`, which is public; `/api/v1/companies` answers 401 without a principal even with `AUTH_ENABLED=false` |

### `playwright.yml`

`npm ci`, `npx playwright install --with-deps`, `npx playwright test`.

### `deploy-pipeline.yml`

| Job | Commands |
|---|---|
| Security & Static Analysis | `python scripts/ruff_ratchet.py`, `bandit -r src/ -ll -q`, hadolint on `Dockerfile.prod` and `dashboard/Dockerfile.prod` (failure threshold `error`) |
| Helm & Kubeconform | `helm lint deploy/helm/nexus --set migration.existingSecret=nexus-migration-db`, `helm template nexus deploy/helm/nexus --set migration.existingSecret=nexus-migration-db > output/manifests.yaml`, then `kubeconform -strict -summary -kubernetes-version 1.31.0` against the default schemas plus the datreeio CRDs catalogue |
| Classify Changes | `python scripts/ci_changes.py classify` decides whether a PR is documentation-only |
| Multi-Arch Image Build (internal) | Builds `Dockerfile.prod` and `dashboard/Dockerfile.prod`, scans them with Trivy, and pushes them on `push` events only (60 min timeout); skipped for documentation-only PRs |
| Multi-Arch Build & Vulnerability Scan | The required check. Always runs; passes when the build passed, or when a documentation-only change correctly skipped it. See [CI_SELECTIVE_BUILDS.md](CI_SELECTIVE_BUILDS.md) |

## Running the checks locally

Run everything from the repository root unless a directory is given.

**Backend**

```bash
python -m venv .venv && .venv/bin/pip install -e ".[dev,otel]"
DATABASE_URL=sqlite+aiosqlite:///./test.db AUTH_ENABLED=false \
  .venv/bin/pytest tests/ --ignore=tests/test_postgres_integration.py -q
```

CI runs on Linux, so a green run on Windows does not prove the Linux job.
Path handling differs: `C:\x` is absolute on Windows but a relative name on
POSIX. Run the same command in a `python:3.12` container before relying on a
Windows result.

**PostgreSQL integration.** Start a disposable pgvector database. The password
below is the CI dummy, not a real secret.

```bash
docker run -d --name ci-pg -p 5432:5432 -e POSTGRES_PASSWORD=postgrespassword \
  -e POSTGRES_DB=test pgvector/pgvector:pg16
export DATABASE_URL=postgresql+asyncpg://postgres:postgrespassword@localhost:5432/test
alembic upgrade head && alembic downgrade base && alembic upgrade head
TEST_DATABASE_URL=postgresql://postgres:postgrespassword@localhost:5432/test \
  AUTH_ENABLED=false pytest tests/test_postgres_integration.py -v
```

Use a fresh database for each run: on main,
`test_postgres_audit_log_immutability` writes a fixed sequence number, so a
second run on the same database collides.

**Production images.** Build them from a clean checkout, as CI does. With no
`.dockerignore`, a local build context also carries `.venv` and
`node_modules`.

```bash
docker build -f Dockerfile.prod -t nexus-api-scan .
docker build -f dashboard/Dockerfile.prod -t nexus-frontend-scan dashboard
```

**Frontend**, with Node 22.23.1:

```bash
cd dashboard && npm ci && npx tsc --noEmit && npx vitest run && npm run lint && npm run build
```

**API parity.** Port 3000 must be free, or run this in a container.

```bash
npm ci && (cd dashboard && npm ci)
(cd dashboard && npx tsx server.ts &) && npx playwright test e2e/api-parity.spec.ts --project=chromium
```

Stop the mock server, then start the backend and the proxy:

```bash
DATABASE_URL=sqlite+aiosqlite:///./parity.db AUTH_ENABLED=false uvicorn nexus.main:app --port 8000 &
(cd dashboard && PROXY_API=true NEXUS_API_URL=http://localhost:8000 npx tsx server.ts &)
npx playwright test e2e/api-parity.spec.ts --project=chromium
```

**Compose boot.** A separate project name keeps this apart from any stack that
is already running.

```bash
docker compose -p nexus-ci up -d postgres
docker compose -p nexus-ci run --rm migrate
docker compose -p nexus-ci up -d backend
curl -sf http://localhost:8000/health/live
docker compose -p nexus-ci down -v
```

**Helm and kubeconform.** No local Helm install is needed:

```bash
docker run --rm -v "$PWD:/w" -w /w alpine/helm:3.14.0 lint deploy/helm/nexus
docker run --rm -v "$PWD:/w" -w /w alpine/helm:3.14.0 template nexus deploy/helm/nexus > manifests.yaml
```

Then download kubeconform v0.8.0, verify it against the SHA-256 pinned in
`deploy-pipeline.yml`, and run the same `kubeconform` command as CI.

**Static analysis**

```bash
python scripts/ruff_ratchet.py
bandit -r src/ -ll -q
docker run --rm -i ghcr.io/hadolint/hadolint:v2.12.0-debian hadolint --failure-threshold error - < Dockerfile.prod
```

## Ruff ratchet

`ruff check .` reported 2900 violations in 439 files when this baseline was
set, and the lint job had never passed. `scripts/ruff_baseline.json` records
the per-file, per-rule counts at that point. `scripts/ruff_ratchet.py` fails
if:
- any count rises;
- a file that is not in the baseline has any violation.

The rule selection in `pyproject.toml` is unchanged. After fixing violations,
run `python scripts/ruff_ratchet.py --baseline` to lock in the lower counts.
The baseline now holds 2901 violations: two E501 lines arrived with the
migration and test fixes cherry-picked from #42 and are kept byte-identical
so that branch rebases cleanly, and the same fixes removed one other.
The counts depend on the ruff version, so upgrading ruff means regenerating
the baseline in the same change. Paying the debt down is tracked in #45.

The five medium-severity bandit findings on main were false positives. Each
one is suppressed on its own line, with `# nosec <test id>` and a comment
giving the reason. None of them is suppressed by a global skip.

## Follow-ups

- #44: migrate timestamps to timezone-aware UTC, then lift the SQLModel bound.
- #45: pay down the ruff baseline and return CI to `ruff check .`.
- `aquasecurity/trivy-action@master` is unpinned. v0.36.0 is commit
  `ed142fd0673e97e23eac54620cfb913e5ce36c25`.
- Backend startup logs asyncpg "attached to a different loop" errors while the
  pool closes connections. Boot and health are unaffected.
- On main, `IdempotencyMiddleware` opens plain sessions with no tenant set,
  while `idempotency_records` has FORCE ROW LEVEL SECURITY. The PostgreSQL
  test passes only because CI connects as a superuser. #43 (`659d323`) moves
  the middleware to `tenant_session` and runs the test as the application role.
- There is no `.dockerignore`, so the dashboard `COPY . .` also copies any
  host `node_modules`.
