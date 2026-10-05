"""Deterministic tests for scripts/project_facts.py (read-only project-facts auditor).

Every test builds a throwaway repository under tmp_path and points the auditor at it, so no
fixture ever touches src/nexus, the primary checkout, or the network. The auditor itself is
loaded by path (scripts/ is not a package), following the convention in test_arch_guard.py;
the module is registered in sys.modules before exec_module per the repo convention.
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


def model_src(class_names: list) -> str:
    body = "from sqlmodel import SQLModel\n"
    for name in class_names:
        body += f"\n\nclass {name}(SQLModel, table=True):\n    id: int = 0\n"
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


def doc_repo(tmp_path: Path, readme: str) -> Path:
    """A repo with two SQLModel table classes, the baseline for claim comparisons."""
    return make_repo(tmp_path, {"src/nexus/models/thing.py": model_src(["Thing", "Other"]),
                                "README.md": readme})


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
    assert "not a guaranteed physical-table count" in database["physical_table_note"]


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
    files = {"dashboard/src/pages/A.tsx": "export default function A() { return null }\n",
             "dashboard/src/pages/B.tsx": "export default function B() { return null }\n",
             "dashboard/src/pages/__tests__/A.test.tsx": "test('a', () => {});\n",
             "dashboard/src/components/C.tsx": "export const C = () => null\n"}
    frontend = collect(make_repo(tmp_path, files))["frontend"]
    assert frontend["dashboard_page_count"] == 2  # test files under pages/ are not pages
    assert frontend["dashboard_unit_test_file_count"] == 1


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
    assert tests["test_function_count_static"] == 3  # parametrization is not expanded
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
        ),
    }
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
    ci = collect(make_repo(tmp_path, {".github/workflows/ci.yml": wf}))["ci"]
    assert ci["action_refs"]["branch_or_other"] == ["actions/checkout@main"]
    assert ci["action_refs"]["sha_pinned"] == []
    assert "mutable" in ci["action_ref_note"].lower()


def test_major_tag_action_reference_not_immutable(tmp_path):
    wf = "name: CI\njobs:\n  build:\n    steps:\n      - uses: actions/checkout@v4\n"
    ci = collect(make_repo(tmp_path, {".github/workflows/ci.yml": wf}))["ci"]
    assert ci["action_refs"]["major_tag"] == ["actions/checkout@v4"]
    assert ci["action_refs"]["sha_pinned"] == []
    assert "mutable" in ci["action_ref_note"].lower()


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
    claims = collect(doc_repo(tmp_path, "The schema has 2 database tables today.\n"))[
        "docs_claims"]["claims"]
    row = [c for c in claims if c["category"] == "database_tables"][0]
    assert (row["claimed"], row["measured"], row["status"]) == (2, 2, "matches")


def test_doc_claim_stale(tmp_path):
    docs = collect(doc_repo(tmp_path, "The schema has 9 database tables today.\n"))["docs_claims"]
    assert docs["stale_count"] == 1
    assert docs["claims"][0]["status"] == "stale"


def test_doc_claim_unverifiable(tmp_path):
    claims = collect(doc_repo(tmp_path, "There are 40 test scenarios covered.\n"))[
        "docs_claims"]["claims"]
    assert claims[0]["status"] == "not_statically_verifiable"
    assert claims[0]["measured"] is None


def test_subjective_readiness_claim(tmp_path):
    docs = collect(doc_repo(tmp_path, "NEXUS is enterprise-grade and production-ready.\n"))[
        "docs_claims"]
    assert [c["status"] for c in docs["claims"]] == ["subjective", "subjective"]
    assert docs["stale_count"] == 0


# 27. --check-docs exit behavior ---

def test_check_docs_exit_behavior(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    matching = doc_repo(tmp_path / "c", "The schema has 2 database tables today.\n")
    assert pf.main(["--repo", str(matching), "--check-docs"]) == 0
    stale = doc_repo(tmp_path / "s", "The schema has 9 database tables today.\n")
    assert pf.main(["--repo", str(stale), "--check-docs"]) == 1
    subjective = doc_repo(tmp_path / "j", "NEXUS is enterprise-grade.\n")
    assert pf.main(["--repo", str(subjective), "--check-docs"]) == 0


# 28-29. Schema and deterministic rendering ---

def test_json_schema_and_deterministic_ordering(tmp_path):
    root = make_repo(tmp_path, {"README.md": "# x\n", "src/nexus/a.py": "x = 1\n"})
    report = collect(root)
    assert report["schema_version"] == 1
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
