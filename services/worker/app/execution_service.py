from __future__ import annotations

import os
import time
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Callable

from libs.core import (
    execution_contracts,
    intent_contract,
    logging as core_logging,
    models,
    tracing as core_tracing,
)
from libs.harness import agent_cancel


@dataclass(frozen=True)
class WorkerExecutionConfig:
    llm_provider_name: str
    openai_model: str
    active_model_name: str  # resolved model name for the active provider
    prompt_version: str
    policy_version: str
    tool_version: str
    output_size_cap: int


@dataclass(frozen=True)
class WorkerExecutionContext:
    tool_runtime: Any
    capability_runtime: Any
    logger: Any
    config: WorkerExecutionConfig


@dataclass(frozen=True)
class WorkerExecutionCallbacks:
    task_intent_inference: Callable[
        [execution_contracts.TaskExecutionRequest],
        intent_contract.TaskIntentInference,
    ]
    intent_segment: Callable[
        [execution_contracts.TaskExecutionRequest],
        Mapping[str, Any] | None,
    ]
    capability_intent_mismatch: Callable[
        [str, Any],
        str | None,
    ]
    enforce_capability_input_contract: Callable[
        [Any, dict[str, Any]],
        tuple[dict[str, Any], str | None, list[str]],
    ]
    build_tool_payload: Callable[
        [str, str, dict[str, Any], dict[str, Any], dict[str, dict[str, Any]]],
        dict[str, Any],
    ]
    intent_mismatch: Callable[[str, models.ToolIntent, str], str | None]
    load_memory_inputs: Callable[[Any, dict[str, Any], str], dict[str, Any]]
    apply_memory_defaults: Callable[[str, dict[str, Any]], dict[str, Any]]
    missing_memory_only_inputs: Callable[[str, dict[str, Any]], list[str]]
    persist_memory_outputs: Callable[[Any, dict[str, Any], models.ToolCall, str], None]
    sync_output_artifact: Callable[[Mapping[str, Any], str | None, str, str], None]
    auto_persist_semantic_facts: Callable[..., None]
    validate_expected_output: Callable[[dict[str, Any], dict[str, Any]], str | None]
    build_task_run_scorecard: Callable[..., dict[str, Any]]


