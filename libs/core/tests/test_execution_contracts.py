from libs.core import execution_contracts


def test_build_task_execution_request_normalizes_payload() -> None:
    payload = {
        "task_id": "task-1",
        "job_id": "job-1",
        "correlation_id": "trace-1",
        "instruction": "Render the final document",
        "context": {"job_context": {"title": "Quarterly Review"}},
        "tool_requests": ["docx_generate_from_spec", "github.repo.list"],
        "tool_inputs": {
            "docx_generate_from_spec": {"path": "artifacts/report.docx"},
            "github.repo.list": {"owner": "narendersurabhi", "repo": "scientific-agent-lab"},
        },
        "intent": "Render",
        "attempts": 0,
        "max_attempts": "bad-value",
        "intent_segment": {
            "id": "s1",
            "intent": "render",
            "objective": "Render a DOCX artifact",
            "slots": {"must_have_inputs": ["document_spec", "path"]},
        },
    }

    request = execution_contracts.build_task_execution_request(
        payload,
        default_max_attempts=4,
    )

    assert request.task_id == "task-1"
    assert request.job_id == "job-1"
    assert request.trace_id == "trace-1"
    assert request.run_id == "trace-1"
    assert request.intent == "render"
    assert request.attempts == 1
    assert request.max_attempts == 4
    assert request.tool_requests == ["docx_generate_from_spec", "github.repo.list"]
    assert request.tool_inputs["docx_generate_from_spec"]["path"] == "artifacts/report.docx"
    assert request.requests[1].resolved_inputs == {
        "owner": "narendersurabhi",
        "repo": "scientific-agent-lab",
    }
    assert request.intent_segment is not None
    assert request.intent_segment.intent == "render"


def test_build_task_execution_request_reads_capability_bindings() -> None:
    request = execution_contracts.build_task_execution_request(
        {
            "task_id": "task-1",
            "tool_requests": ["github.repo.list"],
            "tool_inputs": {"github.repo.list": {}},
            "capability_bindings": {
                "github.repo.list": {
                    "capability_id": "github.repo.list",
                    "tool_name": "github.repo.list",
                    "adapter_type": "mcp",
                    "server_id": "github_local",
                }
            },
        }
    )

    binding = request.requests[0].capability_binding
    assert binding is not None
    assert binding.request_id == "github.repo.list"
    assert binding.capability_id == "github.repo.list"
    assert binding.adapter_type == "mcp"
    assert binding.server_id == "github_local"
