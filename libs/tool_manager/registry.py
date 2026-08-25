"""Tool registry assembly: catalog wiring, plugin loading, governance filtering.

This is the "tool manager" layer of the harness/MCP/tool-manager/memory split.
Handler *implementations* live in libs/tools/ (per CLAUDE.md's standing rule);
this module only wires them together into a ToolRegistry. libs/core/tool_registry.py
re-exports this module's public names for backward compatibility with the many
existing `from libs.core import tool_registry` call sites across the services.
"""

from __future__ import annotations

import logging
import math
import os
from dataclasses import dataclass
from typing import Any, Callable, Dict, Optional

from libs.core.llm_provider import LLMProvider
from libs.core import planner_support_tools
from libs.framework.tool_runtime import (
    Tool as _FrameworkTool,
    ToolRegistry,
)
from libs.harness.agent import _agent
from libs.mcp import mcp_gateway
from libs.tool_manager import tool_governance, tool_plugins
from libs.tools import coder_tools
from libs.tools.core_ops import CoreOpsHandlers, register_core_ops_tools
from libs.tools.docx_render_from_spec import register_docx_tools
from libs.tools.document_spec_iterative import register_document_spec_iterative_tools
from libs.tools.document_spec_llm import (
    _sanitize_document_spec,
    llm_generate_document_spec as _llm_generate_document_spec_external,
    llm_improve_document_spec as _llm_improve_document_spec_external,
    register_document_spec_llm_tools,
)
from libs.tools.document_spec_validate import register_document_spec_tools
from libs.tools.docx_template_render import _docx_render
from libs.tools.file_ops import (
    _artifact_copy,
    _artifact_delete,
    _artifact_mkdir,
    _artifact_move_to_workspace,
    _artifact_rename,
    _derive_output_filename,
    _file_read_text,
    _list_files,
    _list_workspace_files,
    _search_text,
    _workspace_copy,
    _workspace_delete,
    _workspace_mkdir,
    _workspace_read_text,
    _workspace_rename,
    _write_text_file,
)
from libs.tools.llm_tool_groups import (
    register_agent_tool,
    register_coding_agent_publish_pr_tool,
    register_llm_contextual_text_tool,
    register_llm_text_tool,
)
from libs.tools.llm_ops import (
    _llm_generate,
    _llm_generate_with_context,
    _resolve_llm_iterative_tool_timeout_s,
    _resolve_llm_timeout_s,
)
from libs.tools.memory_ops import (
    _memory_read,
    _memory_semantic_search,
    _memory_semantic_write,
    _memory_write,
)
from libs.tools.openapi_iterative import register_openapi_iterative_tools
from libs.tools.pdf_render_from_spec import register_pdf_tools

LOGGER = logging.getLogger(__name__)

Tool = _FrameworkTool
ToolPluginLoadError = tool_plugins.ToolPluginLoadError
ToolAllowDecision = tool_governance.ToolAllowDecision


# ─── Coder-agent adapters ──────────────────────────────────────────────────
# Thin wiring that binds this module's LOGGER/tracing into coder_tools.py's
# already-implemented handlers.


def _resolve_coding_agent_timeout_s() -> int:
    env_timeout = os.getenv("CODING_AGENT_TIMEOUT_S")
    if env_timeout:
        try:
            return max(1, int(math.ceil(float(env_timeout))))
        except ValueError:
            return 30
    return 30


def _coding_agent_publish_pr(payload: Dict[str, Any]) -> Dict[str, Any]:
    from libs.tools.file_ops import _safe_workspace_path

    return coder_tools.coding_agent_publish_pr(
        payload,
        safe_workspace_path=_safe_workspace_path,
        invoke_capability=mcp_gateway.invoke_capability,
    )


def _llm_generate_document_spec(payload: Dict[str, Any], provider: LLMProvider) -> Dict[str, Any]:
    return _llm_generate_document_spec_external(
        payload,
        provider,
        sanitize_document_spec=_sanitize_document_spec,
    )


def _llm_improve_document_spec(payload: Dict[str, Any], provider: LLMProvider) -> Dict[str, Any]:
    return _llm_improve_document_spec_external(
        payload,
        provider,
        sanitize_document_spec=_sanitize_document_spec,
    )


# ─── Catalog assembly ──────────────────────────────────────────────────────


@dataclass(frozen=True)
class ToolCatalogHandlers:
    core_ops_handlers: CoreOpsHandlers
    resolve_llm_timeout_s: Callable[[Optional[LLMProvider]], int]
    resolve_coding_agent_timeout_s: Callable[[], int]
    resolve_llm_iterative_timeout_s: Callable[[Optional[LLMProvider]], int]
    llm_generate: Callable[[Dict[str, Any], LLMProvider], Dict[str, Any]]
    llm_generate_with_context: Callable[[Dict[str, Any], LLMProvider], Dict[str, Any]]
    coding_agent_publish_pr: Callable[[Dict[str, Any]], Dict[str, Any]]
    agent: Callable[[Dict[str, Any], LLMProvider], Dict[str, Any]]
    llm_generate_document_spec: Callable[[Dict[str, Any], LLMProvider], Dict[str, Any]]
    llm_improve_document_spec: Callable[[Dict[str, Any], LLMProvider], Dict[str, Any]]
    sanitize_document_spec: Callable[[dict[str, Any]], dict[str, Any]]


