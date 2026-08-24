"""Unit tests for agent.run's per-call provider/model override."""

from __future__ import annotations

from libs.core.llm_provider import LLMRequest, LLMResponse
from libs.harness import agent_tools


class _StubProvider:
    """Minimal LLMProvider stub (no .client -> uses the text-ReAct path)."""

    def __init__(self, content: str) -> None:
        self._content = content
        self.calls = 0

    def generate_request(self, request: LLMRequest) -> LLMResponse:  # noqa: ARG002
        self.calls += 1
        return LLMResponse(content=self._content)


def test_agent_run_uses_default_provider_when_no_override_given() -> None:
    default_provider = _StubProvider('{"final_answer": "ok"}')

    agent_tools.agent(
        {"goal": "x"},
        default_provider,
        invoke_capability=lambda cap_id, args: {},
    )

    assert default_provider.calls == 1


def test_agent_run_uses_override_provider_when_provider_set(monkeypatch) -> None:
    default_provider = _StubProvider('{"final_answer": "should not be used"}')
    override_provider = _StubProvider('{"final_answer": "overridden"}')

    captured: dict[str, object] = {}

    def _fake_resolve_provider_cached(provider_name, model=None):
        captured["provider_name"] = provider_name
        captured["model"] = model
        return override_provider

    monkeypatch.setattr(agent_tools, "resolve_provider_cached", _fake_resolve_provider_cached)

    agent_tools.agent(
        {"goal": "x", "provider": "anthropic", "model": "claude-sonnet-4-6"},
        default_provider,
        invoke_capability=lambda cap_id, args: {},
    )

    assert captured == {"provider_name": "anthropic", "model": "claude-sonnet-4-6"}
    assert override_provider.calls == 1
    assert default_provider.calls == 0


def test_agent_run_ignores_bare_model_override_without_provider(monkeypatch) -> None:
    default_provider = _StubProvider('{"final_answer": "ok"}')

    def _unexpected_resolve(*args, **kwargs):
        raise AssertionError(
            "resolve_provider_cached should not be called without a provider override"
        )

    monkeypatch.setattr(agent_tools, "resolve_provider_cached", _unexpected_resolve)

    agent_tools.agent(
        {"goal": "x", "model": "gpt-4o"},
        default_provider,
        invoke_capability=lambda cap_id, args: {},
    )

    assert default_provider.calls == 1
