"""Backward-compatible re-export shim.

The tool-registry assembly logic (catalog wiring, plugin loading, governance
filtering) moved to libs/tool_manager/registry.py as part of the harness/MCP/
tool-manager/memory layering. This module re-exports its public names so the
many existing `from libs.core import tool_registry` call sites across the
services keep working unchanged.
"""

from __future__ import annotations

from libs.tool_manager import tool_governance, tool_plugins
from libs.tool_manager.registry import (
    Tool,
    ToolAllowDecision,
    ToolCatalogHandlers,
    ToolPluginLoadError,
    build_default_registry,
    build_planner_support_tool_specs,
    build_tool_registry,
    default_registry,
    register_default_tools,
)

__all__ = [
    "Tool",
    "ToolAllowDecision",
    "ToolCatalogHandlers",
    "ToolPluginLoadError",
    "build_default_registry",
    "build_planner_support_tool_specs",
    "build_tool_registry",
    "default_registry",
    "register_default_tools",
    "tool_governance",
    "tool_plugins",
]
