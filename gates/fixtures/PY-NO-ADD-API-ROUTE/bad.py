"""Selftest fixture."""

from fastapi import APIRouter

router = APIRouter()


def health() -> dict[str, str]:
    """Answer."""
    return {"status": "ok"}


router.add_api_route("/health", health)
