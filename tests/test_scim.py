"""Tests for the SCIM 2.0 provisioning surface (E-04 gap closure).

The routes take a raw ``Request`` for bearer-token checking rather than a
FastAPI dependency, so these call the handlers directly with a stub request,
matching the direct-handler style in ``tests/test_repository_clone.py``.
"""

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from nexus.api.routes import scim as scim_routes
from nexus.models.user_profile import UserProfile

TOKEN = "scim-test-token"
COMPANY_ID = uuid.UUID("00000000-0000-4000-8000-000000000001")
OTHER_COMPANY_ID = uuid.uuid4()


class _Request:
    """Minimal stand-in for ``fastapi.Request``: headers plus a JSON body."""

    def __init__(self, token: str | None = TOKEN, body: dict | None = None):
        self.headers = {} if token is None else {"Authorization": f"Bearer {token}"}
        self._body = body or {}

    async def json(self) -> dict:
        return self._body


class _OneResult:
    def __init__(self, value):
        self._value = value

    def scalar_one_or_none(self):
        return self._value


class _ManyResult:
    def __init__(self, values):
        self._values = values

    def scalars(self):
        return self

    def all(self):
        return list(self._values)


class _CountResult:
    def __init__(self, total):
        self._total = total

    def scalar(self):
        return self._total


class _FirstResult:
    """A result that answers ``.scalars().first()``, as get_membership uses."""

    def __init__(self, value):
        self._value = value

    def scalars(self):
        return self

    def first(self):
        return self._value


def _create_session(existing_user=None, existing_membership=None) -> AsyncMock:
    """Session for ``create_user``.

    Two selects run: the duplicate-email check, then ``get_membership`` inside
    ``grant_membership``. ``pick_setup_company`` resolves through ``db.get``.
    """
    session = _session()
    session.execute = AsyncMock(
        side_effect=[_OneResult(existing_user), _FirstResult(existing_membership)]
    )
    session.get = AsyncMock(return_value=_company())
    return session


def _list_session(page, total=None) -> AsyncMock:
    """``list_users`` issues the page select, then a COUNT over the same filter."""
    session = _session()
    session.execute = AsyncMock(
        side_effect=[_ManyResult(page), _CountResult(len(page) if total is None else total)]
    )
    return session


def _user(**kw) -> UserProfile:
    defaults = dict(
        id=uuid.uuid4(),
        company_id=COMPANY_ID,
        email="ada@example.com",
        hashed_password="",
        first_name="Ada",
        last_name="Lovelace",
        is_active=True,
        oidc_sub="ext-1",
    )
    defaults.update(kw)
    return UserProfile(**defaults)


def _company():
    from nexus.models.company import Company

    return Company(id=COMPANY_ID, name="NVLabs", status="active")


def _session(execute_result=None) -> AsyncMock:
    """AsyncMock session with a synchronous ``add``, as SQLAlchemy has."""
    session = AsyncMock()
    session.add = MagicMock()
    if execute_result is not None:
        session.execute = AsyncMock(return_value=execute_result)
    return session


@pytest.fixture(autouse=True)
def _scim_token(monkeypatch):
    monkeypatch.setenv("SCIM_BEARER_TOKEN", TOKEN)


# --------------------------------------------------------------------------
# Token gate
# --------------------------------------------------------------------------


def test_verify_rejects_missing_header():
    with pytest.raises(Exception) as exc:
        scim_routes._verify_scim_token(_Request(token=None))
    assert exc.value.status_code == 401


def test_verify_rejects_wrong_token():
    with pytest.raises(Exception) as exc:
        scim_routes._verify_scim_token(_Request(token="nope"))
    assert exc.value.status_code == 401


def test_verify_returns_501_when_unconfigured(monkeypatch):
    """An unset SCIM_BEARER_TOKEN closes the surface rather than opening it."""
    monkeypatch.delenv("SCIM_BEARER_TOKEN", raising=False)
    with pytest.raises(Exception) as exc:
        scim_routes._verify_scim_token(_Request())
    assert exc.value.status_code == 501


