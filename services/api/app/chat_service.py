from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
import logging
import os
import re
import threading
import time
from typing import Any, Callable, Sequence

from sqlalchemy.orm import Session

from libs.core import capability_registry, chat_contracts, intent_contract, llm_provider, models, workflow_contracts

from . import chat_clarification_normalizer, context_service, memory_profile_service
from .models import ChatMessageRecord, ChatSessionRecord

logger = logging.getLogger("api.chat_service")

# ---------------------------------------------------------------------------
# In-process caches — eliminate DB round-trips for data that barely changes
# between consecutive turns of the same session.
#
# Session record cache: keyed by session_id; stores the post-persist state
# (metadata_json + updated_at + title) so the next turn skips the initial
# SELECT on chat_sessions.
#
# User profile cache: keyed by user_id; stores the profile payload with a
# monotonic timestamp for TTL expiry.  The profile is re-read from the DB
# only on the first turn or after the TTL expires.
# ---------------------------------------------------------------------------

@dataclass
class _CachedSession:
    metadata_json: dict[str, Any]
    updated_at: datetime
    title: str
    created_at: datetime

_SESSION_CACHE: dict[str, _CachedSession] = {}
_SESSION_CACHE_LOCK = threading.Lock()


def _get_cached_session(session_id: str) -> _CachedSession | None:
    with _SESSION_CACHE_LOCK:
        return _SESSION_CACHE.get(session_id)


def _put_cached_session(
    session_id: str, metadata_json: dict, updated_at: datetime, title: str, created_at: datetime
) -> None:
    with _SESSION_CACHE_LOCK:
        _SESSION_CACHE[session_id] = _CachedSession(
            metadata_json=dict(metadata_json),
            updated_at=updated_at,
            title=title,
            created_at=created_at,
        )


def _invalidate_cached_session(session_id: str) -> None:
    with _SESSION_CACHE_LOCK:
        _SESSION_CACHE.pop(session_id, None)


_INTERNAL_CHAT_USER_ID_KEY = "_chat_user_id"
_CHAT_STATE_VERSION_KEY = "_chat_state_version"
_CHAT_STATE_CONFLICT_COUNT_KEY = "_chat_state_conflict_count"
_PENDING_CLARIFICATION_SLOT_KEYS = (
    "goal",
    "instruction",
    "topic",
    "audience",
    "tone",
    "query",
    "path",
    "output_path",
    "filename",
    "file_name",
    "output_filename",
    "output_format",
    "target_system",
    "safety_constraints",
    "intent_action",
    "risk_level",
    "length",
    "markdown_text",
    "target_repo",
    "workspace_path",
)
_BOOTSTRAP_EXECUTION_ACTION_TOKENS = {"create", "generate", "make", "build"}
_BOOTSTRAP_EXECUTION_ARTIFACT_TOKENS = {"document", "repo", "repository", "file", "workflow"}
_BOOTSTRAP_CONTINUATION_TOKENS = {"yes", "no", "use", "create", "start"}
_OUTPUT_FORMAT_TOKENS = {"pdf", "docx", "markdown", "json", "word"}
_TONE_TOKENS = {"practical", "formal", "conversational", "executive", "technical", "concise"}

CHAT_HISTORY_CONTEXT_LIMIT = max(1, int(os.getenv("CHAT_HISTORY_CONTEXT_LIMIT", "50") or "50"))


@dataclass(frozen=True)
class ChatThreadHints:
    action_tokens: frozenset[str] = frozenset()
    artifact_tokens: frozenset[str] = frozenset()
    continuation_tokens: frozenset[str] = frozenset()


@dataclass(frozen=True)
class ChatServiceRuntime:
    route_turn: Callable[..., dict[str, Any]]
    run_direct_capability: Callable[..., "ChatDirectRunResult"]
    create_job: Callable[[models.JobCreate, Session], models.Job]
    run_workflow: Callable[..., models.WorkflowRunResult]
    inspect_workflow: Callable[..., "ChatWorkflowInspection"]
    utcnow: Callable[[], datetime]
    make_id: Callable[[], str]
    normalize_submit_context: Callable[..., "ChatSubmitNormalizationResult | None"] | None = None
    is_chat_only_correction: Callable[[str], bool] | None = None
    defer_pending_clarification_mapping: bool = False
    progress_callback: Callable[[str, dict], None] | None = None


@dataclass(frozen=True)
class ChatWorkflowInvocation:
    trigger_id: str | None = None
    version_id: str | None = None
    definition_id: str | None = None
    inputs: dict[str, Any] = field(default_factory=dict)
    context_json: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)
    idempotency_key: str | None = None

    def has_target(self) -> bool:
        return bool(self.trigger_id or self.version_id or self.definition_id)


@dataclass(frozen=True)
class ChatWorkflowInspection:
    trigger_id: str | None = None
    version_id: str | None = None
    definition_id: str | None = None
    missing_inputs: list[dict[str, Any]] = field(default_factory=list)


@dataclass(frozen=True)
class ChatDirectRunResult:
    job: models.Job
    capability_id: str
    tool_name: str | None = None
    output: dict[str, Any] = field(default_factory=dict)
    assistant_response: str = ""
    error: str | None = None


@dataclass(frozen=True)
class ChatSubmitNormalizationResult:
    goal: str | None = None
    context_json: dict[str, Any] = field(default_factory=dict)
    clarification_questions: list[str] = field(default_factory=list)
    requires_blocking_clarification: bool = False
    goal_intent_profile: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ClarificationLifecycle:
    state: chat_contracts.ClarificationState | None = None
    active: bool = False
    pending_fields: tuple[str, ...] = ()
    required_fields: tuple[str, ...] = ()
    questions: tuple[str, ...] = ()
    current_question: str | None = None
    current_question_field: str | None = None
    known_slot_values: dict[str, Any] = field(default_factory=dict)
    goal_intent_profile: dict[str, Any] = field(default_factory=dict)

    def next_question(self) -> str | None:
        return self.current_question or (self.questions[0] if self.questions else None)


# ─── Focused runtime interfaces ───────────────────────────────────────────────
# ChatServiceRuntime remains the external interface (used by main.py).
# ChatRuntime and AgentRuntime are narrower views used internally by the
# pipeline stages so each executor only depends on what it actually needs.

@dataclass(frozen=True)
class ChatRuntime:
    """Owns a single synchronous turn: classify, respond, optionally spawn work."""
    route_turn: Callable[..., dict[str, Any]]
    utcnow: Callable[[], datetime]
    make_id: Callable[[], str]
    normalize_submit_context: Callable[..., "ChatSubmitNormalizationResult | None"] | None = None
    is_chat_only_correction: Callable[[str], bool] | None = None
    defer_pending_clarification_mapping: bool = False
    progress_callback: Callable[[str, dict], None] | None = None


@dataclass(frozen=True)
class AgentRuntime:
    """Owns job-scoped operations that outlive a single chat turn."""
    create_job: Callable[[models.JobCreate, Session], models.Job]
    run_workflow: Callable[..., models.WorkflowRunResult]
    inspect_workflow: Callable[..., "ChatWorkflowInspection"]
    run_direct_capability: Callable[..., "ChatDirectRunResult"]


def _decompose_runtime(runtime: ChatServiceRuntime) -> tuple[ChatRuntime, AgentRuntime]:
    """Split a ChatServiceRuntime into its two focused sub-interfaces."""
    chat = ChatRuntime(
        route_turn=runtime.route_turn,
        utcnow=runtime.utcnow,
        make_id=runtime.make_id,
        normalize_submit_context=runtime.normalize_submit_context,
        is_chat_only_correction=runtime.is_chat_only_correction,
        defer_pending_clarification_mapping=runtime.defer_pending_clarification_mapping,
        progress_callback=runtime.progress_callback,
    )
    agent = AgentRuntime(
        create_job=runtime.create_job,
        run_workflow=runtime.run_workflow,
        inspect_workflow=runtime.inspect_workflow,
        run_direct_capability=runtime.run_direct_capability,
    )
    return chat, agent


# ─── Typed turn plans ─────────────────────────────────────────────────────────
# The LLM router currently returns dict[str, Any]. These dataclasses give each
# route type an explicit contract so executors don't silently miss fields.

@dataclass(frozen=True)
class AskClarificationPlan:
    resolved_goal: str
    questions: list[str]
    question_queue: list[str]
    assessment: dict[str, Any]
    context_json: dict[str, Any]
    pending_state: dict[str, Any]
    assistant_content: str = ""
    normalized_intent_envelope: dict[str, Any] | None = None


@dataclass(frozen=True)
class SubmitJobPlan:
    resolved_goal: str
    merged_context: dict[str, Any]
    assessment: dict[str, Any]
    assistant_content: str = ""
    normalization: ChatSubmitNormalizationResult | None = None


@dataclass(frozen=True)
class RunWorkflowPlan:
    resolved_goal: str
    merged_context: dict[str, Any]
    assessment: dict[str, Any]
    assistant_content: str = ""


@dataclass(frozen=True)
class ToolCallPlan:
    resolved_goal: str
    capability_id: str
    arguments: dict[str, Any]
    merged_context: dict[str, Any]
    assessment: dict[str, Any]
    assistant_content: str = ""


@dataclass(frozen=True)
class RespondPlan:
    resolved_goal: str
    merged_context: dict[str, Any]
    assessment: dict[str, Any]
    assistant_content: str = ""
    clear_pending_clarification: bool = False
    boundary_decision: dict[str, Any] | None = None
    routing_decision: dict[str, Any] | None = None


TurnPlan = (
    AskClarificationPlan
    | SubmitJobPlan
    | RunWorkflowPlan
    | ToolCallPlan
    | RespondPlan
)


# ─── Turn context and result ───────────────────────────────────────────────────

@dataclass
class TurnContext:
    """All state assembled before routing; passed unchanged through executors."""
    db: Session
    record: ChatSessionRecord
    request: chat_contracts.ChatTurnRequest
    content: str
    session_metadata: dict[str, Any]
    context_envelope: Any
    merged_context: dict[str, Any]
    candidate_goal: str
    chat_messages: list[chat_contracts.ChatMessage]
    messages: list[ChatMessageRecord]
    loaded_updated_at: Any
    loaded_state_version: int
    cleared_session_keys: set[str]
    bound_user_id: str
    now: datetime
    chat: ChatRuntime
    agent: AgentRuntime
    had_pending_clarification: bool = False
    had_pending_workflow_input: bool = False
    restarted_pending_clarification: bool = False
    exit_pending_to_chat: bool = False
    pre_route_normalization: ChatSubmitNormalizationResult | None = None
    clarification_mapping: dict[str, Any] | None = None

    def emit_progress(self, kind: str, payload: dict) -> None:
        cb = self.chat.progress_callback
        if cb is not None:
            try:
                cb(kind, payload)
            except Exception:  # noqa: BLE001
                pass


@dataclass
class TurnResult:
    """What an executor produces; consumed by _persist_turn and _build_turn_response."""
    assistant_content: str
    assistant_action: chat_contracts.AssistantAction
    created_job: models.Job | None = None
    workflow_run: models.WorkflowRun | None = None
    direct_output: dict[str, Any] | None = None
    boundary_decision: dict[str, Any] | None = None
    routing_decision: dict[str, Any] | None = None


# ─── Clarification state machine ──────────────────────────────────────────────
# Replaces the _clarification_lifecycle blob computation for new code paths.
# Existing ClarificationLifecycle functions are kept for callers not yet migrated.

class ClarificationPhase(str, Enum):
    idle = "idle"
    collecting = "collecting"
    ready = "ready"


@dataclass(frozen=True)
class SlotQuestion:
    field: str
    question: str


@dataclass(frozen=True)
class ClarificationSession:
    phase: ClarificationPhase
    goal: str
    collected: dict[str, Any]
    queue: tuple[SlotQuestion, ...]
    frame: dict[str, Any] = field(default_factory=dict)


def clarification_begin(
    goal: str,
    questions: list[SlotQuestion],
    frame: dict[str, Any] | None = None,
) -> ClarificationSession:
    """Start a new clarification flow for goal, collecting the given slots in order."""
    return ClarificationSession(
        phase=ClarificationPhase.collecting if questions else ClarificationPhase.ready,
        goal=goal,
        collected={},
        queue=tuple(questions),
        frame=dict(frame or {}),
    )


def clarification_answer(
    session: ClarificationSession,
    field: str,
    value: Any,
) -> ClarificationSession:
    """Record a slot answer and advance the queue."""
    updated_collected = {**session.collected, field: value}
    remaining = tuple(q for q in session.queue if q.field != field)
    return ClarificationSession(
        phase=ClarificationPhase.ready if not remaining else ClarificationPhase.collecting,
        goal=session.goal,
        collected=updated_collected,
        queue=remaining,
        frame=session.frame,
    )


def clarification_is_complete(session: ClarificationSession) -> bool:
    """True when all required slots are collected."""
    return session.phase == ClarificationPhase.ready


def clarification_next_question(session: ClarificationSession) -> SlotQuestion | None:
    """Return the next unanswered slot question, or None if complete."""
    return session.queue[0] if session.queue else None


def _submit_normalization_failure_questions(
    *,
    session_metadata: Mapping[str, Any] | None,
    assessment: Mapping[str, Any] | None,
) -> list[str]:
    questions: list[str] = []

    def _append(raw_question: Any) -> None:
        if isinstance(raw_question, str):
            question = raw_question.strip()
            if question and question not in questions:
                questions.append(question)

    lifecycle = clarification_lifecycle_from_metadata(session_metadata)
    for raw_question in lifecycle.questions:
        _append(raw_question)

    if isinstance(assessment, Mapping):
        for raw_question in assessment.get("questions") or []:
            _append(raw_question)

    return questions


def _parse_pending_clarification_state(
    metadata: Mapping[str, Any] | None,
) -> chat_contracts.ClarificationState | None:
    if not isinstance(metadata, Mapping):
        return None
    raw = metadata.get("pending_clarification")
    if not isinstance(raw, Mapping):
        return None
    try:
        return chat_contracts.ClarificationState.model_validate(dict(raw))
    except Exception:  # noqa: BLE001
        return None


def clarification_state_from_metadata(
    metadata: Mapping[str, Any] | None,
) -> chat_contracts.ClarificationState | None:
    return _parse_pending_clarification_state(metadata)


def clarification_lifecycle_from_metadata(
    metadata: Mapping[str, Any] | None,
) -> ClarificationLifecycle:
    return clarification_lifecycle_from_state(_parse_pending_clarification_state(metadata))


def clarification_lifecycle_from_state(
    state: chat_contracts.ClarificationState | Mapping[str, Any] | None,
) -> ClarificationLifecycle:
    if isinstance(state, chat_contracts.ClarificationState):
        parsed = state
    else:
        parsed = _coerce_clarification_state(state)
    return _clarification_lifecycle(parsed)


def pending_clarification_is_active(metadata: Mapping[str, Any] | None) -> bool:
    return clarification_lifecycle_from_metadata(metadata).active


def _clarification_state_has_pending_work(
    state: chat_contracts.ClarificationState | None,
) -> bool:
    return clarification_lifecycle_from_state(state).active


def persist_pending_clarification_state(
    metadata: dict[str, Any],
    *,
    state: Mapping[str, Any] | chat_contracts.ClarificationState | None,
    draft_goal: str | None = None,
    cleared_keys: set[str] | None = None,
) -> bool:
    lifecycle = clarification_lifecycle_from_state(state)
    if lifecycle.active and lifecycle.state is not None:
        if isinstance(draft_goal, str) and draft_goal.strip():
            metadata["draft_goal"] = draft_goal.strip()
        metadata["pending_clarification"] = _canonical_pending_state_payload(lifecycle)
        return True
    if state is not None and lifecycle.state is None:
        # state was a raw Mapping that failed Pydantic validation — log so it's
        # visible in production rather than silently resetting mid-conversation.
        logger.warning(
            "chat_pending_clarification_state_parse_failed",
            extra={"state_type": type(state).__name__},
        )
    for key in ("draft_goal", "pending_clarification"):
        metadata.pop(key, None)
        if cleared_keys is not None:
            cleared_keys.add(key)
    return False


