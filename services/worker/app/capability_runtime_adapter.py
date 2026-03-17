from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Callable

from libs.core import capability_registry, logging as core_logging, mcp_gateway, models
from libs.framework.tool_runtime import ToolExecutionError, classify_tool_error
from services.worker.app import tool_runtime_adapter


@dataclass(frozen=True)
class WorkerCapabilityHooks:
    load_memory_inputs: Callable[[Any, dict[str, Any], str], dict[str, Any]]
    apply_memory_defaults: Callable[[str, dict[str, Any]], dict[str, Any]]
    missing_memory_only_inputs: Callable[[str, dict[str, Any]], list[str]]
    persist_memory_outputs: Callable[[Any, dict[str, Any], models.ToolCall, str], None]


@dataclass(frozen=True)
class WorkerCapabilityRuntime:
    logger: Any
    hooks: WorkerCapabilityHooks
    output_size_cap: int
    service_name: str = "worker"

    def resolve_enabled_capability(
        self,
        capability_id: str,
    ) -> capability_registry.CapabilitySpec | None:
        mode = capability_registry.resolve_capability_mode()
        if mode == "disabled":
            return None
        try:
            registry = capability_registry.load_capability_registry()
        except Exception as exc:  # noqa: BLE001
            core_logging.log_event(
                self.logger,
                "capability_registry_load_failed",
                {"capability_id": capability_id, "mode": mode, "error": str(exc)},
            )
            return None
        spec = registry.get(capability_id)
        if spec is None or not spec.enabled:
            return None
        if mode == "dry_run":
            core_logging.log_event(
                self.logger,
                "capability_mode_dry_run",
                {"capability_id": capability_id},
            )
        return spec

    def evaluate_allowlist(
        self,
        capability_id: str,
    ) -> capability_registry.CapabilityAllowDecision:
        return capability_registry.evaluate_capability_allowlist(
            capability_id,
            self.service_name,
        )

    def execute_capability(
        self,
        *,
        capability_id: str,
        payload: dict[str, Any],
        trace_id: str,
        idempotency_key: str,
        task_payload: dict[str, Any] | None,
        tool_runtime: tool_runtime_adapter.WorkerToolRuntime,
    ) -> models.ToolCall:
        started_at = datetime.now(UTC)
        task_payload = task_payload if isinstance(task_payload, dict) else {}

        def _execute_native_tool(tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
            try:
                tool = tool_runtime.get_tool(tool_name)
            except KeyError as exc:
                raise ToolExecutionError(f"unknown_tool:{tool_name}") from exc
            tool_payload = dict(arguments)
            memory_payload = self.hooks.load_memory_inputs(tool, task_payload, trace_id)
            if memory_payload:
                existing_memory = tool_payload.get("memory")
                merged_memory = (
                    dict(existing_memory) if isinstance(existing_memory, dict) else {}
                )
                merged_memory.update(memory_payload)
                tool_payload["memory"] = merged_memory
            tool_payload = self.hooks.apply_memory_defaults(tool.spec.name, tool_payload)
            missing = self.hooks.missing_memory_only_inputs(tool.spec.name, tool_payload)
            if missing:
                raise ToolExecutionError(
                    f"contract.input_missing:memory_only_inputs_missing:{','.join(missing)}"
                )
            tool_payload["_registry"] = tool_runtime.registry
            call = tool_runtime.execute_tool(
                tool_name,
                payload=tool_payload,
                idempotency_key=str(uuid.uuid4()),
                trace_id=trace_id,
                max_output_bytes=self.output_size_cap,
            )
            if call.status != "completed":
                output = call.output_or_error if isinstance(call.output_or_error, dict) else {}
                error_text = output.get("error", "capability_native_tool_failed")
                raise ToolExecutionError(str(error_text))
            self.hooks.persist_memory_outputs(tool, task_payload, call, trace_id)
            output = call.output_or_error
            if isinstance(output, dict):
                return output
            return {"result": output}

        try:
            result = mcp_gateway.invoke_capability(
                capability_id,
                payload,
                execute_tool=_execute_native_tool,
            )
            output = result if isinstance(result, dict) else {"result": result}
            status = "completed"
        except Exception as exc:  # noqa: BLE001
            error_text = str(exc)
            output = {"error": error_text, "error_code": classify_tool_error(error_text)}
            status = "failed"
        finished_at = datetime.now(UTC)
        return models.ToolCall(
            tool_name=capability_id,
            input=payload,
            idempotency_key=idempotency_key,
            trace_id=trace_id,
            started_at=started_at,
            finished_at=finished_at,
            status=status,
            output_or_error=output,
        )


def build_worker_capability_runtime(
    *,
    logger: Any,
    hooks: WorkerCapabilityHooks,
    output_size_cap: int,
    service_name: str = "worker",
) -> WorkerCapabilityRuntime:
    return WorkerCapabilityRuntime(
        logger=logger,
        hooks=hooks,
        output_size_cap=output_size_cap,
        service_name=service_name,
    )
