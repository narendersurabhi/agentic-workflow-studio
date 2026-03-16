from __future__ import annotations

from typing import Any, Mapping

_DOCUMENT_GENERATION_TOOL_NAMES = {
    "llm_generate_document_spec",
    "llm_iterative_improve_document_spec",
    "llm_iterative_improve_runbook_spec",
}

_DOCUMENT_JOB_TOP_LEVEL_KEYS = (
    "instruction",
    "topic",
    "audience",
    "tone",
    "today",
    "output_dir",
    "document_type",
)

_DOCUMENT_JOB_CONTEXT_KEYS = (
    "markdown_text",
    "topic",
    "audience",
    "tone",
    "today",
    "output_dir",
    "document_type",
    "target_role_name",
    "role_name",
    "company_name",
    "company",
    "candidate_name",
    "first_name",
    "last_name",
    "job_description",
)


def project_job_payload_for_tool(
    tool_name: str,
    job_payload: Mapping[str, Any] | None,
    *,
    default_goal: str | None = None,
) -> dict[str, Any]:
    if not isinstance(job_payload, Mapping):
        return {}
    if str(tool_name).strip() in _DOCUMENT_GENERATION_TOOL_NAMES:
        return compact_document_job_payload(job_payload, default_goal=default_goal)
    return dict(job_payload)


def compact_document_job_payload(
    job_payload: Mapping[str, Any] | None,
    *,
    default_goal: str | None = None,
) -> dict[str, Any]:
    if not isinstance(job_payload, Mapping):
        return {}

    compact: dict[str, Any] = {}
    goal = default_goal or job_payload.get("goal")
    _copy_compact_value(compact, "goal", goal)

    for key in _DOCUMENT_JOB_TOP_LEVEL_KEYS:
        _copy_compact_value(compact, key, job_payload.get(key))

    context_json = job_payload.get("context_json")
    if isinstance(context_json, Mapping):
        compact_context: dict[str, Any] = {}
        for key in _DOCUMENT_JOB_CONTEXT_KEYS:
            _copy_compact_value(compact_context, key, context_json.get(key))
        if compact_context:
            compact["context_json"] = compact_context

    return compact or dict(job_payload)


def _copy_compact_value(target: dict[str, Any], key: str, value: Any) -> None:
    if isinstance(value, str):
        if value.strip():
            target[key] = value
        return
    if isinstance(value, (int, float, bool)):
        target[key] = value