def test_verify_accepts_matching_token():
    assert scim_routes._verify_scim_token(_Request()) is None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "call",
    [
        lambda s: scim_routes.list_users(_Request(token=None), s),
        lambda s: scim_routes.get_user(uuid.uuid4(), _Request(token=None), s),
        lambda s: scim_routes.replace_user(
            uuid.uuid4(), scim_routes.ScimUserRequest(userName="x@y.z"), _Request(token=None), s
        ),
        lambda s: scim_routes.patch_user(uuid.uuid4(), _Request(token=None), s),
        lambda s: scim_routes.delete_user(uuid.uuid4(), _Request(token=None), s),
    ],
    ids=["list", "get", "put", "patch", "delete"],
)
async def test_every_route_enforces_the_token(call):
    """No route may reach the database before the bearer check."""
    session = _session()
    with pytest.raises(Exception) as exc:
        await call(session)
    assert exc.value.status_code == 401
    session.execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_create_enforces_the_token():
    session = _session()
    body = scim_routes.ScimUserRequest(userName="x@y.z")
    with pytest.raises(Exception) as exc:
        await scim_routes.create_user(body, _Request(token=None), session)
    assert exc.value.status_code == 401
    session.add.assert_not_called()


# --------------------------------------------------------------------------
# Serialisation
# --------------------------------------------------------------------------


def test_user_to_scim_shape():
    user = _user()
    payload = scim_routes._user_to_scim(user)
    assert payload["schemas"] == [scim_routes.SCIM_SCHEMA_USER]
    assert payload["id"] == str(user.id)
    assert payload["userName"] == "ada@example.com"
    assert payload["externalId"] == "ext-1"
    assert payload["name"] == {"givenName": "Ada", "familyName": "Lovelace"}
    assert payload["emails"] == [{"value": "ada@example.com", "primary": True}]
    assert payload["active"] is True
    assert payload["meta"]["resourceType"] == "User"
    assert payload["meta"]["created"]
    assert payload["meta"]["lastModified"]


def test_user_to_scim_null_external_id_becomes_empty_string():
    payload = scim_routes._user_to_scim(_user(oidc_sub=None))
    assert payload["externalId"] == ""


# --------------------------------------------------------------------------
# GET /scim/v2/Users
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_users_returns_list_response():
    users = [_user(), _user(email="grace@example.com")]
    session = _list_session(users)

    body = await scim_routes.list_users(_Request(), session)

    assert body["schemas"] == [scim_routes.SCIM_SCHEMA_LIST]
    assert body["startIndex"] == 1
    assert body["itemsPerPage"] == 100
    assert body["totalResults"] == 2
    assert [r["userName"] for r in body["Resources"]] == [
        "ada@example.com",
        "grace@example.com",
    ]


@pytest.mark.asyncio
async def test_list_users_echoes_pagination_arguments():
    session = _list_session([])

    body = await scim_routes.list_users(_Request(), session, startIndex=11, count=5)

    assert body["startIndex"] == 11
    assert body["itemsPerPage"] == 5
    assert body["totalResults"] == 0
    assert body["Resources"] == []


@pytest.mark.asyncio
async def test_list_users_totalresults_counts_the_whole_match():
    """``totalResults`` is the match size, not the page size (RFC 7644 3.4.2.4).

    A full page must not look like the last page, or an IdP stops paging early.
    """
    session = _list_session([_user() for _ in range(3)], total=57)

    body = await scim_routes.list_users(_Request(), session, startIndex=1, count=3)

    assert body["totalResults"] == 57
    assert len(body["Resources"]) == 3


