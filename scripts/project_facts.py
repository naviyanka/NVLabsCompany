#!/usr/bin/env python3
"""Read-only project-facts and documentation-drift auditor for NEXUS.

Static repository inspection only: no application imports, no settings, no database, no
containers, no network, no shell. Facts come from read-only git plumbing plus bounded reads
of tracked files parsed with ast / tomllib / PyYAML (the repository's declared YAML
dependency). Counts are static approximations; docs/testing/PROJECT_FACTS_AUDITOR.md
documents the counting rules and their limits.

Claim statuses (non-overlapping):
    matches                     - claim and measured fact share the same unit and scope.
    stale                       - comparable claim that disagrees with the measured fact.
    not_statically_verifiable   - runtime semantics static scanning cannot adjudicate.
    not_statically_comparable   - the documented metric is not the claimed unit.
    subjective                  - judgment language, reported but never objectively matched.

--check-docs exits nonzero only for `stale`.

Usage: python scripts/project_facts.py [--repo PATH] [--json PATH] [--markdown PATH]
                                       [--check-docs] [--overwrite]
"""
from __future__ import annotations

import argparse
import ast
import json
import os
import re
import subprocess
import sys
import tomllib
from collections import Counter
from pathlib import Path

import yaml

SCHEMA_VERSION = 2
BACKEND_ROOT = "src/nexus"
API_ROOT = "src/nexus/api"
DASH_ROOT = "dashboard"
PAGES_DIR = "dashboard/src/pages"
APP_TSX = "dashboard/src/App.tsx"
DOC_FILES = ("README.md", "ARCHITECTURE.md", "FEATURES.md", "docs/FINAL-STATUS-SUMMARY.md")
ROUTE_METHODS = ("delete", "get", "head", "options", "patch", "post", "put")
HEX40 = re.compile(r"^[0-9a-f]{40}$")
MOCK_DECL = re.compile(r"\bMOCK_[A-Z][A-Z0-9_]*\b")
MAX_FILE_BYTES = 1_000_000
CLAIM_EXCERPT_CHARS = 120
COMMAND_CAP = 200
LOC_RULE = "non-blank lines (lines containing at least one non-whitespace character)"
STATUS_NOTE = ("statuses: matches | stale | not_statically_verifiable | "
               "not_statically_comparable | subjective; --check-docs fails only on stale")
RAW_COMPANY_NOTE = "A raw company_id parameter is an audit signal, not proof of a vulnerability."
TABLE_NOTE = ("Static count of SQLModel class definitions carrying table=True; not a physical-"
              "table count, and generic 'tables' claims are never compared against it.")
ACTION_NOTE = ("Only a 40-hex commit SHA or a Docker digest pins action content; branches, "
               "major tags and semantic tags are mutable; short SHAs and dynamic refs need review.")
TEST_NOTE = ("Static count of Python functions named test_*; parametrization is not expanded. "
             "This is never a collected, executed or passed-test figure.")
TEST_CLAIM_NOTE = ("Runtime test totals ('N tests', 'N+ tests', 'N tests passed/passing') are "
                   "never statically verifiable; only explicit 'N static test functions' claims "
                   "compare with static_test_function_count.")
PAGE_NOTE = ("Page-component files, mounted routes and unique mounted page components are "
             "separate metrics derived from App.tsx route registrations; generic 'UI pages' "
             "claims are not statically comparable.")
DOCS_NOTE = "--check-docs fails only on 'stale' claims; the other four statuses never fail it."


class AuditError(Exception):
    """A refusal (output-path safety, missing repository) with a clean message."""


def _git(repo, *args):
    try:
        proc = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True,
                              timeout=60, check=True)
    except (OSError, subprocess.SubprocessError):
        return None
    return proc.stdout


def _clean(exc, repo) -> str:
    """Exception text with any repository-local absolute path stripped."""
    message = f"{type(exc).__name__}: {exc}"
    for prefix in (str(repo) + os.sep, str(repo) + "/", str(repo)):
        message = message.replace(prefix, "")
    return message.strip().lstrip("\\/") or type(exc).__name__


def _tracked_files(repo) -> list[str]:
    out = _git(repo, "ls-files", "-z")
    if out is None:
        return []
    names = []
    for raw in out.split("\0"):
        if raw and not Path(raw).name.startswith(".env"):
            names.append(raw.replace("\\", "/"))
    return sorted(set(names))


def _read(repo, rel):
    """Bounded read of one tracked file; returns (text, "") or (None, reason)."""
    path = repo / rel
    try:
        if not path.resolve().is_relative_to(repo.resolve()):
            return None, "symlink-escape"
        if path.stat().st_size > MAX_FILE_BYTES:
            return None, "oversized"
        data = path.read_bytes()
    except OSError as exc:
        return None, _clean(exc, repo)
    if b"\x00" in data[:8192]:
        return None, "binary"
    return data.decode("utf-8", errors="replace"), ""


