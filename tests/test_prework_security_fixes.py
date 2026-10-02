"""Regression tests for the pre-work fixes that precede the Agent Workspace work.

Covers: the /api/v1 SSE alias, workspace path allowlisting, the chat
``BudgetInfraUnavailable`` NameError, the governance-policy timezone NameError,
and SSRF guarding of scheduler webhooks.
"""

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from nexus.governance.ssrf_protection import guard_outbound_url
from nexus.models_router.preflight import BudgetInfraUnavailable


# --- SSE route ----------------------------------------------------------------


@pytest.mark.parametrize("path", ["/api/v1/events/stream", "/events/stream"])
def test_sse_routes_exist_and_require_auth(monkeypatch, path):
    """Both the /api/v1 path the dashboard uses and the legacy path are served (401, not 404)."""
    from nexus.config import settings
    from nexus.main import app

    # Auth answers 401 before routing, so check the schema for existence.
    assert path in app.openapi()["paths"]
    monkeypatch.setattr(settings, "auth_enabled", True)
    response = TestClient(app, raise_server_exceptions=False).get(path)
    assert response.status_code == 401


# --- Workspace path allowlist -------------------------------------------------


@pytest.fixture
def workspace_root(tmp_path, monkeypatch):
    from nexus.config import settings

    monkeypatch.setattr(settings, "workspace_roots", str(tmp_path / "{company_id}"))
    return tmp_path


def test_workspace_path_inside_tenant_root_is_accepted(workspace_root):
    from nexus.api.routes.workspaces import _resolve_workspace_path

    cid = uuid.uuid4()
    resolved = _resolve_workspace_path(str(workspace_root / str(cid) / "proj"), cid)
    assert resolved == (workspace_root / str(cid) / "proj").resolve()


@pytest.mark.parametrize(
    "make_path",
    [
        lambda root, cid, other: root / str(cid) / ".." / str(other) / "proj",  # dot-dot escape
        lambda root, cid, other: root / str(other) / "proj",  # another tenant's root
        lambda root, cid, other: root.parent,  # outside every root
        lambda root, cid, other: "   ",  # blank
    ],
)
def test_workspace_path_outside_root_is_rejected(workspace_root, make_path):
    from nexus.api.routes.workspaces import _resolve_workspace_path

    cid, other = uuid.uuid4(), uuid.uuid4()
    with pytest.raises(HTTPException) as exc:
        _resolve_workspace_path(str(make_path(workspace_root, cid, other)), cid)
    assert exc.value.status_code == 422


def test_workspace_symlink_escape_is_rejected(workspace_root, tmp_path_factory):
    from nexus.api.routes.workspaces import _resolve_workspace_path

    cid = uuid.uuid4()
    outside = tmp_path_factory.mktemp("outside")
    link = workspace_root / str(cid) / "link"
    link.parent.mkdir(parents=True)
    try:
        link.symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("symlinks not permitted on this host")
    with pytest.raises(HTTPException):
        _resolve_workspace_path(str(link), cid)


# --- chat._call_llm exception handling ------------------------------------------


def _patched_call_llm(error: Exception):
    from nexus.api.routes import chat

    agent = SimpleNamespace(
        id=uuid.uuid4(), name="A", title=None, role="dev", capabilities=[], company_id=uuid.uuid4()
    )
    registry = MagicMock(side_effect=error)
    patches = [
        patch.object(chat, "_resolve_connection", AsyncMock(return_value=None)),
        patch.object(chat, "_resolve_adapter_type", return_value=("ollama", {"model": "m"})),
        patch.object(chat, "_reserve_budget", AsyncMock(return_value=None)),
        patch.object(chat, "_settle_budget", AsyncMock()),
        patch("nexus.adapters.registry.AdapterRegistry", registry),
    ]
    return agent, patches


@pytest.mark.asyncio
async def test_call_llm_propagates_budget_infra_refusal():
    from nexus.api.routes import chat

    agent, patches = _patched_call_llm(BudgetInfraUnavailable("ledger down"))
    for p in patches:
        p.start()
    try:
        with pytest.raises(BudgetInfraUnavailable):
            await chat._call_llm(agent, "sys", "hi", [])
    finally:
        for p in patches:
            p.stop()


@pytest.mark.asyncio
async def test_call_llm_generic_error_falls_back_in_character():
    """Any other error used to hit a NameError on the except clause."""
    from nexus.api.routes import chat

    agent, patches = _patched_call_llm(RuntimeError("boom"))
    for p in patches:
        p.start()
    try:
        text, model, tokens = await chat._call_llm(agent, "sys", "hi", [])
    finally:
        for p in patches:
            p.stop()
    assert model == "fallback"
    assert text == chat.PROVIDER_UNAVAILABLE_MESSAGE  # a fixed reply: nothing from the failure


# --- Governance middleware time-window policy -----------------------------------


@pytest.mark.parametrize("rules,allowed", [({"deny_after_hour": 0}, False), ({"deny_after_hour": 24}, True)])
def test_policy_hour_window_evaluates(monkeypatch, rules, allowed):
    from nexus.api import middleware as mw

    cid = uuid.uuid4()
    monkeypatch.setitem(mw._policy_cache, cid, [{"name": "p", "rules": rules}])
    request = SimpleNamespace(scope={"path": "/api/v1/agents", "method": "GET"})
    result = mw.GovernanceMiddleware(app=None)._evaluate_policy(request, cid)
    assert result["allowed"] is allowed


# --- Webhook SSRF -----------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "url",
    [
        "http://localhost:8001/restart",
        "https://127.0.0.1/x",
        "https://10.0.0.5/x",
        "https://169.254.169.254/latest/meta-data",
        "https://[::1]/x",
        "ftp://example.com/x",
        "http://8.8.8.8/x",  # plain http to a remote host
    ],
)
async def test_guard_outbound_url_blocks_internal_targets(url):
    with pytest.raises(ValueError):
        await guard_outbound_url(url, "webhook_url")


@pytest.mark.asyncio
async def test_guard_outbound_url_allows_public_https():
    assert await guard_outbound_url("https://8.8.8.8/hook") == "https://8.8.8.8/hook"


@pytest.mark.asyncio
async def test_scheduler_does_not_post_to_blocked_webhook():
    from datetime import datetime

    from nexus.runtime import scheduler

    trigger = SimpleNamespace(
        id=uuid.uuid4(),
        company_id=uuid.uuid4(),
        name="t",
        trigger_type="webhook",
        config={"webhook_url": "http://127.0.0.1:8001/shutdown"},
    )
    db = MagicMock()
    with patch("httpx.AsyncClient") as client, patch.object(scheduler, "compute_next_fire", return_value=None):
        await scheduler._fire_trigger(db, trigger, datetime(2026, 1, 1))
    client.assert_not_called()
    execution = db.add.call_args_list[0].args[0]
    assert execution.status == "failed"


@pytest.mark.asyncio
async def test_trigger_create_rejects_blocked_webhook():
    from nexus.api.routes.triggers import _validate_webhook_config

    with pytest.raises(HTTPException) as exc:
        await _validate_webhook_config({"webhook_url": "http://localhost:8001/x"})
    assert exc.value.status_code == 422
    await _validate_webhook_config({"cron": "* * * * *"})  # no webhook: no-op
