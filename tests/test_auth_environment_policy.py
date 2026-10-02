"""AUTH_ENABLED=false is honoured only in explicitly safe environments."""

import uuid

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from nexus.auth.middleware import AuthenticationMiddleware, rejection_for
from nexus.config import settings
from nexus.config_validator import ConfigurationError, _check_auth_settings, enforce_auth_policy


@pytest.fixture
def set_auth(monkeypatch):
    """Set (auth_enabled, env, ack) on the shared settings object."""

    def _set(enabled: bool, env: str, ack: bool = False) -> None:
        monkeypatch.setattr(settings, "auth_enabled", enabled)
        monkeypatch.setattr(settings, "nexus_env", env)
        monkeypatch.setattr(settings, "nexus_allow_insecure_auth_disabled", ack)

    return _set


@pytest.mark.parametrize(
    ("enabled", "env", "ack", "code"),
    [
        (True, "production", False, None),
        (True, "", False, None),
        (True, "weird", True, None),
        (False, "test", False, None),
        (False, " TEST ", False, None),
        (False, "development", True, None),
        (False, "development", False, "AUTH_DISABLED_NEEDS_ACKNOWLEDGEMENT"),
        (False, "production", True, "AUTH_DISABLED_FORBIDDEN_ENVIRONMENT"),
        (False, "staging", True, "AUTH_DISABLED_FORBIDDEN_ENVIRONMENT"),
        (False, "", True, "AUTH_DISABLED_UNKNOWN_ENVIRONMENT"),
        (False, "prod", True, "AUTH_DISABLED_UNKNOWN_ENVIRONMENT"),
        (False, "qa", False, "AUTH_DISABLED_UNKNOWN_ENVIRONMENT"),
    ],
)
def test_refusal_matrix(set_auth, enabled, env, ack, code):
    set_auth(enabled, env, ack)
    assert settings.auth_disabled_refusal() == code
    assert settings.auth_bypass_active is (not enabled and code is None)
    if code is None:
        enforce_auth_policy()
    else:
        with pytest.raises(ConfigurationError) as exc:
            enforce_auth_policy()
        assert exc.value.code == code


def test_startup_error_names_settings_but_no_values(set_auth):
    set_auth(False, "production", True)
    with pytest.raises(ConfigurationError) as exc:
        enforce_auth_policy()
    assert "AUTH_ENABLED" in str(exc.value)
    assert str(uuid.UUID(int=0)) not in str(exc.value)


def test_warning_only_when_bypass_active(set_auth, caplog):
    set_auth(False, "development", True)
    with caplog.at_level("WARNING"):
        _check_auth_settings()
    assert "INSECURE: AUTH_ENABLED=false in NEXUS_ENV=development" in caplog.text

    caplog.clear()
    set_auth(True, "development", True)
    with caplog.at_level("WARNING"):
        _check_auth_settings()
    assert "INSECURE" not in caplog.text


def test_rejection_for_anonymous(set_auth):
    set_auth(False, "production", True)
    assert rejection_for("/api/v1/companies", None).status_code == 401

    set_auth(False, "test")
    assert rejection_for("/api/v1/companies", None) is None


def _client() -> TestClient:
    app = FastAPI()
    app.add_middleware(AuthenticationMiddleware)

    @app.get("/api/v1/thing")
    async def thing() -> dict:
        return {"ok": True}

    return TestClient(app)


@pytest.mark.parametrize(
    ("env", "ack", "status"),
    [
        ("test", False, 200),
        ("development", True, 200),
        ("development", False, 401),
        ("production", True, 401),
        ("staging", True, 401),
        ("", True, 401),
    ],
)
def test_forged_company_header_only_works_where_allowed(set_auth, env, ack, status):
    """A forged X-Company-Id is a credential only in an allowed environment."""
    set_auth(False, env, ack)
    response = _client().get("/api/v1/thing", headers={"X-Company-Id": str(uuid.uuid4())})
    assert response.status_code == status


def test_auth_enabled_ignores_company_header(set_auth):
    set_auth(True, "test")
    response = _client().get("/api/v1/thing", headers={"X-Company-Id": str(uuid.uuid4())})
    assert response.status_code == 401
