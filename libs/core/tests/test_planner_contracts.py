from __future__ import annotations

from datetime import datetime

import pytest

from libs.core import models, planner_contracts, workflow_contracts

# Tests that constructed capability_registry.CapabilitySpec fixtures were removed
# with the tools framework: test_build_plan_request_extracts_intent_graph_and_capabilities,
# test_canonicalize_planner_request_ids_rewrites_aliases_and_adapter_tools,
# test_compile_task_request_payloads_compiles_capability_requests_to_runtime_tools,
# test_validate_planner_request_language_rejects_raw_adapter_tool_name,
# test_validate_planner_request_language_supports_compat_mode.


def _job() -> models.Job:
    return models.Job(
        id="job-1",
        goal="Create a DOCX from markdown",
        context_json={"output_dir": "artifacts", "repo_owner": "narendersurabhi"},
        status=models.JobStatus.queued,
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
        priority=0,
        metadata={
            "job_type": "document",
            "goal_intent_graph": {
                "segments": [
                    {
                        "id": "seg-1",
                        "intent": "render",
                        "objective": "Render the document",
                    }
                ]
            },
        },
    )


def test_build_plan_request_prefers_normalized_envelope_graph_when_present() -> None:
    job = _job()
    job.metadata = {
        "goal_intent_graph": {
            "segments": [
                {
                    "id": "legacy-seg",
                    "intent": "generate",
                    "objective": "Legacy graph segment",
                }
            ]
        },
        "normalized_intent_envelope": {
            "goal": job.goal,
            "profile": {"intent": "render", "source": "llm"},
            "graph": {
                "segments": [
                    {
                        "id": "env-seg",
                        "intent": "render",
                        "objective": "Render the document",
                        "suggested_capabilities": ["document.docx.render"],
                    }
                ]
            },
        },
    }

    request = planner_contracts.build_plan_request(job, tools=[], capabilities={})

    assert request.normalized_intent_envelope is not None
    assert request.goal_intent_graph is not None
    assert request.goal_intent_graph.segments[0].id == "env-seg"
    assert planner_contracts.goal_intent_sequence(request) == ["render"]


def test_build_plan_request_supports_envelope_only_job_metadata() -> None:
    job = _job()
    job.metadata = {
        "normalized_intent_envelope": {
            "goal": job.goal,
            "profile": {"intent": "validate", "source": "llm"},
            "graph": {
                "segments": [
                    {
                        "id": "env-only-seg",
                        "intent": "validate",
                        "objective": "Validate repository state",
                        "suggested_capabilities": ["github.repo.list"],
                    }
                ]
            },
        }
    }

    request = planner_contracts.build_plan_request(job, tools=[], capabilities={})

    assert request.normalized_intent_envelope is not None
    assert request.goal_intent_graph is not None
    assert request.goal_intent_graph.segments[0].id == "env-only-seg"
    assert planner_contracts.goal_intent_sequence(request) == ["validate"]


def test_build_plan_request_extracts_revision_context_from_metadata() -> None:
    job = _job()
    job.metadata = {
        "planning_mode": "adaptive",
        "revision_context": {
            "revision_number": 2,
            "prior_plan_id": "plan-2",
            "trigger_reason": "retry_exhausted_auto_repair",
            "checkpoint_lineage": {
                "checkpoint_id": "checkpoint-1",
                "checkpoint_key": "after-input",
                "replay_count": 1,
            },
            "completed_steps": [
                {
                    "task_id": "task-1",
                    "name": "CollectInput",
                    "status": "completed",
                    "outputs": {"filesystem.workspace.list": {"entries": []}},
                    "result": {"status": "completed"},
                }
            ],
            "failed_step": {
                "task_id": "task-2",
                "task_name": "CallService",
                "capability_id": "filesystem.workspace.list",
                "task_intent": "io",
                "error_message": "service unavailable: upstream temporary 503",
                "failure_category": "transient",
                "retry_classification": "retryable",
                "retryable": True,
                "attempt_number": 3,
                "max_attempts": 3,
            },
            "remaining_goals": ["CallService"],
            "constraints": {"retry_classification": "retryable"},
            "budgets": {"max_replans": 2, "replans_used": 1, "replans_remaining": 1},
        },
    }

    request = planner_contracts.build_plan_request(job, tools=[], capabilities={})

    assert request.revision_context is not None
    assert request.revision_context.revision_number == 2
    assert request.revision_context.prior_plan_id == "plan-2"
    assert request.revision_context.checkpoint_lineage["checkpoint_id"] == "checkpoint-1"
    assert request.revision_context.completed_steps[0].task_id == "task-1"
    assert request.revision_context.failed_step is not None
    assert request.revision_context.failed_step.task_name == "CallService"
    assert request.revision_context.budgets["replans_remaining"] == 1


