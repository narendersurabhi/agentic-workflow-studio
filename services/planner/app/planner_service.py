from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any, Callable, Mapping

from pydantic import BaseModel

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
    parse_llm_plan: Callable[[str], models.PlanCreate | None]
    ensure_llm_tool: Callable[[models.PlanCreate], models.PlanCreate]
    ensure_task_intents: Callable[
        [models.PlanCreate, planner_contracts.PlanRequest], models.PlanCreate
    ]
    ensure_job_inputs: Callable[[models.PlanCreate, planner_contracts.PlanRequest], models.PlanCreate]
    ensure_default_value_markers: Callable[
        [models.PlanCreate, planner_contracts.PlanRequest], models.PlanCreate
    ]
    ensure_renderer_required_inputs: Callable[[models.PlanCreate], models.PlanCreate]
    ensure_tool_input_dependencies: Callable[[models.PlanCreate], models.PlanCreate]
    ensure_renderer_output_extensions: Callable[[models.PlanCreate], models.PlanCreate]
    apply_max_depth: Callable[[models.PlanCreate, int | None], models.PlanCreate]
    validate_plan: Callable[
        [models.PlanCreate, planner_contracts.PlanRequest], tuple[bool, str]
    ]


def _json_fallback(value: object) -> object:
    if isinstance(value, BaseModel):
        return value.model_dump()
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, set):
        return list(value)
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value)


def _format_intent_mismatch_recovery_block(recovery: Mapping[str, Any] | None) -> str:
    if not isinstance(recovery, Mapping) or not recovery:
        return ""
    payload = json.dumps(recovery, ensure_ascii=False, indent=2, default=_json_fallback)
    return (
        "Intent mismatch auto-repair context:\n"
        f"{payload}\n"
        "Recovery rules:\n"
        "- Do not repeat the failing task/tool intent mismatch.\n"
        "- Ensure each task.intent matches the selected tool/capability intent policy.\n"
        "- If allowed_task_intents are provided, set task intent to one of them.\n"
        "- Keep dependencies valid while minimally modifying the prior plan shape.\n"
    )


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


def build_llm_prompt(request: planner_contracts.PlanRequest) -> str:
    capabilities = planner_contracts.capability_map(request)
    allowed_names = sorted({tool.name for tool in request.tools} | set(capabilities.keys()))
    tool_names = ", ".join(allowed_names)
    tool_catalog = [
        {
            "type": "tool",
            "name": tool.name,
            "description": tool.description,
            "input_schema": tool.input_schema,
            "usage_guidance": tool.usage_guidance,
            "risk_level": tool.risk_level.value
            if isinstance(tool.risk_level, Enum)
            else tool.risk_level,
            "tool_intent": tool.tool_intent.value
            if isinstance(tool.tool_intent, Enum)
            else tool.tool_intent,
        }
        for tool in request.tools
    ]
    capability_catalog = [
        {
            "type": "capability",
            "name": capability.capability_id,
            "description": capability.description,
            "risk_tier": capability.risk_tier,
            "idempotency": capability.idempotency,
            "group": capability.group,
            "subgroup": capability.subgroup,
            "input_schema_ref": capability.input_schema_ref,
            "output_schema_ref": capability.output_schema_ref,
            "adapters": [
                {
                    "type": adapter.type,
                    "server_id": adapter.server_id,
                    "tool_name": adapter.tool_name,
                }
                for adapter in capability.adapters
            ],
        }
        for capability in capabilities.values()
    ]
    tool_catalog_json = json.dumps(
        tool_catalog + capability_catalog,
        ensure_ascii=False,
        indent=2,
        default=_json_fallback,
    )
    depth_hint = ""
    if request.max_dependency_depth:
        depth_hint = f"Max dependency chain depth: {request.max_dependency_depth}.\n"
    intent_graph_block = ""
    if request.goal_intent_graph is not None:
        intent_graph_json = json.dumps(
            request.goal_intent_graph.model_dump(mode="json", exclude_none=True),
            ensure_ascii=False,
            indent=2,
            default=_json_fallback,
        )
        intent_graph_block = (
            "Goal intent decomposition graph (ordered hints for planning):\n"
            f"{intent_graph_json}\n"
            "Prefer preserving this segment order in tasks/dependencies.\n"
        )
    intent_repair_block = _format_intent_mismatch_recovery_block(
        planner_contracts.intent_mismatch_recovery(request)
    )
    semantic_capability_block = ""
    if request.semantic_capability_hints:
        semantic_capability_block = (
            "Most relevant capabilities for this goal from local semantic search:\n"
            f"{json.dumps(request.semantic_capability_hints, ensure_ascii=False, indent=2, default=_json_fallback)}\n"
            "Prefer these capabilities when they fit the goal and required inputs.\n"
        )
    job_json = json.dumps(request.job_payload, ensure_ascii=False, indent=2, default=_json_fallback)
    return (
        "You are a planner. Return ONLY valid JSON for a PlanCreate object (no prose).\n"
        "Required top-level fields: planner_version, tasks_summary, dag_edges, tasks.\n"
        "Schema rules:\n"
        '- dag_edges must be an array of 2-element string arrays, e.g. [["A","B"],["B","C"]].\n'
        "- acceptance_criteria must be an array of strings, not a single string.\n"
        "Each task must include: name, description, instruction, acceptance_criteria, "
        "expected_output_schema_ref, intent, deps, tool_requests, tool_inputs, critic_required.\n"
        "Example:\n"
        "{\n"
        '  "planner_version": "1.0.0",\n'
        '  "tasks_summary": "...",\n'
        '  "dag_edges": [["TaskA","TaskB"],["TaskB","TaskC"]],\n'
        '  "tasks": [\n'
        "    {\n"
        '      "name": "TaskA",\n'
        '      "description": "...",\n'
        '      "instruction": "...",\n'
        '      "acceptance_criteria": ["..."],\n'
        '      "expected_output_schema_ref": "schemas/example",\n'
        '      "intent": "generate",\n'
        '      "deps": [],\n'
        '      "tool_requests": ["llm_generate"],\n'
        '      "tool_inputs": {"llm_generate": {"text": "..."}},\n'
        '      "critic_required": false\n'
        "    }\n"
        "  ]\n"
        "}\n"
        "\n"
        "Rules:\n"
        "1) Use only tool names from the allowed list.\n"
        "1a) Every task must set intent to one of: transform, generate, validate, render, io.\n"
        "2) deps must reference task names that appear in this plan.\n"
        "3) If a tool requires structured JSON, add a prior task to generate that JSON and set "
        "expected_output_schema_ref to that schema.\n"
        "4) If a tool requires specific inputs, put them in task.tool_inputs "
        "(a dict keyed by tool name). Do NOT embed JSON in instruction text.\n"
        "5) Do NOT use placeholder strings like ${Task.output} in tool_inputs. "
        "When a later task needs dependency output, either omit the field and rely on deps context "
        "injection OR use explicit reference objects like "
        '{"$from":"dependencies_by_name.TaskA.tool_name.field"} (or add "$default"). '
        "You may still include other inputs like strict, allowed_block_types, or path.\n"
        "6) Prefer the generic validation + rendering pipeline:\n"
        "   - Generate a DocumentSpec JSON.\n"
        "   - Validate with document_spec_validate.\n"
        "   - Render with docx_generate_from_spec or pdf_generate_from_spec.\n"
        "   - Do not add a separate output-path derivation task unless the path itself is needed downstream.\n"
        "   Use specialized tools only if explicitly requested.\n"
        "7) If unsure, use llm_generate.\n"
        "8) Keep output compact. Do NOT copy or embed large raw text from Job JSON "
        "(especially long context fields like job_description) into tasks, instructions, "
        "acceptance criteria, or tool_inputs.\n"
        "9) For tool_inputs include only minimal scalar params. Omit large/context fields "
        "(e.g., job, memory, document_spec) "
        "and rely on runtime dependency/context injection.\n"
        "10) Keep each task instruction concise (one short paragraph) and keep acceptance "
        "criteria short bullets.\n"
        "\n"
        f"{depth_hint}"
        f"{intent_graph_block}"
        f"{intent_repair_block}"
        f"Allowed tool names: {tool_names}\n"
        f"{semantic_capability_block}"
        f"Tool catalog (JSON): {tool_catalog_json}\n"
        f"Goal: {request.goal}\n"
        f"Job (JSON): {job_json}\n"
    )