def _scan_python(repo, files, diags):
    """Parse every tracked .py file once, recording LOC (non-blank lines) per file."""
    trees: dict = {}
    loc: dict = {}
    for rel in files:
        if not rel.endswith(".py"):
            continue
        text, why = _read(repo, rel)
        if text is None:
            diags.append({"file": rel, "error": f"skipped: {why}"})
            continue
        loc[rel] = sum(1 for line in text.splitlines() if line.strip())
        try:
            trees[rel] = ast.parse(text, filename=rel)
        except (SyntaxError, ValueError, RecursionError) as exc:
            diags.append({"file": rel, "error": _clean(exc, repo)})
    return trees, loc


def git_facts(repo) -> dict:
    sha = _git(repo, "rev-parse", "HEAD")
    if sha is None:
        return {"available": False, "commit_sha": None, "branch": None, "dirty": None,
                "tracked_dirty_paths": []}
    branch = (_git(repo, "rev-parse", "--abbrev-ref", "HEAD") or "").strip()
    status_all = _git(repo, "status", "--porcelain", "-z") or ""
    tracked = _git(repo, "status", "--porcelain", "-uno", "-z") or ""
    # dirty covers untracked files too; the path list is tracked changes only.
    paths = sorted({tok[3:].replace("\\", "/") for tok in tracked.split("\0") if len(tok) >= 4})
    return {"available": True, "commit_sha": sha.strip(), "branch": branch or None,
            "dirty": bool(status_all.strip()), "tracked_dirty_paths": paths}


def _dotted(node):
    if isinstance(node, ast.Name):
        return node.id
    return node.attr if isinstance(node, ast.Attribute) else None


def _sole_pass_count(tree) -> int:
    """pass statements that are the only statement of their block."""
    count = 0
    for node in ast.walk(tree):
        for field in ("body", "orelse", "finalbody"):
            block = getattr(node, field, None)
            if isinstance(block, list) and len(block) == 1 and isinstance(block[0], ast.Pass):
                count += 1
    return count


def backend_facts(files, trees, loc) -> dict:
    prefix = BACKEND_ROOT + "/"
    py = [f for f in files if f.startswith(prefix) and f.endswith(".py")]
    top = sorted({p[2] for f in py if len(p := f.split("/")) > 3})
    broad: Counter = Counter()
    passes = 0
    for rel, tree in trees.items():
        if not rel.startswith(prefix):
            continue
        passes += _sole_pass_count(tree)
        for node in ast.walk(tree):
            if not isinstance(node, ast.ExceptHandler):
                continue
            # A tuple handler such as `except (ValueError, OSError)` counts as neither.
            if node.type is None:
                broad["except_bare"] += 1
            elif _dotted(node.type) in ("Exception", "BaseException"):
                broad[f"except_{_dotted(node.type).lower()}"] += 1
    handlers = {"except_exception": broad["except_exception"],
                "except_baseexception": broad["except_baseexception"],
                "except_bare": broad["except_bare"]}
    return {"root": BACKEND_ROOT, "python_file_count": len(py),
            "python_loc": sum(loc.get(f, 0) for f in py), "loc_rule": LOC_RULE,
            "top_level_directory_count": len(top), "top_level_directories": top,
            "broad_exception_handlers": handlers, "standalone_pass_count": passes}


def _find_cycles(children: dict) -> list:
    color: dict = {}
    cycles: list = []

    def visit(node, stack):
        color[node] = 1
        stack.append(node)
        for child in sorted(children.get(node, ())):
            if color.get(child) == 1:
                cycles.append(stack[stack.index(child):] + [child])
            elif color.get(child) is None:
                visit(child, stack)
        stack.pop()
        color[node] = 2

    for node in sorted(children):
        if color.get(node) is None:
            visit(node, [])
    return cycles


