from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Mapping

from libs.core import llm_provider, logging as core_logging, models, planner_contracts


@dataclass(frozen=True)
class PlannerServiceConfig:
    mode: str = "rule_based"
    max_dependency_depth: int | None = None
    semantic_hint_limit: int = 10


@dataclass(frozen=True)
class PlannerServiceRuntime:
    load_capabilities: Callable[[], Mapping[str, Any]]
    build_semantic_capability_hints: Callable[
        [models.Job, Mapping[str, Any], int], list[dict[str, Any]]
    ]
    build_llm_prompt: Callable[[planner_contracts.PlanRequest], str]
    build_llm_repair_prompt: Callable[[str, str, planner_contracts.PlanRequest], str]
    parse_llm_plan: Callable[[str], models.PlanCreate | None]
    postprocess_llm_plan: Callable[
        [models.PlanCreate, planner_contracts.PlanRequest], models.PlanCreate
    ]
    validate_plan: Callable[
        [models.PlanCreate, planner_contracts.PlanRequest], tuple[bool, str]
    ]


def build_plan_request(
    job: models.Job,
    tools: list[models.ToolSpec],
    *,
    config: PlannerServiceConfig,
    runtime: PlannerServiceRuntime,
    include_semantic_hints: bool | None = None,
) -> planner_contracts.PlanRequest:
    capabilities = runtime.load_capabilities()
    use_semantic_hints = config.mode == "llm" if include_semantic_hints is None else include_semantic_hints
    semantic_hints: list[dict[str, Any]] = []
    if use_semantic_hints and config.semantic_hint_limit > 0:
        semantic_hints = runtime.build_semantic_capability_hints(
            job,
            capabilities,
            config.semantic_hint_limit,
        )
    return planner_contracts.build_plan_request(
        job,
        tools=tools,
        capabilities=capabilities,
        semantic_capability_hints=semantic_hints,
        max_dependency_depth=config.max_dependency_depth,
    )


def rule_based_plan(_: planner_contracts.PlanRequest) -> models.PlanCreate:
    checklist_task = models.TaskCreate(
        name="create_checklist",
        description="Create implementation checklist",
        instruction="Generate a detailed checklist for adding a new tool.",
        acceptance_criteria=["Checklist has at least 5 items"],
        expected_output_schema_ref="TaskResult",
        intent=models.ToolIntent.generate,
        deps=[],
        tool_requests=[],
        critic_required=True,
    )
    write_task = models.TaskCreate(
        name="write_tools_doc",
        description="Write tools.md artifact",
        instruction="Write a tools.md draft file as an artifact.",
        acceptance_criteria=["Artifact path returned"],
        expected_output_schema_ref="TaskResult",
        intent=models.ToolIntent.render,
        deps=["create_checklist"],
        tool_requests=["file_write_artifact"],
        critic_required=True,
    )
    summarize_task = models.TaskCreate(
        name="summarize_artifact",
        description="Summarize the artifact",
        instruction="Summarize the tools.md artifact.",
        acceptance_criteria=["Summary provided"],
        expected_output_schema_ref="TaskResult",
        intent=models.ToolIntent.transform,
        deps=["write_tools_doc"],
        tool_requests=["text_summarize"],
        critic_required=False,
    )
    return models.PlanCreate(
        planner_version="rule_based_v1",
        tasks_summary="Checklist, write artifact, summarize",
        dag_edges=[
            ["create_checklist", "write_tools_doc"],
            ["write_tools_doc", "summarize_artifact"],
        ],
        tasks=[checklist_task, write_task, summarize_task],
    )


def llm_plan(
    request: planner_contracts.PlanRequest,
    provider: llm_provider.LLMProvider,
    *,
    runtime: PlannerServiceRuntime,
) -> models.PlanCreate:
    logger = core_logging.get_logger("planner")
    prompt = runtime.build_llm_prompt(request)
    response = provider.generate_request(
        llm_provider.LLMRequest(
            prompt=prompt,
            metadata={
                "component": "planner",
                "operation": "plan_generation",
                "job_id": request.job_id,
                "goal_len": len(request.goal or ""),
                "tool_count": len(request.tools),
            },
        )
    )
    candidate = runtime.parse_llm_plan(response.content)
    if not candidate:
        logger.warning("llm_plan_parse_retry", reason="initial_parse_failed")
        repair_prompt = runtime.build_llm_repair_prompt(prompt, response.content, request)
        repaired = provider.generate_request(
            llm_provider.LLMRequest(
                prompt=repair_prompt,
                metadata={
                    "component": "planner",
                    "operation": "plan_generation_repair",
                    "job_id": request.job_id,
                    "goal_len": len(request.goal or ""),
                    "tool_count": len(request.tools),
                },
            )
        )
        candidate = runtime.parse_llm_plan(repaired.content)
    if not candidate:
        raise ValueError("Invalid plan generated: parse_failed")
    candidate = runtime.postprocess_llm_plan(candidate, request)
    logger.info("llm_plan_candidate", plan=candidate.model_dump())
    valid, reason = runtime.validate_plan(candidate, request)
    if not valid:
        logger.warning("llm_plan_invalid", reason=reason)
        raise ValueError(f"Invalid plan generated: {reason}")
    return candidate


def plan_job(
    job: models.Job,
    tools: list[models.ToolSpec],
    *,
    provider: llm_provider.LLMProvider | None,
    config: PlannerServiceConfig,
    runtime: PlannerServiceRuntime,
) -> models.PlanCreate:
    request = build_plan_request(
        job,
        tools,
        config=config,
        runtime=runtime,
    )
    if config.mode == "llm":
        if provider is None:
            raise ValueError("LLM planner mode requires a provider")
        return llm_plan(request, provider, runtime=runtime)
    return rule_based_plan(request)
