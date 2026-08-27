from __future__ import annotations

from dataclasses import dataclass, field

SCHEMA_VERSION = "runtime-manifest.v1"


@dataclass(frozen=True)
class RuntimeCapabilityStatus:
    capability_id: str
    available: bool
    reason: str = ""
    details: tuple[str, ...] = ()
    adapter_types: tuple[str, ...] = ()


@dataclass(frozen=True)
class RuntimeManifest:
    service_name: str
    capability_mode: str
    schema_version: str = SCHEMA_VERSION
    runtime_version: str = "phase0"
    capabilities: dict[str, RuntimeCapabilityStatus] = field(default_factory=dict)
    build_errors: tuple[str, ...] = ()


# build_runtime_manifest(), explain_capability_unavailability(),
# _adapter_conformance_errors(), and _build_tool_registry_for_service() were removed
# with the tools framework — they existed solely to orchestrate the capability
# registry, MCP server registry, and worker ToolRegistry to compute per-capability
# availability.