def database_facts(files, trees, diags) -> dict:
    # The revisions directory is whichever "versions" directory holds the most .py files.
    counts: dict = {}
    for f in files:
        parts = f.split("/")
        if "versions" in parts and f.endswith(".py"):
            directory = "/".join(parts[: parts.index("versions") + 1])
            counts[directory] = counts.get(directory, 0) + 1
    mdir = max(sorted(counts), key=lambda d: counts[d]) if counts else None
    mig = [f for f in files if mdir and f.startswith(mdir + "/") and f.endswith(".py")]
    revs: dict = {}
    for rel in mig:
        tree = trees.get(rel)
        if tree is None:
            continue
        revision = down = None
        # Statically read `revision` / `down_revision` assignments; never import the module.
        for stmt in tree.body:
            target = None
            if isinstance(stmt, ast.Assign) and len(stmt.targets) == 1:
                target = stmt.targets[0]
            elif isinstance(stmt, ast.AnnAssign):
                target = stmt.target
            if not isinstance(target, ast.Name) or target.id not in ("revision", "down_revision"):
                continue
            value = stmt.value
            if isinstance(value, ast.Constant):
                value = value.value
            elif isinstance(value, ast.Tuple) and all(isinstance(e, ast.Constant)
                                                      for e in value.elts):
                value = tuple(e.value for e in value.elts)
            else:
                value = "?dynamic"
            if target.id == "revision":
                revision = value
            else:
                down = value
        if isinstance(revision, str) and revision != "?dynamic":
            revs[revision] = {"file": rel, "down": down}
        else:
            diags.append({"file": rel, "error": "migration revision id is not static"})
    children: dict = {rid: [] for rid in revs}
    down_refs: set = set()
    dangling: list = []
    for rid in sorted(revs):
        down = revs[rid]["down"]
        refs = list(down) if isinstance(down, tuple) else [down]
        for ref in refs:
            if ref is None:
                continue
            if ref == "?dynamic" or not isinstance(ref, str):
                diags.append({"file": revs[rid]["file"], "error": "down_revision is not static"})
                continue
            if ref not in revs:
                dangling.append({"file": revs[rid]["file"], "down_revision": ref})
            down_refs.add(ref)
            children.setdefault(ref, []).append(rid)
    table_count = 0
    for rel, tree in trees.items():
        if not rel.startswith(BACKEND_ROOT + "/"):
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef) and any(
                    kw.arg == "table" and isinstance(kw.value, ast.Constant)
                    and kw.value.value is True for kw in node.keywords):
                table_count += 1
    return {"migration_directory": mdir, "alembic_migration_file_count": len(mig),
            "revision_count": len(revs), "revision_ids": sorted(revs),
            "heads": sorted(rid for rid in revs if rid not in down_refs),
            "branch_points": sorted(d for d in children if d in revs and len(children[d]) > 1),
            "cycles": _find_cycles(children), "dangling_down_revisions": dangling,
            "sqlmodel_table_class_count": table_count, "physical_table_note": TABLE_NOTE}


def api_facts(trees) -> dict:
    prefix = API_ROOT + "/"
    methods: Counter = Counter({m: 0 for m in ROUTE_METHODS})
    modules = functions = current = pathdep = raw_count = 0
    raw: list = []
    for rel in sorted(trees):
        if not rel.startswith(prefix):
            continue
        has_route = False
        for node in ast.walk(trees[rel]):
            if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                continue
            decorators = []
            for dec in node.decorator_list:
                target = dec.func if isinstance(dec, ast.Call) else dec
                if isinstance(target, ast.Attribute) and target.attr in ROUTE_METHODS:
                    args = dec.args if isinstance(dec, ast.Call) else []
                    first = args[0] if args and isinstance(args[0], ast.Constant) else None
                    path = first.value if isinstance(first, ast.Constant) else None
                    decorators.append((target.attr, path if isinstance(path, str) else None))
            if not decorators:
                continue
            if not has_route:
                modules += 1
                has_route = True
            functions += 1
            for method, _path in decorators:
                methods[method] += 1
            for arg in node.args.args + node.args.kwonlyargs:
                if arg.arg != "company_id":
                    continue
                names = set()
                if arg.annotation is not None:
                    names = {s.id for s in ast.walk(arg.annotation) if isinstance(s, ast.Name)}
                    names |= {s.attr for s in ast.walk(arg.annotation)
                              if isinstance(s, ast.Attribute)}
                if any(name.endswith("CurrentCompanyId") for name in names):
                    current += 1
                elif any(name.endswith("PathCompanyId") for name in names):
                    pathdep += 1
                else:
                    raw_count += 1
                    raw.append({"file": rel, "function": node.name})
    raw.sort(key=lambda r: (r["file"], r["function"]))
    return {"route_module_count": modules, "route_function_count": functions,
            "routes_by_method": {m: methods[m] for m in ROUTE_METHODS},
            "company_id_params_using_current_company_id": current,
            "company_id_params_using_path_company_id": pathdep,
            "raw_company_id_param_count": raw_count, "raw_company_id_findings": raw,
            "raw_finding_note": RAW_COMPANY_NOTE}


def _is_ts_test(rel: str) -> bool:
    name = rel.rsplit("/", 1)[-1]
    return any(marker in name for marker in (".test.", ".spec.")) or "/__tests__/" in f"/{rel}"


# Page imports in App.tsx: named/default `import {X} from '.../pages/X'` and
# `const X = lazy(() => import('.../pages/X')...)`.
_PAGE_NAMED_IMPORT = re.compile(
    r"import\s+(?:\{([^}]*)\}|(\w+))\s+from\s*['\"][^'\"]*pages/([\w/-]+)['\"]")
