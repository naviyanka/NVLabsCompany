"""Tests for Secret Rotation Automation."""

from datetime import datetime, timedelta, timezone

import pytest

from nexus.governance.secret_backend import (
    FernetSecretBackend,
    RotationPolicy,
)


@pytest.fixture
def backend() -> FernetSecretBackend:
    """Create a FernetSecretBackend with a test key."""
    return FernetSecretBackend(secret_key="test-secret-key-for-rotation")


class TestRotationPolicy:
    """Tests for RotationPolicy dataclass."""

    def test_default_policy(self) -> None:
        """Test default rotation policy values."""
        policy = RotationPolicy()
        assert policy.max_age_days == 90
        assert policy.auto_rotate is False

    def test_custom_policy(self) -> None:
        """Test custom rotation policy values."""
        policy = RotationPolicy(max_age_days=30, auto_rotate=True)
        assert policy.max_age_days == 30
        assert policy.auto_rotate is True

    def test_invalid_max_age_zero(self) -> None:
        """Test that max_age_days of 0 raises ValueError."""
        with pytest.raises(ValueError, match="max_age_days must be positive"):
            RotationPolicy(max_age_days=0)

    def test_invalid_max_age_negative(self) -> None:
        """Test that negative max_age_days raises ValueError."""
        with pytest.raises(ValueError, match="max_age_days must be positive"):
            RotationPolicy(max_age_days=-1)


class TestCheckRotationNeeded:
    """Tests for FernetSecretBackend.check_rotation_needed()."""

    def test_no_policy_no_rotation(self, backend: FernetSecretBackend) -> None:
        """Test that secrets without a policy never need rotation."""
        backend.encrypt("my-secret", "value123")
        assert backend.check_rotation_needed("my-secret") is False

    def test_never_rotated_needs_rotation(
        self, backend: FernetSecretBackend
    ) -> None:
        """Test that a secret with a policy but no rotation history needs rotation."""
        backend.encrypt("my-secret", "value123")
        backend.set_rotation_policy(
            "my-secret", RotationPolicy(max_age_days=30)
        )
        assert backend.check_rotation_needed("my-secret") is True

    def test_recently_rotated_no_rotation_needed(
        self, backend: FernetSecretBackend
    ) -> None:
        """Test that a recently rotated secret does not need rotation."""
        backend.encrypt("my-secret", "value123")
        backend.set_rotation_policy(
            "my-secret", RotationPolicy(max_age_days=30)
        )
        # Mark as just rotated
        backend.rotation_history["my-secret"] = datetime.now(timezone.utc)
        assert backend.check_rotation_needed("my-secret") is False

    def test_old_rotation_needs_rotation(
        self, backend: FernetSecretBackend
    ) -> None:
        """Test that a secret rotated beyond max_age needs rotation."""
        backend.encrypt("my-secret", "value123")
        backend.set_rotation_policy(
            "my-secret", RotationPolicy(max_age_days=30)
        )
        # Set rotation to 31 days ago
        backend.rotation_history["my-secret"] = datetime.now(
            timezone.utc
        ) - timedelta(days=31)
        assert backend.check_rotation_needed("my-secret") is True

    def test_exactly_at_max_age_needs_rotation(
        self, backend: FernetSecretBackend
    ) -> None:
        """Test that a secret exactly at max_age_days needs rotation."""
        backend.encrypt("my-secret", "value123")
        backend.set_rotation_policy(
            "my-secret", RotationPolicy(max_age_days=30)
        )
        backend.rotation_history["my-secret"] = datetime.now(
            timezone.utc
        ) - timedelta(days=30)
        assert backend.check_rotation_needed("my-secret") is True

    def test_just_under_max_age_no_rotation(
        self, backend: FernetSecretBackend
    ) -> None:
        """Test that a secret just under max_age does not need rotation."""
        backend.encrypt("my-secret", "value123")
        backend.set_rotation_policy(
            "my-secret", RotationPolicy(max_age_days=30)
        )
        backend.rotation_history["my-secret"] = datetime.now(
            timezone.utc
        ) - timedelta(days=29)
        assert backend.check_rotation_needed("my-secret") is False


