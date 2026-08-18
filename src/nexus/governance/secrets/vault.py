"""Secret Vault - encrypted secret storage with versioning and access logging.

Secret values are NEVER exposed in logs, error messages, or metadata responses.
Uses Fernet symmetric encryption with a fallback to XOR obfuscation for environments
where the cryptography library is not available.
"""

import base64
import hashlib
import logging
import os
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)

# Try to import Fernet; fall back to base64 obfuscation for testing
try:
    from cryptography.fernet import Fernet

    _HAS_FERNET = True
except ImportError:
    _HAS_FERNET = False


class SecretCategory(str, Enum):
    """Categories of secrets that can be stored."""

    api_key = "api_key"
    password = "password"
    token = "token"
    certificate = "certificate"
    ssh_key = "ssh_key"


@dataclass
class SecretMetadata:
    """Metadata about a stored secret (never contains the secret value).

    Attributes:
        id: Unique identifier for the secret.
        name: Human-readable name.
        category: Type of secret.
        created_at: When the secret was created.
        expires_at: Optional expiration time.
        version: Current version number.
        bound_agents: List of agent IDs allowed to access this secret.
        company_id: Owning company.
        is_revoked: Whether the secret has been revoked.
        rotated_at: When the secret was last rotated.
    """

    id: uuid.UUID = field(default_factory=uuid.uuid4)
    name: str = ""
    category: SecretCategory = SecretCategory.api_key
    created_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    expires_at: datetime | None = None
    version: int = 1
    bound_agents: list[str] = field(default_factory=list)
    company_id: uuid.UUID | None = None
    is_revoked: bool = False
    rotated_at: datetime | None = None


@dataclass
class SecretAccessLog:
    """Record of a secret access attempt.

    Attributes:
        id: Unique log entry ID.
        secret_id: The secret that was accessed.
        accessor_id: Who accessed it.
        action: What action was performed.
        timestamp: When the access occurred.
        success: Whether access was granted.
    """

    id: uuid.UUID = field(default_factory=uuid.uuid4)
    secret_id: uuid.UUID = field(default_factory=uuid.uuid4)
    accessor_id: str = ""
    action: str = ""
    timestamp: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    success: bool = False


class _FernetEncryptor:
    """Encryption using cryptography.fernet.Fernet."""

    def __init__(self, key: bytes | None = None) -> None:
        if key is None:
            key = Fernet.generate_key()
        self._key = key
        self._fernet = Fernet(key)

    def encrypt(self, plaintext: str) -> bytes:
        return self._fernet.encrypt(plaintext.encode("utf-8"))

    def decrypt(self, ciphertext: bytes) -> str:
        return self._fernet.decrypt(ciphertext).decode("utf-8")

    @property
    def key(self) -> bytes:
        return self._key


class _TestOnlyXOREncryptor:
    """Fallback obfuscation using XOR with a key + base64 encoding.

    WARNING: This is NOT cryptographically secure and provides NO real
    confidentiality guarantees. It exists ONLY so that tests can run
    without the cryptography library installed. Do NOT use in production.
    A repeating-key XOR cipher is trivially reversible.
    """

    def __init__(self, key: bytes | str | None = None) -> None:
        if key is None:
            key = os.urandom(32)
        if isinstance(key, str):
            key = key.encode("utf-8")
        self._key = key

    def encrypt(self, plaintext: str) -> bytes:
        data = plaintext.encode("utf-8")
        key_bytes = self._key
        encrypted = bytes(
            b ^ key_bytes[i % len(key_bytes)] for i, b in enumerate(data)
        )
        return base64.urlsafe_b64encode(encrypted)

    def decrypt(self, ciphertext: bytes) -> str:
        encrypted = base64.urlsafe_b64decode(ciphertext)
        key_bytes = self._key
        decrypted = bytes(
            b ^ key_bytes[i % len(key_bytes)] for i, b in enumerate(encrypted)
        )
        return decrypted.decode("utf-8")

    @property
    def key(self) -> bytes:
        return self._key


