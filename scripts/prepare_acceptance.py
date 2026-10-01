"""Prepare the isolated acceptance database copy that scripts/start-local-voice.ps1 made.

    DATABASE_URL=<the copy> python scripts/prepare_acceptance.py migrate <source-db-file>
    DATABASE_URL=<the copy> python scripts/prepare_acceptance.py prepare <company-id>
        [--agent <id>] [--replace-ceo]

``migrate`` runs ``alembic upgrade head`` on the copy only and refuses to run when
DATABASE_URL resolves to the source file. It then checks for a single head and for the
``agents.is_ceo`` column and the organization snapshot tables.

``prepare`` designates the CEO through the application's own appointment service, under an
explicit human-admin acceptance principal (hierarchy, uniqueness and audit rows behave as
in production), then generates the Organization Snapshot through its own service and
verifies it is fresh and that its stored payload hash matches its payload. Nothing here
writes ``is_ceo`` or snapshot rows directly. With no CEO and no ``--agent`` it lists the
eligible agents (id, name, role only) and exits 3: a person has to choose.

Output is one JSON line. Nothing about the database URL, prompts, adapter config or secrets
is printed. Exit codes: 0 done, 2 failed, 3 needs a CEO choice.
"""

import argparse
import asyncio
import json
import os
import sqlite3
import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src"), str(Path(__file__).resolve().parent)]

from clone_sqlite import source_path  # noqa: E402

DISPOSABLE = (
    "Designated in the disposable acceptance copy only; the primary database was not changed."
)
SNAPSHOT_TABLES = ("organization_snapshots", "organization_snapshot_state")


def out(code: int, **fields) -> int:
    print(json.dumps(fields))
    return code


def migrate(source: str) -> int:
    copy = source_path(os.environ.get("DATABASE_URL", ""))
    if copy is None or not copy.is_file():
        return out(2, status="FAIL", error="DATABASE_URL is not an existing SQLite file")
    if copy.resolve() == Path(source).resolve() or (
        Path(source).exists() and os.path.samefile(copy, source)
    ):
        return out(2, status="FAIL", error="refusing to migrate: the target is the source database")

    from alembic.config import Config
    from alembic.script import ScriptDirectory

    from alembic import command

    cfg = Config(str(ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(ROOT / "alembic"))
    heads = ScriptDirectory.from_config(cfg).get_heads()
    if len(heads) != 1:
        return out(2, status="FAIL", error=f"expected one Alembic head, found {len(heads)}")
    try:
        command.upgrade(cfg, "head")
    except Exception as exc:  # noqa: BLE001 - fixed, URL-free message
        return out(
            2,
            status="FAIL",
            error=f"migration failed: {type(exc).__name__}: {str(exc).splitlines()[0][:200]}",
        )

    db = sqlite3.connect(copy)
    try:
        revisions = [r[0] for r in db.execute("select version_num from alembic_version")]
        tables = {r[0] for r in db.execute("select name from sqlite_master where type='table'")}
        agent_columns = {r[1] for r in db.execute("pragma table_info(agents)")}
    finally:
        db.close()
    problems = [
        *([f"at {revisions}, not head"] if revisions != heads else []),
        *(["agents.is_ceo is missing"] if "is_ceo" not in agent_columns else []),
        *(f"table {t} is missing" for t in SNAPSHOT_TABLES if t not in tables),
    ]
    if problems:
        return out(2, status="FAIL", error="; ".join(problems))
    return out(0, status="PASS", head=heads[0])


async def prepare(company: uuid.UUID, agent_id: uuid.UUID | None, replace: bool) -> int:
    from sqlalchemy import select

    from nexus.auth.principal import Principal
    from nexus.database import tenant_session
    from nexus.models.agent import Agent
    from nexus.models.company import Company
    from nexus.services import ceo_service, org_snapshot
    from nexus.services import manager_service as ms

    def brief(a: Agent) -> dict:
        return {"id": str(a.id), "name": a.name, "role": a.role}

    admin = Principal(
        kind="user", company_id=company, role="admin", email="acceptance-admin@acceptance.invalid"
    )
    async with tenant_session(company) as db:
        if await db.get(Company, company) is None:
            return out(2, status="FAIL", error="company not found in the copy")
        ceo = await ceo_service.current_ceo(db, company)
        source = "existing"
        if agent_id is None and ceo is None:
            rows = (
                (
                    await db.execute(
                        select(Agent)
                        .where(Agent.company_id == company, Agent.status != "terminated")
                        .order_by(Agent.name, Agent.id)
                    )
                )
                .scalars()
                .all()
            )
            return out(
                3,
                status="LIVE_CHECK_REQUIRED",
                reason="no CEO is designated; choose one and rerun with -CeoAgentId",
                candidates=[brief(a) for a in rows],
            )
        if agent_id is not None and (ceo is None or ceo.id != agent_id):
            if ceo is not None and not replace:
                return out(
                    2,
                    status="FAIL",
                    error="the company already has a CEO; pass -ReplaceCeo to replace it",
                    ceo=brief(ceo),
                )
            await ms.get_agent(db, company, agent_id)  # 404 for an agent of another company
            await ceo_service.appoint(
                db, company, agent_id, admin, replaces=ceo.id if ceo else None
            )
            ceo, source = await ceo_service.current_ceo(db, company), "appointed"
        if ceo is None:
            return out(2, status="FAIL", error="no CEO after appointment")

    result: dict = {"outcome": "in_progress"}
    for _ in range(20):
        result = await org_snapshot.generate(company)
        if result["outcome"] != "in_progress":
            break
        await asyncio.sleep(0.5)
    if result["outcome"] not in ("created", "unchanged"):
        return out(2, status="FAIL", error=f"snapshot generation {result['outcome']}")
    async with tenant_session(company) as db:
        snap = await org_snapshot.read(db, company)
    if snap["freshness"]["status"] != org_snapshot.FRESH:
        return out(2, status="FAIL", error=f"snapshot is {snap['freshness']['status']}")
    if org_snapshot.payload_hash(snap["snapshot"]) != snap["payload_hash"]:
        return out(2, status="FAIL", error="snapshot payload hash does not match its payload")
    return out(
        0,
        status="PASS",
        company_id=str(company),
        ceo=brief(ceo),
        ceo_source=source,
        note=DISPOSABLE,
        snapshot={
            "version": snap["version"],
            "payload_hash": snap["payload_hash"],
            "freshness": snap["freshness"]["status"],
            "generated_at": snap["generated_at"],
        },
    )


def main() -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("migrate").add_argument("source")
    p = sub.add_parser("prepare")
    p.add_argument("company", type=uuid.UUID)
    p.add_argument("--agent", type=uuid.UUID)
    p.add_argument("--replace-ceo", action="store_true")
    try:
        a = ap.parse_args()
    except SystemExit:
        return out(2, status="FAIL", error="bad arguments")
    if a.cmd == "migrate":
        return migrate(a.source)
    try:
        return asyncio.run(prepare(a.company, a.agent, a.replace_ceo))
    except Exception as exc:  # noqa: BLE001
        detail = getattr(exc, "detail", None)
        code = detail.get("code") if isinstance(detail, dict) else None
        return out(2, status="FAIL", error=code or type(exc).__name__)


if __name__ == "__main__":
    sys.exit(main())