def execute_task_request(
    request: execution_contracts.TaskExecutionRequest,
    *,
    context: WorkerExecutionContext,
    callbacks: WorkerExecutionCallbacks,
) -> models.TaskResult:
    task_payload = dict(request.source_payload)
    task_id = request.task_id
    trace_id = request.trace_id
    run_id = request.run_id or trace_id or str(uuid.uuid4())
    job_id = request.job_id
    tool_requests = request.tool_requests
    task_intent_inference = callbacks.task_intent_inference(request)
    task_intent = task_intent_inference.intent
    task_intent_segment = callbacks.intent_segment(request)
    task_attempt = request.attempts
    task_max_attempts = max(request.max_attempts, request.attempts)
    started_at = datetime.now(UTC)
    outputs: dict[str, Any] = {}
    tool_calls: list[models.ToolCall] = []
    artifacts: list[dict[str, Any]] = []
    tool_error: str | None = None

    core_logging.log_event(
        context.logger,
        "task_intent_inferred",
        {
            "run_id": run_id,
            "job_id": job_id,
            "task_id": task_id,
            "task_intent": task_intent,
            "intent_source": task_intent_inference.source,
            "intent_confidence": round(float(task_intent_inference.confidence), 3),
            "trace_id": trace_id,
        },
    )
    with core_tracing.start_span(
        "worker.execute_task",
        attributes={
            "task.id": str(task_id or ""),
            "job.id": job_id,
            "trace.id": trace_id,
            "run.id": run_id,
            "task.tool_request_count": len(tool_requests),
            "task.intent": task_intent,
            "task.intent_source": task_intent_inference.source,
            "task.intent_confidence": float(task_intent_inference.confidence),
            "task.attempt": task_attempt,
            "task.max_attempts": task_max_attempts,
            "model.provider": context.config.llm_provider_name,
            "model.name": context.config.active_model_name,
            "prompt.version": context.config.prompt_version,
            "policy.version": context.config.policy_version,
            "tool.version": context.config.tool_version,
        },
    ) as task_span:
        for tool_index, step in enumerate(request.requests):
            request_id = step.request_id
            gate_decision = _evaluate_execution_gate(step.execution_gate, request.context)
            if gate_decision is not None and not gate_decision["allowed"]:
                outputs[request_id] = {
                    "skipped": True,
                    "reason": gate_decision["reason"],
                    "expression": gate_decision["expression"],
                }
                continue
            binding = step.capability_binding
            native_execution_name = (
                binding.tool_name if binding and binding.tool_name else request_id
            )
            # Capability resolution (context.capability_runtime.resolve_enabled_capability)
            # and dispatch (_execute_capability_tool / _execute_native_tool) were removed
            # with the tools framework; this loop no longer executes a step against a
            # registry-backed tool/capability runtime.
            execution_name = native_execution_name
            with core_tracing.start_span(
                "worker.execute_tool",
                attributes={
                    "task.id": str(task_id or ""),
                    "job.id": job_id,
                    "trace.id": trace_id,
                    "run.id": run_id,
                    "tool.name": execution_name,
                    "tool.request_id": request_id,
                    "tool.sequence": tool_index + 1,
                    "task.attempt": task_attempt,
                    "task.max_attempts": task_max_attempts,
                    "model.provider": context.config.llm_provider_name,
                    "model.name": context.config.active_model_name,
                    "prompt.version": context.config.prompt_version,
                    "policy.version": context.config.policy_version,
                    "tool.version": context.config.tool_version,
                },
            ):
                tool_error = None
        finished_at = datetime.now(UTC)
        validation_error = callbacks.validate_expected_output(task_payload, outputs)
        status = (
            models.TaskStatus.failed
            if tool_error or validation_error
            else models.TaskStatus.completed
        )
        run_scorecard = callbacks.build_task_run_scorecard(
            run_id=run_id,
            trace_id=trace_id,
            job_id=job_id,
            task_id=str(task_id or ""),
            status=status,
            started_at=started_at,
            finished_at=finished_at,
            tool_calls=tool_calls,
            outputs=outputs,
            task_attempt=task_attempt,
            task_max_attempts=task_max_attempts,
            failure_error=validation_error or tool_error,
        )
        artifacts.append({"type": "run_scorecard", "summary": run_scorecard})
        core_logging.log_event(context.logger, "task_run_scorecard", run_scorecard)
        core_tracing.set_span_attributes(
            task_span,
            {
                "task.status": status.value,
                "task.error": validation_error or tool_error or "",
                "task.tool_calls": len(tool_calls),
                "task.total_latency_ms": run_scorecard.get("total_latency_ms", 0),
                "task.failure_stage": run_scorecard.get("failure_stage", ""),
            },
        )
        if tool_error:
            outputs["tool_error"] = {"error": tool_error}
        if validation_error:
            outputs["validation_error"] = {"error": validation_error}
        return models.TaskResult(
            task_id=task_id,
            status=status,
            outputs=outputs,
            artifacts=artifacts,
            tool_calls=tool_calls,
            started_at=started_at,
            finished_at=finished_at,
            error=validation_error or tool_error,
        )


def _evaluate_execution_gate(
    gate: Mapping[str, Any] | None,
    context: Mapping[str, Any] | None,
) -> dict[str, Any] | None:
    if not isinstance(gate, Mapping):
        return None
    expression = str(gate.get("expression") or "").strip()
    negate = bool(gate.get("negate"))
    if not expression:
        return None
    try:
        value = _evaluate_context_expression(expression, context or {})
    except Exception as exc:  # noqa: BLE001
        return {
            "allowed": False,
            "expression": expression,
            "reason": f"execution_gate_invalid:{exc}",
        }
    allowed = bool(value)
    if negate:
        allowed = not allowed
    return {
        "allowed": allowed,
        "expression": expression,
        "reason": "execution_gate_condition_false"
        if not negate
        else "execution_gate_condition_negated_false",
    }


_BINARY_OPERATORS = (">=", "<=", "!=", "==", ">", "<", " contains ", " startswith ", " endswith ")