def clear_pending_clarification_state(
    metadata: dict[str, Any],
    *,
    cleared_keys: set[str] | None = None,
    include_workflow_input: bool = False,
) -> None:
    keys = ["draft_goal", "pending_clarification"]
    if include_workflow_input:
        keys.append("pending_workflow_input")
    for key in keys:
        metadata.pop(key, None)
        if cleared_keys is not None:
            cleared_keys.add(key)


def _coerce_clarification_state(
    value: Mapping[str, Any] | None,
) -> chat_contracts.ClarificationState | None:
    if not isinstance(value, Mapping):
        return None
    try:
        return chat_contracts.ClarificationState.model_validate(dict(value))
    except Exception:  # noqa: BLE001
        return None


def _clarification_lifecycle(
    state: chat_contracts.ClarificationState | None,
) -> ClarificationLifecycle:
    if state is None:
        return ClarificationLifecycle()

    known_slot_values = _known_clarification_slot_values(state)
    profile = dict(state.goal_intent_profile or {})
    profile_requires_clarification = bool(
        profile.get("needs_clarification")
        or profile.get("requires_blocking_clarification")
    )

    profile_fields = _unresolved_clarification_fields(
        [profile.get("missing_slots"), profile.get("blocking_slots")],
        known_slot_values=known_slot_values,
    )
    state_pending_fields = _unresolved_clarification_fields(
        [state.pending_fields, state.required_fields],
        known_slot_values=known_slot_values,
    )
    current_question_field = _normalize_clarification_field_key(state.current_question_field)
    current_question_field = (
        current_question_field
        if current_question_field and current_question_field not in known_slot_values
        else ""
    )
    pending_fields = tuple(
        _ordered_clarification_fields(
            profile_fields,
            state_pending_fields,
            [current_question_field] if current_question_field else [],
        )
    )
    state_required_fields = _unresolved_clarification_fields(
        [state.required_fields],
        known_slot_values=known_slot_values,
    )
    required_fields = tuple(
        _ordered_clarification_fields(
            profile_fields,
            state_required_fields,
            [current_question_field] if current_question_field else [],
        )
    )

    raw_questions = _unique_string_list(
        [state.current_question] if state.current_question else [],
        state.questions,
        state.pending_questions,
    )
    questions = _active_lifecycle_questions(
        raw_questions=raw_questions,
        candidate_fields=pending_fields or required_fields,
        known_slot_values=known_slot_values,
        goal=state.original_goal,
        profile_requires_clarification=profile_requires_clarification,
        preserve_single_generic_question=bool(
            state.current_question_field and state.question_history
        ),
    )
    current_question = questions[0] if questions else None
    resolved_question_field = _clarification_field_from_question(
        question=current_question,
        candidate_fields=pending_fields or required_fields or _PENDING_CLARIFICATION_SLOT_KEYS,
        goal=state.original_goal,
    )
    if resolved_question_field and resolved_question_field not in known_slot_values:
        current_question_field = resolved_question_field
        if current_question_field not in pending_fields:
            pending_fields = tuple(_ordered_clarification_fields([current_question_field], pending_fields))
        if current_question_field not in required_fields:
            required_fields = tuple(_ordered_clarification_fields([current_question_field], required_fields))
    elif not current_question_field and pending_fields:
        current_question_field = pending_fields[0]

    active = bool(
        pending_fields
        or required_fields
        or (profile_requires_clarification and questions)
    )
    return ClarificationLifecycle(
        state=state,
        active=active,
        pending_fields=pending_fields,
        required_fields=required_fields,
        questions=tuple(questions if active else ()),
        current_question=current_question if active else None,
        current_question_field=current_question_field if active else None,
        known_slot_values=known_slot_values,
        goal_intent_profile=profile,
    )


def _known_clarification_slot_values(
    state: chat_contracts.ClarificationState,
) -> dict[str, Any]:
    known: dict[str, Any] = {}
    for raw_slots in (state.known_slot_values, state.resolved_slots):
        if not isinstance(raw_slots, Mapping):
            continue
        for raw_key, raw_value in raw_slots.items():
            key = _normalize_clarification_field_key(raw_key)
            if not key or key in known:
                continue
            if raw_value is None:
                continue
            if isinstance(raw_value, str):
                value = raw_value.strip()
                if not value:
                    continue
                known[key] = value
            else:
                known[key] = raw_value
    return known


def _unresolved_clarification_fields(
    collections: Sequence[Any],
    *,
    known_slot_values: Mapping[str, Any],
) -> list[str]:
    fields: list[str] = []
    for collection in collections:
        if not isinstance(collection, Sequence) or isinstance(collection, (str, bytes)):
            continue
        for raw_field in collection:
            field = _normalize_clarification_field_key(raw_field)
            if not field or field in fields:
                continue
            value = known_slot_values.get(field)
            if value is not None and (not isinstance(value, str) or value.strip()):
                continue
            fields.append(field)
    return fields


def _active_lifecycle_questions(
    *,
    raw_questions: Sequence[str],
    candidate_fields: Sequence[str],
    known_slot_values: Mapping[str, Any],
    goal: str,
    profile_requires_clarification: bool,
    preserve_single_generic_question: bool,
) -> list[str]:
    questions: list[str] = []
    candidate_field_list = list(candidate_fields)
    for question in raw_questions:
        question_field = _clarification_field_from_question(
            question=question,
            candidate_fields=candidate_field_list or _PENDING_CLARIFICATION_SLOT_KEYS,
            goal=goal,
            allow_single_candidate_fallback=False,
        )
        if question_field:
            value = known_slot_values.get(question_field)
            if value is not None and (not isinstance(value, str) or value.strip()):
                continue
            if candidate_field_list and question_field not in candidate_field_list:
                continue
        elif candidate_field_list:
            if preserve_single_generic_question and len(raw_questions) == 1:
                questions.append(question)
            continue
        elif not profile_requires_clarification:
            continue
        if question not in questions:
            questions.append(question)
    if not questions and candidate_field_list:
        question = chat_clarification_normalizer.clarification_question_for_field(
            candidate_field_list[0],
            goal=goal,
        )
        if question:
            questions.append(question)
    return questions


def _canonical_pending_state_payload(
    lifecycle: ClarificationLifecycle,
) -> dict[str, Any]:
    state = lifecycle.state
    if state is None:
        return {}
    profile = dict(state.goal_intent_profile or {})
    profile["missing_slots"] = list(lifecycle.pending_fields)
    profile["blocking_slots"] = list(lifecycle.required_fields or lifecycle.pending_fields)
    profile["needs_clarification"] = lifecycle.active
    profile["requires_blocking_clarification"] = lifecycle.active
    profile["questions"] = list(lifecycle.questions)
    payload = state.model_dump(mode="json", exclude_none=True)
    payload.update(
        {
            "goal_intent_profile": profile,
            "questions": ([lifecycle.current_question] if lifecycle.current_question else []),
            "pending_questions": list(lifecycle.questions),
            "current_question": lifecycle.current_question,
            "current_question_field": lifecycle.current_question_field,
            "pending_fields": list(lifecycle.pending_fields),
            "required_fields": list(lifecycle.required_fields),
            "known_slot_values": dict(lifecycle.known_slot_values),
            "resolved_slots": dict(lifecycle.known_slot_values),
            "answered_fields": sorted(str(key) for key in lifecycle.known_slot_values.keys()),
        }
    )
    return chat_contracts.ClarificationState.model_validate(payload).model_dump(
        mode="json",
        exclude_none=True,
    )


def _session_state_version(metadata: Mapping[str, Any] | None) -> int:
    if not isinstance(metadata, Mapping):
        return 0
    raw = metadata.get(_CHAT_STATE_VERSION_KEY)
    if isinstance(raw, int):
        return max(0, raw)
    if isinstance(raw, str):
        try:
            return max(0, int(raw.strip()))
        except ValueError:
            return 0
    return 0


def _unique_string_list(*values: Sequence[Any] | None) -> list[str]:
    normalized: list[str] = []
    for collection in values:
        if not isinstance(collection, Sequence) or isinstance(collection, (str, bytes)):
            continue
        for item in collection:
            if not isinstance(item, str):
                continue
            value = item.strip()
            if value and value not in normalized:
                normalized.append(value)
    return normalized


def _normalize_clarification_field_key(value: Any) -> str:
    return chat_clarification_normalizer.normalize_clarification_field_key(value)


def _clarification_output_format_from_path(path: Any) -> str | None:
    if not isinstance(path, str):
        return None
    candidate = path.strip().lower()
    if not candidate or "." not in candidate:
        return None
    extension = candidate.rsplit(".", 1)[-1]
    normalized = chat_clarification_normalizer.normalize_output_format_token(extension)
    return normalized or None


def _merge_known_clarification_slots(
    *,
    slot_values: Mapping[str, Any] | None,
    slot_provenance: Mapping[str, str] | None,
    target_values: dict[str, Any],
    target_provenance: dict[str, str],
) -> None:
    if isinstance(slot_values, Mapping):
        for raw_key, raw_value in slot_values.items():
            key = _normalize_clarification_field_key(raw_key)
            if not key or raw_value is None:
                continue
            if isinstance(raw_value, str):
                value = raw_value.strip()
                if not value:
                    continue
            else:
                value = raw_value
            target_values[key] = value
            if isinstance(slot_provenance, Mapping):
                raw_source = slot_provenance.get(raw_key)
                if raw_source is None:
                    raw_source = slot_provenance.get(key)
                source = str(raw_source or "").strip()
                if source:
                    target_provenance[key] = source

    inferred_output_format = _clarification_output_format_from_path(target_values.get("path"))
    if inferred_output_format and not str(target_values.get("output_format") or "").strip():
        target_values["output_format"] = inferred_output_format
        target_provenance.setdefault(
            "output_format",
            target_provenance.get("path") or workflow_contracts.SlotProvenance.inferred.value,
        )


def _ensure_inferred_clarification_slots(
    *,
    known_slot_values: dict[str, Any],
    slot_provenance: dict[str, str],
) -> None:
    inferred_output_format = _clarification_output_format_from_path(known_slot_values.get("path"))
    if inferred_output_format and not str(known_slot_values.get("output_format") or "").strip():
        known_slot_values["output_format"] = inferred_output_format
        slot_provenance.setdefault(
            "output_format",
            slot_provenance.get("path") or workflow_contracts.SlotProvenance.inferred.value,
        )


def _clarification_collectible_fields(
    capability_ids: Sequence[str] | None,
) -> set[str]:
    normalized_capability_ids = [
        capability_registry.canonicalize_capability_id(capability_id) or str(capability_id or "").strip()
        for capability_id in (capability_ids or [])
        if str(capability_id or "").strip()
    ]
    if not normalized_capability_ids:
        return set()
    try:
        registry = capability_registry.load_capability_registry()
    except Exception:  # noqa: BLE001
        return set()

    allowed: set[str] = set()
    for capability_id in normalized_capability_ids:
        spec = registry.get(capability_id)
        if spec is None:
            continue
        planner_hints = dict(spec.planner_hints or {})
        for collection_name in ("chat_collectible_fields", "chat_required_fields"):
            raw_fields = planner_hints.get(collection_name)
            if not isinstance(raw_fields, Sequence) or isinstance(raw_fields, (str, bytes)):
                continue
            for raw_field in raw_fields:
                field = _normalize_clarification_field_key(raw_field)
                if field:
                    allowed.add(field)
    return allowed


def _sanitize_clarification_field_queue(
    *,
    fields: Sequence[Any] | None,
    allowed_fields: set[str],
    known_slot_values: Mapping[str, Any],
) -> list[str]:
    ordered: list[str] = []
    for raw_field in fields or ():
        field = _normalize_clarification_field_key(raw_field)
        if not field or field in ordered:
            continue
        if allowed_fields and field not in allowed_fields:
            continue
        value = known_slot_values.get(field)
        if value is not None and (not isinstance(value, str) or value.strip()):
            continue
        ordered.append(field)
    return ordered


def _clarification_field_from_question(
    *,
    question: str | None,
    candidate_fields: Sequence[Any] = (),
    goal: str = "",
    allow_single_candidate_fallback: bool = True,
) -> str | None:
    normalized_question = str(question or "").strip()
    if not normalized_question:
        return None
    question_lower = normalized_question.lower()
    candidates: list[str] = []
    candidate_set: set[str] = set()
    for raw_field in candidate_fields:
        normalized_field = _normalize_clarification_field_key(raw_field)
        if normalized_field and normalized_field not in candidate_set:
            candidate_set.add(normalized_field)
            candidates.append(normalized_field)

    for field in candidates:
        canonical_question = chat_clarification_normalizer.clarification_question_for_field(
            field,
            goal=goal,
        )
        if normalized_question == canonical_question:
            return field

    if "target audience" in question_lower and "audience" in candidate_set:
        return "audience"
    if "tone" in question_lower and "tone" in candidate_set:
        return "tone"
    if any(
        token in question_lower
        for token in (
            "output format",
            "what format",
            "target format",
            "pdf",
            "docx",
            "markdown",
        )
    ) and "output_format" in candidate_set:
        return "output_format"
    if any(
        token in question_lower
        for token in (
            "output path",
            "filename",
            "file name",
            "name of the document",
            "exact filename",
            "save the document",
            "where should i save",
        )
    ) and "path" in candidate_set:
        return "path"
    if any(token in question_lower for token in ("main topic", "topic", "title", "subject")) and "topic" in candidate_set:
        return "topic"
    if any(
        token in question_lower
        for token in (
            "system do first",
            "generate, transform, validate, render, or io",
            "generate, transform, validate, render",
            "intent action",
        )
    ) and "intent_action" in candidate_set:
        return "intent_action"
    if any(
        token in question_lower
        for token in (
            "specifically cover",
            "what content should be in the document",
            "what specific content should be in the document",
            "basis for the content",
            "detailed prompt",
            "research",
        )
    ):
        for field in ("instruction", "markdown_text", "query"):
            if field in candidate_set:
                return field
    return candidates[0] if allow_single_candidate_fallback and len(candidates) == 1 else None


def _ordered_clarification_fields(*collections: Sequence[Any] | None) -> list[str]:
    ordered: list[str] = []
    for collection in collections:
        if not isinstance(collection, Sequence) or isinstance(collection, (str, bytes)):
            continue
        for raw_field in collection:
            normalized_field = _normalize_clarification_field_key(raw_field)
            if normalized_field and normalized_field not in ordered:
                ordered.append(normalized_field)
    return ordered


