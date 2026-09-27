"""Multi-CLI employees: one catalog, fail-closed resolution, validated hiring,
and execution through the selected CLI only.

No real CLI is spawned: PATH lookups go through a patched ``shutil.which`` and
subprocesses are mocks, so no account or provider authentication is needed.
"""

from __future__ import annotations

import subprocess
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from fastapi import FastAPI, Request
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlmodel import SQLModel, select

import nexus.adapters.cli_registry as cli_registry_mod
import nexus.models  # noqa: F401 -- registers every table on SQLModel.metadata
from nexus.adapters.cli_adapter import CLIAdapter, _filter_env
from nexus.adapters.cli_registry import (
    CLIConfigError,
    CLIRegistry,
    validate_employee_cli_config,
)
from nexus.adapters.uastl import ProviderResolutionError, resolve_provider
from nexus.api.routes import agents as agent_routes
from nexus.api.routes import hiring as hiring_routes
from nexus.api.routes import providers as provider_routes
from nexus.auth.principal import Principal
from nexus.models.agent import Agent
from nexus.models.company import Company
from nexus.tools.access import check_cli_args

REQUIRED_IDS = {
    "claude", "codex", "gemini", "agy", "kiro-cli", "freebuff", "qwen", "kimi",
    "opencode", "aider", "copilot", "goose", "crush", "pi", "hermes", "amazon-q",
    "cursor-agent", "grok",
}
DESCRIBE_FIELDS = {
    "id", "label", "adapter_type", "installed", "resolved_command", "version",
    "execution_supported", "configured", "stability", "supports_model",
    "supports_resume", "supports_interactive", "supports_worktree",
    "recommended_model", "models", "install_command", "docs_url", "notes",
}
# Installed on the fake PATH: two executable CLIs and one catalog-only CLI.
FAKE_PATH = {"codex": "/bin/codex", "agy": "/bin/agy", "kimi": "/bin/kimi"}


def _which(paths):
    return lambda name: paths.get(name)


@pytest.fixture
def fake_path(monkeypatch):
    """PATH holds FAKE_PATH; the shared registry re-detects against it."""
    monkeypatch.setattr(cli_registry_mod.shutil, "which", _which(FAKE_PATH))
    monkeypatch.setattr(cli_registry_mod, "_shared_registry", None)
    monkeypatch.setattr(CLIRegistry, "probe_version", lambda self, bid, timeout=5: "1.0.0")


# ---------------------------------------------------------------------------
# Catalog
# ---------------------------------------------------------------------------


def test_catalog_ids_unique_and_complete():
    ids = [b.id for b in CLIRegistry(auto_detect=False).get_all()]
    assert len(ids) == len(set(ids))
    assert REQUIRED_IDS <= set(ids)


def test_aliases_resolve_to_exactly_one_backend():
    registry = CLIRegistry(auto_detect=False)
    names = [n for b in registry.get_all() for n in (b.id, *b.aliases)]
    assert len(names) == len(set(names))
    assert registry.resolve_backend_id("antigravity") == "agy"
    assert registry.resolve_backend_id("kiro") == "kiro-cli"
    assert registry.resolve_backend_id("hermes-cli") == "hermes"
    assert registry.resolve_backend_id("nope") is None


def test_every_backend_is_safe_by_default():
    for b in CLIRegistry(auto_detect=False).get_all():
        assert b.command_candidates, b.id
        assert check_cli_args(list(b.safe_non_interactive_args)) is None, b.id
        argv = b.build_args("hi", model="m") if b.execution_supported else []
        assert check_cli_args(argv[1:]) is None or argv[-1] == "hi", b.id


def test_describe_has_required_fields(fake_path):
    registry = cli_registry_mod.get_cli_registry()
    for b in registry.get_all():
        assert DESCRIBE_FIELDS <= set(registry.describe(b.id)), b.id
    codex = registry.describe("codex")
    assert codex["installed"] and codex["version"] == "1.0.0"
    assert registry.describe("claude")["installed"] is False


def test_detection_uses_backend_ids_and_windows_cmd_shims(monkeypatch):
    monkeypatch.setattr(
        cli_registry_mod.shutil, "which", _which({"codex": r"C:\npm\codex.CMD"})
    )
    registry = CLIRegistry()
    assert registry.is_available("codex")
    assert registry.get_path("codex") == r"C:\npm\codex.CMD"
    assert not registry.is_available("claude")


