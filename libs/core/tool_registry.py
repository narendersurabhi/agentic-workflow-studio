from __future__ import annotations

import json
import logging
import math
import os
import re
import shutil
from subprocess import CompletedProcess, run
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional
from urllib.parse import urlparse

from dataclasses import dataclass

from .llm_provider import LLMProvider, LLMRequest
from . import tool_governance, tool_plugins, tracing as core_tracing
from libs.core import mcp_gateway, sub_agent_dispatch
from .models import ToolSpec
from libs.framework.tool_runtime import (
    Tool as _FrameworkTool,
    ToolExecutionError,
    ToolRegistry,
    classify_tool_error as _classify_tool_error,
    validate_schema as _validate_schema,
)
from libs.core.memory_client import MemoryClient, MemoryClientError
from libs.tools.document_spec_llm import (
    llm_generate_document_spec as _llm_generate_document_spec_external,
    llm_improve_document_spec as _llm_improve_document_spec_external,
)
from libs.tools.core_ops import CoreOpsHandlers, register_core_ops_tools
from libs.tools.docx_render_from_spec import register_docx_tools
from libs.tools.document_spec_iterative import register_document_spec_iterative_tools
from libs.tools.document_spec_llm import register_document_spec_llm_tools
from libs.tools.document_spec_validate import register_document_spec_tools
from libs.tools.github_tools import register_github_tools
from libs.tools.llm_tool_groups import (
    register_agent_tool,
    register_coding_agent_tools,
    register_llm_text_tool,
)
from libs.tools.openapi_iterative import register_openapi_iterative_tools
from libs.tools.pdf_render_from_spec import register_pdf_tools
from libs.tools import mcp_client
from libs.tools import coder_tools
from libs.tools import agent_tools
from . import planner_support_tools

LOGGER = logging.getLogger(__name__)

Tool = _FrameworkTool


ToolPluginLoadError = tool_plugins.ToolPluginLoadError


ToolAllowDecision = tool_governance.ToolAllowDecision


def _extract_mcp_error_phase(error_text: str) -> str | None:
    return mcp_client.extract_mcp_error_phase(error_text)


def _safe_artifact_path(path: str, default_name: str) -> Path:
    base_dir = Path("/shared/artifacts")
    base_dir.mkdir(parents=True, exist_ok=True)
    candidate = Path(path or default_name)
    if candidate.is_absolute():
        resolved = candidate.resolve()
    else:
        resolved = (base_dir / candidate).resolve()
    if not str(resolved).startswith(str(base_dir.resolve())):
        raise ToolExecutionError("Invalid path outside /shared/artifacts")
    return resolved


def _workspace_root() -> Path:
    env_root = os.getenv("WORKSPACE_DIR")
    if env_root:
        return Path(env_root).resolve()
    return Path(__file__).resolve().parents[2]


def _safe_workspace_path(path: str, default_name: str) -> Path:
    base_dir = _workspace_root()
    base_dir.mkdir(parents=True, exist_ok=True)
    candidate = Path(path or default_name)
    if candidate.is_absolute():
        resolved = candidate.resolve()
    else:
        resolved = (base_dir / candidate).resolve()
    if not str(resolved).startswith(str(base_dir.resolve())):
        raise ToolExecutionError("Invalid path outside workspace")
    return resolved


def _resolve_schema_path(schema_ref: str) -> Path:
    registry_dir = Path(os.getenv("SCHEMA_REGISTRY_PATH", "/app/schemas"))
    template_dir = Path(os.getenv("DOCX_TEMPLATE_DIR", "/shared/templates"))
    name = schema_ref
    if schema_ref.startswith("schema/"):
        name = schema_ref.split("/", 1)[1]
    if not name.endswith(".json"):
        name = f"{name}.json"
    candidate = registry_dir / name
    if candidate.exists():
        return candidate
    return template_dir / name


def _validate_schema_from_registry(schema_ref: str, payload: Dict[str, Any]) -> None:
    schema_path = _resolve_schema_path(schema_ref)
    if not schema_path.exists():
        raise ToolExecutionError(f"schema_not_found:{schema_path}")
    try:
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        raise ToolExecutionError(f"invalid_schema:{exc}") from exc
    _validate_schema(schema, payload, "input")


def _parse_http_allowlist() -> List[str]:
    raw = os.getenv("TOOL_HTTP_FETCH_ALLOWLIST", "")
    return [entry.strip() for entry in raw.split(",") if entry.strip()]


def _resolve_llm_timeout_s(provider: Optional[LLMProvider]) -> int:
    if provider is not None and hasattr(provider, "timeout_s"):
        try:
            return max(1, int(math.ceil(getattr(provider, "timeout_s"))))
        except (TypeError, ValueError):
            pass
    env_timeout = os.getenv("OPENAI_TIMEOUT_S")
    if env_timeout:
        try:
            return max(1, int(math.ceil(float(env_timeout))))
        except ValueError:
            return 30
    return 30


def _resolve_coding_agent_timeout_s() -> int:
    env_timeout = os.getenv("CODING_AGENT_TIMEOUT_S")
    if env_timeout:
        try:
            return max(1, int(math.ceil(float(env_timeout))))
        except ValueError:
            return 30
    return 30


