"""Common FastAPI dependencies for the NEXUS API."""

import uuid
from collections.abc import AsyncGenerator
from typing import Annotated

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from nexus.database import get_session


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Provide an async database session."""
    async for session in get_session():
        yield session


async def get_current_company_id(
    x_company_id: Annotated[str | None, Header()] = None,
) -> uuid.UUID:
    """Extract and validate the current company ID from request headers.

    In production, this would come from an authenticated JWT token.
    For development, it accepts the X-Company-Id header directly.
    """
    if not x_company_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="X-Company-Id header is required",
        )
    try:
        return uuid.UUID(x_company_id)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="X-Company-Id must be a valid UUID",
        )


# Type aliases for use in route signatures
DbSession = Annotated[AsyncSession, Depends(get_db)]
CurrentCompanyId = Annotated[uuid.UUID, Depends(get_current_company_id)]
