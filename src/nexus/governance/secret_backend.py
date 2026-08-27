"""Encrypted Secret Backend - Fernet-based at-rest encryption for integration secrets.

Provides a protocol-based abstraction for secret storage backends and a concrete
implementation using PBKDF2-derived Fernet keys. Supports optional file persistence
with atomic writes and key rotation. Follows fail-closed semantics: operations
silently refuse when no encryption key is configured.
"""

from __future__ import annotations

import asyncio
import base64
import concurrent.futures
import hashlib
import json
import logging
import os
import tempfile
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Protocol, runtime_checkable

from cryptography.fernet import Fernet, InvalidToken

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

logger = logging.getLogger(__name__)

# Company that owns process-level integration secrets (matches the default
# company seeded at startup). `secrets.company_id` is NOT NULL.
DEFAULT_SECRET_COMPANY_ID = uuid.UUID("00000000-0000-4000-8000-000000000001")

# Derived Fernet keys, memoized per process so the 600k-iteration PBKDF2 runs
# once per (key, salt, iterations) rather than on every backend construction.
_KDF_CACHE: dict[tuple[bytes, bytes, int], bytes] = {}


def _derive_fernet_key(secret_key: str, salt: bytes, iterations: int) -> bytes:
    """Derive a Fernet key from an application secret via PBKDF2-HMAC-SHA256.

    The result is memoized for the lifetime of the process: deriving at 600,000
    iterations costs ~0.3s, and backends are constructed per request in some
    call paths.

    Args:
        secret_key: Application secret to stretch.
        salt: PBKDF2 salt.
        iterations: PBKDF2 iteration count.

    Returns:
        A urlsafe-base64 Fernet key.
    """
    cache_key = (secret_key.encode(), salt, iterations)
    key = _KDF_CACHE.get(cache_key)
    if key is None:
        derived = hashlib.pbkdf2_hmac(
            "sha256", secret_key.encode(), salt=salt, iterations=iterations
        )
        key = base64.urlsafe_b64encode(derived[:32])
        _KDF_CACHE[cache_key] = key
    return key


def _run_sync(coro):
    """Run a coroutine from sync code, whether or not a loop is running.

    The SecretBackend protocol is synchronous and its callers (IntegrationRegistry,
    rotation routes) are sync, while the database layer is async.
    """
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(asyncio.run, coro).result(timeout=30)


@dataclass
class RotationPolicy:
    """Policy defining when a secret should be rotated.

    Attributes:
        max_age_days: Maximum number of days before rotation is needed.
        auto_rotate: Whether to automatically rotate when max_age is exceeded.
    """

    max_age_days: int = 90
    auto_rotate: bool = False

    def __post_init__(self) -> None:
        """Validate rotation policy values."""
        if self.max_age_days <= 0:
            raise ValueError("max_age_days must be positive")


@runtime_checkable
class SecretBackend(Protocol):
    """Protocol for pluggable secret storage backends.

    Implementations must provide encrypt, decrypt, has, and delete operations.
    All operations should be fail-closed: refuse to store if unavailable.
    """

    def encrypt(self, ref: str, plaintext: str) -> bool:
        """Encrypt and store a secret value under the given reference.

        Args:
            ref: Unique reference key for the secret.
            plaintext: The secret value to encrypt and store.

        Returns:
            True if stored successfully, False otherwise.
        """
        ...

    def decrypt(self, ref: str) -> str | None:
        """Decrypt and return the secret value for the given reference.

        Args:
            ref: Reference key to look up.

        Returns:
            Decrypted plaintext, or None if not found or unavailable.
        """
        ...

    def has(self, ref: str) -> bool:
        """Check whether a secret exists for the given reference.

        Args:
            ref: Reference key to check.

        Returns:
            True if a secret is stored for this reference.
        """
        ...

    def delete(self, ref: str) -> None:
        """Delete the secret for the given reference (idempotent).

        Args:
            ref: Reference key to remove.
        """
        ...


