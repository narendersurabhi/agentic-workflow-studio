from datetime import UTC, datetime

from libs.core import execution_contracts, intent_contract, models
from services.worker.app import main


def test_execute_task_delegates_through_execution_request_boundary(monkeypatch) -> None:
    request = execution_contracts.TaskExecutionRequest(
        task_id="task-1",
        source_payload={"task_id": "task-1"},
    )
    expected = models.TaskResult(
        task_id="task-1",
        status=models.TaskStatus.completed,
        outputs={},
        artifacts=[],
        tool_calls=[],
        started_at=datetime.now(UTC),
        finished_at=datetime.now(UTC),
    )
    seen: list[execution_contracts.TaskExecutionRequest] = []

    def fake_build(
        payload: dict, *, default_max_attempts: int
    ) -> execution_contracts.TaskExecutionRequest:
        assert payload == {"task_id": "task-1"}
        assert default_max_attempts == main.WORKER_DEFAULT_MAX_ATTEMPTS
        return request

    def fake_execute(
        built_request: execution_contracts.TaskExecutionRequest,
    ) -> models.TaskResult:
        seen.append(built_request)
        return expected

    monkeypatch.setattr(main.execution_contracts, "build_task_execution_request", fake_build)
    monkeypatch.setattr(main, "execute_task_request", fake_execute)

    result = main.execute_task({"task_id": "task-1"})

    assert result is expected
    assert seen == [request]


def test_infer_task_intent_uses_payload_hint() -> None:
    payload = {
        "intent": "render",
        "description": "Generate something",
        "instruction": "Generate",
        "acceptance_criteria": ["done"],
    }
    assert main._infer_task_intent(payload) == "render"


def test_infer_task_intent_inference_exposes_source_and_confidence() -> None:
    payload = {
        "description": "Step one",
        "instruction": "Handle task",
        "acceptance_criteria": ["done"],
        "goal": "Validate this output against schema",
    }
    inference = main._infer_task_intent_inference(payload)
    assert inference.intent == "validate"
    assert inference.source == "goal_text"
    assert inference.confidence > 0


def test_intent_mismatch_rejects_generate_tool_for_io_task() -> None:
    mismatch = main._intent_mismatch("io", models.ToolIntent.generate, "llm_generate")
    assert mismatch == "tool_intent_mismatch:llm_generate:generate:io"


def test_intent_segment_from_payload_prefers_direct_segment() -> None:
    payload = {
        "intent_segment": {
            "id": "s1",
            "intent": "render",
            "objective": "Render final PDF",
            "slots": {
                "entity": "report",
                "artifact_type": "document",
                "output_format": "pdf",
                "risk_level": "bounded_write",
                "must_have_inputs": ["document_spec", "path"],
            },
        }
    }
    segment = main._intent_segment_from_payload(payload)
    assert segment is not None
    assert segment["intent"] == "render"


def test_intent_segment_contract_requires_explicit_path_when_payload_has_none() -> None:
    # validate_intent_segment_contract has no capability-level "renderer auto-derives
    # its own path" exemption (that existed pre-refactor via a now-removed
    # _capability_auto_derives_output_path allowlist — see git history on
    # libs/core/intent_contract.py commit d05b3d1 "Intent normalization architecture",
    # which replaced it with a narrower document_spec-generation exemption and pushed
    # "path derived by an earlier step" handling to the callers instead). A bare
    # payload with no path key at all is therefore correctly rejected here.
    segment = {
        "id": "s1",
        "intent": "render",
        "objective": "Render final PDF",
        "required_inputs": ["document_spec", "path"],
        "slots": {
            "entity": "report",
            "artifact_type": "document",
            "output_format": "pdf",
            "risk_level": "bounded_write",
            "must_have_inputs": ["document_spec", "path"],
        },
    }
    mismatch = intent_contract.validate_intent_segment_contract(
        segment=segment,
        task_intent="render",
        tool_name="document.pdf.render",
        payload={"document_spec": {"blocks": []}},
        capability_id="document.pdf.render",
        capability_risk_tier="bounded_write",
    )
    assert mismatch == "must_have_inputs_missing:path"


