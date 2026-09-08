#!/usr/bin/env python3
"""Guard against committing generated / ephemeral artifacts into git.

Rule WP-13:
- graphify-out/
- *.egg-info
- __pycache__ / *.pyc
- node_modules
- coverage / .coverage
"""
import subprocess
import sys

BANNED_PREFIXES = (
    "graphify-out/",
    "graphify-out\\",
    ".pytest_cache/",
    "node_modules/",
    "coverage/",
)

BANNED_SUFFIXES = (
    ".pyc",
    ".egg-info",
)

def main():
    res = subprocess.run(
        ["git", "ls-files", "--stage"],
        capture_output=True,
        text=True,
        check=True
    )
    violations = []
    for line in res.stdout.splitlines():
        parts = line.split("\t", 1)
        if len(parts) < 2:
            continue
        filepath = parts[1].strip()
        for p in BANNED_PREFIXES:
            if filepath.startswith(p):
                violations.append(f"Banned prefix {p}: {filepath}")
        for s in BANNED_SUFFIXES:
            if filepath.endswith(s) or (s + "/") in filepath:
                violations.append(f"Banned suffix {s}: {filepath}")
    if violations:
        print("FAIL check_generated_artifacts: git index contains generated files:")
        for v in violations:
            print("  ", v)
        return 1
    print("check_generated_artifacts: clean (no banned generated artifacts in git index).")
    return 0

if __name__ == "__main__":
    sys.exit(main())