_PAGE_LAZY_IMPORT = re.compile(
    r"(\w+)\s*=\s*lazy\(\s*\(\)\s*=>\s*import\(\s*['\"][^'\"]*pages/([\w/-]+)['\"]")
_ROUTE_TAG = re.compile(r"<Route\b")


def _element_blocks(text: str) -> list[str]:
    """Brace-matched contents of every element={ ... } JSX attribute (approximation)."""
    blocks = []
    for marker in re.finditer(r"element=\{", text):
        depth, i = 1, marker.end()
        while i < len(text) and depth:
            depth += (text[i] == "{") - (text[i] == "}")
            i += 1
        blocks.append(text[marker.end(): i - 1])
    return blocks


def route_facts(files, repo) -> dict:
    """Static scan of dashboard/src/App.tsx route registrations; never executed."""
    if APP_TSX not in set(files):
        return {"route_scan_files": [], "mounted_route_count": None,
                "unique_mounted_page_components": None,
                "route_scan_note": "dashboard/src/App.tsx not tracked; mounted metrics unknown."}
    text, why = _read(repo, APP_TSX)
    if text is None:
        return {"route_scan_files": [APP_TSX], "mounted_route_count": None,
                "unique_mounted_page_components": None,
                "route_scan_note": f"App.tsx unreadable ({why}); mounted metrics unknown."}
    page_modules: dict = {}
    for match in _PAGE_NAMED_IMPORT.finditer(text):
        names = [n.strip() for n in match.group(1).split(",")] if match.group(1) \
            else [match.group(2)]
        for name in names:
            if name:
                page_modules[name] = match.group(3)
    for match in _PAGE_LAZY_IMPORT.finditer(text):
        page_modules[match.group(1)] = match.group(2)
    routes = len(_ROUTE_TAG.findall(text))
    mounted: set = set()
    for block in _element_blocks(text):
        for name, module in page_modules.items():
            if re.search(rf"\b{re.escape(name)}\b", block):
                mounted.add(module)
    if routes == 0:
        return {"route_scan_files": [APP_TSX], "mounted_route_count": None,
                "unique_mounted_page_components": None,
                "route_scan_note": "No <Route> registrations found; mounted metrics unknown."}
    return {"route_scan_files": [APP_TSX], "mounted_route_count": routes,
            "unique_mounted_page_components": len(mounted),
            "route_scan_note": ("Static scan of App.tsx <Route> registrations; routes include "
                                "parameterized and layout routes, deduplicated by component.")}


def frontend_facts(files, repo, diags) -> dict:
    ts_files = [f for f in files if f.endswith((".ts", ".tsx"))]
    ts_loc = 0
    decls: set = set()
    comments: set = set()
    for rel in ts_files:
        text, why = _read(repo, rel)
        if text is None:
            diags.append({"file": rel, "error": f"skipped: {why}"})
            continue
        ts_loc += sum(1 for line in text.splitlines() if line.strip())
        if _is_ts_test(rel) or "/e2e/" in f"/{rel}":
            continue
        if MOCK_DECL.search(text):
            decls.add(rel)
        if "mock data" in text.lower():
            comments.add(rel)
    pages = [f for f in files if f.startswith(PAGES_DIR + "/") and f.endswith((".ts", ".tsx"))
             and not _is_ts_test(f)]
    unit = [f for f in ts_files if f.startswith(DASH_ROOT + "/") and _is_ts_test(f)]
    e2e = [f for f in ts_files if "/e2e/" in f"/{f}"]
    facts = {"ts_tsx_file_count": len(ts_files), "ts_tsx_loc": ts_loc, "loc_rule": LOC_RULE,
             "page_component_file_count": len(pages),
             "dashboard_unit_test_file_count": len(unit),
             "playwright_e2e_file_count": len(e2e),
             "mock_declaration_paths": sorted(decls), "mock_comment_paths": sorted(comments),
             "mock_note": "Mock findings list relative paths only, outside test and e2e files."}
    facts.update(route_facts(files, repo))
    facts["page_metrics_note"] = PAGE_NOTE
    return facts


def _decorator_name(dec) -> str:
    if isinstance(dec, ast.Call):
        dec = dec.func
    parts: list = []
    while isinstance(dec, ast.Attribute):
        parts.append(dec.attr)
        dec = dec.value
    if isinstance(dec, ast.Name):
        parts.append(dec.id)
    return ".".join(reversed(parts))