def _merge_clarification_state_for_persistence(
    latest: Mapping[str, Any] | None,
    desired: Mapping[str, Any] | None,
) -> dict[str, Any]:
    latest_state = _coerce_clarification_state(latest)
    desired_state = _coerce_clarification_state(desired)
    if latest_state is None and desired_state is None:
        return {}
    if latest_state is None:
        lifecycle = clarification_lifecycle_from_state(desired_state)
        return _canonical_pending_state_payload(lifecycle) if lifecycle.active else {}
    if desired_state is None:
        lifecycle = clarification_lifecycle_from_state(latest_state)
        return _canonical_pending_state_payload(lifecycle) if lifecycle.active else {}

    known_slot_values: dict[str, Any] = {}
    slot_provenance: dict[str, str] = {}
    _merge_known_clarification_slots(
        slot_values=latest_state.known_slot_values,
        slot_provenance=latest_state.slot_provenance,
        target_values=known_slot_values,
        target_provenance=slot_provenance,
    )
    _merge_known_clarification_slots(
        slot_values=latest_state.resolved_slots,
        slot_provenance=latest_state.slot_provenance,
        target_values=known_slot_values,
        target_provenance=slot_provenance,
    )
    _merge_known_clarification_slots(
        slot_values=desired_state.known_slot_values,
        slot_provenance=desired_state.slot_provenance,
        target_values=known_slot_values,
        target_provenance=slot_provenance,
    )
    _merge_known_clarification_slots(
        slot_values=desired_state.resolved_slots,
        slot_provenance=desired_state.slot_provenance,
        target_values=known_slot_values,
        target_provenance=slot_provenance,
    )
    resolved_slots = dict(known_slot_values)
    workflow_target = dict(latest_state.execution_frame.workflow_target or {})
    workflow_target.update(dict(desired_state.execution_frame.workflow_target or {}))

    execution_frame = latest_state.execution_frame.model_copy(deep=True)
    execution_frame.original_goal = (
        str(desired_state.execution_frame.original_goal or "").strip()
        or str(latest_state.execution_frame.original_goal or "").strip()
    )
    execution_frame.mode = desired_state.execution_frame.mode
    execution_frame.active_family = desired_state.execution_frame.active_family or execution_frame.active_family
    execution_frame.active_segment_id = (
        desired_state.execution_frame.active_segment_id or execution_frame.active_segment_id
    )
    execution_frame.active_capability_id = (
        desired_state.execution_frame.active_capability_id or execution_frame.active_capability_id
    )
    execution_frame.workflow_target = workflow_target
    execution_frame.state_version = max(
        int(latest_state.execution_frame.state_version or 0),
        int(desired_state.execution_frame.state_version or 0),
    ) + 1

    merged = desired_state.model_copy(deep=True)
    merged.schema_version = desired_state.schema_version or latest_state.schema_version
    merged.state_version = max(
        int(latest_state.state_version or 0),
        int(desired_state.state_version or 0),
    ) + 1
    merged.execution_frame = execution_frame
    merged.original_goal = str(desired_state.original_goal or "").strip() or str(
        latest_state.original_goal or ""
    ).strip()
    merged.active_family = desired_state.active_family or latest_state.active_family
    merged.active_segment_id = desired_state.active_segment_id or latest_state.active_segment_id
    merged.active_capability_id = (
        desired_state.active_capability_id or latest_state.active_capability_id
    )
    merged.goal_intent_profile = {
        **dict(latest_state.goal_intent_profile or {}),
        **dict(desired_state.goal_intent_profile or {}),
    }
    merged.current_question = str(desired_state.current_question or "").strip() or None
    merged.current_question_field = str(desired_state.current_question_field or "").strip() or None
    merged.pending_questions = _unique_string_list(
        desired_state.pending_questions or desired_state.questions,
    )
    merged.pending_fields = _ordered_clarification_fields(
        desired_state.pending_fields,
    )
    merged.required_fields = _ordered_clarification_fields(
        desired_state.required_fields,
    )
    merged.known_slot_values = known_slot_values
    merged.resolved_slots = resolved_slots
    merged.slot_provenance = slot_provenance
    merged.pending_fields = [
        field
        for field in merged.pending_fields
        if field and field not in known_slot_values
    ]
    merged.answered_fields = sorted(
        {
            *[str(value).strip() for value in latest_state.answered_fields if str(value).strip()],
            *[str(value).strip() for value in desired_state.answered_fields if str(value).strip()],
            *[str(key).strip() for key in known_slot_values.keys() if str(key).strip()],
        }
    )
    if not merged.current_question and merged.pending_questions:
        merged.current_question = str(merged.pending_questions[0]).strip() or None
    resolved_question_field = _clarification_field_from_question(
        question=merged.current_question,
        candidate_fields=merged.pending_fields or merged.required_fields,
        goal=merged.original_goal,
    )
    if resolved_question_field:
        merged.current_question_field = resolved_question_field
        if resolved_question_field not in merged.required_fields:
            merged.required_fields = [resolved_question_field, *merged.required_fields]
        merged.pending_fields = [
            resolved_question_field,
            *[field for field in merged.pending_fields if field != resolved_question_field],
        ]
    elif not merged.current_question_field and merged.pending_fields:
        merged.current_question_field = str(merged.pending_fields[0]).strip() or None
    merged.questions = [merged.current_question] if merged.current_question else []
    merged.question_history = _unique_string_list(
        latest_state.question_history,
        desired_state.question_history,
        merged.pending_questions,
    )
    merged.answer_history = _unique_string_list(
        latest_state.answer_history,
        desired_state.answer_history,
    )
    merged.candidate_capabilities = _unique_string_list(
        desired_state.candidate_capabilities,
        latest_state.candidate_capabilities,
    )
    merged.auto_path_allowed = bool(
        latest_state.auto_path_allowed or desired_state.auto_path_allowed
    )
    lifecycle = clarification_lifecycle_from_state(merged)
    if not lifecycle.active:
        latest_had_pending_work = _clarification_state_has_pending_work(latest_state)
        desired_had_pending_work = _clarification_state_has_pending_work(desired_state)
        if (
            not latest_had_pending_work
            and not desired_had_pending_work
            and merged.known_slot_values
        ):
            merged.questions = []
            merged.pending_questions = []
            merged.current_question = None
            merged.current_question_field = None
            merged.pending_fields = []
            merged.required_fields = []
            return merged.model_dump(mode="json", exclude_none=True)
        return {}
    return _canonical_pending_state_payload(lifecycle)


def _clarification_question_queue(questions: Sequence[Any] | None) -> list[str]:
    return _unique_string_list(questions)


def _active_clarification_questions(questions: Sequence[Any] | None) -> list[str]:
    queue = _clarification_question_queue(questions)
    return queue[:1]


def _merge_session_metadata_for_persistence(
    *,
    latest_metadata: Mapping[str, Any] | None,
    desired_metadata: Mapping[str, Any] | None,
    cleared_keys: set[str],
    loaded_state_version: int,
) -> tuple[dict[str, Any], bool]:
    latest = dict(latest_metadata or {})
    desired = dict(desired_metadata or {})
    latest_state_version = _session_state_version(latest)
    conflict_detected = latest_state_version > loaded_state_version

    merged = dict(latest)
    for key, value in desired.items():
        if key in {"context_json", "pending_clarification"}:
            continue
        merged[key] = value

    latest_context = latest.get("context_json")
    desired_context = desired.get("context_json")
    if isinstance(latest_context, Mapping) or isinstance(desired_context, Mapping):
        merged["context_json"] = _merge_chat_context(
            dict(latest_context) if isinstance(latest_context, Mapping) else {},
            dict(desired_context) if isinstance(desired_context, Mapping) else {},
        )

    if "pending_clarification" in cleared_keys:
        merged.pop("pending_clarification", None)
    else:
        desired_pending_present = isinstance(desired.get("pending_clarification"), Mapping)
        merged_pending = _merge_clarification_state_for_persistence(
            latest.get("pending_clarification")
            if isinstance(latest.get("pending_clarification"), Mapping)
            else None,
            desired.get("pending_clarification")
            if isinstance(desired.get("pending_clarification"), Mapping)
            else None,
        )
        if merged_pending:
            merged["pending_clarification"] = merged_pending
        elif desired_pending_present:
            merged.pop("pending_clarification", None)

    for key in cleared_keys:
        if key == "pending_clarification":
            continue
        merged.pop(key, None)

    merged[_CHAT_STATE_VERSION_KEY] = max(latest_state_version, loaded_state_version) + 1
    if conflict_detected:
        merged[_CHAT_STATE_CONFLICT_COUNT_KEY] = int(
            latest.get(_CHAT_STATE_CONFLICT_COUNT_KEY) or 0
        ) + 1
    elif _CHAT_STATE_CONFLICT_COUNT_KEY in latest:
        merged[_CHAT_STATE_CONFLICT_COUNT_KEY] = int(latest.get(_CHAT_STATE_CONFLICT_COUNT_KEY) or 0)
    return merged, conflict_detected


def _resolved_session_title(
    *,
    latest_title: str,
    desired_title: str,
) -> str:
    normalized_latest = str(latest_title or "").strip() or "New chat"
    normalized_desired = str(desired_title or "").strip() or normalized_latest
    if normalized_latest != "New chat":
        return normalized_latest
    return normalized_desired


def _persist_chat_session_state(
    *,
    db: Session,
    record: ChatSessionRecord,
    desired_metadata: Mapping[str, Any] | None,
    desired_title: str,
    loaded_updated_at: datetime,
    loaded_state_version: int,
    cleared_keys: set[str],
    runtime: ChatServiceRuntime,
) -> dict[str, Any]:
    expected_updated_at = loaded_updated_at
    for _attempt in range(3):
        db.expire_all()
        latest_record = (
            db.query(ChatSessionRecord).filter(ChatSessionRecord.id == record.id).first()
        )
        if latest_record is None:
            raise KeyError(record.id)
        merged_metadata, _conflict_detected = _merge_session_metadata_for_persistence(
            latest_metadata=latest_record.metadata_json,
            desired_metadata=desired_metadata,
            cleared_keys=cleared_keys,
            loaded_state_version=loaded_state_version,
        )
        resolved_title = _resolved_session_title(
            latest_title=latest_record.title,
            desired_title=desired_title,
        )
        updated_at = runtime.utcnow()
        updated_rows = (
            db.query(ChatSessionRecord)
            .filter(
                ChatSessionRecord.id == record.id,
                ChatSessionRecord.updated_at == expected_updated_at,
            )
            .update(
                {
                    ChatSessionRecord.metadata_json: merged_metadata,
                    ChatSessionRecord.updated_at: updated_at,
                    ChatSessionRecord.title: resolved_title,
                },
                synchronize_session=False,
            )
        )
        if updated_rows:
            record.metadata_json = dict(merged_metadata)
            record.updated_at = updated_at
            record.title = resolved_title
            return dict(merged_metadata)
        expected_updated_at = latest_record.updated_at
    raise RuntimeError("chat_session_state_conflict")


def _normalized_clarification_fields(context_json: Mapping[str, Any] | None) -> set[str]:
    if not isinstance(context_json, Mapping):
        return set()
    raw = context_json.get("clarification_normalization")
    if not isinstance(raw, Mapping):
        return set()
    normalized: set[str] = set()
    for value in raw.get("fields", []):
        key = str(value or "").strip()
        if key:
            normalized.add(key)
    return normalized


def _workflow_target_state(context_json: Mapping[str, Any] | None) -> dict[str, Any]:
    invocation = workflow_invocation_from_context(context_json)
    if invocation is None or not invocation.has_target():
        return {}
    workflow_target: dict[str, Any] = {}
    if invocation.trigger_id:
        workflow_target["trigger_id"] = invocation.trigger_id
    if invocation.version_id:
        workflow_target["version_id"] = invocation.version_id
    if invocation.definition_id:
        workflow_target["definition_id"] = invocation.definition_id
    return workflow_target


def _execution_family_for_capability(capability_id: str | None) -> str | None:
    normalized = capability_registry.canonicalize_capability_id(str(capability_id or "").strip())
    if not normalized:
        return None
    try:
        registry = capability_registry.load_capability_registry()
    except Exception:  # noqa: BLE001
        registry = None
    spec = registry.get(normalized) if registry is not None else None
    family = str(spec.group or spec.subgroup or "").strip() if spec is not None else ""
    if family:
        return family
    prefix = normalized.split(".", 1)[0].strip()
    return prefix or None


def _active_execution_target(
    *,
    normalized_intent_envelope: Mapping[str, Any] | None,
    candidate_capabilities: list[str],
    context_json: Mapping[str, Any] | None,
    existing_state: chat_contracts.ClarificationState | None,
    known_slot_values: Mapping[str, Any] | None,
    pending_fields: Sequence[str] | None,
) -> tuple[
    str | None,
    str | None,
    str | None,
    dict[str, Any],
    intent_contract.ActiveExecutionTarget | None,
]:
    active_family = existing_state.active_family if existing_state is not None else None
    active_segment_id = existing_state.active_segment_id if existing_state is not None else None
    active_capability_id = existing_state.active_capability_id if existing_state is not None else None
    workflow_target = (
        dict(existing_state.execution_frame.workflow_target)
        if existing_state is not None
        and isinstance(existing_state.execution_frame.workflow_target, Mapping)
        else {}
    )

    envelope = workflow_contracts.parse_normalized_intent_envelope(normalized_intent_envelope)
    active_target: intent_contract.ActiveExecutionTarget | None = None
    if envelope is not None:
        active_target = intent_contract.select_active_execution_target(
            graph=workflow_contracts.dump_intent_graph(envelope.graph) or {},
            candidate_capabilities=envelope.candidate_capabilities,
            known_slot_values=known_slot_values,
            pending_fields=pending_fields or (),
            preferred_segment_id=active_segment_id,
            preferred_capability_id=active_capability_id,
        )
        if active_target is not None:
            active_segment_id = active_target.segment_id or active_segment_id
            active_capability_id = active_target.capability_id or active_capability_id
    if not active_capability_id and candidate_capabilities:
        active_capability_id = next(
            (str(capability_id).strip() for capability_id in candidate_capabilities if str(capability_id).strip()),
            None,
        )
    if active_capability_id:
        active_capability_id = capability_registry.canonicalize_capability_id(active_capability_id) or active_capability_id
        active_family = _execution_family_for_capability(active_capability_id) or active_family
    latest_workflow_target = _workflow_target_state(context_json)
    if latest_workflow_target:
        workflow_target = latest_workflow_target
        active_family = active_family or "workflow"
    return active_family, active_segment_id, active_capability_id, workflow_target, active_target


