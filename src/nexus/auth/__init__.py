"""Authentication and authorization.

The pieces fit together in one direction: the middleware turns whatever
credentials a request carries into a :class:`Principal`, the route dependencies
in :mod:`nexus.api.deps` read that principal and decide whether to serve the
request, and everything downstream — governance, tenant scoping, RBAC — keys off
it instead of off a client-supplied header.

Modules:

``principal``
    The resolved identity for one request: which company, which role, and
    whether it is a human or a service key.
``middleware``
    Pure-ASGI middleware that resolves credentials before governance runs, and
    enforces CSRF and WebSocket origin checks.
``sessions``
    Server-side session store behind the login cookie. Tokens are stored hashed.
``api_keys``
    Bearer-key authentication for service callers.
``passwords``
    Hashing and strength validation, over the fastapi-users password helper.
``users``
    User lookup and company-membership resolution.
``csrf``
    Double-submit token helpers.
``bootstrap``
    Command-line creation of the first administrator.
"""

from nexus.auth.principal import Principal, PrincipalKind

__all__ = ["Principal", "PrincipalKind"]
