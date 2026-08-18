"""Tests for Secret Vault and Access Control.

Tests vault operations (create, get, rotate, revoke), encryption verification,
access control bindings, time-limited/one-time access, and emergency revocation.
"""

import asyncio
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Add src to path for direct execution
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from nexus.governance.secrets.vault import (
    SecretVault,
    SecretCategory,
    SecretMetadata,
)
from nexus.governance.secrets.access import SecretAccessController


def run_async(coro):
    """Helper to run async coroutines in tests."""
    return asyncio.run(coro)


class TestSecretVault:
    """Tests for SecretVault encryption and storage."""

    def test_create_secret_returns_metadata(self):
        vault = SecretVault()
        metadata = run_async(vault.create_secret(
            name="test-api-key",
            value="super-secret-value-123",
            category=SecretCategory.api_key,
        ))
        assert isinstance(metadata, SecretMetadata)
        assert metadata.name == "test-api-key"
        assert metadata.category == SecretCategory.api_key
        assert metadata.version == 1
        assert not metadata.is_revoked

    def test_create_secret_never_exposes_value_in_metadata(self):
        vault = SecretVault()
        metadata = run_async(vault.create_secret(
            name="secret",
            value="my-secret-value",
        ))
        # Metadata should not contain the secret value anywhere
        metadata_str = str(metadata)
        assert "my-secret-value" not in metadata_str

    def test_get_secret_returns_decrypted_value(self):
        vault = SecretVault()
        metadata = run_async(vault.create_secret(
            name="test",
            value="decrypt-me-123",
        ))
        value = run_async(vault.get_secret(metadata.id, "agent-1"))
        assert value == "decrypt-me-123"

    def test_encryption_stored_value_differs_from_plaintext(self):
        vault = SecretVault()
        plaintext = "this-should-be-encrypted"
        metadata = run_async(vault.create_secret(
            name="test",
            value=plaintext,
        ))
        # Check that the stored value is not the plaintext
        stored = vault._secrets[metadata.id][1]
        assert stored != plaintext.encode("utf-8")
        assert plaintext.encode("utf-8") not in stored

    def test_rotate_secret_increments_version(self):
        vault = SecretVault()
        metadata = run_async(vault.create_secret(
            name="rotate-test",
            value="original-value",
        ))
        assert metadata.version == 1

        updated = run_async(vault.rotate_secret(metadata.id, "new-value"))
        assert updated is not None
        assert updated.version == 2
        assert updated.rotated_at is not None

    def test_rotate_secret_preserves_old_version(self):
        vault = SecretVault()
        metadata = run_async(vault.create_secret(
            name="rotate-test",
            value="v1-value",
        ))
        run_async(vault.rotate_secret(metadata.id, "v2-value"))

        # Can still access old version
        v1 = run_async(vault.get_secret(metadata.id, "agent-1", version=1))
        v2 = run_async(vault.get_secret(metadata.id, "agent-1", version=2))
        assert v1 == "v1-value"
        assert v2 == "v2-value"

    def test_revoke_secret_blocks_access(self):
        vault = SecretVault()
        metadata = run_async(vault.create_secret(
            name="revoke-test",
            value="secret-val",
        ))
        result = run_async(vault.revoke_secret(metadata.id))
        assert result is True

        value = run_async(vault.get_secret(metadata.id, "agent-1"))
        assert value is None

    def test_bulk_revoke_for_agent(self):
        vault = SecretVault()
        m1 = run_async(vault.create_secret(
            name="s1", value="v1", bound_agents=["agent-a"],
        ))
        m2 = run_async(vault.create_secret(
            name="s2", value="v2", bound_agents=["agent-a"],
        ))
        m3 = run_async(vault.create_secret(
            name="s3", value="v3", bound_agents=["agent-b"],
        ))

        revoked = run_async(vault.bulk_revoke_for_agent("agent-a"))
        assert len(revoked) == 2
        assert m1.id in revoked
        assert m2.id in revoked
        assert m3.id not in revoked

    def test_bound_agents_restricts_access(self):
        vault = SecretVault()
        metadata = run_async(vault.create_secret(
            name="bound-test",
            value="secret",
            bound_agents=["agent-allowed"],
        ))

        allowed_value = run_async(vault.get_secret(metadata.id, "agent-allowed"))
        denied_value = run_async(vault.get_secret(metadata.id, "agent-denied"))
        assert allowed_value == "secret"
        assert denied_value is None

    def test_expired_secret_returns_none(self):
        vault = SecretVault()
        past = datetime.now(timezone.utc) - timedelta(hours=1)
        metadata = run_async(vault.create_secret(
            name="expired",
            value="old-secret",
            expires_at=past,
        ))
        value = run_async(vault.get_secret(metadata.id, "agent-1"))
        assert value is None

    def test_list_secrets_returns_metadata_only(self):
        vault = SecretVault()
        company = uuid.uuid4()
        run_async(vault.create_secret(
            name="s1", value="val1", company_id=company,
        ))
        run_async(vault.create_secret(
            name="s2", value="val2", company_id=company,
        ))

        secrets = vault.list_secrets(company_id=company)
        assert len(secrets) == 2
        for s in secrets:
            assert isinstance(s, SecretMetadata)
            # Values should not appear in metadata
            assert "val1" not in str(s)
            assert "val2" not in str(s)

    def test_access_log_records_all_attempts(self):
        vault = SecretVault()
        metadata = run_async(vault.create_secret(
            name="logged", value="val", bound_agents=["agent-1"],
        ))
        run_async(vault.get_secret(metadata.id, "agent-1"))
        run_async(vault.get_secret(metadata.id, "agent-2"))

        log = vault.get_access_log(secret_id=metadata.id)
        # create + successful get + failed get
        assert len(log) >= 2
        # Check that failures are logged
        denied = [e for e in log if not e.success]
        assert len(denied) >= 1

    def test_secret_categories(self):
        vault = SecretVault()
        for cat in SecretCategory:
            metadata = run_async(vault.create_secret(
                name=f"test-{cat.value}",
                value="val",
                category=cat,
            ))
            assert metadata.category == cat


