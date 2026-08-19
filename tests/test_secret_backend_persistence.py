"""Tests for FernetSecretBackend file persistence, atomic writes, and key rotation."""

from __future__ import annotations

import json
import os
import stat
from pathlib import Path
from unittest.mock import patch

import pytest

from nexus.governance.secret_backend import FernetSecretBackend


@pytest.fixture
def secret_key() -> str:
    """A consistent secret key for testing."""
    return "test-secret-key-for-fernet-backend"


@pytest.fixture
def persist_file(tmp_path: Path) -> Path:
    """A temporary path for the persistence file."""
    return tmp_path / "secrets.json"


class TestPersistenceBasic:
    """Tests for basic encrypt/decrypt with file persistence."""

    def test_encrypt_decrypt_with_persistence(
        self, secret_key: str, persist_file: Path
    ) -> None:
        """Secrets persist across instances with same key and path."""
        backend1 = FernetSecretBackend(secret_key, persist_path=persist_file)
        assert backend1.encrypt("api-key", "super-secret-value")
        assert backend1.encrypt("db-pass", "postgres-password-123")

        # Create a new instance with same key and path
        backend2 = FernetSecretBackend(secret_key, persist_path=persist_file)
        assert backend2.decrypt("api-key") == "super-secret-value"
        assert backend2.decrypt("db-pass") == "postgres-password-123"

    def test_delete_persists_removal(
        self, secret_key: str, persist_file: Path
    ) -> None:
        """Deleting a secret persists the removal to disk."""
        backend1 = FernetSecretBackend(secret_key, persist_path=persist_file)
        backend1.encrypt("api-key", "secret-value")
        backend1.encrypt("other-key", "other-value")
        backend1.delete("api-key")

        # New instance should not have the deleted secret
        backend2 = FernetSecretBackend(secret_key, persist_path=persist_file)
        assert not backend2.has("api-key")
        assert backend2.has("other-key")
        assert backend2.decrypt("other-key") == "other-value"

    def test_has_works_after_persistence_reload(
        self, secret_key: str, persist_file: Path
    ) -> None:
        """has() returns correct result after reloading from file."""
        backend1 = FernetSecretBackend(secret_key, persist_path=persist_file)
        backend1.encrypt("exists", "value")

        backend2 = FernetSecretBackend(secret_key, persist_path=persist_file)
        assert backend2.has("exists")
        assert not backend2.has("does-not-exist")


class TestAtomicWrite:
    """Tests for atomic file writes."""

    def test_atomic_write_uses_replace(
        self, secret_key: str, persist_file: Path
    ) -> None:
        """Atomic write uses os.replace to swap in the new file."""
        real_replace = os.replace
        with patch("nexus.governance.secret_backend.os.replace") as mock_replace:
            # Allow the real replace to happen but track the call
            mock_replace.side_effect = real_replace
            backend = FernetSecretBackend(secret_key, persist_path=persist_file)
            backend.encrypt("key", "value")

            mock_replace.assert_called_once()
            # Second arg should be the persist path
            assert mock_replace.call_args[0][1] == str(persist_file)

    def test_no_partial_files_left(
        self, secret_key: str, persist_file: Path
    ) -> None:
        """After a successful write, no temp files remain in the directory."""
        backend = FernetSecretBackend(secret_key, persist_path=persist_file)
        backend.encrypt("key1", "value1")
        backend.encrypt("key2", "value2")

        # Only the persist file should exist in the directory
        files_in_dir = list(persist_file.parent.iterdir())
        assert files_in_dir == [persist_file]


class TestFilePermissions:
    """Tests for file permission enforcement."""

    def test_file_permissions_are_0o600(
        self, secret_key: str, persist_file: Path
    ) -> None:
        """Persistence file has 0o600 permissions (owner read/write only)."""
        backend = FernetSecretBackend(secret_key, persist_path=persist_file)
        backend.encrypt("key", "value")

        file_stat = os.stat(persist_file)
        permissions = stat.S_IMODE(file_stat.st_mode)
        assert permissions == 0o600


