from __future__ import annotations

import json
from typing import Any


DEFAULT_CHAT_DIRECT_CAPABILITIES = {
    "github.repo.list",
    "github.user.me",
    "github.issue.search",
    "github.user.search",
    "github.branch.list",
    "filesystem.artifacts.list",
    "filesystem.artifacts.read_text",
    "filesystem.artifacts.search_text",
    "filesystem.workspace.list",
    "filesystem.workspace.read_text",
    "memory.read",
    "memory.semantic.search",
    "rag.retrieve",
}


# ChatDirectExecutionConfig, ChatDirectExecutionResult, ChatDirectExecutor,
# execute_capability, and build_chat_direct_executor removed with the tools
# framework: they invoked capabilities via mcp_gateway/tool_registry/tool_governance,
# none of which exist anymore.


def _tool_name_for_capability(spec: Any) -> str:
    if not spec.adapters:
        return spec.capability_id
    return spec.adapters[0].tool_name


# Public alias kept for callers outside this module.
tool_name_for_capability = _tool_name_for_capability


# _render_hint removed with the tools framework (only used by
# _format_chat_direct_result's now-removed capability-registry chat_response_hint lookup).


def _format_chat_direct_result(
    capability_id: str,
    output: dict[str, Any],
    *,
    max_preview_chars: int,
) -> str:
    """Format a capability output for display in chat.

    Previously tried a spec-driven chat_response_hint from the capability registry
    first; that registry was removed with the tools framework, so this always
    falls back to a generic JSON dump.
    """
    rendered = json.dumps(output, ensure_ascii=True, indent=2, default=str)
    if len(rendered) > max_preview_chars:
        return rendered[:max_preview_chars] + "\n\n[truncated]"
    return rendered


def format_chat_direct_result(
    capability_id: str,
    output: dict[str, Any],
    *,
    max_preview_chars: int = 1_500,
) -> str:
    return _format_chat_direct_result(
        capability_id,
        output,
        max_preview_chars=max_preview_chars,
    )
