"""scripts/prepare_acceptance.py for real: Alembic on a copy, the CEO appointment and the
Organization Snapshot.

The source database is built at Alembic revision a7c4e9b2d610 (the primary dev database's
revision) and must stay byte-identical while its copy is migrated and prepared.
"""

import hashlib
import json
import os
import sqlite3
import subprocess
import sys
import uuid
from pathlib import Path

import pytest
from sqlmodel import Session, create_engine

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
OLD_REVISION = "a7c4e9b2d610"
COMPANY = uuid.uuid4()
OTHER_COMPANY = uuid.uuid4()
ACCEPTANCE_ACTOR = "acceptance-admin@acceptance.invalid"


def url(db: Path) -> str:
    return "sqlite+aiosqlite:///" + db.as_posix()


def run(args: list[str], db: Path) -> tuple[int, dict, str]:
    env = {**os.environ, "DATABASE_URL": url(db), "PYTHONPATH": str(ROOT / "src")}
    r = subprocess.run(
        [sys.executable, *args], env=env, cwd=ROOT, capture_output=True, text=True, timeout=300
    )
    last = [ln for ln in r.stdout.splitlines() if ln.startswith("{")][-1]
    return r.returncode, json.loads(last), r.stdout + r.stderr


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def revision(db: Path) -> list[str]:
    c = sqlite3.connect(db)
    try:
        return [r[0] for r in c.execute("select version_num from alembic_version")]
    finally:
        c.close()


@pytest.fixture(scope="module")
def source(tmp_path_factory) -> Path:
    db = tmp_path_factory.mktemp("prep-source") / "source.db"
    env = {**os.environ, "DATABASE_URL": url(db), "PYTHONPATH": str(ROOT / "src")}
    r = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", OLD_REVISION],
        env=env,
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=300,
    )
    assert r.returncode == 0, r.stderr[-800:]
    assert revision(db) == [OLD_REVISION]
    return db


@pytest.fixture(scope="module")
def migrated(source, tmp_path_factory):
    before = sha(source)
    copy = tmp_path_factory.mktemp("prep-copy") / "acceptance.db"
    r = subprocess.run(
        [sys.executable, str(SCRIPTS / "clone_sqlite.py"), str(copy)],
        env={**os.environ, "DATABASE_URL": url(source)},
        capture_output=True,
        text=True,
    )
    assert r.returncode == 0, r.stderr
    assert revision(copy) == [OLD_REVISION]
    code, out, _ = run([str(SCRIPTS / "prepare_acceptance.py"), "migrate", str(source)], copy)
    return {"source": source, "before": before, "copy": copy, "code": code, "out": out}


def test_the_copy_reaches_head_and_the_source_stays_byte_identical(migrated):
    assert migrated["code"] == 0 and migrated["out"]["status"] == "PASS"
    assert revision(migrated["copy"]) == [migrated["out"]["head"]]
    assert revision(migrated["source"]) == [OLD_REVISION]
    assert sha(migrated["source"]) == migrated["before"]
    c = sqlite3.connect(migrated["copy"])
    try:
        assert "is_ceo" in {r[1] for r in c.execute("pragma table_info(agents)")}
        tables = {r[0] for r in c.execute("select name from sqlite_master where type='table'")}
    finally:
        c.close()
    assert {"organization_snapshots", "organization_snapshot_state"} <= tables


@pytest.mark.parametrize("spelling", ["same", "dots", "upper"])
def test_migrate_refuses_when_the_target_is_the_source(source, spelling):
    before = sha(source)
    target = {
        "same": source,
        "dots": source.parent / "sub" / ".." / source.name,
        "upper": Path(str(source).upper()),  # Windows paths are case-insensitive
    }[spelling]
    (source.parent / "sub").mkdir(exist_ok=True)
    if spelling == "upper" and not os.path.exists(target):
        pytest.skip("case-sensitive file system")
    code, out, text = run([str(SCRIPTS / "prepare_acceptance.py"), "migrate", str(source)], target)
    assert code == 2 and out["status"] == "FAIL" and "source database" in out["error"]
    assert sha(source) == before and revision(source) == [OLD_REVISION]
    assert "sqlite" not in text.lower()


def _seed(copy: Path) -> dict:
    """A company with a small org, another company, and a terminated agent, through the ORM."""
    import nexus.models  # noqa: F401  (registers every table)
    from nexus.models.agent import Agent
    from nexus.models.company import Company

    engine = create_engine("sqlite:///" + copy.as_posix())
    with Session(engine) as db:
        db.add(Company(id=COMPANY, name="Acme"))
        db.add(Company(id=OTHER_COMPANY, name="Other"))
        db.commit()
        chief = Agent(company_id=COMPANY, name="Chief", role="executive")
        deputy = Agent(company_id=COMPANY, name="Deputy", role="executive")
        worker = Agent(company_id=COMPANY, name="Worker", role="engineer")
        gone = Agent(company_id=COMPANY, name="Gone", role="engineer", status="terminated")
        foreign = Agent(company_id=OTHER_COMPANY, name="Foreign", role="executive")
        db.add_all([chief, deputy, worker, gone, foreign])
        db.commit()
        worker.manager_id = chief.id
        db.add(worker)
        db.commit()
        ids = {a.name: str(a.id) for a in (chief, deputy, worker, gone, foreign)}
    engine.dispose()
    return ids