class TestSecretAccessController:
    """Tests for SecretAccessController."""

    def test_bind_and_check_access(self):
        controller = SecretAccessController()
        secret_id = uuid.uuid4()
        run_async(controller.bind_secret_to_agent(secret_id, "agent-1"))

        has_access = run_async(controller.check_access(secret_id, "agent-1"))
        no_access = run_async(controller.check_access(secret_id, "agent-2"))
        assert has_access is True
        assert no_access is False

    def test_unbind_revokes_access(self):
        controller = SecretAccessController()
        secret_id = uuid.uuid4()
        run_async(controller.bind_secret_to_agent(secret_id, "agent-1"))
        run_async(controller.unbind_secret(secret_id, "agent-1"))

        has_access = run_async(controller.check_access(secret_id, "agent-1"))
        assert has_access is False

    def test_time_limited_access_before_expiry(self):
        controller = SecretAccessController()
        secret_id = uuid.uuid4()
        future = datetime.now(timezone.utc) + timedelta(hours=1)
        run_async(controller.grant_time_limited_access(
            secret_id, "agent-1", expires_at=future,
        ))

        has_access = run_async(controller.check_access(secret_id, "agent-1"))
        assert has_access is True

    def test_time_limited_access_after_expiry(self):
        controller = SecretAccessController()
        secret_id = uuid.uuid4()
        past = datetime.now(timezone.utc) - timedelta(hours=1)
        run_async(controller.grant_time_limited_access(
            secret_id, "agent-1", expires_at=past,
        ))

        has_access = run_async(controller.check_access(secret_id, "agent-1"))
        assert has_access is False

    def test_one_time_access_consumed_after_use(self):
        controller = SecretAccessController()
        secret_id = uuid.uuid4()
        run_async(controller.grant_one_time_access(secret_id, "agent-1"))

        # First access succeeds
        first = run_async(controller.check_access(secret_id, "agent-1"))
        assert first is True

        # Second access fails (consumed)
        second = run_async(controller.check_access(secret_id, "agent-1"))
        assert second is False

    def test_emergency_revoke_all(self):
        controller = SecretAccessController()
        s1 = uuid.uuid4()
        s2 = uuid.uuid4()
        s3 = uuid.uuid4()
        run_async(controller.bind_secret_to_agent(s1, "agent-1"))
        run_async(controller.bind_secret_to_agent(s2, "agent-1"))
        run_async(controller.bind_secret_to_agent(s3, "agent-2"))

        count = run_async(controller.emergency_revoke_all("agent-1"))
        assert count == 2

        # Agent-1 has no access to anything
        assert run_async(controller.check_access(s1, "agent-1")) is False
        assert run_async(controller.check_access(s2, "agent-1")) is False
        # Agent-2 still has access
        assert run_async(controller.check_access(s3, "agent-2")) is True

    def test_audit_trail_records_actions(self):
        controller = SecretAccessController()
        secret_id = uuid.uuid4()
        run_async(controller.bind_secret_to_agent(secret_id, "agent-1"))
        run_async(controller.check_access(secret_id, "agent-1"))
        run_async(controller.check_access(secret_id, "agent-2"))

        trail = controller.get_access_audit_trail(agent_id="agent-1")
        assert len(trail) >= 2  # bind + check

    def test_get_active_grants(self):
        controller = SecretAccessController()
        s1 = uuid.uuid4()
        s2 = uuid.uuid4()
        run_async(controller.bind_secret_to_agent(s1, "agent-1"))
        run_async(controller.bind_secret_to_agent(s2, "agent-1"))
        run_async(controller.unbind_secret(s1, "agent-1"))

        grants = controller.get_active_grants(agent_id="agent-1")
        assert len(grants) == 1
        assert grants[0].secret_id == s2


if __name__ == "__main__":
    # Run tests directly
    passed = 0
    failed = 0

    for cls in [TestSecretVault, TestSecretAccessController]:
        instance = cls()
        for method_name in dir(instance):
            if method_name.startswith("test_"):
                try:
                    getattr(instance, method_name)()
                    passed += 1
                    print(f"  PASS: {cls.__name__}.{method_name}")
                except Exception as e:
                    failed += 1
                    print(f"  FAIL: {cls.__name__}.{method_name}: {e}")

    print(f"\n{passed} passed, {failed} failed")
    sys.exit(0 if failed == 0 else 1)
