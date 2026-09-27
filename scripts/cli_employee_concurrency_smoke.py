#!/usr/bin/env python3
"""Run several employee CLI backends at once and check that they overlap.

    python scripts/cli_employee_concurrency_smoke.py --backends claude,agy
    python scripts/cli_employee_concurrency_smoke.py --backends claude,agy --mock

Each backend gets its own CLIAdapter session and prompt. The run passes when
every backend answers for itself and the turns overlapped in time (one did not
wait for another to finish). Backends whose binary is missing are SKIPPED; with
fewer than two runnable backends the overlap check is skipped too.

Real mode may use the provider accounts the CLIs are signed in to and is never
run by the test suite or CI. See cli_employee_smoke.py for --mock and for what
is printed.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from contextlib import ExitStack

from cli_employee_smoke import mock_cli, run_backend


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--backends", default="claude,agy", help="comma-separated backend ids")
    parser.add_argument("--mock", action="store_true", help="use canned subprocesses instead of the CLIs")
    parser.add_argument("--timeout", type=int, default=180)
    args = parser.parse_args()
    backends = [b.strip() for b in args.backends.split(",") if b.strip()]

    async def run_all():
        return await asyncio.gather(
            *(run_backend(b, mock=args.mock, timeout=args.timeout) for b in backends)
        )

    with mock_cli(backends, 1.0) if args.mock else ExitStack():
        results = asyncio.run(run_all())
    for r in results:
        print(r.line())

    ran = [r for r in results if r.mode != "SKIPPED"]
    ok = all(r.ok for r in results)
    if len(ran) < 2:
        print(f"[SKIPPED] overlap: only {len(ran)} runnable backend(s)")
        return 0 if ok else 1
    # Each process's own run window (end minus its measured duration), so a
    # turn that queued behind another cannot count as overlapping it.
    windows = [(r.finished - (r.meta or {}).get("duration_ms", 0) / 1000, r.finished) for r in ran]
    overlap = min(end for _, end in windows) - max(start for start, _ in windows)
    print(f"[{ran[0].mode}] overlap {'PASS' if overlap > 0 else 'FAIL'}: {overlap:.1f}s shared")
    return 0 if ok and overlap > 0 else 1


if __name__ == "__main__":
    sys.exit(main())
