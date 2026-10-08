"""Receive health requests."""

from fastapi import APIRouter

from app.health.flow import run_health

router = APIRouter()


@router.get("/health", operation_id="health")
def health() -> dict[str, str]:
    """Return the decided health status."""
    return {"status": run_health().status}
