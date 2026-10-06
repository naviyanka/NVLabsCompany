"""Deterministic tests for scripts/project_facts.py (read-only project-facts auditor).

Every test builds a throwaway repository under tmp_path and points the auditor at it, so no
fixture ever touches src/nexus, the primary checkout, or the network (the single real-
repository test only reads workflow files from the PR checkout). The auditor itself is
loaded by path (scripts/ is not a package), following the convention in test_arch_guard.py;
the module is registered in sys.modules before exec_module per the repo convention.

Coverage: the original 40 auditor areas plus the correction set - runtime test-total
claims are never compared with the static function count, generic table/page claims are
never compared with class/file counts, App.tsx route metrics are scanned statically, and
GitHub action references carry per-file/line provenance with full classification.
"""

import ast
import importlib.util
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT_PATH = REPO_ROOT / "scripts" / "project_facts.py"


def _load_script():
    spec = importlib.util.spec_from_file_location("project_facts", SCRIPT_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["project_facts"] = module
    spec.loader.exec_module(module)
    return module


pf = _load_script()


def _git(root: Path, *args: str) -> str:
    proc = subprocess.run(
        ["git", "-C", str(root), "-c", "user.email=audit@example.test",
         "-c", "user.name=auditor", "-c", "commit.gpgsign=false", *args],
        check=True, capture_output=True, text=True,
    )
    return proc.stdout


def make_repo(tmp_path: Path, files: dict, commit: bool = True) -> Path:
    root = tmp_path / "repo"
    for rel, content in files.items():
        target = root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content if isinstance(content, bytes) else content.encode("utf-8"))
    if commit:
        _git(root, "init", "-q", "-b", "main")
        _git(root, "add", "-A")
        _git(root, "commit", "-q", "-m", "init")
    return root


def collect(root: Path) -> dict:
    return pf.collect(root)


def dump(report: dict) -> str:
    return json.dumps(report, sort_keys=True)


def claims_for(root: Path, needle: str) -> list:
    return [c for c in collect(root)["docs_claims"]["claims"] if needle in c["claim"]]


def model_src(class_names: list, tablename: str | None = None) -> str:
    extra = f'\n    __tablename__ = "{tablename}"\n' if tablename else ""
    body = "from sqlmodel import SQLModel\n"
    for name in class_names:
        body += f"\n\nclass {name}(SQLModel, table=True):{extra}\n    id: int = 0\n"
    return body


def migration(rev: str, down) -> str:
    if down is None:
        down_src = "None"
    elif isinstance(down, tuple):
        down_src = "(" + ", ".join(f'"{d}"' for d in down) + ")"
    else:
        down_src = f'"{down}"'
    return f'"""m"""\nrevision: str = "{rev}"\ndown_revision: str | None = {down_src}\n'


ROUTE_IMPORTS = ("from fastapi import APIRouter\n"
                 "from nexus.api.deps import CurrentCompanyId, PathCompanyId\n"
                 "router = APIRouter()\n")

_PG_MARKED = "import pytest\npytestmark = pytest.mark.postgres\n\n\ndef test_x():\n    pass\n"
_PG_SLOW = "import pytest\npytestmark = pytest.mark.slow\n\n\ndef test_w():\n    pass\n"


def doc_repo(tmp_path: Path, readme: str, model: str | None = None) -> Path:
    """A repo whose model classes back the table-claim comparisons."""
    files = {"README.md": readme,
             "src/nexus/models/thing.py": model or model_src(["Thing", "Other"])}
    return make_repo(tmp_path, files)


def app_tsx(pages: list, route_body: str, lazy_page: str | None = None) -> str:
    imports = "".join(f"import {{ {p} }} from '@/pages/{p}';\n" for p in pages)
    lazy = f"const Lazy{lazy_page} = lazy(() => import('@/pages/{lazy_page}'));\n" \
        if lazy_page else ""
    return (imports + lazy + "import { Routes, Route } from 'react-router-dom';\n\n"
            "export default function App() {\n  return (\n    <Routes>\n"
            + route_body + "    </Routes>\n  );\n}\n")


def route_repo(tmp_path: Path, pages: list, route_body: str, lazy_page: str | None = None) -> dict:
    files = {f"dashboard/src/pages/{p}.tsx": "export default null\n" for p in pages}
    files["dashboard/src/App.tsx"] = app_tsx(pages, route_body, lazy_page)
    return collect(make_repo(tmp_path, files))["frontend"]


def action_repo(tmp_path: Path, content: str, name: str = "ci.yml") -> dict:
    files = {f".github/workflows/{name}": content}
    root = make_repo(tmp_path / f"repo_{name.replace('.', '_')}", files)
    return pf.action_refs_facts(pf._tracked_files(root), root, [])


def ref_entry(refs: dict, uses_value: str) -> dict:
    matches = [r for r in refs["references"] if r["uses"] == uses_value]
    assert matches, f"missing reference {uses_value!r} in {refs['references']}"
    return matches[0]


# 1. Stable output ordering ---

def test_output_ordering_is_stable(tmp_path):
    files = {"src/nexus/zeta.py": "a = 1\n", "src/nexus/alpha.py": "b = 2\n",
             "src/nexus/mid/beta.py": "c = 3\n", "README.md": "# r\n"}
    root = make_repo(tmp_path, files)
    first, second = collect(root), collect(root)
    assert dump(first) == dump(second)
    assert first["backend"]["top_level_directories"] == sorted(
        first["backend"]["top_level_directories"])
    assert first["git"]["tracked_dirty_paths"] == sorted(first["git"]["tracked_dirty_paths"])


# 2. Python file and LOC counts ---

def test_python_file_and_loc_counts(tmp_path):
    files = {"src/nexus/__init__.py": "",
             "src/nexus/a.py": "x = 1\n\n# a comment is a non-blank line\ny = 2\n\n",
             "src/nexus/pkg/b.py": "z = 3\n",
             "outside.py": "q = 1\n"}
    backend = collect(make_repo(tmp_path, files))["backend"]
    assert backend["python_file_count"] == 3
    assert backend["python_loc"] == 4  # non-blank lines: a.py 3 + pkg/b.py 1
    assert backend["loc_rule"] == pf.LOC_RULE
    assert backend["top_level_directory_count"] == 1
    assert backend["top_level_directories"] == ["pkg"]


# 3-4. SQLModel table=True detection ---

