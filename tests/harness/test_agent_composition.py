"""Characterization tests for the `_agent()` composition root.

This wraps agent_tools.agent() with the invoke_capability callback that
routes recursive `agent`/`agent__run` tool calls to sub_agent_dispatch
(cross-process, when API_URL is set) or back into `_agent()` itself
(in-process fallback, when it isn't) -- and routes every other tool call
through a freshly-built ToolRegistry. None of this branching had direct
test coverage before this file.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

from libs.core import tool_registry as core_tool_registry
from libs.harness import agent as harness_agent


def test_agent_wrapper_passes_recursion_depth_and_invoke_capability(monkeypatch) -> None:
    captured: dict[str, Any] = {}

    def _fake_agent(payload, provider, *, invoke_capability, _recursion_depth=0):
        captured["payload"] = payload
        captured["provider"] = provider
        captured["invoke_capability"] = invoke_capability
        captured["_recursion_depth"] = _recursion_depth
        return {"result": "ok"}

    monkeypatch.setattr(harness_agent.agent_tools, "agent", _fake_agent)

    provider = MagicMock()
    result = harness_agent._agent({"goal": "test"}, provider, _recursion_depth=2)

    assert result == {"result": "ok"}
    assert captured["payload"] == {"goal": "test"}
    assert captured["provider"] is provider
    assert captured["_recursion_depth"] == 2
    assert callable(captured["invoke_capability"])


def test_execute_tool_dispatches_recursive_agent_call_when_api_url_set(monkeypatch) -> None:
    def _fake_agent(payload, provider, *, invoke_capability, _recursion_depth=0):
        return invoke_capability("agent.run", {"goal": "nested"})

    monkeypatch.setattr(harness_agent.agent_tools, "agent", _fake_agent)
    monkeypatch.setattr(
        harness_agent.mcp_gateway,
        "invoke_capability",
        lambda cap_id, args, execute_tool: execute_tool("agent", args),
    )
    monkeypatch.setattr(harness_agent.sub_agent_dispatch, "get_api_url", lambda: "http://api:8000")
    dispatch_calls: list[tuple[dict[str, Any], str]] = []
    monkeypatch.setattr(
        harness_agent.sub_agent_dispatch,
        "dispatch_sub_agent",
        lambda arguments, api_url: (
            dispatch_calls.append((arguments, api_url)) or {"result": "dispatched"}
        ),
    )

    provider = MagicMock()
    result = harness_agent._agent({"goal": "test"}, provider)

    assert result == {"result": "dispatched"}
    assert dispatch_calls == [({"goal": "nested"}, "http://api:8000")]


def test_execute_tool_falls_back_to_in_process_recursion_when_no_api_url(monkeypatch) -> None:
    depths_seen: list[int] = []

    def _fake_agent(payload, provider, *, invoke_capability, _recursion_depth=0):
        depths_seen.append(_recursion_depth)
        if _recursion_depth == 0:
            return invoke_capability("agent.run", {"goal": "nested"})
        return {"result": "recursed", "depth": _recursion_depth}

    monkeypatch.setattr(harness_agent.agent_tools, "agent", _fake_agent)
    monkeypatch.setattr(
        harness_agent.mcp_gateway,
        "invoke_capability",
        lambda cap_id, args, execute_tool: execute_tool("agent", args),
    )
    monkeypatch.setattr(harness_agent.sub_agent_dispatch, "get_api_url", lambda: "")

    provider = MagicMock()
    result = harness_agent._agent({"goal": "test"}, provider)

    assert result == {"result": "recursed", "depth": 1}
    assert depths_seen == [0, 1]


def test_execute_tool_looks_up_registry_for_non_agent_tool(monkeypatch) -> None:
    def _fake_agent(payload, provider, *, invoke_capability, _recursion_depth=0):
        return invoke_capability("some_capability", {"x": 1})

    handler_calls: list[dict[str, Any]] = []

    class _FakeTool:
        def handler(self, arguments):
            handler_calls.append(arguments)
            return {"ok": True}

    class _FakeRegistry:
        def get(self, name):
            assert name == "some_tool"
            return _FakeTool()

    monkeypatch.setattr(harness_agent.agent_tools, "agent", _fake_agent)
    monkeypatch.setattr(
        harness_agent.mcp_gateway,
        "invoke_capability",
        lambda cap_id, args, execute_tool: execute_tool("some_tool", args),
    )
    # _agent()'s _execute_tool closure locally imports `libs.core.tool_registry`
    # (to avoid a module-level harness <-> tool_registry cycle), so the patch
    # target is the real tool_registry module, not anything on harness_agent.
    monkeypatch.setattr(core_tool_registry, "build_default_registry", lambda **kwargs: _FakeRegistry())

    provider = MagicMock()
    result = harness_agent._agent({"goal": "test"}, provider)

    assert result == {"ok": True}
    assert handler_calls == [{"x": 1}]