def _split_logical(expression: str, keyword: str) -> list[str]:
    """Split on a logical keyword (' and ' / ' or ') outside of quoted strings."""
    parts: list[str] = []
    buf = ""
    quote: str | None = None
    i = 0
    length = len(expression)
    keyword_len = len(keyword)
    while i < length:
        ch = expression[i]
        if quote is not None:
            buf += ch
            if ch == quote:
                quote = None
            i += 1
            continue
        if ch in ("'", '"'):
            quote = ch
            buf += ch
            i += 1
            continue
        if expression[i : i + keyword_len].lower() == keyword:
            parts.append(buf)
            buf = ""
            i += keyword_len
            continue
        buf += ch
        i += 1
    parts.append(buf)
    return [part.strip() for part in parts if part.strip()]


def _evaluate_context_expression(expression: str, context: Mapping[str, Any]) -> Any:
    normalized = expression.strip()
    # OR has the lowest precedence; AND binds tighter than OR.
    or_parts = _split_logical(normalized, " or ")
    if len(or_parts) > 1:
        return any(bool(_evaluate_context_expression(part, context)) for part in or_parts)
    and_parts = _split_logical(normalized, " and ")
    if len(and_parts) > 1:
        return all(bool(_evaluate_context_expression(part, context)) for part in and_parts)
    return _evaluate_context_atom(normalized, context)


def _evaluate_context_atom(expression: str, context: Mapping[str, Any]) -> Any:
    normalized = expression.strip()
    for op in _BINARY_OPERATORS:
        if op not in normalized:
            continue
        left_raw, right_raw = normalized.split(op, 1)
        left_value = _resolve_context_operand(left_raw.strip(), context)
        right_value = _parse_expression_literal(right_raw.strip(), context)
        op_clean = op.strip()
        if op_clean == "==":
            return left_value == right_value
        if op_clean == "!=":
            return left_value != right_value
        if op_clean == "contains":
            return right_value in str(left_value) if left_value is not None else False
        if op_clean == "startswith":
            return str(left_value).startswith(str(right_value)) if left_value is not None else False
        if op_clean == "endswith":
            return str(left_value).endswith(str(right_value)) if left_value is not None else False
        try:
            left_num = float(left_value) if left_value is not None else 0.0
            right_num = float(right_value) if right_value is not None else 0.0
        except (TypeError, ValueError):
            return False
        if op_clean == ">":
            return left_num > right_num
        if op_clean == "<":
            return left_num < right_num
        if op_clean == ">=":
            return left_num >= right_num
        if op_clean == "<=":
            return left_num <= right_num
    return _resolve_context_operand(normalized, context)


def _resolve_context_operand(token: str, context: Mapping[str, Any]) -> Any:
    normalized = token.strip()
    if not normalized:
        return None
    if normalized.startswith("context."):
        base: Any = _gate_job_context(context)
        segments = normalized.split(".")[1:]
    elif normalized.startswith("workflow.input."):
        base = _gate_workflow_scope(context, "inputs")
        segments = normalized.split(".")[2:]
    elif normalized.startswith("workflow.variable."):
        base = _gate_workflow_scope(context, "variables")
        segments = normalized.split(".")[2:]
    elif normalized.startswith("step."):
        base = _gate_step_outputs(context)
        segments = normalized.split(".")[1:]  # [task_name, ...field_path]
    else:
        raise ValueError("unsupported_operand")
    value: Any = base
    for segment in segments:
        key = segment.strip()
        if not key:
            raise ValueError("empty_context_segment")
        if not isinstance(value, Mapping) or key not in value:
            return None
        value = value[key]
    return value


def _parse_expression_literal(token: str, context: Mapping[str, Any]) -> Any:
    normalized = token.strip()
    lowered = normalized.lower()
    if lowered == "true":
        return True
    if lowered == "false":
        return False
    if lowered == "null":
        return None
    if normalized.startswith(("context.", "workflow.input.", "workflow.variable.", "step.")):
        return _resolve_context_operand(normalized, context)
    if (
        normalized.startswith(("'", '"'))
        and normalized.endswith(("'", '"'))
        and len(normalized) >= 2
    ):
        return normalized[1:-1]
    try:
        if "." in normalized:
            return float(normalized)
        return int(normalized)
    except ValueError:
        return normalized


