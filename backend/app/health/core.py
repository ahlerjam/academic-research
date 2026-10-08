"""Decide the health status from observed facts."""

from pydantic import BaseModel, ConfigDict


class Facts(BaseModel):
    """What the flow observed before deciding."""

    model_config = ConfigDict(frozen=True)

    dependencies_reachable: bool


class Status(BaseModel):
    """The decided health status."""

    model_config = ConfigDict(frozen=True)

    status: str


def decide_status(facts: Facts) -> Status:
    """Return ok when every dependency is reachable, degraded otherwise."""
    return Status(status="ok" if facts.dependencies_reachable else "degraded")
