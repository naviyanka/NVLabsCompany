"""Ed25519 signature verification for multi-party approvals.

A ``status="approved"`` row is only as trustworthy as the request that wrote it.
An operator session that gets replayed, or a compromised admin token, can flip
that column. A signature cannot be produced without the private key, which never
reaches the platform -- so a high-risk operation gated on N distinct signatures
survives a breach of the platform itself.

The bytes signed are canonical: the same approval always produces the same
message, and changing what was approved (the payload, the amount, the target
file) invalidates every signature already collected.
"""

from __future__ import annotations

import base64
import json
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

# Approval types that must never rest on one operator's word. Anything not
# listed keeps the historical single-signature behaviour, so adding signing to
# the platform does not silently gate every existing flow.
HIGH_RISK_APPROVAL_TYPES: dict[str, int] = {
    "budget_override": 2,
    "deployment": 2,
    "destructive_file_write": 2,
    "secret_request": 2,
}

# Spend above this needs a quorum regardless of the approval's type, because the
# roadmap's threshold is a dollar amount and a request can carry any label.
HIGH_RISK_SPEND_CENTS = 10_000


class SignatureError(Exception):
    """A signature was malformed, did not verify, or its key is not trusted."""


def canonical_approval_bytes(
    approval_id: Any,
    company_id: Any,
    approval_type: str,
    payload: dict[str, Any] | None,
) -> bytes:
    """The exact bytes a signer signs for one approval.

    Includes the payload, so a signature collected for "deploy commit abc" does
    not carry over to "deploy commit def" -- swapping the payload after the fact
    invalidates every signature on the row.

    Args:
        approval_id: The approval's id.
        company_id: Owning company, so a signature cannot be replayed across
            tenants.
        approval_type: The approval type.
        payload: The approval payload, or None.

    Returns:
        Deterministic UTF-8 bytes.
    """
    return json.dumps(
        {
            "approval_id": str(approval_id),
            "company_id": str(company_id),
            "type": approval_type,
            "payload": payload or {},
        },
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")


def required_signatures_for(
    approval_type: str, payload: dict[str, Any] | None
) -> int:
    """How many distinct signatures an approval of this shape needs.

    Args:
        approval_type: The approval type.
        payload: The approval payload; an ``amount_cents`` above
            :data:`HIGH_RISK_SPEND_CENTS` forces a quorum whatever the type.

    Returns:
        The signature count, at least 1.
    """
    required = HIGH_RISK_APPROVAL_TYPES.get(approval_type, 1)
    amount = (payload or {}).get("amount_cents")
    if isinstance(amount, (int, float)) and amount >= HIGH_RISK_SPEND_CENTS:
        required = max(required, 2)
    return required


def verify_signature(public_key_b64: str, message: bytes, signature_b64: str) -> None:
    """Check one Ed25519 signature over ``message``.

    Args:
        public_key_b64: Base64 raw 32-byte Ed25519 public key.
        message: The bytes from :func:`canonical_approval_bytes`.
        signature_b64: Base64 signature.

    Raises:
        SignatureError: The key or signature is malformed, or verification
            failed. Both collapse into one error on purpose: telling a caller
            which of the two it was tells an attacker which half to vary.
    """
    try:
        key = Ed25519PublicKey.from_public_bytes(base64.b64decode(public_key_b64))
        key.verify(base64.b64decode(signature_b64), message)
    except (InvalidSignature, ValueError, TypeError) as exc:
        raise SignatureError("signature did not verify") from exc


if __name__ == "__main__":  # pragma: no cover - self-check
    import uuid

    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    private = Ed25519PrivateKey.generate()
    pub = base64.b64encode(
        private.public_key().public_bytes_raw()
    ).decode()

    approval_id, company_id = uuid.uuid4(), uuid.uuid4()
    message = canonical_approval_bytes(
        approval_id, company_id, "deployment", {"commit": "abc"}
    )
    sig = base64.b64encode(private.sign(message)).decode()
    verify_signature(pub, message, sig)

    # A changed payload must invalidate the signature.
    tampered = canonical_approval_bytes(
        approval_id, company_id, "deployment", {"commit": "def"}
    )
    try:
        verify_signature(pub, tampered, sig)
        raise AssertionError("tampered payload verified")
    except SignatureError:
        pass

    assert required_signatures_for("deployment", None) == 2
    assert required_signatures_for("chat_note", None) == 1
    assert required_signatures_for("chat_note", {"amount_cents": 50_000}) == 2
    print("approval signing self-check OK")
