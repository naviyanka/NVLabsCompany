"""Only nexus.memory.lifecycle changes a memory row's lifecycle or trust.

A source scan. ``status``, ``trust_state``, ``lifecycle_changed_at``,
``lifecycle_changed_by`` and ``supersedes_id`` are written at insert by
``nexus.memory.ingest`` and afterwards only by ``nexus.memory.lifecycle``. Everything
else may update the scoring columns (importance, access_count, last_accessed_at, tier,
updated_at), and only through a tenant-scoped UPDATE; the ones that rank recall must
also filter on status so a read or decay pass never touches a closed row.

Verified promotion (candidate -> active, untrusted -> asserted -> verified) is
deliberately absent from the codebase: it needs the future ``memory_evidence`` table, and
a trust change without evidence is exactly what this guard exists to stop.
"""

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LIFECYCLE = Path("nexus/memory/lifecycle.py")
INGEST = Path("nexus/memory/ingest.py")
# Migration/backfill exceptions, as paths relative to the repository's src/ or scripts/.
# Empty today: Alembic revisions are outside the scanned trees and carry frozen SQL.
# Add one only with a comment saying why a one-off data fix cannot use lifecycle.
MIGRATION_EXCEPTIONS: set[Path] = set()

PROTECTED = {
    "status",
    "trust_state",
    "lifecycle_changed_at",
    "lifecycle_changed_by",
    "supersedes_id",
}
SCORING = {"importance", "access_count", "last_accessed_at", "tier", "updated_at"}
RANKING = {"importance", "access_count", "last_accessed_at"}
SCORING_UPDATERS = {
    Path("nexus/runtime/orchestrator.py"),  # importance decay
    Path("nexus/memory/layered_persistent.py"),  # access counters
    Path("nexus/memory/store.py"),  # tier moves
    Path("nexus/api/routes/memory_global.py"),  # operator importance/tier/content edit
}


def _name(node: ast.AST) -> str:
    return (
        node.id
        if isinstance(node, ast.Name)
        else node.attr
        if isinstance(node, ast.Attribute)
        else ""
    )


def _update_chains(tree: ast.AST):
    """Yield (call, where_text, value_keys) for each ``update(MemoryRecord)...`` expression."""
    parents = {c: p for p in ast.walk(tree) for c in ast.iter_child_nodes(p)}
    for node in ast.walk(tree):
        if not (
            isinstance(node, ast.Call)
            and _name(node.func) in {"update", "sa_update"}
            and node.args
            and _name(node.args[0]) == "MemoryRecord"
        ):
            continue
        chain, cur = [node], node
        while isinstance(parents.get(cur), ast.Attribute) and isinstance(
            parents.get(parents[cur]), ast.Call
        ):
            cur = parents[parents[cur]]
            chain.append(cur)
        where = " ".join(ast.unparse(a) for c in chain if _name(c.func) == "where" for a in c.args)
        keys: set[str] = set()
        for call in (c for c in chain if _name(c.func) == "values"):
            keys |= {k.arg for k in call.keywords if k.arg}
            dicts = [a for a in call.args if isinstance(a, ast.Dict)]
            dicts += [
                k.value for k in call.keywords if k.arg is None and isinstance(k.value, ast.Dict)
            ]
            for d in dicts:
                keys |= {k.value for k in d.keys if isinstance(k, ast.Constant)}
            # ``.values(**x)`` hides its keys: treat it as touching every protected column.
            if any(k.arg is None and not isinstance(k.value, ast.Dict) for k in call.keywords):
                keys |= PROTECTED
        yield node, where, keys


def violations(source: str, rel: Path) -> list[str]:
    """Every way ``source`` (at ``rel``) writes lifecycle/trust or updates scoring unsafely."""
    if rel == LIFECYCLE:
        return []
    tree = ast.parse(source)
    found: set[str] = set()

    def flag(node: ast.AST, why: str) -> None:
        found.add(f"{rel}:{node.lineno}: {why}")

    for node, where, keys in _update_chains(tree):
        if keys & PROTECTED:
            flag(node, f"update(MemoryRecord) writes {sorted(keys & PROTECTED)}: use lifecycle")
        if rel not in SCORING_UPDATERS:
            flag(node, "update(MemoryRecord) outside the scoring modules")
        if "MemoryRecord.company_id" not in where:
            flag(node, "update(MemoryRecord) is not tenant-scoped")
        if keys - SCORING - PROTECTED:
            flag(
                node, f"update(MemoryRecord) writes unexpected {sorted(keys - SCORING - PROTECTED)}"
            )
        if keys & RANKING and "MemoryRecord.status" not in where:
            flag(node, "ranking update is not lifecycle-safe: filter on MemoryRecord.status")

    for node in ast.walk(tree):
        targets = (
            node.targets
            if isinstance(node, ast.Assign)
            else [node.target]
            if isinstance(node, (ast.AugAssign, ast.AnnAssign))
            else []
        )
        for t in targets:
            if isinstance(t, ast.Attribute) and t.attr in PROTECTED - {"status"}:
                flag(node, f"assigns .{t.attr}")
        if (
            isinstance(node, ast.Call)
            and _name(node.func) == "setattr"
            and len(node.args) > 1
            and isinstance(node.args[1], ast.Constant)
            and node.args[1].value in PROTECTED
        ):
            flag(node, f"setattr({node.args[1].value!r})")
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            sql = " ".join(node.value.lower().split())
            if sql.startswith("update memory_records set") and any(
                f"{col} =" in sql or f"{col}=" in sql for col in PROTECTED
            ):
                flag(node, "raw SQL writes lifecycle/trust")
        if (
            isinstance(node, ast.Call)
            and _name(node.func) == "MemoryRecord"
            and rel not in {INGEST, Path("nexus/models/memory.py")}
            and {k.arg for k in node.keywords} & PROTECTED
        ):
            flag(node, "MemoryRecord(...) picks a lifecycle outside ingest")

    # ``.status`` is too common an attribute to ban everywhere; inside a function that
    # handles MemoryRecord, assigning it is a lifecycle write.
    for fn in ast.walk(tree):
        if isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)) and any(
            _name(n) == "MemoryRecord" for n in ast.walk(fn)
        ):
            for node in ast.walk(fn):
                if isinstance(node, ast.Assign) and any(
                    isinstance(t, ast.Attribute) and t.attr == "status" for t in node.targets
                ):
                    flag(node, "assigns .status in a function that handles MemoryRecord")
    return sorted(found)