@pytest.mark.parametrize(
    ("stdout", "stderr", "expected"),
    [("codex 0.9.1\n", "", "codex 0.9.1"), ("", "agy v2\n", "agy v2")],
)
def test_version_probe_reads_stdout_or_stderr(monkeypatch, stdout, stderr, expected):
    monkeypatch.setattr(cli_registry_mod.shutil, "which", _which({"codex": "/c", "agy": "/a"}))
    registry = CLIRegistry()
    backend = "codex" if stdout else "agy"
    done = subprocess.CompletedProcess([], 0, stdout, stderr)
    with patch.object(cli_registry_mod.subprocess, "run", return_value=done) as run:
        assert registry.probe_version(backend) == expected
        assert run.call_args.kwargs["timeout"] > 0


def test_version_probe_timeout_returns_none(monkeypatch):
    monkeypatch.setattr(cli_registry_mod.shutil, "which", _which({"codex": "/c"}))
    registry = CLIRegistry()
    boom = subprocess.TimeoutExpired("codex", 1)
    with patch.object(cli_registry_mod.subprocess, "run", side_effect=boom):
        assert registry.probe_version("codex") is None


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def _registry(paths=FAKE_PATH):
    with patch.object(cli_registry_mod.shutil, "which", _which(paths)):
        return CLIRegistry()


@pytest.mark.parametrize(
    ("config", "code"),
    [
        ({}, "CLI_BACKEND_REQUIRED"),
        ({"backend": "nope"}, "CLI_BACKEND_UNKNOWN"),
        ({"backend": "claude"}, "CLI_BACKEND_UNAVAILABLE"),
        ({"backend": "kimi"}, "CLI_BACKEND_NOT_EXECUTABLE"),
        ({"backend": "codex", "command": "/tmp/evil"}, "CLI_CONFIG_INVALID"),
        ({"backend": "codex", "executable": "C:\\evil.exe"}, "CLI_CONFIG_INVALID"),
        ({"backend": "codex", "api_key": "sk-123"}, "CLI_CONFIG_INVALID"),
        ({"backend": "codex", "extra_args": ["--dangerously-bypass-approvals-and-sandbox"]}, "CLI_ARGS_FORBIDDEN"),
        ({"backend": "codex", "autonomy_mode": "yolo"}, "CLI_AUTONOMY_REQUIRES_APPROVAL"),
    ],
)
def test_validation_refuses(config, code):
    with pytest.raises(CLIConfigError) as exc:
        validate_employee_cli_config("cli", config, "", registry=_registry())
    assert exc.value.code == code


def test_validation_normalizes_alias_and_allows_explicit_unavailable():
    config, ready = validate_employee_cli_config(
        "cli", {"backend": "antigravity"}, "gemini-x", registry=_registry()
    )
    assert config["backend"] == "agy" and ready
    config, ready = validate_employee_cli_config(
        "cli", {"backend": "claude"}, "", allow_unavailable=True, registry=_registry()
    )
    assert config["backend"] == "claude" and not ready


def test_validation_rejects_flag_shaped_model():
    with pytest.raises(CLIConfigError) as exc:
        validate_employee_cli_config("cli", {"backend": "codex"}, "--yolo", registry=_registry())
    assert exc.value.code == "CLI_MODEL_INVALID"


# ---------------------------------------------------------------------------
# Resolution
# ---------------------------------------------------------------------------


def test_canonical_cli_config_resolves_every_executable_backend():
    for b in CLIRegistry(auto_detect=False).get_all():
        key, config = resolve_provider("cli", "m", adapter_config={"backend": b.id})
        assert (key, config["backend"], config["model"]) == ("cli", b.id, "m")


@pytest.mark.parametrize(
    ("adapter_type", "config", "expected"),
    [
        ("codex", None, ("cli", "codex")),
        ("antigravity", None, ("cli", "agy")),
        ("agy", None, ("cli", "agy")),
        ("kiro-cli", None, ("cli", "kiro-cli")),
        ("kiro", None, ("cli", "kiro-cli")),
        ("cursor", None, ("cli", "cursor-agent")),
        ("cli", None, ("cli", "claude")),  # legacy cli always ran Claude Code
        ("cli", {"backend": "antigravity"}, ("cli", "agy")),
        ("cli", {"backend": "hermes"}, ("cli", "hermes")),
    ],
)
def test_legacy_and_alias_resolution(adapter_type, config, expected):
    key, resolved = resolve_provider(adapter_type, adapter_config=config)
    assert (key, resolved["backend"]) == expected


def test_distinct_api_and_cli_providers():
    assert resolve_provider("hermes")[0] == "hermes"
    assert resolve_provider("anthropic")[0] == "anthropic"
    assert resolve_provider("claude_code")[0] == "claude_code"


