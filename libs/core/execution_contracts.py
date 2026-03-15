from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from libs.core import intent_contract, workflow_contracts


class CapabilityBinding(BaseModel):
    model_config = ConfigDict(extra="allow")

    request_id: str
    capability_id: str | None = None
    tool_name: str | None = None
    adapter_type: str | None = None
    server_id: str | None = None


class TaskExecutionStep(BaseModel):
    model_config = ConfigDict(extra="allow")

    request_id: str
    resolved_inputs: dict[str, Any] = Field(default_factory=dict)
    capability_binding: CapabilityBinding | None = None


class TaskExecutionRequest(BaseModel):
    model_config = ConfigDict(extra="allow")

    task_id: str = ""
    job_id: str = ""
    run_id: str = ""
    trace_id: str = ""
    name: str = ""
    description: str = ""
    instruction: str = ""
    context: dict[str, Any] = Field(default_factory=dict)
    attempts: int = 1
    max_attempts: int = 1
    intent: str | None = None
    intent_source: str | None = None
    intent_confidence: float | None = None
    intent_segment: workflow_contracts.IntentGraphSegment | None = None
    dependency_artifacts: dict[str, Any] = Field(default_factory=dict)
    retry_policy: str | None = None
    source_payload: dict[str, Any] = Field(default_factory=dict, exclude=True)
    requests: list[TaskExecutionStep] = Field(default_factory=list)

    @property
    def tool_requests(self) -> list[str]:
        return [request.request_id for request in self.requests]

    @property
    def tool_inputs(self) -> dict[str, dict[str, Any]]:
        return {
            request.request_id: dict(request.resolved_inputs)
            for request in self.requests
        }


def build_task_execution_request(
    value: Mapping[str, Any] | TaskExecutionRequest | None,
    *,
    default_max_attempts: int = 1,
) -> TaskExecutionRequest:
    if isinstance(value, TaskExecutionRequest):
        return value
    payload = dict(value) if isinstance(value, Mapping) else {}
    trace_id = _string_value(payload.get("correlation_id"))
    run_id = _string_value(payload.get("run_id")) or trace_id
    request_ids = _request_ids(payload.get("tool_requests"))
    tool_inputs = _tool_inputs(payload.get("tool_inputs"))
    attempts = _attempt_count(payload.get("attempts"))
    max_attempts = max(
        attempts,
        _max_attempts(payload.get("max_attempts"), default_max_attempts),
    )
    bindings = _binding_index(
        payload.get("capability_bindings") or payload.get("execution_bindings")
    )
    return TaskExecutionRequest(
        task_id=_string_value(payload.get("task_id")),
        job_id=_string_value(payload.get("job_id")),
        run_id=run_id,
        trace_id=trace_id,
        name=_string_value(payload.get("name")),
        description=_string_value(payload.get("description")),
        instruction=_string_value(payload.get("instruction")),
        context=dict(payload.get("context")) if isinstance(payload.get("context"), Mapping) else {},
        attempts=attempts,
        max_attempts=max_attempts,
        intent=_normalized_intent(payload),
        intent_source=_string_value(payload.get("intent_source")) or None,
        intent_confidence=_intent_confidence(payload.get("intent_confidence")),
        intent_segment=_intent_segment(payload),
        dependency_artifacts=(
            dict(payload.get("dependency_artifacts"))
            if isinstance(payload.get("dependency_artifacts"), Mapping)
            else {}
        ),
        retry_policy=_string_value(payload.get("retry_policy")) or None,
        source_payload=payload,
        requests=[
            TaskExecutionStep(
                request_id=request_id,
                resolved_inputs=dict(tool_inputs.get(request_id) or {}),
                capability_binding=bindings.get(request_id),
            )
            for request_id in request_ids
        ],
    )


def _string_value(value: Any) -> str:
    if isinstance(value, str):
        return value.strip()
    return ""


def _request_ids(value: Any) -> list[str]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        return []
    request_ids: list[str] = []
    for item in value:
        normalized = _string_value(item)
        if normalized:
            request_ids.append(normalized)
    return request_ids


def _tool_inputs(value: Any) -> dict[str, dict[str, Any]]:
    if not isinstance(value, Mapping):
        return {}
    normalized: dict[str, dict[str, Any]] = {}
    for request_id, payload in value.items():
        key = _string_value(request_id)
        if not key:
            continue
        normalized[key] = dict(payload) if isinstance(payload, Mapping) else {}
    return normalized


def _attempt_count(value: Any) -> int:
    return max(1, _int_or_default(value, 1))


def _max_attempts(value: Any, default_max_attempts: int) -> int:
    fallback = max(1, default_max_attempts)
    if value is None:
        return fallback
    return max(1, _int_or_default(value, fallback))


def _int_or_default(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _normalized_intent(payload: Mapping[str, Any]) -> str | None:
    return intent_contract.normalize_task_intent(
        payload.get("intent")
    ) or intent_contract.normalize_task_intent(payload.get("task_intent"))


def _intent_confidence(value: Any) -> float | None:
    if not isinstance(value, (int, float)):
        return None
    return max(0.0, min(1.0, float(value)))


def _intent_segment(payload: Mapping[str, Any]) -> workflow_contracts.IntentGraphSegment | None:
    segment = payload.get("intent_segment")
    if not isinstance(segment, Mapping):
        profile = payload.get("intent_profile")
        if isinstance(profile, Mapping):
            candidate = profile.get("segment")
            segment = candidate if isinstance(candidate, Mapping) else None
    if not isinstance(segment, Mapping):
        return None
    try:
        return workflow_contracts.IntentGraphSegment.model_validate(segment)
    except ValidationError:
        return None


def _binding_index(value: Any) -> dict[str, CapabilityBinding]:
    index: dict[str, CapabilityBinding] = {}
    if isinstance(value, Mapping):
        for request_id, binding_payload in value.items():
            if not isinstance(binding_payload, Mapping):
                continue
            binding = _binding_from_mapping(binding_payload, fallback_request_id=_string_value(request_id))
            if binding is not None:
                index[binding.request_id] = binding
        return index
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        for binding_payload in value:
            if not isinstance(binding_payload, Mapping):
                continue
            binding = _binding_from_mapping(binding_payload)
            if binding is not None:
                index[binding.request_id] = binding
    return index


def _binding_from_mapping(
    value: Mapping[str, Any],
    *,
    fallback_request_id: str = "",
) -> CapabilityBinding | None:
    request_id = _string_value(value.get("request_id")) or fallback_request_id
    if not request_id:
        return None
    return CapabilityBinding(
        request_id=request_id,
        capability_id=_string_value(value.get("capability_id")) or None,
        tool_name=_string_value(value.get("tool_name")) or None,
        adapter_type=(
            _string_value(value.get("adapter_type"))
            or _string_value(value.get("type"))
            or None
        ),
        server_id=_string_value(value.get("server_id")) or None,
    )