def test_production_code_cannot_write_lifecycle_or_trust():
    offenders = []
    for base in (ROOT / "src", ROOT / "scripts"):
        for path in base.rglob("*.py"):
            rel = path.relative_to(ROOT / "src" if base.name == "src" else ROOT)
            if rel not in MIGRATION_EXCEPTIONS:
                offenders += violations(path.read_text(encoding="utf-8"), rel)
    assert not offenders, (
        "lifecycle/trust change only through nexus.memory.lifecycle:\n" + "\n".join(offenders)
    )


def test_operator_edit_cannot_name_a_protected_field():
    from nexus.api.routes.memory_global import MemoryUpdate

    assert not set(MemoryUpdate.model_fields) & PROTECTED


def test_guard_catches_direct_lifecycle_and_trust_writes():
    head = (
        "def f(db, c, kw):\n    db.execute(update(MemoryRecord)"
        ".where(MemoryRecord.company_id == c)"
    )
    bad = {
        "values status": f"{head}.values(status='active'))\n",
        "values dict": f"{head}.values({{'trust_state': 'verified'}}))\n",
        "values spread": f"{head}.values(**kw))\n",
        "attr trust": "def f(r):\n    r.trust_state = 'verified'\n",
        "attr changed_by": "def f(r):\n    r.lifecycle_changed_by = 'me'\n",
        "attr supersedes": "def f(r):\n    r.supersedes_id = None\n",
        "attr status": "def f(r):\n    m = MemoryRecord\n    r.status = 'active'\n",
        "setattr": "def f(r):\n    setattr(r, 'status', 'active')\n",
        "raw sql": "Q = \"UPDATE memory_records SET status = 'active' WHERE id = :i\"\n",
        "constructor": "def f():\n    return MemoryRecord(status='active')\n",
    }
    for name, source in bad.items():
        assert violations(source, Path("nexus/api/routes/evil.py")), name


def test_guard_rejects_untenanted_unfiltered_or_misplaced_scoring_updates():
    scorer = Path("nexus/runtime/orchestrator.py")
    untenanted = (
        "def f(db):\n    db.execute(update(MemoryRecord)"
        ".where(MemoryRecord.id == 1).values(tier='cold'))\n"
    )
    no_status = (
        "def f(db, c):\n    db.execute(update(MemoryRecord)"
        ".where(MemoryRecord.company_id == c).values(importance=0.1))\n"
    )
    assert any("tenant" in v for v in violations(untenanted, scorer))
    assert any("lifecycle-safe" in v for v in violations(no_status, scorer))
    tier_only = no_status.replace("importance=0.1", "tier='cold'")
    assert not violations(tier_only, scorer)
    assert any(
        "outside the scoring" in v for v in violations(tier_only, Path("nexus/api/routes/x.py"))
    )


def test_guard_allows_lifecycle_module_and_safe_scoring_updates():
    transition = (
        "def t(db, c):\n    db.execute(update(MemoryRecord).where(MemoryRecord.company_id == c)"
        ".values(status='archived', lifecycle_changed_by='x'))\n    r.trust_state = 'asserted'\n"
    )
    assert not violations(transition, LIFECYCLE)
    safe = (
        "def f(db, c):\n    db.execute(update(MemoryRecord).where(MemoryRecord.company_id == c,"
        " MemoryRecord.status.in_(PROMPT_STATUSES))"
        ".values(importance=MemoryRecord.importance * 0.95,"
        " access_count=1, last_accessed_at=None, updated_at=None))\n"
    )
    assert not violations(safe, Path("nexus/memory/layered_persistent.py"))
