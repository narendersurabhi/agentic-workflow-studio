from __future__ import annotations

import json
import os
import uuid
from datetime import datetime
from enum import Enum
from functools import wraps
from pathlib import Path
from time import perf_counter
from typing import Any, List, Mapping, Sequence

import redis
from prometheus_client import start_http_server
from pydantic import BaseModel

from libs.core import (
    capability_search,
    capability_registry,
    events,
    intent_contract,
    llm_provider,
    logging as core_logging,
    models,
    planner_contracts,
    payload_resolver,
    prompts,
    tool_registry,
    workflow_contracts,
)
try:
    from . import planner_service
except ImportError:  # pragma: no cover - compatibility for direct module loading in tests
    from services.planner.app import planner_service

core_logging.configure_logging("planner")

REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379/0")
PLANNER_MODE = os.getenv("PLANNER_MODE", "rule_based")
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "mock")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "")
OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL", "https://api.openai.com")
OPENAI_TEMPERATURE = os.getenv("OPENAI_TEMPERATURE")
OPENAI_MAX_OUTPUT_TOKENS = os.getenv("OPENAI_MAX_OUTPUT_TOKENS")
PLANNER_MAX_DEPTH = os.getenv("PLANNER_MAX_DEPTH")
OPENAI_TIMEOUT_S = os.getenv("OPENAI_TIMEOUT_S")
OPENAI_MAX_RETRIES = os.getenv("OPENAI_MAX_RETRIES")
SCHEMA_REGISTRY_PATH = os.getenv("SCHEMA_REGISTRY_PATH", "/app/schemas")
METRICS_PORT = int(os.getenv("PLANNER_METRICS_PORT", "9101"))

redis_client = redis.Redis.from_url(REDIS_URL, decode_responses=True)
_METRICS_SERVER_STARTED = False

DEFAULT_ALLOWED_BLOCK_TYPES = [
    "text",
    "paragraph",
    "heading",
    "bullets",
    "spacer",
    "optional_paragraph",
    "repeat",
]


def _log_entry_exit(name: str):
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            logger = core_logging.get_logger("planner")
            safe_args = _safe_log_value(args)
            safe_kwargs = _safe_log_value(kwargs)
            logger.info("enter", function=name, args=safe_args, kwargs=safe_kwargs)
            started = perf_counter()
            try:
                result = func(*args, **kwargs)
                duration_ms = int((perf_counter() - started) * 1000)
                safe_result = _safe_log_value(result)
                logger.info(
                    "exit",
                    function=name,
                    status="ok",
                    duration_ms=duration_ms,
                    result=safe_result,
                )
                return result
            except Exception as exc:  # noqa: BLE001
                duration_ms = int((perf_counter() - started) * 1000)
                logger.error(
                    "exit",
                    function=name,
                    status="error",
                    duration_ms=duration_ms,
                    error=str(exc),
                )
                raise

        return wrapper

    return decorator


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


def _safe_log_value(value: object, max_len: int = 10000) -> object:
    try:
        serialized = json.dumps(value, default=_json_fallback, ensure_ascii=True)
    except Exception:
        try:
            serialized = json.dumps(str(value), ensure_ascii=True)
        except Exception:
            return "<unserializable>"
    if len(serialized) > max_len:
        return f"{serialized[:max_len]}...[truncated]"
    try:
        return json.loads(serialized)
    except Exception:
        return serialized


@_log_entry_exit("rule_based_plan")
def rule_based_plan(job: models.Job, tools: List[models.ToolSpec]) -> models.PlanCreate:
    request = planner_contracts.build_plan_request(
        job,
        tools=tools,
        capabilities={},
        semantic_capability_hints=[],
        max_dependency_depth=_parse_optional_int(PLANNER_MAX_DEPTH),
    )
    return planner_service.rule_based_plan(request)


@_log_entry_exit("llm_plan")
def llm_plan(
    job: models.Job, tools: List[models.ToolSpec], provider: llm_provider.LLMProvider
) -> models.PlanCreate:
    request = planner_service.build_plan_request(
        job,
        tools,
        config=_planner_service_config(),
        runtime=_planner_service_runtime(),
        include_semantic_hints=True,
    )
    return planner_service.llm_plan(request, provider, runtime=_planner_service_runtime())


@_log_entry_exit("plan_job")
def plan_job(job: models.Job) -> models.PlanCreate:
    provider: llm_provider.LLMProvider | None = None
    if PLANNER_MODE == "llm":
        provider = llm_provider.resolve_provider(
            LLM_PROVIDER,
            api_key=OPENAI_API_KEY,
            model=OPENAI_MODEL,
            base_url=OPENAI_BASE_URL,
            temperature=_parse_optional_float(OPENAI_TEMPERATURE),
            max_output_tokens=_parse_optional_int(OPENAI_MAX_OUTPUT_TOKENS),
            timeout_s=_parse_optional_float(OPENAI_TIMEOUT_S),
            max_retries=_parse_optional_int(OPENAI_MAX_RETRIES),
        )
        registry = tool_registry.default_registry(
            False,
            llm_enabled=True,
            llm_provider=provider,
            service_name="planner",
        )
    else:
        registry = tool_registry.default_registry(False, service_name="planner")
    return planner_service.plan_job(
        job,
        registry.list_specs(),
        provider=provider,
        config=_planner_service_config(),
        runtime=_planner_service_runtime(),
    )


def _planner_service_config() -> planner_service.PlannerServiceConfig:
    return planner_service.PlannerServiceConfig(
        mode=PLANNER_MODE,
        max_dependency_depth=_parse_optional_int(PLANNER_MAX_DEPTH),
        semantic_hint_limit=10,
    )


def _planner_service_runtime() -> planner_service.PlannerServiceRuntime:
    return planner_service.PlannerServiceRuntime(
        load_capabilities=_planner_capabilities,
        build_semantic_capability_hints=lambda job, capabilities, limit: _planner_semantic_capability_hints(
            job,
            capabilities,
            limit=limit,
        ),
        build_llm_prompt=_llm_prompt_from_request,
        build_llm_repair_prompt=_llm_plan_repair_prompt_from_request,
        parse_llm_plan=_parse_llm_plan,
        postprocess_llm_plan=_postprocess_llm_plan_request,
        validate_plan=_validate_plan_request,
    )


@_log_entry_exit("_job_from_event_payload")
def _job_from_event_payload(event: dict) -> models.Job | None:
    data = event.get("payload")
    if not isinstance(data, dict):
        return None
    try:
        return models.Job(**data)
    except Exception:
        job_id = data.get("id") or data.get("job_id")
        goal = data.get("goal")
        if not job_id or not goal:
            return None
        now = datetime.utcnow()
        return models.Job(
            id=job_id,
            goal=goal,
            context_json=data.get("context_json", {}),
            status=_parse_job_status(data.get("status")),
            created_at=_parse_datetime(data.get("created_at"), now),
            updated_at=_parse_datetime(data.get("updated_at"), now),
            priority=data.get("priority", 0),
            metadata=data.get("metadata", {}),
        )


