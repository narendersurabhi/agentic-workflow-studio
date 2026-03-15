from __future__ import annotations

from datetime import datetime

from libs.core import llm_provider, models, planner_contracts
from services.planner.app import planner_service


def _job() -> models.Job:
    return models.Job(
        id="job-1",
        goal="Generate a plan",
        context_json={"topic": "demo"},
        status=models.JobStatus.queued,
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
        priority=0,
        metadata={},
    )


class _Provider(llm_provider.LLMProvider):
    def generate_request(self, request: llm_provider.LLMRequest) -> llm_provider.LLMResponse:
        del request
        return llm_provider.LLMResponse(
            content=(
                '{"planner_version":"1.0.0","tasks_summary":"demo","dag_edges":[],"tasks":[]}'
            )
        )


def test_build_plan_request_adds_semantic_hints() -> None:
    runtime = planner_service.PlannerServiceRuntime(
        load_capabilities=lambda: {},
        build_semantic_capability_hints=lambda job, capabilities, limit: [
            {"capability_id": "demo", "score": 0.9, "goal": job.goal, "limit": limit}
        ],
        parse_llm_plan=lambda content: models.PlanCreate.model_validate_json(content),
        ensure_llm_tool=lambda plan: plan,
        ensure_task_intents=lambda plan, request: plan,
        ensure_job_inputs=lambda plan, request: plan,
        ensure_default_value_markers=lambda plan, request: plan,
        ensure_renderer_required_inputs=lambda plan: plan,
        ensure_tool_input_dependencies=lambda plan: plan,
        ensure_renderer_output_extensions=lambda plan: plan,
        apply_max_depth=lambda plan, max_depth: plan,
        validate_plan=lambda plan, request: (True, "ok"),
    )

    request = planner_service.build_plan_request(
        _job(),
        [],
        config=planner_service.PlannerServiceConfig(mode="llm", semantic_hint_limit=5),
        runtime=runtime,
    )

    assert isinstance(request, planner_contracts.PlanRequest)
    assert request.semantic_capability_hints[0]["capability_id"] == "demo"
    assert request.semantic_capability_hints[0]["limit"] == 5


def test_plan_job_uses_request_boundary_for_llm_path() -> None:
    captured: list[planner_contracts.PlanRequest] = []

    def _ensure_task_intents(
        plan: models.PlanCreate,
        request: planner_contracts.PlanRequest,
    ) -> models.PlanCreate:
        captured.append(request)
        return plan

    runtime = planner_service.PlannerServiceRuntime(
        load_capabilities=lambda: {},
        build_semantic_capability_hints=lambda job, capabilities, limit: [],
        parse_llm_plan=lambda content: models.PlanCreate.model_validate_json(content),
        ensure_llm_tool=lambda plan: plan,
        ensure_task_intents=_ensure_task_intents,
        ensure_job_inputs=lambda plan, request: plan,
        ensure_default_value_markers=lambda plan, request: plan,
        ensure_renderer_required_inputs=lambda plan: plan,
        ensure_tool_input_dependencies=lambda plan: plan,
        ensure_renderer_output_extensions=lambda plan: plan,
        apply_max_depth=lambda plan, max_depth: plan,
        validate_plan=lambda plan, request: (True, "ok"),
    )

    plan = planner_service.plan_job(
        _job(),
        [],
        provider=_Provider(),
        config=planner_service.PlannerServiceConfig(mode="llm"),
        runtime=runtime,
    )

    assert plan.planner_version == "1.0.0"
    assert captured
    assert captured[0].job_id == "job-1"


def test_build_llm_prompt_uses_request_contract() -> None:
    request = planner_contracts.PlanRequest(
        job_id="job-1",
        goal="Render a DOCX",
        job_payload={"goal": "Render a DOCX"},
        semantic_capability_hints=[{"capability_id": "docx.generate"}],
    )

    prompt = planner_service.build_llm_prompt(request)

    assert "Goal: Render a DOCX" in prompt
    assert "docx.generate" in prompt