class FernetSecretBackend:
    """Fernet-based encrypted secret backend with PBKDF2 key derivation.

    Derives a Fernet-compatible key from an application secret using PBKDF2-HMAC
    with SHA-256. Secrets are stored in an in-memory dictionary, encrypted at rest.
    Optionally persists encrypted secrets to a JSON file on disk with atomic writes
    and restricted file permissions. Follows fail-closed semantics: all mutating
    operations return failure when no encryption key is available.
    """

    # Salt is intentionally shared across deployments. It prevents rainbow-table
    # attacks on the PBKDF2 output; deployment isolation comes from the per-deployment
    # secret_key parameter, which is unique to each environment.
    _SALT = b"nexus-integration-secrets"
    _ITERATIONS = 600_000

    def __init__(
        self,
        secret_key: str | None,
        persist_path: str | Path | None = None,
        session_factory: async_sessionmaker[AsyncSession] | None = None,
        company_id: uuid.UUID | None = None,
    ) -> None:
        """Initialize the Fernet secret backend.

        Args:
            secret_key: Application secret used to derive the Fernet key.
                If None, the backend operates in fail-closed mode.
            persist_path: Optional path to a JSON file for persisting encrypted
                secrets. If None, secrets are stored in-memory only.
                Parent directories are created automatically.
            session_factory: Optional async session factory. When given, the
                `secrets` table is the store and secrets survive a restart;
                `persist_path` is ignored.
            company_id: Owning company for DB-backed rows. Defaults to the
                default company.
        """
        self._fernet: Fernet | None = None
        self._store: dict[str, bytes] = {}
        # Refs deleted through this instance but not yet flushed to the DB. The
        # DB sync removes only these, never rows merely absent from _store.
        self._pending_deletes: set[str] = set()
        self._persist_path: Path | None = None
        self._session_factory = session_factory
        self._company_id = company_id or DEFAULT_SECRET_COMPANY_ID
        self._rotation_policies: dict[str, RotationPolicy] = {}
        self.rotation_history: dict[str, datetime] = {}

        if persist_path is not None and session_factory is None:
            self._persist_path = Path(persist_path)
            self._persist_path.parent.mkdir(parents=True, exist_ok=True)

        if secret_key is not None:
            try:
                fernet_key = _derive_fernet_key(
                    secret_key, self._SALT, self._ITERATIONS
                )
                self._fernet = Fernet(fernet_key)
            except Exception:
                logger.warning(
                    "Failed to derive Fernet key from secret_key; "
                    "backend will operate in fail-closed mode."
                )
                self._fernet = None

        if self._persist_path is not None:
            self._load_from_file()
        elif self._session_factory is not None:
            self._load_from_db()

    # --- Database-backed store (Phase 0.3) -------------------------------

    def _load_from_db(self) -> None:
        """Load encrypted secrets for this company from the `secrets` table."""
        try:
            self._store = _run_sync(self._async_load_from_db())
        except Exception:
            logger.warning(
                "Failed to load secrets from database; starting with empty store."
            )
            self._store = {}

    async def _async_load_from_db(self) -> dict[str, bytes]:
        """Read all non-revoked secret rows for this company.

        Returns:
            Mapping of secret name to ciphertext bytes.
        """
        from sqlalchemy import select

        from nexus.models.secret import Secret

        assert self._session_factory is not None
        async with self._session_factory() as session:
            rows = (
                await session.execute(
                    select(Secret).where(
                        Secret.company_id == self._company_id,
                        Secret.is_revoked == False,  # noqa: E712
                    )
                )
            ).scalars()
            return {
                row.name: row.encrypted_value.encode("ascii") for row in rows
            }

    def _load_from_file(self) -> None:
        """Load encrypted secrets from the persistence file.

        Reads the JSON file at self._persist_path and populates self._store
        with base64-decoded bytes values. If the file does not exist, the
        store remains empty. If the file contains invalid JSON, a warning
        is logged and the store starts empty.
        """
        if self._persist_path is None or not self._persist_path.exists():
            return
        try:
            raw = self._persist_path.read_text(encoding="utf-8")
            data = json.loads(raw)
            for ref, encoded_value in data.items():
                self._store[ref] = base64.b64decode(encoded_value)
        except (json.JSONDecodeError, ValueError):
            logger.warning(
                "Corrupt JSON in secret persistence file %s; starting with empty store.",
                self._persist_path,
            )
            self._store = {}
        except Exception:
            logger.warning(
                "Failed to load secret persistence file %s; starting with empty store.",
                self._persist_path,
            )
            self._store = {}

    async def _async_sync_store(self) -> None:
        """Make the `secrets` table match `self._store` exactly.

        Upserts every ref currently held and deletes rows this company owns
        that are no longer in the store. One seam serves encrypt, delete, and
        rotate_key.
        """
        from sqlalchemy import delete, select

        from nexus.models.secret import Secret

        assert self._session_factory is not None
        async with self._session_factory() as session:
            rows = list(
                (
                    await session.execute(
                        select(Secret).where(Secret.company_id == self._company_id)
                    )
                ).scalars()
            )
            existing = {row.name: row for row in rows}
            now = datetime.now(UTC).replace(tzinfo=None)

            for ref, ciphertext in self._store.items():
                encoded = ciphertext.decode("ascii")
                row = existing.get(ref)
                if row is None:
                    session.add(
                        Secret(
                            company_id=self._company_id,
                            name=ref,
                            encrypted_value=encoded,
                        )
                    )
                elif row.encrypted_value != encoded or row.is_revoked:
                    row.encrypted_value = encoded
                    row.is_revoked = False
                    row.current_version += 1
                    row.updated_at = now

            # Only rows this instance explicitly deleted are removed. Absence
            # from self._store is NOT treated as a deletion: another process (or
            # another backend instance) may have written a secret this instance
            # never loaded, and mirroring the local store would silently drop it.
            pending = [name for name in self._pending_deletes if name in existing]
            if pending:
                await session.execute(
                    delete(Secret).where(
                        Secret.company_id == self._company_id,
                        Secret.name.in_(pending),
                    )
                )
            await session.commit()
            self._pending_deletes.clear()

    def _persist(self) -> None:
        """Write the store to whichever backing store is configured (if any)."""
        if self._session_factory is not None:
            _run_sync(self._async_sync_store())
        else:
            self._save_to_file()

    def _save_to_file(self) -> None:
        """Persist encrypted secrets to disk atomically.

        Serializes self._store to JSON (base64-encoding bytes values), writes
        to a temporary file in the same directory, then atomically replaces
        the target file using os.replace(). Sets file permissions to 0o600
        (owner-only read/write). Only writes when self._persist_path is set.
        """
        if self._persist_path is None:
            return
        data = {
            ref: base64.b64encode(ciphertext).decode("ascii")
            for ref, ciphertext in self._store.items()
        }
        parent_dir = self._persist_path.parent
        parent_dir.mkdir(parents=True, exist_ok=True)

        fd, tmp_path = tempfile.mkstemp(dir=str(parent_dir))
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(data, f)
            os.chmod(tmp_path, 0o600)
            os.replace(tmp_path, str(self._persist_path))
        except Exception:
            # Clean up temp file on failure
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise

    @property
    def _available(self) -> bool:
        """Whether the backend is operational (key was derived successfully).

        Returns:
            True if encryption is available.
        """
        return self._fernet is not None

    def encrypt(self, ref: str, plaintext: str) -> bool:
        """Encrypt and store a secret value under the given reference.

        Fail-closed: returns False if no encryption key is configured.
        Persists to file if persist_path is configured.

        Args:
            ref: Unique reference key for the secret.
            plaintext: The secret value to encrypt and store.

        Returns:
            True if stored successfully, False if unavailable.
        """
        if not self._available:
            return False
        assert self._fernet is not None
        self._store[ref] = self._fernet.encrypt(plaintext.encode("utf-8"))
        self._persist()
        return True

    def decrypt(self, ref: str) -> str | None:
        """Decrypt and return the secret value for the given reference.

        Args:
            ref: Reference key to look up.

        Returns:
            Decrypted plaintext, or None if not found or unavailable.
            Returns None on decryption failure (e.g., ciphertext encrypted
            with a different key or corrupted data) to maintain fail-closed
            semantics.
        """
        if not self._available:
            return None
        assert self._fernet is not None
        ciphertext = self._store.get(ref)
        if ciphertext is None:
            return None
        try:
            return self._fernet.decrypt(ciphertext).decode("utf-8")
        except InvalidToken:
            logger.warning(
                "Failed to decrypt secret '%s': invalid token (wrong key or corrupt data).",
                ref,
            )
            return None

    def has(self, ref: str) -> bool:
        """Check whether a secret exists for the given reference.

        Args:
            ref: Reference key to check.

        Returns:
            True if a secret is stored for this reference.
        """
        return ref in self._store

    def delete(self, ref: str) -> None:
        """Delete the secret for the given reference (idempotent).

        Persists the removal to file if persist_path is configured.

        Args:
            ref: Reference key to remove.
        """
        self._store.pop(ref, None)
        self._pending_deletes.add(ref)
        self._persist()

    def rotate_key(self, new_secret_key: str) -> int:
        """Rotate the encryption key, re-encrypting all stored secrets.

        Decrypts all secrets with the current Fernet key, derives a new key
        from new_secret_key using the same PBKDF2 parameters, re-encrypts
        all secrets with the new key, and persists to file.

        Args:
            new_secret_key: New application secret to derive the Fernet key from.

        Returns:
            Number of secrets successfully re-encrypted. Returns 0 if the
            backend is unavailable (no key configured).
        """
        if not self._available:
            return 0
        assert self._fernet is not None

        # Decrypt all secrets with current key
        plaintext_map: dict[str, str] = {}
        for ref, ciphertext in self._store.items():
            plaintext_map[ref] = self._fernet.decrypt(ciphertext).decode("utf-8")

        # Derive new Fernet key
        new_fernet = Fernet(
            _derive_fernet_key(new_secret_key, self._SALT, self._ITERATIONS)
        )

        # Re-encrypt all secrets with new key
        new_store: dict[str, bytes] = {}
        for ref, plaintext in plaintext_map.items():
            new_store[ref] = new_fernet.encrypt(plaintext.encode("utf-8"))

        # Update state
        self._fernet = new_fernet
        self._store = new_store
        self._persist()

        return len(plaintext_map)

    def set_rotation_policy(self, ref: str, policy: RotationPolicy) -> None:
        """Set a rotation policy for a specific secret reference.

        Args:
            ref: The secret reference key.
            policy: The rotation policy to apply.
        """
        self._rotation_policies[ref] = policy

    def get_rotation_policy(self, ref: str) -> RotationPolicy | None:
        """Get the rotation policy for a specific secret reference.

        Args:
            ref: The secret reference key.

        Returns:
            The rotation policy if configured, None otherwise.
        """
        return self._rotation_policies.get(ref)

    def check_rotation_needed(self, ref: str) -> bool:
        """Check whether a secret needs rotation based on its policy.

        A secret needs rotation if it has a rotation policy configured and
        either has never been rotated or was last rotated more than
        max_age_days ago.

        Args:
            ref: The secret reference key to check.

        Returns:
            True if rotation is needed, False otherwise.
        """
        policy = self._rotation_policies.get(ref)
        if policy is None:
            return False

        last_rotated = self.rotation_history.get(ref)
        if last_rotated is None:
            # Never rotated - rotation is needed
            return True

        now = datetime.now(UTC)
        age_days = (now - last_rotated).days
        return age_days >= policy.max_age_days

    def get_secrets_needing_rotation(self) -> list[str]:
        """Return all secret references that need rotation.

        Checks each secret that has a rotation policy configured and
        returns those that are past their max age.

        Returns:
            List of secret reference keys needing rotation.
        """
        needing: list[str] = []
        for ref in self._rotation_policies:
            if ref in self._store and self.check_rotation_needed(ref):
                needing.append(ref)
        return needing


