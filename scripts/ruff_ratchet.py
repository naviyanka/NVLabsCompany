#!/usr/bin/env python3
"""Ruff ratchet: no file may gain violations of any rule.

`ruff check .` reported 2900 violations in 439 files when this gate was
introduced, and it had never passed on main. Fixing all of them in one change
would rewrite most of the tree. Instead, the per-file, per-rule counts at that
point are recorded in ``ruff_baseline.json``. A file whose count for a rule
rises above its baseline fails, and a file missing from the baseline must be
clean. The rule selection in pyproject.toml is unchanged.

Run: python scripts/ruff_ratchet.py [--baseline]
Exit 0 = no file got worse, exit 1 = new violation(s).

The counts depend on the ruff version, so CI pins it (docs/CI_BASELINE.md).
When a file improves, run ``--baseline`` to lock in the lower count.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BASELINE_PATH = Path(__file__).with_name("ruff_baseline.json")


def run_ruff() -> list[dict]:
    proc = subprocess.run(
        [sys.executable, "-m", "ruff", "check", ".", "--output-format", "json", "--exit-zero"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    return json.loads(proc.stdout)


def rel(filename: str) -> str:
    return Path(filename).resolve().relative_to(ROOT).as_posix()


def count(diagnostics: list[dict]) -> dict[str, dict[str, int]]:
    counts: dict[str, Counter[str]] = {}
    for d in diagnostics:
        counts.setdefault(rel(d["filename"]), Counter())[d["code"] or "syntax-error"] += 1
    return {f: dict(sorted(c.items())) for f, c in sorted(counts.items())}


def regressions(
    current: dict[str, dict[str, int]], baseline: dict[str, dict[str, int]]
) -> list[tuple[str, str, int, int]]:
    return [
        (f, code, n, baseline.get(f, {}).get(code, 0))
        for f, codes in current.items()
        for code, n in codes.items()
        if n > baseline.get(f, {}).get(code, 0)
    ]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--baseline", action="store_true", help="rewrite the baseline and exit")
    args = ap.parse_args(argv)

    diagnostics = run_ruff()
    current = count(diagnostics)
    if args.baseline:
        BASELINE_PATH.write_text(json.dumps(current, indent=1) + "\n", encoding="utf-8")
        print(f"ruff-ratchet: wrote {len(diagnostics)} violation(s) in {len(current)} file(s).")
        return 0

    baseline = json.loads(BASELINE_PATH.read_text(encoding="utf-8"))
    failed = regressions(current, baseline)
    for f, code, n, allowed in failed:
        print(f"FAIL  {f}: {code} {n} > baseline {allowed}")
        for d in diagnostics:
            if rel(d["filename"]) == f and (d["code"] or "syntax-error") == code:
                loc = d["location"]
                print(f"      {f}:{loc['row']}:{loc['column']}: {code} {d['message']}")
    if failed:
        print(f"\nruff-ratchet: {len(failed)} file/rule count(s) above baseline.")
        return 1
    total = sum(sum(c.values()) for c in baseline.values())
    print(f"ruff-ratchet: clean ({len(diagnostics)} violation(s), baseline {total}).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
