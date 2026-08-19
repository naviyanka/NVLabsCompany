"""Encrypted Secret Backend - Fernet-based at-rest encryption for integration secrets.

Provides a protocol-based abstraction for secret storage backends and a concrete
implementation using PBKDF2-derived Fernet keys. Supports optional file persistence
with atomic writes and key rotation. Follows fail-closed semantics: operations
silently refuse when no encryption key is configured.
"""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import os
import tempfile
from pathlib import Path
from typing import Protocol, runtime_checkable

from cryptography.fernet import Fernet

logger = logging.getLogger(__name__)


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

    _SALT = b"nexus-integration-secrets"
    _ITERATIONS = 480_000

    def __init__(
        self, secret_key: str | None, persist_path: str | Path | None = None
    ) -> None:
        """Initialize the Fernet secret backend.

        Args:
            secret_key: Application secret used to derive the Fernet key.
                If None, the backend operates in fail-closed mode.
            persist_path: Optional path to a JSON file for persisting encrypted
                secrets. If None, secrets are stored in-memory only.
                Parent directories are created automatically.
        """
        self._fernet: Fernet | None = None
        self._store: dict[str, bytes] = {}
        self._persist_path: Path | None = None

        if persist_path is not None:
            self._persist_path = Path(persist_path)
            self._persist_path.parent.mkdir(parents=True, exist_ok=True)

        if secret_key is not None:
            try:
                derived = hashlib.pbkdf2_hmac(
                    "sha256",
                    secret_key.encode(),
                    salt=self._SALT,
                    iterations=self._ITERATIONS,
                )
                fernet_key = base64.urlsafe_b64encode(derived[:32])
                self._fernet = Fernet(fernet_key)
            except Exception:
                logger.warning(
                    "Failed to derive Fernet key from secret_key; "
                    "backend will operate in fail-closed mode."
                )
                self._fernet = None

        if self._persist_path is not None:
            self._load_from_file()

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
        self._save_to_file()
        return True

    def decrypt(self, ref: str) -> str | None:
        """Decrypt and return the secret value for the given reference.

        Args:
            ref: Reference key to look up.

        Returns:
            Decrypted plaintext, or None if not found or unavailable.
        """
        if not self._available:
            return None
        assert self._fernet is not None
        ciphertext = self._store.get(ref)
        if ciphertext is None:
            return None
        return self._fernet.decrypt(ciphertext).decode("utf-8")

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
        self._save_to_file()

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
        derived = hashlib.pbkdf2_hmac(
            "sha256",
            new_secret_key.encode(),
            salt=self._SALT,
            iterations=self._ITERATIONS,
        )
        fernet_key = base64.urlsafe_b64encode(derived[:32])
        new_fernet = Fernet(fernet_key)

        # Re-encrypt all secrets with new key
        new_store: dict[str, bytes] = {}
        for ref, plaintext in plaintext_map.items():
            new_store[ref] = new_fernet.encrypt(plaintext.encode("utf-8"))

        # Update state
        self._fernet = new_fernet
        self._store = new_store
        self._save_to_file()

        return len(plaintext_map)
