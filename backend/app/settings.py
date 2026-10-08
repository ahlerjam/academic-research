"""Read the settings from the environment once."""

import os

from pydantic import BaseModel, ConfigDict


class Settings(BaseModel):
    """Runtime settings."""

    model_config = ConfigDict(frozen=True)

    log_level: str


def load_settings() -> Settings:
    """Read the settings from the environment."""
    return Settings(log_level=os.environ.get("LOG_LEVEL", "INFO"))