def build_llm_repair_prompt(
    original_prompt: str,
    raw_output: str,
    request: planner_contracts.PlanRequest,
) -> str:
    capabilities = planner_contracts.capability_map(request)
    allowed_names = sorted({tool.name for tool in request.tools} | set(capabilities.keys()))
    tool_names = ", ".join(allowed_names)
    return (
        "You are fixing a malformed planner response.\n"
        "Return ONLY one valid JSON object for PlanCreate.\n"
        "Do not include markdown, comments, or prose.\n"
        "Required top-level fields: planner_version, tasks_summary, dag_edges, tasks.\n"
        "Each task must include: name, description, instruction, acceptance_criteria, "
        "expected_output_schema_ref, intent, deps, tool_requests, tool_inputs, critic_required.\n"
        "Rules:\n"
        "- acceptance_criteria must be string array.\n"
        "- dag_edges must be array of 2-string arrays.\n"
        "- each task must include intent in {transform, generate, validate, render, io}.\n"
        "- Use only allowed tool names.\n"
        "- If a field is missing, add a safe default value.\n"
        f"Allowed tool names: {tool_names}\n\n"
        f"Original planner prompt (for context):\n{original_prompt}\n\n"
        f"Malformed planner output to repair:\n{raw_output}\n"
    )


def postprocess_llm_plan(
    plan: models.PlanCreate,
    request: planner_contracts.PlanRequest,
    *,
    runtime: PlannerServiceRuntime,
) -> models.PlanCreate:
    candidate = runtime.ensure_llm_tool(plan)
    candidate = runtime.ensure_task_intents(candidate, request)
    candidate = runtime.ensure_job_inputs(candidate, request)
    candidate = runtime.ensure_default_value_markers(candidate, request)
    candidate = runtime.ensure_renderer_required_inputs(candidate)
    candidate = runtime.ensure_tool_input_dependencies(candidate)
    candidate = runtime.ensure_renderer_output_extensions(candidate)
    return runtime.apply_max_depth(candidate, request.max_dependency_depth)


def llm_plan(
    request: planner_contracts.PlanRequest,
    provider: llm_provider.LLMProvider,
    *,
    runtime: PlannerServiceRuntime,
) -> models.PlanCreate:
    logger = core_logging.get_logger("planner")
    prompt = build_llm_prompt(request)
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
        repair_prompt = build_llm_repair_prompt(prompt, response.content, request)
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
    candidate = postprocess_llm_plan(candidate, request, runtime=runtime)
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
