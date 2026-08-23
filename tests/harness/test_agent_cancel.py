from __future__ import annotations

from libs.harness import agent_cancel


class _FakeRedis:
    def __init__(self) -> None:
        self.store: dict[str, str] = {}

    def set(self, key: str, value: str, ex: int | None = None) -> None:
        self.store[key] = value

    def exists(self, key: str) -> int:
        return 1 if key in self.store else 0

    def delete(self, key: str) -> None:
        self.store.pop(key, None)


def test_set_and_get_current_run_id() -> None:
    agent_cancel.set_current_run_id("run-123")
    assert agent_cancel.get_current_run_id() == "run-123"
    agent_cancel.set_current_run_id("")


def test_get_current_run_id_defaults_empty() -> None:
    agent_cancel.set_current_run_id("")
    assert agent_cancel.get_current_run_id() == ""


def test_signal_cancel_writes_flag_and_is_cancelled_reads_it(monkeypatch) -> None:
    fake = _FakeRedis()
    monkeypatch.setattr(agent_cancel, "_redis_client", lambda: fake)
    assert agent_cancel.is_cancelled("run-abc") is False
    agent_cancel.signal_cancel("run-abc")
    assert agent_cancel.is_cancelled("run-abc") is True
    assert fake.store["cancel:run:run-abc"] == "1"


def test_clear_cancel_removes_flag(monkeypatch) -> None:
    fake = _FakeRedis()
    monkeypatch.setattr(agent_cancel, "_redis_client", lambda: fake)
    agent_cancel.signal_cancel("run-xyz")
    assert agent_cancel.is_cancelled("run-xyz") is True
    agent_cancel.clear_cancel("run-xyz")
    assert agent_cancel.is_cancelled("run-xyz") is False


def test_is_cancelled_empty_run_id_returns_false(monkeypatch) -> None:
    monkeypatch.setattr(agent_cancel, "_redis_client", lambda: _FakeRedis())
    assert agent_cancel.is_cancelled("") is False


def test_gracefully_degrades_when_redis_unavailable(monkeypatch) -> None:
    monkeypatch.setattr(agent_cancel, "_redis_client", lambda: None)
    agent_cancel.signal_cancel("run-1")
    assert agent_cancel.is_cancelled("run-1") is False
    agent_cancel.clear_cancel("run-1")
