"""One CEO authority: ``agents.is_ceo``, changed only by ``ceo_service``.

The static half walks the AST of every module under src/nexus and fails when a
second source of CEO authority, a privileged ``<tool_call>`` path or an agent
placement that bypasses the hierarchy service appears. The runtime half checks
that the legacy Hermes adapter grants nothing: its config cannot make a CEO,
it refuses the governed tool names, and model text that looks like a tool call
executes nothing unless the server registered that tool.
"""

from __future__ import annotations

import ast
import uuid
from pathlib import Path

import pytest

from nexus.adapters.hermes_adapter import HermesAdapter
from nexus.runtime.adapter import AgentSession
from nexus.tools.ceo_tools import CEO_TOOLS
from nexus.tools.manager_tools import MANAGER_TOOLS

SRC = Path(__file__).resolve().parent.parent / "src" / "nexus"

# Only these modules may read the designation attribute; everyone else asks
# ceo_service.is_ceo(), which re-reads it in the caller's transaction.
DESIGNATION_READERS = {
    "services/ceo_service.py",
    "services/org_snapshot.py",  # the snapshot's ceo_id
    "api/routes/chat.py",  # withholds the legacy Hermes tools from the CEO
}
# Only this module sets the designation or moves reporting lines in bulk.
DESIGNATION_WRITER = "services/ceo_service.py"
MANAGER_WRITERS = {DESIGNATION_WRITER, "api/routes/agents.py", "services/agent_service.py"}
# Agent rows built outside a real placement: a transient copy and the demo seed.
UNPLACED_AGENT_BUILDERS = {"services/session_service.py", "demo/seed.py"}
HERMES = "adapters/hermes_adapter.py"
HERMES_FORBIDDEN_IMPORTS = ("ceo_service", "ceo_tools", "manager_tools", "manager_bridge",
                            "manager_service", "hiring_service", "approval", "vault", "secret")


def _modules():
    for path in sorted(SRC.rglob("*.py")):
        yield path.relative_to(SRC).as_posix(), ast.parse(path.read_text(encoding="utf-8"))


def _is_ceo_string(node):
    return isinstance(node, ast.Constant) and isinstance(node.value, str) and \
        node.value.strip().lower() == "ceo"


def _violations():
    found = []
    for name, tree in _modules():
        calls = {id(n.func) for n in ast.walk(tree) if isinstance(n, ast.Call)}
        for node in ast.walk(tree):
            where = f"{name}:{getattr(node, 'lineno', '?')}"
            if isinstance(node, ast.Attribute) and node.attr == "is_ceo":
                if isinstance(node.ctx, ast.Store) and name != DESIGNATION_WRITER:
                    found.append(f"{where} sets is_ceo")
                elif id(node) not in calls and name not in DESIGNATION_READERS | {
                        DESIGNATION_WRITER}:
                    found.append(f"{where} reads is_ceo; use ceo_service.is_ceo()")
            if isinstance(node, ast.Attribute) and node.attr == "manager_id" and \
                    isinstance(node.ctx, ast.Store) and name not in MANAGER_WRITERS:
                found.append(f"{where} sets manager_id outside the hierarchy service")
            if isinstance(node, ast.keyword) and node.arg == "is_ceo" and \
                    name != DESIGNATION_WRITER:
                found.append(f"{where} passes is_ceo=")
            if isinstance(node, ast.Subscript) and isinstance(node.slice, ast.Constant) and \
                    node.slice.value == "is_ceo":
                found.append(f"{where} reads a config is_ceo")
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                if node.func.attr == "get" and node.args and \
                        isinstance(node.args[0], ast.Constant) and node.args[0].value == "is_ceo":
                    found.append(f"{where} reads a config is_ceo")
                if node.func.attr == "values" and name not in MANAGER_WRITERS and \
                        any(k.arg == "manager_id" for k in node.keywords):
                    found.append(f"{where} bulk-sets manager_id")
            if isinstance(node, ast.Compare):
                operands = [node.left, *node.comparators]
                for operand in list(operands):
                    if isinstance(operand, (ast.Tuple, ast.List, ast.Set)):
                        operands.extend(operand.elts)
                if any(_is_ceo_string(o) for o in operands):
                    found.append(f"{where} compares a role/title/string to 'ceo'")
            if isinstance(node, ast.Constant) and isinstance(node.value, str) and \
                    "<tool_call" in node.value and name != HERMES:
                found.append(f"{where} handles <tool_call> text outside the Hermes adapter")
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and \
                    node.func.attr == "register_tool" and name != HERMES:
                arg = node.args[0] if node.args else None
                # ToolRegistry.register_tool(ToolDefinition(...)) is the governed
                # registry; an adapter's register_tool(name, handler) is free-form.
                if not isinstance(arg, ast.Call) and not (
                        name == "api/routes/chat.py" and isinstance(arg, ast.Name)
                        and arg.id == "OBSIDIAN_NOTE_REPLACE_NAME"):
                    found.append(f"{where} registers a free-form tool")
        for fn in ast.walk(tree):
            if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            called = {getattr(n.func, "id", getattr(n.func, "attr", None))
                      for n in ast.walk(fn) if isinstance(n, ast.Call)}
            if "Agent" in called and "resolve_manager" not in called and \
                    name not in UNPLACED_AGENT_BUILDERS:
                found.append(f"{name}:{fn.lineno} {fn.name} creates an Agent without "
                             "ceo_service.resolve_manager")
        if name == HERMES:
            for node in ast.walk(tree):
                if isinstance(node, (ast.Import, ast.ImportFrom)):
                    names = [getattr(node, "module", None) or ""] + [a.name for a in node.names]
                    if any(bad in n for n in names for bad in HERMES_FORBIDDEN_IMPORTS):
                        found.append(f"{HERMES}:{node.lineno} imports a privileged module")
    return found