class TestKeyRotation:
    """Tests for key rotation functionality."""

    def test_rotate_key_re_encrypts_all_secrets(
        self, secret_key: str, persist_file: Path
    ) -> None:
        """rotate_key re-encrypts all secrets with the new key."""
        backend = FernetSecretBackend(secret_key, persist_path=persist_file)
        backend.encrypt("key1", "value1")
        backend.encrypt("key2", "value2")

        new_key = "new-secret-key-for-rotation"
        count = backend.rotate_key(new_key)
        assert count == 2

        # Verify decryption works with the rotated backend
        assert backend.decrypt("key1") == "value1"
        assert backend.decrypt("key2") == "value2"

    def test_rotate_key_persists_re_encrypted_secrets(
        self, secret_key: str, persist_file: Path
    ) -> None:
        """After rotation, re-instantiating with new key reads back secrets."""
        backend = FernetSecretBackend(secret_key, persist_path=persist_file)
        backend.encrypt("key1", "value1")
        backend.encrypt("key2", "value2")

        new_key = "new-secret-key-for-rotation"
        backend.rotate_key(new_key)

        # New instance with new key can read the secrets
        backend2 = FernetSecretBackend(new_key, persist_path=persist_file)
        assert backend2.decrypt("key1") == "value1"
        assert backend2.decrypt("key2") == "value2"

    def test_rotate_key_old_key_cannot_decrypt(
        self, secret_key: str, persist_file: Path
    ) -> None:
        """After rotation, the old key cannot decrypt the re-encrypted secrets."""
        backend = FernetSecretBackend(secret_key, persist_path=persist_file)
        backend.encrypt("key1", "value1")

        new_key = "new-secret-key-for-rotation"
        backend.rotate_key(new_key)

        # Old key instance cannot decrypt
        old_backend = FernetSecretBackend(secret_key, persist_path=persist_file)
        # The old key will load the ciphertext but fail to decrypt
        assert old_backend.has("key1")
        # decrypt returns None on InvalidToken (fail-closed semantics)
        assert old_backend.decrypt("key1") is None

    def test_rotate_key_returns_correct_count(
        self, secret_key: str, persist_file: Path
    ) -> None:
        """rotate_key returns the number of re-encrypted secrets."""
        backend = FernetSecretBackend(secret_key, persist_path=persist_file)
        backend.encrypt("a", "1")
        backend.encrypt("b", "2")
        backend.encrypt("c", "3")

        assert backend.rotate_key("new-key") == 3

    def test_rotate_key_with_no_secrets_returns_zero(
        self, secret_key: str, persist_file: Path
    ) -> None:
        """rotate_key with an empty store returns 0."""
        backend = FernetSecretBackend(secret_key, persist_path=persist_file)
        assert backend.rotate_key("new-key") == 0

    def test_rotate_key_unavailable_backend_returns_zero(
        self, persist_file: Path
    ) -> None:
        """rotate_key returns 0 when backend has no key (fail-closed)."""
        backend = FernetSecretBackend(None, persist_path=persist_file)
        assert backend.rotate_key("new-key") == 0


class TestBackwardCompatibility:
    """Tests ensuring backward compatibility when no persist_path is given."""

    def test_in_memory_only_without_persist_path(self, secret_key: str) -> None:
        """Without persist_path, backend works purely in-memory."""
        backend = FernetSecretBackend(secret_key)
        assert backend.encrypt("key", "value")
        assert backend.decrypt("key") == "value"
        assert backend.has("key")
        backend.delete("key")
        assert not backend.has("key")

    def test_no_file_created_without_persist_path(
        self, secret_key: str, tmp_path: Path
    ) -> None:
        """Without persist_path, no files are created anywhere."""
        backend = FernetSecretBackend(secret_key)
        backend.encrypt("key", "value")
        backend.delete("key")

        # tmp_path should remain empty
        assert list(tmp_path.iterdir()) == []


class TestEdgeCases:
    """Tests for edge cases and error handling."""

    def test_missing_file_on_init_does_not_crash(
        self, secret_key: str, persist_file: Path
    ) -> None:
        """Initializing with a non-existent file path starts with empty store."""
        backend = FernetSecretBackend(secret_key, persist_path=persist_file)
        assert not backend.has("anything")
        # Can still encrypt and persist
        assert backend.encrypt("key", "value")
        assert persist_file.exists()

    def test_parent_dirs_created_automatically(
        self, secret_key: str, tmp_path: Path
    ) -> None:
        """Parent directories for persist_path are created automatically."""
        deep_path = tmp_path / "a" / "b" / "c" / "secrets.json"
        backend = FernetSecretBackend(secret_key, persist_path=deep_path)
        backend.encrypt("key", "value")

        assert deep_path.exists()
        # Verify the content was actually persisted
        backend2 = FernetSecretBackend(secret_key, persist_path=deep_path)
        assert backend2.decrypt("key") == "value"

    def test_corrupt_json_file_logs_warning_starts_empty(
        self, secret_key: str, persist_file: Path
    ) -> None:
        """A corrupt JSON file logs a warning and starts with empty store."""
        persist_file.write_text("this is not valid json {{{{", encoding="utf-8")

        with patch(
            "nexus.governance.secret_backend.logger"
        ) as mock_logger:
            backend = FernetSecretBackend(secret_key, persist_path=persist_file)

        mock_logger.warning.assert_called_once()
        assert "Corrupt JSON" in mock_logger.warning.call_args[0][0]
        assert not backend.has("anything")

    def test_fail_closed_none_secret_key_all_operations_fail(
        self, persist_file: Path
    ) -> None:
        """With None secret_key, all operations return failure values."""
        backend = FernetSecretBackend(None, persist_path=persist_file)
        assert backend.encrypt("key", "value") is False
        assert backend.decrypt("key") is None
        assert not backend.has("key")
        # delete should not crash
        backend.delete("key")

    def test_persist_path_as_string(
        self, secret_key: str, tmp_path: Path
    ) -> None:
        """persist_path accepts a string in addition to Path."""
        str_path = str(tmp_path / "secrets.json")
        backend = FernetSecretBackend(secret_key, persist_path=str_path)
        backend.encrypt("key", "value")

        backend2 = FernetSecretBackend(secret_key, persist_path=str_path)
        assert backend2.decrypt("key") == "value"

    def test_file_format_is_valid_json_with_base64_values(
        self, secret_key: str, persist_file: Path
    ) -> None:
        """The persistence file contains valid JSON with base64-encoded values."""
        backend = FernetSecretBackend(secret_key, persist_path=persist_file)
        backend.encrypt("my-ref", "my-secret")

        raw = persist_file.read_text(encoding="utf-8")
        data = json.loads(raw)
        assert "my-ref" in data
        # Value should be base64 string (decodable)
        import base64

        decoded = base64.b64decode(data["my-ref"])
        assert isinstance(decoded, bytes)
        assert len(decoded) > 0
