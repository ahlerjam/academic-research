"""Wire the application exactly once."""

from fastapi import FastAPI

from app.health.api import router as health_router


def create_app() -> FastAPI:
    """Build the application with every feature router."""
    application = FastAPI(title="academic-research")
    application.include_router(health_router)
    return application


app = create_app()
