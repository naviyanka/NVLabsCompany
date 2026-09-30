"""Memory rows are created only by nexus.memory.ingest and never hard-deleted.

A source scan, so a new writer that bypasses ingest (redaction, hashing, provenance,
idempotency) or a new hard delete fails here instead of shipping.
"""

import ast
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent / "src" / "nexus"
CREATORS = {Path("memory/ingest.py"), Path("models/memory.py")}
# MemoryStore builds transient, never-persisted rows to answer from its hot cache.
TRANSIENT_VIEWS = Path("memory/store.py")


def _calls():
    for path in SRC.rglob("*.py"):
        rel = path.relative_to(SRC)
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Call):
                yield rel, node


def _name(node: ast.expr) -> str:
    return node.id if isinstance(node, ast.Name) else node.attr if isinstance(node, ast.Attribute) else ""


def _mentions_memory_record(node: ast.Call) -> bool:
    return any(_name(a) == "MemoryRecord" for a in node.args)


def test_only_ingest_constructs_memory_records():
    offenders = sorted(
        f"{rel}:{node.lineno}"
        for rel, node in _calls()
        if _name(node.func) == "MemoryRecord" and rel not in CREATORS | {TRANSIENT_VIEWS}
    )
    assert not offenders, f"construct MemoryRecord only in nexus.memory.ingest: {offenders}"


def test_memory_store_never_adds_rows_itself():
    adds = [
        node.lineno
        for rel, node in _calls()
        if rel == TRANSIENT_VIEWS and isinstance(node.func, ast.Attribute) and node.func.attr == "add"
    ]
    assert not adds, f"MemoryStore persists through ingest_memory only: lines {adds}"


def test_no_memory_record_insert_or_hard_delete():
    offenders = sorted(
        f"{rel}:{node.lineno}"
        for rel, node in _calls()
        if _name(node.func) in {"insert", "delete"} and _mentions_memory_record(node)
    )
    assert not offenders, f"archive through nexus.memory.lifecycle instead: {offenders}"


def test_no_session_delete_of_a_memory_row():
    """`await db.delete(record)` on a memory row: the row must be archived, not removed."""
    offenders = []
    for path in SRC.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        if "MemoryRecord" not in text:
            continue
        for node in ast.walk(ast.parse(text)):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "delete"
                and _name(node.func.value) != "router"  # an HTTP route decorator, not a row delete
            ):
                offenders.append(f"{path.relative_to(SRC)}:{node.lineno}")
    assert not offenders, f"hard delete in a module that owns memory rows: {sorted(offenders)}"
