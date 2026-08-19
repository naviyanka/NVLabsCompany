"""API Versioning Strategy - provides versioned routing and deprecation support.

Implements a VersionedRouter that mounts routes under a version prefix,
adds an X-API-Version response header, and supports marking routes as
deprecated with a Sunset header indicating the removal date.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from fastapi import APIRouter, Request, Response
from starlette.middleware.base import (
    BaseHTTPMiddleware,
    RequestResponseEndpoint,
)
from starlette.types import ASGIApp


class APIVersionMiddleware(BaseHTTPMiddleware):
    """Middleware that adds X-API-Version header to all responses.

    Injects the current API version into every HTTP response to allow
    clients to verify which version they are communicating with.
    """

    def __init__(self, app: ASGIApp, version: str = "1.0") -> None:
        """Initialize the version middleware.

        Args:
            app: The ASGI application.
            version: API version string to include in responses.
        """
        super().__init__(app)
        self.version = version

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        """Process the request and add version header to response.

        Args:
            request: The incoming HTTP request.
            call_next: The next middleware/handler in the chain.

        Returns:
            Response with X-API-Version header added.
        """
        response = await call_next(request)
        response.headers["X-API-Version"] = self.version
        return response


class VersionedRouter(APIRouter):
    """APIRouter subclass with built-in version prefix and deprecation support.

    Routes registered on this router are automatically prefixed with
    /api/v{version}. Deprecated routes include Sunset and Deprecation
    headers in their responses.

    Example:
        router = VersionedRouter(version=1)
        router.get("/items")(list_items)  # accessible at /api/v1/items

        # Mark a route as deprecated
        router.add_api_route(
            "/old-items",
            list_items,
            methods=["GET"],
            deprecated=True,
            sunset_date=date(2025, 6, 1),
        )
    """

    def __init__(
        self,
        version: int = 1,
        **kwargs: Any,
    ) -> None:
        """Initialize the versioned router.

        Args:
            version: API version number (used in prefix /api/v{version}).
            **kwargs: Additional keyword arguments passed to APIRouter.
        """
        self.api_version = version
        prefix = kwargs.pop("prefix", "") or f"/api/v{version}"
        super().__init__(prefix=prefix, **kwargs)
        self._deprecated_routes: dict[str, date] = {}

    def add_deprecated_route(
        self,
        path: str,
        endpoint: Any,
        sunset_date: date,
        methods: list[str] | None = None,
        **kwargs: Any,
    ) -> None:
        """Add a deprecated route with sunset date.

        The route will include Sunset and Deprecation headers in responses
        to inform clients of the planned removal date.

        Args:
            path: The route path.
            endpoint: The route handler function.
            sunset_date: Date after which the route will be removed.
            methods: HTTP methods for this route.
            **kwargs: Additional keyword arguments for add_api_route.
        """
        full_path = path
        self._deprecated_routes[full_path] = sunset_date

        # Wrap the endpoint to add deprecation headers
        original_endpoint = endpoint

        async def deprecated_wrapper(request: Request) -> Response:
            """Wrapper that adds deprecation headers to the response."""
            result = await original_endpoint(request)
            if isinstance(result, Response):
                result.headers["Sunset"] = sunset_date.isoformat()
                result.headers["Deprecation"] = "true"
                return result
            # For non-Response returns, create a JSON response
            from fastapi.responses import JSONResponse
            response = JSONResponse(content=result)
            response.headers["Sunset"] = sunset_date.isoformat()
            response.headers["Deprecation"] = "true"
            return response

        self.add_api_route(
            path,
            deprecated_wrapper,
            methods=methods or ["GET"],
            deprecated=True,
            **kwargs,
        )

    def get_deprecated_routes(self) -> dict[str, date]:
        """Return all deprecated routes and their sunset dates.

        Returns:
            Dictionary mapping route paths to their sunset dates.
        """
        return dict(self._deprecated_routes)
