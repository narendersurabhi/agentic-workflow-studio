from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from libs.core import prompts_resume_analysis
from libs.core.llm_provider import LLMProvider
from libs.core.models import RiskLevel, ToolIntent, ToolSpec
from libs.framework.tool_runtime import Tool, ToolExecutionError, validate_schema


def register_resume_analysis_tools(registry, llm_provider: LLMProvider, timeout_s: int) -> None:
    registry.register(
        Tool(
            spec=ToolSpec(
                name="jd_analyze",
                description="Analyze a job description into structured hiring signals.",
                input_schema={
                    "type": "object",
                    "properties": {"job_description": {"type": "string", "minLength": 1}},
                    "required": ["job_description"],
                },
                output_schema=_load_schema("jd_analysis_output.json"),
                timeout_s=timeout_s,
                risk_level=RiskLevel.high,
                tool_intent=ToolIntent.generate,
            ),
            handler=lambda payload, provider=llm_provider: jd_analyze(payload, provider),
        )
    )

    registry.register(
        Tool(
            spec=ToolSpec(
                name="resume_example_generate",
                description="Generate a reference-only ideal example resume for a job description.",
                input_schema={
                    "type": "object",
                    "properties": {
                        "job_description": {"type": "string", "minLength": 1},
                        "jd_analysis": {"type": "object"},
                        "candidate_level": {"type": "string"},
                        "target_role_name": {"type": "string"},
                    },
                    "required": ["job_description", "jd_analysis"],
                },
                output_schema=_load_schema("resume_example_generate_output.json"),
                timeout_s=timeout_s,
                risk_level=RiskLevel.high,
                tool_intent=ToolIntent.generate,
            ),
            handler=lambda payload, provider=llm_provider: resume_example_generate(payload, provider),
        )
    )

    registry.register(
        Tool(
            spec=ToolSpec(
                name="resume_gap_detect",
                description="Detect resume-to-job-description gaps and section-level improvements.",
                input_schema={
                    "type": "object",
                    "properties": {
                        "candidate_resume": {"type": "string", "minLength": 1},
                        "jd_analysis": {"type": "object"},
                    },
                    "required": ["candidate_resume", "jd_analysis"],
                },
                output_schema=_load_schema("resume_gap_detect_output.json"),
                timeout_s=timeout_s,
                risk_level=RiskLevel.high,
                tool_intent=ToolIntent.transform,
            ),
            handler=lambda payload, provider=llm_provider: resume_gap_detect(payload, provider),
        )
    )

    registry.register(
        Tool(
            spec=ToolSpec(
                name="resume_gap_report_generate",
                description="Generate a concrete resume improvement report from gap analysis.",
                input_schema={
                    "type": "object",
                    "properties": {
                        "candidate_resume": {"type": "string", "minLength": 1},
                        "jd_analysis": {"type": "object"},
                        "gap_detection": {"type": "object"},
                    },
                    "required": ["candidate_resume", "jd_analysis", "gap_detection"],
                },
                output_schema=_load_schema("resume_gap_report_generate_output.json"),
                timeout_s=timeout_s,
                risk_level=RiskLevel.high,
                tool_intent=ToolIntent.generate,
            ),
            handler=lambda payload, provider=llm_provider: resume_gap_report_generate(
                payload, provider
            ),
        )
    )

    registry.register(
        Tool(
            spec=ToolSpec(
                name="resume_skill_inject",
                description="Inject specific skill terms into relevant resume sections to improve impact.",
                input_schema=_load_schema("resume_skill_inject_capability_input.json"),
                output_schema=_load_schema("resume_skill_inject_output.json"),
                timeout_s=timeout_s,
                risk_level=RiskLevel.high,
                tool_intent=ToolIntent.transform,
            ),
            handler=lambda payload, provider=llm_provider: resume_skill_inject(payload, provider),
        )
    )


def jd_analyze(payload: dict[str, Any], provider: LLMProvider) -> dict[str, Any]:
    job_description = _require_string(payload, "job_description")
    prompt = prompts_resume_analysis.jd_analysis_prompt(job_description)
    result = _parse_json_object_response(provider.generate(prompt).content)
    _validate_against_schema("jd_analysis_output.json", result, "output")
    return result


