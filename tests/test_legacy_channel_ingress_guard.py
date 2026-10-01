"""Inbound channel routes never mutate NEXUS state on their own authority.

A provider webhook or an API key authenticates the sending service, not the human
who wrote the message. Until a channel route can map the sender to an active NEXUS
user and run normal authorization (ADR 0006), it must not create Tasks, Goals,
ChatTurns, tool invocations or approvals, and must not open a tenant session or
call out with a bot token. A source scan, so a new or revived legacy channel route
fails here instead of shipping.
"""

import ast
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent / "src" / "nexus"
ROUTES = SRC / "api" / "routes"
CHANNEL_PREFIX = "/api/v1/channels/"

MUTATING_MODELS = {"Task", "Goal", "ChatTurn", "ToolInvocation", "Approval"}
FORBIDDEN_NAMES = MUTATING_MODELS | {
    "tenant_session",
    "CurrentCompanyId",
    "get_current_company_id",
    "guarded_call",
    "ToolExecutor",
    "ChannelRouter",
    "handle_inbound",
}
FORBIDDEN_IMPORT_ROOTS = {"httpx", "requests", "aiohttp", "nexus.models", "nexus.tools"}


def _tree(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"))


def _channel_route_modules() -> list[Path]:
    """Route modules that register any ``/api/v1/channels/...`` path."""
    return sorted(
        path
        for path in ROUTES.glob("*.py")
        if any(
            isinstance(node, ast.Constant)
            and isinstance(node.value, str)
            and node.value.startswith(CHANNEL_PREFIX)
            for node in ast.walk(_tree(path))
        )
    )


def _imports(tree: ast.Module) -> set[str]:
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            found.add(node.module)
            found.update(f"{node.module}.{alias.name}" for alias in node.names)
    return found


def _names(tree: ast.Module) -> set[str]:
    used = {
        n.id if isinstance(n, ast.Name) else n.attr
        for n in ast.walk(tree)
        if isinstance(n, ast.Name | ast.Attribute)
    }
    imported = {
        alias.name.split(".")[-1]
        for n in ast.walk(tree)
        if isinstance(n, ast.ImportFrom)
        for alias in n.names
    }
    return used | imported


def test_the_scan_finds_the_known_legacy_channel_routes():
    """A rename or move must not turn the guard below into a vacuous pass."""
    names = {p.name for p in _channel_route_modules()}
    assert {"slack_events.py", "telegram_bot.py"} <= names


def test_channel_routes_cannot_mutate_state_or_reach_tools():
    offenders = []
    for path in _channel_route_modules():
        tree = _tree(path)
        for name in sorted(_names(tree) & FORBIDDEN_NAMES):
            offenders.append(f"{path.name}: uses {name}")
        for module in sorted(_imports(tree)):
            if any(module == r or module.startswith(f"{r}.") for r in FORBIDDEN_IMPORT_ROOTS):
                offenders.append(f"{path.name}: imports {module}")
    assert not offenders, (
        "inbound channel routes need a verified NEXUS principal and a service boundary "
        f"before they may mutate state (ADR 0006): {offenders}"
    )


def test_channel_route_handlers_take_no_request_input():
    """Handlers that never accept a Request, body model or dependency cannot read a payload."""
    offenders = []
    for path in _channel_route_modules():
        for node in ast.walk(_tree(path)):
            if isinstance(node, ast.AsyncFunctionDef | ast.FunctionDef) and node.decorator_list:
                args = node.args
                if args.args or args.kwonlyargs or args.posonlyargs or args.vararg or args.kwarg:
                    offenders.append(f"{path.name}:{node.name}")
    assert not offenders, f"legacy channel handlers must not read the request: {offenders}"


def test_no_route_feeds_provider_input_into_channel_router_inbound():
    """``ChannelRouter.handle_inbound`` persists a Message as an agent; no route may call it."""
    offenders = sorted(
        path.name
        for path in ROUTES.glob("*.py")
        if "handle_inbound" in _names(_tree(path))
    )
    assert not offenders, f"routes must not call handle_inbound: {offenders}"
