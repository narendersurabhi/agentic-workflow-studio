from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from typing import Any

from libs.core import capability_registry, tool_registry
from libs.tool_manager import tool_governance
from libs.framework.tool_runtime import ToolExecutionError, ToolRegistry
from libs.mcp import mcp_gateway


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


@dataclass(frozen=True)
class ChatDirectExecutionConfig:
    allowed_capabilities: set[str]
    output_size_cap: int = 50_000
    max_preview_chars: int = 1_500


@dataclass(frozen=True)
class ChatDirectExecutionResult:
    capability_id: str
    tool_name: str
    output: dict[str, Any]
    assistant_response: str


@dataclass(frozen=True)
class ChatDirectExecutor:
    registry: ToolRegistry
    config: ChatDirectExecutionConfig
    service_name: str = "api"

    def execute_capability(
        self,
        *,
        capability_id: str,
        arguments: dict[str, Any],
        trace_id: str,
    ) -> ChatDirectExecutionResult:
        normalized_capability_id = str(capability_id or "").strip()
        if not normalized_capability_id:
            raise ToolExecutionError("chat_direct_missing_capability_id")
        if normalized_capability_id not in self.config.allowed_capabilities:
            raise ToolExecutionError(
                f"chat_direct_capability_not_allowed:{normalized_capability_id}"
            )

        registry = capability_registry.load_capability_registry()
        spec = registry.require(normalized_capability_id)
        if not spec.enabled:
            raise ToolExecutionError(f"chat_direct_capability_disabled:{normalized_capability_id}")
        allow_decision = capability_registry.evaluate_capability_allowlist(
            normalized_capability_id,
            self.service_name,
        )
        if not allow_decision.allowed:
            raise ToolExecutionError(
                f"chat_direct_capability_blocked:{normalized_capability_id}:{allow_decision.reason}"
            )

        def _execute_native_tool(tool_name: str, tool_arguments: dict[str, Any]) -> dict[str, Any]:
            tool = self.registry.get(tool_name)
            tool_decision = tool_governance.evaluate_tool_allowlist(
                tool_name,
                self.service_name,
                context={"chat_direct": True},
                tool_spec=tool.spec,
            )
            if not tool_decision.allowed:
                raise ToolExecutionError(
                    f"chat_direct_tool_blocked:{tool_name}:{tool_decision.reason}"
                )
            payload = dict(tool_arguments)
            payload["_registry"] = self.registry
            call = self.registry.execute(
                tool_name,
                payload=payload,
                idempotency_key=str(uuid.uuid4()),
                trace_id=trace_id,
                max_output_bytes=self.config.output_size_cap,
            )
            if call.status != "completed":
                output = call.output_or_error if isinstance(call.output_or_error, dict) else {}
                raise ToolExecutionError(str(output.get("error", "chat_direct_tool_failed")))
            output = call.output_or_error
            if isinstance(output, dict):
                return output
            return {"result": output}

        result = mcp_gateway.invoke_capability(
            normalized_capability_id,
            dict(arguments),
            capability_registry=registry,
            execute_tool=_execute_native_tool,
        )
        output = result if isinstance(result, dict) else {"result": result}
        return ChatDirectExecutionResult(
            capability_id=normalized_capability_id,
            tool_name=_tool_name_for_capability(spec),
            output=output,
            assistant_response=_format_chat_direct_result(
                normalized_capability_id,
                output,
                max_preview_chars=self.config.max_preview_chars,
            ),
        )


def build_chat_direct_executor(
    *,
    service_name: str = "api",
    allowed_capabilities: set[str] | None = None,
    output_size_cap: int = 50_000,
    llm_enabled: bool = False,
    llm_provider_instance: Any | None = None,
) -> ChatDirectExecutor:
    registry = tool_registry.build_default_registry(
        http_fetch_enabled=False,
        llm_enabled=llm_enabled,
        llm_provider=llm_provider_instance,
        service_name=service_name,
    )
    return ChatDirectExecutor(
        registry=registry,
        service_name=service_name,
        config=ChatDirectExecutionConfig(
            allowed_capabilities=set(allowed_capabilities or DEFAULT_CHAT_DIRECT_CAPABILITIES),
            output_size_cap=output_size_cap,
        ),
    )


def _tool_name_for_capability(spec: capability_registry.CapabilitySpec) -> str:
    if not spec.adapters:
        return spec.capability_id
    return spec.adapters[0].tool_name


# Public alias kept for callers outside this module.
tool_name_for_capability = _tool_name_for_capability


