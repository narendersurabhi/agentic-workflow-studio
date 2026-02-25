from __future__ import annotations

from dataclasses import dataclass
from collections.abc import Iterable, Mapping
from typing import Any

from . import models


TASK_INTENT_VALUES = tuple(intent.value for intent in models.ToolIntent)

_KEYWORD_MAP: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("validate", ("validate", "verify", "check", "lint", "schema")),
    ("render", ("render", "rendering", "docx", "pdf")),
    ("transform", ("transform", "reshape", "wrap", "convert", "derive", "summarize", "repair")),
    ("generate", ("generate", "create", "draft", "write", "compose", "produce", "build")),
    ("io", ("read", "fetch", "list", "search", "load", "save", "download", "upload")),
)

_ALLOWED_TOOL_INTENTS_BY_TASK_INTENT: dict[str, set[models.ToolIntent]] = {
    # generate tasks can compose and finish artifacts with render/io tools.
    "generate": {models.ToolIntent.generate, models.ToolIntent.render, models.ToolIntent.io},
    # transform tasks can reshape data and optionally use io utilities.
    "transform": {models.ToolIntent.transform, models.ToolIntent.io},
    # validate tasks can validate and normalize inputs before asserting quality.
    "validate": {
        models.ToolIntent.validate,
        models.ToolIntent.transform,
        models.ToolIntent.io,
    },
    # render tasks can format outputs and do lightweight data shaping.
    "render": {models.ToolIntent.render, models.ToolIntent.transform, models.ToolIntent.io},
    # io tasks should stay side-effect/data movement focused.
    "io": {models.ToolIntent.io},
}


@dataclass(frozen=True)
class TaskIntentInference:
    intent: str
    source: str
    confidence: float


_INTENT_SOURCE_EXPLICIT = "explicit"
_INTENT_SOURCE_TASK_TEXT = "task_text"
_INTENT_SOURCE_GOAL_TEXT = "goal_text"
_INTENT_SOURCE_DEFAULT = "default"


def _infer_intent_from_text_with_source(
    text: str,
    *,
    source: str,
) -> TaskIntentInference:
    normalized = text.lower()
    for intent, keywords in _KEYWORD_MAP:
        if any(keyword in normalized for keyword in keywords):
            confidence = 0.82 if source == _INTENT_SOURCE_TASK_TEXT else 0.72
            return TaskIntentInference(intent=intent, source=source, confidence=confidence)
    return TaskIntentInference(
        intent=models.ToolIntent.generate.value,
        source=_INTENT_SOURCE_DEFAULT,
        confidence=0.4,
    )


def normalize_task_intent(value: Any) -> str | None:
    if isinstance(value, models.ToolIntent):
        return value.value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in TASK_INTENT_VALUES:
            return normalized
    return None


def infer_task_intent_from_text(
    *,
    description: str = "",
    instruction: str = "",
    acceptance_criteria: Iterable[str] | None = None,
) -> str:
    parts: list[str] = []
    if description:
        parts.append(description)
    if instruction:
        parts.append(instruction)
    if acceptance_criteria:
        parts.extend([item for item in acceptance_criteria if isinstance(item, str)])
    text = " ".join(parts).lower()
    for intent, keywords in _KEYWORD_MAP:
        if any(keyword in text for keyword in keywords):
            return intent
    return "generate"


def infer_task_intent_from_text_with_metadata(
    *,
    description: str = "",
    instruction: str = "",
    acceptance_criteria: Iterable[str] | None = None,
) -> TaskIntentInference:
    parts: list[str] = []
    if description:
        parts.append(description)
    if instruction:
        parts.append(instruction)
    if acceptance_criteria:
        parts.extend([item for item in acceptance_criteria if isinstance(item, str)])
    text = " ".join(parts)
    return _infer_intent_from_text_with_source(text, source=_INTENT_SOURCE_TASK_TEXT)