class SecretVault:
    """Encrypted secret storage with versioning and access logging.

    Secrets are stored encrypted and never exposed in logs, metadata,
    or error messages. Supports versioning for rotation without breaking
    references, and maintains an access log for auditing.
    """

    def __init__(self, encryption_key: bytes | str | None = None) -> None:
        """Initialize the secret vault.

        Args:
            encryption_key: Optional encryption key. If not provided,
                a new key is generated.
        """
        if isinstance(encryption_key, str):
            encryption_key = encryption_key.encode("utf-8")
        if _HAS_FERNET:
            self._encryptor = _FernetEncryptor(encryption_key)
        else:
            logger.warning(
                "cryptography library not available - falling back to "
                "_TestOnlyXOREncryptor which provides NO real encryption. "
                "This is acceptable for testing only. Do NOT use in production."
            )
            self._encryptor = _TestOnlyXOREncryptor(encryption_key)

        # secret_id -> {version -> encrypted_value}
        self._secrets: dict[uuid.UUID, dict[int, bytes]] = {}
        # secret_id -> metadata
        self._metadata: dict[uuid.UUID, SecretMetadata] = {}
        # Access log
        self._access_log: list[SecretAccessLog] = []

    async def create_secret(
        self,
        name: str,
        value: str,
        category: SecretCategory = SecretCategory.api_key,
        expires_at: datetime | None = None,
        bound_agents: list[str] | None = None,
        company_id: uuid.UUID | None = None,
    ) -> SecretMetadata:
        """Create a new secret with encryption.

        The value is encrypted before storage; it never appears in
        the returned metadata.

        Args:
            name: Human-readable name for the secret.
            value: The secret value to encrypt and store.
            category: Type of secret.
            expires_at: Optional expiration time.
            bound_agents: Agent IDs allowed to access this secret.
            company_id: Owning company.

        Returns:
            SecretMetadata (never contains the value).
        """
        secret_id = uuid.uuid4()
        encrypted = self._encryptor.encrypt(value)

        metadata = SecretMetadata(
            id=secret_id,
            name=name,
            category=category,
            expires_at=expires_at,
            version=1,
            bound_agents=bound_agents or [],
            company_id=company_id,
        )

        self._metadata[secret_id] = metadata
        self._secrets[secret_id] = {1: encrypted}

        self._log_access(secret_id, "system", "create", success=True)
        return metadata

    async def get_secret(
        self,
        secret_id: uuid.UUID,
        accessor_id: str,
        version: int | None = None,
    ) -> str | None:
        """Retrieve and decrypt a secret value.

        Logs the access attempt. Returns None if the secret does not exist,
        is revoked, or the accessor is not bound.

        Args:
            secret_id: The secret to retrieve.
            accessor_id: Who is requesting access.
            version: Specific version to retrieve (latest if None).

        Returns:
            Decrypted secret value, or None if access denied.
        """
        metadata = self._metadata.get(secret_id)
        if metadata is None:
            self._log_access(secret_id, accessor_id, "get", success=False)
            return None

        if metadata.is_revoked:
            self._log_access(secret_id, accessor_id, "get", success=False)
            return None

        # Check expiration
        if metadata.expires_at and datetime.now(timezone.utc) > metadata.expires_at:
            self._log_access(secret_id, accessor_id, "get", success=False)
            return None

        # Check binding
        if metadata.bound_agents and accessor_id not in metadata.bound_agents:
            self._log_access(secret_id, accessor_id, "get", success=False)
            return None

        target_version = version if version is not None else metadata.version
        versions = self._secrets.get(secret_id, {})
        encrypted = versions.get(target_version)

        if encrypted is None:
            self._log_access(secret_id, accessor_id, "get", success=False)
            return None

        self._log_access(secret_id, accessor_id, "get", success=True)
        return self._encryptor.decrypt(encrypted)

    async def rotate_secret(
        self,
        secret_id: uuid.UUID,
        new_value: str,
        rotated_by: str = "system",
    ) -> SecretMetadata | None:
        """Rotate a secret to a new version.

        The old version is preserved for lookback. The version number
        is incremented, and the new value is encrypted.

        Args:
            secret_id: The secret to rotate.
            new_value: New secret value.
            rotated_by: Who initiated the rotation.

        Returns:
            Updated SecretMetadata, or None if secret not found.
        """
        metadata = self._metadata.get(secret_id)
        if metadata is None:
            return None

        if metadata.is_revoked:
            return None

        new_version = metadata.version + 1
        encrypted = self._encryptor.encrypt(new_value)

        self._secrets[secret_id][new_version] = encrypted
        metadata.version = new_version
        metadata.rotated_at = datetime.now(timezone.utc)

        self._log_access(secret_id, rotated_by, "rotate", success=True)
        return metadata

    async def revoke_secret(
        self,
        secret_id: uuid.UUID,
        revoked_by: str = "system",
    ) -> bool:
        """Revoke a secret, making it inaccessible.

        Args:
            secret_id: The secret to revoke.
            revoked_by: Who initiated the revocation.

        Returns:
            True if the secret was revoked, False if not found.
        """
        metadata = self._metadata.get(secret_id)
        if metadata is None:
            return False

        metadata.is_revoked = True
        self._log_access(secret_id, revoked_by, "revoke", success=True)
        return True

    async def bulk_revoke_for_agent(
        self,
        agent_id: str,
        revoked_by: str = "system",
    ) -> list[uuid.UUID]:
        """Revoke all secrets bound to a specific agent.

        Args:
            agent_id: The agent whose secrets should be revoked.
            revoked_by: Who initiated the revocation.

        Returns:
            List of revoked secret IDs.
        """
        revoked: list[uuid.UUID] = []
        for secret_id, metadata in self._metadata.items():
            if agent_id in metadata.bound_agents and not metadata.is_revoked:
                metadata.is_revoked = True
                self._log_access(secret_id, revoked_by, "bulk_revoke", success=True)
                revoked.append(secret_id)
        return revoked

    def list_secrets(
        self,
        company_id: uuid.UUID | None = None,
        category: SecretCategory | None = None,
        include_revoked: bool = False,
    ) -> list[SecretMetadata]:
        """List secret metadata (NEVER includes secret values).

        Args:
            company_id: Filter by company.
            category: Filter by category.
            include_revoked: Whether to include revoked secrets.

        Returns:
            List of SecretMetadata objects.
        """
        results: list[SecretMetadata] = []
        for metadata in self._metadata.values():
            if company_id and metadata.company_id != company_id:
                continue
            if category and metadata.category != category:
                continue
            if not include_revoked and metadata.is_revoked:
                continue
            results.append(metadata)
        return results

    def get_access_log(
        self,
        secret_id: uuid.UUID | None = None,
        accessor_id: str | None = None,
        limit: int = 100,
    ) -> list[SecretAccessLog]:
        """Retrieve the secret access log.

        Args:
            secret_id: Filter by secret.
            accessor_id: Filter by accessor.
            limit: Maximum entries to return.

        Returns:
            List of SecretAccessLog entries.
        """
        results: list[SecretAccessLog] = []
        for entry in reversed(self._access_log):
            if secret_id and entry.secret_id != secret_id:
                continue
            if accessor_id and entry.accessor_id != accessor_id:
                continue
            results.append(entry)
            if len(results) >= limit:
                break
        return results

    def _log_access(
        self,
        secret_id: uuid.UUID,
        accessor_id: str,
        action: str,
        success: bool,
    ) -> None:
        """Internal method to log access attempts.

        Never logs secret values - only metadata about the access.
        """
        entry = SecretAccessLog(
            secret_id=secret_id,
            accessor_id=accessor_id,
            action=action,
            success=success,
        )
        self._access_log.append(entry)