def _pending_clarification_state(
    *,
    resolved_goal: str,
    questions: list[str],
    assessment: Mapping[str, Any] | None,
    session_metadata: Mapping[str, Any] | None,
    context_json: Mapping[str, Any] | None,
    normalized_intent_envelope: Mapping[str, Any] | None = None,
    latest_user_answer: str | None = None,
) -> dict[str, Any]:
    existing_state = _parse_pending_clarification_state(session_metadata)
    question_queue = _clarification_question_queue(questions)
    active_questions = question_queue[:1]
    original_goal = str(
        (existing_state.original_goal if existing_state is not None else "")
        or (session_metadata.get("draft_goal") if isinstance(session_metadata, Mapping) else "")
        or resolved_goal
        or ""
    ).strip()
    known_slot_values: dict[str, Any] = {}
    slot_provenance: dict[str, str] = {}
    if existing_state is not None:
        _merge_known_clarification_slots(
            slot_values=existing_state.known_slot_values,
            slot_provenance=existing_state.slot_provenance,
            target_values=known_slot_values,
            target_provenance=slot_provenance,
        )
        _merge_known_clarification_slots(
            slot_values=existing_state.resolved_slots,
            slot_provenance=existing_state.slot_provenance,
            target_values=known_slot_values,
            target_provenance=slot_provenance,
        )
    normalized_fields = _normalized_clarification_fields(context_json)
    if isinstance(context_json, Mapping):
        for key in _PENDING_CLARIFICATION_SLOT_KEYS:
            value = context_json.get(key)
            source_key = _normalize_clarification_field_key(key)
            if not source_key:
                continue
            if isinstance(value, str):
                stripped = value.strip()
                if not stripped:
                    continue
                known_slot_values[source_key] = stripped
                slot_provenance[source_key] = (
                    workflow_contracts.SlotProvenance.clarification_normalized.value
                    if source_key in normalized_fields
                    else workflow_contracts.SlotProvenance.explicit_user.value
                )
                continue
            if value is not None:
                known_slot_values[source_key] = value
                slot_provenance[source_key] = (
                    workflow_contracts.SlotProvenance.clarification_normalized.value
                    if source_key in normalized_fields
                    else workflow_contracts.SlotProvenance.explicit_user.value
                )
    assessment_unresolved_fields: set[str] = set()
    if isinstance(assessment, Mapping):
        for raw_field in (assessment.get("missing_slots") or []) + (assessment.get("blocking_slots") or []):
            field = _normalize_clarification_field_key(raw_field)
            if field:
                assessment_unresolved_fields.add(field)
    assessment_low_confidence = bool(
        isinstance(assessment, Mapping)
        and (
            assessment.get("low_confidence")
            or (
                isinstance(assessment.get("confidence"), (int, float))
                and isinstance(assessment.get("threshold"), (int, float))
                and float(assessment.get("confidence") or 0) < float(assessment.get("threshold") or 0)
            )
        )
    )
    if isinstance(assessment, Mapping) and isinstance(assessment.get("slot_values"), Mapping):
        for raw_key, value in dict(assessment.get("slot_values") or {}).items():
            source_key = _normalize_clarification_field_key(raw_key)
            if not source_key or source_key in known_slot_values:
                continue
            if assessment_low_confidence and source_key in assessment_unresolved_fields:
                continue
            if isinstance(value, str):
                stripped = value.strip()
                if not stripped:
                    continue
                known_slot_values[source_key] = stripped
            elif value is not None:
                known_slot_values[source_key] = value
            else:
                continue
            slot_provenance[source_key] = workflow_contracts.SlotProvenance.inferred.value
    _ensure_inferred_clarification_slots(
        known_slot_values=known_slot_values,
        slot_provenance=slot_provenance,
    )
    pending_fields: list[str] = []
    required_fields: list[str] = []
    if isinstance(assessment, Mapping):
        for raw_field in (assessment.get("missing_slots") or []) + (assessment.get("blocking_slots") or []):
            if isinstance(raw_field, str):
                field = _normalize_clarification_field_key(raw_field)
                if field and field not in required_fields:
                    required_fields.append(field)
                if field and field not in pending_fields:
                    pending_fields.append(field)
    assessment_source = (
        str(assessment.get("source") or "").strip() if isinstance(assessment, Mapping) else ""
    )
    profile_requires_clarification = bool(
        isinstance(assessment, Mapping)
        and (
            assessment.get("needs_clarification")
            or assessment.get("requires_blocking_clarification")
        )
    )
    reset_existing_pending_fields = (
        isinstance(assessment, Mapping)
        and assessment_source == "chat_boundary_meta_clarification"
    )
    if not reset_existing_pending_fields:
        for raw_field in (existing_state.pending_fields if existing_state is not None else []):
            if isinstance(raw_field, str):
                field = _normalize_clarification_field_key(raw_field)
                if field and field not in pending_fields and field not in known_slot_values:
                    pending_fields.append(field)
    if existing_state is not None and not reset_existing_pending_fields:
        for raw_field in existing_state.required_fields:
            if isinstance(raw_field, str):
                field = _normalize_clarification_field_key(raw_field)
                if field and field not in required_fields:
                    required_fields.append(field)
    question_history: list[str] = []
    for raw_question in (existing_state.question_history if existing_state is not None else []):
        if isinstance(raw_question, str):
            question = raw_question.strip()
            if question and question not in question_history:
                question_history.append(question)
    for question in questions:
        normalized = str(question or "").strip()
        if normalized and normalized not in question_history:
            question_history.append(normalized)
    answer_history: list[str] = []
    for raw_answer in (existing_state.answer_history if existing_state is not None else []):
        if isinstance(raw_answer, str):
            answer = raw_answer.strip()
            if answer and answer not in answer_history:
                answer_history.append(answer)
    if existing_state is not None and isinstance(latest_user_answer, str):
        latest_answer = latest_user_answer.strip()
        if latest_answer and latest_answer not in answer_history:
            answer_history.append(latest_answer)
    candidate_capabilities: list[str] = []
    raw_candidates = context_json.get("capability_candidates") if isinstance(context_json, Mapping) else None
    if isinstance(raw_candidates, list):
        for raw_value in raw_candidates:
            if isinstance(raw_value, str):
                value = raw_value.strip()
                if value and value not in candidate_capabilities:
                    candidate_capabilities.append(value)
    if not candidate_capabilities:
        for raw_value in (existing_state.candidate_capabilities if existing_state is not None else []):
            if isinstance(raw_value, str):
                value = raw_value.strip()
                if value and value not in candidate_capabilities:
                    candidate_capabilities.append(value)
    (
        active_family,
        active_segment_id,
        active_capability_id,
        workflow_target,
        active_target,
    ) = _active_execution_target(
        normalized_intent_envelope=normalized_intent_envelope,
        candidate_capabilities=candidate_capabilities,
        context_json=context_json,
        existing_state=existing_state,
        known_slot_values=known_slot_values,
        pending_fields=pending_fields,
    )
    allowed_fields = _clarification_collectible_fields(
        [
            *(candidate_capabilities or []),
            *(active_target.capability_ids if active_target is not None else ()),
            active_capability_id or "",
        ]
    )
    if active_target is not None:
        for raw_field in (*active_target.required_fields, *active_target.unresolved_fields):
            field = _normalize_clarification_field_key(raw_field)
            if field:
                allowed_fields.add(field)
    if not allowed_fields:
        allowed_fields = {
            _normalize_clarification_field_key(field)
            for field in _PENDING_CLARIFICATION_SLOT_KEYS
            if _normalize_clarification_field_key(field)
        }
    pending_fields = _sanitize_clarification_field_queue(
        fields=pending_fields,
        allowed_fields=allowed_fields,
        known_slot_values=known_slot_values,
    )
    required_fields = _sanitize_clarification_field_queue(
        fields=required_fields,
        allowed_fields=allowed_fields,
        known_slot_values=known_slot_values,
    )
    question_candidate_fields = (
        list(pending_fields)
        + list(required_fields)
        + list(active_target.required_fields if active_target is not None else ())
    )
    filtered_question_queue: list[str] = []
    if question_candidate_fields:
        for question in question_queue:
            question_field = _clarification_field_from_question(
                question=question,
                candidate_fields=_PENDING_CLARIFICATION_SLOT_KEYS,
                goal=resolved_goal or original_goal,
            )
            if not question_field:
                if len(question_queue) == 1:
                    filtered_question_queue.append(question)
                continue
            value = known_slot_values.get(question_field)
            if value is not None and (not isinstance(value, str) or value.strip()):
                continue
            if question_field not in question_candidate_fields:
                continue
            if question not in filtered_question_queue:
                filtered_question_queue.append(question)
    if not filtered_question_queue and pending_fields:
        filtered_question_queue = [
            chat_clarification_normalizer.clarification_question_for_field(
                pending_fields[0],
                goal=resolved_goal or original_goal,
            )
        ]
    if question_candidate_fields or filtered_question_queue:
        question_queue = filtered_question_queue
    elif not pending_fields and not required_fields:
        if assessment_source == "chat_boundary_meta_clarification" or (
            profile_requires_clarification and question_queue
        ):
            question_queue = _clarification_question_queue(questions)
        else:
            question_queue = []
    active_questions = question_queue[:1]
    execution_frame = (
        existing_state.execution_frame.model_copy(deep=True)
        if existing_state is not None
        else workflow_contracts.ExecutionFrame()
    )
    execution_frame.original_goal = original_goal
    execution_frame.mode = workflow_contracts.ExecutionFrameMode.clarification
    execution_frame.active_family = active_family
    execution_frame.active_segment_id = active_segment_id
    execution_frame.active_capability_id = active_capability_id
    execution_frame.workflow_target = workflow_target
    execution_frame.state_version = (
        existing_state.execution_frame.state_version + 1
        if existing_state is not None
        else 1
    )
    if not str(execution_frame.frame_id or "").strip():
        execution_frame.frame_id = (
            active_segment_id or active_capability_id or active_family or "clarification"
        )

    current_question = active_questions[0] if active_questions else None
    current_question_field = _clarification_field_from_question(
        question=current_question,
        candidate_fields=(
            list(pending_fields)
            + list(required_fields)
            + list(active_target.required_fields if active_target is not None else ())
        ),
        goal=resolved_goal or original_goal,
    )
    if current_question_field:
        if current_question_field in known_slot_values:
            current_question = None
            current_question_field = None
        elif current_question_field not in required_fields:
            required_fields = [current_question_field, *required_fields]
    if current_question_field:
        pending_fields = [
            current_question_field,
            *[field for field in pending_fields if field != current_question_field],
        ]

    state = chat_contracts.ClarificationState(
        schema_version="clarification_state_v1",
        state_version=(existing_state.state_version + 1) if existing_state is not None else 1,
        execution_frame=execution_frame,
        original_goal=original_goal,
        active_family=active_family,
        active_segment_id=active_segment_id,
        active_capability_id=active_capability_id,
        goal_intent_profile=dict(assessment or {}),
        questions=active_questions,
        pending_questions=question_queue,
        current_question=current_question,
        current_question_field=current_question_field or (pending_fields[0] if pending_fields else None),
        pending_fields=pending_fields,
        required_fields=required_fields,
        known_slot_values=known_slot_values,
        resolved_slots=dict(known_slot_values),
        slot_provenance=slot_provenance,
        answered_fields=sorted(str(key) for key in known_slot_values.keys()),
        question_history=question_history,
        answer_history=answer_history,
        candidate_capabilities=candidate_capabilities,
        auto_path_allowed=bool(existing_state.auto_path_allowed) if existing_state is not None else False,
    )
    return state.model_dump(mode="json", exclude_none=True)


def _apply_pending_clarification_mapping(
    *,
    db: Session,
    runtime: ChatServiceRuntime,
    goal: str,
    content: str,
    session_metadata: Mapping[str, Any],
    merged_context: Mapping[str, Any] | None,
    context_envelope: workflow_contracts.ContextEnvelope,
    user_id: str | None,
    messages: Sequence[chat_contracts.ChatMessage] | None = None,
) -> tuple[
    str,
    workflow_contracts.ContextEnvelope,
    dict[str, Any],
    dict[str, Any],
    ChatSubmitNormalizationResult | None,
]:
    pending_lifecycle = clarification_lifecycle_from_metadata(session_metadata)
    pending_state = pending_lifecycle.state if pending_lifecycle.active else None
    if pending_state is None or runtime.normalize_submit_context is None:
        updated_metadata = dict(session_metadata)
        if pending_lifecycle.state is not None and not pending_lifecycle.active:
            clear_pending_clarification_state(updated_metadata)
        return (
            goal,
            context_envelope,
            dict(merged_context or {}),
            updated_metadata,
            None,
        )
    if runtime.defer_pending_clarification_mapping:
        return (
            goal,
            context_envelope,
            dict(merged_context or {}),
            dict(session_metadata),
            None,
        )

    normalization = _local_pending_clarification_normalization(
        goal=goal,
        content=content,
        session_metadata=session_metadata,
        merged_context=merged_context,
        pending_lifecycle=pending_lifecycle,
    )
    if normalization is None:
        if _looks_like_pending_meta_clarification(content):
            return (
                goal,
                context_envelope,
                dict(merged_context or {}),
                dict(session_metadata),
                None,
            )
        try:
            normalization = runtime.normalize_submit_context(
                db=db,
                goal=goal,
                content=content,
                session_metadata=session_metadata,
                merged_context=merged_context,
                context_envelope=context_envelope,
                user_id=user_id,
                messages=messages,
            )
        except Exception:  # noqa: BLE001
            logger.exception(
                "chat_pending_clarification_mapping_failed",
                extra={"session_id": session_metadata.get("id")},
            )
            return (
                goal,
                context_envelope,
                dict(merged_context or {}),
                dict(session_metadata),
                None,
            )

    if normalization is None:
        return (
            goal,
            context_envelope,
            dict(merged_context or {}),
            dict(session_metadata),
            None,
        )

    return _apply_clarification_normalization_result(
        goal=goal,
        content=content,
        session_metadata=session_metadata,
        merged_context=merged_context,
        context_envelope=context_envelope,
        pending_state=pending_state,
        normalization=normalization,
    )


def _local_pending_clarification_normalization(
    *,
    goal: str,
    content: str,
    session_metadata: Mapping[str, Any],
    merged_context: Mapping[str, Any] | None,
    pending_lifecycle: ClarificationLifecycle,
) -> ChatSubmitNormalizationResult | None:
    current_field = _normalize_clarification_field_key(pending_lifecycle.current_question_field)
    if not current_field:
        return None
    lowered_content = str(content or "").lower()
    if re.search(r"\b(?:actually|instead|rather)\b", lowered_content):
        return None
    if _looks_like_pending_meta_clarification(content):
        return None
    if _should_skip_local_pending_slot_mapping(
        field=current_field,
        content=content,
    ):
        return None
    candidate_fields = list(pending_lifecycle.pending_fields or pending_lifecycle.required_fields)
    updates = chat_clarification_normalizer.heuristic_field_updates_for_answer(
        preferred_field=current_field,
        latest_answer=content,
        allowed_fields=tuple(candidate_fields),
    )
    if not updates:
        return None

    updated_context = dict(merged_context or {})
    updated_context.update(updates)
    known_slot_values = {
        **dict(pending_lifecycle.known_slot_values or {}),
        **{
            _normalize_clarification_field_key(key): value
            for key, value in updates.items()
            if _normalize_clarification_field_key(key)
        },
    }
    remaining_fields: list[str] = []
    for raw_field in _ordered_clarification_fields(
        pending_lifecycle.pending_fields,
        pending_lifecycle.required_fields,
    ):
        field = _normalize_clarification_field_key(raw_field)
        if not field or field in remaining_fields:
            continue
        value = known_slot_values.get(field, updated_context.get(field))
        if value is not None and (not isinstance(value, str) or value.strip()):
            continue
        remaining_fields.append(field)

    assessment = dict(pending_lifecycle.goal_intent_profile or {})
    slot_values = (
        dict(assessment.get("slot_values"))
        if isinstance(assessment.get("slot_values"), Mapping)
        else {}
    )
    slot_values.update(updates)
    assessment["slot_values"] = slot_values
    assessment["missing_slots"] = list(remaining_fields)
    assessment["blocking_slots"] = list(remaining_fields)
    assessment["needs_clarification"] = bool(remaining_fields)
    assessment["requires_blocking_clarification"] = bool(remaining_fields)
    remaining_questions: list[str] = []
    for question in pending_lifecycle.questions:
        question_field = _clarification_field_from_question(
            question=question,
            candidate_fields=remaining_fields,
            goal=goal,
            allow_single_candidate_fallback=False,
        )
        if question_field in remaining_fields and question not in remaining_questions:
            remaining_questions.append(question)
    for field in remaining_fields:
        if any(
            _clarification_field_from_question(
                question=question,
                candidate_fields=(field,),
                goal=goal,
            )
            == field
            for question in remaining_questions
        ):
            continue
        question = chat_clarification_normalizer.clarification_question_for_field(
            field,
            goal=goal,
        )
        if question and question not in remaining_questions:
            remaining_questions.append(question)
    assessment["questions"] = remaining_questions
    if remaining_fields:
        assessment["clarification_mode"] = (
            str(assessment.get("clarification_mode") or "").strip()
            or "targeted_slot_filling"
        )
    else:
        assessment["clarification_mode"] = None

    updated_context["clarification_normalization"] = {
        "source": "chat_clarification_heuristic",
        "fields": sorted(updates.keys()),
        "confidence": {field: 1.0 for field in updates},
    }
    return ChatSubmitNormalizationResult(
        goal=goal,
        context_json=updated_context,
        clarification_questions=list(assessment["questions"]),
        requires_blocking_clarification=bool(remaining_fields),
        goal_intent_profile=assessment,
    )


def _looks_like_pending_meta_clarification(content: str) -> bool:
    normalized = str(content or "").strip()
    if not normalized:
        return False
    lowered = normalized.lower()
    if "answer:" in lowered:
        return False
    return "?" in normalized or bool(
        re.search(
            r"\b(?:clarify|what do you|what you|what still|still need|need from me)\b",
            lowered,
        )
    )


