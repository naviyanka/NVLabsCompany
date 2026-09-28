#!/usr/bin/env python3
"""Smoke-test one employee CLI backend through the real CLIAdapter path.

    python scripts/cli_employee_smoke.py --backend claude
    python scripts/cli_employee_smoke.py --backend agy --mock

Real mode spawns the installed CLI, so it may use the provider account the CLI
is signed in to. It is never run by the test suite or CI. When the binary is
not on PATH the backend is reported as SKIPPED and the exit code is 0.

--mock replaces the subprocess with a canned reply, which checks the adapter
plumbing without any CLI or provider call.

Nothing here reads, prints or forwards credentials: the adapter's own
environment filter decides what the CLI sees, and only the executable's file
name (not its full path) is printed.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
import uuid
from contextlib import ExitStack
from dataclasses import dataclass
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from nexus.adapters.cli_adapter import CLIAdapter  # noqa: E402
from nexus.adapters.cli_registry import CLIRegistry, get_cli_registry  # noqa: E402

PROMPT = 'Return JSON only: {{"employee":"{backend}","result":55}}'


@dataclass
class SmokeResult:
    backend: str
    mode: str  # REAL | MOCK | SKIPPED
    ok: bool
    started: float = 0.0
    finished: float = 0.0
    output: str = ""
    error: str = ""
    meta: dict | None = None

    def line(self) -> str:
        if self.mode == "SKIPPED":
            return f"[SKIPPED] {self.backend}: {self.error}"
        status = "PASS" if self.ok else "FAIL"
        meta = self.meta or {}
        exe = Path(str(meta.get("executable") or "")).name
        return (
            f"[{self.mode}] {status} {self.backend} "
            f"({self.finished - self.started:.1f}s, exit={meta.get('exit_code')}, "
            f"exe={exe or '-'}, version={meta.get('version') or '-'}): "
            f"{(self.output or self.error).strip()[:200]}"
        )


def _fake_process(backend: str, delay: float) -> MagicMock:
    reply = json.dumps({"employee": backend, "result": 55}).encode()

    async def read_stdout(*_):
        await asyncio.sleep(delay)
        read_stdout.chunks, chunk = [b""], read_stdout.chunks[0]
        return chunk

    read_stdout.chunks = [reply]
    proc = MagicMock(pid=None, returncode=0)
    proc.stdin = MagicMock(write=MagicMock(), drain=AsyncMock(), close=MagicMock())
    proc.stdout = MagicMock(read=read_stdout)
    proc.stderr = MagicMock(read=AsyncMock(return_value=b""))
    proc.wait = AsyncMock(return_value=0)
    return proc


def mock_cli(backends: list[str], delay: float) -> ExitStack:
    """Patch the registry and subprocess spawn so no real CLI runs."""
    registry = CLIRegistry(auto_detect=False)
    for b in backends:
        registry._available[b] = f"/mock/{b}"

    async def spawn(*argv, **_):
        backend = next(b for b in backends if Path(argv[0]).name == b)
        return _fake_process(backend, delay)

    stack = ExitStack()
    stack.enter_context(patch("nexus.adapters.cli_adapter.get_cli_registry", return_value=registry))
    stack.enter_context(patch("nexus.adapters.cli_adapter.asyncio.create_subprocess_exec", spawn))
    stack.enter_context(patch.object(CLIRegistry, "probe_version", lambda *a, **k: "mock"))
    return stack


async def run_backend(backend: str, *, mock: bool, prompt: str | None = None,
                      timeout: int = 180) -> SmokeResult:
    registry = CLIRegistry(auto_detect=False)
    info = registry.get_backend(backend)
    if info is None:
        return SmokeResult(backend, "SKIPPED", True, error="unknown backend id")
    backend = info.id
    if not info.execution_supported:
        return SmokeResult(backend, "SKIPPED", True, error="catalog-only backend (not executable)")
    if not mock and not get_cli_registry().is_available(backend):
        return SmokeResult(backend, "SKIPPED", True, error="binary not installed on PATH")

    adapter = CLIAdapter()
    session = await adapter.create_session(uuid.uuid4(), {"backend": backend, "timeout": timeout})
    result = SmokeResult(backend, "MOCK" if mock else "REAL", False, started=time.monotonic())
    try:
        task = await adapter.execute_task(
            session, uuid.uuid4(),
            {"prompt": prompt or PROMPT.format(backend=backend), "system_prompt": ""},
        )
    finally:
        result.finished = time.monotonic()
        await adapter.terminate(session)
    result.meta = next((a for a in task.artifacts if a.get("type") == "cli_execution"), {})
    result.output = str(task.output or "")
    result.error = task.error or ""
    result.ok = (
        task.success
        and result.meta.get("backend") == backend
        and f'"employee":"{backend}"' in result.output.replace(" ", "")
    )
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--backend", required=True, help="canonical backend id, e.g. claude or agy")
    parser.add_argument("--mock", action="store_true", help="use a canned subprocess instead of the CLI")
    parser.add_argument("--timeout", type=int, default=180)
    args = parser.parse_args()

    with mock_cli([args.backend], 0.1) if args.mock else ExitStack():
        result = asyncio.run(run_backend(args.backend, mock=args.mock, timeout=args.timeout))
    print(result.line())
    return 0 if result.ok else 1


if __name__ == "__main__":
    sys.exit(main())
