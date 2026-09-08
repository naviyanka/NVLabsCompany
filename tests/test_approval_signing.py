"""Tests for cryptographic multi-party approval signing.

The guarantee is that a high-risk approval cannot reach status="approved" on one
party's word alone, and that a signature is bound to exactly what was approved.
These drive a real SQLite database because the quorum count and the
one-signature-per-party rule live in SQL.
"""

import base64
import uuid

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlmodel import SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession

from nexus.governance.approval_signing import (
    SignatureError,
    canonical_approval_bytes,
    required_signatures_for,
)
from nexus.models.governance import Approval, ApprovalSignature, ApprovalSignerKey
from nexus.services.approval_service import ApprovalService


@pytest.fixture
async def session_factory(tmp_path):
    """A SQLite database holding just the approval tables."""
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'approvals.db'}")
    async with engine.begin() as conn:
        await conn.run_sync(
            SQLModel.metadata.create_all,
            tables=[
                Approval.__table__,
                ApprovalSignerKey.__table__,
                ApprovalSignature.__table__,
            ],
        )
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    yield factory
    await engine.dispose()


def _keypair() -> tuple[Ed25519PrivateKey, str]:
    """A private key and its base64 public half, as enrolled."""
    private = Ed25519PrivateKey.generate()
    return private, base64.b64encode(private.public_key().public_bytes_raw()).decode()


async def _enrol(factory, company_id: uuid.UUID, subject: str) -> Ed25519PrivateKey:
    """Register one signer's public key and hand back the private half."""
    private, public = _keypair()
    async with factory() as db:
        db.add(
            ApprovalSignerKey(
                company_id=company_id, subject=subject, public_key=public
            )
        )
        await db.commit()
    return private


def _sign(private: Ed25519PrivateKey, approval: Approval) -> str:
    """Sign an approval's canonical bytes the way a client would."""
    message = canonical_approval_bytes(
        approval.id, approval.company_id, approval.type, approval.payload
    )
    return base64.b64encode(private.sign(message)).decode()


class TestRequiredSignatures:
    """Quorum is decided by the approval's shape, not by the caller."""

    def test_high_risk_type_needs_two(self):
        """A deployment is not a one-operator decision."""
        assert required_signatures_for("deployment", None) == 2

    def test_ordinary_type_needs_one(self):
        """Everything else keeps the historical single-approver behaviour."""
        assert required_signatures_for("routine_note", None) == 1

    def test_large_spend_forces_quorum_regardless_of_type(self):
        """A request can carry any label; the amount at stake still gates it."""
        assert required_signatures_for("routine_note", {"amount_cents": 50_000}) == 2


class TestQuorumGatesApproval:
    """approve() must refuse until the quorum is met."""

    async def test_approve_refused_below_quorum(self, session_factory):
        """One signature on a two-party request is not enough."""
        company_id, agent_id = uuid.uuid4(), uuid.uuid4()
        alice = await _enrol(session_factory, company_id, "alice@example.com")

        async with session_factory() as db:
            service = ApprovalService(db)
            approval = await service.request_approval(
                company_id, "deployment", agent_id, payload={"commit": "abc"}
            )
            await db.commit()
            assert approval.required_signatures == 2

            await service.add_signature(
                approval.id, "alice@example.com", _sign(alice, approval)
            )
            await db.commit()

            with pytest.raises(SignatureError, match="needs 2 signatures"):
                await service.approve(approval.id, decided_by="alice@example.com")

    async def test_approve_succeeds_at_quorum(self, session_factory):
        """Two distinct signers unlock the approval."""
        company_id, agent_id = uuid.uuid4(), uuid.uuid4()
        alice = await _enrol(session_factory, company_id, "alice@example.com")
        bob = await _enrol(session_factory, company_id, "bob@example.com")

        async with session_factory() as db:
            service = ApprovalService(db)
            approval = await service.request_approval(
                company_id, "deployment", agent_id, payload={"commit": "abc"}
            )
            await db.commit()

            await service.add_signature(
                approval.id, "alice@example.com", _sign(alice, approval)
            )
            await service.add_signature(
                approval.id, "bob@example.com", _sign(bob, approval)
            )
            await db.commit()

            decided = await service.approve(approval.id, decided_by="alice@example.com")
            assert decided.status == "approved"

    async def test_single_signature_type_needs_no_signatures(self, session_factory):
        """An ordinary approval still approves with no signing ceremony."""
        company_id, agent_id = uuid.uuid4(), uuid.uuid4()
        async with session_factory() as db:
            service = ApprovalService(db)
            approval = await service.request_approval(
                company_id, "routine_note", agent_id
            )
            await db.commit()
            decided = await service.approve(approval.id, decided_by="alice@example.com")
        assert decided.status == "approved"