def test_sqlmodel_table_detection(tmp_path):
    src = ("from sqlmodel import SQLModel\n\n\n"
           "class Plain(SQLModel):\n    id: int = 0\n\n\n"
           "class Real(SQLModel, table=True):\n    id: int = 0\n\n\n"
           "class Also(SQLModel, table=True):\n    id: int = 0\n")
    database = collect(make_repo(tmp_path, {"src/nexus/models/t.py": src}))["database"]
    assert database["sqlmodel_table_class_count"] == 2
    assert "not a physical-table count" in database["physical_table_note"]


def test_table_true_in_comments_and_strings_ignored(tmp_path):
    src = ("from sqlmodel import SQLModel\n"
           "# class Commented(SQLModel, table=True):\n"
           'DOC = """\nclass InString(SQLModel, table=True):\n    pass\n"""\n'
           'NOISE = "table=True"\n\n\n'
           "class Real(SQLModel, table=True):\n    id: int = 0\n")
    database = collect(make_repo(tmp_path, {"src/nexus/models/t.py": src}))["database"]
    assert database["sqlmodel_table_class_count"] == 1


# 5-9. Alembic graph ---

def test_alembic_single_head(tmp_path):
    files = {"alembic/versions/a.py": migration("a", None),
             "alembic/versions/b.py": migration("b", "a"),
             "alembic/versions/c.py": migration("c", "b")}
    db = collect(make_repo(tmp_path, files))["database"]
    assert db["migration_directory"] == "alembic/versions"
    assert db["revision_count"] == 3 and db["revision_ids"] == ["a", "b", "c"]
    assert db["heads"] == ["c"]
    assert db["branch_points"] == [] and db["cycles"] == []
    assert db["dangling_down_revisions"] == []


def test_alembic_multiple_heads(tmp_path):
    files = {"alembic/versions/a.py": migration("a", None),
             "alembic/versions/b.py": migration("b", "a"),
             "alembic/versions/c.py": migration("c", None)}
    assert collect(make_repo(tmp_path, files))["database"]["heads"] == ["b", "c"]


def test_alembic_branch_point(tmp_path):
    files = {"alembic/versions/a.py": migration("a", None),
             "alembic/versions/b.py": migration("b", "a"),
             "alembic/versions/c.py": migration("c", "a")}
    db = collect(make_repo(tmp_path, files))["database"]
    assert db["branch_points"] == ["a"]
    assert db["heads"] == ["b", "c"]


def test_alembic_revision_cycle(tmp_path):
    files = {"alembic/versions/a.py": migration("a", "b"),
             "alembic/versions/b.py": migration("b", "a")}
    cycles = collect(make_repo(tmp_path, files))["database"]["cycles"]
    assert len(cycles) == 1
    assert set(cycles[0][:2]) == {"a", "b"}


def test_alembic_missing_down_revision(tmp_path):
    files = {"alembic/versions/a.py": migration("a", None),
             "alembic/versions/b.py": migration("b", "ghost")}
    db = collect(make_repo(tmp_path, files))["database"]
    assert {"file": "alembic/versions/b.py", "down_revision": "ghost"} in db[
        "dangling_down_revisions"]
    assert db["heads"] == ["a", "b"]  # nothing descends from a or b


# 10-11. Route detection ---

def test_route_function_detection(tmp_path):
    routed = (ROUTE_IMPORTS +
              '\n\n@router.get("/api/v1/agents")\nasync def list_agents():\n    return []\n')
    files = {"src/nexus/api/routes/agents.py": routed,
             "src/nexus/api/deps.py": "def h():\n    return None\n"}
    api = collect(make_repo(tmp_path, files))["api"]
    assert api["route_module_count"] == 1
    assert api["route_function_count"] == 1


def test_http_method_counts(tmp_path):
    src = (ROUTE_IMPORTS + '\n\n@router.get("/a")\nasync def ga():\n    return None\n\n\n'
           '@router.get("/b")\nasync def gb():\n    return None\n\n\n'
           '@router.post("/c")\nasync def pc():\n    return None\n\n\n'
           '@router.delete("/d")\nasync def dd():\n    return None\n\n\n'
           '@router.patch("/e")\nasync def pe():\n    return None\n')
    methods = collect(make_repo(tmp_path, {"src/nexus/api/routes/x.py": src}))["api"][
        "routes_by_method"]
    assert methods["get"] == 2 and methods["post"] == 1
    assert methods["delete"] == 1 and methods["patch"] == 1 and methods["put"] == 0


# 12-14. company_id parameter forms ---

def test_current_company_id_detection(tmp_path):
    src = (ROUTE_IMPORTS +
           '\n\n@router.get("/api/v1/budgets")\n'
           "async def get_budget(company_id: CurrentCompanyId):\n    return None\n")
    api = collect(make_repo(tmp_path, {"src/nexus/api/routes/budgets.py": src}))["api"]
    assert api["company_id_params_using_current_company_id"] == 1
    assert api["company_id_params_using_path_company_id"] == 0
    assert api["raw_company_id_param_count"] == 0


def test_path_company_id_detection(tmp_path):
    src = (ROUTE_IMPORTS +
           '\n\n@router.get("/api/v1/companies/{company_id}/keys")\n'
           "async def list_keys(company_id: PathCompanyId):\n    return None\n")
    api = collect(make_repo(tmp_path, {"src/nexus/api/routes/keys.py": src}))["api"]
    assert api["company_id_params_using_path_company_id"] == 1
    assert api["raw_company_id_param_count"] == 0


def test_raw_company_id_audit_signal(tmp_path):
    src = (ROUTE_IMPORTS +
           '\n\n@router.post("/api/v1/companies/{company_id}/agents")\n'
           "async def create_agent(company_id: uuid.UUID, body: dict):\n    return None\n")
    api = collect(make_repo(tmp_path, {"src/nexus/api/routes/agents.py": src}))["api"]
    assert api["raw_company_id_param_count"] == 1
    assert api["raw_company_id_findings"] == [{"file": "src/nexus/api/routes/agents.py",
                                               "function": "create_agent"}]
    assert "not proof of a vulnerability" in api["raw_finding_note"]


# 15-16. Frontend ---

