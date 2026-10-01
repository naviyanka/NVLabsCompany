"""Selective multi-arch image builds: the classifier, the required gate, and the workflow.

A documentation-only PR may skip the image build, but only on positive evidence, and the
required check "Multi-Arch Build & Vulnerability Scan" must exist on every run. See
docs/CI_SELECTIVE_BUILDS.md.
"""

import importlib.util
import re
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent
GATE_NAME = "Multi-Arch Build & Vulnerability Scan"
SHA_A = "a" * 40
SHA_B = "b" * 40

_spec = importlib.util.spec_from_file_location("ci_changes", ROOT / "scripts" / "ci_changes.py")
ci = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ci)


def _classify(paths, event="pull_request", base=SHA_A, head=SHA_B, force=""):
    return ci.classify(event, base, head, force, diff=lambda b, h: paths)[0]


# --- classifier ------------------------------------------------------------------------


@pytest.mark.parametrize(
    "paths",
    [
        ["docs/CI_BASELINE.md"],
        ["docs/adr/0006-azure.md", "docs/architecture/matrix.md", "ARCHITECTURE.md"],
        ["ARCHITECTURE.md"],
        ["CONTRIBUTING.md", "FEATURES.md"],
        ["docs/architecture/diagram.png", "docs/img/flow.svg"],
        ["docs/deleted-page.md"],
    ],
)
def test_docs_only_change_skips_the_image_build(paths):
    assert _classify(paths) is True


@pytest.mark.parametrize(
    "paths",
    [
        ["src/nexus/main.py"],
        ["dashboard/src/App.tsx"],
        ["dashboard/Dockerfile.prod"],
        ["Dockerfile.prod"],
        [".github/workflows/deploy-pipeline.yml"],
        [".github/workflows/test.yml"],
        ["package-lock.json"],
        ["dashboard/package-lock.json"],
        ["pyproject.toml"],
        ["alembic/versions/0042_add_table.py"],
        ["alembic.ini"],
        ["dashboard/nginx.conf"],
        ["deploy/helm/nexus/values.yaml"],
        ["scripts/ci_changes.py"],
        ["tests/test_ci_selective_multiarch.py"],
        ["voice/service.py"],
        ["services/teams/app.py"],
        ["brand-new-dir/file.txt"],
        ["README.md"],  # COPY'd by Dockerfile.prod
        ["readme.md"],
        ["docs/ARCHITECTURE.md", "src/nexus/main.py"],
        ["docs/page.md", "Dockerfile.prod"],
        ["notes.txt"],
        ["docs"],  # a file named docs, not the directory
        ["docsx/page.md"],
        ["dashboard/README.md"],  # inside the dashboard build context
        [".claude/skills/x/SKILL.md"],
    ],
)
def test_anything_else_requires_the_full_build(paths):
    assert _classify(paths) is False


@pytest.mark.parametrize(
    "paths",
    [
        [],
        [""],
        ["docs/a.md", ""],
        ["/docs/a.md"],
        ["docs/../src/nexus/main.py"],
        ["docs/./a.md"],
        ["docs\\a.md"],
        ["docs//a.md"],
        ["docs/a\nsrc/b.py"],
    ],
)
def test_empty_or_malformed_change_set_requires_the_full_build(paths):
    assert _classify(paths) is False


@pytest.mark.parametrize(
    "event,base,head",
    [
        ("pull_request", "", SHA_B),
        ("pull_request", SHA_A, ""),
        ("pull_request", None, None),
        ("pull_request", "not-a-sha", SHA_B),
        ("pull_request", SHA_A + "; rm -rf /", SHA_B),
    ],
)
def test_missing_or_malformed_shas_require_the_full_build(event, base, head):
    assert _classify(["docs/a.md"], event=event, base=base, head=head) is False


def test_detection_error_requires_the_full_build():
    def boom(base, head):
        raise subprocess.CalledProcessError(128, "git")

    docs_only, reason = ci.classify("pull_request", SHA_A, SHA_B, diff=boom)
    assert docs_only is False and "error" in reason


def test_undecodable_diff_output_requires_the_full_build(monkeypatch):
    class Done:
        stdout = b"docs/\xff\xfe.md\0"

    monkeypatch.setattr(ci.subprocess, "run", lambda *a, **k: Done())
    assert ci.classify("pull_request", SHA_A, SHA_B)[0] is False


@pytest.mark.parametrize("value", ["true", "True", " TRUE "])
def test_manual_force_requires_the_full_build(value):
    assert _classify(["docs/a.md"], force=value) is False


@pytest.mark.parametrize("event", ["schedule", "push", "workflow_dispatch", "release", "", None])
def test_every_non_pull_request_event_requires_the_full_build(event):
    assert _classify(["docs/a.md"], event=event) is False


def _git(repo, *args):
    subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@example.com", *args],
        cwd=repo,
        check=True,
        capture_output=True,
    )


def _sha(repo):
    out = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo, check=True, capture_output=True)
    return out.stdout.decode().strip()


