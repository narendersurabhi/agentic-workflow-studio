from __future__ import annotations

from datetime import UTC, datetime

from libs.core import models
from services.worker.app import capability_runtime_adapter


def _build_runtime(**hook_overrides):
    hooks = capability_runtime_adapter.WorkerCapabilityHooks(
        load_memory_inputs=hook_overrides.get(
            "load_memory_inputs", lambda _tool, _task_payload, _trace_id: {}
        ),
        apply_memory_defaults=hook_overrides.get(
            "apply_memory_defaults", lambda _tool_name, payload: payload
        ),
        missing_memory_only_inputs=hook_overrides.get(
            "missing_memory_only_inputs", lambda _tool_name, _payload: []
        ),
        persist_memory_outputs=hook_overrides.get(
            "persist_memory_outputs", lambda _tool, _task_payload, _call, _trace_id: None
        ),
    )
    return capability_runtime_adapter.build_worker_capability_runtime(
        logger=object(),
        hooks=hooks,
        output_size_cap=1024,
    )


def test_execute_capability_runs_mcp_capability_request(monkeypatch) -> None:
    monkeypatch.setattr(
        capability_runtime_adapter.mcp_gateway,
        "invoke_capability",
        lambda capability_id, arguments, **_: {
            "capability_id": capability_id,
            "arguments": arguments,
            "repos": ["awe", "platform"],
        },
    )
    runtime = _build_runtime()

    call = runtime.execute_capability(
        capability_id="github.repo.list",
        payload={"query": "agentic"},
        trace_id="trace-1",
        idempotency_key="id-1",
        task_payload={"task_id": "task-1"},
        tool_runtime=object(),  # unused on the mcp adapter path
    )

    assert call.status == "completed"
    assert call.output_or_error["repos"] == ["awe", "platform"]


def test_execute_capability_marks_timeout_as_failed(monkeypatch) -> None:
    def _raise_timeout(_capability_id: str, _arguments: dict, **_: dict) -> dict:
        raise RuntimeError("mcp_sdk_timeout:phase=initialize;mcp_call_timed_out_after_10.0s")

    monkeypatch.setattr(capability_runtime_adapter.mcp_gateway, "invoke_capability", _raise_timeout)
    runtime = _build_runtime()

    call = runtime.execute_capability(
        capability_id="github.repo.list",
        payload={"query": "agentic"},
        trace_id="trace-2",
        idempotency_key="id-2",
        task_payload={"task_id": "task-2"},
        tool_runtime=object(),
    )

    assert call.status == "failed"
    assert call.output_or_error["error_code"] == "runtime.timeout"


def test_execute_capability_native_tool_hydrates_memory_defaults(monkeypatch) -> None:
    class _Tool:
        spec = models.ToolSpec(
            name="document_spec_validate",
            description="Validate DocumentSpec",
            input_schema={},
            output_schema={},
            tool_intent=models.ToolIntent.generate,
        )

    class _ToolRuntime:
        def __init__(self) -> None:
            self.registry = self
            self.calls: list[dict] = []

        def get_tool(self, tool_name: str):
            assert tool_name == "document_spec_validate"
            return _Tool()

        def execute_tool(
            self, tool_name: str, *, payload, idempotency_key, trace_id, max_output_bytes
        ):
            self.calls.append(dict(payload))
            return models.ToolCall(
                tool_name=tool_name,
                input=dict(payload),
                idempotency_key=idempotency_key,
                trace_id=trace_id,
                started_at=datetime.now(UTC),
                finished_at=datetime.now(UTC),
                status="completed",
                output_or_error={"valid": True},
            )

    monkeypatch.setattr(
        capability_runtime_adapter.mcp_gateway,
        "invoke_capability",
        lambda capability_id, payload, execute_tool: execute_tool(
            "document_spec_validate", payload
        ),
    )

    runtime = _build_runtime(
        load_memory_inputs=lambda _tool, _task_payload, _trace_id: {
            "task_outputs": [
                {"document_spec": {"blocks": [{"type": "paragraph", "text": "hello"}]}}
            ]
        },
    )
    tool_runtime = _ToolRuntime()

    call = runtime.execute_capability(
        capability_id="document.spec.validate",
        payload={"strict": True},
        trace_id="trace-3",
        idempotency_key="id-3",
        task_payload={"task_id": "task-3"},
        tool_runtime=tool_runtime,
    )

    assert call.status == "completed"
    assert call.output_or_error["valid"] is True
    hydrated_memory = tool_runtime.calls[0]["memory"]
    assert hydrated_memory["task_outputs"][0]["document_spec"]["blocks"][0]["text"] == "hello"
