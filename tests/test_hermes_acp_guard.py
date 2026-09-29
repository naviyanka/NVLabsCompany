"""Architecture guard: production code never reconfigures or borrows Hermes' own state."""

from __future__ import annotations

import ast
import re
from pathlib import Path

from nexus.adapters.hermes_adapter import GOVERNED_TOOL_PREFIXES
from nexus.services import org_snapshot
from nexus.tools.ceo_tools import CEO_TOOLS
from nexus.tools.manager_tools import MANAGER_TOOLS

SRC = Path(__file__).resolve().parent.parent / "src" / "nexus"
MCP_MUTATION = re.compile(r"\bmcp\s+(add|remove|rm)\b")
# The one place that names Hermes' home files: a deny list for agent file access.
HOME_FILE_EXEMPT = {"adapters/hermes_adapter.py"}
HOME_TOKENS = ("HERMES_HOME", "auth.json")


def _constants(path: Path):
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            yield node.value
        if isinstance(node, (ast.List, ast.Tuple)):
            words = [e.value for e in node.elts if isinstance(e, ast.Constant)]
            for a, b in zip(words, words[1:]):
                if a == "mcp" and b in ("add", "remove", "rm"):
                    yield f"mcp {b}"


def _files():
    return [p for p in SRC.rglob("*.py")]


def test_production_never_adds_or_removes_hermes_mcp_servers():
    bad = [
        str(p.relative_to(SRC))
        for p in _files()
        if any(MCP_MUTATION.search(s) for s in _constants(p))
    ]
    assert bad == []


def test_production_never_touches_hermes_home_or_credentials():
    bad = []
    for p in _files():
        rel = p.relative_to(SRC).as_posix()
        if rel in HOME_FILE_EXEMPT:
            continue
        if any(tok in s for s in _constants(p) for tok in HOME_TOKENS):
            bad.append(rel)
    assert bad == []


def test_governed_tools_stay_out_of_free_form_tool_call_parsing():
    governed = {*CEO_TOOLS, *MANAGER_TOOLS, org_snapshot.TOOL}
    assert all(name.startswith(GOVERNED_TOOL_PREFIXES) for name in governed)