def register_default_tools(
    registry: ToolRegistry,
    *,
    handlers: ToolCatalogHandlers,
    llm_enabled: bool = False,
    llm_provider: Optional[LLMProvider] = None,
) -> None:
    register_core_ops_tools(
        registry,
        handlers=handlers.core_ops_handlers,
    )
    register_docx_tools(registry)
    register_pdf_tools(registry)
    register_document_spec_tools(registry)

    if not llm_enabled:
        return
    if llm_provider is None:
        raise ValueError("llm_enabled requires a llm_provider instance")

    llm_timeout_s = handlers.resolve_llm_timeout_s(llm_provider)
    coding_agent_timeout_s = handlers.resolve_coding_agent_timeout_s()
    llm_iterative_timeout_s = handlers.resolve_llm_iterative_timeout_s(llm_provider)

    register_llm_text_tool(
        registry,
        timeout_s=llm_timeout_s,
        handler=lambda payload, provider=llm_provider: handlers.llm_generate(payload, provider),
    )
    register_llm_contextual_text_tool(
        registry,
        timeout_s=llm_timeout_s,
        handler=lambda payload, provider=llm_provider: handlers.llm_generate_with_context(
            payload, provider
        ),
    )
    register_coding_agent_publish_pr_tool(
        registry,
        timeout_s=coding_agent_timeout_s,
        handler_publish_pr=handlers.coding_agent_publish_pr,
    )
    register_agent_tool(
        registry,
        timeout_s=coding_agent_timeout_s,
        handler=lambda payload, provider=llm_provider: handlers.agent(payload, provider),
    )
    register_document_spec_llm_tools(
        registry,
        llm_provider,
        timeout_s=llm_timeout_s,
        sanitize_document_spec=handlers.sanitize_document_spec,
    )
    register_document_spec_iterative_tools(
        registry,
        llm_provider,
        timeout_s=llm_iterative_timeout_s,
        generate_document_spec=handlers.llm_generate_document_spec,
        improve_document_spec=handlers.llm_improve_document_spec,
        sanitize_document_spec=handlers.sanitize_document_spec,
    )
    register_openapi_iterative_tools(
        registry,
        llm_provider,
        timeout_s=llm_iterative_timeout_s,
    )


def build_planner_support_tool_specs() -> list[Any]:
    return planner_support_tools.build_planner_support_tool_specs()


def _build_core_ops_handlers() -> CoreOpsHandlers:
    return CoreOpsHandlers(
        file_write_text=_write_text_file,
        file_read_text=_file_read_text,
        list_files=_list_files,
        workspace_read_text=_workspace_read_text,
        workspace_list_files=_list_workspace_files,
        artifact_mkdir=_artifact_mkdir,
        workspace_mkdir=_workspace_mkdir,
        artifact_delete=_artifact_delete,
        workspace_delete=_workspace_delete,
        artifact_rename=_artifact_rename,
        workspace_rename=_workspace_rename,
        artifact_copy=_artifact_copy,
        workspace_copy=_workspace_copy,
        artifact_move=_artifact_move_to_workspace,
        derive_output_filename=_derive_output_filename,
        search_text=_search_text,
        memory_read=_memory_read,
        memory_write=_memory_write,
        memory_semantic_write=_memory_semantic_write,
        memory_semantic_search=_memory_semantic_search,
        docx_render=_docx_render,
    )


def _default_catalog_handlers() -> ToolCatalogHandlers:
    return ToolCatalogHandlers(
        core_ops_handlers=_build_core_ops_handlers(),
        resolve_llm_timeout_s=_resolve_llm_timeout_s,
        resolve_coding_agent_timeout_s=_resolve_coding_agent_timeout_s,
        resolve_llm_iterative_timeout_s=_resolve_llm_iterative_tool_timeout_s,
        llm_generate=_llm_generate,
        llm_generate_with_context=_llm_generate_with_context,
        coding_agent_publish_pr=_coding_agent_publish_pr,
        agent=_agent,
        llm_generate_document_spec=_llm_generate_document_spec,
        llm_improve_document_spec=_llm_improve_document_spec,
        sanitize_document_spec=_sanitize_document_spec,
    )


def build_tool_registry(
    *,
    handlers: ToolCatalogHandlers,
    http_fetch_enabled: bool = False,
    llm_enabled: bool = False,
    llm_provider: Optional[LLMProvider] = None,
    service_name: str | None = None,
) -> ToolRegistry:
    registry = ToolRegistry()
    register_default_tools(
        registry,
        handlers=handlers,
        llm_enabled=llm_enabled,
        llm_provider=llm_provider,
    )
    tool_plugins.load_configured_plugins(
        registry,
        llm_enabled=llm_enabled,
        llm_provider=llm_provider,
        http_fetch_enabled=http_fetch_enabled,
    )
    tool_governance.filter_registry_tools(registry, service_name)
    return registry


def build_default_registry(
    *,
    http_fetch_enabled: bool = False,
    llm_enabled: bool = False,
    llm_provider: Optional[LLMProvider] = None,
    service_name: str | None = None,
) -> ToolRegistry:
    return build_tool_registry(
        handlers=_default_catalog_handlers(),
        http_fetch_enabled=http_fetch_enabled,
        llm_enabled=llm_enabled,
        llm_provider=llm_provider,
        service_name=service_name,
    )


def default_registry(
    http_fetch_enabled: bool = False,
    llm_enabled: bool = False,
    llm_provider: Optional[LLMProvider] = None,
    service_name: Optional[str] = None,
) -> ToolRegistry:
    return build_default_registry(
        http_fetch_enabled=http_fetch_enabled,
        llm_enabled=llm_enabled,
        llm_provider=llm_provider,
        service_name=service_name,
    )
