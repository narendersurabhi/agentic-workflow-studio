"""Unit tests confirming agent.run's tool descriptors surface CapabilitySpec.agent_hint."""

from __future__ import annotations

from libs.core.llm_provider import LLMRequest, LLMResponse
from libs.harness import agent_tools


class _CapturingProvider:
    """Minimal LLMProvider stub (no .client -> uses the text-ReAct path)."""

    def __init__(self, content: str) -> None:
        self._content = content
        self.requests: list[LLMRequest] = []

    def generate_request(self, request: LLMRequest) -> LLMResponse:
        self.requests.append(request)
        return LLMResponse(content=self._content)


def test_agent_tool_descriptor_appends_agent_hint_when_present() -> None:
    provider = _CapturingProvider('{"final_answer": "ok"}')

    agent_tools.agent(
        {"goal": "x", "allowed_capability_ids": ["memory.write"]},
        provider,
        invoke_capability=lambda cap_id, args: {},
    )

    assert len(provider.requests) == 1
    system_prompt = provider.requests[0].system_prompt

    from libs.core import capability_registry as cap_registry

    spec = cap_registry.load_capability_registry().require("memory.write")
    assert spec.agent_hint
    assert spec.description in system_prompt
    assert spec.agent_hint in system_prompt


def test_agent_tool_descriptor_falls_back_to_description_when_no_agent_hint(monkeypatch) -> None:
    from libs.core import capability_registry as cap_registry

    real_registry = cap_registry.load_capability_registry()
    real_spec = real_registry.require("memory.write")

    stripped_spec = cap_registry.CapabilitySpec(
        **{**vars(real_spec), "agent_hint": None},
    )

    class _StubRegistry:
        def require(self, cap_id: str):
            assert cap_id == "memory.write"
            return stripped_spec

    monkeypatch.setattr(cap_registry, "load_capability_registry", lambda: _StubRegistry())

    provider = _CapturingProvider('{"final_answer": "ok"}')

    agent_tools.agent(
        {"goal": "x", "allowed_capability_ids": ["memory.write"]},
        provider,
        invoke_capability=lambda cap_id, args: {},
    )

    system_prompt = provider.requests[0].system_prompt
    assert stripped_spec.description in system_prompt
    assert f"  - memory__write: {stripped_spec.description}" in system_prompt
