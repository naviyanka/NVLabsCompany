#!/usr/bin/env python3
"""Architecture invariant guard (Phase 0.6 / A7).

Four rules, each guarding an invariant that earlier Wave 0 phases established.
None of them are style rules: every one of them protects a property that fails
silently at runtime rather than loudly at import time, which is exactly the
class of regression a reviewer misses.

Run: python scripts/arch_guard.py [--list-baseline]
Exit 0 = clean (baselined debt prints as WARN), exit 1 = new violation.

Rules
-----
R1  No new module-level mutable state in ``governance/``.
    Governance state (audit entries, approvals, breaker trips, kill-switch
    position) must live in the database so it survives a restart and is shared
    across replicas. A module-level dict or list silently becomes per-process
    state: the second worker disagrees with the first, and nothing errors.
    UPPER_CASE names are exempt as declared constants.

R2  No second scheduler.
    Two things polling the same trigger rows means a cron trigger fires twice,
    and duplicate LLM spend is not idempotent. ``runtime/scheduler.py`` owns
    the tick loop and gates it behind ``is_leader()``; anything else that wants
    periodic work registers with it. Also bans apscheduler/celery imports,
    which bring their own loop.

R3  ``workflows/`` must not import DB sessions directly.
    Workflow bodies are replayed by Temporal. A session opened inside a
    workflow is a non-deterministic side effect that breaks replay and holds a
    connection across an arbitrarily long await. DB access belongs in
    activities; workflows pass DTOs.

R4  ``*_persistent.py`` / ``persistent_*.py`` must import ``AsyncSession``.
    A module whose name claims persistence but keeps a Python list is the
    worst failure mode available: callers trust the name, the data is gone on
    restart, and no test that runs in one process can tell.

R5  No unscoped query against a tenant table in ``api/routes/`` (Phase 5.2).
    A route that does ``select(Task)`` without a ``company_id`` filter returns
    every tenant's rows. Nothing fails: the response is a valid list, longer
    than it should be, and in single-tenant development it is indistinguishable
    from correct. The tenant tables are discovered from ``models/`` rather than
    listed here, so a new model with a ``company_id`` column is covered the day
    it lands. A route function is clean when ``company_id`` appears somewhere in
    its body -- coarse on purpose, since the filter is often assembled across
    several statements, and a rule that demanded one shape would be argued with
    rather than obeyed.
"""

from __future__ import annotations

import argparse
import ast
import json
import sys
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent / "src" / "nexus"

# --- R1 ---------------------------------------------------------------------
MUTABLE_CALLS = {"dict", "list", "set", "defaultdict", "deque", "OrderedDict", "Counter"}

# --- R2 ---------------------------------------------------------------------
# Files allowed to own a `while ...: await asyncio.sleep(...)` loop.
# runtime/scheduler.py is the one trigger dispatcher; the other two poll their
# own in-process state, not the trigger table.
LOOP_OWNERS = {
    "runtime/scheduler.py",  # the scheduler
    "runtime/watchdog.py",  # stall detection over live run state
    "runtime/orchestrator.py",  # per-run agent iteration loop
}
BANNED_SCHEDULER_IMPORTS = ("apscheduler", "celery", "rq_scheduler", "schedule")

# --- R3 ---------------------------------------------------------------------
SESSION_NAMES = {
    "AsyncSession",
    "Session",
    "sessionmaker",
    "async_sessionmaker",
    "get_session",
    "get_db",
    "SessionLocal",
    "engine",
}
SESSION_MODULES = ("sqlalchemy.orm", "sqlalchemy.ext.asyncio", "nexus.database")

# --- R5 ---------------------------------------------------------------------
# Route functions exempt from the company_id requirement, each with the reason
# the query is legitimately global. Same drift risk as LOOP_OWNERS, so
# test_arch_guard.py checks these still exist.
TENANT_QUERY_OWNERS = {
    # A caller's own companies cannot be filtered by the company being looked
    # up; membership is the filter, and these routes apply it.
    "companies.py",
    # Login and setup run before a company is known.
    "auth.py",
}

# --- Baseline ---------------------------------------------------------------
# Pre-existing violations, each owned by a phase that will remove it. Entries
# print as WARN and do not fail the build. Adding an entry requires a phase
# reference; removing one is the definition of that phase being done.
#
# The baseline lives in a sibling JSON file rather than in this script so that a
# phase which resolves a violation can prune its own entry without editing the
# guard. Regenerate the file from the current tree with --baseline.
BASELINE_PATH = Path(__file__).with_name("arch_guard_baseline.json")


def load_baseline() -> dict[str, str]:
    """Read the baseline JSON, tolerating its absence (treated as empty)."""
    if not BASELINE_PATH.exists():
        return {}
    data = json.loads(BASELINE_PATH.read_text(encoding="utf-8"))
    return dict(data.get("violations", {}))