def _should_skip_local_pending_slot_mapping(*, field: str, content: str) -> bool:
    if field in {"instruction", "goal"}:
        return False
    normalized = str(content or "").strip()
    if not normalized:
        return True
    lowered = normalized.lower()
    if "," in normalized or "." in normalized or ";" in normalized:
        return True
    if re.search(r"\b(?:make|create|generate|save|render|write)\b", lowered):
        return True
    if re.search(r"\b(?:pdf|docx|markdown|json|word)\b", lowered) and re.search(
        r"\bfor\b",
        lowered,
    ):
        return True
    return False


def _apply_clarification_normalization_result(
    *,
    goal: str,
    content: str,
    session_metadata: Mapping[str, Any],
    merged_context: Mapping[str, Any] | None,
    context_envelope: workflow_contracts.ContextEnvelope,
    pending_state: chat_contracts.ClarificationState,
    normalization: ChatSubmitNormalizationResult,
) -> tuple[
    str,
    workflow_contracts.ContextEnvelope,
    dict[str, Any],
    dict[str, Any],
    ChatSubmitNormalizationResult,
]:
    updated_goal = str(normalization.goal or "").strip() or goal
    updated_envelope = context_envelope
    if updated_goal != goal or (
        isinstance(normalization.context_json, Mapping) and normalization.context_json
    ):
        updated_envelope = context_service.update_chat_context_envelope(
            context_envelope,
            goal=updated_goal,
            context_json=normalization.context_json,
        )
    updated_context = context_service.chat_submit_context_view(updated_envelope)
    updated_metadata = dict(session_metadata)
    updated_metadata["draft_goal"] = updated_goal
    updated_metadata["context_json"] = updated_context

    clarification_question_queue = [
        str(question).strip()
        for question in normalization.clarification_questions
        if isinstance(question, str) and question.strip()
    ]
    assessment = (
        dict(normalization.goal_intent_profile)
        if isinstance(normalization.goal_intent_profile, Mapping)
        and normalization.goal_intent_profile
        else dict(pending_state.goal_intent_profile or {})
    )
    next_pending_state = _pending_clarification_state(
        resolved_goal=updated_goal,
        questions=clarification_question_queue,
        assessment=assessment,
        session_metadata=session_metadata,
        context_json=updated_context,
        normalized_intent_envelope=(
            dict(session_metadata.get("normalized_intent_envelope"))
            if isinstance(session_metadata.get("normalized_intent_envelope"), Mapping)
            else None
        ),
        latest_user_answer=content,
    )
    next_lifecycle = clarification_lifecycle_from_state(next_pending_state)
    if next_lifecycle.active:
        persist_pending_clarification_state(
            updated_metadata,
            state=next_pending_state,
            draft_goal=updated_goal,
        )
    else:
        clear_pending_clarification_state(updated_metadata)
    return updated_goal, updated_envelope, updated_context, updated_metadata, normalization


def _resolved_clarification_mapping_fields(
    normalization: ChatSubmitNormalizationResult | None,
) -> list[str]:
    if normalization is None or not isinstance(normalization.context_json, Mapping):
        return []
    payload = normalization.context_json.get("clarification_normalization")
    if not isinstance(payload, Mapping):
        return []
    resolved: list[str] = []
    for raw_field in payload.get("fields") or []:
        field = _normalize_clarification_field_key(raw_field)
        if field and field not in resolved:
            resolved.append(field)
    return resolved


def _clarification_mapping_metadata(
    *,
    before_state: chat_contracts.ClarificationState | None,
    after_state: chat_contracts.ClarificationState | None,
    normalization: ChatSubmitNormalizationResult | None,
    restarted: bool,
) -> dict[str, Any] | None:
    if before_state is None and not restarted:
        return None
    active_field_before = (
        _normalize_clarification_field_key(before_state.current_question_field)
        if before_state is not None and before_state.current_question_field
        else None
    )
    active_field_after = (
        _normalize_clarification_field_key(after_state.current_question_field)
        if after_state is not None and after_state.current_question_field
        else None
    )
    resolved_fields = _resolved_clarification_mapping_fields(normalization)
    resolved_active_field = bool(
        active_field_before and active_field_before in set(resolved_fields)
    )
    queue_advanced = bool(
        resolved_active_field
        and (active_field_after is None or active_field_after != active_field_before)
    )
    return {
        "active_field_before": active_field_before,
        "active_field_after": active_field_after,
        "resolved_fields": resolved_fields,
        "resolved_active_field": resolved_active_field,
        "queue_advanced": queue_advanced,
        "restarted": bool(restarted),
    }


def _pending_clarification_fast_turn_plan(
    *,
    candidate_goal: str,
    session_metadata: Mapping[str, Any],
    normalization: ChatSubmitNormalizationResult | None,
    had_pending_clarification: bool,
    had_pending_workflow_input: bool,
    restarted: bool,
    exit_pending_to_chat: bool,
) -> dict[str, Any] | None:
    if (
        not had_pending_clarification
        or had_pending_workflow_input
        or restarted
        or exit_pending_to_chat
        or normalization is None
    ):
        return None
    lifecycle = clarification_lifecycle_from_metadata(session_metadata)
    assessment = (
        dict(normalization.goal_intent_profile)
        if isinstance(normalization.goal_intent_profile, Mapping)
        and normalization.goal_intent_profile
        else dict(lifecycle.goal_intent_profile or {})
    )
    resolved_goal = str(normalization.goal or "").strip() or candidate_goal
    if lifecycle.active:
        questions = list(lifecycle.questions)
        if not questions:
            questions = [
                str(question).strip()
                for question in normalization.clarification_questions
                if isinstance(question, str) and question.strip()
            ]
        questions = _active_clarification_questions(questions)
        return {
            "type": "ask_clarification",
            "assistant_content": "\n".join(questions),
            "clarification_questions": questions,
            "goal_intent_profile": assessment,
            "resolved_goal": resolved_goal,
            "context_json_updates": (
                dict(normalization.context_json)
                if isinstance(normalization.context_json, Mapping)
                else {}
            ),
            "routing_decision": {
                "route": "ask_clarification",
                "fallback_used": True,
                "fallback_reason": "pending_clarification_fast_path",
                "reason_codes": ["pending_clarification_fast_path"],
                "missing_inputs": list(assessment.get("missing_slots") or []),
                "clarification_questions": questions,
            },
        }
    if normalization.requires_blocking_clarification:
        questions = _active_clarification_questions(normalization.clarification_questions)
        return {
            "type": "ask_clarification",
            "assistant_content": "\n".join(questions),
            "clarification_questions": questions,
            "goal_intent_profile": assessment,
            "resolved_goal": resolved_goal,
            "context_json_updates": (
                dict(normalization.context_json)
                if isinstance(normalization.context_json, Mapping)
                else {}
            ),
            "routing_decision": {
                "route": "ask_clarification",
                "fallback_used": True,
                "fallback_reason": "pending_clarification_fast_path",
                "reason_codes": ["pending_clarification_fast_path"],
                "missing_inputs": list(assessment.get("missing_slots") or []),
                "clarification_questions": questions,
            },
        }
    return {
        "type": "submit_job",
        "assistant_content": "",
        "clarification_questions": [],
        "goal_intent_profile": assessment,
        "resolved_goal": resolved_goal,
        "context_json_updates": (
            dict(normalization.context_json)
            if isinstance(normalization.context_json, Mapping)
            else {}
        ),
        "routing_decision": {
            "route": "submit_job",
            "fallback_used": True,
            "fallback_reason": "pending_clarification_fast_path",
            "reason_codes": ["pending_clarification_fast_path"],
            "missing_inputs": [],
            "clarification_questions": [],
        },
    }


def looks_like_chat_only_correction(content: str) -> bool:
    lowered = str(content or "").strip().lower()
    if not lowered:
        return False
    tokens = set(re.findall(r"[a-z0-9]+", lowered))
    if not tokens:
        return False

    negation_tokens = {"no", "not", "dont", "don't", "do", "without", "skip", "cancel", "stop", "instead", "rather"}
    execution_tokens = {
        "document",
        "doc",
        "docx",
        "pdf",
        "markdown",
        "report",
        "file",
        "files",
        "workflow",
        "job",
        "artifact",
        "artifacts",
        "render",
        "generate",
        "create",
        "submit",
    }
    chat_tokens = {
        "chat",
        "response",
        "respond",
        "answer",
        "reply",
        "explain",
        "thoughts",
        "here",
    }
    redirect_tokens = {"just", "only", "instead", "rather"}

    has_execution_reference = bool(tokens & execution_tokens)
    has_chat_reference = bool(tokens & chat_tokens)
    has_negation_or_redirect = bool(tokens & negation_tokens)
    has_redirect_reference = bool(tokens & redirect_tokens)

    if has_chat_reference and (has_negation_or_redirect or has_redirect_reference):
        return True
    if has_execution_reference and has_chat_reference:
        return True
    if has_execution_reference and has_negation_or_redirect:
        return True

    compact = re.sub(r"[^a-z0-9]+", " ", lowered)
    semantic_patterns = (
        r"\b(?:answer|reply|respond|explain)\b.{0,24}\b(?:here|in chat|in the chat)\b",
        r"\b(?:just|only)\b.{0,24}\b(?:chat|response|reply|answer)\b",
        r"\b(?:not|no|dont|don't|skip|cancel|stop)\b.{0,24}\b(?:document|workflow|job|pdf|docx|report|artifact)\b",
        r"\binstead\b.{0,24}\b(?:chat|answer|reply|respond|here)\b",
    )
    return any(re.search(pattern, compact) for pattern in semantic_patterns)


def _looks_like_local_clarification_field_answer(
    content: str,
    *,
    current_field: str | None,
) -> bool:
    normalized_field = intent_contract.normalize_required_input_key(current_field)
    lowered = str(content or "").strip().lower()
    if not lowered or not normalized_field:
        return False
    tokens = set(re.findall(r"[a-z0-9]+", lowered))
    if not tokens:
        return False

    if normalized_field == "output_format":
        return bool(tokens & _OUTPUT_FORMAT_TOKENS)
    if normalized_field == "tone":
        return bool(tokens & _TONE_TOKENS) and len(tokens) <= 8
    if normalized_field == "audience":
        return not bool(tokens & _chat_thread_hints().action_tokens) and len(tokens) <= 12
    if normalized_field == "goal":
        return len(tokens) >= 4
    if normalized_field == "workspace_path":
        return bool(tokens & {"workspace", "folder", "directory", "path", "repo", "repository"})
    if normalized_field in {"path", "output_path"}:
        return bool(
            re.search(
                r"(\.(?:docx|pdf|md|markdown|json)\b|\b(?:workspace|folder|download|filename|path|save)\b)",
                lowered,
            )
        )
    return False


def _looks_like_pending_clarification_intent_change(
    content: str,
    *,
    pending_state: chat_contracts.ClarificationState | None,
) -> bool:
    if pending_state is None:
        return False
    lowered = str(content or "").strip().lower()
    if not lowered:
        return False
    if re.search(r"\b(?:chat|answer|reply|respond|explain|here)\b", lowered) and re.search(
        r"\b(?:instead|only|just|not|no|skip|cancel|stop|rather)\b",
        lowered,
    ):
        return False
    tokens = set(re.findall(r"[a-z0-9]+", lowered))
    hints = _chat_thread_hints()
    if (
        len(tokens) > 12
        and bool(tokens & hints.artifact_tokens)
        and bool(tokens & hints.action_tokens)
    ):
        return True
    if _looks_like_local_clarification_field_answer(
        content,
        current_field=pending_state.current_question_field,
    ):
        return False
    redirect_patterns = (
        r"\bactually\b",
        r"\binstead\b",
        r"\brather\b",
        r"\bstart over\b",
        r"\brestart\b",
        r"\bnew request\b",
        r"\bdifferent request\b",
        r"\bmake this\b",
        r"\bturn this\b",
        r"\bconvert this\b",
    )
    if not any(re.search(pattern, lowered) for pattern in redirect_patterns):
        return False
    return bool(tokens & hints.artifact_tokens) and bool(tokens & hints.action_tokens)


# ─── Turn pipeline ─────────────────────────────────────────────────────────────


def _build_turn_context(
    db: Session,
    session_id: str,
    request: chat_contracts.ChatTurnRequest,
    *,
    chat: ChatRuntime,
    agent: AgentRuntime,
    user_id: str | None,
) -> TurnContext:
    """Validate session access, assemble all pre-routing state, and return TurnContext."""
    _tc0 = time.perf_counter()
    _cached = _get_cached_session(session_id)
    if _cached is not None:
        # Warm path: skip the SELECT on chat_sessions entirely.  We have all
        # fields we need from last turn's post-persist snapshot.  A lightweight
        # namespace works wherever the code uses record.field; _persist_chat_session_state
        # does its own fresh SELECT internally so the ORM identity map is not needed here.
        import types as _types
        record: Any = _types.SimpleNamespace(
            id=session_id,
            title=_cached.title,
            metadata_json=dict(_cached.metadata_json),
            updated_at=_cached.updated_at,
            created_at=_cached.created_at,
        )
        _cache_hit = True
    else:
        record = db.query(ChatSessionRecord).filter(ChatSessionRecord.id == session_id).first()
        if record is None:
            raise KeyError(session_id)
        _cache_hit = False
    _tc1 = time.perf_counter()
    if not _chat_session_access_allowed(record, user_id):
        raise KeyError(session_id)

    content = str(request.content or "").strip()
    if not content:
        raise ValueError("content_required")

    now = chat.utcnow()
    session_metadata = dict(record.metadata_json or {})
    session_metadata["_chat_session_id"] = record.id
    loaded_updated_at = record.updated_at
    loaded_state_version = _session_state_version(session_metadata)
    cleared_session_keys: set[str] = set()

    bound_user_id = _normalized_user_id(user_id) or _chat_session_user_id(session_metadata)
    if bound_user_id and not _chat_session_user_id(session_metadata):
        session_metadata[_INTERNAL_CHAT_USER_ID_KEY] = bound_user_id

    # Detect pending clarification state before any mapping
    pending_lifecycle = clarification_lifecycle_from_metadata(session_metadata)
    pending_state = pending_lifecycle.state if pending_lifecycle.active else None
    had_pending_clarification = pending_state is not None
    had_pending_workflow_input = isinstance(session_metadata.get("pending_workflow_input"), Mapping)
    exit_pending_to_chat = bool(
        pending_state is not None
        and chat.is_chat_only_correction is not None
        and chat.is_chat_only_correction(content)
    )

    restarted_pending_clarification = False
    if _looks_like_pending_clarification_intent_change(content, pending_state=pending_state):
        restarted_pending_clarification = True
        clear_pending_clarification_state(session_metadata, include_workflow_input=True)

    # Build context
    session_context = _sanitize_chat_context(_coerce_context_json(session_metadata.get("context_json")))
    turn_context_json = _sanitize_chat_context(
        _prepare_turn_context(request.context_json, session_metadata=session_metadata, content=content)
    )
    _tc2 = time.perf_counter()
    messages = _message_records_for_session(db, record.id)
    _tc3 = time.perf_counter()
    chat_messages = [_message_from_record(m) for m in messages]
    _tc3a = time.perf_counter()
    candidate_goal = (
        content.strip()
        if restarted_pending_clarification
        else _candidate_goal(content, session_metadata, messages=chat_messages,
                             is_chat_only_correction=chat.is_chat_only_correction)
    )
    _tc4 = time.perf_counter()
    context_envelope = context_service.build_chat_context_envelope(
        db=db,
        goal=candidate_goal,
        session_metadata=session_metadata,
        session_context=session_context,
        turn_context=turn_context_json,
        user_id=bound_user_id,
    )
    _tc5 = time.perf_counter()
    merged_context = context_service.chat_submit_context_view(context_envelope)
    logger.info(
        "chat_build_context_timing",
        extra={
            "cache_hit": _cache_hit,
            "session_ms": round((_tc1 - _tc0) * 1000, 1),
            "gap1_ms": round((_tc2 - _tc1) * 1000, 1),
            "messages_ms": round((_tc3 - _tc2) * 1000, 1),
            "convert_ms": round((_tc3a - _tc3) * 1000, 1),
            "goal_ms": round((_tc4 - _tc3a) * 1000, 1),
            "gap2_ms": round((_tc4 - _tc3) * 1000, 1),
            "envelope_ms": round((_tc5 - _tc4) * 1000, 1),
            "total_build_ms": round((_tc5 - _tc0) * 1000, 1),
            "session_id": session_id,
        },
    )

    # Apply pending clarification slot mapping (may update goal / context)
    pending_state_before_mapping = _parse_pending_clarification_state(session_metadata)
    (
        candidate_goal,
        context_envelope,
        merged_context,
        session_metadata,
        pre_route_normalization,
    ) = _apply_pending_clarification_mapping(
        db=db,
        runtime=ChatServiceRuntime(
            route_turn=chat.route_turn,
            run_direct_capability=agent.run_direct_capability,
            create_job=agent.create_job,
            run_workflow=agent.run_workflow,
            inspect_workflow=agent.inspect_workflow,
            utcnow=chat.utcnow,
            make_id=chat.make_id,
            normalize_submit_context=chat.normalize_submit_context,
            is_chat_only_correction=chat.is_chat_only_correction,
            defer_pending_clarification_mapping=chat.defer_pending_clarification_mapping,
        ),
        goal=candidate_goal,
        content=content,
        session_metadata=session_metadata,
        merged_context=merged_context,
        context_envelope=context_envelope,
        user_id=bound_user_id,
        messages=chat_messages,
    )
    pending_state_after_mapping = _parse_pending_clarification_state(session_metadata)
    clarification_mapping = _clarification_mapping_metadata(
        before_state=pending_state_before_mapping,
        after_state=pending_state_after_mapping,
        normalization=pre_route_normalization,
        restarted=restarted_pending_clarification,
    )

    return TurnContext(
        db=db,
        record=record,
        request=request,
        content=content,
        session_metadata=session_metadata,
        context_envelope=context_envelope,
        merged_context=merged_context,
        candidate_goal=candidate_goal,
        chat_messages=chat_messages,
        messages=messages,
        loaded_updated_at=loaded_updated_at,
        loaded_state_version=loaded_state_version,
        cleared_session_keys=cleared_session_keys,
        bound_user_id=bound_user_id,
        now=now,
        chat=chat,
        agent=agent,
        had_pending_clarification=had_pending_clarification,
        had_pending_workflow_input=had_pending_workflow_input,
        restarted_pending_clarification=restarted_pending_clarification,
        exit_pending_to_chat=exit_pending_to_chat,
        pre_route_normalization=pre_route_normalization,
        clarification_mapping=clarification_mapping,
    )