@pytest.fixture
def repo(tmp_path, monkeypatch):
    _git(tmp_path, "init", "-q")
    (tmp_path / "src").mkdir()
    (tmp_path / "docs").mkdir()
    (tmp_path / "src" / "app.py").write_text("x = 1\n" * 40)
    (tmp_path / "docs" / "a.md").write_text("doc\n")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-qm", "base")
    monkeypatch.chdir(tmp_path)
    return tmp_path


def _run_on_repo(repo, base):
    return ci.classify("pull_request", base, _sha(repo))[0]


def test_real_git_docs_edit_is_docs_only(repo):
    base = _sha(repo)
    (repo / "docs" / "a.md").write_text("changed\n")
    _git(repo, "commit", "-qam", "docs")
    assert _run_on_repo(repo, base) is True


def test_real_git_rename_from_runtime_to_docs_requires_the_full_build(repo):
    base = _sha(repo)
    _git(repo, "mv", "src/app.py", "docs/app.py")
    _git(repo, "commit", "-qm", "move runtime file into docs")
    assert _run_on_repo(repo, base) is False


def test_real_git_deleted_runtime_file_requires_the_full_build(repo):
    base = _sha(repo)
    _git(repo, "rm", "-q", "src/app.py")
    _git(repo, "commit", "-qm", "delete runtime file")
    assert _run_on_repo(repo, base) is False


def test_real_git_unreachable_base_requires_the_full_build(repo):
    assert ci.classify("pull_request", SHA_A, _sha(repo))[0] is False


# --- required gate ---------------------------------------------------------------------


@pytest.mark.parametrize(
    "classify_result,docs_only,build_result,passes",
    [
        ("success", "false", "success", True),
        ("success", "true", "skipped", True),  # documentation-only: not applicable
        ("success", "false", "failure", False),  # build or vulnerability scan failed
        ("success", "false", "cancelled", False),  # includes a timeout
        ("success", "false", "skipped", False),  # required build unexpectedly skipped
        ("success", "", "skipped", False),  # a skipped build alone never passes
        ("success", "true", "success", False),
        ("success", "true", "failure", False),
        ("failure", "", "skipped", False),  # classification failed: no silent skip
        ("failure", "true", "skipped", False),
        ("cancelled", "true", "skipped", False),
        ("skipped", "true", "skipped", False),
        ("", "", "", False),
    ],
)
def test_gate_verdict(classify_result, docs_only, build_result, passes):
    assert ci.gate(classify_result, docs_only, build_result)[0] is passes


def test_docs_only_gate_says_not_applicable():
    assert ci.gate("success", "true", "skipped")[1] == "not applicable: documentation-only change"


def test_gate_exit_code_follows_the_verdict(monkeypatch):
    env = {"CLASSIFY_RESULT": "success", "DOCS_ONLY": "false", "BUILD_RESULT": "failure"}
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    assert ci.main(["ci_changes.py", "gate"]) == 1
    monkeypatch.setenv("BUILD_RESULT", "success")
    assert ci.main(["ci_changes.py", "gate"]) == 0


# --- workflow structure ----------------------------------------------------------------