def write_baseline(violations: dict[str, str]) -> None:
    """Overwrite the baseline file with the given violations."""
    payload = {
        "_comment": (
            "Pre-existing architecture violations, each owned by a phase that "
            "removes it. Entries print as WARN and do not fail the build. "
            "Regenerate with: python scripts/arch_guard.py --baseline. Adding an "
            "entry by hand requires a phase reference in its reason."
        ),
        "violations": violations,
    }
    BASELINE_PATH.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


BASELINE: dict[str, str] = load_baseline()


def rel(path: Path) -> str:
    return path.relative_to(SRC).as_posix()


def iter_py(subdir: str = "") -> list[Path]:
    root = SRC / subdir if subdir else SRC
    return sorted(p for p in root.rglob("*.py") if "__pycache__" not in p.parts)


def parse(path: Path) -> ast.Module | None:
    try:
        return ast.parse(path.read_text(encoding="utf-8"))
    except (SyntaxError, UnicodeDecodeError):
        return None


def is_mutable_literal(node: ast.expr) -> bool:
    if isinstance(node, (ast.Dict, ast.List, ast.Set, ast.DictComp, ast.ListComp, ast.SetComp)):
        return True
    if isinstance(node, ast.Call):
        fn = node.func
        name = fn.attr if isinstance(fn, ast.Attribute) else getattr(fn, "id", None)
        return name in MUTABLE_CALLS
    return False


def targets(stmt: ast.Assign | ast.AnnAssign) -> list[str]:
    raw = stmt.targets if isinstance(stmt, ast.Assign) else [stmt.target]
    return [t.id for t in raw if isinstance(t, ast.Name)]


def check_r1() -> list[tuple[str, str]]:
    """No new module-level mutable state in governance/."""
    out: list[tuple[str, str]] = []
    for path in iter_py("governance"):
        tree = parse(path)
        if tree is None:
            continue
        for stmt in tree.body:
            if not isinstance(stmt, (ast.Assign, ast.AnnAssign)) or stmt.value is None:
                continue
            mutable = is_mutable_literal(stmt.value)
            singleton = isinstance(stmt.value, ast.Constant) and (
                stmt.value.value is None or stmt.value.value is False
            )
            for name in targets(stmt):
                if name.isupper() or name.startswith("__"):
                    continue  # declared constant / dunder
                if not (mutable or singleton):
                    continue
                kind = "mutable state" if mutable else "mutable singleton"
                out.append(
                    (
                        f"R1 {rel(path)}:{name}",
                        f"module-level {kind} at line {stmt.lineno} -- "
                        "governance state must be in the DB",
                    )
                )
    return out


def check_r2() -> list[tuple[str, str]]:
    """No second scheduler."""
    out: list[tuple[str, str]] = []
    for path in iter_py():
        tree = parse(path)
        if tree is None:
            continue
        name = rel(path)
        for node in ast.walk(tree):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                mods = (
                    [a.name for a in node.names]
                    if isinstance(node, ast.Import)
                    else [node.module or ""]
                )
                for mod in mods:
                    if mod.split(".")[0] in BANNED_SCHEDULER_IMPORTS:
                        out.append(
                            (
                                f"R2 {name}:{mod}",
                                f"third-party scheduler imported at line {node.lineno} -- "
                                "runtime/scheduler.py owns the only tick loop",
                            )
                        )
            if isinstance(node, ast.While) and name not in LOOP_OWNERS:
                dumped = ast.dump(node)
                if "'sleep'" in dumped and "asyncio" in dumped:
                    out.append(
                        (
                            f"R2 {name}:{node.lineno}",
                            f"polling loop at line {node.lineno} -- register periodic work with "
                            "runtime/scheduler.py instead of starting a second loop",
                        )
                    )
    return out


def check_r3() -> list[tuple[str, str]]:
    """workflows/ must not import DB sessions directly."""
    out: list[tuple[str, str]] = []
    for path in iter_py("workflows"):
        tree = parse(path)
        if tree is None:
            continue
        for node in ast.walk(tree):
            hits: list[str] = []
            if isinstance(node, ast.ImportFrom):
                mod = node.module or ""
                if mod.startswith(SESSION_MODULES):
                    hits = [a.name for a in node.names]
                else:
                    hits = [a.name for a in node.names if a.name in SESSION_NAMES]
            elif isinstance(node, ast.Import):
                hits = [a.name for a in node.names if a.name.startswith(SESSION_MODULES)]
            for hit in hits:
                out.append(
                    (
                        f"R3 {rel(path)}:{hit}",
                        f"DB session imported at line {node.lineno} -- workflows are replayed; "
                        "move DB access into a Temporal activity and pass a DTO",
                    )
                )
    return out


