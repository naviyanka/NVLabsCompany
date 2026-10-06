# Selective multi-arch image builds

The workflow builds images for `linux/amd64` and `linux/arm64`. The loaded
`linux/amd64` backend and frontend images are scanned with Trivy; the arm64
images are built but are not currently loaded or scanned. It takes 12-14
minutes, so a pull request that cannot change an image skips that work. The
check itself is never skipped.

## How it works

`deploy-pipeline.yml` has three linked jobs:

| Job | Name | Role |
|---|---|---|
| `classify` | Classify Changes | Lists the changed paths and decides `docs_only=true` or `false` |
| `image-build` | Multi-Arch Image Build (internal) | Does the builds and scans; skipped only when `docs_only` is `true` |
| `build-and-scan` | **Multi-Arch Build & Vulnerability Scan** | The required check; always runs and decides pass or fail |

The gate (`python scripts/ci_changes.py gate`) passes in exactly two cases:

- the build ran and succeeded;
- the change was classified documentation-only and the build was skipped. The
  summary then reads `not applicable: documentation-only change`.

Everything else fails: a failed, cancelled or timed-out build, a failed
classification, a build that was skipped without a documentation-only verdict.
A skipped internal job on its own can never satisfy the gate.

### Why not `paths-ignore`?

A workflow that a path filter does not start creates no check run, and a
required check that is never created leaves the PR blocked on "Expected -
waiting for status". The workflow therefore always starts, and the gate always
reports. `tests/test_ci_selective_multiarch.py` asserts that the pull request
trigger has no `paths` or `paths-ignore`.

## What counts as documentation-only

A PR skips the build only if **every** changed path is one of:

- anything under `docs/` (Markdown, images and other assets);
- a Markdown file in the repository root, except `README.md` (the backend
  Dockerfile copies it into the build).

Everything else needs the full build, including paths nobody has thought of:

- `.github/workflows/**`, Dockerfiles, `scripts/**` (copied into the backend
  image, and it holds the classifier), `tests/**`;
- `src/**`, `dashboard/**` (the whole directory is the frontend build
  context), `alembic/**`, `deploy/**`, `docker/**`;
- `pyproject.toml`, lockfiles, package manifests, nginx configuration;
- any new directory, and any Markdown outside `docs/` and the root.

Renames and deletions count: `git diff --no-renames` reports both ends, so
moving a runtime file into `docs/` is a runtime change.

### Fail-safe rules

Any of these requires the full build:

- an unknown path, an empty change set, or a malformed path (absolute, `..`,
  backslash, control character);
- a missing or malformed base or head SHA, or any `git` error;
- an event that is not `pull_request`;
- a manual run, which has no base to compare with.

The classifier that decides comes from the **PR base**, not the PR head, so a
PR cannot loosen its own classification. Changing `scripts/ci_changes.py` is
itself a non-documentation change, and if the base has no classifier the
build runs.

## When the full build always runs

| Trigger | Why |
|---|---|
| Push to `main` | The images are built and pushed |
| Tag `v*.*.*` | Release |
| Weekly schedule (Monday 03:17 UTC) | A run of docs-only PRs must not hide base-image drift or a new vulnerability |
| `workflow_dispatch` | Manual |
| Any pull request that touches anything that is not documentation-only | Runtime, dependency, Docker, CI or unknown paths |

Images are pushed only on `push` events (`main` and tags). Scheduled and
manual runs build and scan but do not push.

### Force a full build by hand

```bash
gh workflow run deploy-pipeline.yml --ref <branch>
```

or Actions > "Enterprise Deployment & CI/CD Pipeline" > Run workflow. The
`force_full` input defaults to `true`; a manual run always performs the full
build, because it has no base to compare with. A pull request cannot be forced
from the UI: touch a path that is not documentation-only.

## Timeouts and failure handling

| Scope | Limit | Basis |
|---|---|---|
| `image-build` job | 60 min | Successful runs take 12-14 min |
| Each multi-arch build step | 30 min | |
| `classify`, gate | 5 min | |

A timeout cancels `image-build`, and the gate then reports a failure. There
are no automatic retries; re-run the workflow by hand once if the failure
looks transient. On failure the job prints the `buildx` builder list, free
disk space and the BuildKit container log, which name the platform and stage
that failed.

## The QEMU crash

The multi-arch build runs `npm ci` and `vite build` for arm64 under QEMU. Node
under emulation can die with `qemu: uncaught target signal 4 (Illegal
instruction)` and then hang the build. The static output (`/app/dist`) is
identical on every architecture and the nginx runtime stage is the only part
that is arm64-specific, so `dashboard/Dockerfile.prod` runs its builder stage
with `FROM --platform=$BUILDPLATFORM`. The runtime stage still builds for each
target platform, and only `/app/dist` is copied into it.

The backend builder (`apt-get`, `pip install`) still runs under QEMU for arm64
because it compiles for the target.

## Adding a new runtime directory

Nothing to do: an unknown directory is not on the allowlist, so a change to it
runs the full build. Only widen the allowlist for a directory that no image,
chart or script consumes, by editing `DOCS_PREFIXES` in
`scripts/ci_changes.py` and the parametrised cases in
`tests/test_ci_selective_multiarch.py`. That PR runs the full build itself.

If a Dockerfile starts copying something from `docs/` or a root Markdown
file, `test_nothing_an_image_copies_is_classified_documentation_only` fails
until the allowlist is narrowed.

## Vulnerability thresholds

Unchanged: Trivy scans the `linux/amd64` image of each service for `CRITICAL`
and `HIGH` findings with `exit-code: '0'` (report only). A scan step that
errors still fails the build job and therefore the gate. The Trivy Action is
pinned to the reviewed v0.36.0 commit. Tightening the vulnerability exit code,
completing repository-wide immutable action pinning, and scanning arm64 remain
separate follow-ups.
