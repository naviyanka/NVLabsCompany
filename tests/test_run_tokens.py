"""Tests for run JWTs (Phase 5.1).

The plan's acceptance test is one sentence -- "a run token works during its run
and fails after expiry" -- and it is the first test here. The rest cover the
ways a token can be wrong that are not expiry, because each of them would
otherwise fail open: a token signed with another secret, a token for a different
audience, a token missing the claims that scope it. All four have to be
rejections, and the middleware has to turn a rejection into an anonymous request
rather than a 500.
"""

import uuid

import pytest

from nexus.api.deps import require_run
from nexus.auth.middleware import AuthenticationMiddleware
from nexus.auth.principal import Principal
from nexus.auth.run_tokens import (
    ALGORITHM,
    AUDIENCE,
    RunTokenError,
    assert_pyjwt,
    looks_like_run_token,
    mint_run_token,
    verify_run_token,
)
from nexus.config import settings


@pytest.fixture
def ids():
    """The three ids a run token scopes work to."""
    return uuid.uuid4(), uuid.uuid4(), uuid.uuid4()


class TestMintAndVerify:
    """5.1.1 / 5.1.2 -- the round trip and its expiry boundary."""

    def test_token_works_during_its_run(self, ids):
        """The acceptance test, first half: a live token yields its three ids."""
        run_id, agent_id, company_id = ids

        token = mint_run_token(run_id, agent_id, company_id)

        assert verify_run_token(token) == (run_id, agent_id, company_id)

    def test_token_fails_after_expiry(self, ids):
        """The acceptance test, second half: a lapsed token is refused.

        A negative TTL puts ``exp`` in the past at mint time, which is the same
        state a token reaches on its own a quarter of an hour later.
        """
        token = mint_run_token(*ids, ttl_seconds=-1)

        with pytest.raises(RunTokenError):
            verify_run_token(token)

    def test_company_id_is_not_caller_supplied(self, ids):
        """The company comes out of the signed payload, not out of a header.

        This is the property the whole design rests on: a run principal's tenant
        is fixed at mint time, so an agent cannot point its token at another
        company the way an ``X-Company-Id`` header could be repointed.
        """
        run_id, agent_id, company_id = ids
        other_company = uuid.uuid4()

        _, _, resolved = verify_run_token(mint_run_token(run_id, agent_id, company_id))

        assert resolved == company_id
        assert resolved != other_company


class TestRejections:
    """Every way a token can be wrong ends in RunTokenError, never in a pass."""

    def test_wrong_secret_is_refused(self, ids, monkeypatch):
        """A token signed with a secret we do not hold must not verify."""
        import jwt

        from nexus.models._time import utcnow

        forged = jwt.encode(
            {
                "sub": str(ids[1]),
                "run_id": str(ids[0]),
                "company_id": str(ids[2]),
                "aud": AUDIENCE,
                "exp": utcnow().timestamp() + 900,
            },
            # 32 bytes: shorter keys are valid HMAC keys but make PyJWT warn,
            # and a warning in a passing test trains people to ignore warnings.
            "a-different-secret-of-sufficient-length",
            algorithm=ALGORITHM,
        )

        with pytest.raises(RunTokenError):
            verify_run_token(forged)

    def test_wrong_audience_is_refused(self, ids):
        """A token signed with our secret but minted for something else.

        Without the audience check, any other JWT the deployment signs with the
        same secret -- a password reset link, a download URL -- would be accepted
        here as a run credential.
        """
        import jwt

        from nexus.models._time import utcnow

        other = jwt.encode(
            {
                "sub": str(ids[1]),
                "run_id": str(ids[0]),
                "company_id": str(ids[2]),
                "aud": "some-other-service",
                "exp": utcnow().timestamp() + 900,
            },
            settings.secret_key,
            algorithm=ALGORITHM,
        )

        with pytest.raises(RunTokenError):
            verify_run_token(other)

    def test_missing_claim_is_refused(self, ids):
        """A token with no ``company_id`` cannot be scoped, so it is not usable."""
        import jwt

        from nexus.models._time import utcnow

        partial = jwt.encode(
            {
                "sub": str(ids[1]),
                "run_id": str(ids[0]),
                "aud": AUDIENCE,
                "exp": utcnow().timestamp() + 900,
            },
            settings.secret_key,
            algorithm=ALGORITHM,
        )

        with pytest.raises(RunTokenError):
            verify_run_token(partial)

    def test_no_expiry_is_refused(self, ids):
        """A token without ``exp`` would be a permanent credential."""
        import jwt

        forever = jwt.encode(
            {
                "sub": str(ids[1]),
                "run_id": str(ids[0]),
                "company_id": str(ids[2]),
                "aud": AUDIENCE,
            },
            settings.secret_key,
            algorithm=ALGORITHM,
        )

        with pytest.raises(RunTokenError):
            verify_run_token(forever)

    def test_garbage_is_refused_not_raised_through(self):
        """Nonsense in the header is a RunTokenError, not a ValueError."""
        with pytest.raises(RunTokenError):
            verify_run_token("not-a-token")


