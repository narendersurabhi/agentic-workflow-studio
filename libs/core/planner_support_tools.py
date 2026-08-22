from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping, Sequence

from pydantic import BaseModel, ConfigDict, Field

from libs.core import (
    capability_registry,
    capability_search,
    memory_registry,
    models,
    run_specs,
)


class SearchCapabilitiesInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    query: str = Field(description="Search query for capability catalog")
    intent_hint: str | None = None
    limit: int | None = Field(default=None, ge=1, le=25)


class SearchCapabilitiesOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    matches: list[dict[str, Any]]


class GetCapabilityContractInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    capability_id: str = Field(description="The capability ID to inspect")


class GetCapabilityContractOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    contract: dict[str, Any]


class GetSchemaInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_ref: str = Field(description="Schema reference (path or ID) to load")


class GetSchemaOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema: dict[str, Any]
    summary: dict[str, Any]


class GetWorkflowHintsInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    goal: str = Field(description="The planning goal to get workflow hints for")
    limit: int | None = Field(default=None, ge=1, le=25)


class GetWorkflowHintsOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    hints: list[dict[str, Any]]


class GetMemoryHintsInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    goal: str = Field(description="The planning goal to get memory hints for")
    user_id: str | None = None
    limit: int | None = Field(default=None, ge=1, le=25)


class GetMemoryHintsOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    hints: list[dict[str, Any]]


class FinalizeRunSpecInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    plan: dict[str, Any] = Field(description="Capability-first PlanCreate candidate to compile")


class FinalizeRunSpecOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ok: bool
    run_spec: dict[str, Any] | None = None
    error: str | None = None


def build_planner_support_tool_specs() -> list[models.ToolSpec]:
    return [
        models.ToolSpec(
            name="search_capabilities",
            description="Search the allowed capability catalog for relevant capability IDs.",
            input_schema=SearchCapabilitiesInput.model_json_schema(),
            output_schema=SearchCapabilitiesOutput.model_json_schema(),
            usage_guidance=(
                "Planner-only metadata tool. Use it to narrow capability candidates. "
                "Do not emit this tool name in tasks."
            ),
            tool_intent=models.ToolIntent.io,
        ),
        models.ToolSpec(
            name="get_capability_contract",
            description="Inspect the contract, hints, and adapter summary for one capability.",
            input_schema=GetCapabilityContractInput.model_json_schema(),
            output_schema=GetCapabilityContractOutput.model_json_schema(),
            usage_guidance=(
                "Planner-only metadata tool. Use it to inspect required inputs and planner hints."
            ),
            tool_intent=models.ToolIntent.validate,
        ),
        models.ToolSpec(
            name="get_schema",
            description="Load a JSON schema and summarize its required fields.",
            input_schema=GetSchemaInput.model_json_schema(),
            output_schema=GetSchemaOutput.model_json_schema(),
            usage_guidance=(
                "Planner-only metadata tool. Use it to inspect input or output schema requirements."
            ),
            tool_intent=models.ToolIntent.validate,
        ),
        models.ToolSpec(
            name="get_workflow_hints",
            description="Return plan-shape hints from the normalized intent envelope and capability candidates.",
            input_schema=GetWorkflowHintsInput.model_json_schema(),
            output_schema=GetWorkflowHintsOutput.model_json_schema(),
            usage_guidance=(
                "Planner-only metadata tool. Use it for prior segment order, clarification, and candidate-capability hints."
            ),
            tool_intent=models.ToolIntent.io,
        ),
        models.ToolSpec(
            name="get_memory_hints",
            description="Return planner-readable memory sources and when to use them.",
            input_schema=GetMemoryHintsInput.model_json_schema(),
            output_schema=GetMemoryHintsOutput.model_json_schema(),
            usage_guidance=(
                "Planner-only metadata tool. Use it to decide which memory sources are relevant before planning."
            ),
            tool_intent=models.ToolIntent.io,
        ),
        models.ToolSpec(
            name="finalize_run_spec",
            description="Compile a capability-first PlanCreate candidate into a canonical RunSpec.",
            input_schema=FinalizeRunSpecInput.model_json_schema(),
            output_schema=FinalizeRunSpecOutput.model_json_schema(),
            usage_guidance=(
                "Planner-only metadata tool. Use it to validate a candidate plan shape before returning it."
            ),
            tool_intent=models.ToolIntent.validate,
        ),
    ]


def search_capabilities_support(
    *,
    query: str,
    capabilities: Mapping[str, capability_registry.CapabilitySpec],
    intent_hint: str | None = None,
    limit: int = 8,
) -> dict[str, Any]:
    entries = capability_search.build_capability_search_entries(capabilities)
    matches = capability_search.search_capabilities(
        query=query,
        capability_entries=entries,
        intent_hint=intent_hint,
        limit=limit,
        rerank_feedback_rows=[],
    )
    return {"matches": matches}


