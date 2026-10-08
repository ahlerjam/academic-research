"""Selftest fixture."""

from pydantic import BaseModel, ConfigDict


class Price(BaseModel):
    """A price."""

    model_config = ConfigDict(frozen=True)

    amount: int
