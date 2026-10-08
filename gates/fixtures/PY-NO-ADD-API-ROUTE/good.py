"""Selftest fixture."""

from fastapi import APIRouter

router = APIRouter()


@router.get("/health", operation_id="health")
def health() -> dict[str, str]:
    """Answer."""
    return {"status": "ok"}
