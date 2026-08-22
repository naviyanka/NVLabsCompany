"""Common FastAPI dependencies for the NEXUS API.

Route handlers get their tenant scope from the authenticated principal, not
from a request header. :mod:`nexus.auth.middleware` resolves the principal once
per request and stores it on the ASGI scope; the dependencies here read it back
out, so a handler cannot choose which company it operates on.

``CurrentCompanyId`` keeps its original name and type. Existing routers that
already depend on it now receive a company id that the caller has proven
membership of, without any change to their signatures.
"""

import uuid
from collections.abc import AsyncGenerator
from typing import Annotated, Any

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from nexus.auth.middleware import get_principal_from_scope
from nexus.auth.principal import Principal
from nexus.database import get_session


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Provide an async database session."""
    async for session in get_session():
        yield session


def get_optional_principal(request: Request) -> Principal | None:
    """The request's principal, or ``None`` for an anonymous request.

    Use this only where anonymous access is a legitimate outcome — the login
    endpoint, the first-run setup probe. Everything else should depend on
    :data:`CurrentPrincipal`.
    """
    return get_principal_from_scope(request.scope)


def get_principal(request: Request) -> Principal:
    """The request's principal, rejecting anonymous callers with 401.

    The ``WWW-Authenticate`` header names Bearer because that is the scheme a
    non-browser client should retry with; browser clients ignore it and follow
    the dashboard's own redirect to the login page.
    """
    principal = get_principal_from_scope(request.scope)
    if principal is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return principal


def get_current_company_id(
    principal: Annotated[Principal, Depends(get_principal)],
) -> uuid.UUID:
    """The company the caller is authenticated for.

    A user principal carries the company of the membership their session is
    bound to; a service principal carries the company its API key was issued
    for. Neither can be overridden per request.
    """
    return principal.company_id


def get_scoped_company_id(
    company_id: uuid.UUID,
    principal: Annotated[Principal, Depends(get_principal)],
) -> uuid.UUID:
    """Validate a ``{company_id}`` path parameter against the caller's tenant.

    A number of routes were written with the company in the URL. That reads
    naturally and the dashboard builds its links that way, but taken at face
    value it lets any authenticated caller substitute another company's UUID and
    read or write that tenant's rows. Declaring the parameter as
    :data:`PathCompanyId` keeps the URL shape and turns the mismatch into a 403.

    403 rather than 404: the caller is authenticated and the company probably
    exists, they simply have no standing in it.
    """
    if company_id != principal.company_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have access to that company",
        )
    return company_id


def require_permission(
    action: str,
    resource_type: str,
    resource_id: str = "*",
) -> Any:
    """Build a dependency that admits only principals holding a permission.

    Applied per route rather than globally: most endpoints are readable by any
    member of the company, and blanket enforcement would have to guess an action
    for every one of them. Sensitive routes name their requirement explicitly::

        @router.post("/secrets", dependencies=[require_permission("write", "secret")])

    Returns a ``Depends`` object so it can be dropped straight into a router's
    or route's ``dependencies=[...]`` list.
    """

    def dependency(principal: Annotated[Principal, Depends(get_principal)]) -> Principal:
        if not principal.has_permission(action, resource_type, resource_id):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=(
                    f"Role '{principal.role}' may not {action} {resource_type}"
                ),
            )
        return principal

    return Depends(dependency)


def require_admin(
    principal: Annotated[Principal, Depends(get_principal)],
) -> Principal:
    """Admit only company administrators.

    Used where the action has no useful resource-level permission because it
    changes who may act at all — issuing invites, minting API keys, revoking
    another user's sessions.
    """
    if principal.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Administrator role required",
        )
    return principal


def require_user(
    principal: Annotated[Principal, Depends(get_principal)],
) -> Principal:
    """Admit only human callers.

    Some endpoints are meaningless for a service principal: an API key has no
    password to change, no session list, and no other company to switch to.
    """
    if principal.kind != "user":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This endpoint requires a user session, not an API key",
        )
    return principal


# Type aliases for use in route signatures
DbSession = Annotated[AsyncSession, Depends(get_db)]
CurrentPrincipal = Annotated[Principal, Depends(get_principal)]
OptionalPrincipal = Annotated[Principal | None, Depends(get_optional_principal)]
CurrentCompanyId = Annotated[uuid.UUID, Depends(get_current_company_id)]
PathCompanyId = Annotated[uuid.UUID, Depends(get_scoped_company_id)]
RequireAdmin = Annotated[Principal, Depends(require_admin)]
RequireUser = Annotated[Principal, Depends(require_user)]
