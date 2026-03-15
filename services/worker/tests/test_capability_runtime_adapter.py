from __future__ import annotations

from datetime import UTC, datetime

from libs.core import capability_registry, models
from services.worker.app import capability_runtime_adapter


def test_resolve_enabled_capability_reads_registry(monkeypatch) -> None:
    spec = capability_registry.CapabilitySpec(
        capability_id="github.repo.list",
        description="List repos",
        risk_tier="read_only",
        idempotency="read",
        enabled=True,
    )
    monkeypatch.setattr(
        capability_runtime_adapter.capability_registry,
        "resolve_capability_mode",
        lambda: "enforce",
    )
    monkeypatch.setattr(
        capability_runtime_adapter.capability_registry,
        "load_capability_registry",
        lambda: {"github.repo.list": spec},
    )

    runtime = capability_runtime_adapter.build_worker_capability_runtime(
        logger=object(),
        hooks=capability_runtime_adapter.WorkerCapabilityHooks(
            load_memory_inputs=lambda _tool, _task_payload, _trace_id: {},
            apply_memory_defaults=lambda _tool_name, payload: payload,
            missing_memory_only_inputs=lambda _tool_name, _payload: [],
            persist_memory_outputs=lambda _tool, _task_payload, _call, _trace_id: None,
        ),
        output_size_cap=1024,
    )

    resolved = runtime.resolve_enabled_capability("github.repo.list")

    assert resolved is spec


def test_execute_capability_bridges_native_tool(monkeypatch) -> None:
    class _Tool:
        spec = models.ToolSpec(
            name="llm_generate",
            description="Generate",
            input_schema={},
            output_schema={},
            tool_intent=models.ToolIntent.generate,
        )

    class _ToolRuntime:
        def __init__(self) -> None:
            self.registry = self
            self.calls: list[dict[str, object]] = []

        def get_tool(self, tool_name: str):
            assert tool_name == "llm_generate"
            return _Tool()

        def execute_tool(self, tool_name: str, *, payload, idempotency_key, trace_id, max_output_bytes):
            self.calls.append(dict(payload))
            return models.ToolCall(
                tool_name=tool_name,
                input=dict(payload),
                idempotency_key=idempotency_key,
                trace_id=trace_id,
                started_at=datetime.now(UTC),
                finished_at=datetime.now(UTC),
                status="completed",
                output_or_error={"text": "hello"},
            )

    monkeypatch.setattr(
        capability_runtime_adapter.mcp_gateway,
        "invoke_capability",
        lambda capability_id, payload, execute_tool: {
            "items": [execute_tool("llm_generate", {"text": "hello"})]
        },
    )

    runtime = capability_runtime_adapter.build_worker_capability_runtime(
        logger=object(),
        hooks=capability_runtime_adapter.WorkerCapabilityHooks(
            load_memory_inputs=lambda _tool, _task_payload, _trace_id: {},
            apply_memory_defaults=lambda _tool_name, payload: payload,
            missing_memory_only_inputs=lambda _tool_name, _payload: [],
            persist_memory_outputs=lambda _tool, _task_payload, _call, _trace_id: None,
        ),
        output_size_cap=1024,
    )
    tool_runtime = _ToolRuntime()

    call = runtime.execute_capability(
        capability_id="github.repo.list",
        payload={"query": "repo:demo owner:octocat"},
        trace_id="trace-1",
        idempotency_key="id-1",
        task_payload={"task_id": "task-1"},
        tool_runtime=tool_runtime,
    )

    assert call.status == "completed"
    assert call.output_or_error["items"][0]["text"] == "hello"
    assert tool_runtime.calls[0]["_registry"] is tool_runtime.registry