def _load(name):
    return yaml.safe_load((ROOT / ".github" / "workflows" / name).read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def pipeline():
    return _load("deploy-pipeline.yml")


def _on(workflow):
    return workflow.get("on", workflow.get(True))  # PyYAML reads the bare key `on` as True


def test_exactly_one_job_carries_the_required_check_name(pipeline):
    named = [j for j, body in pipeline["jobs"].items() if body.get("name") == GATE_NAME]
    assert named == ["build-and-scan"]


def test_gate_always_runs_and_waits_for_classification_and_the_build(pipeline):
    gate = pipeline["jobs"]["build-and-scan"]
    assert str(gate["if"]).strip() == "always()"
    assert {"classify", "image-build"} <= set(gate["needs"])
    assert "timeout-minutes" in gate


def test_gate_decides_from_the_needs_results(pipeline):
    gate = pipeline["jobs"]["build-and-scan"]
    steps = [s for s in gate["steps"] if "ci_changes.py gate" in s.get("run", "")]
    assert len(steps) == 1
    env = steps[0]["env"]
    assert env["CLASSIFY_RESULT"] == "${{ needs.classify.result }}"
    assert env["DOCS_ONLY"] == "${{ needs.classify.outputs.docs_only }}"
    assert env["BUILD_RESULT"] == "${{ needs.image-build.result }}"
    assert "continue-on-error" not in gate and "continue-on-error" not in steps[0]


def test_internal_build_job_does_not_share_the_required_name(pipeline):
    build = pipeline["jobs"]["image-build"]
    assert build["name"] != GATE_NAME
    assert {"classify", "security-and-lint", "helm-validation"} <= set(build["needs"])


def test_build_is_skipped_only_on_an_explicit_docs_only_verdict(pipeline):
    condition = str(pipeline["jobs"]["image-build"]["if"]).replace(" ", "")
    # No always()/failure(): a failed or cancelled classify keeps the implicit success()
    # check, so the build is skipped and the gate fails instead of silently passing.
    assert condition == "needs.classify.outputs.docs_only!='true'"


def test_build_and_scan_steps_cannot_swallow_failures(pipeline):
    build = pipeline["jobs"]["image-build"]
    assert "continue-on-error" not in build
    assert not [s for s in build["steps"] if s.get("continue-on-error")]


def test_build_has_timeouts_so_a_qemu_hang_cannot_run_for_hours(pipeline):
    build = pipeline["jobs"]["image-build"]
    assert 15 <= build["timeout-minutes"] <= 90
    multiarch = [s for s in build["steps"] if "Multi-Arch Image" in s.get("name", "")]
    assert len(multiarch) == 2
    for step in multiarch:
        assert 10 <= step["timeout-minutes"] < build["timeout-minutes"]
        assert step["with"]["platforms"] == "linux/amd64,linux/arm64"


def test_trivy_scans_still_cover_critical_and_high(pipeline):
    scans = [s for s in pipeline["jobs"]["image-build"]["steps"] if "trivy" in s.get("uses", "")]
    assert len(scans) == 2
    for scan in scans:
        assert scan["with"]["severity"] == "CRITICAL,HIGH"


def test_images_are_pushed_only_by_push_events(pipeline):
    steps = pipeline["jobs"]["image-build"]["steps"]
    pushes = [s["with"]["push"] for s in steps if "push" in s.get("with", {})]
    assert pushes == ["${{ github.event_name == 'push' }}"] * 2


def test_classify_uses_the_base_copy_of_the_classifier(pipeline):
    classify = pipeline["jobs"]["classify"]
    assert classify["permissions"] == {"contents": "read"}
    checkout = classify["steps"][0]
    assert checkout["with"]["fetch-depth"] == 0
    script = classify["steps"][1]["run"]
    assert 'git show "${BASE_SHA}:scripts/ci_changes.py"' in script
    assert "docs_only=false" in script  # no trusted classifier: full build


def test_triggers_keep_pr_and_push_and_add_schedule_and_manual_runs(pipeline):
    on = _on(pipeline)
    assert on["pull_request"] == {"branches": ["main"]}  # no paths / paths-ignore
    assert on["push"]["branches"] == ["main"] and on["push"]["tags"] == ["v*.*.*"]
    assert len(on["schedule"]) == 1
    minute, hour, dom, month, dow = on["schedule"][0]["cron"].split()
    assert dow != "*" and dom == "*" and month == "*", "weekly, not daily"
    assert on["workflow_dispatch"]["inputs"]["force_full"]["type"] == "boolean"


@pytest.mark.parametrize("name", ["test.yml", "playwright.yml"])
def test_other_workflows_have_no_path_filters_and_no_classifier(name):
    workflow = _load(name)
    for trigger in _on(workflow).values():
        assert not (isinstance(trigger, dict) and ({"paths", "paths-ignore"} & set(trigger)))
    assert "ci_changes" not in (ROOT / ".github" / "workflows" / name).read_text("utf-8")


def test_test_workflow_jobs_are_unchanged():
    assert set(_load("test.yml")["jobs"]) == {
        "arch-guard",
        "compose-boot",
        "backend",
        "postgres-integration",
        "frontend",
        "api-parity",
    }


# --- Dockerfiles -----------------------------------------------------------------------


def _copy_sources(dockerfile):
    sources = []
    for line in dockerfile.read_text("utf-8").splitlines():
        if line.upper().startswith("COPY ") and "--from=" not in line:
            args = [a for a in line.split()[1:] if not a.startswith("--")]
            sources += args[:-1]
    return sources


@pytest.mark.parametrize("dockerfile", ["Dockerfile.prod", "dashboard/Dockerfile.prod"])
def test_nothing_an_image_copies_is_classified_documentation_only(dockerfile):
    path = ROOT / dockerfile
    prefix = path.parent.relative_to(ROOT).as_posix()
    sources = _copy_sources(path)
    assert sources
    for source in sources:
        if source in (".", "./"):  # whole context: fine only inside dashboard/, never at the root
            assert prefix != ".", f"{dockerfile} copies the whole repository"
            continue
        full = source if prefix == "." else f"{prefix}/{source}"
        assert not ci.is_docs_only(full.rstrip("/")), f"{dockerfile} copies {full}"


def test_frontend_builder_runs_on_the_build_platform_and_ships_only_static_files():
    text = (ROOT / "dashboard" / "Dockerfile.prod").read_text("utf-8")
    stages = re.findall(r"^FROM\s+(.*?)\s+AS\s+(\w+)\s*$", text, re.M | re.I)
    assert [name for _, name in stages] == ["builder", "runtime"]
    builder, runtime = (spec for spec, _ in stages)
    assert builder == "--platform=$BUILDPLATFORM node:22.23.1-alpine"  # pinned image unchanged
    assert "--platform" not in runtime  # final image keeps target-platform behaviour
    from_builder = [ln for ln in text.splitlines() if "--from=builder" in ln]
    assert len(from_builder) == 1 and from_builder[0].split()[-2:] == [
        "/app/dist",
        "/usr/share/nginx/html",
    ]
    assert "node_modules" not in text