def _parse_job_status(value: object) -> models.JobStatus:
    if isinstance(value, models.JobStatus):
        return value
    if isinstance(value, str):
        try:
            return models.JobStatus(value)
        except ValueError:
            return models.JobStatus.queued
    return models.JobStatus.queued


def _parse_datetime(value: object, fallback: datetime) -> datetime:
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return fallback
    return fallback


def _llm_prompt(job: models.Job, tools: List[models.ToolSpec]) -> str:
    request = planner_service.build_plan_request(
        job,
        tools,
        config=_planner_service_config(),
        runtime=_planner_service_runtime(),
        include_semantic_hints=True,
    )
    return _llm_prompt_from_request(request)


def _llm_prompt_from_request(request: planner_contracts.PlanRequest) -> str:
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
    combined_catalog = tool_catalog + capability_catalog
    tool_catalog_json = json.dumps(
        combined_catalog, ensure_ascii=False, indent=2, default=_json_fallback
    )
    semantic_capability_hints = request.semantic_capability_hints
    job_json = json.dumps(request.job_payload, ensure_ascii=False, indent=2, default=_json_fallback)
    max_depth = request.max_dependency_depth
    depth_hint = ""
    if max_depth:
        depth_hint = f"Max dependency chain depth: {max_depth}.\n"
    intent_graph_block = ""
    intent_graph = request.goal_intent_graph
    if intent_graph:
        intent_graph_json = json.dumps(
            intent_graph.model_dump(mode="json", exclude_none=True),
            ensure_ascii=False,
            indent=2,
            default=_json_fallback,
        )
        intent_graph_block = (
            "Goal intent decomposition graph (ordered hints for planning):\n"
            f"{intent_graph_json}\n"
            "Prefer preserving this segment order in tasks/dependencies.\n"
        )
    intent_repair_block = _intent_mismatch_recovery_block_from_request(request)
    semantic_capability_block = ""
    if semantic_capability_hints:
        semantic_capability_block = (
            "Most relevant capabilities for this goal from local semantic search:\n"
            f"{json.dumps(semantic_capability_hints, ensure_ascii=False, indent=2, default=_json_fallback)}\n"
            "Prefer these capabilities when they fit the goal and required inputs.\n"
        )
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


def _llm_plan_repair_prompt(
    *, original_prompt: str, raw_output: str, tools: List[models.ToolSpec]
) -> str:
    request = planner_contracts.PlanRequest(
        job_id="repair",
        goal="",
        tools=list(tools),
        capabilities=[
            planner_contracts.PlanRequestCapability(
                capability_id=capability_id,
                description=capability.description,
                risk_tier=capability.risk_tier,
                idempotency=capability.idempotency,
                group=capability.group,
                subgroup=capability.subgroup,
                input_schema_ref=capability.input_schema_ref,
                output_schema_ref=capability.output_schema_ref,
                planner_hints=(
                    dict(capability.planner_hints)
                    if isinstance(capability.planner_hints, dict)
                    else {}
                ),
                adapters=[
                    planner_contracts.PlanRequestCapabilityAdapter(
                        type=adapter.type,
                        server_id=adapter.server_id,
                        tool_name=adapter.tool_name,
                    )
                    for adapter in capability.adapters
                    if adapter.enabled
                ],
            )
            for capability_id, capability in _planner_capabilities().items()
        ],
    )
    return _llm_plan_repair_prompt_from_request(original_prompt, raw_output, request)


