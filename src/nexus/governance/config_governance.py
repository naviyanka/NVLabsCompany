"""Configuration Governance - Runtime config safety.

Provides configuration change approval, validation, rollback,
audit trail, sensitive value encryption, and environment guards.
"""

import base64
import hashlib
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable

from cryptography.fernet import Fernet, InvalidToken

# Distinct salt so config-governance keys cannot collide with the integration
# secret backend's derived key even when both start from the same app secret.
_SALT = b"nexus-config-governance"
_ITERATIONS = 480_000
_fernet: Fernet | None = None
_fernet_lock = threading.Lock()


def _get_fernet() -> Fernet | None:
    """Lazily derive a Fernet instance from the application secret key."""
    global _fernet
    if _fernet is not None:
        return _fernet
    with _fernet_lock:
        if _fernet is not None:
            return _fernet
        try:
            from nexus.config import settings

            derived = hashlib.pbkdf2_hmac(
                "sha256",
                settings.secret_key.encode(),
                salt=_SALT,
                iterations=_ITERATIONS,
            )
            _fernet = Fernet(base64.urlsafe_b64encode(derived[:32]))
        except Exception:
            _fernet = None
    return _fernet


@dataclass
class ConfigChange:
    """A recorded configuration change.

    Attributes:
        id: Unique change identifier.
        key: Configuration key that was changed.
        old_value: Previous value.
        new_value: New value.
        changed_by: Who made the change.
        timestamp: When the change was made.
        approved: Whether the change was approved.
        approved_by: Who approved the change (if approval required).
        applied: Whether the change has been applied.
        rolled_back: Whether the change was rolled back.
        environment: The environment this change targets.
    """

    id: uuid.UUID = field(default_factory=uuid.uuid4)
    key: str = ""
    old_value: Any = None
    new_value: Any = None
    changed_by: str = ""
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    approved: bool = False
    approved_by: str = ""
    applied: bool = False
    rolled_back: bool = False
    environment: str = "production"


@dataclass
class ConfigValidationRule:
    """A validation rule for a configuration key.

    Attributes:
        key: Configuration key pattern.
        validator: Function that validates the value.
        description: Human-readable description of the rule.
    """

    key: str
    validator: Callable[[Any], bool]
    description: str = ""