def _resolve_coder_http_timeout_s() -> int:
    for key in ("CODER_HTTP_TIMEOUT_S", "CODING_AGENT_TIMEOUT_S"):
        env_timeout = os.getenv(key)
        if env_timeout:
            try:
                return max(1, int(math.ceil(float(env_timeout))))
            except ValueError:
                return 30
    return 30


def _resolve_mcp_timeout_s() -> float:
    return mcp_client.resolve_mcp_timeout_s()


def _resolve_mcp_outer_timeout_headroom_s() -> float:
    return mcp_client.resolve_mcp_outer_timeout_headroom_s()


def _resolve_mcp_tool_timeout_s() -> int:
    return mcp_client.resolve_mcp_tool_timeout_s()


def _resolve_mcp_max_retries() -> int:
    return mcp_client.resolve_mcp_max_retries()


def _resolve_mcp_retry_sleep_s() -> float:
    return mcp_client.resolve_mcp_retry_sleep_s()


def _resolve_mcp_first_attempt_reserve_s(timeout_s: float) -> float:
    return mcp_client.resolve_mcp_first_attempt_reserve_s(timeout_s)


def _resolve_mcp_transport_timeout_s(timeout_s: float) -> float:
    return mcp_client.resolve_mcp_transport_timeout_s(timeout_s)


def _resolve_mcp_isolation_mode() -> str:
    return mcp_client.resolve_mcp_isolation_mode()


def _streamable_http_client_kwargs(
    client_factory: Callable[..., Any], timeout_s: float
) -> Dict[str, Any]:
    return mcp_client.streamable_http_client_kwargs(client_factory, timeout_s)


def _is_retryable_mcp_error(message: str) -> bool:
    return mcp_client.is_retryable_mcp_error(message)


def _host_allowed(host: str, allowlist: List[str]) -> bool:
    if not allowlist:
        return False
    if "*" in allowlist:
        return True
    for entry in allowlist:
        if entry.startswith("*."):
            suffix = entry[1:]
            if host.endswith(suffix):
                return True
        elif entry.startswith("."):
            if host.endswith(entry):
                return True
        elif host == entry:
            return True
    return False


def evaluate_tool_allowlist(
    tool_name: str,
    service_name: str | None = None,
    *,
    context: dict[str, Any] | None = None,
    tool_spec: ToolSpec | None = None,
) -> ToolAllowDecision:
    return tool_governance.evaluate_tool_allowlist(
        tool_name,
        service_name,
        context=context,
        tool_spec=tool_spec,
    )


def _filter_registry_tools(registry: ToolRegistry, service_name: str | None = None) -> None:
    tool_governance.filter_registry_tools(registry, service_name)


def _parse_plugin_spec(spec: str) -> tuple[str, str]:
    return tool_plugins.parse_plugin_spec(spec)


def _resolve_module_register_fn(module: Any, attr_name: str) -> Callable[..., None]:
    return tool_plugins.resolve_module_register_fn(module, attr_name)


def _call_register_fn(
    register_fn: Callable[..., None],
    registry: ToolRegistry,
    *,
    llm_enabled: bool,
    llm_provider: Optional[LLMProvider],
    http_fetch_enabled: bool,
) -> None:
    tool_plugins.call_register_fn(
        register_fn,
        registry,
        llm_enabled=llm_enabled,
        llm_provider=llm_provider,
        http_fetch_enabled=http_fetch_enabled,
    )


def _load_module_plugins(
    registry: ToolRegistry,
    *,
    llm_enabled: bool,
    llm_provider: Optional[LLMProvider],
    http_fetch_enabled: bool,
) -> None:
    tool_plugins.load_module_plugins(
        registry,
        llm_enabled=llm_enabled,
        llm_provider=llm_provider,
        http_fetch_enabled=http_fetch_enabled,
    )


def _iter_entry_points(group: str) -> list[Any]:
    return tool_plugins._iter_entry_points(group)


def _load_entrypoint_plugins(
    registry: ToolRegistry,
    *,
    llm_enabled: bool,
    llm_provider: Optional[LLMProvider],
    http_fetch_enabled: bool,
) -> None:
    tool_plugins.load_entrypoint_plugins(
        registry,
        llm_enabled=llm_enabled,
        llm_provider=llm_provider,
        http_fetch_enabled=http_fetch_enabled,
    )


@dataclass(frozen=True)
class ToolCatalogHandlers:
    core_ops_handlers: CoreOpsHandlers
    resolve_llm_timeout_s: Callable[[Optional[LLMProvider]], int]
    resolve_coding_agent_timeout_s: Callable[[], int]
    resolve_llm_iterative_timeout_s: Callable[[Optional[LLMProvider]], int]
    llm_generate: Callable[[Dict[str, Any], LLMProvider], Dict[str, Any]]
    coding_agent_generate: Callable[[Dict[str, Any]], Dict[str, Any]]
    coding_agent_autonomous: Callable[[Dict[str, Any], LLMProvider], Dict[str, Any]]
    coding_agent_publish_pr: Callable[[Dict[str, Any]], Dict[str, Any]]
    agent: Callable[[Dict[str, Any], LLMProvider], Dict[str, Any]]
    llm_generate_document_spec: Callable[[Dict[str, Any], LLMProvider], Dict[str, Any]]
    llm_improve_document_spec: Callable[[Dict[str, Any], LLMProvider], Dict[str, Any]]
    sanitize_document_spec: Callable[[dict[str, Any]], dict[str, Any]]