def _is_postgres_marked(tree) -> bool:
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            if any(_decorator_name(d) == "pytest.mark.postgres" for d in node.decorator_list):
                return True
        elif isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "pytestmark"
                                                  for t in node.targets):
            value = node.value
            values = value.elts if isinstance(value, ast.List | ast.Tuple) else [value]
            if any(_decorator_name(v) == "pytest.mark.postgres" for v in values):
                return True
    return False


def tests_facts(files, trees) -> dict:
    test_files = [rel for rel in files if rel.startswith("tests/") and rel.endswith(".py")
                  and rel.rsplit("/", 1)[-1].startswith("test_")]
    functions = 0
    marked: list = []
    for rel in test_files:
        tree = trees.get(rel)
        if tree is None:
            continue
        defs = [n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef | ast.AsyncFunctionDef)]
        functions += sum(1 for n in defs if n.name.startswith("test_"))
        if _is_postgres_marked(tree):
            marked.append(rel)
    return {"python_test_file_count": len(test_files),
            "static_test_function_count": functions, "parametrization_note": TEST_NOTE,
            "postgres_marked_file_count": len(marked), "postgres_marked_files": marked}


_ACTION_KINDS = ("branch", "docker", "docker_digest", "local", "major_tag", "semantic_tag",
                 "sha_pinned", "unknown")
# Source-level `uses:` detection runs beside the YAML parse so that a parser quirk can never
# silently drop a valid action line; results from both are deduplicated by file, line, value.
_USES_LINE = re.compile(r"^\s*(?:-\s*)?uses\s*:\s*(.+?)\s*(?:#.*)?$")
_USES_YAML_KEY = "uses"


def _classify_action(uses: str) -> str:
    if uses.startswith("./"):
        return "local"
    if "${{" in uses:
        return "unknown"
    if uses.startswith("docker://"):
        return "docker_digest" if re.search(r"@sha256:[0-9a-f]{6,}", uses, re.I) else "docker"
    if "@" not in uses:
        return "unknown"
    ref = uses.rsplit("@", 1)[1]
    if HEX40.match(ref):
        return "sha_pinned"
    if re.fullmatch(r"v\d+", ref):
        return "major_tag"
    if re.fullmatch(r"v?\d+\.\d+[\w.+-]*", ref):
        return "semantic_tag"
    if re.fullmatch(r"[0-9a-f]{7,39}", ref):
        return "unknown"  # abbreviated SHA: mutable, not a verified immutable pin
    return "branch"


def _uses_lines_source(text: str) -> list[tuple[int, str]]:
    found = []
    for lineno, line in enumerate(text.splitlines(), start=1):
        match = _USES_LINE.match(line)
        if not match:
            continue
        raw = match.group(1).strip()
        if raw[:1] in ("\"", "'") and len(raw) >= 2 and raw[-1:] == raw[:1]:
            raw = raw[1:-1]
        else:
            raw = raw.split()[0] if raw.split() else ""
        if raw:
            found.append((lineno, raw))
    return found


def _uses_lines_yaml(text: str) -> list[tuple[int, str]]:
    found = []
    try:
        tokens = list(yaml.scan(text))
    except yaml.YAMLError:
        return found
    for index in range(len(tokens) - 2):
        key, sep, value = tokens[index:index + 3]
        if isinstance(key, yaml.ScalarToken) and key.value == _USES_YAML_KEY \
                and isinstance(sep, yaml.ValueToken) and isinstance(value, yaml.ScalarToken) \
                and value.value:
            found.append((value.start_mark.line + 1, value.value))
    return found


def action_refs_facts(files, repo, diags) -> dict:
    wf_paths = sorted(f for f in files
                      if f.startswith(".github/workflows/") and f.endswith((".yml", ".yaml")))
    entries: dict = {}
    for rel in wf_paths:
        text, why = _read(repo, rel)
        if text is None:
            diags.append({"file": rel, "error": f"skipped: {why}"})
            continue
        detected = _uses_lines_source(text) + _uses_lines_yaml(text)
        for lineno, value in detected:
            entries[(rel, lineno, value)] = _classify_action(value)
    references = [{"file": rel, "line": lineno, "uses": value, "kind": kind}
                  for (rel, lineno, value), kind in sorted(entries.items())]
    by_kind = {kind: sum(1 for r in references if r["kind"] == kind) for kind in _ACTION_KINDS}
    return {"note": ACTION_NOTE, "by_kind": by_kind, "references": references}


def _pytest_commands(steps, rel, job_name) -> list:
    found = []
    for step in steps if isinstance(steps, list) else []:
        if not isinstance(step, dict) or not isinstance(step.get("run"), str):
            continue
        for line in step["run"].splitlines():
            tokens = line.strip().split()
            if not tokens or tokens[0] != "pytest":
                continue
            ignores = sorted(t.split("=", 1)[1].replace("\\", "/")
                             for t in tokens if t.startswith("--ignore="))
            targets = sorted(t for t in tokens[1:] if t.endswith(".py") and not t.startswith("-"))
            found.append({"workflow": rel, "job": job_name,
                          "command": " ".join(tokens)[:COMMAND_CAP], "has_dash_x": "-x" in tokens,
                          "ignore_files": ignores, "test_files": targets})
    return found


