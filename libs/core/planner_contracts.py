from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from libs.core import capability_registry, intent_contract, models, workflow_contracts


class PlanRequestCapabilityAdapter(BaseModel):
    model_config = ConfigDict(extra="allow")

    type: str
    server_id: str | None = None
    tool_name: str | None = None


class PlanRequestCapability(BaseModel):
    model_config = ConfigDict(extra="allow")

    capability_id: str
    description: str = ""
    risk_tier: str = "low"
    idempotency: str = "unknown"
    group: str | None = None
    subgroup: str | None = None
    input_schema_ref: str | None = None
    output_schema_ref: str | None = None
    planner_hints: dict[str, Any] = Field(default_factory=dict)
    adapters: list[PlanRequestCapabilityAdapter] = Field(default_factory=list)


class PlanRequest(BaseModel):
    model_config = ConfigDict(extra="allow")

    job_id: str
    goal: str
    job_context: dict[str, Any] = Field(default_factory=dict)
    job_metadata: dict[str, Any] = Field(default_factory=dict)
    job_payload: dict[str, Any] = Field(default_factory=dict)
    tools: list[models.ToolSpec] = Field(default_factory=list)
    capabilities: list[PlanRequestCapability] = Field(default_factory=list)
    goal_intent_graph: workflow_contracts.IntentGraph | None = None
    semantic_capability_hints: list[dict[str, Any]] = Field(default_factory=list)
    max_dependency_depth: int | None = None


def build_plan_request(
    job: models.Job,
    *,
    tools: Sequence[models.ToolSpec],
    capabilities: Mapping[str, capability_registry.CapabilitySpec]
    | Sequence[capability_registry.CapabilitySpec]
    | None = None,
    semantic_capability_hints: Sequence[Mapping[str, Any]] | None = None,
    max_dependency_depth: int | None = None,
) -> PlanRequest:
    capability_values: Sequence[capability_registry.CapabilitySpec]
    if isinstance(capabilities, Mapping):
        capability_values = list(capabilities.values())
    elif capabilities is None:
        capability_values = []
    else:
        capability_values = list(capabilities)
    job_metadata = job.metadata if isinstance(job.metadata, dict) else {}
    goal_intent_graph = workflow_contracts.parse_intent_graph(job_metadata.get("goal_intent_graph"))
    return PlanRequest(
        job_id=job.id,
        goal=job.goal,
        job_context=job.context_json if isinstance(job.context_json, dict) else {},
        job_metadata=dict(job_metadata),
        job_payload=job.model_dump(mode="json"),
        tools=list(tools),
        capabilities=[
            PlanRequestCapability(
                capability_id=spec.capability_id,
                description=spec.description,
                risk_tier=spec.risk_tier,
                idempotency=spec.idempotency,
                group=spec.group,
                subgroup=spec.subgroup,
                input_schema_ref=spec.input_schema_ref,
                output_schema_ref=spec.output_schema_ref,
                planner_hints=(
                    dict(spec.planner_hints) if isinstance(spec.planner_hints, dict) else {}
                ),
                adapters=[
                    PlanRequestCapabilityAdapter(
                        type=adapter.type,
                        server_id=adapter.server_id,
                        tool_name=adapter.tool_name,
                    )
                    for adapter in spec.adapters
                    if adapter.enabled
                ],
            )
            for spec in capability_values
        ],
        goal_intent_graph=goal_intent_graph,
        semantic_capability_hints=[
            dict(item) for item in semantic_capability_hints or [] if isinstance(item, Mapping)
        ],
        max_dependency_depth=max_dependency_depth,
    )


def capability_map(request: PlanRequest) -> dict[str, PlanRequestCapability]:
    return {capability.capability_id: capability for capability in request.capabilities}


def goal_intent_sequence(request: PlanRequest) -> list[str]:
    graph = request.goal_intent_graph
    if graph is None:
        return []
    sequence: list[str] = []
    for segment in graph.segments:
        normalized = intent_contract.normalize_task_intent(segment.intent)
        if normalized:
            sequence.append(normalized)
    return sequence


def goal_intent_segments(request: PlanRequest) -> list[dict[str, Any]]:
    graph = request.goal_intent_graph
    if graph is None:
        return []
    return [segment.model_dump(mode="json", exclude_none=True) for segment in graph.segments]


def intent_mismatch_recovery(request: PlanRequest) -> dict[str, Any] | None:
    raw = request.job_metadata.get("intent_mismatch_recovery")
    if not isinstance(raw, dict):
        return None
    return dict(raw)


def governance_context(request: PlanRequest) -> dict[str, Any]:
    metadata = request.job_metadata if isinstance(request.job_metadata, dict) else {}
    return {
        "job_id": request.job_id,
        "job_type": metadata.get("job_type"),
        "tenant_id": metadata.get("tenant_id"),
        "org_id": metadata.get("org_id"),
        "job_context": request.job_context if isinstance(request.job_context, dict) else {},
    }