def test_governance_context_uses_request_metadata() -> None:
    request = planner_contracts.build_plan_request(_job(), tools=[], capabilities={})

    context = planner_contracts.governance_context(request)

    assert context["job_id"] == "job-1"
    assert context["job_type"] == "document"
    assert context["job_context"]["output_dir"] == "artifacts"


def test_build_plan_request_defaults_render_path_mode_to_explicit() -> None:
    request = planner_contracts.build_plan_request(_job(), tools=[], capabilities={})

    assert request.render_path_mode == planner_contracts.RENDER_PATH_MODE_EXPLICIT


def test_build_plan_request_projects_stage_specific_planner_context() -> None:
    job = _job()
    job.context_json = {
        "title": "Senior AI Engineer cheat sheet",
        "user_profile": {"preferences": {"response_verbosity": "concise"}},
        "interaction_summaries": [
            {"facts": ["thanks"], "action": "thanks"},
            {"facts": ["document tone should be practical"], "action": "set document tone"},
        ],
        "interaction_summaries_ref": {"memory_name": "interaction_summaries_compact"},
        "interaction_summaries_meta": {"count": 2},
    }
    job.metadata = {
        "normalized_intent_envelope": workflow_contracts.dump_normalized_intent_envelope(
            workflow_contracts.NormalizedIntentEnvelope(
                goal=job.goal,
                profile=workflow_contracts.GoalIntentProfile(
                    intent="generate",
                    source="test",
                    missing_slots=["topic", "path"],
                ),
                graph=workflow_contracts.IntentGraph(
                    segments=[
                        workflow_contracts.IntentGraphSegment(
                            id="seg-1",
                            intent="generate",
                            objective="Render the document",
                            suggested_capabilities=["document.docx.render"],
                        )
                    ]
                ),
                candidate_capabilities={"seg-1": ["document.docx.render"]},
                clarification=workflow_contracts.ClarificationState(
                    missing_inputs=["topic", "path"],
                ),
            )
        )
        or {}
    }

    request = planner_contracts.build_plan_request(job, tools=[], capabilities={})

    assert "user_profile" not in request.job_context
    assert "interaction_summaries_ref" not in request.job_context
    assert "interaction_summaries_meta" not in request.job_context
    assert request.job_context["capability_candidates"] == ["document.docx.render"]
    assert request.job_context["missing_inputs"] == ["path"]
    assert request.job_context["interaction_summaries"] == [
        {"facts": ["document tone should be practical"], "action": "set document tone"}
    ]


def test_validate_render_path_requirement_accepts_job_context_reference() -> None:
    error = planner_contracts.validate_render_path_requirement(
        request_id="docx_render_from_spec",
        raw_payload={"path": {"$from": "job_context.path"}},
        resolved_payload={"path": "documents/report.docx"},
        job_context={"path": "documents/report.docx"},
        render_path_mode="explicit",
    )

    assert error is None


def test_validate_render_path_requirement_rejects_dependency_reference() -> None:
    error = planner_contracts.validate_render_path_requirement(
        request_id="docx_render_from_spec",
        raw_payload={
            "path": {"$from": "dependencies_by_name.DeriveOutputPath.derive_output_filename.path"}
        },
        resolved_payload={"path": "documents/report.docx"},
        job_context={},
        render_path_mode="explicit",
    )

    assert error == "render_path_derived_not_allowed:docx_render_from_spec"