def get_capability_contract_support(
    *,
    capability_id: str,
    capabilities: Mapping[str, capability_registry.CapabilitySpec],
) -> dict[str, Any]:
    spec = capabilities.get(capability_id)
    if spec is None:
        return {"contract": {}, "error": f"capability_not_found:{capability_id}"}
    return {
        "contract": {
            "capability_id": spec.capability_id,
            "description": spec.description,
            "risk_tier": spec.risk_tier,
            "idempotency": spec.idempotency,
            "group": spec.group,
            "subgroup": spec.subgroup,
            "input_schema_ref": spec.input_schema_ref,
            "output_schema_ref": spec.output_schema_ref,
            "aliases": list(spec.aliases),
            "planner_hints": dict(spec.planner_hints or {}),
            "adapters": [
                {
                    "type": adapter.type,
                    "server_id": adapter.server_id,
                }
                for adapter in spec.adapters
                if adapter.enabled
            ],
        }
    }


def get_schema_support(
    *,
    schema_ref: str,
    schema_registry_path: str,
) -> dict[str, Any]:
    schema = _load_schema_from_ref(schema_ref, schema_registry_path=schema_registry_path)
    if schema is None:
        return {"schema": {}, "summary": {}, "error": f"schema_not_found:{schema_ref}"}
    required = [key for key in schema.get("required", []) if isinstance(key, str) and key.strip()]
    return {
        "schema": schema,
        "summary": {
            "type": schema.get("type"),
            "required_fields": required,
            "property_count": len(schema.get("properties", {}))
            if isinstance(schema.get("properties"), Mapping)
            else 0,
        },
    }


def get_workflow_hints_support(
    *,
    goal: str,
    request: Any,
    limit: int = 5,
) -> dict[str, Any]:
    del goal
    hints: list[dict[str, Any]] = []
    envelope = getattr(request, "normalized_intent_envelope", None)
    if envelope is not None:
        clarification = getattr(envelope, "clarification", None)
        if clarification is not None and clarification.missing_inputs:
            hints.append(
                {
                    "type": "clarification",
                    "missing_inputs": list(clarification.missing_inputs),
                    "blocking_slots": list(clarification.blocking_slots),
                }
            )
        graph = getattr(envelope, "graph", None)
        if graph is not None and graph.segments:
            hints.append(
                {
                    "type": "segment_order",
                    "segments": [
                        {
                            "id": segment.id,
                            "intent": segment.intent,
                            "objective": segment.objective,
                            "suggested_capabilities": list(segment.suggested_capabilities),
                        }
                        for segment in graph.segments[:limit]
                    ],
                }
            )
    semantic_hints = getattr(request, "semantic_capability_hints", None)
    if isinstance(semantic_hints, Sequence) and semantic_hints:
        hints.append({"type": "semantic_capability_hints", "items": list(semantic_hints[:limit])})
    return {"hints": hints[:limit]}


def get_memory_hints_support(
    *,
    goal: str,
    user_id: str | None = None,
    limit: int = 5,
) -> dict[str, Any]:
    del goal
    registry = memory_registry.default_memory_registry()
    hints: list[dict[str, Any]] = []
    for spec in registry.list():
        if "planner" not in spec.read_roles:
            continue
        if spec.name not in {
            "interaction_summaries_compact",
            "user_profile",
            "semantic_memory",
            "project_preferences",
            "global_reference",
        }:
            continue
        hints.append(
            {
                "memory_name": spec.name,
                "scope": spec.scope.value,
                "description": spec.description,
                "user_scoped": spec.scope in {models.MemoryScope.user, models.MemoryScope.project},
                "requires_user_id": bool(user_id)
                if spec.scope == models.MemoryScope.user
                else False,
            }
        )
    return {"hints": hints[:limit]}


def finalize_run_spec_support(
    *,
    plan: Mapping[str, Any] | models.PlanCreate,
    metadata: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    try:
        candidate = (
            plan if isinstance(plan, models.PlanCreate) else models.PlanCreate.model_validate(plan)
        )
        compiled = run_specs.plan_to_run_spec(
            candidate,
            kind=models.RunKind.planner,
            metadata=metadata,
        )
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc)}
    return {"ok": True, "run_spec": compiled.model_dump(mode="json")}


def _load_schema_from_ref(schema_ref: str, *, schema_registry_path: str) -> dict[str, Any] | None:
    candidate = Path(schema_ref)
    if not candidate.is_absolute():
        candidate = Path(schema_registry_path) / (
            schema_ref if schema_ref.endswith(".json") else f"{schema_ref}.json"
        )
    if not candidate.exists():
        return None
    try:
        parsed = json.loads(candidate.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return None
    return parsed if isinstance(parsed, dict) else None