@pytest.mark.parametrize(
    ("adapter_type", "config"),
    [("totally-unknown", None), ("cli", {"backend": "totally-unknown"})],
)
def test_unknown_provider_never_falls_back(adapter_type, config):
    with pytest.raises(ProviderResolutionError):
        resolve_provider(adapter_type, adapter_config=config)


# ---------------------------------------------------------------------------
# Execution
# ---------------------------------------------------------------------------


def _fake_process(stdout=b"ok", stderr=b"", returncode=0):
    proc = MagicMock()
    proc.pid = None
    proc.returncode = returncode
    proc.stdin = MagicMock(write=MagicMock(), drain=AsyncMock(), close=MagicMock())
    proc.stdout = MagicMock(read=AsyncMock(side_effect=[stdout, b""]))
    proc.stderr = MagicMock(read=AsyncMock(side_effect=[stderr, b""]))
    proc.wait = AsyncMock(return_value=returncode)
    return proc


async def _run(backend, model="", tmp_path=None, payload=None, paths=None, proc=None):
    adapter = CLIAdapter()
    registry = _registry(paths or {backend: f"/bin/{backend}"})
    session = await adapter.create_session(
        uuid.uuid4(),
        {"backend": backend, "model": model, "workspace": str(tmp_path)},
    )
    proc = proc or _fake_process()
    with patch("nexus.adapters.cli_adapter.get_cli_registry", return_value=registry), patch(
        "nexus.adapters.cli_adapter.asyncio.create_subprocess_exec",
        new=AsyncMock(return_value=proc),
    ) as spawn:
        result = await adapter.execute_task(
            session, uuid.uuid4(), payload or {"prompt": "Say hi", "system_prompt": ""}
        )
    return result, spawn, proc


EXECUTABLE = sorted(b.id for b in CLIRegistry(auto_detect=False).get_all() if b.execution_supported)


@pytest.mark.parametrize("backend_id", EXECUTABLE)
async def test_each_executable_backend_spawns_its_own_cli(backend_id, tmp_path):
    result, spawn, proc = await _run(backend_id, model="m1", tmp_path=tmp_path)
    assert result.success, result.error
    argv = list(spawn.call_args.args)
    backend = CLIRegistry(auto_detect=False).get_backend(backend_id)
    assert argv == backend.build_args("Say hi", model="m1", executable=f"/bin/{backend_id}")
    assert "shell" not in spawn.call_args.kwargs
    if backend.supports_model:
        assert argv[argv.index(backend.model_flag) + 1] == "m1"
    else:
        assert "m1" not in argv
    if backend.prompt_transport == "stdin":
        assert "Say hi" not in argv
        proc.stdin.write.assert_called_once()
    else:
        assert argv[-1] == "Say hi"
    meta = next(a for a in result.artifacts if a.get("type") == "cli_execution")
    assert meta["adapter"] == "cli" and meta["backend"] == backend_id
    assert meta["model"] == "m1" and meta["exit_code"] == 0
    assert {"executable", "version", "duration_ms", "session_id", "task_id"} <= set(meta)


async def test_catalog_only_backend_is_refused(tmp_path):
    with pytest.raises(ValueError):
        await _run("kimi", tmp_path=tmp_path)


async def test_forbidden_extra_args_are_refused(tmp_path):
    result, spawn, _ = await _run(
        "codex",
        tmp_path=tmp_path,
        payload={"prompt": "x", "args": ["--dangerously-bypass-approvals-and-sandbox"]},
    )
    assert not result.success
    spawn.assert_not_called()


async def test_cmd_shim_refuses_metacharacters(tmp_path):
    result, spawn, _ = await _run(
        "agy",
        tmp_path=tmp_path,
        payload={"prompt": 'hi" & del *', "system_prompt": ""},
        paths={"agy": r"C:\npm\agy.cmd"},
    )
    assert not result.success and "batch" in result.error.lower()
    spawn.assert_not_called()


async def test_nonzero_exit_returns_structured_error(tmp_path):
    result, _, _ = await _run(
        "codex", tmp_path=tmp_path, proc=_fake_process(b"", b"auth required", 2)
    )
    assert not result.success and "auth required" in result.error
    meta = next(a for a in result.artifacts if a.get("type") == "cli_execution")
    assert meta["exit_code"] == 2


def test_env_filter_strips_secrets_but_keeps_allowlisted():
    env = {
        "PATH": "/bin",
        "OPENAI_API_KEY": "sk",
        "GITHUB_TOKEN": "gh",
        "MY_SERVICE_SECRET": "s",
        "DATABASE_URL": "db",
        "HOME": "/h",
    }
    assert _filter_env(env, ["OPENAI_API_KEY"]) == {
        "PATH": "/bin",
        "OPENAI_API_KEY": "sk",
        "HOME": "/h",
    }