def test_intent_segment_contract_allows_renderer_without_explicit_path() -> None:
    # A render step's path genuinely CAN be absent at plan-validation time when it's
    # derived by an earlier step (e.g. a derive_output_filename task feeding path via
    # a `$from` dependency reference). That tolerance is real and lives in the callers
    # of validate_intent_segment_contract, not inside it: planner_service.py resolves
    # unresolved `$from` references into a placeholder before calling this function
    # (payload_resolver.normalize_reference_payload_for_validation's `unknown_default`,
    # "__dependency__" by default), and services/api/app/main.py's
    # _build_preflight_dependency_output does the same for API-side preflight. This
    # test simulates that placeholder-substitution contract: by the time
    # validate_intent_segment_contract sees the payload, `path` is a non-empty string
    # placeholder rather than a raw `$from` reference or a missing key.
    segment = {
        "id": "s1",
        "intent": "render",
        "objective": "Render final PDF",
        "required_inputs": ["document_spec", "path"],
        "slots": {
            "entity": "report",
            "artifact_type": "document",
            "output_format": "pdf",
            "risk_level": "bounded_write",
            "must_have_inputs": ["document_spec", "path"],
        },
    }
    mismatch = intent_contract.validate_intent_segment_contract(
        segment=segment,
        task_intent="render",
        tool_name="document.pdf.render",
        payload={"document_spec": {"blocks": []}, "path": "__dependency__"},
        capability_id="document.pdf.render",
        capability_risk_tier="bounded_write",
    )
    assert mismatch is None


def test_tool_payload_builds_github_repo_query_from_context_fields() -> None:
    payload = main._tool_payload(
        "github.repo.list",
        "Verify repository exists",
        {
            "job_context": {
                "repo_owner": "narendersurabhi",
                "repo_name": "scientific-agent-lab",
            }
        },
        {"tool_inputs": {"github.repo.list": {}}},
        {"github.repo.list": {}},
    )
    assert payload["query"] == "repo:scientific-agent-lab owner:narendersurabhi"


def test_tool_payload_strips_final_path_for_document_spec_generation() -> None:
    payload = main._tool_payload(
        "llm_generate_document_spec",
        "GenerateDocumentSpec",
        {
            "job_context": {
                "path": "Narender.docx",
                "output_format": "docx",
            }
        },
        {"output_path": "Narender.docx"},
        {
            "llm_generate_document_spec": {
                "instruction": "Create a document spec.",
                "topic": "Agentic AI Ops best practices",
                "audience": "agentic ai ops engineers",
                "tone": "practical",
            }
        },
    )

    assert payload == {
        "instruction": "Create a document spec.",
        "topic": "Agentic AI Ops best practices",
        "audience": "agentic ai ops engineers",
        "tone": "practical",
    }


def test_validate_expected_output_rejects_invalid_render_validation_report() -> None:
    error = main._validate_expected_output(
        {
            "tool_requests": ["docx_render_from_spec"],
            "tool_inputs": {
                "docx_render_from_spec": {
                    "validation_report": {
                        "valid": False,
                        "errors": [
                            {
                                "path": "/blocks/0/text",
                                "message": "text/paragraph requires text: string",
                            }
                        ],
                    }
                }
            },
        },
        {},
    )

    assert (
        error
        == "render_validation_failed:docx_render_from_spec:/blocks/0/text: text/paragraph requires text: string"
    )


def test_validate_expected_output_rejects_render_errors_without_validation_report() -> None:
    error = main._validate_expected_output(
        {
            "tool_requests": ["document.pdf.render"],
            "tool_inputs": {
                "document.pdf.render": {
                    "errors": [
                        {
                            "path": "/blocks/1/items",
                            "message": "items must be an array",
                        }
                    ]
                }
            },
        },
        {},
    )

    assert (
        error
        == "render_validation_failed:document.pdf.render:/blocks/1/items: items must be an array"
    )


def test_validate_expected_output_rejects_invalid_legacy_render_alias_report() -> None:
    error = main._validate_expected_output(
        {
            "tool_requests": ["docx_generate_from_spec"],
            "tool_inputs": {
                "docx_generate_from_spec": {
                    "validation_report": {
                        "valid": False,
                        "errors": [
                            {
                                "path": "/blocks/0/text",
                                "message": "text/paragraph requires text: string",
                            }
                        ],
                    }
                }
            },
        },
        {},
    )

    assert (
        error
        == "render_validation_failed:docx_generate_from_spec:/blocks/0/text: text/paragraph requires text: string"
    )