def register_default_tools(
    registry: ToolRegistry,
    *,
    handlers: ToolCatalogHandlers,
    http_fetch_enabled: bool = False,
    llm_enabled: bool = False,
    llm_provider: Optional[LLMProvider] = None,
) -> None:
    register_core_ops_tools(
        registry,
        handlers=handlers.core_ops_handlers,
        http_fetch_enabled=http_fetch_enabled,
    )
    register_docx_tools(registry)
    register_pdf_tools(registry)
    register_document_spec_tools(registry)
    register_github_tools(registry)

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
    register_coding_agent_tools(
        registry,
        timeout_s=coding_agent_timeout_s,
        handler_generate=handlers.coding_agent_generate,
        handler_autonomous=lambda payload, provider=llm_provider: handlers.coding_agent_autonomous(
            payload, provider
        ),
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


def build_planner_support_tool_specs() -> list[ToolSpec]:
    return planner_support_tools.build_planner_support_tool_specs()


def _build_core_ops_handlers() -> CoreOpsHandlers:
    return CoreOpsHandlers(
        math_eval=_math_eval,
        file_write_text=_write_text_file,
        file_read_text=_file_read_text,
        list_files=_list_files,
        workspace_write_text=_write_workspace_text_file,
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
        run_tests=_run_tests,
        search_text=_search_text,
        memory_read=_memory_read,
        memory_write=_memory_write,
        memory_semantic_write=_memory_semantic_write,
        memory_semantic_search=_memory_semantic_search,
        docx_render=_docx_render,
        http_fetch=_http_fetch,
    )


def _default_catalog_handlers() -> ToolCatalogHandlers:
    return ToolCatalogHandlers(
        core_ops_handlers=_build_core_ops_handlers(),
        resolve_llm_timeout_s=_resolve_llm_timeout_s,
        resolve_coding_agent_timeout_s=_resolve_coding_agent_timeout_s,
        resolve_llm_iterative_timeout_s=_resolve_llm_iterative_tool_timeout_s,
        llm_generate=_llm_generate,
        coding_agent_generate=_coding_agent_generate,
        coding_agent_autonomous=_coding_agent_autonomous,
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
        http_fetch_enabled=http_fetch_enabled,
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


def _math_eval(payload: Dict[str, Any]) -> Dict[str, Any]:
    expr = payload.get("expr", "0")
    allowed = {"sqrt": math.sqrt, "pow": pow}
    value = eval(expr, {"__builtins__": {}}, allowed)  # noqa: S307
    return {"value": value}


def _write_text_file(
    payload: Dict[str, Any], default_filename: str | None = None
) -> Dict[str, Any]:
    path = payload.get("path", "")
    content = payload.get("content", "")
    if not isinstance(path, str) or not path.strip():
        if not default_filename:
            raise ToolExecutionError("Missing path")
        path = default_filename
    path = path.strip()
    if path and path.endswith("/"):
        raise ToolExecutionError("Missing file name in path")
    candidate = _safe_artifact_path(path, default_filename or "")
    candidate.parent.mkdir(parents=True, exist_ok=True)
    candidate.write_text(content, encoding="utf-8")
    return {"path": str(candidate)}


def _write_workspace_text_file(
    payload: Dict[str, Any], default_filename: str | None = None
) -> Dict[str, Any]:
    path = payload.get("path", "")
    content = payload.get("content", "")
    if not isinstance(path, str) or not path.strip():
        if not default_filename:
            raise ToolExecutionError("Missing path")
        path = default_filename
    path = path.strip()
    if path and path.endswith("/"):
        raise ToolExecutionError("Missing file name in path")
    candidate = _safe_workspace_path(path, default_filename or "")
    candidate.parent.mkdir(parents=True, exist_ok=True)
    candidate.write_text(content, encoding="utf-8")
    return {"path": str(candidate)}


def _file_read_text(payload: Dict[str, Any]) -> Dict[str, Any]:
    path = payload.get("path", "")
    if not path:
        raise ToolExecutionError("Missing path")
    candidate = _safe_artifact_path(path, "output.txt")
    if not candidate.exists():
        raise ToolExecutionError("File not found")
    return {"content": candidate.read_text(encoding="utf-8")}


def _workspace_read_text(payload: Dict[str, Any]) -> Dict[str, Any]:
    path = payload.get("path", "")
    if not path:
        raise ToolExecutionError("Missing path")
    candidate = _safe_workspace_path(path, "output.txt")
    if not candidate.exists():
        raise ToolExecutionError("File not found")
    return {"content": candidate.read_text(encoding="utf-8")}


def _list_files(payload: Dict[str, Any]) -> Dict[str, Any]:
    path = payload.get("path", "")
    recursive = bool(payload.get("recursive", False))
    max_files = payload.get("max_files", 200)
    if not isinstance(max_files, int) or max_files < 1:
        max_files = 200
    root = _safe_artifact_path(path, "")
    if not root.exists():
        return {"entries": []}
    if root.is_file():
        return {"entries": [{"path": str(root), "type": "file"}]}
    entries = []
    iterator = root.rglob("*") if recursive else root.glob("*")
    for entry in iterator:
        entry_type = "dir" if entry.is_dir() else "file"
        entries.append({"path": str(entry), "type": entry_type})
        if len(entries) >= max_files:
            break
    return {"entries": entries}


def _list_workspace_files(payload: Dict[str, Any]) -> Dict[str, Any]:
    path = payload.get("path", "")
    recursive = bool(payload.get("recursive", False))
    max_files = payload.get("max_files", 200)
    if not isinstance(max_files, int) or max_files < 1:
        max_files = 200
    root = _safe_workspace_path(path, "")
    if not root.exists():
        return {"entries": []}
    if root.is_file():
        return {"entries": [{"path": str(root), "type": "file"}]}
    entries = []
    iterator = root.rglob("*") if recursive else root.glob("*")
    for entry in iterator:
        entry_type = "dir" if entry.is_dir() else "file"
        entries.append({"path": str(entry), "type": entry_type})
        if len(entries) >= max_files:
            break
    return {"entries": entries}


def _artifact_mkdir(payload: Dict[str, Any]) -> Dict[str, Any]:
    path = payload.get("path", "")
    if not path:
        raise ToolExecutionError("Missing path")
    parents = bool(payload.get("parents", True))
    exist_ok = bool(payload.get("exist_ok", True))
    candidate = _safe_artifact_path(path, "")
    candidate.mkdir(parents=parents, exist_ok=exist_ok)
    return {"path": str(candidate)}


def _workspace_mkdir(payload: Dict[str, Any]) -> Dict[str, Any]:
    path = payload.get("path", "")
    if not path:
        raise ToolExecutionError("Missing path")
    parents = bool(payload.get("parents", True))
    exist_ok = bool(payload.get("exist_ok", True))
    candidate = _safe_workspace_path(path, "")
    candidate.mkdir(parents=parents, exist_ok=exist_ok)
    return {"path": str(candidate)}


def _delete_path(target: Path, *, recursive: bool, missing_ok: bool) -> Dict[str, Any]:
    if not target.exists():
        if missing_ok:
            return {"path": str(target), "deleted": False}
        raise ToolExecutionError("Path not found")
    if target.is_dir():
        if recursive:
            shutil.rmtree(target)
        else:
            target.rmdir()
    else:
        target.unlink()
    return {"path": str(target), "deleted": True}


def _artifact_delete(payload: Dict[str, Any]) -> Dict[str, Any]:
    path = payload.get("path", "")
    if not path:
        raise ToolExecutionError("Missing path")
    recursive = bool(payload.get("recursive", False))
    missing_ok = bool(payload.get("missing_ok", False))
    target = _safe_artifact_path(path, "")
    return _delete_path(target, recursive=recursive, missing_ok=missing_ok)


def _workspace_delete(payload: Dict[str, Any]) -> Dict[str, Any]:
    path = payload.get("path", "")
    if not path:
        raise ToolExecutionError("Missing path")
    recursive = bool(payload.get("recursive", False))
    missing_ok = bool(payload.get("missing_ok", False))
    target = _safe_workspace_path(path, "")
    return _delete_path(target, recursive=recursive, missing_ok=missing_ok)


def _replace_existing_path(path: Path) -> None:
    if not path.exists():
        return
    if path.is_dir():
        shutil.rmtree(path)
    else:
        path.unlink()


def _rename_path(
    source: Path,
    destination: Path,
    *,
    overwrite: bool,
) -> Dict[str, Any]:
    if not source.exists():
        raise ToolExecutionError("Source path not found")
    if destination.exists():
        if not overwrite:
            raise ToolExecutionError("Destination already exists")
        _replace_existing_path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    source.replace(destination)
    return {"path": str(destination)}


def _artifact_rename(payload: Dict[str, Any]) -> Dict[str, Any]:
    source_path = payload.get("source_path", "")
    destination_path = payload.get("destination_path", "")
    overwrite = bool(payload.get("overwrite", False))
    if not source_path:
        raise ToolExecutionError("Missing source_path")
    if not destination_path:
        raise ToolExecutionError("Missing destination_path")
    if destination_path.endswith("/"):
        raise ToolExecutionError("Missing file or directory name in destination_path")
    source = _safe_artifact_path(source_path, "")
    destination = _safe_artifact_path(destination_path, "")
    return _rename_path(source, destination, overwrite=overwrite)


def _workspace_rename(payload: Dict[str, Any]) -> Dict[str, Any]:
    source_path = payload.get("source_path", "")
    destination_path = payload.get("destination_path", "")
    overwrite = bool(payload.get("overwrite", False))
    if not source_path:
        raise ToolExecutionError("Missing source_path")
    if not destination_path:
        raise ToolExecutionError("Missing destination_path")
    if destination_path.endswith("/"):
        raise ToolExecutionError("Missing file or directory name in destination_path")
    source = _safe_workspace_path(source_path, "")
    destination = _safe_workspace_path(destination_path, "")
    return _rename_path(source, destination, overwrite=overwrite)


def _copy_path(
    source: Path,
    destination: Path,
    *,
    overwrite: bool,
    recursive: bool,
) -> Dict[str, Any]:
    if not source.exists():
        raise ToolExecutionError("Source path not found")
    if destination.exists():
        if not overwrite:
            raise ToolExecutionError("Destination already exists")
        _replace_existing_path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    if source.is_dir():
        if not recursive:
            raise ToolExecutionError("Source is a directory; set recursive=true")
        shutil.copytree(source, destination)
    else:
        shutil.copy2(source, destination)
    return {"path": str(destination)}


def _artifact_copy(payload: Dict[str, Any]) -> Dict[str, Any]:
    source_path = payload.get("source_path", "")
    destination_path = payload.get("destination_path", "")
    overwrite = bool(payload.get("overwrite", False))
    recursive = bool(payload.get("recursive", True))
    if not source_path:
        raise ToolExecutionError("Missing source_path")
    if not destination_path:
        raise ToolExecutionError("Missing destination_path")
    if destination_path.endswith("/"):
        raise ToolExecutionError("Missing file or directory name in destination_path")
    source = _safe_artifact_path(source_path, "")
    destination = _safe_artifact_path(destination_path, "")
    return _copy_path(source, destination, overwrite=overwrite, recursive=recursive)


def _workspace_copy(payload: Dict[str, Any]) -> Dict[str, Any]:
    source_path = payload.get("source_path", "")
    destination_path = payload.get("destination_path", "")
    overwrite = bool(payload.get("overwrite", False))
    recursive = bool(payload.get("recursive", True))
    if not source_path:
        raise ToolExecutionError("Missing source_path")
    if not destination_path:
        raise ToolExecutionError("Missing destination_path")
    if destination_path.endswith("/"):
        raise ToolExecutionError("Missing file or directory name in destination_path")
    source = _safe_workspace_path(source_path, "")
    destination = _safe_workspace_path(destination_path, "")
    return _copy_path(source, destination, overwrite=overwrite, recursive=recursive)


def _artifact_move_to_workspace(payload: Dict[str, Any]) -> Dict[str, Any]:
    source_path = payload.get("source_path", "")
    destination_path = payload.get("destination_path", "")
    overwrite = bool(payload.get("overwrite", False))
    if not source_path:
        raise ToolExecutionError("Missing source_path")
    if not destination_path:
        raise ToolExecutionError("Missing destination_path")
    if destination_path.endswith("/"):
        raise ToolExecutionError("Missing file name in destination_path")
    source = _safe_artifact_path(source_path, "")
    if not source.exists():
        raise ToolExecutionError("Source file not found")
    destination = _safe_workspace_path(destination_path, "")
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists() and not overwrite:
        raise ToolExecutionError("Destination already exists")
    shutil.move(str(source), str(destination))
    return {"path": str(destination)}


def _run_tests(payload: Dict[str, Any]) -> Dict[str, Any]:
    command = payload.get("command", "")
    args = payload.get("args") or []
    cwd = payload.get("cwd", "")
    if not isinstance(args, list):
        args = []
    allowlist = {"pytest", "python"}
    if command not in allowlist:
        raise ToolExecutionError("Command not allowed")
    cmd = [command, *args]
    if command == "python":
        if len(args) < 2 or args[0] != "-m" or args[1] != "pytest":
            raise ToolExecutionError("Only python -m pytest is allowed")
    run_cwd = _safe_artifact_path(cwd, "")
    if not run_cwd.exists():
        raise ToolExecutionError("Working directory not found")
    result: CompletedProcess[str] = run(
        cmd, cwd=str(run_cwd), capture_output=True, text=True, check=False
    )
    return {"exit_code": result.returncode, "stdout": result.stdout, "stderr": result.stderr}


def _search_text(payload: Dict[str, Any]) -> Dict[str, Any]:
    query = payload.get("query", "")
    if not isinstance(query, str) or not query:
        raise ToolExecutionError("Missing query")
    path = payload.get("path", "")
    glob = payload.get("glob", "")
    case_sensitive = bool(payload.get("case_sensitive", False))
    use_regex = bool(payload.get("regex", False))
    context_lines = payload.get("context_lines", 0)
    if not isinstance(context_lines, int) or context_lines < 0:
        context_lines = 0
    max_matches = payload.get("max_matches", 200)
    if not isinstance(max_matches, int) or max_matches < 1:
        max_matches = 200
    root = _safe_artifact_path(path, "")
    if not root.exists():
        return {"matches": []}
    pattern = glob or "**/*"
    matches = []
    needle = query if case_sensitive else query.lower()
    regex = None
    if use_regex:
        import re

        flags = 0 if case_sensitive else re.IGNORECASE
        try:
            regex = re.compile(query, flags=flags)
        except re.error as exc:
            raise ToolExecutionError(f"Invalid regex: {exc}") from exc
    for file_path in root.glob(pattern):
        if not file_path.is_file():
            continue
        try:
            with file_path.open("r", encoding="utf-8") as handle:
                lines = handle.readlines()
                for idx, line in enumerate(lines, start=1):
                    hay = line if case_sensitive else line.lower()
                    matched = False
                    if regex is not None:
                        matched = regex.search(line) is not None
                    else:
                        matched = needle in hay
                    if matched:
                        start = max(0, idx - 1 - context_lines)
                        end = min(len(lines), idx - 1 + context_lines + 1)
                        context = [item.rstrip("\n") for item in lines[start:end]]
                        entry = {"path": str(file_path), "line": idx, "text": line.rstrip("\n")}
                        if context_lines:
                            entry["context"] = context
                        matches.append(entry)
                        if len(matches) >= max_matches:
                            return {"matches": matches}
        except OSError:
            continue
    return {"matches": matches}


def _memory_client() -> MemoryClient:
    base_url = os.getenv("MEMORY_API_URL", "http://api:8000").strip() or "http://api:8000"
    timeout_raw = os.getenv("MEMORY_API_TIMEOUT_S", "5.0").strip()
    try:
        timeout_s = float(timeout_raw)
    except ValueError:
        timeout_s = 5.0
    timeout_s = max(0.5, min(timeout_s, 60.0))
    return MemoryClient(base_url, timeout_s=timeout_s)


def _memory_read(payload: Dict[str, Any]) -> Dict[str, Any]:
    name = payload.get("name")
    if not isinstance(name, str) or not name.strip():
        raise ToolExecutionError("Missing name")
    limit = payload.get("limit", 50)
    if not isinstance(limit, int):
        raise ToolExecutionError("limit must be an integer")
    include_expired = bool(payload.get("include_expired", False))
    try:
        entries = _memory_client().read(
            name=name.strip(),
            scope=payload.get("scope") if isinstance(payload.get("scope"), str) else None,
            key=payload.get("key") if isinstance(payload.get("key"), str) else None,
            job_id=payload.get("job_id") if isinstance(payload.get("job_id"), str) else None,
            user_id=payload.get("user_id") if isinstance(payload.get("user_id"), str) else None,
            project_id=payload.get("project_id")
            if isinstance(payload.get("project_id"), str)
            else None,
            limit=max(1, min(limit, 200)),
            include_expired=include_expired,
        )
    except MemoryClientError as exc:
        raise ToolExecutionError(f"memory_read_failed:{exc}") from exc
    first = entries[0] if entries else None
    output: Dict[str, Any] = {"entries": entries, "count": len(entries)}
    if isinstance(first, dict):
        output["entry"] = first
        payload_obj = first.get("payload")
        if isinstance(payload_obj, dict):
            output["payload"] = payload_obj
    return output


def _memory_write(payload: Dict[str, Any]) -> Dict[str, Any]:
    name = payload.get("name")
    if not isinstance(name, str) or not name.strip():
        raise ToolExecutionError("Missing name")
    entry_payload = payload.get("payload")
    if not isinstance(entry_payload, dict):
        raise ToolExecutionError("payload must be an object")

    request: Dict[str, Any] = {"name": name.strip(), "payload": entry_payload}
    for field in ("scope", "key", "job_id", "user_id", "project_id"):
        value = payload.get(field)
        if isinstance(value, str) and value.strip():
            request[field] = value.strip()
    ttl_seconds = payload.get("ttl_seconds")
    if ttl_seconds is not None:
        if not isinstance(ttl_seconds, int) or ttl_seconds <= 0:
            raise ToolExecutionError("ttl_seconds must be a positive integer")
        request["ttl_seconds"] = ttl_seconds
    metadata = payload.get("metadata")
    if metadata is not None:
        if not isinstance(metadata, dict):
            raise ToolExecutionError("metadata must be an object")
        request["metadata"] = metadata
    try:
        written = _memory_client().write(request)
    except MemoryClientError as exc:
        raise ToolExecutionError(f"memory_write_failed:{exc}") from exc
    if not isinstance(written, dict):
        raise ToolExecutionError("memory_write_failed:empty_response")
    return {"entry": written}


def _memory_semantic_write(payload: Dict[str, Any]) -> Dict[str, Any]:
    fact = payload.get("fact")
    if not isinstance(fact, str) or not fact.strip():
        raise ToolExecutionError("fact is required")
    request: Dict[str, Any] = {"fact": fact.strip()}
    for field in ("subject", "namespace", "source", "source_ref", "reasoning", "key", "user_id"):
        value = payload.get(field)
        if isinstance(value, str) and value.strip():
            request[field] = value.strip()
    for list_field in ("aliases", "keywords"):
        value = payload.get(list_field)
        if value is None:
            continue
        if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
            raise ToolExecutionError(f"{list_field} must be an array of strings")
        request[list_field] = [item.strip() for item in value if item.strip()]
    confidence = payload.get("confidence")
    if confidence is not None:
        if not isinstance(confidence, (int, float)):
            raise ToolExecutionError("confidence must be a number between 0 and 1")
        confidence_f = float(confidence)
        if confidence_f < 0 or confidence_f > 1:
            raise ToolExecutionError("confidence must be a number between 0 and 1")
        request["confidence"] = confidence_f
    metadata = payload.get("metadata")
    if metadata is not None:
        if not isinstance(metadata, dict):
            raise ToolExecutionError("metadata must be an object")
        request["metadata"] = metadata
    try:
        written = _memory_client().semantic_write(request)
    except MemoryClientError as exc:
        raise ToolExecutionError(f"memory_semantic_write_failed:{exc}") from exc
    if not isinstance(written, dict):
        raise ToolExecutionError("memory_semantic_write_failed:empty_response")
    return written


def _memory_semantic_search(payload: Dict[str, Any]) -> Dict[str, Any]:
    query = payload.get("query")
    if not isinstance(query, str) or not query.strip():
        raise ToolExecutionError("query is required")
    request: Dict[str, Any] = {"query": query.strip()}
    for field in ("namespace", "subject", "key", "user_id"):
        value = payload.get(field)
        if isinstance(value, str) and value.strip():
            request[field] = value.strip()
    limit = payload.get("limit")
    if limit is not None:
        if not isinstance(limit, int):
            raise ToolExecutionError("limit must be an integer")
        request["limit"] = max(1, min(limit, 50))
    min_score = payload.get("min_score")
    if min_score is not None:
        if not isinstance(min_score, (int, float)):
            raise ToolExecutionError("min_score must be a number")
        request["min_score"] = max(0.0, float(min_score))
    include_payload = payload.get("include_payload")
    if include_payload is not None:
        request["include_payload"] = bool(include_payload)
    try:
        result = _memory_client().semantic_search(request)
    except MemoryClientError as exc:
        raise ToolExecutionError(f"memory_semantic_search_failed:{exc}") from exc
    if not isinstance(result, dict):
        raise ToolExecutionError("memory_semantic_search_failed:empty_response")
    return result


def _resolve_template_path(template_path: str, template_id: str) -> Path:
    base_dir = Path(os.getenv("DOCX_TEMPLATE_DIR", "/shared/templates"))
    base_dir.mkdir(parents=True, exist_ok=True)
    candidate = Path(template_path or "")
    if not template_path:
        candidate = Path(f"{template_id}.docx")
    if candidate.is_absolute():
        resolved = candidate.resolve()
    else:
        resolved = (base_dir / candidate).resolve()
    if not str(resolved).startswith(str(base_dir.resolve())):
        raise ToolExecutionError("Invalid template path outside template directory")
    return resolved


def _docx_render(payload: Dict[str, Any]) -> Dict[str, Any]:
    try:
        from docxtpl import DocxTemplate
    except Exception as exc:  # noqa: BLE001
        raise ToolExecutionError("docxtpl is not installed") from exc
    data = payload.get("data")
    if not isinstance(data, dict):
        raise ToolExecutionError("data must be an object")
    schema_ref = payload.get("schema_ref", "")
    template_id = payload.get("template_id", "")
    template_path = payload.get("template_path", "")
    output_path = payload.get("output_path", "")
    if not output_path:
        raise ToolExecutionError("Missing output_path")
    if not schema_ref and template_id:
        schema_ref = template_id
    if schema_ref:
        _validate_schema_from_registry(schema_ref, data)
    if not template_id and not template_path:
        raise ToolExecutionError("Missing template_id or template_path")
    template_file = _resolve_template_path(template_path, template_id)
    if not template_file.exists():
        raise ToolExecutionError("DOCX template not found")
    candidate = _safe_artifact_path(output_path, f"docx_{template_id or 'output'}.docx")
    candidate.parent.mkdir(parents=True, exist_ok=True)
    doc = DocxTemplate(str(template_file))
    doc.render(data)
    doc.save(str(candidate))
    return {"path": str(candidate)}


def _http_fetch(payload: Dict[str, Any]) -> Dict[str, Any]:
    import urllib.request

    url = payload.get("url", "")
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        raise ToolExecutionError("Unsupported URL scheme")
    host = parsed.hostname or ""
    allowlist = _parse_http_allowlist()
    if not _host_allowed(host, allowlist):
        raise ToolExecutionError("URL host not in allowlist")
    with urllib.request.urlopen(url, timeout=5) as response:
        body = response.read().decode("utf-8")
    return {"body": body}


def _post_json(url: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    return coder_tools.post_json(url, payload, timeout_s=_resolve_coder_http_timeout_s())


def _post_mcp_tool_call(
    service_url: str,
    tool_name: str,
    arguments: Dict[str, Any],
) -> Dict[str, Any]:
    return mcp_client.post_mcp_tool_call(
        service_url,
        tool_name,
        arguments,
        call_mcp_tool_sdk=_call_mcp_tool_sdk,
        classify_tool_error=_classify_tool_error,
        logger=LOGGER,
        tracing_module=core_tracing,
    )


def _call_mcp_tool_sdk(
    mcp_url: str,
    tool_name: str,
    arguments: Dict[str, Any],
    timeout_s: float,
    headers: Dict[str, str] | None = None,
) -> Dict[str, Any]:
    return mcp_client.call_mcp_tool_sdk(
        mcp_url,
        tool_name,
        arguments,
        timeout_s,
        headers=headers,
        tracing_module=core_tracing,
        logger=LOGGER,
    )


def _call_mcp_tool_sdk_inproc(
    mcp_url: str,
    tool_name: str,
    arguments: Dict[str, Any],
    timeout_s: float,
    headers: Dict[str, str] | None = None,
) -> Dict[str, Any]:
    return mcp_client.call_mcp_tool_sdk_inproc(
        mcp_url,
        tool_name,
        arguments,
        timeout_s,
        headers=headers,
        tracing_module=core_tracing,
    )


def _mcp_process_entry(
    queue: Any,
    mcp_url: str,
    tool_name: str,
    arguments: Dict[str, Any],
    timeout_s: float,
    headers: Dict[str, str] | None = None,
) -> None:
    mcp_client.mcp_process_entry(
        queue,
        mcp_url,
        tool_name,
        arguments,
        timeout_s,
        headers,
    )


def _call_mcp_tool_sdk_process(
    mcp_url: str,
    tool_name: str,
    arguments: Dict[str, Any],
    timeout_s: float,
    headers: Dict[str, str] | None = None,
) -> Dict[str, Any]:
    return mcp_client.call_mcp_tool_sdk_process(
        mcp_url,
        tool_name,
        arguments,
        timeout_s,
        headers=headers,
        logger=LOGGER,
        tracing_module=core_tracing,
    )


def _flatten_exception_messages(exc: BaseException) -> List[str]:
    return mcp_client.flatten_exception_messages(exc)


def _extract_mcp_sdk_result(result: Any) -> Dict[str, Any]:
    return mcp_client.extract_mcp_sdk_result(result)


def _normalize_mcp_structured_result(structured: Dict[str, Any]) -> Dict[str, Any]:
    return mcp_client.normalize_mcp_structured_result(structured)


def _extract_mcp_error_detail(result: Any) -> str:
    return mcp_client.extract_mcp_error_detail(result)


def _coding_agent_generate(payload: Dict[str, Any]) -> Dict[str, Any]:
    return coder_tools.coding_agent_generate(
        payload,
        post_mcp_tool_call=_post_mcp_tool_call,
        write_workspace_text_file=_write_workspace_text_file,
    )


def _build_plan_prompt(goal: str, constraints: Optional[str], max_steps: int) -> str:
    return coder_tools.build_plan_prompt(goal, constraints, max_steps)


def _render_plan_markdown(goal: str, steps: list[dict[str, Any]], statuses: list[bool]) -> str:
    return coder_tools.render_plan_markdown(goal, steps, statuses)


def _coding_agent_autonomous(payload: Dict[str, Any], provider: LLMProvider) -> Dict[str, Any]:
    return coder_tools.coding_agent_autonomous(
        payload,
        provider,
        post_mcp_tool_call=_post_mcp_tool_call,
        write_workspace_text_file=_write_workspace_text_file,
    )


def _agent(payload: Dict[str, Any], provider: LLMProvider, _recursion_depth: int = 0) -> Dict[str, Any]:
    def _execute_tool(tool_name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        # Intercept recursive agent calls: dispatch as an independent job when
        # API_URL is available (true process isolation); fall back to in-process
        # recursion in dev/test environments where API_URL is not set.
        if tool_name == "agent" or tool_name == "agent__run":
            api_url = sub_agent_dispatch.get_api_url()
            if api_url:
                return sub_agent_dispatch.dispatch_sub_agent(arguments, api_url=api_url)
            return _agent(arguments, provider, _recursion_depth=_recursion_depth + 1)
        reg = default_registry(
            http_fetch_enabled=True,
            llm_enabled=True,
            llm_provider=provider,
        )
        tool = reg.get(tool_name)
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


def _coding_agent_publish_pr(payload: Dict[str, Any]) -> Dict[str, Any]:
    return coder_tools.coding_agent_publish_pr(
        payload,
        safe_workspace_path=_safe_workspace_path,
        invoke_capability=mcp_gateway.invoke_capability,
    )


def _llm_generate(payload: Dict[str, Any], provider: LLMProvider) -> Dict[str, Any]:
    prompt = payload.get("text") or payload.get("prompt") or ""
    meta: Dict[str, Any] = {
        "component": "tools",
        "tool": "llm_generate",
        "operation": "generate_text",
        "prompt_len": len(prompt),
    }
    job_id = payload.get("job_id")
    if job_id:
        meta["job_id"] = job_id
    response = provider.generate_request(LLMRequest(prompt=prompt, metadata=meta))
    return {
        "text": response.content,
        "usage": {
            "prompt_tokens": response.input_tokens,
            "completion_tokens": response.output_tokens,
            "cached_tokens": response.cached_input_tokens,
            "cache_write_tokens": response.cache_creation_tokens,
        },
    }


def _llm_generate_document_spec(payload: Dict[str, Any], provider: LLMProvider) -> Dict[str, Any]:
    return _llm_generate_document_spec_external(
        payload,
        provider,
        sanitize_document_spec=_sanitize_document_spec,
    )


def _sanitize_document_spec(document_spec: Dict[str, Any]) -> Dict[str, Any]:
    sanitized = dict(document_spec)
    blocks = sanitized.get("blocks")
    if isinstance(blocks, list):
        sanitized["blocks"] = _sanitize_document_blocks(blocks)
    return sanitized


def _sanitize_document_blocks(blocks: List[Any]) -> List[Dict[str, Any]]:
    cleaned: List[Dict[str, Any]] = []
    for raw in blocks:
        if not isinstance(raw, dict):
            continue
        block = dict(raw)
        block_type = block.get("type")

        if block_type == "spacer":
            # Spacer maps to an empty paragraph in DOCX; skip to avoid blank lines.
            continue

        if block_type in {"text", "paragraph", "heading", "optional_paragraph"}:
            text = block.get("text")
            if isinstance(text, str) and not text.strip():
                continue

        if block_type == "bullets":
            items = block.get("items")
            if isinstance(items, list):
                filtered_items = []
                for item in items:
                    if isinstance(item, str) and not item.strip():
                        continue
                    filtered_items.append(item)
                if not filtered_items:
                    continue
                block["items"] = filtered_items

        if block_type == "repeat":
            template = block.get("template")
            if isinstance(template, list):
                cleaned_template = _sanitize_document_blocks(template)
                if not cleaned_template:
                    continue
                block["template"] = cleaned_template

        cleaned.append(block)
    return cleaned


def _resolve_llm_iterative_tool_timeout_s(provider: Optional[LLMProvider]) -> int:
    base = _resolve_llm_timeout_s(provider)
    return min(900, max(60, base * 3))


def _llm_improve_document_spec(payload: Dict[str, Any], provider: LLMProvider) -> Dict[str, Any]:
    return _llm_improve_document_spec_external(
        payload,
        provider,
        sanitize_document_spec=_sanitize_document_spec,
    )