def _classify_turn(ctx: TurnContext) -> TurnPlan:
    """Route the turn through the chat LLM and convert the raw dict into a typed plan."""
    route_context = context_service.chat_route_context_view(ctx.context_envelope)
    try:
        turn_dict = ctx.chat.route_turn(
            content=ctx.content,
            candidate_goal=ctx.candidate_goal,
            session_metadata=ctx.session_metadata,
            merged_context=route_context,
            messages=ctx.chat_messages,
        )
    except llm_provider.LLMUnavailableError:
        raise
    except Exception as exc:  # noqa: BLE001
        logger.exception("chat_route_turn_failed", extra={"session_id": ctx.record.id})
        if llm_provider.is_llm_unavailable_error(exc):
            raise llm_provider.LLMUnavailableError(str(exc)) from exc
        raise llm_provider.LLMUnavailableError("chat_route_turn_failed") from exc

    return _plan_from_turn_dict(turn_dict, ctx)


def _plan_from_turn_dict(turn_dict: dict[str, Any], ctx: TurnContext) -> TurnPlan:
    """Convert the raw router dict into a typed TurnPlan, applying context updates."""
    # Persist normalized intent envelope into session
    normalized_intent_envelope: dict[str, Any] | None = (
        dict(turn_dict.get("normalized_intent_envelope"))
        if isinstance(turn_dict.get("normalized_intent_envelope"), Mapping)
        else None
    )
    if normalized_intent_envelope:
        ctx.session_metadata["normalized_intent_envelope"] = normalized_intent_envelope

    assessment = workflow_contracts.dump_goal_intent_profile(turn_dict.get("goal_intent_profile")) or {}
    route_type = str(turn_dict.get("type") or "").strip().lower() or "respond"
    resolved_goal = str(turn_dict.get("resolved_goal") or ctx.candidate_goal or "").strip() or ctx.content
    assistant_content = str(turn_dict.get("assistant_content") or "").strip()

    # Apply any context updates the router returned
    context_json_updates = (
        dict(turn_dict.get("context_json_updates"))
        if isinstance(turn_dict.get("context_json_updates"), Mapping)
        else {}
    )
    merged_context = ctx.merged_context
    context_envelope = ctx.context_envelope
    if context_json_updates:
        context_envelope = context_service.update_chat_context_envelope(
            context_envelope, goal=resolved_goal, context_json=context_json_updates,
        )
        merged_context = context_service.chat_submit_context_view(context_envelope)
        ctx.context_envelope = context_envelope
        ctx.merged_context = merged_context

    boundary_decision: dict[str, Any] | None = (
        dict(turn_dict.get("boundary_decision"))
        if isinstance(turn_dict.get("boundary_decision"), Mapping)
        else None
    )
    routing_decision: dict[str, Any] | None = (
        dict(turn_dict.get("routing_decision"))
        if isinstance(turn_dict.get("routing_decision"), Mapping)
        else None
    )

    if route_type == "ask_clarification":
        question_queue = [
            str(q).strip()
            for q in turn_dict.get("clarification_questions", assessment.get("questions", []))
            if isinstance(q, str) and q.strip()
        ]
        questions = _active_clarification_questions(question_queue)
        pending_state = _pending_clarification_state(
            resolved_goal=resolved_goal,
            questions=question_queue,
            assessment=assessment,
            session_metadata=ctx.session_metadata,
            context_json=merged_context,
            normalized_intent_envelope=normalized_intent_envelope,
            latest_user_answer=ctx.content,
        )
        return AskClarificationPlan(
            resolved_goal=resolved_goal,
            questions=questions,
            question_queue=question_queue,
            assessment=assessment,
            context_json=merged_context,
            pending_state=pending_state,
            assistant_content=assistant_content or ("\n".join(questions) if questions else ""),
            normalized_intent_envelope=normalized_intent_envelope,
        )

    if route_type == "submit_job":
        return SubmitJobPlan(
            resolved_goal=resolved_goal,
            merged_context=merged_context,
            assessment=assessment,
            assistant_content=assistant_content,
            normalization=ctx.pre_route_normalization,
        )

    if route_type == "run_workflow":
        return RunWorkflowPlan(
            resolved_goal=resolved_goal,
            merged_context=merged_context,
            assessment=assessment,
            assistant_content=assistant_content,
        )

    if route_type == "tool_call":
        raw_args = turn_dict.get("arguments")
        return ToolCallPlan(
            resolved_goal=resolved_goal,
            capability_id=str(turn_dict.get("capability_id") or "").strip(),
            arguments=dict(raw_args) if isinstance(raw_args, Mapping) else {},
            merged_context=merged_context,
            assessment=assessment,
            assistant_content=assistant_content,
        )

    return RespondPlan(
        resolved_goal=resolved_goal,
        merged_context=merged_context,
        assessment=assessment,
        assistant_content=assistant_content,
        clear_pending_clarification=bool(turn_dict.get("clear_pending_clarification")),
        boundary_decision=boundary_decision,
        routing_decision=routing_decision,
    )


def _execute_turn(plan: TurnPlan, ctx: TurnContext) -> TurnResult:
    """Dispatch to the executor for the given plan type."""
    if isinstance(plan, AskClarificationPlan):
        return _execute_ask_clarification(plan, ctx)
    if isinstance(plan, SubmitJobPlan):
        return _execute_submit_job(plan, ctx)
    if isinstance(plan, RunWorkflowPlan):
        return _execute_run_workflow(plan, ctx)
    if isinstance(plan, ToolCallPlan):
        return _execute_tool_call(plan, ctx)
    return _execute_respond(plan, ctx)  # type: ignore[arg-type]


def _execute_ask_clarification(plan: AskClarificationPlan, ctx: TurnContext) -> TurnResult:
    questions = plan.questions or _active_clarification_questions(plan.question_queue)
    content = plan.assistant_content or ("\n".join(questions) if questions else "")
    if not content:
        raise llm_provider.LLMUnavailableError("chat_clarification_response_empty")
    persist_pending_clarification_state(
        ctx.session_metadata,
        state=plan.pending_state,
        draft_goal=plan.resolved_goal,
        cleared_keys=ctx.cleared_session_keys,
    )
    return TurnResult(
        assistant_content=content,
        assistant_action=chat_contracts.AssistantAction(
            type=chat_contracts.AssistantActionType.ask_clarification,
            goal=plan.resolved_goal,
            clarification_questions=questions,
            goal_intent_profile=dict(plan.assessment),
            context_json=plan.context_json,
        ),
    )


def _execute_submit_job(plan: SubmitJobPlan, ctx: TurnContext) -> TurnResult:
    normalization = plan.normalization
    if normalization is None and ctx.chat.normalize_submit_context is not None:
        try:
            normalization = ctx.chat.normalize_submit_context(
                db=ctx.db,
                goal=plan.resolved_goal,
                content=ctx.content,
                session_metadata=ctx.session_metadata,
                merged_context=plan.merged_context,
                context_envelope=ctx.context_envelope,
                user_id=ctx.bound_user_id,
                messages=ctx.chat_messages,
            )
        except llm_provider.LLMUnavailableError:
            raise
        except Exception as exc:  # noqa: BLE001
            logger.exception("chat_submit_normalization_failed", extra={"session_id": ctx.record.id})
            if llm_provider.is_llm_unavailable_error(exc):
                raise llm_provider.LLMUnavailableError(str(exc)) from exc
            raise llm_provider.LLMUnavailableError("chat_submit_normalization_failed") from exc

    resolved_goal = plan.resolved_goal
    merged_context = plan.merged_context
    assessment = plan.assessment

    if normalization is not None:
        if isinstance(normalization.context_json, Mapping) and normalization.context_json:
            ctx.context_envelope = context_service.update_chat_context_envelope(
                ctx.context_envelope, goal=resolved_goal, context_json=normalization.context_json,
            )
            merged_context = context_service.chat_submit_context_view(ctx.context_envelope)
        if isinstance(normalization.goal, str) and normalization.goal.strip():
            resolved_goal = normalization.goal.strip()
            ctx.context_envelope = context_service.update_chat_context_envelope(
                ctx.context_envelope, goal=resolved_goal,
            )
        if isinstance(normalization.goal_intent_profile, Mapping) and normalization.goal_intent_profile:
            assessment = dict(normalization.goal_intent_profile)

        clarification_question_queue = [
            str(q).strip() for q in normalization.clarification_questions
            if isinstance(q, str) and q.strip()
        ]
        if normalization.requires_blocking_clarification and not clarification_question_queue:
            clarification_question_queue = _submit_normalization_failure_questions(
                session_metadata=ctx.session_metadata, assessment=assessment,
            )
        if normalization.requires_blocking_clarification and not clarification_question_queue:
            raise llm_provider.LLMUnavailableError("chat_submit_clarification_empty")
        clarification_questions = _active_clarification_questions(clarification_question_queue)
        if clarification_questions or normalization.requires_blocking_clarification:
            content = "\n".join(clarification_questions or clarification_question_queue)
            persist_pending_clarification_state(
                ctx.session_metadata,
                state=_pending_clarification_state(
                    resolved_goal=resolved_goal,
                    questions=clarification_question_queue,
                    assessment=assessment,
                    session_metadata=ctx.session_metadata,
                    context_json=merged_context,
                    normalized_intent_envelope=ctx.session_metadata.get("normalized_intent_envelope"),
                    latest_user_answer=ctx.content,
                ),
                draft_goal=resolved_goal,
                cleared_keys=ctx.cleared_session_keys,
            )
            return TurnResult(
                assistant_content=content,
                assistant_action=chat_contracts.AssistantAction(
                    type=chat_contracts.AssistantActionType.ask_clarification,
                    goal=resolved_goal,
                    clarification_questions=clarification_questions,
                    goal_intent_profile=dict(assessment),
                    context_json=merged_context,
                ),
            )

    job, action = _create_job_and_action(
        db=ctx.db,
        runtime=ChatServiceRuntime(
            route_turn=ctx.chat.route_turn,
            run_direct_capability=ctx.agent.run_direct_capability,
            create_job=ctx.agent.create_job,
            run_workflow=ctx.agent.run_workflow,
            inspect_workflow=ctx.agent.inspect_workflow,
            utcnow=ctx.chat.utcnow,
            make_id=ctx.chat.make_id,
        ),
        resolved_goal=resolved_goal,
        merged_context=merged_context,
        assessment=assessment,
        priority=ctx.request.priority,
        session_metadata=ctx.session_metadata,
        cleared_session_keys=ctx.cleared_session_keys,
    )
    content = plan.assistant_content or (
        f"Started job {job.id}. I submitted it to the normal planner and worker pipeline."
    )
    return TurnResult(assistant_content=content, assistant_action=action, created_job=job)