def test_frontend_page_counting(tmp_path):
    files = {"dashboard/src/pages/A.tsx": "export default null\n",
             "dashboard/src/pages/B.tsx": "export default null\n",
             "dashboard/src/pages/__tests__/A.test.tsx": "test('a', () => {});\n",
             "dashboard/src/components/C.tsx": "export const C = () => null\n"}
    frontend = collect(make_repo(tmp_path, files))["frontend"]
    assert frontend["page_component_file_count"] == 2  # test files under pages/ are not pages
    assert frontend["dashboard_unit_test_file_count"] == 1
    assert frontend["mounted_route_count"] is None  # no App.tsx: mounted metrics unknown


def test_mock_detection_outside_tests(tmp_path):
    files = {"dashboard/src/pages/Tasks.tsx": "export const MOCK_TASKS = []\n// mock data only\n",
             "dashboard/src/pages/Tasks.test.ts": "export const MOCK_TASKS = []\n",
             "dashboard/src/lib/api.ts": "export const API_URL = '/api'\n"}
    frontend = collect(make_repo(tmp_path, files))["frontend"]
    assert frontend["mock_declaration_paths"] == ["dashboard/src/pages/Tasks.tsx"]
    assert frontend["mock_comment_paths"] == ["dashboard/src/pages/Tasks.tsx"]


# 17-18. Python tests ---

def test_test_function_count_without_parametrize_expansion(tmp_path):
    src = ("import pytest\n\n\n"
           '@pytest.mark.parametrize("n", [1, 2, 3])\ndef test_n(n):\n    assert n\n\n\n'
           "def test_other():\n    pass\n\n\n"
           "class TestGroup:\n    def test_member(self):\n        pass\n")
    tests = collect(make_repo(tmp_path, {"tests/test_a.py": src}))["tests"]
    assert tests["python_test_file_count"] == 1
    assert tests["static_test_function_count"] == 3  # parametrization is not expanded
    assert "parametrization" in tests["parametrization_note"].lower()


def test_postgres_marker_detection(tmp_path):
    files = {"tests/test_pg_module.py": _PG_MARKED,
             "tests/test_pg_decorator.py":
                 "import pytest\n\n\n@pytest.mark.postgres\ndef test_y():\n    pass\n",
             "tests/test_other_marker.py": _PG_SLOW,
             "tests/test_plain.py": "def test_z():\n    pass\n"}
    tests = collect(make_repo(tmp_path, files))["tests"]
    assert tests["postgres_marked_files"] == ["tests/test_pg_decorator.py",
                                              "tests/test_pg_module.py"]
    assert tests["postgres_marked_file_count"] == 2


# 19. CI Postgres split agreement ---

def test_workflow_postgres_split_agreement(tmp_path):
    files = {"tests/test_pg_module.py": _PG_MARKED,
             ".github/workflows/test.yml": (
                 "name: Tests\n"
                 "jobs:\n"
                 "  backend:\n"
                 "    steps:\n"
                 "      - run: pytest tests/ --ignore=tests/test_pg_module.py -x -q\n"
                 "  postgres-integration:\n"
                 "    steps:\n"
                 "      - run: pytest tests/test_pg_module.py -v\n"
             )}
    report = collect(make_repo(tmp_path, files))
    ci, split = report["ci"], report["ci"]["postgres_split"]
    assert ci["workflow_file_count"] == 1
    assert ci["workflows"] == [{"file": ".github/workflows/test.yml", "name": "Tests",
                                "jobs": ["backend", "postgres-integration"]}]
    assert split["ci_ignore_files"] == ["tests/test_pg_module.py"]
    assert split["ci_integration_files"] == ["tests/test_pg_module.py"]
    assert split["static_marked_files"] == ["tests/test_pg_module.py"]
    assert split["marked_not_in_ignore"] == []
    assert split["marked_not_in_integration"] == []
    assert split["listed_not_marked"] == []
    backend_cmd = [c for c in ci["pytest_commands"] if c["job"] == "backend"][0]
    assert backend_cmd["has_dash_x"] is True


# 20-21. Action reference classification ---

def test_mutable_action_reference_detection(tmp_path):
    wf = "name: CI\njobs:\n  build:\n    steps:\n      - uses: actions/checkout@main\n"
    refs = action_repo(tmp_path, wf)
    entry = ref_entry(refs, "actions/checkout@main")
    assert entry["kind"] == "branch"
    assert refs["by_kind"]["branch"] == 1
    assert refs["by_kind"]["sha_pinned"] == 0
    assert "mutable" in refs["note"].lower()


def test_major_tag_action_reference_not_immutable(tmp_path):
    wf = "name: CI\njobs:\n  build:\n    steps:\n      - uses: actions/checkout@v4\n"
    refs = action_repo(tmp_path, wf)
    assert ref_entry(refs, "actions/checkout@v4")["kind"] == "major_tag"
    assert refs["by_kind"]["sha_pinned"] == 0
    assert "mutable" in refs["note"].lower()


# 22. Release hygiene ---

def test_release_hygiene_presence_and_tags(tmp_path):
    files = {"LICENSE": "MIT\n", "SECURITY.md": "x\n", "CHANGELOG.md": "x\n",
             ".github/CODEOWNERS": "* @team\n", ".github/dependabot.yml": "x\n",
             ".github/workflows/release.yml": "name: Release\njobs:\n  publish:\n    steps: []\n",
             "README.md": "x\n"}
    root = make_repo(tmp_path, files)
    _git(root, "tag", "v1.0.0")
    release = collect(root)["release"]
    assert release["git_tag_count"] == 1
    assert release["files_present"]["LICENSE"] is True
    assert release["files_present"]["CODEOWNERS"] is True
    assert release["files_present"][".github/dependabot.yml"] is True
    assert release["release_workflow_present"] is True
    assert release["sbom_config_present"] is False
    bare = collect(make_repo(tmp_path / "bare", {"README.md": "x\n"}))["release"]
    assert bare["files_present"]["SECURITY.md"] is False
    assert bare["release_workflow_present"] is False


# 23-26. Documentation claims ---

def test_doc_claim_match(tmp_path):
    row = claims_for(doc_repo(tmp_path, "The schema has 2 SQLModel table=True classes.\n"),
                     "SQLModel table=True classes")[0]
    assert (row["claimed"], row["measured"], row["status"]) == (2, 2, "matches")


def test_doc_claim_stale(tmp_path):
    docs = collect(doc_repo(tmp_path, "There are 9 static test functions in the suite.\n"))[
        "docs_claims"]
    assert docs["stale_count"] == 1
    assert docs["claims"][0]["status"] == "stale"