def resume_example_generate(payload: dict[str, Any], provider: LLMProvider) -> dict[str, Any]:
    job_description = _require_string(payload, "job_description")
    jd_analysis = _require_object(payload, "jd_analysis")
    target_role_name = _optional_string(payload, "target_role_name")
    prompt = prompts_resume_analysis.resume_example_prompt(
        job_description, jd_analysis, target_role_name=target_role_name
    )
    result = _parse_json_object_response(provider.generate(prompt).content)
    _validate_against_schema("resume_example_generate_output.json", result, "output")
    return result


def resume_gap_detect(payload: dict[str, Any], provider: LLMProvider) -> dict[str, Any]:
    candidate_resume = _require_string(payload, "candidate_resume")
    jd_analysis = _require_object(payload, "jd_analysis")
    prompt = prompts_resume_analysis.resume_gap_detect_prompt(candidate_resume, jd_analysis)
    result = _parse_json_object_response(provider.generate(prompt).content)
    _validate_against_schema("resume_gap_detect_output.json", result, "output")
    return result


def resume_gap_report_generate(payload: dict[str, Any], provider: LLMProvider) -> dict[str, Any]:
    candidate_resume = _require_string(payload, "candidate_resume")
    jd_analysis = _require_object(payload, "jd_analysis")
    gap_detection = _require_object(payload, "gap_detection")
    prompt = prompts_resume_analysis.resume_gap_report_prompt(
        candidate_resume, jd_analysis, gap_detection
    )
    result = _parse_json_object_response(provider.generate(prompt).content)
    _validate_against_schema("resume_gap_report_generate_output.json", result, "output")
    return result


def resume_skill_inject(payload: dict[str, Any], provider: LLMProvider) -> dict[str, Any]:
    tailored_resume = _require_object(payload, "tailored_resume")
    skills = _require_string_list(payload, "skills")
    target_sections = _optional_string_list(payload, "target_sections")
    job_description = _optional_string(payload, "job_description")
    instructions = _optional_string(payload, "instructions")
    prompt = prompts_resume_analysis.resume_skill_inject_prompt(
        tailored_resume,
        skills,
        target_sections=target_sections,
        job_description=job_description,
        instructions=instructions,
    )
    result = _parse_json_object_response(provider.generate(prompt).content)
    _validate_against_schema("resume_skill_inject_output.json", result, "output")
    return result


def _schema_dir() -> Path:
    configured = os.getenv("SCHEMA_REGISTRY_PATH")
    if configured:
        return Path(configured)
    return Path(__file__).resolve().parents[2] / "schemas"


def _load_schema(name: str) -> dict[str, Any]:
    path = _schema_dir() / name
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ToolExecutionError(f"schema_not_found:{path}") from exc
    except json.JSONDecodeError as exc:
        raise ToolExecutionError(f"invalid_schema:{exc}") from exc


def _validate_against_schema(name: str, payload: dict[str, Any], label: str) -> None:
    validate_schema(_load_schema(name), payload, label)


def _parse_json_object_response(text: str) -> dict[str, Any]:
    content = (text or "").strip()
    if content.startswith("```"):
        parts = content.split("```")
        if len(parts) > 1:
            content = parts[1].lstrip()
            if content.lower().startswith("json"):
                content = content[4:].lstrip()
    try:
        parsed = json.loads(content)
    except json.JSONDecodeError as exc:
        raise ToolExecutionError(f"Invalid JSON returned: {exc}") from exc
    if not isinstance(parsed, dict):
        raise ToolExecutionError("LLM output must be a JSON object")
    return parsed


def _require_string(payload: dict[str, Any], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ToolExecutionError(f"{key} must be a non-empty string")
    return value.strip()


def _optional_string(payload: dict[str, Any], key: str) -> str | None:
    value = payload.get(key)
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _require_object(payload: dict[str, Any], key: str) -> dict[str, Any]:
    value = payload.get(key)
    if not isinstance(value, dict):
        raise ToolExecutionError(f"{key} must be an object")
    return value


def _require_string_list(payload: dict[str, Any], key: str) -> list[str]:
    value = payload.get(key)
    if not isinstance(value, list):
        raise ToolExecutionError(f"{key} must be an array")
    normalized = [item.strip() for item in value if isinstance(item, str) and item.strip()]
    if not normalized:
        raise ToolExecutionError(f"{key} must contain at least one non-empty string")
    return normalized


def _optional_string_list(payload: dict[str, Any], key: str) -> list[str] | None:
    value = payload.get(key)
    if value is None:
        return None
    if not isinstance(value, list):
        raise ToolExecutionError(f"{key} must be an array")
    normalized = [item.strip() for item in value if isinstance(item, str) and item.strip()]
    return normalized
