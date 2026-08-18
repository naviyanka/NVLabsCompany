"""Health check endpoint."""

from fastapi import APIRouter

from nexus import __version__

router = APIRouter(tags=["health"])


@router.get("/health")
async def health_check() -> dict[str, str]:
    """Return the current health status and version of the NEXUS server."""
    return {
        "status": "ok",
        "version": __version__,
        "service": "nexus",
    }