class ConfigGovernance:
    """Governs runtime configuration changes with safety controls.

    Provides:
    - Change approval workflow for sensitive keys
    - Configuration validation before application
    - Configuration rollback on failure
    - Full audit trail of all changes
    - Sensitive configuration encryption
    - Environment-specific guards
    """

    def __init__(self, current_environment: str = "production") -> None:
        """Initialize configuration governance.

        Args:
            current_environment: The current runtime environment (production, staging, dev).
        """
        self._current_environment = current_environment
        self._sensitive_keys: set[str] = set()
        self._change_history: list[ConfigChange] = []
        self._current_config: dict[str, Any] = {}
        self._validation_rules: dict[str, ConfigValidationRule] = {}
        self._encrypted_values: dict[str, str] = {}
        self._environment_guards: dict[str, set[str]] = {}  # env -> blocked keys

    def register_sensitive_key(self, key: str) -> None:
        """Register a key as sensitive (requires approval for changes).

        Args:
            key: The configuration key to mark as sensitive.
        """
        self._sensitive_keys.add(key)

    def is_sensitive_key(self, key: str) -> bool:
        """Check if a key is registered as sensitive.

        Args:
            key: The configuration key to check.

        Returns:
            True if the key is sensitive.
        """
        return key in self._sensitive_keys

    def add_validation_rule(
        self,
        key: str,
        validator: Callable[[Any], bool],
        description: str = "",
    ) -> ConfigValidationRule:
        """Add a validation rule for a configuration key.

        Args:
            key: The configuration key to validate.
            validator: Function that returns True if value is valid.
            description: Human-readable description of the rule.

        Returns:
            The created ConfigValidationRule.
        """
        rule = ConfigValidationRule(key=key, validator=validator, description=description)
        self._validation_rules[key] = rule
        return rule

    def validate_change(self, key: str, new_value: Any) -> tuple[bool, str]:
        """Validate a configuration change before application.

        Args:
            key: The configuration key.
            new_value: The proposed new value.

        Returns:
            Tuple of (is_valid, reason). is_valid is True if validation passes.
        """
        rule = self._validation_rules.get(key)
        if rule is None:
            return True, "No validation rule configured"

        try:
            is_valid = rule.validator(new_value)
            if is_valid:
                return True, "Validation passed"
            return False, f"Validation failed: {rule.description}"
        except Exception as e:
            return False, f"Validation error: {str(e)}"

    def request_change_approval(
        self,
        key: str,
        new_value: Any,
        changed_by: str,
        environment: str | None = None,
    ) -> ConfigChange:
        """Request approval for a configuration change.

        For sensitive keys, the change is recorded but not applied until approved.
        For non-sensitive keys, the change is auto-approved.

        Args:
            key: Configuration key to change.
            new_value: Proposed new value.
            changed_by: Who is requesting the change.
            environment: Target environment (defaults to current).

        Returns:
            The ConfigChange record (check .approved to see if auto-approved).
        """
        env = environment or self._current_environment
        old_value = self._current_config.get(key)

        change = ConfigChange(
            key=key,
            old_value=old_value,
            new_value=new_value,
            changed_by=changed_by,
            environment=env,
        )

        # Auto-approve non-sensitive keys
        if key not in self._sensitive_keys:
            change.approved = True
            change.approved_by = "auto"

        self._change_history.append(change)
        return change

    def approve_change(self, change_id: uuid.UUID, approved_by: str) -> ConfigChange | None:
        """Approve a pending configuration change.

        Args:
            change_id: The change to approve.
            approved_by: Who is approving.

        Returns:
            The updated ConfigChange, or None if not found.
        """
        for change in self._change_history:
            if change.id == change_id:
                change.approved = True
                change.approved_by = approved_by
                return change
        return None

    def apply_change(self, change_id: uuid.UUID) -> tuple[bool, str]:
        """Apply an approved configuration change.

        Args:
            change_id: The change to apply.

        Returns:
            Tuple of (success, reason).
        """
        change = self._find_change(change_id)
        if change is None:
            return False, "Change not found"

        if not change.approved:
            return False, "Change has not been approved"

        if change.applied:
            return False, "Change has already been applied"

        if change.rolled_back:
            return False, "Change has been rolled back"

        # Check environment guard
        env_safe, env_reason = self.check_environment_guard(
            change.key, change.environment
        )
        if not env_safe:
            return False, env_reason

        # Validate the value
        is_valid, reason = self.validate_change(change.key, change.new_value)
        if not is_valid:
            return False, reason

        # Apply the change
        self._current_config[change.key] = change.new_value
        change.applied = True
        return True, "Change applied successfully"

    def rollback_change(self, change_id: uuid.UUID) -> tuple[bool, str]:
        """Rollback an applied configuration change.

        Args:
            change_id: The change to rollback.

        Returns:
            Tuple of (success, reason).
        """
        change = self._find_change(change_id)
        if change is None:
            return False, "Change not found"

        if not change.applied:
            return False, "Change has not been applied"

        if change.rolled_back:
            return False, "Change has already been rolled back"

        # Restore old value
        if change.old_value is None:
            if change.key in self._current_config:
                del self._current_config[change.key]
        else:
            self._current_config[change.key] = change.old_value

        change.rolled_back = True
        return True, "Change rolled back successfully"

    def get_change_history(
        self, key: str | None = None, limit: int = 100
    ) -> list[ConfigChange]:
        """Get the configuration change history.

        Args:
            key: If provided, filter to changes for this key.
            limit: Maximum entries to return.

        Returns:
            List of ConfigChange records (most recent first).
        """
        entries = self._change_history
        if key:
            entries = [c for c in entries if c.key == key]
        return list(reversed(entries[-limit:]))

    def encrypt_sensitive_value(self, key: str, value: str) -> str:
        """Encrypt a sensitive configuration value.

        Uses Fernet (AES-128-CBC + HMAC) with a key derived from the
        application secret via PBKDF2-HMAC-SHA256. Reversible with
        :meth:`decrypt_sensitive_value`; raises RuntimeError in the
        fail-closed case where no key can be derived.

        Args:
            key: The configuration key.
            value: The plaintext value.

        Returns:
            The encrypted token.
        """
        fernet = _get_fernet()
        if fernet is None:
            raise RuntimeError(
                "No encryption key available: refusing to store sensitive "
                "value for key '%s' (fail-closed)." % key
            )
        encrypted = fernet.encrypt(value.encode()).decode()
        self._encrypted_values[key] = encrypted
        return encrypted

    def decrypt_sensitive_value(self, key: str) -> str | None:
        """Decrypt a sensitive configuration value previously encrypted.

        Args:
            key: The configuration key.

        Returns:
            The decrypted plaintext, or None when the value does not exist
            or cannot be authenticated/decrypted.
        """
        token = self._encrypted_values.get(key)
        if token is None:
            return None
        fernet = _get_fernet()
        if fernet is None:
            return None
        try:
            return fernet.decrypt(token.encode()).decode()
        except InvalidToken:
            return None

    def set_environment_guard(self, environment: str, blocked_keys: set[str]) -> None:
        """Set environment-specific configuration guards.

        Prevents certain keys from being changed in specific environments.
        For example, prevent production configs from being modified in dev.

        Args:
            environment: The environment to guard.
            blocked_keys: Set of keys that cannot be changed in this environment.
        """
        self._environment_guards[environment] = blocked_keys

    def check_environment_guard(
        self, key: str, target_environment: str | None = None
    ) -> tuple[bool, str]:
        """Check if a config change is allowed in the target environment.

        Args:
            key: The configuration key.
            target_environment: The environment to check (defaults to current).

        Returns:
            Tuple of (is_allowed, reason).
        """
        env = target_environment or self._current_environment
        blocked_keys = self._environment_guards.get(env, set())

        if key in blocked_keys:
            return False, (
                f"Key '{key}' is blocked from modification in "
                f"environment '{env}'"
            )
        return True, "Change allowed in this environment"

    def get_current_config(self) -> dict[str, Any]:
        """Get the current configuration state.

        Returns:
            Dict of current configuration values.
        """
        return dict(self._current_config)

    def _find_change(self, change_id: uuid.UUID) -> ConfigChange | None:
        """Find a change by ID.

        Args:
            change_id: The change to find.

        Returns:
            The ConfigChange, or None if not found.
        """
        for change in self._change_history:
            if change.id == change_id:
                return change
        return None