def _execute_run_workflow(plan: RunWorkflowPlan, ctx: TurnContext) -> TurnResult:
    workflow_invocation = workflow_invocation_from_context(plan.merged_context)
    if workflow_invocation is None or not workflow_invocation.has_target():
        question = (
            "Which published workflow should I run? Provide workflow_trigger_id, "
            "workflow_version_id, or workflow_definition_id in context_json."
        )
        workflow_assessment = {
            **dict(plan.assessment),
            "needs_clarification": True,
            "requires_blocking_clarification": True,
            "questions": [question],
        }
        persist_pending_clarification_state(
            ctx.session_metadata,
            state=_pending_clarification_state(
                resolved_goal=plan.resolved_goal,
                questions=[question],
                assessment=workflow_assessment,
                session_metadata=ctx.session_metadata,
                context_json=plan.merged_context,
                normalized_intent_envelope=ctx.session_metadata.get("normalized_intent_envelope"),
                latest_user_answer=ctx.content,
            ),
            draft_goal=plan.resolved_goal,
            cleared_keys=ctx.cleared_session_keys,
        )
        return TurnResult(
            assistant_content=plan.assistant_content or question,
            assistant_action=chat_contracts.AssistantAction(
                type=chat_contracts.AssistantActionType.ask_clarification,
                goal=plan.resolved_goal,
                clarification_questions=[question],
                goal_intent_profile=dict(plan.assessment),
                context_json=plan.merged_context,
            ),
        )

    try:
        workflow_inspection = ctx.agent.inspect_workflow(
            db=ctx.db,
            workflow_trigger_id=workflow_invocation.trigger_id,
            workflow_version_id=workflow_invocation.version_id,
            workflow_definition_id=workflow_invocation.definition_id,
            inputs=workflow_invocation.inputs,
            context_json=workflow_invocation.context_json,
        )
        if workflow_inspection.missing_inputs:
            next_input = workflow_inspection.missing_inputs[0]
            question = _workflow_input_question(next_input)
            workflow_assessment = {
                **dict(plan.assessment),
                "needs_clarification": True,
                "requires_blocking_clarification": True,
                "questions": [question],
            }
            persist_pending_clarification_state(
                ctx.session_metadata,
                state=_pending_clarification_state(
                    resolved_goal=plan.resolved_goal,
                    questions=[question],
                    assessment=workflow_assessment,
                    session_metadata=ctx.session_metadata,
                    context_json=plan.merged_context,
                    normalized_intent_envelope=ctx.session_metadata.get("normalized_intent_envelope"),
                    latest_user_answer=ctx.content,
                ),
                draft_goal=plan.resolved_goal,
                cleared_keys=ctx.cleared_session_keys,
            )
            ctx.session_metadata["pending_workflow_input"] = dict(next_input)
            return TurnResult(
                assistant_content=plan.assistant_content or question,
                assistant_action=chat_contracts.AssistantAction(
                    type=chat_contracts.AssistantActionType.ask_clarification,
                    goal=plan.resolved_goal,
                    clarification_questions=[question],
                    goal_intent_profile=dict(plan.assessment),
                    context_json=plan.merged_context,
                ),
            )

        workflow_result = ctx.agent.run_workflow(
            db=ctx.db,
            workflow_trigger_id=workflow_invocation.trigger_id,
            workflow_version_id=workflow_invocation.version_id,
            workflow_definition_id=workflow_invocation.definition_id,
            inputs=workflow_invocation.inputs,
            context_json=workflow_invocation.context_json,
            metadata={**workflow_invocation.metadata, "chat_session_id": ctx.record.id},
            idempotency_key=workflow_invocation.idempotency_key,
            priority=ctx.request.priority,
        )
        created_job = workflow_result.job
        workflow_run = workflow_result.workflow_run
        ctx.session_metadata["active_job_id"] = created_job.id
        ctx.session_metadata["active_workflow_run_id"] = workflow_run.id
        ctx.session_metadata["active_workflow_definition_id"] = workflow_run.definition_id
        ctx.session_metadata["active_workflow_version_id"] = workflow_run.version_id
        if workflow_run.trigger_id:
            ctx.session_metadata["active_workflow_trigger_id"] = workflow_run.trigger_id
        else:
            ctx.session_metadata.pop("active_workflow_trigger_id", None)
            ctx.cleared_session_keys.add("active_workflow_trigger_id")
        clear_pending_clarification_state(
            ctx.session_metadata,
            cleared_keys=ctx.cleared_session_keys,
            include_workflow_input=True,
        )
        content = plan.assistant_content or (
            f"Started workflow run {workflow_run.id}. Job {created_job.id} is queued."
        )
        return TurnResult(
            assistant_content=content,
            assistant_action=chat_contracts.AssistantAction(
                type=chat_contracts.AssistantActionType.run_workflow,
                goal=plan.resolved_goal,
                job_id=created_job.id,
                workflow_run_id=workflow_run.id,
                workflow_definition_id=workflow_run.definition_id,
                workflow_version_id=workflow_run.version_id,
                workflow_trigger_id=workflow_run.trigger_id,
                goal_intent_profile=dict(plan.assessment),
                context_json=plan.merged_context,
            ),
            created_job=created_job,
            workflow_run=workflow_run,
        )
    except Exception as exc:  # noqa: BLE001
        content = f"I could not start that published workflow from chat. Workflow invocation failed: {exc}"
        return TurnResult(
            assistant_content=content,
            assistant_action=chat_contracts.AssistantAction(
                type=chat_contracts.AssistantActionType.respond,
                goal=plan.resolved_goal,
                goal_intent_profile=dict(plan.assessment),
                context_json=plan.merged_context,
            ),
        )


def _execute_tool_call(plan: ToolCallPlan, ctx: TurnContext) -> TurnResult:
    arguments = _enrich_memory_arguments(plan.capability_id, plan.arguments, plan.merged_context)
    label = plan.capability_id.replace(".", " ").replace("_", " ").title()
    ctx.emit_progress("tool_start", {"capability": plan.capability_id, "label": f"Running {label}"})
    try:
        direct_result = ctx.agent.run_direct_capability(
            db=ctx.db,
            chat_session_id=ctx.record.id,
            goal=plan.resolved_goal,
            capability_id=plan.capability_id,
            arguments=arguments,
            context_json=plan.merged_context,
            priority=ctx.request.priority,
        )
        created_job = direct_result.job
        if direct_result.error:
            content = (
                f"I could not complete that directly in chat. One-step run failed: {direct_result.error}"
            )
            return TurnResult(
                assistant_content=content,
                assistant_action=chat_contracts.AssistantAction(
                    type=chat_contracts.AssistantActionType.respond,
                    goal=plan.resolved_goal,
                    job_id=created_job.id,
                    goal_intent_profile=dict(plan.assessment),
                    context_json=plan.merged_context,
                ),
                created_job=created_job,
            )
        direct_output = (
            dict(direct_result.output) if isinstance(direct_result.output, Mapping) else None
        )
        ctx.emit_progress("tool_done", {
            "capability": direct_result.capability_id or plan.capability_id,
            "label": f"{label} complete",
            **({"result": direct_output} if direct_output else {}),
        })
        content = str(direct_result.assistant_response or plan.assistant_content).strip()
        clear_pending_clarification_state(
            ctx.session_metadata,
            cleared_keys=ctx.cleared_session_keys,
            include_workflow_input=True,
        )
        return TurnResult(
            assistant_content=content,
            assistant_action=chat_contracts.AssistantAction(
                type=chat_contracts.AssistantActionType.tool_call,
                goal=plan.resolved_goal,
                job_id=created_job.id,
                capability_id=direct_result.capability_id or plan.capability_id or None,
                tool_name=direct_result.tool_name,
                goal_intent_profile=dict(plan.assessment),
                context_json=plan.merged_context,
            ),
            created_job=created_job,
            direct_output=direct_output,
        )
    except Exception as exc:  # noqa: BLE001
        content = f"I could not complete that directly in chat. One-step run failed: {exc}"
        return TurnResult(
            assistant_content=content,
            assistant_action=chat_contracts.AssistantAction(
                type=chat_contracts.AssistantActionType.respond,
                goal=plan.resolved_goal,
                goal_intent_profile=dict(plan.assessment),
                context_json=plan.merged_context,
            ),
        )


def _execute_respond(plan: RespondPlan, ctx: TurnContext) -> TurnResult:
    if plan.clear_pending_clarification:
        clear_pending_clarification_state(
            ctx.session_metadata,
            cleared_keys=ctx.cleared_session_keys,
            include_workflow_input=True,
        )
    return TurnResult(
        assistant_content=plan.assistant_content,
        assistant_action=chat_contracts.AssistantAction(
            type=chat_contracts.AssistantActionType.respond,
            goal=plan.resolved_goal,
            goal_intent_profile=dict(plan.assessment),
            context_json=plan.merged_context,
        ),
        boundary_decision=plan.boundary_decision,
        routing_decision=plan.routing_decision,
    )


def _persist_turn(
    db: Session,
    ctx: TurnContext,
    result: TurnResult,
    user_message: ChatMessageRecord,
    assistant_message: ChatMessageRecord,
) -> dict[str, Any]:
    """Persist session state and commit both messages; return the saved metadata."""
    if ctx.restarted_pending_clarification:
        for key in ("draft_goal", "pending_clarification", "pending_workflow_input"):
            if key not in ctx.session_metadata:
                ctx.cleared_session_keys.add(key)

    context_envelope = context_service.update_chat_context_envelope(
        ctx.context_envelope, goal=_resolved_goal_from_result(result),
        context_json=ctx.merged_context,
    )
    ctx.merged_context = context_service.chat_submit_context_view(context_envelope)
    ctx.session_metadata["context_json"] = ctx.merged_context

    desired_title = ctx.record.title
    if desired_title == "New chat":
        desired_title = _default_session_title(_resolved_goal_from_result(result))

    try:
        saved_metadata = _persist_chat_session_state(
            db=db,
            record=ctx.record,
            desired_metadata=ctx.session_metadata,
            desired_title=desired_title,
            loaded_updated_at=ctx.loaded_updated_at,
            loaded_state_version=ctx.loaded_state_version,
            cleared_keys=ctx.cleared_session_keys,
            runtime=ChatServiceRuntime(
                route_turn=ctx.chat.route_turn,
                run_direct_capability=ctx.agent.run_direct_capability,
                create_job=ctx.agent.create_job,
                run_workflow=ctx.agent.run_workflow,
                inspect_workflow=ctx.agent.inspect_workflow,
                utcnow=ctx.chat.utcnow,
                make_id=ctx.chat.make_id,
            ),
        )
    except RuntimeError:
        logger.exception("chat_session_state_persist_failed", extra={"session_id": ctx.record.id})
        saved_metadata = dict(ctx.record.metadata_json or {})

    db.add(user_message)
    db.add(assistant_message)
    db.commit()
    return saved_metadata


def _resolved_goal_from_result(result: TurnResult) -> str:
    return str(result.assistant_action.goal or "").strip()


def _create_job_and_action(
    *,
    db: Session,
    runtime: ChatServiceRuntime,
    resolved_goal: str,
    merged_context: dict[str, Any],
    assessment: Mapping[str, Any],
    priority: Any,
    session_metadata: dict[str, Any],
    cleared_session_keys: set[str],
) -> tuple[models.Job, chat_contracts.AssistantAction]:
    job = runtime.create_job(
        models.JobCreate(
            goal=resolved_goal,
            context_json=merged_context,
            priority=priority,
            planning_mode=models.PlanningMode.adaptive,
        ),
        db,
    )
    action = chat_contracts.AssistantAction(
        type=chat_contracts.AssistantActionType.submit_job,
        goal=resolved_goal,
        job_id=job.id,
        goal_intent_profile=dict(assessment),
        context_json=merged_context,
    )
    session_metadata["active_job_id"] = job.id
    clear_pending_clarification_state(session_metadata, cleared_keys=cleared_session_keys)
    return job, action


def create_session(
    db: Session,
    request: chat_contracts.ChatSessionCreate,
    *,
    runtime: ChatServiceRuntime,
    user_id: str | None = None,
) -> chat_contracts.ChatSession:
    now = runtime.utcnow()
    title = str(request.title or "").strip() or "New chat"
    metadata = _coerce_context_json(request.metadata)
    metadata.pop(_INTERNAL_CHAT_USER_ID_KEY, None)
    metadata.pop("user_id", None)
    metadata.pop("semantic_user_id", None)
    if isinstance(metadata.get("context_json"), Mapping):
        metadata["context_json"] = _sanitize_chat_context(metadata.get("context_json"))
    if _normalized_user_id(user_id):
        metadata[_INTERNAL_CHAT_USER_ID_KEY] = _normalized_user_id(user_id)
    metadata[_CHAT_STATE_VERSION_KEY] = max(1, _session_state_version(metadata) or 1)
    record = ChatSessionRecord(
        id=runtime.make_id(),
        title=title,
        metadata_json=metadata,
        created_at=now,
        updated_at=now,
    )
    db.add(record)
    db.commit()
    return get_session(db, record.id, user_id=user_id)


def get_session(
    db: Session,
    session_id: str,
    *,
    user_id: str | None = None,
) -> chat_contracts.ChatSession | None:
    record = db.query(ChatSessionRecord).filter(ChatSessionRecord.id == session_id).first()
    if record is None:
        return None
    if not _chat_session_access_allowed(record, user_id):
        return None
    messages = (
        db.query(ChatMessageRecord)
        .filter(ChatMessageRecord.session_id == session_id)
        .order_by(ChatMessageRecord.created_at.asc(), ChatMessageRecord.id.asc())
        .all()
    )
    return _session_from_record(record, messages)


def handle_turn(
    db: Session,
    session_id: str,
    request: chat_contracts.ChatTurnRequest,
    *,
    runtime: ChatServiceRuntime,
    user_id: str | None = None,
) -> chat_contracts.ChatTurnResponse:
    chat, agent = _decompose_runtime(runtime)

    ctx = _build_turn_context(db, session_id, request, chat=chat, agent=agent, user_id=user_id)

    user_message = ChatMessageRecord(
        id=chat.make_id(),
        session_id=ctx.record.id,
        role=chat_contracts.ChatRole.user.value,
        content=ctx.content,
        metadata_json=(
            {"context_json": _sanitize_chat_context(
                _prepare_turn_context(request.context_json,
                                     session_metadata=ctx.session_metadata,
                                     content=ctx.content)
            )}
        ),
        action_json=None,
        job_id=None,
        created_at=ctx.now,
    )

    try:
        plan: TurnPlan = _classify_turn(ctx)
        result: TurnResult = _execute_turn(plan, ctx)
    except llm_provider.LLMUnavailableError as exc:
        logger.warning("chat_llm_unavailable", extra={"session_id": ctx.record.id, "reason": str(exc)[:120]})
        raise ValueError("chat_llm_unavailable") from exc

    if not result.assistant_content:
        logger.warning("chat_llm_empty_response", extra={"session_id": ctx.record.id})
        raise ValueError("chat_llm_unavailable")

    assistant_message = ChatMessageRecord(
        id=chat.make_id(),
        session_id=ctx.record.id,
        role=chat_contracts.ChatRole.assistant.value,
        content=result.assistant_content,
        metadata_json=_assistant_metadata(
            result.assistant_action.goal_intent_profile or {},
            result.direct_output,
            result.workflow_run,
            boundary_decision=result.boundary_decision,
            clarification_mapping=ctx.clarification_mapping,
            routing_decision=result.routing_decision,
        ),
        action_json=result.assistant_action.model_dump(mode="json", exclude_none=True),
        job_id=result.created_job.id if result.created_job is not None else None,
        created_at=chat.utcnow(),
    )

    _persist_turn(db, ctx, result, user_message, assistant_message)

    # Update the session cache with the post-persist record state so the NEXT
    # turn can skip the SELECT on chat_sessions entirely.
    _put_cached_session(
        session_id=ctx.record.id,
        metadata_json=dict(ctx.record.metadata_json or {}),
        updated_at=ctx.record.updated_at,
        title=ctx.record.title,
        created_at=ctx.record.created_at,
    )

    if ctx.bound_user_id:
        try:
            memory_profile_service.apply_user_profile_updates_from_text(
                db, user_id=ctx.bound_user_id, content=ctx.content,
            )
        except Exception:  # noqa: BLE001
            logger.exception("chat_profile_memory_persist_failed",
                             extra={"session_id": ctx.record.id})

    return chat_contracts.ChatTurnResponse(
        session=_session_from_record(ctx.record, [*ctx.messages, user_message, assistant_message]),
        user_message=_message_from_record(user_message),
        assistant_message=_message_from_record(assistant_message),
        job=result.created_job,
        workflow_run=result.workflow_run,
    )


def _candidate_goal(
    content: str,
    session_metadata: Mapping[str, Any],
    *,
    messages: Sequence[chat_contracts.ChatMessage] | None = None,
    is_chat_only_correction: Callable[[str], bool] | None = None,
) -> str:
    draft_goal = session_metadata.get("draft_goal")
    pending_state = _parse_pending_clarification_state(session_metadata)
    if not _clarification_state_has_pending_work(pending_state):
        pending_state = None
    original_goal = str(pending_state.original_goal or "").strip() if pending_state is not None else ""
    if original_goal:
        return f"{original_goal}\n\nUser clarification: {content.strip()}"
    if isinstance(draft_goal, str) and draft_goal.strip() and pending_state is not None:
        return f"{draft_goal.strip()}\n\nUser clarification: {content.strip()}"
    threaded_goal = _execution_thread_candidate_goal(
        content,
        messages=messages,
        # Only check for chat-only corrections when there is an active pending
        # clarification state — otherwise the LLM call is wasted on every turn.
        is_chat_only_correction=is_chat_only_correction if pending_state is not None else None,
    )
    if threaded_goal:
        return threaded_goal
    return content.strip()