def _llm_plan_repair_prompt_from_request(
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


def _document_spec_prompt(job: models.Job, allowed_block_types: List[str]) -> str:
    return prompts.document_spec_prompt(job.model_dump(mode="json"), allowed_block_types)


@_log_entry_exit("_parse_llm_plan")
def _parse_llm_plan(content: str) -> models.PlanCreate | None:
    try:
        data = llm_provider.parse_json_object(content)
    except llm_provider.LLMProviderError:
        return None
    candidates = []
    inner = data.get("plan")
    if isinstance(inner, dict):
        candidates.append(inner)
    candidates.append(data)
    for candidate in candidates:
        try:
            return models.PlanCreate.model_validate(candidate)
        except Exception:
            continue
    return None


def _ensure_llm_tool(plan: models.PlanCreate) -> models.PlanCreate:
    updated_tasks = []
    for task in plan.tasks:
        if not task.tool_requests:
            updated_tasks.append(task.model_copy(update={"tool_requests": ["llm_generate"]}))
        else:
            updated_tasks.append(task)
    return plan.model_copy(update={"tasks": updated_tasks})


def _ensure_task_intents(
    plan: models.PlanCreate,
    tools: List[models.ToolSpec],
    goal_text: str = "",
    goal_intent_sequence: list[str] | None = None,
) -> models.PlanCreate:
    logger = core_logging.get_logger("planner")
    tool_map = {tool.name: tool for tool in tools}
    updated_tasks: list[models.TaskCreate] = []
    changed = False
    for index, task in enumerate(plan.tasks):
        unique_tool_intents = {
            tool_map[tool_name].tool_intent
            for tool_name in (task.tool_requests or [])
            if tool_name in tool_map
        }
        inference = intent_contract.infer_task_intent_for_task_with_metadata(
            explicit_intent=task.intent,
            description=task.description,
            instruction=task.instruction,
            acceptance_criteria=task.acceptance_criteria,
            goal_text=goal_text,
        )
        inferred = inference.intent
        intent_source = inference.source
        intent_confidence = float(inference.confidence)
        # If text inference falls back to generate, prefer known tool intent where unambiguous.
        if inferred == models.ToolIntent.generate.value and not task.intent:
            if len(unique_tool_intents) == 1:
                inferred = next(iter(unique_tool_intents)).value
                intent_source = "tool_intent"
                intent_confidence = 0.9
            elif goal_intent_sequence and index < len(goal_intent_sequence):
                hinted = intent_contract.normalize_task_intent(goal_intent_sequence[index])
                if hinted:
                    inferred = hinted
                    intent_source = "goal_graph"
                    intent_confidence = max(intent_confidence, 0.88)
        # LLM can emit explicit task intents that conflict with a task's only tool intent.
        # Auto-repair to the single tool intent so plan validation does not fail hard.
        if len(unique_tool_intents) == 1:
            has_mismatch = any(
                bool(
                    intent_contract.validate_tool_intent_compatibility(
                        inferred,
                        tool_map[tool_name].tool_intent,
                        tool_name,
                    )
                )
                for tool_name in (task.tool_requests or [])
                if tool_name in tool_map
            )
            if has_mismatch:
                inferred = next(iter(unique_tool_intents)).value
                intent_source = "tool_intent_repair"
                intent_confidence = max(intent_confidence, 0.93)
        try:
            normalized = models.ToolIntent(inferred)
        except ValueError:
            normalized = models.ToolIntent.generate
        logger.info(
            "task_intent_inferred",
            task_name=task.name,
            task_intent=normalized.value,
            intent_source=intent_source,
            intent_confidence=round(max(0.0, min(1.0, intent_confidence)), 3),
            has_explicit_intent=bool(task.intent),
        )
        if task.intent != normalized:
            updated_tasks.append(task.model_copy(update={"intent": normalized}))
            changed = True
        else:
            updated_tasks.append(task)
    if not changed:
        return plan
    return plan.model_copy(update={"tasks": updated_tasks})


def _job_goal_intent_graph(job: models.Job) -> workflow_contracts.IntentGraph | None:
    if not isinstance(job.metadata, dict):
        return None
    graph = workflow_contracts.parse_intent_graph(job.metadata.get("goal_intent_graph"))
    if graph is None or not graph.segments:
        return None
    return graph


def _job_goal_intent_sequence(job: models.Job) -> list[str]:
    graph = _job_goal_intent_graph(job)
    if not graph:
        return []
    sequence: list[str] = []
    for segment in graph.segments:
        normalized = intent_contract.normalize_task_intent(segment.intent)
        if normalized:
            sequence.append(normalized)
    return sequence


def _job_goal_intent_segments(job: models.Job) -> list[dict[str, Any]]:
    graph = _job_goal_intent_graph(job)
    if not graph:
        return []
    segments: list[dict[str, Any]] = []
    for segment in graph.segments:
        segments.append(segment.model_dump(mode="json", exclude_none=True))
    return segments


def _select_goal_intent_segment_for_task(
    *,
    task: models.TaskCreate,
    task_index: int,
    task_intent: str,
    goal_intent_segments: Sequence[dict[str, Any]],
    total_tasks: int,
    capabilities: Mapping[str, Any] | None = None,
) -> dict[str, Any] | None:
    if not goal_intent_segments:
        return None
    capabilities = dict(capabilities or _planner_capabilities())
    has_suggested_capabilities = any(
        isinstance(segment.get("suggested_capabilities"), list)
        and bool(segment.get("suggested_capabilities"))
        for segment in goal_intent_segments
    )
    task_requests = {str(name).strip().lower() for name in (task.tool_requests or []) if str(name).strip()}
    if task_requests:
        for segment in goal_intent_segments:
            suggested = segment.get("suggested_capabilities")
            if not isinstance(suggested, list):
                continue
            suggested_ids = set()
            for item in suggested:
                capability_id = str(item).strip().lower()
                if not capability_id:
                    continue
                suggested_ids.add(capability_id)
                capability = capabilities.get(capability_id)
                if capability is None:
                    continue
                for adapter in capability.adapters:
                    tool_name = str(adapter.tool_name or "").strip().lower()
                    if tool_name:
                        suggested_ids.add(tool_name)
            if suggested_ids & task_requests:
                return segment
    # If the intent graph already carries capability-level suggestions, avoid loose
    # fallback matching that can bind unrelated slot requirements to a task.
    if has_suggested_capabilities:
        if len(goal_intent_segments) == 1:
            only_segment = goal_intent_segments[0]
            if intent_contract.normalize_task_intent(only_segment.get("intent")) == task_intent:
                return only_segment
        return None
    for segment in goal_intent_segments:
        if intent_contract.normalize_task_intent(segment.get("intent")) == task_intent:
            return segment
    # Index fallback is only safe when decomposition cardinality equals plan cardinality.
    if (
        not has_suggested_capabilities
        and len(goal_intent_segments) == total_tasks
        and task_index < len(goal_intent_segments)
    ):
        return goal_intent_segments[task_index]
    return None


def _job_intent_mismatch_recovery(job: models.Job) -> dict[str, Any] | None:
    if not isinstance(job.metadata, dict):
        return None
    raw = job.metadata.get("intent_mismatch_recovery")
    if not isinstance(raw, dict):
        return None
    return raw


def _job_intent_mismatch_recovery_block(job: models.Job) -> str:
    recovery = _job_intent_mismatch_recovery(job)
    if not recovery:
        return ""
    return _format_intent_mismatch_recovery_block(recovery)


def _intent_mismatch_recovery_block_from_request(request: planner_contracts.PlanRequest) -> str:
    recovery = planner_contracts.intent_mismatch_recovery(request)
    if not recovery:
        return ""
    return _format_intent_mismatch_recovery_block(recovery)


def _format_intent_mismatch_recovery_block(recovery: Mapping[str, Any]) -> str:
    payload = json.dumps(recovery, ensure_ascii=False, indent=2, default=_json_fallback)
    guardrails = (
        "Intent mismatch auto-repair context:\n"
        f"{payload}\n"
        "Recovery rules:\n"
        "- Do not repeat the failing task/tool intent mismatch.\n"
        "- Ensure each task.intent matches the selected tool/capability intent policy.\n"
        "- If allowed_task_intents are provided, set task intent to one of them.\n"
        "- Keep dependencies valid while minimally modifying the prior plan shape.\n"
    )
    return guardrails


def _ensure_job_inputs(
    plan: models.PlanCreate, job: models.Job, tools: List[models.ToolSpec]
) -> models.PlanCreate:
    request = planner_contracts.build_plan_request(
        job,
        tools=tools,
        capabilities={},
        semantic_capability_hints=[],
        max_dependency_depth=_parse_optional_int(PLANNER_MAX_DEPTH),
    )
    return _ensure_job_inputs_for_request(plan, request)


def _ensure_job_inputs_for_request(
    plan: models.PlanCreate,
    request: planner_contracts.PlanRequest,
) -> models.PlanCreate:
    tool_map = {tool.name: tool for tool in request.tools}
    job_payload = request.job_payload
    updated_tasks = []
    for task in plan.tasks:
        tool_inputs = dict(task.tool_inputs) if isinstance(task.tool_inputs, dict) else {}
        changed = False
        for tool_name in task.tool_requests or []:
            tool = tool_map.get(tool_name)
            if tool is None:
                continue
            schema = tool.input_schema if isinstance(tool.input_schema, dict) else {}
            if not _schema_requires_key(schema, "job"):
                continue
            payload = tool_inputs.get(tool_name)
            payload = dict(payload) if isinstance(payload, dict) else {}
            existing_job = payload.get("job")
            if isinstance(existing_job, dict):
                # Resolve planner placeholders so downstream contract checks can inspect actual context.
                marker_keys = {str(key) for key in existing_job.keys()}
                if "$default" in marker_keys and bool(existing_job.get("$default")):
                    payload["job"] = job_payload
                elif marker_keys and marker_keys.issubset({"$default", "$from"}):
                    payload["job"] = job_payload
                else:
                    continue
            elif existing_job is not None:
                continue
            payload["job"] = job_payload
            tool_inputs[tool_name] = payload
            changed = True
        if changed:
            updated_tasks.append(task.model_copy(update={"tool_inputs": tool_inputs}))
        else:
            updated_tasks.append(task)
    return plan.model_copy(update={"tasks": updated_tasks})


def _ensure_default_value_markers(plan: models.PlanCreate, job: models.Job) -> models.PlanCreate:
    request = planner_contracts.build_plan_request(
        job,
        tools=[],
        capabilities={},
        semantic_capability_hints=[],
        max_dependency_depth=_parse_optional_int(PLANNER_MAX_DEPTH),
    )
    return _ensure_default_value_markers_for_request(plan, request)


def _ensure_default_value_markers_for_request(
    plan: models.PlanCreate,
    request: planner_contracts.PlanRequest,
) -> models.PlanCreate:
    job_context = request.job_context if isinstance(request.job_context, dict) else {}
    if not job_context:
        return plan
    tasks = [task.model_copy(deep=True) for task in plan.tasks]
    changed = False
    for task in tasks:
        if not isinstance(task.tool_inputs, dict):
            continue
        tool_inputs = dict(task.tool_inputs)
        task_changed = False
        for request_id, payload_raw in list(tool_inputs.items()):
            if not isinstance(payload_raw, dict):
                continue
            payload = dict(payload_raw)
            payload_changed = False
            for key, value in list(payload.items()):
                if not (isinstance(value, dict) and value.get("$default") is True):
                    continue
                replacement = job_context.get(key)
                if isinstance(replacement, str):
                    stripped = replacement.strip()
                    if stripped:
                        payload[key] = stripped
                        payload_changed = True
                        continue
                if isinstance(replacement, (int, float, bool)):
                    payload[key] = replacement
                    payload_changed = True
                    continue
                # No usable default in context: drop marker and allow later fillers/validators.
                payload.pop(key, None)
                payload_changed = True
            if payload_changed:
                tool_inputs[request_id] = payload
                task_changed = True
        if task_changed:
            task.tool_inputs = tool_inputs
            changed = True
    if not changed:
        return plan
    return plan.model_copy(update={"tasks": tasks})


def _postprocess_llm_plan_request(
    plan: models.PlanCreate,
    request: planner_contracts.PlanRequest,
) -> models.PlanCreate:
    candidate = _ensure_llm_tool(plan)
    candidate = _ensure_task_intents(
        candidate,
        request.tools,
        goal_text=request.goal,
        goal_intent_sequence=planner_contracts.goal_intent_sequence(request),
    )
    candidate = _ensure_job_inputs_for_request(candidate, request)
    candidate = _ensure_default_value_markers_for_request(candidate, request)
    candidate = _ensure_renderer_required_inputs(candidate)
    candidate = _ensure_tool_input_dependencies(candidate)
    candidate = _ensure_renderer_output_extensions(candidate)
    return _apply_max_depth_limit(candidate, request.max_dependency_depth)


def _ensure_renderer_output_extensions(plan: models.PlanCreate) -> models.PlanCreate:
    derive_request_ids, renderer_extension_by_request = _planner_renderer_hints()
    if not derive_request_ids or not renderer_extension_by_request:
        return plan
    task_by_name = {task.name: task for task in plan.tasks}
    derive_ext_requests: dict[str, set[str]] = {}

    for task in plan.tasks:
        if not task.tool_requests:
            continue
        tool_inputs = task.tool_inputs if isinstance(task.tool_inputs, dict) else {}
        for request_id in task.tool_requests:
            required_ext = renderer_extension_by_request.get(request_id)
            if not required_ext:
                continue
            payload = tool_inputs.get(request_id)
            if not isinstance(payload, dict):
                continue
            derive_task_name = _derive_task_name_from_path_reference(
                payload.get("path"), derive_request_ids
            )
            if not derive_task_name:
                continue
            derive_task = task_by_name.get(derive_task_name)
            if not derive_task or not any(
                tool in derive_request_ids for tool in (derive_task.tool_requests or [])
            ):
                continue
            derive_ext_requests.setdefault(derive_task_name, set()).add(required_ext)

    if not derive_ext_requests:
        return plan

    updated_tasks: list[models.TaskCreate] = []
    changed = False
    for task in plan.tasks:
        requested = derive_ext_requests.get(task.name)
        if not requested or len(requested) != 1:
            updated_tasks.append(task)
            continue
        derive_request_id = _derive_request_id_for_task(task, derive_request_ids)
        if not derive_request_id:
            updated_tasks.append(task)
            continue
        extension = next(iter(requested))
        tool_inputs = dict(task.tool_inputs) if isinstance(task.tool_inputs, dict) else {}
        payload = tool_inputs.get(derive_request_id)
        payload_dict = dict(payload) if isinstance(payload, dict) else {}
        task_changed = False
        if _normalize_extension_hint(payload_dict.get("output_extension")) != extension:
            payload_dict["output_extension"] = extension
            task_changed = True
        document_type = payload_dict.get("document_type")
        if not isinstance(document_type, str) or not document_type.strip():
            payload_dict["document_type"] = _infer_document_type_for_derive_task(
                task,
                task_by_name=task_by_name,
                all_tasks=plan.tasks,
            )
            task_changed = True
        if not task_changed:
            updated_tasks.append(task)
            continue
        tool_inputs[derive_request_id] = payload_dict
        updated_tasks.append(task.model_copy(update={"tool_inputs": tool_inputs}))
        changed = True
    if not changed:
        return plan
    return plan.model_copy(update={"tasks": updated_tasks})


def _infer_document_type_for_derive_task(
    task: models.TaskCreate,
    *,
    task_by_name: Mapping[str, models.TaskCreate],
    all_tasks: Sequence[models.TaskCreate],
) -> str:
    return "document"


def _planner_renderer_hints() -> tuple[set[str], dict[str, str]]:
    capabilities = _planner_capabilities()
    derive_request_ids: set[str] = set()
    renderer_extension_by_request: dict[str, str] = {}
    for capability_id, spec in capabilities.items():
        hints = spec.planner_hints if isinstance(spec.planner_hints, dict) else {}
        if bool(hints.get("derives_output_path")):
            derive_request_ids.add(capability_id)
        required_ext = hints.get("required_output_extension")
        normalized_ext = _normalize_extension_hint(required_ext)
        if normalized_ext:
            renderer_extension_by_request[capability_id] = normalized_ext
    return derive_request_ids, renderer_extension_by_request


def _derive_task_name_from_path_reference(
    path_value: Any, derive_request_ids: set[str]
) -> str | None:
    if not isinstance(path_value, dict):
        return None
    path_spec = path_value.get("$from")
    segments: list[Any]
    if isinstance(path_spec, list):
        segments = list(path_spec)
    elif isinstance(path_spec, str):
        raw = path_spec.strip()
        if not raw:
            return None
        segments = [segment for segment in raw.split(".") if segment]
    else:
        return None
    if len(segments) < 4:
        return None
    if segments[0] not in ("dependencies_by_name", "dependencies"):
        return None
    source_tool = str(segments[2])
    output_field = str(segments[3])
    if source_tool not in derive_request_ids:
        return None
    if output_field != "path":
        return None
    return str(segments[1])


def _reference_task_name_from_from_spec(from_spec: Any) -> str | None:
    segments: list[Any]
    if isinstance(from_spec, list):
        segments = list(from_spec)
    elif isinstance(from_spec, str):
        raw = from_spec.strip()
        if not raw:
            return None
        segments = [segment for segment in raw.split(".") if segment]
    else:
        return None
    if len(segments) < 2:
        return None
    if segments[0] not in ("dependencies_by_name", "dependencies"):
        return None
    task_name = str(segments[1]).strip()
    return task_name or None


def _collect_referenced_task_names(value: Any) -> set[str]:
    names: set[str] = set()
    if isinstance(value, dict):
        if "$from" in value:
            ref_name = _reference_task_name_from_from_spec(value.get("$from"))
            if ref_name:
                names.add(ref_name)
        for child in value.values():
            names.update(_collect_referenced_task_names(child))
        return names
    if isinstance(value, list):
        for item in value:
            names.update(_collect_referenced_task_names(item))
    return names


def _ensure_tool_input_dependencies(plan: models.PlanCreate) -> models.PlanCreate:
    task_names = {task.name for task in plan.tasks}
    tasks = [task.model_copy(deep=True) for task in plan.tasks]
    changed = False
    for task in tasks:
        referenced = _collect_referenced_task_names(task.tool_inputs)
        if not referenced:
            continue
        deps = list(task.deps or [])
        dep_set = set(deps)
        for dep_name in sorted(referenced):
            if dep_name == task.name or dep_name not in task_names or dep_name in dep_set:
                continue
            deps.append(dep_name)
            dep_set.add(dep_name)
            changed = True
        if deps != list(task.deps or []):
            task.deps = deps
    if not changed:
        return plan

    edges: list[list[str]] = []
    existing_edges: set[tuple[str, str]] = set()
    for edge in plan.dag_edges or []:
        if not isinstance(edge, list) or len(edge) != 2:
            continue
        from_node = str(edge[0])
        to_node = str(edge[1])
        pair = (from_node, to_node)
        if pair in existing_edges:
            continue
        existing_edges.add(pair)
        edges.append([from_node, to_node])
    for task in tasks:
        for dep_name in task.deps or []:
            pair = (dep_name, task.name)
            if pair in existing_edges:
                continue
            existing_edges.add(pair)
            edges.append([dep_name, task.name])
    return plan.model_copy(update={"tasks": tasks, "dag_edges": edges})


def _ensure_renderer_required_inputs(plan: models.PlanCreate) -> models.PlanCreate:
    tasks = [task.model_copy(deep=True) for task in plan.tasks]
    task_by_name = {task.name: task for task in tasks}
    changed = False
    renderer_requests = {
        "docx_generate_from_spec",
        "pdf_generate_from_spec",
        "document.docx.generate",
        "document.pdf.generate",
    }
    document_spec_consumer_requests = {
        "document_spec_validate",
        "document.spec.validate",
    }
    document_spec_producers = {
        "document.spec.generate",
        "document_spec_generate",
        "llm_generate_document_spec",
        "llm_repair_document_spec",
        "llm_improve_document_spec",
        "llm_iterative_improve_document_spec",
        "document.spec.repair",
    }
    def _ref_task_exists(value: Any) -> bool:
        if not isinstance(value, dict):
            return False
        ref_task = _reference_task_name_from_from_spec(value.get("$from"))
        if not ref_task:
            return False
        return ref_task in task_by_name

    def _find_source_task_name(
        current_task: models.TaskCreate,
        index: int,
        producer_requests: set[str],
    ) -> tuple[str | None, str | None]:
        deps = [str(dep) for dep in (current_task.deps or [])]
        for dep_name in deps:
            dep_task = task_by_name.get(dep_name)
            if not dep_task:
                continue
            for req in dep_task.tool_requests or []:
                req_name = str(req)
                if req_name in producer_requests:
                    return dep_task.name, req_name
        for dep_task in tasks[:index]:
            for req in dep_task.tool_requests or []:
                req_name = str(req)
                if req_name in producer_requests:
                    return dep_task.name, req_name
        for dep_task in tasks:
            if dep_task.name == current_task.name:
                continue
            for req in dep_task.tool_requests or []:
                req_name = str(req)
                if req_name in producer_requests:
                    return dep_task.name, req_name
        return None, None

    for index, task in enumerate(tasks):
        request_id = next(
            (
                req
                for req in (task.tool_requests or [])
                if str(req) in renderer_requests
                or str(req) in document_spec_consumer_requests
            ),
            None,
        )
        if request_id is None:
            continue
        request_id = str(request_id)
        tool_inputs = dict(task.tool_inputs) if isinstance(task.tool_inputs, dict) else {}
        payload_raw = tool_inputs.get(request_id)
        payload = dict(payload_raw) if isinstance(payload_raw, dict) else {}

        has_valid_document_spec_ref = _ref_task_exists(payload.get("document_spec"))
        if ("document_spec" not in payload) or (
            isinstance(payload.get("document_spec"), dict) and not has_valid_document_spec_ref
        ):
            source_task_name, source_request_id = _find_source_task_name(
                task, index, document_spec_producers
            )
            if source_task_name and source_request_id:
                payload["document_spec"] = {
                    "$from": (
                        f"dependencies_by_name.{source_task_name}."
                        f"{source_request_id}.document_spec"
                    )
                }
                changed = True

        if request_id in renderer_requests:
            has_valid_path_ref = _ref_task_exists(payload.get("path"))
            has_valid_output_path_ref = _ref_task_exists(payload.get("output_path"))
            if isinstance(payload.get("path"), dict) and not has_valid_path_ref:
                payload.pop("path", None)
                changed = True
            if isinstance(payload.get("output_path"), dict) and not has_valid_output_path_ref:
                payload.pop("output_path", None)
                changed = True

        tool_inputs[request_id] = payload
        task.tool_inputs = tool_inputs

    if not changed:
        return plan
    return plan.model_copy(update={"tasks": tasks})


def _derive_request_id_for_task(
    task: models.TaskCreate, derive_request_ids: set[str]
) -> str | None:
    for request_id in task.tool_requests or []:
        if request_id in derive_request_ids:
            return request_id
    return None


def _normalize_extension_hint(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    normalized = value.strip().lower()
    if normalized.startswith("."):
        normalized = normalized[1:]
    if normalized == "markdown":
        normalized = "md"
    return normalized


def _validate_plan(
    plan: models.PlanCreate, tools: List[models.ToolSpec], job: models.Job
) -> tuple[bool, str]:
    request = planner_contracts.build_plan_request(
        job,
        tools=tools,
        capabilities=_planner_capabilities(),
        semantic_capability_hints=[],
        max_dependency_depth=_parse_optional_int(PLANNER_MAX_DEPTH),
    )
    return _validate_plan_request(plan, request)


def _validate_plan_request(
    plan: models.PlanCreate,
    request: planner_contracts.PlanRequest,
) -> tuple[bool, str]:
    tool_map = {tool.name: tool for tool in request.tools}
    tool_schemas = {tool.name: tool.input_schema or {} for tool in request.tools}
    capabilities = planner_contracts.capability_map(request)
    goal_intent_segments = planner_contracts.goal_intent_segments(request)
    for task_index, task in enumerate(plan.tasks):
        if not task.tool_requests:
            continue
        task_intent = _resolve_task_intent_for_validation(task, tool_map, goal_text=request.goal)
        if not task_intent:
            return False, f"missing_task_intent:{task.name}"
        goal_intent_segment = _select_goal_intent_segment_for_task(
            task=task,
            task_index=task_index,
            task_intent=task_intent,
            goal_intent_segments=goal_intent_segments,
            total_tasks=len(plan.tasks),
            capabilities=capabilities,
        )
        for tool_name in task.tool_requests:
            tool = tool_map.get(tool_name)
            capability = capabilities.get(tool_name)
            raw_tool_inputs = {}
            if isinstance(task.tool_inputs, dict) and tool_name in task.tool_inputs:
                entry = task.tool_inputs.get(tool_name)
                if not isinstance(entry, dict):
                    return False, f"tool_inputs_invalid:{tool_name}:{task.name}:payload_not_object"
                raw_tool_inputs = dict(entry)
            segment_payload = raw_tool_inputs
            if tool is not None:
                segment_payload = _build_validation_payload_for_request(
                    task,
                    tool,
                    request,
                    raw_tool_inputs,
                )
            elif capability is not None:
                segment_payload = _build_capability_validation_payload_for_request(
                    task,
                    raw_tool_inputs,
                    request,
                )
            segment_contract_error = intent_contract.validate_intent_segment_contract(
                segment=goal_intent_segment,
                task_intent=task_intent,
                tool_name=tool_name,
                payload=segment_payload,
                capability_id=tool_name if capability is not None else None,
                capability_risk_tier=capability.risk_tier if capability is not None else None,
            )
            if segment_contract_error:
                return (
                    False,
                    f"intent_segment_invalid:{tool_name}:{task.name}:{segment_contract_error}",
                )
            if tool is None and capability is None:
                return False, f"unknown_tool_or_capability:{tool_name}"
            if tool is None and capability is not None:
                capability_mismatch = _capability_intent_mismatch(
                    task_intent,
                    capability,
                    tool_name,
                )
                if capability_mismatch:
                    return False, f"capability_intent_invalid:{tool_name}:{task.name}:{capability_mismatch}"
                validation_error = _validate_capability_inputs(
                    capability,
                    task,
                    raw_tool_inputs,
                    request,
                )
                if validation_error:
                    return (
                        False,
                        f"capability_inputs_invalid:{tool_name}:{task.name}:{validation_error}",
                    )
                continue
            governance_context = planner_contracts.governance_context(request)
            allow_decision = tool_registry.evaluate_tool_allowlist(
                tool_name,
                "planner",
                context=governance_context,
                tool_spec=tool,
            )
            if not allow_decision.allowed:
                return False, f"tool_not_allowed:{tool_name}:{allow_decision.reason}"
            if allow_decision.violated and allow_decision.mode == "dry_run":
                core_logging.get_logger("planner").warning(
                    "tool_governance_violation_dry_run",
                    tool_name=tool_name,
                    mode=allow_decision.mode,
                    reason=allow_decision.reason,
                    task_name=task.name,
                    job_id=request.job_id,
                )
            mismatch = intent_contract.validate_tool_intent_compatibility(
                task_intent,
                tool.tool_intent,
                tool_name,
            )
            if mismatch:
                return False, f"{mismatch}:task={task.name}"
            validation_payload = _build_validation_payload_for_request(
                task,
                tool,
                request,
                raw_tool_inputs,
            )
            validation_errors = payload_resolver.validate_tool_inputs(
                {tool_name: validation_payload}, tool_schemas
            )
            message = validation_errors.get(tool_name)
            if message:
                return False, f"tool_inputs_invalid:{tool_name}:{task.name}:{message}"
    return True, "ok"


def _resolve_task_intent_for_validation(
    task: models.TaskCreate,
    tool_map: dict[str, models.ToolSpec],
    goal_text: str = "",
) -> str:
    inference = intent_contract.infer_task_intent_for_task_with_metadata(
        explicit_intent=task.intent,
        description=task.description,
        instruction=task.instruction,
        acceptance_criteria=task.acceptance_criteria,
        goal_text=goal_text,
    )
    inferred = inference.intent
    if inferred == models.ToolIntent.generate.value and not task.intent:
        unique_tool_intents = {
            tool_map[tool_name].tool_intent
            for tool_name in (task.tool_requests or [])
            if tool_name in tool_map
        }
        if len(unique_tool_intents) == 1:
            inferred = next(iter(unique_tool_intents)).value
    return inferred


def _capability_intent_mismatch(
    task_intent: str,
    capability: capability_registry.CapabilitySpec,
    capability_id: str,
) -> str | None:
    hints = capability.planner_hints if isinstance(capability.planner_hints, dict) else {}
    raw_allowed = hints.get("task_intents")
    if not isinstance(raw_allowed, list) or not raw_allowed:
        return None
    allowed = {
        normalized
        for item in raw_allowed
        for normalized in [intent_contract.normalize_task_intent(item)]
        if normalized
    }
    if not allowed:
        return None
    if task_intent in allowed:
        return None
    return f"task_intent_mismatch:{capability_id}:{task_intent}:allowed={','.join(sorted(allowed))}"


def _build_validation_payload(
    task: models.TaskCreate,
    tool: models.ToolSpec,
    job: models.Job,
    raw_tool_inputs: dict,
) -> dict:
    request = planner_contracts.build_plan_request(
        job,
        tools=[tool],
        capabilities={},
        semantic_capability_hints=[],
        max_dependency_depth=_parse_optional_int(PLANNER_MAX_DEPTH),
    )
    return _build_validation_payload_for_request(task, tool, request, raw_tool_inputs)


def _build_validation_payload_for_request(
    task: models.TaskCreate,
    tool: models.ToolSpec,
    request: planner_contracts.PlanRequest,
    raw_tool_inputs: dict,
) -> dict:
    payload = payload_resolver.normalize_reference_payload_for_validation(
        dict(raw_tool_inputs),
        dependency_defaults=_dependency_fill_defaults(),
    )
    payload.setdefault("tool_inputs", dict(raw_tool_inputs))
    if "instruction" not in payload and isinstance(task.instruction, str) and task.instruction.strip():
        payload["instruction"] = task.instruction.strip()
    schema = tool.input_schema if isinstance(tool.input_schema, dict) else {}
    if _schema_requires_key(schema, "job"):
        payload.setdefault("job", request.job_payload)
    if task.deps:
        for key, default_value in _dependency_fill_defaults().items():
            payload.setdefault(key, default_value)
    if isinstance(tool.memory_reads, list) and tool.memory_reads:
        payload.setdefault("memory", {})
    job_context = request.job_context if isinstance(request.job_context, dict) else {}
    for key in (
        "instruction",
        "topic",
        "audience",
        "tone",
        "today",
        "date",
        "target_pages",
        "page_count",
        "target_role_name",
        "role_name",
        "company_name",
        "company",
        "candidate_name",
        "first_name",
        "last_name",
        "job_description",
        "output_dir",
        "document_type",
    ):
        if key in payload:
            continue
        value = job_context.get(key)
        if isinstance(value, str) and value.strip():
            payload[key] = value
            continue
        if isinstance(value, (int, float, bool)):
            payload[key] = value
    # Planner-time validation should account for deterministic runtime date defaults.
    if "today" not in payload and "date" not in payload:
        payload["today"] = datetime.utcnow().date().isoformat()
    return payload


def _dependency_fill_defaults() -> dict[str, object]:
    return {
        "content": "__dependency__",
        "text": "__dependency__",
        "prompt": "__dependency__",
        "data": {},
        "document_spec": {},
        "validation_report": {},
        "errors": [],
        "original_spec": {},
        "openapi_spec": {},
    }


def _planner_capabilities() -> dict[str, capability_registry.CapabilitySpec]:
    mode = capability_registry.resolve_capability_mode()
    if mode == "disabled":
        return {}
    try:
        registry = capability_registry.load_capability_registry()
    except Exception as exc:  # noqa: BLE001
        core_logging.get_logger("planner").warning(
            "capability_registry_load_failed",
            mode=mode,
            error=str(exc),
        )
        return {}
    return dict(sorted(registry.enabled_capabilities().items()))


def _emit_plan_event(
    event_type: str,
    *,
    job_id: str | None,
    correlation_id: str | None,
    payload: dict[str, Any],
) -> None:
    event = models.EventEnvelope(
        type=event_type,
        version="1",
        occurred_at=datetime.utcnow(),
        correlation_id=correlation_id or str(uuid.uuid4()),
        job_id=job_id,
        payload=payload,
    )
    try:
        redis_client.xadd(events.PLAN_STREAM, {"data": event.model_dump_json()})
    except Exception as exc:  # noqa: BLE001
        core_logging.get_logger("planner").warning(
            "plan_event_emit_failed",
            event_type=event_type,
            job_id=job_id,
            error=str(exc),
        )


def _planner_semantic_capability_hints(
    job: models.Job,
    capabilities: Mapping[str, capability_registry.CapabilitySpec],
    *,
    correlation_id: str | None = None,
    limit: int = 10,
) -> list[dict[str, Any]]:
    entries = capability_search.build_capability_search_entries(capabilities)
    started = perf_counter()
    matches = capability_search.search_capabilities(
        query=job.goal,
        capability_entries=entries,
        limit=limit,
    )
    latency_ms = round((perf_counter() - started) * 1000.0, 3)
    _emit_plan_event(
        "plan.capability_search",
        job_id=job.id,
        correlation_id=correlation_id,
        payload={
            "job_id": job.id,
            "goal": job.goal,
            "request_source": "planner_prompt",
            "limit": limit,
            "latency_ms": latency_ms,
            "results": matches,
            "result_count": len(matches),
        },
    )
    return matches


def _emit_planner_capability_selection_event(
    job: models.Job,
    plan: models.PlanCreate,
    *,
    correlation_id: str | None = None,
) -> None:
    selected_capabilities: list[str] = []
    for task in plan.tasks:
        for tool_name in task.tool_requests or []:
            normalized = str(tool_name or "").strip()
            if normalized and normalized not in selected_capabilities:
                selected_capabilities.append(normalized)
    _emit_plan_event(
        "plan.capability_selection",
        job_id=job.id,
        correlation_id=correlation_id,
        payload={
            "job_id": job.id,
            "goal": job.goal,
            "planner_version": plan.planner_version,
            "selected_capabilities": selected_capabilities,
            "task_count": len(plan.tasks),
        },
    )


def _validate_capability_inputs(
    capability: capability_registry.CapabilitySpec | planner_contracts.PlanRequestCapability,
    task: models.TaskCreate,
    raw_tool_inputs: dict[str, Any],
    job_or_request: models.Job | planner_contracts.PlanRequest,
) -> str | None:
    request = (
        job_or_request
        if isinstance(job_or_request, planner_contracts.PlanRequest)
        else planner_contracts.build_plan_request(
            job_or_request,
            tools=[],
            capabilities={},
            semantic_capability_hints=[],
            max_dependency_depth=_parse_optional_int(PLANNER_MAX_DEPTH),
        )
    )
    if not capability.input_schema_ref:
        return None
    schema = _load_schema_from_ref(capability.input_schema_ref)
    if schema is None:
        return f"capability_schema_not_found:{capability.input_schema_ref}"
    payload = _build_capability_validation_payload_for_request(task, raw_tool_inputs, request)
    if capability.capability_id == "github.repo.list":
        job_context = request.job_context if isinstance(request.job_context, dict) else {}
        github_query = _synthesize_github_repo_query(
            raw_tool_inputs=raw_tool_inputs,
            payload=payload,
            job_context=job_context,
        )
        if github_query:
            payload["query"] = github_query
    errors = payload_resolver.validate_tool_inputs(
        {capability.capability_id: payload},
        {capability.capability_id: schema},
    )
    return errors.get(capability.capability_id)


def _synthesize_github_repo_query(
    *,
    raw_tool_inputs: Mapping[str, Any] | None,
    payload: Mapping[str, Any] | None,
    job_context: Mapping[str, Any] | None,
) -> str | None:
    def _read_str(source: Mapping[str, Any] | None, *keys: str) -> str | None:
        if not isinstance(source, Mapping):
            return None
        for key in keys:
            value = source.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        return None

    owner = (
        _read_str(raw_tool_inputs, "owner", "repo_owner")
        or _read_str(payload, "owner", "repo_owner")
        or _read_str(job_context, "owner", "repo_owner")
    )
    repo = (
        _read_str(raw_tool_inputs, "repo", "repo_name")
        or _read_str(payload, "repo", "repo_name")
        or _read_str(job_context, "repo", "repo_name")
    )
    if owner and repo:
        return f"repo:{repo} owner:{owner}"
    return (
        _read_str(raw_tool_inputs, "query", "github_query")
        or _read_str(payload, "query", "github_query")
        or _read_str(job_context, "query", "github_query")
    )


def _load_schema_from_ref(schema_ref: str) -> dict[str, Any] | None:
    candidate = Path(schema_ref)
    if not candidate.is_absolute():
        candidate = Path(SCHEMA_REGISTRY_PATH) / (
            schema_ref if schema_ref.endswith(".json") else f"{schema_ref}.json"
        )
    if not candidate.exists():
        return None
    try:
        parsed = json.loads(candidate.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return None
    return parsed if isinstance(parsed, dict) else None


def _build_capability_validation_payload(
    task: models.TaskCreate,
    raw_tool_inputs: dict[str, Any],
    job: models.Job,
) -> dict[str, Any]:
    request = planner_contracts.build_plan_request(
        job,
        tools=[],
        capabilities={},
        semantic_capability_hints=[],
        max_dependency_depth=_parse_optional_int(PLANNER_MAX_DEPTH),
    )
    return _build_capability_validation_payload_for_request(task, raw_tool_inputs, request)


def _build_capability_validation_payload_for_request(
    task: models.TaskCreate,
    raw_tool_inputs: dict[str, Any],
    request: planner_contracts.PlanRequest,
) -> dict[str, Any]:
    payload = payload_resolver.normalize_reference_payload_for_validation(
        dict(raw_tool_inputs),
        dependency_defaults=_dependency_fill_defaults(),
    )
    payload.setdefault("tool_inputs", dict(raw_tool_inputs))
    if task.deps:
        for key, default_value in _dependency_fill_defaults().items():
            payload.setdefault(key, default_value)
    job_context = request.job_context if isinstance(request.job_context, dict) else {}
    for key in (
        "instruction",
        "topic",
        "audience",
        "tone",
        "today",
        "date",
        "target_pages",
        "page_count",
        "target_role_name",
        "role_name",
        "company_name",
        "company",
        "candidate_name",
        "first_name",
        "last_name",
        "job_description",
        "output_dir",
        "document_type",
    ):
        if key in payload:
            continue
        value = job_context.get(key)
        if isinstance(value, str) and value.strip():
            payload[key] = value
            continue
        if isinstance(value, (int, float, bool)):
            payload[key] = value
    if task.tool_requests and "github.repo.list" in task.tool_requests:
        github_query = _synthesize_github_repo_query(
            raw_tool_inputs=raw_tool_inputs,
            payload=payload,
            job_context=job_context,
        )
        if github_query:
            payload["query"] = github_query
    # Keep capability schema validation aligned with deterministic runtime date defaults.
    if "today" not in payload and "date" not in payload:
        payload["today"] = datetime.utcnow().date().isoformat()
    return payload


def _schema_requires_key(schema: dict, key: str) -> bool:
    if not isinstance(schema, dict):
        return False
    required = schema.get("required")
    if isinstance(required, list) and key in required:
        return True
    for keyword in ("allOf", "anyOf", "oneOf"):
        entries = schema.get(keyword)
        if not isinstance(entries, list):
            continue
        for entry in entries:
            if isinstance(entry, dict) and _schema_requires_key(entry, key):
                return True
    return False


def _parse_optional_float(value: str | None) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except ValueError:
        return None


def _parse_optional_int(value: str | None) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except ValueError:
        return None


def _apply_max_depth(plan: models.PlanCreate) -> models.PlanCreate:
    return _apply_max_depth_limit(plan, _parse_optional_int(PLANNER_MAX_DEPTH))


def _apply_max_depth_limit(
    plan: models.PlanCreate,
    max_depth: int | None,
) -> models.PlanCreate:
    if not max_depth or max_depth <= 0:
        return plan
    tasks = [task.model_copy(deep=True) for task in plan.tasks]
    for _ in range(len(tasks) + 1):
        depths = _task_depths(tasks, max_depth)
        current_max = max(depths.values(), default=0)
        if current_max <= max_depth:
            break
        changed = False
        for task in tasks:
            if not task.deps:
                continue
            allowed = [dep for dep in task.deps if depths.get(dep, 1) < max_depth]
            if allowed != task.deps:
                task.deps = allowed
                changed = True
        if not changed:
            for task in tasks:
                if depths.get(task.name, 1) > max_depth and task.deps:
                    task.deps = []
                    changed = True
            if not changed:
                break
    return plan.model_copy(update={"tasks": tasks})


def _task_depths(tasks: List[models.TaskCreate], limit: int) -> dict[str, int]:
    by_name = {task.name: task for task in tasks}
    depth_cache: dict[str, int] = {}
    visiting: set[str] = set()

    def depth_for(name: str) -> int:
        if name in depth_cache:
            return depth_cache[name]
        if name in visiting:
            return limit + 1
        visiting.add(name)
        task = by_name.get(name)
        if not task:
            visiting.remove(name)
            return 1
        max_depth = 1
        for dep in task.deps:
            max_depth = max(max_depth, depth_for(dep) + 1)
            if max_depth > limit:
                break
        visiting.remove(name)
        depth_cache[name] = max_depth
        return max_depth

    for task in tasks:
        depth_for(task.name)
    return depth_cache


def run() -> None:
    global _METRICS_SERVER_STARTED
    if not _METRICS_SERVER_STARTED:
        start_http_server(METRICS_PORT)
        _METRICS_SERVER_STARTED = True
    group = "planner"
    consumer = str(uuid.uuid4())
    try:
        redis_client.xgroup_create(events.JOB_STREAM, group, id="0-0", mkstream=True)
    except redis.ResponseError:
        pass
    while True:
        messages = redis_client.xreadgroup(
            group, consumer, {events.JOB_STREAM: ">"}, count=1, block=1000
        )
        for _, entries in messages:
            for message_id, data in entries:
                payload = json.loads(data["data"])
                job = _job_from_event_payload(payload)
                if not job:
                    redis_client.xack(events.JOB_STREAM, group, message_id)
                    continue
                try:
                    plan = plan_job(job)
                    correlation_id = str(payload.get("correlation_id", str(uuid.uuid4())))
                    _emit_plan_event(
                        "plan.created",
                        job_id=job.id,
                        correlation_id=correlation_id,
                        payload=plan.model_dump(),
                    )
                    _emit_planner_capability_selection_event(
                        job,
                        plan,
                        correlation_id=correlation_id,
                    )
                except Exception as exc:  # noqa: BLE001
                    _emit_plan_event(
                        "plan.failed",
                        job_id=job.id,
                        correlation_id=str(payload.get("correlation_id", str(uuid.uuid4()))),
                        payload={"job_id": job.id, "error": str(exc)},
                    )
                redis_client.xack(events.JOB_STREAM, group, message_id)


if __name__ == "__main__":
    run()
