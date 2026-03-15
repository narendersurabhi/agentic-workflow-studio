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
        build_llm_prompt=lambda request: request.goal,
        build_llm_repair_prompt=lambda original, raw, request: original + raw + request.goal,
        parse_llm_plan=lambda content: models.PlanCreate.model_validate_json(content),
        postprocess_llm_plan=lambda plan, request: plan,
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

    def _build_prompt(request: planner_contracts.PlanRequest) -> str:
        captured.append(request)
        return request.goal

    runtime = planner_service.PlannerServiceRuntime(
        load_capabilities=lambda: {},
        build_semantic_capability_hints=lambda job, capabilities, limit: [],
        build_llm_prompt=_build_prompt,
        build_llm_repair_prompt=lambda original, raw, request: original + raw,
        parse_llm_plan=lambda content: models.PlanCreate.model_validate_json(content),
        postprocess_llm_plan=lambda plan, request: plan,
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
