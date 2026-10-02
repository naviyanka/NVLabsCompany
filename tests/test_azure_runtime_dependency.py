"""The Azure Entra SDK is a normal runtime dependency; the provider stays off by default.

No database, no network and no token request: these pin the deployment model documented
in docs/azure-openai-provider.md (a pinned base dependency, import-smoked in CI on the
exact production image) and the stable statuses when the SDK is or is not there.
"""

import json
import socket
import subprocess
import tomllib
import uuid
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from nexus.adapters import azure_openai_native as ao
from nexus.config import Settings, settings

ROOT = Path(__file__).resolve().parents[1]
KEY = "az-key-not-a-real-key-456"


@pytest.fixture
def entra(monkeypatch):
    """Enabled Entra mode on a loopback endpoint."""
    monkeypatch.setattr(settings, "azure_openai_enabled", True)
    monkeypatch.setattr(settings, "azure_openai_endpoint", "http://127.0.0.1:9")
    monkeypatch.setattr(settings, "azure_openai_deployment", "dep")
    monkeypatch.setattr(settings, "azure_openai_model", "gpt-4o")
    monkeypatch.setattr(settings, "azure_openai_auth", "entra")
    monkeypatch.setattr(ao, "_token_source", None)  # the real SDK check, not a test injection


@pytest.fixture
def no_network(monkeypatch):
    def refuse(*args, **kwargs):
        raise AssertionError("network activity")

    # Not socket.connect: the event loop's own self-pipe uses it. Any real request needs a client.
    monkeypatch.setattr(socket, "getaddrinfo", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)
    monkeypatch.setattr(httpx.AsyncClient, "__init__", refuse)


class TestDeploymentModel:
    def test_the_sdk_is_pinned_in_the_normal_runtime_dependencies_not_an_extra(self):
        project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
        base = [d.replace(" ", "") for d in project["dependencies"]]
        assert "azure-identity>=1.26.0,<1.27" in base
        assert any(d.startswith("aiohttp>=") for d in base)  # azure.identity.aio's async transport
        assert "azure" not in project["optional-dependencies"]

    def test_the_production_image_installs_the_project_with_its_runtime_dependencies(self):
        dockerfile = (ROOT / "Dockerfile.prod").read_text(encoding="utf-8")
        assert (
            'pip install --no-cache-dir ".[otel]"' in dockerfile and "--no-deps" not in dockerfile
        )

    def test_ci_import_smokes_the_exact_production_image_without_network(self):
        workflow = (ROOT / ".github" / "workflows" / "deploy-pipeline.yml").read_text(
            encoding="utf-8"
        )
        smoke = workflow.split("Import-smoke Azure provider runtime", 1)[1].split("- name:", 1)[0]
        assert "--network none nexus-api-scan:latest" in smoke
        assert "azure.identity.aio" in smoke and "AZURE_OPENAI_DISABLED" in smoke
        build = workflow.index("Build Backend Image (Local single-arch for scan)")
        assert build < workflow.index("Import-smoke Azure provider runtime")

    def test_the_installed_sdk_matches_the_pin(self):
        import importlib.metadata as md

        assert md.version("azure-identity").startswith("1.26.")
        from azure.identity.aio import DefaultAzureCredential  # noqa: F401


class TestEntraAvailability:
    def test_enabled_entra_mode_has_the_sdk_available(self, entra):
        assert ao._identity_sdk() is True
        assert ao.unavailable_reason() is None
        assert ao.status()["identity_sdk"] is True

    async def test_a_missing_sdk_is_a_stable_status_before_any_turn_work(
        self, entra, monkeypatch, no_network
    ):
        monkeypatch.setattr(ao.importlib.util, "find_spec", lambda name: None)
        assert ao.unavailable_reason().startswith("AZURE_OPENAI_IDENTITY_SDK_MISSING")
        assert ao.status()["identity_sdk"] is False and ao.status()["available"] is False
        session = SimpleNamespace(agent_id=uuid.uuid4())
        result = await ao.AzureOpenAINativeAdapter()._do_execute(
            session, uuid.uuid4(), {"prompt": "x"}
        )
        assert not result.success and result.error.startswith("AZURE_OPENAI_IDENTITY_SDK_MISSING")

    def test_aiohttp_missing_is_the_same_stable_status(self, entra, monkeypatch):
        real = ao.importlib.util.find_spec
        monkeypatch.setattr(
            ao.importlib.util, "find_spec", lambda n: None if n == "aiohttp" else real(n)
        )
        assert ao.unavailable_reason().startswith("AZURE_OPENAI_IDENTITY_SDK_MISSING")

    async def test_nothing_is_installed_at_runtime(self, entra, monkeypatch):
        def refuse(*args, **kwargs):
            raise AssertionError("runtime package installation")

        monkeypatch.setattr(subprocess, "run", refuse)
        monkeypatch.setattr(subprocess, "Popen", refuse)
        monkeypatch.setitem(
            __import__("sys").modules, "azure.identity.aio", None
        )  # import now fails
        with pytest.raises(ao.ProviderError, match="AZURE_OPENAI_IDENTITY_SDK_MISSING"):
            await ao._entra_token(ao._scope())
        source = Path(ao.__file__).read_text(encoding="utf-8")
        assert (
            "subprocess" not in source and "ensurepip" not in source and "pip install" not in source
        )


class TestNoSecretsAndNoNetworkByDefault:
    def test_the_provider_is_disabled_by_default(self):
        assert Settings.model_fields["azure_openai_enabled"].default is False

    async def test_a_disabled_provider_adds_no_network_activity(self, monkeypatch, no_network):
        monkeypatch.setattr(settings, "azure_openai_enabled", False)
        assert ao.unavailable_reason().startswith("AZURE_OPENAI_DISABLED")
        assert ao.status()["available"] is False
        session = SimpleNamespace(agent_id=uuid.uuid4())
        result = await ao.AzureOpenAINativeAdapter()._do_execute(
            session, uuid.uuid4(), {"prompt": "x"}
        )
        assert result.error.startswith("AZURE_OPENAI_DISABLED")

    def test_status_and_reasons_print_and_log_no_credential(
        self, entra, monkeypatch, capsys, caplog
    ):
        monkeypatch.setattr(settings, "secret_backend", "env")
        monkeypatch.setenv("NEXUS_SECRET_AZURE_OPENAI_API_KEY", KEY)
        monkeypatch.setattr(settings, "azure_openai_auth", "key")
        shown = [ao.status(), ao.unavailable_reason()]
        monkeypatch.setattr(settings, "azure_openai_auth", "entra")
        monkeypatch.setattr(ao.importlib.util, "find_spec", lambda name: None)
        shown += [ao.status(), ao.unavailable_reason()]
        out = capsys.readouterr()
        assert KEY not in json.dumps(shown, default=str) + out.out + out.err + caplog.text