@pytest.mark.asyncio
async def test_list_users_totalresults_survives_a_null_count():
    session = _list_session([_user()])
    session.execute = AsyncMock(side_effect=[_ManyResult([_user()]), _CountResult(None)])

    body = await scim_routes.list_users(_Request(), session)

    assert body["totalResults"] == 0


@pytest.mark.asyncio
async def test_list_users_filters_on_quoted_username():
    session = _list_session([_user()])

    body = await scim_routes.list_users(
        _Request(), session, filter='userName eq "ada@example.com"'
    )

    assert body["totalResults"] == 1
    page_stmt = str(session.execute.await_args_list[0].args[0])
    assert "WHERE user_profiles.email" in page_stmt
    count_stmt = str(session.execute.await_args_list[1].args[0])
    assert "count(" in count_stmt
    assert "WHERE user_profiles.email" in count_stmt


@pytest.mark.asyncio
async def test_list_users_ignores_unquoted_filter():
    session = _list_session([_user()])

    await scim_routes.list_users(_Request(), session, filter="userName eq ada@example.com")

    assert "WHERE" not in str(session.execute.await_args_list[0].args[0])


@pytest.mark.asyncio
async def test_list_users_ignores_unsupported_filter_attribute():
    """A filter the parser does not understand widens to every user.

    SCIM clients send ``active eq false``, ``emails.value eq ...`` and similar.
    Only ``userName eq`` is handled, and anything else falls through to an
    unfiltered select rather than a 400, so the caller silently receives the
    whole directory.
    """
    session = _list_session([_user(), _user()])

    body = await scim_routes.list_users(_Request(), session, filter='active eq "false"')

    assert "WHERE" not in str(session.execute.await_args_list[0].args[0])
    assert body["totalResults"] == 2


# --------------------------------------------------------------------------
# GET /scim/v2/Users/{id}
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_user_returns_resource():
    user = _user()
    session = _session()
    session.execute = AsyncMock(return_value=_OneResult(user))

    body = await scim_routes.get_user(user.id, _Request(), session)

    assert body["id"] == str(user.id)
    assert body["userName"] == user.email


@pytest.mark.asyncio
async def test_get_user_unknown_id_is_404():
    session = _session()
    session.execute = AsyncMock(return_value=_OneResult(None))

    with pytest.raises(Exception) as exc:
        await scim_routes.get_user(uuid.uuid4(), _Request(), session)

    assert exc.value.status_code == 404
    assert exc.value.detail == "User not found"


@pytest.mark.asyncio
async def test_get_user_is_not_tenant_scoped():
    """A SCIM token reads a user from any company.

    The select filters on ``id`` alone (``scim.py:123``) and the handler takes
    no ``CurrentCompanyId``, so one identity provider's token reaches every
    tenant's users. Documented here; changing it alters who can call the API.
    """
    foreign = _user(company_id=OTHER_COMPANY_ID, email="outsider@other.example")
    session = _session()
    session.execute = AsyncMock(return_value=_OneResult(foreign))

    body = await scim_routes.get_user(foreign.id, _Request(), session)

    assert body["userName"] == "outsider@other.example"
    where = str(session.execute.await_args.args[0]).split("WHERE", 1)[1]
    assert "company_id" not in where


# --------------------------------------------------------------------------
# POST /scim/v2/Users
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_user_provisions_from_username():
    session = _create_session()
    body = scim_routes.ScimUserRequest(
        userName="grace@example.com",
        name=scim_routes.ScimName(givenName="Grace", familyName="Hopper"),
        externalId="ext-42",
    )

    payload = await scim_routes.create_user(body, _Request(), session)

    created = session.add.call_args_list[0].args[0]
    assert created.email == "grace@example.com"
    assert created.first_name == "Grace"
    assert created.last_name == "Hopper"
    assert created.oidc_sub == "ext-42"
    assert created.is_active is True
    assert created.is_verified is True
    assert created.hashed_password == ""
    session.commit.assert_awaited_once()
    assert payload["userName"] == "grace@example.com"