class TestCredentialShape:
    """An API key must not be fed to the JWT decoder, or vice versa."""

    def test_api_key_is_not_mistaken_for_a_run_token(self):
        """``nv_...`` keys have no dots, so the JWT path skips them."""
        assert looks_like_run_token("nv_abc123def456") is False

    def test_minted_token_is_recognised(self, ids):
        assert looks_like_run_token(mint_run_token(*ids)) is True


class TestMiddlewareIntegration:
    """5.1.2 -- the middleware turns a token into a principal, or into nobody."""

    def test_valid_token_becomes_a_run_principal(self, ids):
        run_id, agent_id, company_id = ids
        mw = AuthenticationMiddleware(app=None)

        principal = mw._principal_from_run_token(mint_run_token(run_id, agent_id, company_id))

        assert principal is not None
        assert principal.kind == "run"
        assert principal.company_id == company_id
        assert principal.run_id == run_id
        assert principal.agent_id == agent_id

    def test_expired_token_resolves_to_nobody(self, ids):
        """An expired token is anonymity, not an error.

        The route then answers 401 through the normal path, which is what an
        agent whose run has ended should see -- not a 500 from a decode error.
        """
        mw = AuthenticationMiddleware(app=None)

        assert mw._principal_from_run_token(mint_run_token(*ids, ttl_seconds=-1)) is None

    def test_run_principal_role_is_not_token_controlled(self, ids):
        """The role is fixed at ``agent`` rather than read from a claim.

        A token that named its own role would let whoever mints one grant itself
        admin over the tenant.
        """
        mw = AuthenticationMiddleware(app=None)

        principal = mw._principal_from_run_token(mint_run_token(*ids))

        assert principal.role == "agent"
        assert principal.has_permission("write", "company") is False


class TestRequireRun:
    """The dependency that admits only run callers."""

    def test_run_principal_passes(self, ids):
        run_id, agent_id, company_id = ids
        principal = Principal(
            kind="run",
            company_id=company_id,
            role="agent",
            run_id=run_id,
            agent_id=agent_id,
        )

        assert require_run(principal) is principal

    @pytest.mark.parametrize("kind", ["user", "service"])
    def test_other_kinds_are_refused(self, kind):
        """A session or API key outlives the run, so neither substitutes for one."""
        from fastapi import HTTPException

        principal = Principal(kind=kind, company_id=uuid.uuid4(), role="admin")

        with pytest.raises(HTTPException) as exc:
            require_run(principal)
        assert exc.value.status_code == 403


def test_jwt_import_is_pyjwt():
    """5.1.3 -- python-jose must not be what provides the ``jwt`` name.

    python-jose signs through the pure-Python ``ecdsa`` package, which has a
    known non-constant-time weakness (CVE-2024-23342) its maintainers treat as
    out of scope. Both packages publish a module called ``jwt``, so the wrong
    one winning the import is a silent crypto downgrade -- every call in
    run_tokens.py would still appear to work.
    """
    assert_pyjwt()