def test_one_ceo_authority_and_no_privileged_tool_call_path():
    assert _violations() == []


def test_the_guard_fires(tmp_path, monkeypatch):
    """A guard that never fails certifies nothing: each rule sees a probe."""
    probe = tmp_path / "api" / "routes"
    probe.mkdir(parents=True)
    (probe / "rogue.py").write_text(
        "async def hire(db, agent, cfg, body):\n"
        "    if agent.role.lower() == 'ceo' or cfg.get('is_ceo') or agent.is_ceo:\n"
        "        agent.is_ceo = True\n"
        "    agent.manager_id = None\n"
        "    db.add(Agent(name='x', is_ceo=True))\n"
        "    adapter.register_tool('ceo_request_hire', hire)\n"
        "    return '<tool_call>'\n",
        encoding="utf-8",
    )
    monkeypatch.setitem(globals(), "SRC", tmp_path)
    text = "\n".join(_violations())
    for rule in ("sets is_ceo", "reads is_ceo", "passes is_ceo=", "reads a config is_ceo",
                 "compares a role/title/string to 'ceo'", "sets manager_id",
                 "creates an Agent without", "registers a free-form tool", "<tool_call>"):
        assert rule in text, rule


# --- legacy Hermes adapter at runtime ----------------------------------------------------------


def _session(**config):
    return AgentSession(session_id=str(uuid.uuid4()), agent_id=uuid.uuid4(),
                        adapter_type="hermes", config=config)


@pytest.fixture
def hermes(monkeypatch):
    adapter = HermesAdapter()
    replies: list[str] = []

    async def reply(session, messages):
        return {"success": True, "output": replies.pop(0)}

    monkeypatch.setattr(adapter, "_load_nous_token", lambda: "")
    monkeypatch.setattr(adapter, "_check_ollama", lambda host, model: _true())
    monkeypatch.setattr(adapter, "_call_ollama", reply)
    return adapter, replies


async def _true():
    return True


GOVERNED = sorted(set(CEO_TOOLS) | set(MANAGER_TOOLS))


@pytest.mark.parametrize("name", GOVERNED)
def test_hermes_refuses_governed_tools(name):
    with pytest.raises(ValueError, match="governed tool"):
        HermesAdapter().register_tool(name, lambda **kw: None)


async def test_legacy_config_grants_no_ceo_mode(hermes):
    adapter, _ = hermes
    session = _session(is_ceo=True, role="ceo", title="CEO")
    await adapter._do_create_session(session)
    assert "is_ceo" not in session.metadata
    assert "CEO" not in session.metadata["system_prompt"]
    assert adapter._tool_registry == {}


async def test_tool_call_text_executes_nothing_and_chat_still_works(hermes):
    adapter, replies = hermes
    session = _session()
    await adapter._do_create_session(session)
    hire = '<tool_call>{"name": "ceo_request_hire", "arguments": {"role": "cfo"}}</tool_call>'
    replies.extend([hire, "Hello from Hermes"])
    first = await adapter._do_execute(session, uuid.uuid4(), {"prompt": "hire a CFO"})
    assert first.success and first.output == hire and first.artifacts is None
    second = await adapter._do_execute(session, uuid.uuid4(), {"prompt": "hi"})
    assert second.success and second.output == "Hello from Hermes"
    # Beside a server-registered tool, a governed name still finds no handler.
    adapter.register_tool("obsidian_note_replace", lambda **kw: None, {"description": "note"})
    replies.extend([hire, "done"])
    third = await adapter._do_execute(session, uuid.uuid4(), {"prompt": "hire a CFO"})
    [attempt] = third.artifacts["tool_results"]
    assert attempt["result"]["status"] == "not_found"