def _render_hint(
    output: dict[str, Any],
    hint: dict[str, Any],
    *,
    max_preview_chars: int,
) -> str | None:
    """Apply a spec-driven chat_response_hint to output. Returns None when hint doesn't match."""
    mode = str(hint.get("mode") or "").strip()

    if mode == "list":
        items = output.get(str(hint.get("items_field") or "items"))
        if not isinstance(items, list):
            return None
        label_fields: list[str] = hint.get("label_fields") or ["name"]
        max_items = int(hint.get("max_items") or 10)
        prefix = str(hint.get("prefix") or "Items:")
        labels = [
            next(
                (
                    str(item.get(f) or "").strip()
                    for f in label_fields
                    if str(item.get(f) or "").strip()
                ),
                "",
            )
            for item in items[:max_items]
            if isinstance(item, dict)
        ]
        labels = [label for label in labels if label]
        if not labels:
            return None
        return prefix + "\n" + "\n".join(f"- {label}" for label in labels)

    if mode == "entries":
        entries = output.get(str(hint.get("entries_field") or "entries"))
        label_fields = hint.get("label_fields") or ["path"]
        max_items = int(hint.get("max_items") or 20)
        prefix = str(hint.get("prefix") or "Entries:")
        empty = str(hint.get("empty_message") or "No entries found.")
        if not isinstance(entries, list):
            return None
        labels = [
            next(
                (str(e.get(f) or "").strip() for f in label_fields if str(e.get(f) or "").strip()),
                "",
            )
            for e in entries[:max_items]
            if isinstance(e, dict)
        ]
        labels = [label for label in labels if label]
        return (prefix + "\n" + "\n".join(f"- {label}" for label in labels)) if labels else empty

    if mode == "text":
        content = output.get(str(hint.get("content_field") or "content"))
        if not isinstance(content, str):
            return None
        preview = content[:max_preview_chars]
        return preview if len(content) <= max_preview_chars else f"{preview}\n\n[truncated]"

    if mode == "search_matches":
        matches = output.get(str(hint.get("matches_field") or "matches"))
        max_items = int(hint.get("max_items") or 10)
        if not isinstance(matches, list):
            return None
        if not matches:
            return "No matches found."
        lines: list[str] = []
        for match in matches[:max_items]:
            if not isinstance(match, dict):
                continue
            path = str(match.get("path") or "").strip()
            line_num = match.get("line")
            text = str(match.get("text") or "").strip()
            loc = f"{path}:{line_num}" if path and line_num is not None else path or "match"
            lines.append(f"- {loc} {text}".rstrip())
        return ("Matches:\n" + "\n".join(lines)) if lines else "No matches found."

    if mode == "json_preview":
        entries_fields: list[str] = hint.get("entries_fields") or ["entries", "matches"]
        max_items = int(hint.get("max_items") or 5)
        entries = next(
            (output.get(f) for f in entries_fields if isinstance(output.get(f), list)),
            None,
        )
        if not isinstance(entries, list) or not entries:
            return None
        return json.dumps(entries[:max_items], ensure_ascii=True, indent=2)[:max_preview_chars]

    if mode == "rag_matches":
        matches = output.get("matches")
        max_items = int(hint.get("max_items") or 5)
        excerpt_chars = int(hint.get("excerpt_chars") or 180)
        if not isinstance(matches, list):
            return None
        if not matches:
            return "No matches found."
        lines = []
        for match in matches[:max_items]:
            if not isinstance(match, dict):
                continue
            label = (
                str(match.get("source_uri") or "").strip()
                or str(match.get("document_id") or "").strip()
                or "match"
            )
            score = match.get("score")
            text = str(match.get("text") or "").strip()
            pfx = (
                f"- {label} (score {score:.3f})"
                if isinstance(score, (int, float))
                else f"- {label}"
            )
            if text:
                excerpt = text[:excerpt_chars]
                lines.append(f"{pfx}: {excerpt}{'...' if len(text) > excerpt_chars else ''}")
            else:
                lines.append(pfx)
        return ("Retrieved matches:\n" + "\n".join(lines)) if lines else "No matches found."

    return None


def _format_chat_direct_result(
    capability_id: str,
    output: dict[str, Any],
    *,
    max_preview_chars: int,
) -> str:
    """Format a capability output for display in chat.

    Tries the spec-driven chat_response_hint from the capability registry first;
    falls back to a generic JSON dump. Adding a new capability to the allow-list
    only requires a chat_response_hint in capability_registry.yaml — no code here.
    """
    try:
        registry = capability_registry.load_capability_registry()
        spec = registry.get(capability_id)
        if spec is not None:
            hint = spec.planner_hints.get("chat_response_hint")
            if isinstance(hint, dict):
                rendered = _render_hint(output, hint, max_preview_chars=max_preview_chars)
                if rendered is not None:
                    return rendered
    except Exception:  # noqa: BLE001
        pass

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