def _declared_yaml_dependency(repo, diags):
    if not (repo / "pyproject.toml").exists():
        return None  # no pyproject is normal, not a diagnostic
    text, why = _read(repo, "pyproject.toml")
    if text is None:
        diags.append({"file": "pyproject.toml", "error": f"skipped: {why}"})
        return None
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        diags.append({"file": "pyproject.toml", "error": _clean(exc, repo)})
        return None
    deps = (data.get("project") or {}).get("dependencies") or []
    names = [re.split(r"[<>=\[]", entry.lower(), maxsplit=1)[0].strip() for entry in deps]
    return next((n for n in names if n in ("pyyaml", "ruamel-yaml")), None)


def ci_facts(files, repo, marked, diags) -> dict:
    workflows: list = []
    commands: list = []
    sbom = release_wf = False
    wf_paths = sorted(f for f in files
                      if f.startswith(".github/workflows/") and f.endswith((".yml", ".yaml")))
    for rel in wf_paths:
        text, why = _read(repo, rel)
        if text is None:
            diags.append({"file": rel, "error": f"skipped: {why}"})
            continue
        try:
            data = yaml.safe_load(text)
        except yaml.YAMLError as exc:
            diags.append({"file": rel, "error": _clean(exc, repo)})
            data = None
        data = data if isinstance(data, dict) else {}
        name = str(data.get("name") or rel.rsplit("/", 1)[-1])
        jobs = data.get("jobs") if isinstance(data.get("jobs"), dict) else {}
        workflows.append({"file": rel, "name": name, "jobs": sorted(jobs)})
        low = text.lower()
        sbom = sbom or "sbom" in low or "cyclonedx" in low or "spdx" in low
        release_wf = release_wf or "release" in f"{name} {rel}".lower()
        for job_name in sorted(jobs):
            job = jobs[job_name] if isinstance(jobs[job_name], dict) else {}
            steps = job.get("steps") if isinstance(job.get("steps"), list) else []
            commands.extend(_pytest_commands(steps, rel, job_name))
    ignore = sorted({f for c in commands for f in c["ignore_files"]})
    integ = sorted({f for c in commands if "postgres" in c["job"] for f in c["test_files"]})
    marked_set = set(marked)
    split = {"ci_ignore_files": ignore, "ci_integration_files": integ,
             "static_marked_files": marked,
             "marked_not_in_ignore": sorted(marked_set - set(ignore)),
             "marked_not_in_integration": sorted(marked_set - set(integ)),
             "listed_not_marked": sorted((set(ignore) | set(integ)) - marked_set)}
    return {"workflow_file_count": len(wf_paths), "workflows": workflows,
            "action_refs": action_refs_facts(files, repo, diags),
            "pytest_commands": commands,
            "declared_yaml_dependency": _declared_yaml_dependency(repo, diags),
            "release_workflow_named": release_wf, "sbom_signal_in_workflows": sbom,
            "postgres_split": split}


def release_facts(files, repo, ci) -> dict:
    tags = _git(repo, "tag") or ""
    present = set(files)
    def has(*names):
        return any(name in present for name in names)
    return {"git_tag_count": len([t for t in tags.splitlines() if t.strip()]),
            "files_present": {"LICENSE": has("LICENSE"),
                              "SECURITY.md": has("SECURITY.md", "security.md"),
                              "CHANGELOG.md": has("CHANGELOG.md", "changelog.md"),
                              "CODEOWNERS": has("CODEOWNERS", ".github/CODEOWNERS"),
                              ".github/dependabot.yml": has(".github/dependabot.yml",
                                                            ".github/dependabot.yaml")},
            "release_workflow_present": bool(ci["release_workflow_named"]),
            "sbom_config_present": bool(ci["sbom_signal_in_workflows"])
            or any("sbom" in f.lower() for f in files)}