class TestSignatureBinding:
    """A signature must only count for what it actually signed."""

    async def test_signature_over_different_payload_rejected(self, session_factory):
        """Signing "commit abc" does not approve "commit def"."""
        company_id, agent_id = uuid.uuid4(), uuid.uuid4()
        alice = await _enrol(session_factory, company_id, "alice@example.com")

        async with session_factory() as db:
            service = ApprovalService(db)
            approval = await service.request_approval(
                company_id, "deployment", agent_id, payload={"commit": "abc"}
            )
            await db.commit()

            other = Approval(
                id=approval.id,
                company_id=company_id,
                type="deployment",
                payload={"commit": "def"},
            )
            with pytest.raises(SignatureError, match="did not verify"):
                await service.add_signature(
                    approval.id, "alice@example.com", _sign(alice, other)
                )

    async def test_unenrolled_signer_rejected(self, session_factory):
        """A valid signature from an unknown key is still not an approval."""
        company_id, agent_id = uuid.uuid4(), uuid.uuid4()
        stranger, _ = _keypair()

        async with session_factory() as db:
            service = ApprovalService(db)
            approval = await service.request_approval(
                company_id, "deployment", agent_id, payload={"commit": "abc"}
            )
            await db.commit()

            with pytest.raises(SignatureError, match="no active signer key"):
                await service.add_signature(
                    approval.id, "stranger@example.com", _sign(stranger, approval)
                )

    async def test_same_party_cannot_sign_twice(self, session_factory):
        """One operator signing twice must not satisfy a two-party quorum."""
        company_id, agent_id = uuid.uuid4(), uuid.uuid4()
        alice = await _enrol(session_factory, company_id, "alice@example.com")

        async with session_factory() as db:
            service = ApprovalService(db)
            approval = await service.request_approval(
                company_id, "deployment", agent_id, payload={"commit": "abc"}
            )
            await db.commit()

            signature = _sign(alice, approval)
            await service.add_signature(approval.id, "alice@example.com", signature)
            await db.commit()

            with pytest.raises(SignatureError, match="already signed"):
                await service.add_signature(approval.id, "alice@example.com", signature)

    async def test_revoked_key_cannot_sign(self, session_factory):
        """Deactivating a key removes its ability to sign new approvals."""
        company_id, agent_id = uuid.uuid4(), uuid.uuid4()
        alice = await _enrol(session_factory, company_id, "alice@example.com")

        async with session_factory() as db:
            keys = await db.execute(
                ApprovalSignerKey.__table__.select().where(
                    ApprovalSignerKey.subject == "alice@example.com"
                )
            )
            key_id = keys.one()[0]
            await db.execute(
                ApprovalSignerKey.__table__.update()
                .where(ApprovalSignerKey.id == key_id)
                .values(is_active=False)
            )
            await db.commit()

        async with session_factory() as db:
            service = ApprovalService(db)
            approval = await service.request_approval(
                company_id, "deployment", agent_id, payload={"commit": "abc"}
            )
            await db.commit()

            with pytest.raises(SignatureError, match="no active signer key"):
                await service.add_signature(
                    approval.id, "alice@example.com", _sign(alice, approval)
                )
