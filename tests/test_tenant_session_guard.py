"""Architecture guard: no raw app session without a stated reason.

``async_session_factory()`` opens a session with no RLS tenant. On PostgreSQL,
under the application role, it reads nothing from a tenant-owned table and every
write to one fails the policy's WITH CHECK. In background code that failure is
often only logged. Tenant-owned work therefore goes through
``tenant_session(company_id)`` or ``tenant_session_factory(company_id)``, and
cross-tenant maintenance through ``system_session``.

The remaining raw uses are listed in ``ALLOWED``, each with a category and the
reason it is not tenant work. See ``docs/security/TENANT_SESSION_AUDIT.md``.
"""

import ast
import uuid
from pathlib import Path

from sqlmodel import select

from nexus import database

SRC = Path(__file__).resolve().parents[1] / "src" / "nexus"

# A raw session is correct only for work that is not tenant work:
DISCOVERY = "discovery"  # a bounded read that finds the tenant, or the credential behind it
SYSTEM = "system"  # tables that are not tenant-scoped (global catalogues, kill switch, ...)
BOOTSTRAP = "bootstrap"  # startup and seed code that runs before any tenant exists
CATEGORIES = {DISCOVERY, SYSTEM, BOOTSTRAP}

# "path::qualified.function" -> (category, why a session with no tenant is correct there)
ALLOWED: dict[str, tuple[str, str]] = {
    "auth/middleware.py::AuthenticationMiddleware._resolve": (
        DISCOVERY,
        "resolves the credential to a principal before the tenant is known",
    ),
    "tools/mcp_server.py::authenticate": (
        DISCOVERY,
        "resolves the MCP API key before the tenant is known",
    ),
    "api/routes/audit.py::verify_audit_chain": (
        SYSTEM,
        "verifies the one global audit chain, which spans every company",
    ),
    "governance/audit_persistent.py::PersistentAuditLogger._sessions": (
        SYSTEM,
        "default for chain verification and retention when no factory is given",
    ),
    "runtime/checkpoint.py::save_checkpoint_nonblocking": (
        SYSTEM,
        "execution_checkpoints is not tenant-scoped",
    ),
    "runtime/watchdog_service.py::_file_decision": (
        SYSTEM,
        "decision queues are not tenant-scoped; the queue row carries company_id",
    ),
    "tools/factory.py::_access_session": (
        SYSTEM,
        "used only when no company is known; tenant_session otherwise",
    ),
    "tools/registry.py::ToolRegistry.__init__": (
        SYSTEM,
        "default for the global tools catalogue; tenant callers pass tenant_session_factory",
    ),
    "triggers/executor.py::TriggerExecutor._factory": (
        SYSTEM,
        "default for trigger execution records, which are not tenant-scoped",
    ),
    "auth/bootstrap.py::_main": (BOOTSTRAP, "first-admin CLI, before any tenant exists"),
    "ceo_knowledge_seed.py::seed_ceo_knowledge": (BOOTSTRAP, "dev seed of non-RLS memory_records"),
    "demo/seed.py::_main": (BOOTSTRAP, "dev seed CLI, run as the database owner"),
    "main.py::lifespan": (
        BOOTSTRAP,
        "default-company seed and budget flush (companies), kill switch and circuit breaker "
        "(global tables), secret backend (stored_secrets): none is tenant-scoped",
    ),
}


def _raw_session_uses(root: Path = SRC) -> set[str]:
    """Every function under ``root`` that names ``async_session_factory``.

    Only ``Name`` and ``Attribute`` nodes count, so imports (alias nodes),
    comments and docstrings do not. ``database.py`` defines the factory and the
    tenant/system wrappers around it.
    """
    found: set[str] = set()

    def walk(node: ast.AST, rel: str, scope: list[str]) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                walk(child, rel, [*scope, child.name])
                continue
            if (isinstance(child, ast.Name) and child.id == "async_session_factory") or (
                isinstance(child, ast.Attribute) and child.attr == "async_session_factory"
            ):
                found.add(f"{rel}::{'.'.join(scope) or '<module>'}")
            walk(child, rel, scope)

    for path in root.rglob("*.py"):
        rel = path.relative_to(root).as_posix()
        if rel != "database.py":
            walk(ast.parse(path.read_text(encoding="utf-8")), rel, [])
    return found


def test_scanner_ignores_imports_comments_and_strings(tmp_path):
    pkg = tmp_path / "nexus"
    pkg.mkdir()
    (pkg / "mod.py").write_text(
        '"""async_session_factory() in a docstring."""\n'
        "from nexus.database import async_session_factory  # async_session_factory\n"
        "def quiet():\n"
        "    return 'async_session_factory'\n"
        "def loud():\n"
        "    return async_session_factory()\n"
        "class K:\n"
        "    def m(self):\n"
        "        return database.async_session_factory\n",
        encoding="utf-8",
    )
    assert _raw_session_uses(pkg) == {"mod.py::loud", "mod.py::K.m"}


def test_every_exception_has_a_category_and_reason():
    for key, (category, reason) in ALLOWED.items():
        assert category in CATEGORIES, key
        assert reason.strip(), key


def test_no_raw_session_outside_the_allowlist():
    unexplained = sorted(_raw_session_uses() - ALLOWED.keys())
    assert unexplained == [], (
        "raw async_session_factory() use without a stated reason; use tenant_session / "
        "tenant_session_factory for tenant work, or add it to ALLOWED with a category"
    )


def test_allowlist_has_no_stale_entries():
    assert sorted(ALLOWED.keys() - _raw_session_uses()) == []


async def test_tenant_session_factory_works_on_sqlite(tmp_path, monkeypatch):
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from sqlmodel import SQLModel
    from sqlmodel.ext.asyncio.session import AsyncSession

    from nexus.models.company import Company

    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 't.db'}")
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all, tables=[Company.__table__])
    monkeypatch.setattr(
        database,
        "async_session_factory",
        async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False),
    )
    cid = uuid.uuid4()
    factory = database.tenant_session_factory(cid)

    async with factory() as session:
        session.add(Company(id=cid, name="SQLite"))
        await session.commit()
        session.add(Company(name="After commit"))
        await session.commit()
    async with factory() as session:
        names = await session.exec(select(Company.name).order_by(Company.name))
        assert list(names) == ["After commit", "SQLite"]
    await engine.dispose()