_NUM = r"(?:\d{1,3}(?:,\d{3})+|\d+)"
# "N" in each pattern stands in for the number-capture group _NUM. Order matters: explicit,
# unit-matched wordings come first; generic wordings after them are suppressed on a line when
# an explicit match subsumes their span. `(?!=)` keeps "table=True classes" out of the generic
# tables pattern.
_CLAIM_TABLE = (
    ("sqlmodel_table_classes", r"\b(N)\s+(?:sqlmodel\s+)?table=true\s+classes?\b",
     "sqlmodel_table_classes", "not_statically_comparable"),
    ("static_test_functions", r"\b(N)\s+static\s+test\s+functions?\b",
     "static_test_functions", "not_statically_verifiable"),
    ("page_component_files", r"\b(N)\s+page\s+component\s+files?\b",
     "page_component_files", "not_statically_comparable"),
    ("mounted_page_components", r"\b(N)\s+mounted\s+page\s+components?\b",
     "unique_mounted_page_components", "not_statically_verifiable"),
    ("mounted_routes", r"\b(N)\s+mounted\s+routes?\b",
     "mounted_route_count", "not_statically_verifiable"),
    ("mounted_pages", r"\b(N)\s+mounted\s+pages?\b",
     "unique_mounted_page_components", "not_statically_verifiable"),
    ("api_routers", r"\b(N)\s+(?:router\s+modules?|routers?)\b",
     "api_router_modules", "not_statically_comparable"),
    ("api_endpoints", r"\b(N)\s+(?:routes?|endpoints?)\b",
     "route_functions", "not_statically_comparable"),
    ("migrations", r"\b(N)\s+(?:alembic\s+)?migrations?\b",
     "alembic_migration_files", "not_statically_comparable"),
    ("database_tables", r"\b(N)\s+(?:database\s+|sqlmodel\s+|physical\s+)?tables?\b(?!=)",
     None, "not_statically_comparable"),
    ("sqlmodel_schemas", r"\b(N)\s+sqlmodel\s+schemas?\b",
     None, "not_statically_comparable"),
    ("dashboard_pages", r"\b(N)\s+(?:(?:dashboard|react|ui)\s+)*pages?\b",
     None, "not_statically_comparable"),
    ("tests", r"\b(N)\+?\s+tests?\b", None, "not_statically_verifiable"),
    ("test_scenarios", r"\b(N)\s+test\s+scenarios\b", None, "not_statically_verifiable"),
)
CLAIM_PATTERNS = tuple((name, re.compile(rx.replace("N", _NUM), re.I), metric, inc)
                       for name, rx, metric, inc in _CLAIM_TABLE)
READINESS_PATTERNS = (
    ("production_readiness", re.compile(r"production[-\s]ready|ready\s+for\s+production", re.I)),
    ("enterprise_readiness", re.compile(r"enterprise[-\s](?:ready|grade)", re.I)),
)


def _claim_status(claimed, metric, measured, incomparable_status):
    if metric is None:
        return incomparable_status, None
    value = measured.get(metric)
    if value is None:
        return "not_statically_verifiable", None  # metric exists but was not derivable
    return ("matches" if claimed == value else "stale"), value


def docs_claims_facts(files, repo, measured) -> dict:
    claims: list = []
    scanned: list = []
    missing = [rel for rel in DOC_FILES if rel not in set(files)]

    def claim(rel, lineno, text, category, claimed, value, status):
        claims.append({"file": rel, "line": lineno, "category": category, "claimed": claimed,
                       "measured": value, "status": status, "claim": text[:CLAIM_EXCERPT_CHARS]})

    for rel in DOC_FILES:
        if rel in missing:
            continue
        text, _why = _read(repo, rel)
        if text is None:
            continue
        scanned.append(rel)
        for lineno, line in enumerate(text.splitlines(), start=1):
            stripped = line.strip()
            if not stripped:
                continue
            accepted: list = []
            for category, pattern, metric, inc_status in CLAIM_PATTERNS:
                for match in pattern.finditer(stripped):
                    span = (match.start(), match.end())
                    if any(s <= span[0] and span[1] <= e for s, e in accepted):
                        continue  # a more specific claim already covers this span
                    accepted.append(span)
                    number = int(match.group(1).replace(",", ""))
                    status, value = _claim_status(number, metric, measured, inc_status)
                    claim(rel, lineno, stripped, category, number, value, status)
            for category, pattern in READINESS_PATTERNS:
                if pattern.search(stripped):
                    claim(rel, lineno, stripped, category, None, None, "subjective")
    claims.sort(key=lambda c: (c["file"], c["line"], c["category"]))
    return {"scanned_files": scanned, "missing_files": missing, "claims": claims,
            "stale_count": sum(1 for c in claims if c["status"] == "stale"),
            "status_model": STATUS_NOTE, "comparable_note": DOCS_NOTE,
            "test_claim_rule": TEST_CLAIM_NOTE, "page_claim_rule": PAGE_NOTE}