@pytest.mark.asyncio
async def test_create_user_falls_back_to_primary_email():
    session = _create_session()
    body = scim_routes.ScimUserRequest(
        emails=[scim_routes.ScimEmail(value="fallback@example.com")]
    )

    await scim_routes.create_user(body, _Request(), session)

    assert session.add.call_args_list[0].args[0].email == "fallback@example.com"


@pytest.mark.asyncio
async def test_create_user_honours_active_false():
    session = _create_session()
    body = scim_routes.ScimUserRequest(userName="dormant@example.com", active=False)

    await scim_routes.create_user(body, _Request(), session)

    assert session.add.call_args_list[0].args[0].is_active is False


@pytest.mark.asyncio
async def test_create_user_without_identifier_is_400():
    session = _session()
    body = scim_routes.ScimUserRequest()

    with pytest.raises(Exception) as exc:
        await scim_routes.create_user(body, _Request(), session)

    assert exc.value.status_code == 400
    assert exc.value.detail == "userName or email required"
    session.add.assert_not_called()


@pytest.mark.asyncio
async def test_create_user_duplicate_email_is_409():
    session = _create_session(existing_user=_user())
    body = scim_routes.ScimUserRequest(userName="ada@example.com")

    with pytest.raises(Exception) as exc:
        await scim_routes.create_user(body, _Request(), session)

    assert exc.value.status_code == 409
    assert exc.value.detail == "User already exists"
    session.add.assert_not_called()
    session.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_create_user_resolves_the_company_instead_of_hardcoding_it():
    """``company_id`` comes from ``pick_setup_company``, not a literal UUID.

    A hardcoded id writes a user row pointing at a company that need not exist
    on a fresh deployment.
    """
    session = _create_session()
    body = scim_routes.ScimUserRequest(userName="anyone@example.com")

    await scim_routes.create_user(body, _Request(), session)

    session.get.assert_awaited()
    assert session.add.call_args_list[0].args[0].company_id == COMPANY_ID


@pytest.mark.asyncio
async def test_create_user_grants_a_viewer_membership():
    """Without a membership row the provisioned user cannot log in at all.

    ``authenticate_session`` denies any caller whose ``get_membership`` lookup
    is empty, so provisioning must also grant one — at the least-privileged
    role, since an external directory should not be able to mint admins.
    """
    from nexus.models.company import CompanyMembership

    session = _create_session()
    body = scim_routes.ScimUserRequest(userName="newbie@example.com")

    await scim_routes.create_user(body, _Request(), session)

    added = [c.args[0] for c in session.add.call_args_list]
    memberships = [a for a in added if isinstance(a, CompanyMembership)]
    assert len(memberships) == 1
    assert memberships[0].role == scim_routes.SCIM_DEFAULT_ROLE == "viewer"
    assert memberships[0].company_id == COMPANY_ID


# --------------------------------------------------------------------------
# PUT /scim/v2/Users/{id}
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_replace_user_updates_name_active_and_external_id():
    user = _user()
    session = _session()
    session.execute = AsyncMock(return_value=_OneResult(user))
    body = scim_routes.ScimUserRequest(
        userName=user.email,
        name=scim_routes.ScimName(givenName="Augusta", familyName="King"),
        active=False,
        externalId="ext-99",
    )

    payload = await scim_routes.replace_user(user.id, body, _Request(), session)

    assert user.first_name == "Augusta"
    assert user.last_name == "King"
    assert user.is_active is False
    assert user.oidc_sub == "ext-99"
    session.commit.assert_awaited_once()
    assert payload["active"] is False


