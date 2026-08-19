"""Integration Registry - manages external service integrations with encrypted secrets.

Provides CRUD operations for integration records and delegates secret storage
to a pluggable SecretBackend. Secrets are never exposed through the public
listing APIs; only a boolean indicating their presence is surfaced.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

from nexus.governance.secret_backend import SecretBackend


@dataclass
class IntegrationRecord:
    """Represents a registered external integration.

    Attributes:
        id: Unique integration identifier.
        name: Human-readable display name.
        auth_type: Authentication mechanism (e.g. 'api_key', 'oauth2').
        enabled: Whether this integration is active.
        secret_ref: Reference key for the stored secret.
        created_at: Unix timestamp of creation.
        updated_at: Unix timestamp of last update.
    """

    id: str
    name: str
    auth_type: str
    enabled: bool = True
    secret_ref: str = ""
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)


class IntegrationRegistry:
    """Registry for managing external integrations with encrypted secret storage.

    Delegates secret encryption/decryption to a SecretBackend instance.
    Supports full CRUD lifecycle with cascading secret deletion on removal.
    """

    def __init__(self, secret_backend: SecretBackend) -> None:
        """Initialize the integration registry.

        Args:
            secret_backend: Backend used for secret encryption/decryption.
        """
        self._backend = secret_backend
        self._records: dict[str, IntegrationRecord] = {}

    def list_records(self) -> list[IntegrationRecord]:
        """Return all integration records.

        Returns:
            List of all registered IntegrationRecord objects.
        """
        return list(self._records.values())

    def get_record(self, id: str) -> IntegrationRecord | None:
        """Retrieve a single integration record by ID.

        Args:
            id: The integration identifier.

        Returns:
            The matching IntegrationRecord, or None if not found.
        """
        return self._records.get(id)

    def upsert_record(self, record: IntegrationRecord) -> IntegrationRecord:
        """Insert or update an integration record.

        On update, preserves the original created_at timestamp and stamps
        a fresh updated_at. On insert, both timestamps reflect the current time.

        Args:
            record: The integration record to upsert.

        Returns:
            The stored IntegrationRecord (with updated timestamps).
        """
        existing = self._records.get(record.id)
        if existing is not None:
            record.created_at = existing.created_at
        record.updated_at = time.time()
        self._records[record.id] = record
        return record

    def remove_record(self, id: str) -> bool:
        """Remove an integration record and cascade-delete its secret.

        Args:
            id: The integration identifier to remove.

        Returns:
            True if the record was found and removed, False otherwise.
        """
        record = self._records.pop(id, None)
        if record is None:
            return False
        if record.secret_ref:
            self._backend.delete(record.secret_ref)
        return True

    def set_secret(self, id: str, plaintext: str) -> bool:
        """Store an encrypted secret for an integration.

        Uses the record's secret_ref as the storage key. Fails if the
        record does not exist or has no secret_ref configured.

        Args:
            id: The integration identifier.
            plaintext: The secret value to encrypt and store.

        Returns:
            True if the secret was stored successfully, False otherwise.
        """
        record = self._records.get(id)
        if record is None:
            return False
        if not record.secret_ref:
            return False
        return self._backend.encrypt(record.secret_ref, plaintext)

    def has_secret(self, id: str) -> bool:
        """Check whether an integration has a stored secret.

        Args:
            id: The integration identifier.

        Returns:
            True if the integration exists and has a stored secret.
        """
        record = self._records.get(id)
        if record is None:
            return False
        if not record.secret_ref:
            return False
        return self._backend.has(record.secret_ref)

    def get_secret(self, id: str) -> str | None:
        """Retrieve the decrypted secret for an integration (internal use only).

        This method is intended for internal system use and should never be
        exposed through public APIs.

        Args:
            id: The integration identifier.

        Returns:
            Decrypted secret plaintext, or None if not available.
        """
        record = self._records.get(id)
        if record is None:
            return None
        if not record.secret_ref:
            return None
        return self._backend.decrypt(record.secret_ref)

    def list_records_redacted(self) -> list[dict]:
        """Return all records with secret presence indicated but not exposed.

        Replaces the secret_ref field with a boolean 'has_secret' that
        indicates whether a secret is stored without exposing the value.

        Returns:
            List of dicts with record fields and 'has_secret' boolean.
        """
        results: list[dict] = []
        for record in self._records.values():
            results.append({
                "id": record.id,
                "name": record.name,
                "auth_type": record.auth_type,
                "enabled": record.enabled,
                "has_secret": (
                    bool(record.secret_ref)
                    and self._backend.has(record.secret_ref)
                ),
                "created_at": record.created_at,
                "updated_at": record.updated_at,
            })
        return results

    def enabled_ids(self) -> list[str]:
        """Return IDs of enabled integrations that have required secrets stored.

        Returns:
            List of integration IDs that are enabled and have secrets.
        """
        result: list[str] = []
        for record in self._records.values():
            if not record.enabled:
                continue
            if not record.secret_ref:
                continue
            if not self._backend.has(record.secret_ref):
                continue
            result.append(record.id)
        return result
