"""Tests for the Integration Registry and FernetSecretBackend modules."""

import time

from nexus.governance.secret_backend import FernetSecretBackend, SecretBackend
from nexus.governance.integration_registry import IntegrationRecord, IntegrationRegistry


class TestFernetSecretBackend:
    """Tests for the FernetSecretBackend class."""

    def test_encrypt_decrypt_roundtrip(self) -> None:
        """Encrypted value can be decrypted back to original plaintext."""
        backend = FernetSecretBackend("test-secret-key")
        assert backend.encrypt("ref1", "my-secret-value") is True
        assert backend.decrypt("ref1") == "my-secret-value"

    def test_encrypt_decrypt_unicode(self) -> None:
        """Backend handles unicode strings correctly."""
        backend = FernetSecretBackend("test-key")
        plaintext = "secret-with-emoji-\U0001f511-and-accent-\u00e9"
        assert backend.encrypt("unicode-ref", plaintext) is True
        assert backend.decrypt("unicode-ref") == plaintext

    def test_has_returns_true_when_exists(self) -> None:
        """has() returns True for stored references."""
        backend = FernetSecretBackend("key123")
        backend.encrypt("exists", "value")
        assert backend.has("exists") is True

    def test_has_returns_false_when_missing(self) -> None:
        """has() returns False for non-existent references."""
        backend = FernetSecretBackend("key123")
        assert backend.has("nonexistent") is False

    def test_delete_removes_secret(self) -> None:
        """delete() removes the stored secret."""
        backend = FernetSecretBackend("key123")
        backend.encrypt("to-delete", "value")
        assert backend.has("to-delete") is True
        backend.delete("to-delete")
        assert backend.has("to-delete") is False
        assert backend.decrypt("to-delete") is None

    def test_delete_idempotent(self) -> None:
        """delete() does not raise when reference does not exist."""
        backend = FernetSecretBackend("key123")
        backend.delete("never-existed")  # Should not raise

    def test_fail_closed_no_key(self) -> None:
        """Backend refuses operations when no key is provided."""
        backend = FernetSecretBackend(None)
        assert backend.encrypt("ref", "value") is False
        assert backend.decrypt("ref") is None
        assert backend.has("ref") is False

    def test_fail_closed_encrypt_returns_false(self) -> None:
        """encrypt() returns False when backend is unavailable."""
        backend = FernetSecretBackend(None)
        result = backend.encrypt("any-ref", "any-value")
        assert result is False

    def test_decrypt_nonexistent_ref(self) -> None:
        """decrypt() returns None for references that were never stored."""
        backend = FernetSecretBackend("valid-key")
        assert backend.decrypt("never-stored") is None

    def test_multiple_secrets(self) -> None:
        """Backend can store and retrieve multiple secrets independently."""
        backend = FernetSecretBackend("multi-key")
        backend.encrypt("ref-a", "value-a")
        backend.encrypt("ref-b", "value-b")
        backend.encrypt("ref-c", "value-c")
        assert backend.decrypt("ref-a") == "value-a"
        assert backend.decrypt("ref-b") == "value-b"
        assert backend.decrypt("ref-c") == "value-c"

    def test_overwrite_existing_ref(self) -> None:
        """Encrypting the same ref again overwrites the stored value."""
        backend = FernetSecretBackend("overwrite-key")
        backend.encrypt("ref", "original")
        backend.encrypt("ref", "updated")
        assert backend.decrypt("ref") == "updated"

    def test_implements_protocol(self) -> None:
        """FernetSecretBackend satisfies the SecretBackend protocol."""
        backend = FernetSecretBackend("key")
        assert isinstance(backend, SecretBackend)


