"""Dispatch sub-agent calls as independent jobs via the API service.

Replaces in-process recursive agent execution with a proper job that runs in
its own worker process. The parent worker blocks on a poll until the child job
completes; if the child crashes, the parent gets ToolExecutionError — its own
call stack is unaffected.

Set API_URL=http://api:8000 in the worker service environment to enable.
When API_URL is not set, callers fall back to in-process execution (dev/test).
"""
from __future__ import annotations

import logging
import os
import time
from typing import Any

LOGGER = logging.getLogger(__name__)

_POLL_INTERVAL_START_S = 0.5
_POLL_INTERVAL_MAX_S = 5.0
_DEFAULT_TIMEOUT_S = 300.0

_TERMINAL_STATUSES = frozenset({"completed", "done", "failed", "error", "cancelled"})
_SUCCESS_STATUSES = frozenset({"completed", "done"})


def get_api_url() -> str:
    return os.getenv("API_URL", "").rstrip("/")


def dispatch_sub_agent(
    payload: dict[str, Any],
    *,
    api_url: str | None = None,
    timeout_s: float = _DEFAULT_TIMEOUT_S,
    background: bool = False,
) -> dict[str, Any]:
    """Create a sub-agent job via the API and optionally wait for completion.

    Args:
        payload: agent tool payload (goal, allowed_capability_ids, etc.)
        api_url: override; defaults to API_URL env var
        timeout_s: how long to poll before raising ToolExecutionError
        background: if True, return immediately with run_id without polling
    """
    import httpx

    from libs.framework.tool_runtime import ToolExecutionError

    resolved = (api_url or get_api_url()).rstrip("/")
    if not resolved:
        raise ToolExecutionError("API_URL not configured; cannot dispatch sub-agent job")

    try:
        resp = httpx.post(
            f"{resolved}/internal/sub-agent",
            json=payload,
            timeout=30.0,
        )
        resp.raise_for_status()
    except Exception as exc:
        raise ToolExecutionError(f"sub-agent dispatch failed: {exc}") from exc

    data = resp.json()
    run_id: str = data["run_id"]

    if background:
        return {
            "result": "",
            "steps_taken": 0,
            "tool_calls": [],
            "agents": [],
            "run_id": run_id,
            "background": True,
            "status": "running",
        }

    return _wait_for_completion(run_id, resolved, timeout_s)


def _wait_for_completion(
    run_id: str,
    api_url: str,
    timeout_s: float,
) -> dict[str, Any]:
    import httpx

    from libs.framework.tool_runtime import ToolExecutionError

    deadline = time.monotonic() + timeout_s
    interval = _POLL_INTERVAL_START_S

    while time.monotonic() < deadline:
        try:
            run = httpx.get(f"{api_url}/runs/{run_id}", timeout=10.0).json()
        except Exception as exc:
            LOGGER.warning("sub-agent poll error run_id=%s: %s", run_id, exc)
            _sleep(interval, deadline)
            interval = min(interval * 1.5, _POLL_INTERVAL_MAX_S)
            continue

        status = str(run.get("status") or "")
        if status in _SUCCESS_STATUSES:
            return _extract_output(run_id, api_url)
        if status in _TERMINAL_STATUSES:
            error = run.get("job_error") or run.get("latest_step_error") or status
            raise ToolExecutionError(f"sub-agent job failed: {error} (run_id={run_id})")

        _sleep(interval, deadline)
        interval = min(interval * 1.5, _POLL_INTERVAL_MAX_S)

    raise ToolExecutionError(
        f"sub-agent job timed out after {timeout_s}s (run_id={run_id})"
    )


def _extract_output(run_id: str, api_url: str) -> dict[str, Any]:
    """Pull the agent tool output from the completed run's task outputs."""
    import httpx

    try:
        steps = httpx.get(f"{api_url}/runs/{run_id}/steps", timeout=10.0).json()
        if isinstance(steps, list):
            for step in steps:
                outputs = step.get("outputs") or {}
                if "agent" in outputs:
                    return outputs["agent"]
    except Exception as exc:
        LOGGER.warning("sub-agent output extraction failed run_id=%s: %s", run_id, exc)

    return {"result": "completed", "steps_taken": 0, "tool_calls": [], "agents": []}


def _sleep(interval: float, deadline: float) -> None:
    remaining = deadline - time.monotonic()
    if remaining > 0:
        time.sleep(min(interval, remaining))
