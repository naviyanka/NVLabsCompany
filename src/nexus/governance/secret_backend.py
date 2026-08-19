"""Encrypted Secret Backend - Fernet-based at-rest encryption for integration secrets.

Provides a protocol-based abstraction for secret storage backends and a concrete
implementation using PBKDF2-derived Fernet keys. Follows fail-closed semantics:
operations silently refuse when no encryption key is configured.
"""

from __future__ import annotations

import base64
import hashlib
import logging
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
    Follows fail-closed semantics: all mutating operations return failure when no
    encryption key is available.
    """

    _SALT = b"nexus-integration-secrets"
    _ITERATIONS = 480_000

    def __init__(self, secret_key: str | None) -> None:
        """Initialize the Fernet secret backend.

        Args:
            secret_key: Application secret used to derive the Fernet key.
                If None, the backend operates in fail-closed mode.
        """
        self._fernet: Fernet | None = None
        self._store: dict[str, bytes] = {}

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

        Args:
            ref: Reference key to remove.
        """
        self._store.pop(ref, None)