def _gate_job_context(context: Mapping[str, Any]) -> Mapping[str, Any]:
    nested = context.get("job_context")
    if isinstance(nested, Mapping):
        return nested
    return context


def _gate_workflow_scope(context: Mapping[str, Any], scope: str) -> Mapping[str, Any]:
    job_context = _gate_job_context(context)
    workflow = job_context.get("workflow")
    if not isinstance(workflow, Mapping):
        return {}
    value = workflow.get(scope)
    return value if isinstance(value, Mapping) else {}


def _gate_step_outputs(context: Mapping[str, Any]) -> Mapping[str, Any]:
    # dependencies_by_name maps task_name -> output dict for all completed upstream tasks
    by_name = context.get("dependencies_by_name")
    return by_name if isinstance(by_name, Mapping) else {}


def _resolve_secret_value(secret_ref: execution_contracts.SecretRef) -> tuple[Any, str | None]:
    provider = str(secret_ref.provider or execution_contracts.DEFAULT_SECRET_PROVIDER).strip()
    if provider != execution_contracts.DEFAULT_SECRET_PROVIDER:
        return None, f"runtime.secret_provider_not_supported:{provider}"
    value = os.getenv(secret_ref.name)
    if value is None:
        return None, f"runtime.secret_not_found:{secret_ref.name}"
    return value, None


def _resolve_payload_secret_refs(value: Any) -> tuple[Any, str | None]:
    secret_ref = execution_contracts.parse_secret_ref(value)
    if secret_ref is not None:
        return _resolve_secret_value(secret_ref)
    if isinstance(value, Mapping):
        resolved: dict[str, Any] = {}
        for key, item in value.items():
            resolved_item, error = _resolve_payload_secret_refs(item)
            if error is not None:
                return None, error
            resolved[key] = resolved_item
        return resolved, None
    if isinstance(value, list):
        resolved_items: list[Any] = []
        for item in value:
            resolved_item, error = _resolve_payload_secret_refs(item)
            if error is not None:
                return None, error
            resolved_items.append(resolved_item)
        return resolved_items, None
    return value, None


def _request_tool_inputs(
    request: execution_contracts.TaskExecutionRequest,
    request_id: str,
    tool_name: str,
) -> dict[str, dict[str, Any]]:
    tool_inputs = dict(request.tool_inputs)
    request_inputs = dict(tool_inputs.get(request_id) or {})
    if tool_name and tool_name != request_id:
        tool_inputs[tool_name] = request_inputs
    return tool_inputs


def _failed_tool_call(
    *,
    tool_name: str,
    input_payload: dict[str, Any],
    trace_id: str,
    started_at: datetime,
    request_id: str | None = None,
    capability_id: str | None = None,
    adapter_id: str | None = None,
    error: str,
    error_code: str | None = None,
) -> models.ToolCall:
    output_or_error = {"error": error}
    if error_code:
        output_or_error["error_code"] = error_code
    return models.ToolCall(
        tool_name=tool_name,
        input=input_payload,
        idempotency_key=str(uuid.uuid4()),
        trace_id=trace_id,
        request_id=request_id,
        capability_id=capability_id,
        adapter_id=adapter_id,
        started_at=started_at,
        finished_at=datetime.now(UTC),
        status="failed",
        output_or_error=output_or_error,
    )


def _capability_adapter_id(capability_spec: Any) -> str | None:
    adapters = capability_spec.adapters if isinstance(capability_spec.adapters, tuple) else ()
    if not adapters:
        return None
    adapter = adapters[0]
    parts = [
        str(adapter.type or "").strip(),
        str(adapter.server_id or "").strip(),
        str(adapter.tool_name or "").strip(),
    ]
    normalized = [part for part in parts if part]
    return ":".join(normalized) if normalized else None


def _native_adapter_id(tool_name: str) -> str:
    return f"local_tool:{tool_name}"


def _normalize_timeout_error(error: str) -> str:
    lowered = error.lower()
    if (
        "timed out" in lowered or "timeout" in lowered or "mcp_sdk_timeout:" in lowered
    ) and not error.startswith("tool_call_timed_out"):
        return f"tool_call_timed_out:{error}"
    return error