class TestGetSecretsNeedingRotation:
    """Tests for FernetSecretBackend.get_secrets_needing_rotation()."""

    def test_empty_backend(self, backend: FernetSecretBackend) -> None:
        """Test with no secrets stored."""
        assert backend.get_secrets_needing_rotation() == []

    def test_mixed_rotation_status(
        self, backend: FernetSecretBackend,
    ) -> None:
        """Test with a mix of secrets needing and not needing rotation."""
        # Secret that needs rotation (never rotated)
        backend.encrypt("old-secret", "val1")
        backend.set_rotation_policy(
            "old-secret", RotationPolicy(max_age_days=30)
        )

        # Secret that does not need rotation (recently rotated)
        backend.encrypt("new-secret", "val2")
        backend.set_rotation_policy(
            "new-secret", RotationPolicy(max_age_days=30)
        )
        backend.rotation_history["new-secret"] = datetime.now(timezone.utc)

        # Secret with no policy
        backend.encrypt("no-policy", "val3")

        needing = backend.get_secrets_needing_rotation()
        assert "old-secret" in needing
        assert "new-secret" not in needing
        assert "no-policy" not in needing

    def test_multiple_needing_rotation(
        self, backend: FernetSecretBackend,
    ) -> None:
        """Test that multiple expired secrets are all returned."""
        for i in range(3):
            ref = f"secret-{i}"
            backend.encrypt(ref, f"value-{i}")
            backend.set_rotation_policy(
                ref, RotationPolicy(max_age_days=7)
            )
            backend.rotation_history[ref] = datetime.now(
                timezone.utc
            ) - timedelta(days=10)

        needing = backend.get_secrets_needing_rotation()
        assert len(needing) == 3


class TestSetRotationPolicy:
    """Tests for FernetSecretBackend.set_rotation_policy()."""

    def test_set_and_retrieve_policy(
        self, backend: FernetSecretBackend
    ) -> None:
        """Test setting and checking a rotation policy."""
        policy = RotationPolicy(max_age_days=60, auto_rotate=True)
        backend.set_rotation_policy("ref-1", policy)
        assert backend._rotation_policies["ref-1"] is policy
        assert backend._rotation_policies["ref-1"].max_age_days == 60
        assert backend._rotation_policies["ref-1"].auto_rotate is True

    def test_overwrite_policy(self, backend: FernetSecretBackend) -> None:
        """Test overwriting an existing rotation policy."""
        backend.set_rotation_policy(
            "ref-1", RotationPolicy(max_age_days=30)
        )
        backend.set_rotation_policy(
            "ref-1", RotationPolicy(max_age_days=60, auto_rotate=True)
        )
        assert backend._rotation_policies["ref-1"].max_age_days == 60
        assert backend._rotation_policies["ref-1"].auto_rotate is True


class TestRotationHistory:
    """Tests for rotation_history tracking."""

    def test_initial_empty_history(self, backend: FernetSecretBackend) -> None:
        """Test that rotation history starts empty."""
        assert backend.rotation_history == {}

    def test_manual_history_update(
        self, backend: FernetSecretBackend
    ) -> None:
        """Test manually updating rotation history."""
        now = datetime.now(timezone.utc)
        backend.rotation_history["my-secret"] = now
        assert backend.rotation_history["my-secret"] == now

    def test_history_affects_rotation_check(
        self, backend: FernetSecretBackend
    ) -> None:
        """Test that rotation history affects check_rotation_needed."""
        backend.encrypt("s1", "val")
        backend.set_rotation_policy("s1", RotationPolicy(max_age_days=10))

        # Initially needs rotation (no history)
        assert backend.check_rotation_needed("s1") is True

        # After recording rotation, should not need it
        backend.rotation_history["s1"] = datetime.now(timezone.utc)
        assert backend.check_rotation_needed("s1") is False