def test_doc_claim_unverifiable(tmp_path):
    row = claims_for(doc_repo(tmp_path, "There are 40 test scenarios covered.\n"),
                     "40 test scenarios")[0]
    assert row["status"] == "not_statically_verifiable"
    assert row["measured"] is None


def test_subjective_readiness_claim(tmp_path):
    docs = collect(doc_repo(tmp_path, "NEXUS is enterprise-grade and production-ready.\n"))[
        "docs_claims"]
    assert [c["status"] for c in docs["claims"]] == ["subjective", "subjective"]
    assert docs["stale_count"] == 0


# 27. --check-docs exit behavior ---

def test_check_docs_exit_behavior(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    matching = doc_repo(tmp_path / "c", "The schema has 2 SQLModel table=True classes.\n")
    assert pf.main(["--repo", str(matching), "--check-docs"]) == 0
    stale = doc_repo(tmp_path / "s", "There are 9 static test functions in the suite.\n")
    assert pf.main(["--repo", str(stale), "--check-docs"]) == 1
    subjective = doc_repo(tmp_path / "j", "NEXUS is enterprise-grade.\n")
    assert pf.main(["--repo", str(subjective), "--check-docs"]) == 0


# 28-29. Schema and deterministic rendering ---

def test_json_schema_and_deterministic_ordering(tmp_path):
    root = make_repo(tmp_path, {"README.md": "# x\n", "src/nexus/a.py": "x = 1\n"})
    report = collect(root)
    assert report["schema_version"] == 2
    assert {"api", "backend", "ci", "database", "docs_claims", "frontend", "git",
            "parse_diagnostics", "release", "schema_version", "tests"} <= set(report)
    assert dump(report) == dump(collect(root))
    rendered = json.dumps(report, indent=2, sort_keys=True)
    assert rendered == json.dumps(json.loads(rendered), indent=2, sort_keys=True)


def test_markdown_determinism(tmp_path):
    root = make_repo(tmp_path, {"README.md": "# x\n", "src/nexus/a.py": "x = 1\n"})
    report = collect(root)
    assert pf.render(report, md=True) == pf.render(collect(root), md=True)
    assert pf.render(report, md=True).startswith("# NEXUS Project Facts")
    assert pf.render(report).startswith("NEXUS project facts")


# 30-31. Output file modes ---

def test_exclusive_output_creation(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    root = make_repo(tmp_path / "r", {"README.md": "# x\n"})
    assert pf.main(["--repo", str(root), "--json", "out.json"]) == 0
    first = (tmp_path / "out.json").read_text(encoding="utf-8")
    with pytest.raises(pf.AuditError):
        pf.main(["--repo", str(root), "--json", "out.json"])
    assert (tmp_path / "out.json").read_text(encoding="utf-8") == first


def test_explicit_overwrite(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    root = make_repo(tmp_path / "r", {"README.md": "# x\n"})
    assert pf.main(["--repo", str(root), "--json", "out.json"]) == 0
    (tmp_path / "out.json").write_text("junk", encoding="utf-8")
    assert pf.main(["--repo", str(root), "--json", "out.json", "--overwrite"]) == 0
    assert (tmp_path / "out.json").read_text(encoding="utf-8") != "junk"


# 32. Path safety ---

def test_symlink_and_traversal_escape_refusal(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    root = make_repo(tmp_path / "r", {"README.md": "# x\n"})
    with pytest.raises(pf.AuditError, match="escapes"):
        pf.main(["--repo", str(root), "--json", "../escape.json"])
    try:
        (tmp_path / "outside-target").mkdir()
        os.symlink(tmp_path / "outside-target", tmp_path / "link", target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("symlink creation unavailable on this platform")
    with pytest.raises(pf.AuditError, match="symlink"):
        pf.main(["--repo", str(root), "--json", "link/out.json"])


# 33-34. Output hygiene ---

def test_no_absolute_paths_in_outputs(tmp_path):
    root = make_repo(tmp_path, {"README.md": "# x\n", "src/nexus/bad.py": "def (:\n"})
    report = collect(root)
    assert report["parse_diagnostics"][0]["file"] == "src/nexus/bad.py"
    for text in (dump(report), pf.render(report), pf.render(report, md=True)):
        assert str(tmp_path) not in text
        assert not re.search(r"[A-Za-z]:\\", text)


def test_no_environment_values_in_outputs(tmp_path, monkeypatch):
    monkeypatch.setenv("NEXUS_AUDIT_CANARY", "canary-secret-value-123")
    root = make_repo(tmp_path, {"README.md": "# x\n"})
    for text in (dump(collect(root)), pf.render(collect(root)), pf.render(collect(root), md=True)):
        assert "canary-secret-value-123" not in text
        assert "NEXUS_AUDIT_CANARY" not in text


# 35. Git state ---

def test_git_dirty_state_names_only(tmp_path):
    root = make_repo(tmp_path, {"tracked.txt": "original-sensitive-content\n"})
    (root / "tracked.txt").write_text("modified-sensitive-content\n", encoding="utf-8")
    (root / "untracked.txt").write_text("untracked-sensitive-content\n", encoding="utf-8")
    git_facts = collect(root)["git"]
    assert git_facts["available"] is True
    assert re.fullmatch(r"[0-9a-f]{40}", git_facts["commit_sha"])
    assert git_facts["branch"] == "main"
    assert git_facts["dirty"] is True
    assert git_facts["tracked_dirty_paths"] == ["tracked.txt"]
    blob = dump(collect(root))
    assert "sensitive-content" not in blob
    assert "untracked.txt" not in blob  # untracked names are not in the tracked path list


# 36. Binary and oversized handling ---

def test_binary_and_oversized_files_skipped(tmp_path, monkeypatch):
    monkeypatch.setattr(pf, "MAX_FILE_BYTES", 200)
    files = {"src/nexus/big.py": "x = 1\n" * 100, "src/nexus/blob.py": b"a = 1\x00b = 2\n"}
    report = collect(make_repo(tmp_path, files))
    diags = {d["file"]: d["error"] for d in report["parse_diagnostics"]}
    assert diags["src/nexus/big.py"] == "skipped: oversized"
    assert diags["src/nexus/blob.py"] == "skipped: binary"
    assert report["backend"]["python_file_count"] == 2  # still tracked files
    assert report["backend"]["python_loc"] == 0  # skipped contents contribute no LOC


# 37-39. Static self-restraints ---

def _script_import_roots() -> set:
    roots = set()
    for node in ast.walk(ast.parse(SCRIPT_PATH.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            roots.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            roots.add((node.module or "").split(".")[0])
    return roots


def test_no_application_imports(tmp_path):
    roots = _script_import_roots()
    assert "nexus" not in roots
    assert not any(name.startswith("src") for name in roots)
    before = set(sys.modules)
    collect(make_repo(tmp_path, {"README.md": "# x\n"}))
    assert "nexus" not in set(sys.modules) - before


def test_no_network_imports():
    banned = {"socket", "ssl", "urllib", "http", "httpx", "requests", "aiohttp", "smtplib",
              "ftplib", "telnetlib"}
    assert not _script_import_roots() & banned


def test_no_shell_execution():
    source = SCRIPT_PATH.read_text(encoding="utf-8")
    assert "shell=True" not in source
    assert "os.system" not in source
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Call):
            for keyword in node.keywords:
                assert keyword.arg != "shell"


# 40. Malformed inputs ---

def test_malformed_files_sanitized_diagnostic(tmp_path):
    files = {"src/nexus/bad.py": "def (:\n",
             "pyproject.toml": "=[broken\n",
             ".github/workflows/wf.yml": "name: [unclosed\n"}
    root = make_repo(tmp_path, files)
    report = collect(root)
    diags = {d["file"]: d["error"] for d in report["parse_diagnostics"]}
    assert diags["src/nexus/bad.py"].startswith("SyntaxError")
    assert diags["pyproject.toml"].startswith("TOMLDecodeError")
    assert "Error" in diags[".github/workflows/wf.yml"]
    for message in diags.values():
        assert str(tmp_path) not in message  # diagnostics stay repository-relative
    assert pf.main(["--repo", str(root)]) == 0


# ---- Correction 1: runtime test totals are never compared with static counts ---------------

def test_runtime_test_total_claim_not_verifiable(tmp_path):
    row = claims_for(doc_repo(tmp_path, "3,109 tests passed in CI.\n"), "3,109 tests passed")[0]
    assert row["status"] == "not_statically_verifiable"
    assert row["measured"] is None


def test_tests_passing_ratio_claim_not_verifiable(tmp_path):
    row = claims_for(doc_repo(tmp_path, "3,109 / 3,109 tests passing cleanly.\n"),
                     "3,109 / 3,109 tests passing")[0]
    assert row["status"] == "not_statically_verifiable"
    assert row["measured"] is None


def test_tests_plus_floor_claim_not_verifiable(tmp_path):
    row = claims_for(doc_repo(tmp_path, "Pytest (3,232+ tests) runs on every push.\n"),
                     "3,232+ tests")[0]
    assert row["status"] == "not_statically_verifiable"
    assert row["measured"] is None


def test_static_test_function_claim_is_comparable(tmp_path):
    src = "def test_a():\n    pass\n\n\ndef test_b():\n    pass\n"
    root = make_repo(tmp_path, {"tests/test_a.py": src,
                                "README.md": "The suite defines 2 static test functions.\n"
                                             "Docs once claimed 9 static test functions.\n"})
    claims = collect(root)["docs_claims"]["claims"]
    statuses = {c["claimed"]: c["status"] for c in claims
                if c["category"] == "static_test_functions"}
    assert statuses == {2: "matches", 9: "stale"}


def test_parametrize_proves_static_count_not_collected(tmp_path):
    src = 'import pytest\n\n\n@pytest.mark.parametrize("n", [1, 2, 3])\ndef test_n(n):\n    pass\n'
    root = make_repo(tmp_path, {"tests/test_a.py": src, "README.md": "It runs 300 tests.\n"})
    report = collect(root)
    assert report["tests"]["static_test_function_count"] == 1  # one function, many items
    row = claims_for(root, "300 tests")[0]
    assert row["status"] == "not_statically_verifiable"


def test_check_docs_ignores_runtime_test_totals(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    root = doc_repo(tmp_path / "r", "3,109 tests passed in CI.\n")
    assert pf.main(["--repo", str(root), "--check-docs"]) == 0


def test_json_distinguishes_static_counts_from_runtime_claims(tmp_path):
    root = doc_repo(tmp_path, "3,109 tests passed in CI.\n")
    report = collect(root)
    assert "static_test_function_count" in report["tests"]
    row = claims_for(root, "3,109 tests passed")[0]
    assert row["claimed"] == 3109 and row["measured"] is None
    assert row["status"] == "not_statically_verifiable"


# ---- Correction 2: table claims are only comparable in explicit class wording --------------

def test_generic_table_claim_not_compared(tmp_path):
    row = claims_for(doc_repo(tmp_path, "The schema has 69 database tables.\n"),
                     "69 database tables")[0]
    assert row["status"] == "not_statically_comparable"
    assert row["measured"] is None


def test_explicit_table_class_claim_matches(tmp_path):
    row = claims_for(doc_repo(tmp_path, "The schema has 2 SQLModel table=True classes.\n"),
                     "SQLModel table=True classes")[0]
    assert row["status"] == "matches" and row["measured"] == 2


def test_shared_tablename_classes_not_two_physical_tables(tmp_path):
    src = model_src(["A", "B"], tablename="shared_table")
    root = make_repo(tmp_path, {"src/nexus/models/t.py": src,
                                "README.md": "The schema has 2 database tables.\n"})
    database = collect(root)["database"]
    assert database["sqlmodel_table_class_count"] == 2  # two classes, by definition of the metric
    row = claims_for(root, "2 database tables")[0]
    assert row["status"] == "not_statically_comparable"  # never proof of two physical tables


def test_link_models_do_not_inflate_physical_claims(tmp_path):
    src = ("from sqlmodel import SQLModel\n\n\n"
           "class TaskLink(SQLModel, table=True):\n    task_id: int = 0\n\n\n"
           "class Real(SQLModel, table=True):\n    id: int = 0\n")
    root = make_repo(tmp_path, {"src/nexus/models/t.py": src,
                                "README.md": "There are 2 physical tables and "
                                             "2 SQLModel table=True classes.\n"})
    claims = collect(root)["docs_claims"]["claims"]
    by_cat = {c["category"]: c for c in claims}
    assert by_cat["database_tables"]["status"] == "not_statically_comparable"
    assert by_cat["sqlmodel_table_classes"]["status"] == "matches"  # link models count as classes


def test_check_docs_ignores_generic_table_claim(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    root = doc_repo(tmp_path / "r", "The schema has 69 database tables.\n")
    assert pf.main(["--repo", str(root), "--check-docs"]) == 0


# ---- Correction 3: page claims need a semantically matching metric --------------------------

def test_page_files_vs_mounted_components(tmp_path):
    frontend = route_repo(tmp_path, ["A", "B", "C"],
                          '      <Route path="/a" element={<A />} />\n'
                          '      <Route path="/b" element={<B />} />\n')
    assert frontend["page_component_file_count"] == 3
    assert frontend["mounted_route_count"] == 2
    assert frontend["unique_mounted_page_components"] == 2  # C is never mounted


def test_two_routes_one_component(tmp_path):
    frontend = route_repo(tmp_path, ["A"],
                          '      <Route path="/a" element={<A />} />\n'
                          '      <Route path="/overview" element={<A />} />\n')
    assert frontend["mounted_route_count"] == 2
    assert frontend["unique_mounted_page_components"] == 1


def test_parameterized_route_counts(tmp_path):
    frontend = route_repo(tmp_path, ["A"],
                          '      <Route path="/a/:id" element={<A />} />\n')
    assert frontend["mounted_route_count"] == 1  # a parameterized route is one route
    assert frontend["unique_mounted_page_components"] == 1


def test_lazy_route_detected(tmp_path):
    body = ('      <Route path="/office" element={'
            '<Suspense fallback={null}><LazyOffice /></Suspense>} />\n')
    frontend = route_repo(tmp_path, ["Office"], body, lazy_page="Office")
    assert frontend["mounted_route_count"] == 1
    assert frontend["unique_mounted_page_components"] == 1
    assert frontend["route_scan_files"] == ["dashboard/src/App.tsx"]


def test_unmounted_page_excluded_from_mounted_count(tmp_path):
    frontend = route_repo(tmp_path, ["A", "Orphan"],
                          '      <Route path="/a" element={<A />} />\n')
    assert frontend["page_component_file_count"] == 2
    assert frontend["unique_mounted_page_components"] == 1


def test_test_files_under_pages_excluded(tmp_path):
    frontend = route_repo(tmp_path, ["A", "B"],
                          '      <Route path="/a" element={<A />} />\n')
    assert frontend["page_component_file_count"] == 2
    assert frontend["mounted_route_count"] == 1


def test_page_component_files_wording_compares(tmp_path):
    files = {"dashboard/src/pages/A.tsx": "x\n", "dashboard/src/pages/B.tsx": "x\n",
             "dashboard/src/pages/C.tsx": "x\n",
             "dashboard/src/App.tsx": app_tsx(["A"], '      <Route path="/a" element={<A />} />\n'),
             "README.md": "There are 3 page component files today.\n"}
    root = make_repo(tmp_path, files)
    row = claims_for(root, "3 page component files")[0]
    assert row["status"] == "matches" and row["measured"] == 3


def test_mounted_wordings_compare_with_matching_metrics(tmp_path):
    frontend_files = {"dashboard/src/pages/A.tsx": "x\n",
                      "dashboard/src/App.tsx": app_tsx(
                          ["A"],
                          '      <Route path="/a" element={<A />} />\n'
                          '      <Route path="/a2" element={<A />} />\n'),
                      "README.md": "It registers 2 mounted routes and 1 mounted page "
                                   "component.\n"}
    root = make_repo(tmp_path, frontend_files)
    claims = collect(root)["docs_claims"]["claims"]
    by_cat = {c["category"]: c for c in claims}
    assert by_cat["mounted_routes"]["status"] == "matches"
    assert by_cat["mounted_routes"]["measured"] == 2
    assert by_cat["mounted_page_components"]["status"] == "matches"
    assert by_cat["mounted_page_components"]["measured"] == 1


def test_ambiguous_ui_pages_not_stale(tmp_path):
    row = claims_for(doc_repo(tmp_path, "The dashboard has 25 React UI pages.\n"),
                     "25 React UI pages")[0]
    assert row["status"] == "not_statically_comparable"
    assert row["measured"] is None


# ---- Correction 4: action-reference provenance and classification ----------------------------

def test_nested_job_step_uses_detected(tmp_path):
    refs = action_repo(tmp_path, "name: CI\njobs:\n  build:\n    steps:\n"
                                 "      - uses: actions/checkout@v4\n")
    entry = ref_entry(refs, "actions/checkout@v4")
    assert (entry["file"], entry["line"]) == (".github/workflows/ci.yml", 5)


def test_reusable_workflow_uses_detected(tmp_path):
    wf = "name: CI\njobs:\n  call:\n    uses: owner/repo/.github/workflows/w.yml@v1\n"
    entry = ref_entry(action_repo(tmp_path, wf), "owner/repo/.github/workflows/w.yml@v1")
    assert (entry["file"], entry["line"], entry["kind"]) == (
        ".github/workflows/ci.yml", 4, "major_tag")


def test_action_ref_main_is_branch(tmp_path):
    refs = action_repo(tmp_path, "jobs:\n  b:\n    steps:\n      - uses: actions/x@main\n")
    assert ref_entry(refs, "actions/x@main")["kind"] == "branch"


def test_action_ref_master_is_branch(tmp_path):
    refs = action_repo(tmp_path, "jobs:\n  b:\n    steps:\n      - uses: actions/x@master\n")
    assert ref_entry(refs, "actions/x@master")["kind"] == "branch"


def test_action_ref_v4_is_mutable_major_tag(tmp_path):
    refs = action_repo(tmp_path, "jobs:\n  b:\n    steps:\n      - uses: actions/x@v4\n")
    assert ref_entry(refs, "actions/x@v4")["kind"] == "major_tag"


def test_action_ref_semantic_tag_is_movable(tmp_path):
    refs = action_repo(tmp_path, "jobs:\n  b:\n    steps:\n      - uses: actions/x@v4.2.1\n")
    assert ref_entry(refs, "actions/x@v4.2.1")["kind"] == "semantic_tag"
    assert refs["by_kind"]["sha_pinned"] == 0


def test_action_ref_full_sha_is_immutable(tmp_path):
    sha = "a" * 40
    refs = action_repo(tmp_path, f"jobs:\n  b:\n    steps:\n      - uses: actions/x@{sha}\n")
    assert ref_entry(refs, f"actions/x@{sha}")["kind"] == "sha_pinned"


def test_action_ref_short_sha_not_immutable(tmp_path):
    refs = action_repo(tmp_path, "jobs:\n  b:\n    steps:\n      - uses: actions/x@1a2b3c4\n")
    entry = ref_entry(refs, "actions/x@1a2b3c4")
    assert entry["kind"] != "sha_pinned"
    assert entry["kind"] == "unknown"  # abbreviated pins require review


def test_docker_digest_vs_untagged(tmp_path):
    digest = "sha256:" + "a" * 64
    wf = ("jobs:\n  b:\n    steps:\n"
          f"      - uses: docker://alpine@{digest}\n"
          "      - uses: docker://alpine:3.18\n")
    refs = action_repo(tmp_path, wf)
    assert ref_entry(refs, f"docker://alpine@{digest}")["kind"] == "docker_digest"
    assert ref_entry(refs, "docker://alpine:3.18")["kind"] == "docker"


def test_local_action_detected(tmp_path):
    refs = action_repo(tmp_path, "jobs:\n  b:\n    steps:\n"
                                 "      - uses: ./.github/actions/my-action\n")
    assert ref_entry(refs, "./.github/actions/my-action")["kind"] == "local"


def test_quoted_and_unquoted_uses(tmp_path):
    wf = ("jobs:\n  b:\n    steps:\n"
          '      - uses: "actions/checkout@v4"\n'
          "      - uses: actions/setup-node@v4\n")
    refs = action_repo(tmp_path, wf)
    assert ref_entry(refs, "actions/checkout@v4")["kind"] == "major_tag"
    assert ref_entry(refs, "actions/setup-node@v4")["kind"] == "major_tag"


def test_yaml_and_yml_extensions_scanned(tmp_path):
    yml = action_repo(tmp_path, "jobs:\n  b:\n    steps:\n      - uses: actions/x@v4\n",
                      name="one.yml")
    yaml_ = action_repo(tmp_path, "jobs:\n  b:\n    steps:\n      - uses: actions/x@v4\n",
                        name="two.yaml")
    assert yml["by_kind"]["major_tag"] == 1 and yaml_["by_kind"]["major_tag"] == 1


def test_uses_detection_deduplicated(tmp_path):
    wf = ("jobs:\n  b:\n    steps:\n"
          "      - uses: actions/checkout@v4\n"
          "      - uses: actions/checkout@v4\n")
    refs = action_repo(tmp_path, wf)
    entries = [r for r in refs["references"] if r["uses"] == "actions/checkout@v4"]
    assert len(entries) == 2  # two lines: YAML- and source-level detections are deduplicated
    assert len({(r["file"], r["line"]) for r in entries}) == 2
    assert refs["by_kind"]["major_tag"] == 2


def test_dynamic_expression_unknown(tmp_path):
    wf = ("jobs:\n  b:\n    steps:\n"
          "      - uses: ${{ env.ACTION_REF }}\n"
          "      - uses: owner/repo@${{ env.REF }}\n")
    refs = action_repo(tmp_path, wf)
    assert ref_entry(refs, "${{ env.ACTION_REF }}")["kind"] == "unknown"
    assert ref_entry(refs, "owner/repo@${{ env.REF }}")["kind"] == "unknown"


def test_real_repository_trivy_findings():
    files = pf._tracked_files(REPO_ROOT)
    refs = pf.action_refs_facts(files, REPO_ROOT, [])
    # The pinning PR replaced both branch references with the reviewed v0.36.0 commit, so no
    # branch reference is left anywhere in the repository.
    assert not [r for r in refs["references"] if r["kind"] == "branch"]
    trivy = [r for r in refs["references"] if r["uses"].startswith("aquasecurity/trivy-action@")]
    assert [(r["file"], r["line"]) for r in trivy] == [
        (".github/workflows/deploy-pipeline.yml", 231),
        (".github/workflows/deploy-pipeline.yml", 261)]
    assert all(r["kind"] == "sha_pinned" for r in trivy)
    assert len({r["uses"] for r in trivy}) == 1  # one reviewed commit for both steps
    assert refs["by_kind"]["branch"] == 0 and refs["by_kind"]["sha_pinned"] == 2
    for value in ("actions/checkout@v4", "actions/setup-python@v5"):
        entries = [r for r in refs["references"] if r["uses"] == value]
        assert entries and all(r["kind"] == "major_tag" for r in entries)
    total = sum(refs["by_kind"].values())
    assert refs["by_kind"]["sha_pinned"] < total  # no false "all immutable" conclusion


# ---- Correction 5: the five statuses and exit behavior ----------------------------------------

def test_all_five_statuses_present_and_exit(tmp_path, monkeypatch):
    readme = ("The schema has 2 SQLModel table=True classes.\n"      # matches
              "There are 9 static test functions in the suite.\n"    # stale
              "3,109 tests passed in CI.\n"                          # not_statically_verifiable
              "The schema has 69 database tables.\n"                 # not_statically_comparable
              "NEXUS is enterprise-grade.\n")                        # subjective
    root = doc_repo(tmp_path, readme)
    docs = collect(root)["docs_claims"]
    assert {c["status"] for c in docs["claims"]} == {
        "matches", "stale", "not_statically_verifiable", "not_statically_comparable",
        "subjective"}
    assert docs["stale_count"] == 1
    monkeypatch.chdir(tmp_path)
    assert pf.main(["--repo", str(root), "--check-docs"]) == 1


# ---- Corrective follow-up A: restricted-console output safety -------------------------------

class _FakeConsole:
    """A stream behaving like a Windows console with a restricted text codec."""

    def __init__(self, encoding):
        self.encoding = encoding
        self.value = ""

    def write(self, text):
        text.encode(self.encoding)  # strict, exactly like a real console
        self.value += text
        return len(text)

    def flush(self):
        pass


_EMOJI_README = "There are 9 static test functions \U0001f3af in the suite.\n"


def _emoji_repo(tmp_path: Path) -> Path:
    # 9 claimed vs 0 measured static test functions: an objective stale claim.
    return make_repo(tmp_path, {"README.md": _EMOJI_README})


def test_console_emoji_under_cp1252_no_crash(tmp_path, monkeypatch):
    fake = _FakeConsole("cp1252")
    monkeypatch.setattr(sys, "stdout", fake)
    rc = pf.main(["--repo", str(_emoji_repo(tmp_path)), "--check-docs"])
    assert rc == 1  # stale finding still reported, no exception escapes
    assert "static test functions" in fake.value  # the claim is identified, not dropped


def test_console_restricted_no_traceback(tmp_path, monkeypatch):
    fake = _FakeConsole("cp1252")
    monkeypatch.setattr(sys, "stdout", fake)
    pf.main(["--repo", str(_emoji_repo(tmp_path)), "--check-docs"])
    assert "Traceback" not in fake.value


def test_console_restricted_stale_exit_is_1(tmp_path, monkeypatch):
    fake = _FakeConsole("cp1252")
    monkeypatch.setattr(sys, "stdout", fake)
    assert pf.main(["--repo", str(_emoji_repo(tmp_path)), "--check-docs"]) == 1


def test_console_utf8_preserves_emoji(tmp_path, monkeypatch):
    fake = _FakeConsole("utf-8")
    monkeypatch.setattr(sys, "stdout", fake)
    pf.main(["--repo", str(_emoji_repo(tmp_path)), "--check-docs"])
    assert "\U0001f3af" in fake.value  # full Unicode preserved on UTF-8 output


def test_console_restricted_output_deterministic(tmp_path, monkeypatch):
    root = _emoji_repo(tmp_path)
    first, second = _FakeConsole("cp1252"), _FakeConsole("cp1252")
    monkeypatch.setattr(sys, "stdout", first)
    pf.main(["--repo", str(root), "--check-docs"])
    monkeypatch.setattr(sys, "stdout", second)
    pf.main(["--repo", str(root), "--check-docs"])
    assert first.value == second.value
    assert "\\U0001f3af" in first.value  # deterministic escaped form identifies the claim


def test_json_markdown_remain_utf8_with_emoji(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    rc = pf.main(["--repo", str(_emoji_repo(tmp_path)), "--check-docs",
                  "--json", "out.json", "--markdown", "out.md"])
    assert rc == 1
    payload = json.loads((tmp_path / "out.json").read_text(encoding="utf-8"))
    assert payload["docs_claims"]["stale_count"] == 1
    markdown = (tmp_path / "out.md").read_text(encoding="utf-8")
    assert "\U0001f3af" in markdown  # files keep full Unicode regardless of the console


def test_operational_failure_exit_is_2_not_stale(tmp_path, monkeypatch):
    def broken_write(raw, content, overwrite):
        raise OSError("disk full")

    monkeypatch.setattr(pf, "_write_output", broken_write)
    monkeypatch.chdir(tmp_path)
    rc = pf.main(["--repo", str(_emoji_repo(tmp_path)),
                  "--check-docs", "--json", "out.json"])
    assert rc == 2  # operational failure is distinguishable from the stale exit


# ---- Corrective follow-up B: explicit incomparable status wins over metrics ------------------

def _api_repo(tmp_path: Path, readme: str, modules: int = 1) -> Path:
    files = {"README.md": readme}
    for index in range(modules):
        files[f"src/nexus/api/routes/m{index}.py"] = (
            "from fastapi import APIRouter\nrouter = APIRouter()\n\n"
            "@router.get('/a')\nasync def a():\n    return None\n")
    return make_repo(tmp_path, files)


def test_generic_routes_and_endpoints_incomparable(tmp_path):
    root = _api_repo(tmp_path, "The API exposes 5 endpoints.\nIt serves 3 routes today.\n")
    claims = [c for c in collect(root)["docs_claims"]["claims"]
              if c["category"] == "api_endpoints"]
    assert [c["status"] for c in claims] == ["not_statically_comparable"] * 2
    assert all(c["measured"] is None for c in claims)


def test_explicit_route_function_claim_match_and_stale(tmp_path):
    root = _api_repo(tmp_path, "The API defines 1 route function.\n"
                               "Docs once claimed 9 route functions.\n")
    claims = [c for c in collect(root)["docs_claims"]["claims"]
              if c["category"] == "route_functions"]
    assert {c["claimed"]: c["status"] for c in claims} == {1: "matches", 9: "stale"}


def test_router_module_claim_match_and_stale(tmp_path):
    root = _api_repo(tmp_path, "The API has 2 router modules.\n"
                               "Docs once claimed 9 router modules.\n", modules=2)
    claims = [c for c in collect(root)["docs_claims"]["claims"]
              if c["category"] == "api_routers"]
    assert {c["claimed"]: c["status"] for c in claims} == {2: "matches", 9: "stale"}


def test_incomparable_rule_with_metric_stays_incomparable(tmp_path):
    root = _api_repo(tmp_path, "The API defines 1 route function.\n"
                               "The API exposes 5 endpoints.\n")
    claims = {c["category"]: c for c in collect(root)["docs_claims"]["claims"]
              if c["category"] in ("route_functions", "api_endpoints")}
    assert claims["route_functions"]["status"] == "matches"  # metric is available
    assert claims["api_endpoints"]["status"] == "not_statically_comparable"  # override wins


def test_real_repo_router_claims_stale_unchanged():
    docs = collect(REPO_ROOT)["docs_claims"]
    stale = [(c["category"], c["claimed"], c["measured"], c["file"], c["line"])
             for c in docs["claims"] if c["status"] == "stale"]
    assert stale == [
        ("api_routers", 54, 69, "ARCHITECTURE.md", 36),
        ("api_routers", 54, 69, "ARCHITECTURE.md", 79),
        ("api_routers", 54, 69, "docs/FINAL-STATUS-SUMMARY.md", 17),
    ]
    assert docs["stale_count"] == 3


# ---- Corrective follow-up C: git optional-lock suppression ------------------------------------

def test_git_invocations_suppress_optional_locks(tmp_path, monkeypatch):
    captured = {}
    real_run = pf.subprocess.run

    def spy(argv, **kwargs):
        captured["argv"] = argv
        captured["kwargs"] = kwargs
        return real_run(argv, **kwargs)

    monkeypatch.setattr(pf.subprocess, "run", spy)
    root = make_repo(tmp_path, {"README.md": "# x\n"})
    pf._git(root, "status", "--porcelain", "-uno")
    assert captured["argv"][:3] == ["git", "--no-optional-locks", "-C"]
    assert captured["argv"][3] == str(root)
    assert captured["kwargs"].get("timeout") == 60
    assert not captured["kwargs"].get("shell")
    assert "env" not in captured["kwargs"]  # no environment is constructed, passed or logged
