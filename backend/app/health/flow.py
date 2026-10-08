"""Sequence the health check: load the facts, decide, log the outcome."""

import json
import logging

from app.health.core import Facts, Status, decide_status

log = logging.getLogger(__name__)


def load_facts() -> Facts:
    """Collect the facts the decision needs."""
    return Facts(dependencies_reachable=True)


def run_health() -> Status:
    """Load the facts, decide and log the outcome as one JSON event."""
    status = decide_status(load_facts())
    log.info(json.dumps({"event": "health", "status": status.status}))
    return status
