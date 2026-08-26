"""Tests for config governance sensitive-value encryption (R-05 gap closure)."""

import pytest

from nexus.governance import config_governance as cg
from nexus.governance.config_governance import ConfigGovernance


@pytest.fixture
def gov():
    return ConfigGovernance()


def test_encrypt_is_reversible(gov):
    token = gov.encrypt_sensitive_value("api_key", "super-secret-123")
    assert token != "super-secret-123"
    assert gov.decrypt_sensitive_value("api_key") == "super-secret-123"


def test_encrypt_uses_fernet_token_format(gov):
    token = gov.encrypt_sensitive_value("db_password", "hunter2")
    # The old placeholder was a 64-char SHA-256 hex digest; Fernet tokens are
    # base64url and longer.
    assert len(token) > 64


def test_encrypt_same_value_twice_differs(gov):
    a = gov.encrypt_sensitive_value("k", "same")
    b = gov.encrypt_sensitive_value("k", "same")
    assert a != b  # Fernet includes a random IV + timestamp

    gov._encrypted_values["k"] = b
    assert gov.decrypt_sensitive_value("k") == "same"


def test_decrypt_missing_or_tampered_returns_none(gov):
    assert gov.decrypt_sensitive_value("nonexistent") is None
    gov.encrypt_sensitive_value("k", "value")
    gov._encrypted_values["k"] = "tampered-token"
    assert gov.decrypt_sensitive_value("k") is None


def test_fail_closed_when_no_key(monkeypatch, gov):
    monkeypatch.setattr(cg, "_get_fernet", lambda: None)
    with pytest.raises(RuntimeError):
        gov.encrypt_sensitive_value("k", "value")


@pytest.mark.asyncio
async def test_derived_key_stable_across_calls():
    f1 = cg._get_fernet()
    f2 = cg._get_fernet()
    assert f1 is f2