class TestIntegrationRegistry:
    """Tests for the IntegrationRegistry class."""

    def _make_registry(self, key: str = "test-key") -> IntegrationRegistry:
        """Helper to create a registry with a working backend."""
        backend = FernetSecretBackend(key)
        return IntegrationRegistry(backend)

    def _make_record(
        self,
        id: str = "int-1",
        name: str = "Test Integration",
        auth_type: str = "api_key",
        enabled: bool = True,
        secret_ref: str = "secret:int-1",
    ) -> IntegrationRecord:
        """Helper to create a test integration record."""
        return IntegrationRecord(
            id=id,
            name=name,
            auth_type=auth_type,
            enabled=enabled,
            secret_ref=secret_ref,
        )

    def test_upsert_and_get(self) -> None:
        """upsert_record stores and get_record retrieves."""
        registry = self._make_registry()
        record = self._make_record()
        result = registry.upsert_record(record)
        assert result.id == "int-1"
        retrieved = registry.get_record("int-1")
        assert retrieved is not None
        assert retrieved.name == "Test Integration"

    def test_list_records(self) -> None:
        """list_records returns all stored records."""
        registry = self._make_registry()
        registry.upsert_record(self._make_record(id="a", name="A"))
        registry.upsert_record(self._make_record(id="b", name="B"))
        records = registry.list_records()
        assert len(records) == 2
        ids = {r.id for r in records}
        assert ids == {"a", "b"}

    def test_get_nonexistent_returns_none(self) -> None:
        """get_record returns None for unknown IDs."""
        registry = self._make_registry()
        assert registry.get_record("unknown") is None

    def test_upsert_preserves_created_at(self) -> None:
        """Updating a record preserves original created_at."""
        registry = self._make_registry()
        record = self._make_record()
        registry.upsert_record(record)
        original_created = registry.get_record("int-1").created_at  # type: ignore[union-attr]

        time.sleep(0.01)
        updated = self._make_record(name="Updated Name")
        registry.upsert_record(updated)

        result = registry.get_record("int-1")
        assert result is not None
        assert result.name == "Updated Name"
        assert result.created_at == original_created
        assert result.updated_at > original_created

    def test_remove_record_returns_true(self) -> None:
        """remove_record returns True when record exists."""
        registry = self._make_registry()
        registry.upsert_record(self._make_record())
        assert registry.remove_record("int-1") is True
        assert registry.get_record("int-1") is None

    def test_remove_record_returns_false_for_missing(self) -> None:
        """remove_record returns False for unknown IDs."""
        registry = self._make_registry()
        assert registry.remove_record("nonexistent") is False

    def test_remove_record_cascades_secret_delete(self) -> None:
        """remove_record deletes the associated secret from the backend."""
        backend = FernetSecretBackend("cascade-key")
        registry = IntegrationRegistry(backend)
        record = self._make_record(secret_ref="secret:cascade")
        registry.upsert_record(record)
        registry.set_secret("int-1", "my-api-key")
        assert backend.has("secret:cascade") is True

        registry.remove_record("int-1")
        assert backend.has("secret:cascade") is False

    def test_set_secret_and_get_secret(self) -> None:
        """set_secret stores and get_secret retrieves the plaintext."""
        registry = self._make_registry()
        registry.upsert_record(self._make_record(secret_ref="secret:x"))
        assert registry.set_secret("int-1", "super-secret") is True
        assert registry.get_secret("int-1") == "super-secret"

    def test_set_secret_fails_for_missing_record(self) -> None:
        """set_secret returns False if record does not exist."""
        registry = self._make_registry()
        assert registry.set_secret("nonexistent", "value") is False

    def test_set_secret_fails_without_secret_ref(self) -> None:
        """set_secret returns False if record has no secret_ref."""
        registry = self._make_registry()
        registry.upsert_record(self._make_record(secret_ref=""))
        assert registry.set_secret("int-1", "value") is False

    def test_has_secret(self) -> None:
        """has_secret returns True after storing a secret."""
        registry = self._make_registry()
        registry.upsert_record(self._make_record())
        assert registry.has_secret("int-1") is False
        registry.set_secret("int-1", "val")
        assert registry.has_secret("int-1") is True

    def test_has_secret_false_for_missing_record(self) -> None:
        """has_secret returns False for unknown IDs."""
        registry = self._make_registry()
        assert registry.has_secret("unknown") is False

    def test_get_secret_returns_none_when_no_secret(self) -> None:
        """get_secret returns None when no secret is stored."""
        registry = self._make_registry()
        registry.upsert_record(self._make_record())
        assert registry.get_secret("int-1") is None

    def test_list_records_redacted(self) -> None:
        """list_records_redacted shows has_secret boolean, not the value."""
        registry = self._make_registry()
        registry.upsert_record(self._make_record(id="a", secret_ref="s:a"))
        registry.upsert_record(self._make_record(id="b", secret_ref="s:b"))
        registry.set_secret("a", "secret-a")

        redacted = registry.list_records_redacted()
        assert len(redacted) == 2

        entry_a = next(e for e in redacted if e["id"] == "a")
        entry_b = next(e for e in redacted if e["id"] == "b")
        assert entry_a["has_secret"] is True
        assert entry_b["has_secret"] is False
        # Ensure no secret_ref or plaintext is exposed
        assert "secret_ref" not in entry_a
        assert "plaintext" not in entry_a

    def test_enabled_ids(self) -> None:
        """enabled_ids returns only enabled integrations with secrets."""
        registry = self._make_registry()
        # Enabled with secret
        registry.upsert_record(self._make_record(
            id="a", enabled=True, secret_ref="s:a"
        ))
        registry.set_secret("a", "key-a")
        # Enabled without secret
        registry.upsert_record(self._make_record(
            id="b", enabled=True, secret_ref="s:b"
        ))
        # Disabled with secret
        registry.upsert_record(self._make_record(
            id="c", enabled=False, secret_ref="s:c"
        ))
        registry.set_secret("c", "key-c")

        ids = registry.enabled_ids()
        assert ids == ["a"]

    def test_full_crud_lifecycle(self) -> None:
        """Full lifecycle: create, read, update, delete."""
        registry = self._make_registry()

        # Create
        record = self._make_record(id="lifecycle", name="Original")
        registry.upsert_record(record)
        assert registry.get_record("lifecycle") is not None

        # Read
        stored = registry.get_record("lifecycle")
        assert stored is not None
        assert stored.name == "Original"

        # Update
        updated = self._make_record(id="lifecycle", name="Updated")
        registry.upsert_record(updated)
        stored = registry.get_record("lifecycle")
        assert stored is not None
        assert stored.name == "Updated"

        # Delete
        assert registry.remove_record("lifecycle") is True
        assert registry.get_record("lifecycle") is None
        assert registry.list_records() == []