def _execution_thread_candidate_goal(
    content: str,
    *,
    messages: Sequence[chat_contracts.ChatMessage] | None,
    is_chat_only_correction: Callable[[str], bool] | None = None,
) -> str:
    current = str(content or "").strip()
    if not current:
        return ""
    if is_chat_only_correction is not None and is_chat_only_correction(current):
        return ""
    lowered_current = current.lower()
    if lowered_current in {"thanks", "thank you", "ok", "okay", "cool"}:
        return ""

    recent_user_messages = [
        str(message.content or "").strip()
        for message in list(messages or [])[-8:]
        if str(getattr(message, "role", "")).lower().endswith("user")
        and str(message.content or "").strip()
    ]
    if not recent_user_messages:
        return ""

    execution_blob = " ".join(recent_user_messages).lower()
    thread_hints = _chat_thread_hints()
    execution_tokens = set(re.findall(r"[a-z0-9]+", execution_blob))
    has_execution_action = bool(execution_tokens & thread_hints.action_tokens)
    has_execution_artifact = bool(execution_tokens & thread_hints.artifact_tokens)
    if not (has_execution_action and has_execution_artifact):
        return ""

    current_tokens = set(re.findall(r"[a-z0-9]+", lowered_current))
    if len(current.split()) > 80 and not (current_tokens & thread_hints.continuation_tokens):
        return ""

    parts: list[str] = []
    for message in recent_user_messages[-5:]:
        if message not in parts:
            parts.append(message)
    if current not in parts:
        parts.append(current)
    if len(parts) < 2:
        return ""
    return "\n\nUser clarification: ".join(parts)


_CHAT_THREAD_HINTS_CACHE: ChatThreadHints | None = None
_CHAT_THREAD_HINTS_CACHE_KEY: int | None = None


def _chat_thread_hints() -> ChatThreadHints:
    global _CHAT_THREAD_HINTS_CACHE, _CHAT_THREAD_HINTS_CACHE_KEY
    # Check our own cache first — avoids calling load_capability_registry (which
    # runs stat() on the YAML file) on every hot turn.
    if _CHAT_THREAD_HINTS_CACHE is not None:
        try:
            registry = capability_registry.load_capability_registry()
        except Exception:  # noqa: BLE001
            return _CHAT_THREAD_HINTS_CACHE
        if _CHAT_THREAD_HINTS_CACHE_KEY == id(registry):
            return _CHAT_THREAD_HINTS_CACHE

    action_tokens = set(_BOOTSTRAP_EXECUTION_ACTION_TOKENS)
    artifact_tokens = set(_BOOTSTRAP_EXECUTION_ARTIFACT_TOKENS)
    continuation_tokens = set(_BOOTSTRAP_CONTINUATION_TOKENS)
    try:
        registry = capability_registry.load_capability_registry()
    except Exception:  # noqa: BLE001
        return ChatThreadHints(
            action_tokens=frozenset(action_tokens),
            artifact_tokens=frozenset(artifact_tokens),
            continuation_tokens=frozenset(continuation_tokens),
        )

    cache_key = id(registry)

    for spec in registry.enabled_capabilities().values():
        artifact_tokens.update(_tokens_from_text(spec.capability_id))
        artifact_tokens.update(_tokens_from_text(spec.group or ""))
        artifact_tokens.update(_tokens_from_text(spec.subgroup or ""))
        for value in (*spec.tags, *spec.aliases):
            artifact_tokens.update(_tokens_from_text(value))
        hints = spec.planner_hints if isinstance(spec.planner_hints, Mapping) else {}
        action_tokens.update(_tokens_from_sequence(hints.get("task_intents")))
        raw_thread_hints = hints.get("chat_thread_hints")
        if not isinstance(raw_thread_hints, Mapping):
            continue
        action_tokens.update(_tokens_from_sequence(raw_thread_hints.get("action_tokens")))
        artifact_tokens.update(_tokens_from_sequence(raw_thread_hints.get("artifact_tokens")))
        continuation_tokens.update(_tokens_from_sequence(raw_thread_hints.get("continuation_tokens")))

    result = ChatThreadHints(
        action_tokens=frozenset(action_tokens),
        artifact_tokens=frozenset(artifact_tokens),
        continuation_tokens=frozenset(continuation_tokens),
    )
    _CHAT_THREAD_HINTS_CACHE = result
    _CHAT_THREAD_HINTS_CACHE_KEY = cache_key
    return result


def get_chat_thread_hints() -> ChatThreadHints:
    """Public accessor for use by the routing layer."""
    return _chat_thread_hints()


def _tokens_from_sequence(value: Any) -> set[str]:
    tokens: set[str] = set()
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return tokens
    for item in value:
        if isinstance(item, str):
            tokens.update(_tokens_from_text(item))
    return tokens


def _tokens_from_text(value: str) -> set[str]:
    return {
        token
        for token in re.findall(r"[a-z0-9]+", str(value or "").lower())
        if token
    }


def _message_records_for_session(db: Session, session_id: str) -> list[ChatMessageRecord]:
    records = (
        db.query(ChatMessageRecord)
        .filter(ChatMessageRecord.session_id == session_id)
        .order_by(ChatMessageRecord.created_at.desc(), ChatMessageRecord.id.desc())
        .limit(CHAT_HISTORY_CONTEXT_LIMIT)
        .all()
    )
    return sorted(records, key=lambda m: (m.created_at, m.id))


def _coerce_context_json(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    return {}


def _prepare_turn_context(
    value: Any,
    *,
    session_metadata: Mapping[str, Any],
    content: str,
) -> dict[str, Any]:
    turn_context = context_service.sanitize_user_context(_coerce_context_json(value))
    pending_input = session_metadata.get("pending_workflow_input")
    if not isinstance(pending_input, Mapping):
        return turn_context
    input_key = _normalized_optional_str(pending_input.get("key"))
    if not input_key:
        return turn_context

    workflow_inputs = (
        dict(turn_context.get("workflow_inputs"))
        if isinstance(turn_context.get("workflow_inputs"), Mapping)
        else {}
    )
    if input_key in workflow_inputs:
        if _workflow_input_omission_requested(workflow_inputs.get(input_key)):
            workflow_inputs[input_key] = None
        turn_context["workflow_inputs"] = workflow_inputs
        return turn_context

    if input_key in turn_context:
        raw_value = turn_context[input_key]
        workflow_inputs[input_key] = (
            None if _workflow_input_omission_requested(raw_value) else raw_value
        )
    elif str(content or "").strip():
        workflow_inputs[input_key] = (
            None if _workflow_input_omission_requested(content) else str(content).strip()
        )

    if workflow_inputs:
        turn_context["workflow_inputs"] = workflow_inputs
    return turn_context


def _merge_chat_context(
    session_context: Mapping[str, Any],
    turn_context: Mapping[str, Any],
) -> dict[str, Any]:
    merged = {**dict(session_context), **dict(turn_context)}
    for key in ("workflow_inputs", "workflow_context_json", "workflow_run_metadata"):
        session_value = session_context.get(key)
        turn_value = turn_context.get(key)
        if isinstance(session_value, Mapping) or isinstance(turn_value, Mapping):
            merged[key] = {
                **(dict(session_value) if isinstance(session_value, Mapping) else {}),
                **(dict(turn_value) if isinstance(turn_value, Mapping) else {}),
            }
    session_ref = session_context.get("workflow_ref")
    turn_ref = turn_context.get("workflow_ref")
    if isinstance(session_ref, Mapping) or isinstance(turn_ref, Mapping):
        merged["workflow_ref"] = {
            **(dict(session_ref) if isinstance(session_ref, Mapping) else {}),
            **(dict(turn_ref) if isinstance(turn_ref, Mapping) else {}),
        }
    return merged


def workflow_invocation_from_context(
    value: Mapping[str, Any] | None,
) -> ChatWorkflowInvocation | None:
    context = dict(value) if isinstance(value, Mapping) else {}
    nested = context.get("workflow_ref")
    nested_ref = dict(nested) if isinstance(nested, Mapping) else {}

    control_keys = {
        "workflow_ref",
        "workflow_trigger_id",
        "workflow_version_id",
        "workflow_definition_id",
        "workflow_inputs",
        "workflow_context_json",
        "workflow_run_metadata",
        "workflow_idempotency_key",
    }
    passthrough_context = {
        key: raw_value for key, raw_value in context.items() if key not in control_keys
    }

    trigger_id = _normalized_optional_str(
        context.get("workflow_trigger_id") or nested_ref.get("trigger_id")
    )
    version_id = _normalized_optional_str(
        context.get("workflow_version_id") or nested_ref.get("version_id")
    )
    definition_id = _normalized_optional_str(
        context.get("workflow_definition_id") or nested_ref.get("definition_id")
    )

    raw_inputs = context.get("workflow_inputs")
    if not isinstance(raw_inputs, Mapping):
        raw_inputs = nested_ref.get("inputs")
    inputs = dict(raw_inputs) if isinstance(raw_inputs, Mapping) else {}

    raw_context_override = context.get("workflow_context_json")
    if not isinstance(raw_context_override, Mapping):
        raw_context_override = nested_ref.get("context_json")
    context_override = (
        dict(raw_context_override) if isinstance(raw_context_override, Mapping) else {}
    )

    raw_metadata = context.get("workflow_run_metadata")
    if not isinstance(raw_metadata, Mapping):
        raw_metadata = nested_ref.get("metadata")
    metadata = dict(raw_metadata) if isinstance(raw_metadata, Mapping) else {}

    idempotency_key = _normalized_optional_str(
        context.get("workflow_idempotency_key") or nested_ref.get("idempotency_key")
    )

    invocation = ChatWorkflowInvocation(
        trigger_id=trigger_id,
        version_id=version_id,
        definition_id=definition_id,
        inputs=inputs,
        context_json={**passthrough_context, **context_override},
        metadata=metadata,
        idempotency_key=idempotency_key,
    )
    if invocation.has_target():
        return invocation
    return None


def _default_session_title(goal: str) -> str:
    title = " ".join(str(goal or "").split()).strip()
    if not title:
        return "New chat"
    return title[:80]


def _enrich_memory_arguments(
    capability_id: str,
    arguments: dict[str, Any],
    merged_context: Mapping[str, Any],
) -> dict[str, Any]:
    if capability_id not in {"memory.read", "memory.semantic.search"}:
        return arguments
    normalized_user_id = str(
        merged_context.get("user_id") or merged_context.get("semantic_user_id") or ""
    ).strip()
    if not normalized_user_id or str(arguments.get("user_id") or "").strip():
        return arguments
    enriched = dict(arguments)
    enriched["user_id"] = normalized_user_id
    if capability_id == "memory.read" and not str(enriched.get("scope") or "").strip():
        enriched["scope"] = "user"
    return enriched


def _session_from_record(
    record: ChatSessionRecord,
    messages: list[ChatMessageRecord],
) -> chat_contracts.ChatSession:
    metadata = _public_session_metadata(record.metadata_json)
    return chat_contracts.ChatSession(
        id=record.id,
        title=record.title,
        created_at=record.created_at,
        updated_at=record.updated_at,
        metadata=metadata,
        active_job_id=_active_job_id(metadata),
        messages=[_message_from_record(message) for message in messages],
    )


def _message_from_record(record: ChatMessageRecord) -> chat_contracts.ChatMessage:
    action = None
    if isinstance(record.action_json, dict):
        action_payload = dict(record.action_json)
        if isinstance(action_payload.get("context_json"), Mapping):
            action_payload["context_json"] = _sanitize_chat_context(action_payload.get("context_json"))
        action = chat_contracts.AssistantAction.model_validate(action_payload)
    return chat_contracts.ChatMessage(
        id=record.id,
        session_id=record.session_id,
        role=record.role,
        content=record.content,
        created_at=record.created_at,
        metadata=_public_session_metadata(record.metadata_json),
        action=action,
        job_id=record.job_id,
    )


def _active_job_id(metadata: Mapping[str, Any]) -> str | None:
    value = metadata.get("active_job_id")
    if isinstance(value, str) and value.strip():
        return value
    return None


def _assistant_metadata(
    assessment: Mapping[str, Any],
    direct_output: Any = None,
    workflow_run: models.WorkflowRun | None = None,
    *,
    boundary_decision: Mapping[str, Any] | None = None,
    clarification_mapping: Mapping[str, Any] | None = None,
    routing_decision: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    metadata = {
        "goal_intent_profile": workflow_contracts.dump_goal_intent_profile(assessment) or {}
    }
    if isinstance(direct_output, Mapping):
        metadata["tool_output"] = dict(direct_output)
    if isinstance(workflow_run, models.WorkflowRun):
        metadata["workflow_run"] = workflow_run.model_dump(mode="json", exclude_none=True)
    if isinstance(boundary_decision, Mapping):
        metadata["boundary_decision"] = dict(boundary_decision)
    if isinstance(clarification_mapping, Mapping):
        metadata["clarification_mapping"] = dict(clarification_mapping)
    if isinstance(routing_decision, Mapping):
        metadata["routing_decision"] = dict(routing_decision)
    return metadata


def _sanitize_chat_context(value: Mapping[str, Any] | None) -> dict[str, Any]:
    context = dict(value) if isinstance(value, Mapping) else {}
    context.pop("user_id", None)
    context.pop("semantic_user_id", None)
    return context


def _public_session_metadata(value: Any) -> dict[str, Any]:
    metadata = dict(value) if isinstance(value, Mapping) else {}
    metadata.pop(_INTERNAL_CHAT_USER_ID_KEY, None)
    metadata.pop(_CHAT_STATE_VERSION_KEY, None)
    metadata.pop(_CHAT_STATE_CONFLICT_COUNT_KEY, None)
    if isinstance(metadata.get("context_json"), Mapping):
        metadata["context_json"] = _sanitize_chat_context(metadata.get("context_json"))
    return metadata


def _chat_session_user_id(metadata: Mapping[str, Any]) -> str:
    return _normalized_user_id(metadata.get(_INTERNAL_CHAT_USER_ID_KEY))


def _normalized_user_id(value: Any) -> str:
    return str(value or "").strip()


def _chat_session_access_allowed(record: ChatSessionRecord, user_id: str | None) -> bool:
    bound_user_id = _chat_session_user_id(record.metadata_json or {})
    if not bound_user_id:
        return True
    # None means explicitly unauthenticated → open access.
    # An empty string is not a valid identity and denies access to bound sessions
    # so a misconfigured auth layer that passes "" instead of None is caught here.
    if user_id is None:
        return True
    normalized_user_id = _normalized_user_id(user_id)
    return bool(normalized_user_id) and bound_user_id == normalized_user_id


def _workflow_input_question(definition: Mapping[str, Any]) -> str:
    key = str(definition.get("key") or "value").strip() or "value"
    label = str(definition.get("label") or key).strip() or key
    value_type = str(definition.get("value_type") or "string").strip().lower() or "string"
    description = str(definition.get("description") or "").strip()
    message = str(definition.get("message") or "").strip()

    if value_type in {"object", "array"}:
        question = f"I need `{label}` before I can run this workflow. Reply with valid JSON for `{key}`."
    elif value_type == "boolean":
        question = f"I need `{label}` before I can run this workflow. What value should I use for `{key}`? Reply with `true` or `false`."
    elif value_type in {"number", "integer"}:
        question = f"I need `{label}` before I can run this workflow. What numeric value should I use for `{key}`?"
    else:
        question = f"I need `{label}` before I can run this workflow. What value should I use for `{key}`?"

    if description:
        question = f"{question} {description}"
    if message:
        question = f"{question} ({message})"
    question = (
        f"{question} Reply `use default` if you want me to leave it unset and let the workflow "
        "use its own fallback behavior when possible."
    )
    return question


def _workflow_input_omission_requested(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    normalized = re.sub(r"[^a-z0-9]+", " ", value.strip().lower()).strip()
    if not normalized:
        return False
    return normalized in {
        "default",
        "use default",
        "use the default",
        "default is fine",
        "the default is fine",
        "leave blank",
        "leave it blank",
        "leave it empty",
        "skip",
        "skip it",
        "omit it",
        "no preference",
        "whatever works",
        "anything is fine",
        "anything works",
        "i dont care",
        "i do not care",
    }


def _normalized_optional_str(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    return normalized or None
