"""Composition root for the agent harness.

Wires agent_tools.agent() (the ReAct-style execution loop) together with
MCP dispatch (libs.mcp.mcp_gateway) and sub-agent process isolation
(libs.harness.sub_agent_dispatch), and exposes the result as the "agent"
tool handler registered by libs.core.tool_registry.
"""

from __future__ import annotations

from typing import Any, Dict

from libs.core.llm_provider import LLMProvider
from libs.harness import agent_tools, sub_agent_dispatch
from libs.mcp import mcp_gateway


def _agent(
    payload: Dict[str, Any], provider: LLMProvider, _recursion_depth: int = 0
) -> Dict[str, Any]:
    # Built once per _agent() invocation (i.e. once per agent run, not once
    # per tool call) and reused by every _execute_tool call below -- this
    # loop can make dozens of tool calls, and re-registering every tool,
    # reloading plugins, and re-running governance filtering on each one was
    # pure waste. Lazily constructed on first non-"agent" tool call so a run
    # that only ever recurses into nested agents never pays for it.
    _registry = None

    def _execute_tool(tool_name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        nonlocal _registry
        # Intercept recursive agent calls: dispatch as an independent job when
        # API_URL is available (true process isolation); fall back to in-process
        # recursion in dev/test environments where API_URL is not set.
        if tool_name == "agent" or tool_name == "agent__run":
            api_url = sub_agent_dispatch.get_api_url()
            if api_url:
                return sub_agent_dispatch.dispatch_sub_agent(arguments, api_url=api_url)
            return _agent(arguments, provider, _recursion_depth=_recursion_depth + 1)

        if _registry is None:
            # Local import: libs.core.tool_registry imports this module to wire
            # _agent() in as the "agent" tool handler, so a module-level import
            # here would be circular.
            from libs.core import tool_registry

            _registry = tool_registry.build_default_registry(
                http_fetch_enabled=True,
                llm_enabled=True,
                llm_provider=provider,
            )
        tool = _registry.get(tool_name)
        if tool is None:
            from libs.framework.tool_runtime import ToolExecutionError as _TEE

            raise _TEE(f"tool_not_found:{tool_name}")
        return tool.handler(arguments)

    return agent_tools.agent(
        payload,
        provider,
        invoke_capability=lambda cap_id, args: mcp_gateway.invoke_capability(
            cap_id,
            args,
            execute_tool=_execute_tool,
        ),
        _recursion_depth=_recursion_depth,
    )