async def test_spawned_env_honors_operator_allowlist_only(tmp_path, monkeypatch):
    from nexus.config import settings

    monkeypatch.setenv("CUSTOM_PROVIDER_API_KEY", "custom-provider-key")
    monkeypatch.setenv("OTHER_API_KEY", "must-not-leak")
    monkeypatch.setattr(settings, "cli_env_allowlist", " CUSTOM_PROVIDER_API_KEY , ")
    result, spawn, _ = await _run("codex", tmp_path=tmp_path)
    assert result.success, result.error
    env = spawn.call_args.kwargs["env"]
    assert env["CUSTOM_PROVIDER_API_KEY"] == "custom-provider-key"
    assert "OTHER_API_KEY" not in env


# ---------------------------------------------------------------------------
# Hiring and provider API over HTTP
# ---------------------------------------------------------------------------


@pytest.fixture
async def world(tmp_path, monkeypatch, fake_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'cli.db'}")
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    import nexus.database as database

    monkeypatch.setattr(database, "async_session_factory", factory)
    acme = Company(name="Acme")
    async with factory() as db:
        db.add(acme)
        await db.commit()

    principals = {
        "viewer": Principal(kind="user", company_id=acme.id, role="viewer", user_id=uuid.uuid4()),
        "manager": Principal(kind="user", company_id=acme.id, role="manager", user_id=uuid.uuid4()),
    }
    app = FastAPI()
    for router in (agent_routes.router, hiring_routes.router, provider_routes.router):
        app.include_router(router)

    @app.middleware("http")
    async def as_principal(request: Request, call_next):
        request.state.principal = principals[request.headers.get("x-test-principal", "manager")]
        return await call_next(request)

    client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")
    yield {"client": client, "factory": factory, "acme": acme.id}
    await client.aclose()
    await engine.dispose()


async def _agents(w):
    async with w["factory"]() as db:
        return (await db.execute(select(Agent))).scalars().all()


def _hire_body(backend, **extra):
    return {
        "name": "CLI Smoke Employee",
        "role": "Software Engineer",
        "adapter_type": "cli",
        "adapter_config": {
            "backend": backend,
            "interactive": False,
            "use_worktree": False,
            "autonomy_mode": "safe",
            "extra_args": [],
        },
        "model": "",
        **extra,
    }