@pytest.fixture(scope="module")
def seeded(migrated):
    assert migrated["code"] == 0
    return _seed(migrated["copy"])


def test_without_a_ceo_or_choice_it_lists_eligible_agents_only(migrated, seeded):
    code, out, text = run(
        [str(SCRIPTS / "prepare_acceptance.py"), "prepare", str(COMPANY)], migrated["copy"]
    )
    assert code == 3 and out["status"] == "LIVE_CHECK_REQUIRED"
    assert {c["name"] for c in out["candidates"]} == {"Chief", "Deputy", "Worker"}, (
        "terminated and foreign agents are not eligible"
    )
    assert all(set(c) == {"id", "name", "role"} for c in out["candidates"])
    assert "sqlite" not in text.lower()


@pytest.mark.parametrize("who", ["Foreign", "Gone"])
def test_an_agent_of_another_company_or_a_terminated_one_is_rejected(migrated, seeded, who):
    code, out, _ = run(
        [str(SCRIPTS / "prepare_acceptance.py"), "prepare", str(COMPANY), "--agent", seeded[who]],
        migrated["copy"],
    )
    assert code == 2 and out["status"] == "FAIL"
    c = sqlite3.connect(migrated["copy"])
    try:
        assert c.execute("select count(*) from agents where is_ceo").fetchone()[0] == 0
    finally:
        c.close()


def test_appointment_and_snapshot_go_through_the_services(migrated, seeded):
    copy = migrated["copy"]
    code, out, text = run(
        [
            str(SCRIPTS / "prepare_acceptance.py"),
            "prepare",
            str(COMPANY),
            "--agent",
            seeded["Chief"],
        ],
        copy,
    )
    assert code == 0, text[-500:]
    assert out["ceo_source"] == "appointed" and out["ceo"]["id"] == seeded["Chief"]
    assert (
        "disposable" in out["note"]
        and out["snapshot"]["freshness"] == "fresh"
        and out["snapshot"]["payload_hash"]
    )
    assert "sqlite" not in text.lower()
    c = sqlite3.connect(copy)
    try:
        assert [
            r[0]
            for r in c.execute(
                "select id from agents where is_ceo and company_id = ?", (COMPANY.hex,)
            )
        ] == [uuid.UUID(seeded["Chief"]).hex]
        actors = {r[0] for r in c.execute("select actor_id from audit_log")}
        assert ACCEPTANCE_ACTOR in actors, (
            "the appointment is audited under the acceptance principal"
        )
        # Another live root is re-parented under the CEO by the service, never left beside it.
        deputy_manager = c.execute(
            "select manager_id from agents where id = ?", (uuid.UUID(seeded["Deputy"]).hex,)
        ).fetchone()[0]
        assert deputy_manager == uuid.UUID(seeded["Chief"]).hex
        assert c.execute("select count(*) from agents where is_ceo").fetchone()[0] == 1
    finally:
        c.close()
    assert migrated["source"].exists() and sha(migrated["source"]) == migrated["before"]


def test_rerun_reports_the_existing_ceo_and_a_different_one_needs_replace(migrated, seeded):
    copy, prep = migrated["copy"], str(SCRIPTS / "prepare_acceptance.py")
    code, first, _ = run([prep, "prepare", str(COMPANY)], copy)
    assert code == 0 and first["ceo_source"] == "existing" and first["ceo"]["id"] == seeded["Chief"]
    code, again, _ = run([prep, "prepare", str(COMPANY), "--agent", seeded["Chief"]], copy)
    assert code == 0 and again["snapshot"]["version"] == first["snapshot"]["version"], (
        "unchanged org, same snapshot"
    )

    code, out, _ = run([prep, "prepare", str(COMPANY), "--agent", seeded["Deputy"]], copy)
    assert code == 2 and "-ReplaceCeo" in out["error"]

    code, out, _ = run(
        [prep, "prepare", str(COMPANY), "--agent", seeded["Deputy"], "--replace-ceo"], copy
    )
    assert code == 0 and out["ceo"]["id"] == seeded["Deputy"] and out["ceo_source"] == "appointed"
    c = sqlite3.connect(copy)
    try:
        assert c.execute("select count(*) from agents where is_ceo").fetchone()[0] == 1
    finally:
        c.close()


def test_unknown_company_fails_without_echoing_the_database(migrated, seeded):
    code, out, text = run(
        [str(SCRIPTS / "prepare_acceptance.py"), "prepare", str(uuid.uuid4())], migrated["copy"]
    )
    assert code == 2 and out["status"] == "FAIL" and "sqlite" not in text.lower()