class KeyringSecretBackend:
    """Secret backend backed by the OS keychain via the `keyring` package.

    Storage and encryption are the operating system's responsibility, so there
    is no application-level key. Fail-closed: if `keyring` is not installed or
    the platform has no usable backend, every operation refuses.
    """

    SERVICE = "nexus-integration-secrets"

    def __init__(self) -> None:
        """Import `keyring` lazily; stay unavailable if it is missing."""
        try:
            import keyring

            self._keyring = keyring
        except Exception:
            logger.warning(
                "keyring package unavailable; secret backend is fail-closed."
            )
            self._keyring = None

    def encrypt(self, ref: str, plaintext: str) -> bool:
        """Store a secret in the OS keychain.

        Args:
            ref: Reference key for the secret.
            plaintext: Value to store.

        Returns:
            True if stored, False if the keyring is unavailable or errored.
        """
        if self._keyring is None:
            return False
        try:
            self._keyring.set_password(self.SERVICE, ref, plaintext)
            return True
        except Exception:
            logger.warning("Failed to store secret '%s' in keyring.", ref)
            return False

    def decrypt(self, ref: str) -> str | None:
        """Read a secret from the OS keychain.

        Args:
            ref: Reference key to look up.

        Returns:
            The value, or None if absent or unavailable.
        """
        if self._keyring is None:
            return None
        try:
            return self._keyring.get_password(self.SERVICE, ref)
        except Exception:
            logger.warning("Failed to read secret '%s' from keyring.", ref)
            return None

    def has(self, ref: str) -> bool:
        """Whether a secret exists for `ref`.

        Args:
            ref: Reference key to check.

        Returns:
            True if the keychain holds a value for this reference.
        """
        return self.decrypt(ref) is not None

    def delete(self, ref: str) -> None:
        """Remove a secret from the keychain (idempotent).

        Args:
            ref: Reference key to remove.
        """
        if self._keyring is None:
            return
        try:
            self._keyring.delete_password(self.SERVICE, ref)
        except Exception:
            pass