async def test_hire_persists_canonical_config(world):
    r = await world["client"].post(
        f"/api/v1/companies/{world['acme']}/agents", json=_hire_body("antigravity", model="custom-m")
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert (body["adapter_type"], body["cli_backend"], body["model"]) == ("cli", "agy", "custom-m")
    assert "adapter_config" not in body
    [agent] = await _agents(world)
    assert agent.adapter_config == {
        "backend": "agy",
        "interactive": False,
        "use_worktree": False,
        "autonomy_mode": "safe",
        "extra_args": [],
    }
    assert agent.status == "idle"


async def test_hire_unavailable_is_rejected_unless_explicit(world):
    url = f"/api/v1/companies/{world['acme']}/agents"
    r = await world["client"].post(url, json=_hire_body("claude"))
    assert r.status_code == 422
    assert r.json()["detail"]["code"] == "CLI_BACKEND_UNAVAILABLE"
    assert await _agents(world) == []

    r = await world["client"].post(url, json=_hire_body("claude", allow_unavailable_backend=True))
    assert r.status_code == 201
    assert r.json()["status"] == "configuration_required"


async def test_hire_rejects_executable_path_and_secrets(world):
    url = f"/api/v1/companies/{world['acme']}/agents"
    for key, value in (("executable", "/tmp/x"), ("api_key", "sk-1")):
        body = _hire_body("codex")
        body["adapter_config"][key] = value
        r = await world["client"].post(url, json=body)
        assert r.status_code == 422 and r.json()["detail"]["code"] == "CLI_CONFIG_INVALID"
    assert await _agents(world) == []


async def test_update_cannot_make_configuration_required_routable(world):
    url = f"/api/v1/companies/{world['acme']}/agents"
    r = await world["client"].post(url, json=_hire_body("claude", allow_unavailable_backend=True))
    agent_id = r.json()["id"]
    r = await world["client"].patch(f"/api/v1/agents/{agent_id}", json={"status": "idle"})
    assert r.status_code == 422


async def test_team_hire_uses_same_validation_atomically(world):
    good = {"name": "A", "adapter_type": "cli", "adapter_config": {"backend": "codex"}}
    bad = {"name": "B", "adapter_type": "cli", "adapter_config": {"backend": "nope"}}
    url = f"/api/v1/companies/{world['acme']}/agents/hire-team"
    r = await world["client"].post(url, json={"team_name": "T", "agents": [good, bad]})
    assert r.status_code == 422 and r.json()["detail"]["code"] == "CLI_BACKEND_UNKNOWN"
    assert await _agents(world) == []

    r = await world["client"].post(url, json={"team_name": "T", "agents": [good]})
    assert r.status_code == 201, r.text
    [agent] = await _agents(world)
    assert agent.adapter_type == "cli" and agent.adapter_config["backend"] == "codex"


async def test_manifest_hire_uses_same_validation(world):
    url = f"/api/v1/companies/{world['acme']}/agents/hire-from-manifest"
    manifest = {"spec": "nexus/hire@1", "name": "Builder", "provider": "antigravity"}
    r = await world["client"].post(url, json={"manifest": manifest})
    assert r.status_code == 201, r.text
    assert r.json()["cli_backend"] == "agy"

    manifest["provider"] = "claude"  # not on the fake PATH
    r = await world["client"].post(url, json={"manifest": manifest})
    assert r.status_code == 422 and r.json()["detail"]["code"] == "CLI_BACKEND_UNAVAILABLE"


async def test_provider_endpoints_serialize_the_catalog(world):
    client = world["client"]
    listed = (await client.get("/api/v1/agent-providers")).json()
    assert [p["id"] for p in listed] == [b.id for b in CLIRegistry(auto_detect=False).get_all()]
    assert all(DESCRIBE_FIELDS <= set(p) for p in listed)

    assert (await client.get("/api/v1/agent-providers/antigravity")).json()["id"] == "agy"
    assert (await client.get("/api/v1/agent-providers/nope")).status_code == 404
    assert (await client.get("/api/v1/agent-providers/nope/models")).status_code == 404

    r = await client.post("/api/v1/agent-providers/codex/probe")
    assert r.status_code == 200
    assert r.json() | {"resolved_command": None} == {
        "id": "codex",
        "installed": True,
        "resolved_command": None,
        "version": "1.0.0",
        "execution_supported": True,
        "configured": None,
        "ok": True,
        "error": None,
    }
    probe = (await client.post("/api/v1/agent-providers/claude/probe")).json()
    assert probe["ok"] is False and probe["installed"] is False
    viewer = await client.post(
        "/api/v1/agent-providers/codex/probe", headers={"x-test-principal": "viewer"}
    )
    assert viewer.status_code == 403


# ---------------------------------------------------------------------------
# Direct employee chat reaches the selected CLI
# ---------------------------------------------------------------------------


async def test_chat_executes_through_selected_cli(tmp_path, monkeypatch, fake_path):
    from nexus.api.routes import chat as chat_routes

    agent = Agent(
        id=uuid.uuid4(),
        company_id=uuid.uuid4(),
        name="Smoke",
        role="engineer",
        adapter_type="cli",
        adapter_config={"backend": "codex"},
        model="",
    )
    monkeypatch.setattr(chat_routes, "_resolve_connection", AsyncMock(return_value=None))
    monkeypatch.setattr(chat_routes, "_reserve_budget", AsyncMock(return_value=None))
    monkeypatch.setattr(chat_routes, "_settle_budget", AsyncMock())
    monkeypatch.setattr(chat_routes, "_remember_response", AsyncMock(return_value=0))
    spawn = AsyncMock(return_value=_fake_process(b"5050"))
    monkeypatch.setattr("nexus.adapters.cli_adapter.asyncio.create_subprocess_exec", spawn)

    execution: dict = {}
    text, _, _ = await chat_routes._call_llm(
        agent, "You are Smoke.", "Sum 1..100", [], execution=execution
    )
    assert text == "5050"
    assert spawn.call_args.args[0] == "/bin/codex"
    assert execution["adapter"] == "cli" and execution["backend"] == "codex"
    assert execution["cli"]["backend"] == "codex" and execution["execution_id"]


async def test_chat_refuses_configuration_required_agent():
    from fastapi import HTTPException

    from nexus.api.routes import chat as chat_routes

    agent = Agent(
        company_id=uuid.uuid4(),
        name="Blocked",
        role="engineer",
        adapter_type="cli",
        adapter_config={"backend": "claude"},
        status="configuration_required",
    )
    with pytest.raises(HTTPException) as exc:
        await chat_routes._call_llm(agent, "", "hi", [])
    assert exc.value.status_code == 409