def collect(repo) -> dict:
    diags: list = []
    files = _tracked_files(repo)
    trees, loc = _scan_python(repo, files, diags)
    frontend = frontend_facts(files, repo, diags)
    database = database_facts(files, trees, diags)
    api = api_facts(trees)
    tests = tests_facts(files, trees)
    tests["dashboard_test_file_count"] = frontend["dashboard_unit_test_file_count"]
    ci = ci_facts(files, repo, tests["postgres_marked_files"], diags)
    measured = {"sqlmodel_table_classes": database["sqlmodel_table_class_count"],
                "api_router_modules": api["route_module_count"],
                "route_functions": api["route_function_count"],
                "page_component_files": frontend["page_component_file_count"],
                "mounted_route_count": frontend["mounted_route_count"],
                "unique_mounted_page_components": frontend["unique_mounted_page_components"],
                "alembic_migration_files": database["alembic_migration_file_count"],
                "static_test_functions": tests["static_test_function_count"]}
    return {"schema_version": SCHEMA_VERSION, "git": git_facts(repo),
            "backend": backend_facts(files, trees, loc), "database": database, "api": api,
            "frontend": frontend, "tests": tests, "ci": ci,
            "release": release_facts(files, repo, ci),
            "docs_claims": docs_claims_facts(files, repo, measured),
            "parse_diagnostics": sorted(diags, key=lambda d: (d["file"], d["error"]))}


def _render(value, depth, md, out):
    pad = "  " * depth
    if isinstance(value, dict):
        for key in sorted(value):
            item = value[key]
            label = f"**{key}**" if md else key
            if isinstance(item, dict | list) and item:
                out.append(f"{pad}{label}:")
                _render(item, depth + 1, md, out)
            elif isinstance(item, list):
                out.append(f"{pad}{label}: []")
            else:
                text = "null" if item is None else str(item).replace("\n", " ")
                out.append(f"{pad}{label}: {text}")
    elif isinstance(value, list):
        for item in value:
            if isinstance(item, dict):
                inner = ", ".join(f"{key}={item[key]}" for key in sorted(item))
                out.append(f"{pad}- {inner}")
            else:
                out.append(f"{pad}- {item}")
    else:
        out.append(f"{pad}{value}")


def render(report, md=False) -> str:
    """Deterministic full-tree rendering; JSON is the canonical machine format."""
    title = "NEXUS Project Facts" if md else "NEXUS project facts"
    out = [f"# {title} (schema version {SCHEMA_VERSION})" if md
           else f"{title} (schema version {SCHEMA_VERSION})", ""]
    _render(report, 0 if md else 1, md, out)
    return "\n".join(out).rstrip() + "\n"


def _resolve_output(raw, overwrite):
    """Resolve an output path inside the current directory, refusing escapes."""
    root = Path.cwd().resolve()
    candidate = Path(raw)
    candidate = candidate if candidate.is_absolute() else root / candidate
    absolute = os.path.normpath(str(candidate))
    root_case, norm_case = os.path.normcase(str(root)), os.path.normcase(absolute)
    if norm_case != root_case and not norm_case.startswith(root_case + os.sep):
        raise AuditError(f"output path escapes the current directory: {raw}")
    try:
        parts = Path(absolute).relative_to(root).parts
    except ValueError as exc:
        raise AuditError(f"output path escapes the current directory: {raw}") from exc
    current = root
    for part in parts:
        current = current / part
        if current.is_symlink():
            raise AuditError(f"refusing to write through a symlink: {part}")
    if Path(absolute).is_dir():
        raise AuditError(f"output path is a directory: {raw}")
    if Path(absolute).exists() and not overwrite:
        raise AuditError(f"output file exists; pass --overwrite to replace it: {raw}")
    return Path(absolute)


def _write_output(raw, content, overwrite) -> None:
    target = _resolve_output(raw, overwrite)
    with open(target, "w" if overwrite else "x", encoding="utf-8", newline="\n") as handle:
        handle.write(content)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Read-only project-facts and documentation-drift auditor.")
    parser.add_argument("--repo", default=".", help="repository to audit (default: cwd)")
    parser.add_argument("--json", metavar="PATH", help="write the JSON report to PATH")
    parser.add_argument("--markdown", metavar="PATH", help="write the Markdown report to PATH")
    parser.add_argument("--check-docs", action="store_true",
                        help="exit 1 when objectively stale doc claims exist")
    parser.add_argument("--overwrite", action="store_true", help="replace an existing output file")
    args = parser.parse_args(argv)
    repo = Path(args.repo).resolve()
    if not repo.is_dir():
        print(f"error: repository directory not found: {args.repo}", file=sys.stderr)
        return 2
    report = collect(repo)
    if args.json:
        _write_output(args.json, json.dumps(report, indent=2, sort_keys=True) + "\n",
                      args.overwrite)
    if args.markdown:
        _write_output(args.markdown, render(report, md=True), args.overwrite)
    print(render(report))
    if args.check_docs:
        return 1 if report["docs_claims"]["stale_count"] else 0
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except AuditError as error:
        print(f"error: {error}", file=sys.stderr)
        sys.exit(2)