class EnvSecretBackend:
    """Read-only secret backend reading `NEXUS_SECRET_<REF>` env variables.

    For deployments where secrets are injected by the platform (Kubernetes
    secrets, ECS task definitions, systemd credentials). Writes always refuse:
    the environment is owned by the deployer, not the application.
    """

    PREFIX = "NEXUS_SECRET_"

    def _env_name(self, ref: str) -> str:
        """Map a secret reference to its environment variable name.

        Args:
            ref: Reference key, e.g. "github-token".

        Returns:
            The env var name, e.g. "NEXUS_SECRET_GITHUB_TOKEN".
        """
        return self.PREFIX + ref.upper().replace("-", "_").replace(".", "_")

    def encrypt(self, ref: str, plaintext: str) -> bool:
        """Refuse to write; the environment is externally managed.

        Args:
            ref: Reference key (unused).
            plaintext: Value (unused).

        Returns:
            Always False.
        """
        logger.warning(
            "SECRET_BACKEND=env is read-only; refusing to store secret '%s'.", ref
        )
        return False

    def decrypt(self, ref: str) -> str | None:
        """Read the secret from the environment.

        Args:
            ref: Reference key to look up.

        Returns:
            The env var value, or None if unset.
        """
        return os.environ.get(self._env_name(ref))

    def has(self, ref: str) -> bool:
        """Whether the corresponding environment variable is set.

        Args:
            ref: Reference key to check.

        Returns:
            True if the env var is present.
        """
        return self._env_name(ref) in os.environ

    def delete(self, ref: str) -> None:
        """No-op; the environment is externally managed.

        Args:
            ref: Reference key (unused).
        """
        logger.warning(
            "SECRET_BACKEND=env is read-only; refusing to delete secret '%s'.", ref
        )


def make_secret_backend(
    session_factory: async_sessionmaker[AsyncSession] | None = None,
) -> SecretBackend:
    """Build the secret backend named by `settings.secret_backend`.

    Args:
        session_factory: Async session factory handed to the `fernet` backend so
            secrets live in the `secrets` table and survive a restart. When
            omitted, the fernet backend is in-memory only.

    Returns:
        A SecretBackend implementation. An unknown selector falls back to
        `fernet` with a warning rather than failing startup.
    """
    from nexus.config import settings

    choice = (settings.secret_backend or "fernet").strip().lower()
    if choice == "keyring":
        return KeyringSecretBackend()
    if choice == "env":
        return EnvSecretBackend()
    if choice != "fernet":
        logger.warning(
            "Unknown SECRET_BACKEND '%s'; falling back to 'fernet'.", choice
        )
    return FernetSecretBackend(
        settings.secret_key, session_factory=session_factory
    )
