from __future__ import annotations

import pytest

from libs.framework.tool_runtime import ToolExecutionError
from libs.harness import sub_agent_dispatch


def test_get_api_url_reads_env(monkeypatch) -> None:
    monkeypatch.setenv("API_URL", "http://api:8000/")
    assert sub_agent_dispatch.get_api_url() == "http://api:8000"


def test_get_api_url_defaults_empty(monkeypatch) -> None:
    monkeypatch.delenv("API_URL", raising=False)
    assert sub_agent_dispatch.get_api_url() == ""


def test_dispatch_sub_agent_raises_without_api_url(monkeypatch) -> None:
    monkeypatch.delenv("API_URL", raising=False)
    with pytest.raises(ToolExecutionError, match="API_URL not configured"):
        sub_agent_dispatch.dispatch_sub_agent({"goal": "x"})


def test_dispatch_sub_agent_background_returns_immediately(monkeypatch) -> None:
    class _FakeResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return {"run_id": "run-1", "job_id": "job-1"}

    monkeypatch.setattr("httpx.post", lambda *a, **k: _FakeResponse())

    result = sub_agent_dispatch.dispatch_sub_agent(
        {"goal": "x"}, api_url="http://api:8000", background=True
    )
    assert result["run_id"] == "run-1"
    assert result["background"] is True
    assert result["status"] == "running"


def test_dispatch_sub_agent_polls_until_completion(monkeypatch) -> None:
    class _FakePostResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return {"run_id": "run-2"}

    calls = {"n": 0}

    class _Resp:
        def __init__(self, payload):
            self._payload = payload

        def json(self):
            return self._payload

    def _fake_get(url, timeout=10.0):
        if url.endswith("/runs/run-2"):
            calls["n"] += 1
            if calls["n"] < 2:
                return _Resp({"status": "running"})
            return _Resp({"status": "completed"})
        if url.endswith("/steps"):
            return _Resp(
                [
                    {
                        "outputs": {
                            "agent": {
                                "result": "done",
                                "steps_taken": 1,
                                "tool_calls": [],
                                "agents": [],
                            }
                        }
                    }
                ]
            )
        raise AssertionError(f"unexpected url {url}")

    monkeypatch.setattr("httpx.post", lambda *a, **k: _FakePostResponse())
    monkeypatch.setattr("httpx.get", _fake_get)
    monkeypatch.setattr(sub_agent_dispatch, "_POLL_INTERVAL_START_S", 0.01)

    result = sub_agent_dispatch.dispatch_sub_agent({"goal": "x"}, api_url="http://api:8000")
    assert result["result"] == "done"


def test_dispatch_sub_agent_raises_on_job_failure(monkeypatch) -> None:
    class _FakePostResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return {"run_id": "run-3"}

    class _Resp:
        def json(self):
            return {"status": "failed", "job_error": "boom"}

    monkeypatch.setattr("httpx.post", lambda *a, **k: _FakePostResponse())
    monkeypatch.setattr("httpx.get", lambda url, timeout=10.0: _Resp())

    with pytest.raises(ToolExecutionError, match="boom"):
        sub_agent_dispatch.dispatch_sub_agent({"goal": "x"}, api_url="http://api:8000")
