"""Tests for the architecture invariant guard (scripts/arch_guard.py, Phase 0.6).

Two jobs here. First, prove each rule actually fires -- a guard that silently
passes is worse than no guard, since CI then certifies the invariant is held
when nobody is checking. Each rule gets a synthetic violation written into a
temp tree with ``SRC`` monkeypatched, so no probe file ever lands in src/nexus.

Second, guard the guard's own config against drift: ``LOOP_OWNERS`` exempts
files by path, and ``BASELINE`` suppresses known debt by key. Both go stale
silently when a file is renamed or a phase lands, and a stale exemption is an
invariant that stopped being enforced without anyone noticing.
"""

import importlib.util
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
GUARD_PATH = REPO_ROOT / "scripts" / "arch_guard.py"


def _load_guard():
    """Import scripts/arch_guard.py by path (scripts/ is not a package)."""
    spec = importlib.util.spec_from_file_location("arch_guard", GUARD_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def guard():
    return _load_guard()


@pytest.fixture
def fake_src(guard, tmp_path, monkeypatch):
    """Point the guard at an empty temp tree instead of src/nexus."""
    root = tmp_path / "nexus"
    (root / "governance").mkdir(parents=True)
    (root / "workflows").mkdir(parents=True)
    monkeypatch.setattr(guard, "SRC", root)
    return root


def _keys(findings):
    return [key for key, _ in findings]


# --- the four rules fire -----------------------------------------------------


def test_r1_catches_in_memory_audit_list(guard, fake_src):
    """The plan's stated acceptance test: reintroducing an in-memory audit list fails."""
    probe = fake_src / "governance" / "audit.py"
    probe.write_text("_audit_entries: dict = {}\n_log = []\n", encoding="utf-8")

    keys = _keys(guard.check_r1())
    assert "R1 governance/audit.py:_audit_entries" in keys
    assert "R1 governance/audit.py:_log" in keys


def test_r1_allows_upper_case_constants(guard, fake_src):
    """Declared constants are config, not per-process state -- must not trip."""
    probe = fake_src / "governance" / "rbac.py"
    probe.write_text("STANDARD_ROLES: dict = {'admin': 1}\n", encoding="utf-8")

    assert guard.check_r1() == []


def test_r1_catches_mutable_singleton(guard, fake_src):
    """`_x = None` / `_x = False` are the lazy-init form of the same bug."""
    probe = fake_src / "governance" / "vault.py"
    probe.write_text("_client = None\n_initialized = False\n", encoding="utf-8")

    keys = _keys(guard.check_r1())
    assert "R1 governance/vault.py:_client" in keys
    assert "R1 governance/vault.py:_initialized" in keys


def test_r2_catches_second_polling_loop(guard, fake_src):
    probe = fake_src / "triggers"
    probe.mkdir()
    (probe / "poller.py").write_text(
        "import asyncio\n\n\nasync def go():\n    while True:\n        await asyncio.sleep(5)\n",
        encoding="utf-8",
    )

    assert "R2 triggers/poller.py:5" in _keys(guard.check_r2())


def test_r2_catches_third_party_scheduler_import(guard, fake_src):
    probe = fake_src / "jobs.py"
    probe.write_text(
        "from apscheduler.schedulers.asyncio import AsyncIOScheduler\n", encoding="utf-8"
    )

    assert any(key.startswith("R2 jobs.py:apscheduler") for key in _keys(guard.check_r2()))


def test_r2_exempts_the_designated_loop_owner(guard, fake_src):
    """runtime/scheduler.py owns the one tick loop, so its loop is legal."""
    owner = fake_src / "runtime"
    owner.mkdir()
    (owner / "scheduler.py").write_text(
        "import asyncio\n\n\nasync def go():\n    while True:\n        await asyncio.sleep(5)\n",
        encoding="utf-8",
    )

    assert guard.check_r2() == []


def test_r3_catches_session_import_in_workflows(guard, fake_src):
    probe = fake_src / "workflows" / "task_flow.py"
    probe.write_text("from sqlalchemy.ext.asyncio import AsyncSession\n", encoding="utf-8")

    assert "R3 workflows/task_flow.py:AsyncSession" in _keys(guard.check_r3())


def test_r3_allows_dto_imports_in_workflows(guard, fake_src):
    """Workflows passing DTOs is the sanctioned pattern -- must not trip."""
    probe = fake_src / "workflows" / "company_flow.py"
    probe.write_text("from dataclasses import dataclass\n", encoding="utf-8")

    assert guard.check_r3() == []


def test_r4_catches_persistent_module_without_asyncsession(guard, fake_src):
    for name in ("audit_persistent.py", "persistent_vault.py"):
        (fake_src / "governance" / name).write_text("store = []\n", encoding="utf-8")

    keys = _keys(guard.check_r4())
    assert "R4 governance/audit_persistent.py" in keys
    assert "R4 governance/persistent_vault.py" in keys


def test_r4_passes_when_db_backed(guard, fake_src):
    probe = fake_src / "governance" / "persistent_kill_switch.py"
    probe.write_text(
        "from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker\n", encoding="utf-8"
    )

    assert guard.check_r4() == []


def _routes_probe(fake_src, name: str, body: str):
    """Write a route module plus the model file R5 discovers tenant tables from."""
    models = fake_src / "models"
    models.mkdir(exist_ok=True)
    (models / "task.py").write_text(
        "import uuid\n\n\nclass Task:\n    company_id: uuid.UUID\n", encoding="utf-8"
    )
    routes = fake_src / "api" / "routes"
    routes.mkdir(parents=True, exist_ok=True)
    (routes / name).write_text(body, encoding="utf-8")


def test_r5_catches_unscoped_tenant_query(guard, fake_src):
    """The plan's acceptance shape: select(Task) with no company_id filter fails."""
    _routes_probe(
        fake_src,
        "tasks.py",
        "async def list_tasks(db):\n    return await db.execute(select(Task))\n",
    )

    keys = _keys(guard.check_r5())
    assert "R5 api/routes/tasks.py:list_tasks" in keys


def test_r5_allows_a_scoped_query(guard, fake_src):
    _routes_probe(
        fake_src,
        "tasks.py",
        "async def list_tasks(db, company_id):\n"
        "    return await db.execute(select(Task).where(Task.company_id == company_id))\n",
    )

    assert guard.check_r5() == []


def test_r5_ignores_models_without_company_id(guard, fake_src):
    """A global table is not a tenant table, so querying it unfiltered is fine."""
    _routes_probe(
        fake_src,
        "companies_list.py",
        "async def list_all(db):\n    return await db.execute(select(Company))\n",
    )

    assert guard.check_r5() == []


def test_r5_catches_column_selects_too(guard, fake_src):
    """``select(Task.status)`` still reads the tenant table."""
    _routes_probe(
        fake_src,
        "stats.py",
        "async def counts(db):\n    return await db.execute(select(Task.status))\n",
    )

    assert "R5 api/routes/stats.py:counts" in _keys(guard.check_r5())


def test_r5_exempts_declared_owners(guard, fake_src):
    """The exemption list is honoured, so the reasons in it are load-bearing."""
    name = sorted(guard.TENANT_QUERY_OWNERS)[0]
    _routes_probe(
        fake_src,
        name,
        "async def anything(db):\n    return await db.execute(select(Task))\n",
    )

    assert guard.check_r5() == []


def test_clean_tree_produces_no_findings(guard, fake_src):
    """No false positives on an empty tree -- every rule stays quiet."""
    for check in guard.CHECKS:
        assert check() == [], check.__name__


# --- the guard's own config cannot drift silently ----------------------------


def test_tenant_query_owner_exemptions_all_exist(guard):
    """Same drift risk as LOOP_OWNERS: a renamed route file leaves a dead exemption.

    Worse than dead -- if the name is later reused by a different router, that
    router inherits an exemption from the tenant filter nobody granted it.
    """
    routes = guard.SRC / "api" / "routes"
    missing = [n for n in guard.TENANT_QUERY_OWNERS if not (routes / n).is_file()]
    assert not missing, f"TENANT_QUERY_OWNERS entries no longer on disk: {missing}"


def test_loop_owner_exemptions_all_exist(guard):
    """A renamed or deleted owner leaves a dead exemption that quietly excuses nothing.

    Worse, if the path is later reused by a different module, that module
    inherits a scheduler exemption nobody granted it.
    """
    missing = [p for p in guard.LOOP_OWNERS if not (guard.SRC / p).is_file()]
    assert not missing, f"LOOP_OWNERS entries no longer on disk: {missing}"


def test_baseline_entries_are_still_violated(guard):
    """Every baselined key must still correspond to a real finding.

    When a Wave 0 phase lands and fixes the debt, the stale entry has to be
    deleted -- that deletion is how the phase proves it is done. The guard
    already fails on stale entries at runtime; this pins the behaviour so the
    baseline cannot quietly outlive the debt it documents.
    """
    found = set()
    for check in guard.CHECKS:
        found.update(key for key, _ in check())

    stale = sorted(set(guard.BASELINE) - found)
    assert not stale, f"BASELINE entries no longer violated, remove them: {stale}"


def test_repo_currently_passes_the_guard(guard, capsys):
    """The committed tree must be green, otherwise CI is red on arrival."""
    assert guard.main([]) == 0
    assert "FAIL" not in capsys.readouterr().out