@pytest.mark.asyncio
async def test_replace_user_does_not_change_the_email():
    """PUT is a full replace in SCIM, but ``userName`` is ignored here.

    ``replace_user`` never assigns ``user.email`` (``scim.py:181-186``), so an
    identity provider renaming a user's ``userName`` sees a 200 and no change.
    """
    user = _user()
    session = _session()
    session.execute = AsyncMock(return_value=_OneResult(user))
    body = scim_routes.ScimUserRequest(userName="renamed@example.com")

    payload = await scim_routes.replace_user(user.id, body, _Request(), session)

    assert user.email == "ada@example.com"
    assert payload["userName"] == "ada@example.com"


@pytest.mark.asyncio
async def test_replace_user_omitting_active_reactivates():
    """``active`` defaults to True, so a payload without it silently re-enables.

    ``scim.py:184`` assigns ``body.active`` unconditionally and the field
    defaults to ``True``, so a PUT that only changes a name resurrects a
    deactivated account.
    """
    user = _user(is_active=False)
    session = _session()
    session.execute = AsyncMock(return_value=_OneResult(user))
    body = scim_routes.ScimUserRequest(
        userName=user.email, name=scim_routes.ScimName(givenName="Ada", familyName="L")
    )

    await scim_routes.replace_user(user.id, body, _Request(), session)

    assert user.is_active is True


@pytest.mark.asyncio
async def test_replace_user_unknown_id_is_404():
    session = _session()
    session.execute = AsyncMock(return_value=_OneResult(None))

    with pytest.raises(Exception) as exc:
        await scim_routes.replace_user(
            uuid.uuid4(), scim_routes.ScimUserRequest(userName="x@y.z"), _Request(), session
        )

    assert exc.value.status_code == 404
    session.commit.assert_not_awaited()


# --------------------------------------------------------------------------
# PATCH /scim/v2/Users/{id}
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_patch_user_deactivates_via_path_operation():
    """The ``path: active`` form Okta and Azure AD send."""
    user = _user()
    session = _session()
    session.execute = AsyncMock(return_value=_OneResult(user))
    request = _Request(
        body={"Operations": [{"op": "replace", "path": "active", "value": False}]}
    )

    payload = await scim_routes.patch_user(user.id, request, session)

    assert user.is_active is False
    assert payload["active"] is False
    session.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_patch_user_deactivates_via_pathless_value_object():
    """The ``value: {active: false}`` form, with no ``path``."""
    user = _user()
    session = _session()
    session.execute = AsyncMock(return_value=_OneResult(user))
    request = _Request(
        body={"Operations": [{"op": "replace", "value": {"active": False}}]}
    )

    await scim_routes.patch_user(user.id, request, session)

    assert user.is_active is False


@pytest.mark.asyncio
async def test_patch_user_reactivates():
    user = _user(is_active=False)
    session = _session()
    session.execute = AsyncMock(return_value=_OneResult(user))
    request = _Request(
        body={"Operations": [{"op": "replace", "path": "active", "value": True}]}
    )

    await scim_routes.patch_user(user.id, request, session)

    assert user.is_active is True


@pytest.mark.asyncio
async def test_patch_user_updates_name_components():
    user = _user()
    session = _session()
    session.execute = AsyncMock(return_value=_OneResult(user))
    request = _Request(
        body={
            "Operations": [
                {"op": "replace", "path": "name.givenName", "value": "Augusta"},
                {"op": "replace", "path": "name.familyName", "value": "King"},
            ]
        }
    )

    payload = await scim_routes.patch_user(user.id, request, session)

    assert payload["name"] == {"givenName": "Augusta", "familyName": "King"}


