from __future__ import annotations

import logging
import os
from contextvars import ContextVar
from typing import Any

LOGGER = logging.getLogger(__name__)

_CANCEL_KEY_PREFIX = "cancel:run:"
_CANCEL_TTL_S = 3600

# Set by the worker before invoking a capability so the agent loop can read it.
_CURRENT_RUN_ID: ContextVar[str] = ContextVar("agent_current_run_id", default="")


def set_current_run_id(run_id: str) -> None:
    _CURRENT_RUN_ID.set(run_id)


def get_current_run_id() -> str:
    return _CURRENT_RUN_ID.get()


def _redis_client() -> Any | None:
    try:
        import redis

        url = os.getenv("REDIS_URL", "redis://redis:6379/0")
        return redis.Redis.from_url(url, decode_responses=True)
    except Exception:
        return None


def signal_cancel(run_id: str) -> None:
    """Write the cancellation flag to Redis. Called by the API cancel endpoint."""
    client = _redis_client()
    if client is None:
        return
    try:
        client.set(f"{_CANCEL_KEY_PREFIX}{run_id}", "1", ex=_CANCEL_TTL_S)
    except Exception as exc:
        LOGGER.warning("agent_cancel: failed to set cancel flag for %s: %s", run_id, exc)


def is_cancelled(run_id: str) -> bool:
    """Return True if the run has been cancelled. Called by the agent loop between steps."""
    if not run_id:
        return False
    client = _redis_client()
    if client is None:
        return False
    try:
        return client.exists(f"{_CANCEL_KEY_PREFIX}{run_id}") == 1
    except Exception:
        return False


def clear_cancel(run_id: str) -> None:
    """Remove the cancellation flag (e.g. after the job has been cleaned up)."""
    client = _redis_client()
    if client is None:
        return
    try:
        client.delete(f"{_CANCEL_KEY_PREFIX}{run_id}")
    except Exception:
        pass