def infer_task_intent_from_goal(goal_text: str) -> str:
    goal = goal_text.strip() if isinstance(goal_text, str) else ""
    if not goal:
        return models.ToolIntent.generate.value
    return infer_task_intent_from_text(description=goal)


def infer_task_intent_from_goal_with_metadata(goal_text: str) -> TaskIntentInference:
    goal = goal_text.strip() if isinstance(goal_text, str) else ""
    if not goal:
        return TaskIntentInference(
            intent=models.ToolIntent.generate.value,
            source=_INTENT_SOURCE_DEFAULT,
            confidence=0.4,
        )
    return _infer_intent_from_text_with_source(goal, source=_INTENT_SOURCE_GOAL_TEXT)


def _extract_goal_text(payload: Mapping[str, Any]) -> str:
    goal = payload.get("goal")
    if isinstance(goal, str) and goal.strip():
        return goal
    job = payload.get("job")
    if isinstance(job, Mapping):
        nested_goal = job.get("goal")
        if isinstance(nested_goal, str) and nested_goal.strip():
            return nested_goal
    return ""


def infer_task_intent_for_payload(payload: Mapping[str, Any]) -> str:
    return infer_task_intent_for_payload_with_metadata(payload).intent


def infer_task_intent_for_payload_with_metadata(payload: Mapping[str, Any]) -> TaskIntentInference:
    explicit = normalize_task_intent(payload.get("intent")) or normalize_task_intent(
        payload.get("task_intent")
    )
    if explicit:
        return TaskIntentInference(
            intent=explicit,
            source=_INTENT_SOURCE_EXPLICIT,
            confidence=1.0,
        )
    description = payload.get("description")
    instruction = payload.get("instruction")
    criteria = payload.get("acceptance_criteria")
    inferred = infer_task_intent_from_text_with_metadata(
        description=description if isinstance(description, str) else "",
        instruction=instruction if isinstance(instruction, str) else "",
        acceptance_criteria=criteria if isinstance(criteria, list) else [],
    )
    if inferred.intent != models.ToolIntent.generate.value:
        return inferred
    goal_inferred = infer_task_intent_from_goal_with_metadata(_extract_goal_text(payload))
    if goal_inferred.source != _INTENT_SOURCE_DEFAULT:
        return goal_inferred
    return inferred


def infer_task_intent_for_task(
    *,
    explicit_intent: Any,
    description: str,
    instruction: str,
    acceptance_criteria: Iterable[str] | None,
    goal_text: str = "",
) -> str:
    return infer_task_intent_for_task_with_metadata(
        explicit_intent=explicit_intent,
        description=description,
        instruction=instruction,
        acceptance_criteria=acceptance_criteria,
        goal_text=goal_text,
    ).intent


def infer_task_intent_for_task_with_metadata(
    *,
    explicit_intent: Any,
    description: str,
    instruction: str,
    acceptance_criteria: Iterable[str] | None,
    goal_text: str = "",
) -> TaskIntentInference:
    normalized = normalize_task_intent(explicit_intent)
    if normalized:
        return TaskIntentInference(
            intent=normalized,
            source=_INTENT_SOURCE_EXPLICIT,
            confidence=1.0,
        )
    inferred = infer_task_intent_from_text_with_metadata(
        description=description,
        instruction=instruction,
        acceptance_criteria=acceptance_criteria,
    )
    if inferred.intent != models.ToolIntent.generate.value:
        return inferred
    goal_inferred = infer_task_intent_from_goal_with_metadata(goal_text)
    if goal_inferred.source != _INTENT_SOURCE_DEFAULT:
        return goal_inferred
    return inferred


def validate_tool_intent_compatibility(
    task_intent: str,
    tool_intent: models.ToolIntent,
    tool_name: str,
) -> str | None:
    allowed = _ALLOWED_TOOL_INTENTS_BY_TASK_INTENT.get(task_intent)
    if not allowed:
        return f"invalid_task_intent:{task_intent}"
    if tool_intent in allowed:
        return None
    return f"tool_intent_mismatch:{tool_name}:{tool_intent.value}:{task_intent}"
