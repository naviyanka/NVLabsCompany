# ruff: noqa: E501
"""Architecture guards: the three Hermes paths stay separate.

hermes / hermes-cli: advisory chat, no governed tools. hermes-native: the API adapter
with native governed tool calls. Hermes ACP: an unsafe prototype, absent and unselectable.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from nexus.adapters import hermes_adapter, hermes_provider
from nexus.adapters.registry import AdapterRegistry
from nexus.adapters.uastl import PROVIDERS, ProviderResolutionError, resolve_provider

SRC = Path(__file__).resolve().parent.parent / "src" / "nexus"
GOVERNED_MODULES = ("mcp_server", "manager_tools", "ceo_tools", "manager_bridge", "hermes_provider")


def _tree(path):
    return ast.parse(Path(path).read_text(encoding="utf-8"))


def _names(tree):
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            yield node.id
        elif isinstance(node, ast.Attribute):
            yield node.attr
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            yield node.name
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            yield getattr(node, "module", None) or ""
            for alias in node.names:
                yield alias.name


def test_the_native_adapter_never_touches_the_legacy_adapter_or_hermes_state():
    tree = _tree(hermes_provider.__file__)
    names = set(_names(tree))
    assert not names & {"hermes_adapter", "HermesAdapter", "_parse_tool_calls", "register_tool",
                        "_tool_registry", "GOVERNED_TOOL_PREFIXES"}
    strings = [n.value for n in ast.walk(tree) if isinstance(n, ast.Constant) and isinstance(n.value, str)]
    assert not any(t in s for s in strings for t in ("auth.json", "HERMES_HOME", "config.yaml"))
    assert not hasattr(hermes_provider.HermesProviderAdapter, "register_tool")


def test_the_legacy_adapter_never_reaches_governed_services():
    names = set(_names(_tree(hermes_adapter.__file__)))
    assert not names & {"MCPServer", "manager_tools", "ceo_tools", "manager_bridge", "hermes_provider",
                        "HermesProviderAdapter"}


def test_the_legacy_adapter_refuses_every_governed_tool():
    adapter = hermes_adapter.HermesAdapter()
    for name in ("ceo_list_managers", "manager_delegate_task", "organization_get_snapshot"):
        with pytest.raises(ValueError):
            adapter.register_tool(name, lambda: None, {})


async def test_tool_like_text_from_the_legacy_adapter_runs_nothing():
    adapter = hermes_adapter.HermesAdapter()
    out = await adapter._execute_tool("ceo_list_managers", {})
    assert out["status"] == "not_found"


def test_each_hermes_path_has_its_own_adapter_and_acp_is_not_selectable():
    registry = AdapterRegistry()
    assert type(registry.create_adapter("hermes")).__name__ == "HermesAdapter"
    assert type(registry.create_adapter("hermes_native")).__name__ == "HermesProviderAdapter"
    assert resolve_provider("hermes")[0] == "hermes"
    assert resolve_provider("hermes-cli")[0] == "hermes"
    assert resolve_provider("hermes-native")[0] == "hermes_native"
    assert not [k for k in PROVIDERS if "acp" in k]
    with pytest.raises(ProviderResolutionError):
        resolve_provider("hermes-acp")
    sources = "".join(p.read_text(encoding="utf-8") for p in SRC.rglob("*.py"))
    assert "hermes_acp" not in sources and "HermesACP" not in sources


def test_the_tool_gate_is_an_operator_setting_only():
    from nexus.config import Settings

    assert Settings.model_fields["hermes_native_tools_enabled"].default is False
    source = Path(hermes_provider.__file__).read_text(encoding="utf-8")
    assert "config.get(\"hermes_native" not in source and "config[\"hermes_native" not in source
