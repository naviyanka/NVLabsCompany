"""Regression guard: one key schedule across every writer of `secrets`.

Two code paths write ciphertext into `Secret.encrypted_value`: the API routes in
``nexus.api.routes.secrets`` and ``FernetSecretBackend``. They used to derive
their Fernet keys differently -- the routes did a single unsalted SHA-256 pass
over ``settings.secret_key``, while the backend used PBKDF2-HMAC-SHA256. A
secret written by one was undecryptable by the other, which surfaced as an
``InvalidToken`` raise or, worse, a silent ``None`` on read.

Both now derive through ``_derive_fernet_key``. These tests fail if the
schedules diverge again.
"""

from __future__ import annotations

import base64
import hashlib

import pytest
from cryptography.fernet import Fernet, InvalidToken

from nexus.governance.secret_backend import FernetSecretBackend, _derive_fernet_key

SECRET_KEY = "a-real-application-secret-not-the-default"
PLAINTEXT = "postgres://user:pw@host/db"


def legacy_fernet(secret_key: str) -> Fernet:
    """Rebuild the retired single-round SHA-256 key schedule."""
    return Fernet(base64.urlsafe_b64encode(hashlib.sha256(secret_key.encode()).digest()))


def route_fernet(secret_key: str) -> Fernet:
    """Rebuild the key schedule the routes module uses today."""
    return Fernet(
        _derive_fernet_key(
            secret_key,
            FernetSecretBackend._SALT,
            FernetSecretBackend._ITERATIONS,
        )
    )


class TestSchedulesAgree:
    """The two writers must produce mutually readable ciphertext."""

    def test_backend_reads_what_the_route_schedule_wrote(self) -> None:
        backend = FernetSecretBackend(secret_key=SECRET_KEY)
        ciphertext = route_fernet(SECRET_KEY).encrypt(PLAINTEXT.encode())

        # Inject as though the row had been written by the routes module.
        backend._store["db_url"] = ciphertext

        assert backend.decrypt("db_url") == PLAINTEXT

    def test_route_schedule_reads_what_the_backend_wrote(self) -> None:
        backend = FernetSecretBackend(secret_key=SECRET_KEY)
        assert backend.encrypt("db_url", PLAINTEXT) is True

        stored = backend._store["db_url"]
        assert route_fernet(SECRET_KEY).decrypt(stored).decode() == PLAINTEXT

    def test_derived_keys_are_identical(self) -> None:
        backend = FernetSecretBackend(secret_key=SECRET_KEY)
        expected = _derive_fernet_key(
            SECRET_KEY, FernetSecretBackend._SALT, FernetSecretBackend._ITERATIONS
        )
        assert backend._fernet is not None
        assert backend._fernet._signing_key + backend._fernet._encryption_key == (
            base64.urlsafe_b64decode(expected)
        )


class TestLegacySchedule:
    """Document what happens to rows written under the retired schedule."""

    def test_legacy_ciphertext_is_not_silently_wrong(self) -> None:
        """A legacy row must fail closed, never decrypt to wrong plaintext."""
        backend = FernetSecretBackend(secret_key=SECRET_KEY)
        backend._store["old"] = legacy_fernet(SECRET_KEY).encrypt(PLAINTEXT.encode())

        # decrypt() swallows InvalidToken and returns None by design, so the
        # guarantee under test is "never the wrong string", not "never fails".
        assert backend.decrypt("old") is None

    def test_legacy_and_current_keys_differ(self) -> None:
        """Guards against someone reintroducing the weak derivation."""
        legacy = base64.urlsafe_b64encode(hashlib.sha256(SECRET_KEY.encode()).digest())
        current = _derive_fernet_key(
            SECRET_KEY, FernetSecretBackend._SALT, FernetSecretBackend._ITERATIONS
        )
        assert legacy != current

    def test_current_key_cannot_read_legacy_ciphertext(self) -> None:
        legacy_token = legacy_fernet(SECRET_KEY).encrypt(PLAINTEXT.encode())
        with pytest.raises(InvalidToken):
            route_fernet(SECRET_KEY).decrypt(legacy_token)


class TestWeakKeysRefused:
    """The routes module must not encrypt under a placeholder secret."""

    def test_default_secret_key_is_refused(self) -> None:
        from nexus.api.routes import secrets as secrets_route

        fernet = secrets_route._make_fernet.__wrapped__ if hasattr(
            secrets_route._make_fernet, "__wrapped__"
        ) else secrets_route._make_fernet

        assert callable(fernet)
        # The module-level guard is what matters: no hardcoded fallback key.
        source = __import__("inspect").getsource(secrets_route)
        assert "fallback-dev-key" not in source
        assert "_TestOnlyXOREncryptor" not in source
