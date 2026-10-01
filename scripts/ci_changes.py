#!/usr/bin/env python3
"""Decide whether a pull request can skip the multi-arch image build.

The build is skipped only when every changed path is explicitly documentation-only.
Anything else - an unknown path, an empty or malformed change set, a missing SHA, a git
error - requires the full build. See docs/CI_SELECTIVE_BUILDS.md.

    ci_changes.py classify   writes docs_only=true|false (EVENT_NAME, BASE_SHA, HEAD_SHA,
                             FORCE_FULL in the environment)
    ci_changes.py gate       verdict for the required check (CLASSIFY_RESULT, DOCS_ONLY,
                             BUILD_RESULT in the environment); exit 1 means FAIL
"""

from __future__ import annotations

import os
import re
import subprocess
import sys

# Paths below these prefixes are never COPY'd into an image (tests/test_ci_changes.py
# checks that against the Dockerfiles).
DOCS_PREFIXES = ("docs/",)
# Dockerfile.prod COPYs README.md, so it is the one root Markdown file that is runtime.
ROOT_MARKDOWN_EXCLUDED = {"readme.md"}

SHA = re.compile(r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$")


def is_docs_only(path: str) -> bool:
    if not path or path.startswith("/") or "\\" in path or any(ord(c) < 32 for c in path):
        return False
    if any(part in ("", ".", "..") for part in path.split("/")):
        return False
    if path.startswith(DOCS_PREFIXES):
        return True
    return (
        "/" not in path
        and path.lower().endswith(".md")
        and (path.lower() not in ROOT_MARKDOWN_EXCLUDED)
    )


def changed_paths(base: str, head: str) -> list[str]:
    # --no-renames reports a rename as a delete plus an add, so both ends are classified.
    out = subprocess.run(
        ["git", "diff", "--name-only", "--no-renames", "-z", f"{base}...{head}"],
        capture_output=True,
        check=True,
        timeout=120,
    ).stdout.decode("utf-8")
    paths = out.split("\0")
    if paths and paths[-1] == "":
        paths.pop()
    return paths


def classify(
    event: str,
    base: str,
    head: str,
    force_full: str = "",
    diff=changed_paths,
) -> tuple[bool, str]:
    """Return (docs_only, reason). docs_only is True only on positive evidence."""
    try:
        if event != "pull_request":
            return False, f"{event or 'unknown'} event always builds"
        if force_full.strip().lower() == "true":
            return False, "force_full requested"
        if not (SHA.match(base or "") and SHA.match(head or "")):
            return False, "missing or malformed base/head SHA"
        paths = diff(base, head)
        if not paths:
            return False, "empty change set"
        runtime = [p for p in paths if not is_docs_only(p)]
        if runtime:
            return False, f"{len(runtime)} non-documentation path(s), e.g. {runtime[0]!r}"
        return True, f"all {len(paths)} changed path(s) are documentation-only"
    except Exception as exc:  # fail safe: any detection error means full build
        return False, f"detection error ({type(exc).__name__}): full build"


def gate(classify_result: str, docs_only: str, build_result: str) -> tuple[bool, str]:
    """Verdict for the required check. Only two combinations pass."""
    if classify_result != "success":
        return False, f"classification {classify_result or 'missing'}"
    if docs_only == "true" and build_result == "skipped":
        return True, "not applicable: documentation-only change"
    if docs_only == "false" and build_result == "success":
        return True, "multi-arch build and vulnerability scan passed"
    return (
        False,
        f"classify docs_only={docs_only or 'empty'}, image build {build_result or 'missing'}",
    )


def _emit(path_var: str, text: str) -> None:
    path = os.environ.get(path_var)
    if path:
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(text)


def main(argv: list[str]) -> int:
    env = os.environ.get
    if argv[1:] == ["classify"]:
        docs_only, reason = classify(
            env("EVENT_NAME", ""), env("BASE_SHA", ""), env("HEAD_SHA", ""), env("FORCE_FULL", "")
        )
        verdict = "documentation-only: image build skipped" if docs_only else "full build"
        print(f"{verdict} ({reason})")
        _emit("GITHUB_OUTPUT", f"docs_only={'true' if docs_only else 'false'}\n")
        _emit("GITHUB_STEP_SUMMARY", f"**Change classification:** {verdict} - {reason}\n")
        return 0
    if argv[1:] == ["gate"]:
        ok, message = gate(
            env("CLASSIFY_RESULT", ""), env("DOCS_ONLY", ""), env("BUILD_RESULT", "")
        )
        print(("PASS: " if ok else "FAIL: ") + message)
        _emit(
            "GITHUB_STEP_SUMMARY",
            f"**Multi-Arch Build & Vulnerability Scan:** {'PASS' if ok else 'FAIL'} - {message}\n",
        )
        return 0 if ok else 1
    print(__doc__, file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