def check_r4() -> list[tuple[str, str]]:
    """*_persistent.py must import AsyncSession."""
    out: list[tuple[str, str]] = []
    for path in iter_py():
        stem = path.stem
        if not (stem.endswith("_persistent") or stem.startswith("persistent_")):
            continue
        # A module can reach the DB either by naming AsyncSession directly or by
        # pulling the shared session factory, which is the lazier pattern used to
        # avoid an import cycle. Both count as being DB-backed.
        source = path.read_text(encoding="utf-8")
        if not any(
            token in source
            for token in ("AsyncSession", "async_session_factory", "async_sessionmaker")
        ):
            out.append(
                (
                    f"R4 {rel(path)}",
                    "named persistent but never imports AsyncSession -- "
                    "either back it with the DB or drop the name",
                )
            )
    return out


def tenant_models() -> set[str]:
    """Model class names carrying a ``company_id`` column.

    Read out of ``models/`` rather than hard-coded so the rule covers a new
    tenant table the day it is added, instead of the day someone remembers to
    extend a list here.
    """
    names: set[str] = set()
    for path in iter_py("models"):
        tree = parse(path)
        if tree is None:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.ClassDef):
                continue
            for stmt in node.body:
                if isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name):
                    if stmt.target.id == "company_id":
                        names.add(node.name)
                        break
    return names


def queried_models(fn: ast.AST) -> set[str]:
    """Model names appearing as ``select(Model)`` / ``delete(Model)`` inside ``fn``."""
    out: set[str] = set()
    for node in ast.walk(fn):
        if not isinstance(node, ast.Call):
            continue
        fname = node.func.attr if isinstance(node.func, ast.Attribute) else getattr(
            node.func, "id", None
        )
        if fname not in ("select", "delete", "update"):
            continue
        for arg in node.args:
            if isinstance(arg, ast.Name):
                out.add(arg.id)
            elif isinstance(arg, ast.Attribute) and isinstance(arg.value, ast.Name):
                # `select(Task.status)` -- still a read of the tenant table.
                out.add(arg.value.id)
    return out


def check_r5() -> list[tuple[str, str]]:
    """No unscoped query against a tenant table in api/routes/."""
    tenant = tenant_models()
    out: list[tuple[str, str]] = []
    for path in iter_py("api/routes"):
        if path.name in TENANT_QUERY_OWNERS:
            continue
        tree = parse(path)
        if tree is None:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            hit = sorted(queried_models(node) & tenant)
            if not hit:
                continue
            # The filter is often built up over several statements, sometimes
            # through a helper's keyword argument, so presence of the column
            # name anywhere in the function is what counts as scoped.
            if "company_id" in ast.dump(node):
                continue
            out.append(
                (
                    f"R5 {rel(path)}:{node.name}",
                    f"queries tenant table(s) {', '.join(hit)} at line {node.lineno} "
                    "without a company_id filter -- add one, or scope the session "
                    "with nexus.database.tenant_scope()",
                )
            )
    return out


CHECKS = (check_r1, check_r2, check_r3, check_r4, check_r5)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--list-baseline", action="store_true", help="print baselined debt and exit")
    ap.add_argument(
        "--baseline",
        action="store_true",
        help="regenerate the baseline file from the current tree, then exit",
    )
    ap.add_argument(
        "--strict-baseline",
        action="store_true",
        help="fail when a baselined violation is resolved but its entry remains",
    )
    args = ap.parse_args(argv)

    if args.list_baseline:
        for key, why in sorted(BASELINE.items()):
            print(f"{key}\n    {why}")
        return 0

    failures: list[tuple[str, str]] = []
    warnings: list[tuple[str, str]] = []
    for check in CHECKS:
        for key, msg in check():
            (warnings if key in BASELINE else failures).append((key, msg))

    if args.baseline:
        found = {k: BASELINE.get(k, "TODO: name the phase that removes this") for k, _ in warnings}
        found.update({k: "TODO: name the phase that removes this" for k, _ in failures})
        write_baseline(dict(sorted(found.items())))
        print(f"arch-guard: wrote {len(found)} entry(ies) to {BASELINE_PATH.name}.")
        return 0

    for key, msg in warnings:
        print(f"WARN  {key}\n      {msg}\n      baselined: {BASELINE[key]}")
    for key, msg in failures:
        print(f"FAIL  {key}\n      {msg}")

    # A baselined entry that no longer fires means the phase owning it has
    # landed. That is good news, so it is reported but does not redden CI by
    # default -- otherwise a landing phase breaks the build until someone prunes
    # the file. Use --strict-baseline in a cleanup job to enforce pruning.
    stale = sorted(set(BASELINE) - {k for k, _ in warnings})
    label = "FAIL" if args.strict_baseline else "DONE"
    for key in stale:
        print(
            f"{label}  {key}\n      resolved -- remove this entry from "
            f"{BASELINE_PATH.name}"
        )
    if stale and args.strict_baseline:
        failures.extend((k, "stale baseline") for k in stale)

    if failures:
        print(
            f"\narch-guard: {len(failures)} violation(s). "
            "See scripts/arch_guard.py for rationale."
        )
        return 1
    print(f"arch-guard: clean ({len(warnings)} baselined).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