@pytest.mark.asyncio
async def test_patch_user_ignores_unknown_paths():
    user = _user()
    session = _session()
    session.execute = AsyncMock(return_value=_OneResult(user))
    request = _Request(
        body={"Operations": [{"op": "replace", "path": "title", "value": "CTO"}]}
    )

    await scim_routes.patch_user(user.id, request, session)

    assert user.title == ""
    session.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_patch_user_without_operations_still_commits():
    user = _user()
    session = _session()
    session.execute = AsyncMock(return_value=_OneResult(user))

    await scim_routes.patch_user(user.id, _Request(body={}), session)

    assert user.is_active is True
    session.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_patch_user_unknown_id_is_404():
    session = _session()
    session.execute = AsyncMock(return_value=_OneResult(None))

    with pytest.raises(Exception) as exc:
        await scim_routes.patch_user(uuid.uuid4(), _Request(body={}), session)

    assert exc.value.status_code == 404
    session.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_patch_user_null_active_value_is_rejected():
    """``{"path": "active", "value": null}`` must not become a 500.

    ``scim.py:215`` calls ``value.get("active", True)`` for any non-bool value,
    which raised ``AttributeError`` on ``None`` (and on a string) before the
    guard was added.
    """
    user = _user()
    session = _session()
    session.execute = AsyncMock(return_value=_OneResult(user))
    request = _Request(
        body={"Operations": [{"op": "replace", "path": "active", "value": None}]}
    )

    with pytest.raises(Exception) as exc:
        await scim_routes.patch_user(user.id, request, session)

    assert exc.value.status_code == 400
    session.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_patch_user_string_active_value_is_rejected():
    user = _user()
    session = _session()
    session.execute = AsyncMock(return_value=_OneResult(user))
    request = _Request(
        body={"Operations": [{"op": "replace", "path": "active", "value": "False"}]}
    )

    with pytest.raises(Exception) as exc:
        await scim_routes.patch_user(user.id, request, session)

    assert exc.value.status_code == 400


@pytest.mark.asyncio
async def test_patch_user_operations_not_a_list_is_rejected():
    user = _user()
    session = _session()
    session.execute = AsyncMock(return_value=_OneResult(user))

    with pytest.raises(Exception) as exc:
        await scim_routes.patch_user(
            user.id, _Request(body={"Operations": {"op": "replace"}}), session
        )

    assert exc.value.status_code == 400
    session.commit.assert_not_awaited()


# --------------------------------------------------------------------------
# DELETE /scim/v2/Users/{id}
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_delete_user_soft_deletes():
    user = _user()
    session = _session()
    session.execute = AsyncMock(return_value=_OneResult(user))

    result = await scim_routes.delete_user(user.id, _Request(), session)

    assert result is None
    assert user.is_active is False
    session.delete.assert_not_called()
    session.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_delete_user_unknown_id_is_404():
    session = _session()
    session.execute = AsyncMock(return_value=_OneResult(None))

    with pytest.raises(Exception) as exc:
        await scim_routes.delete_user(uuid.uuid4(), _Request(), session)

    assert exc.value.status_code == 404
    session.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_delete_user_crosses_tenants():
    """Deprovisioning is not tenant-scoped either (``scim.py:235``)."""
    foreign = _user(company_id=OTHER_COMPANY_ID)
    session = _session()
    session.execute = AsyncMock(return_value=_OneResult(foreign))

    await scim_routes.delete_user(foreign.id, _Request(), session)

    assert foreign.is_active is False


# --------------------------------------------------------------------------
# Middleware interaction
# --------------------------------------------------------------------------


def test_scim_paths_are_not_public_to_the_auth_middleware():
    from nexus.auth.middleware import is_public_path

    assert is_public_path("/scim/v2/Users") is False
    assert is_public_path("/scim/v2/Users/" + str(uuid.uuid4())) is False


def test_scim_survives_auth_disabled_only_because_of_its_own_token():
    """With ``AUTH_ENABLED=false`` the middleware waves the request through.

    ``rejection_for`` returns ``None`` for an unauthenticated caller in legacy
    mode, so the bearer check inside ``scim.py`` is the only thing standing
    between the internet and user provisioning.
    """
    from nexus.auth.middleware import rejection_for
    from nexus.config import settings

    original = settings.auth_enabled
    settings.auth_enabled = False
    try:
        assert rejection_for("/scim/v2/Users", None) is None
    finally:
        settings.auth_enabled = original
