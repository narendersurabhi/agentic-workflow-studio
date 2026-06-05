# Chat & Agent Runtime Redesign

## Context

This document captures architectural issues observed across `chat_service.py`,
`chat_execution_service.py`, and the workflow runtime, and proposes a redesign
direction. It is a design proposal, not an implementation plan.

---

## Current Architecture Snapshot

### Chat

`handle_turn` is a 600-line god function that:
- classifies the user turn (via LLM router)
- mutates session state (clarification, job tracking)
- creates database records (Job, WorkflowRun, ChatMessage)
- generates a response

All of this happens in a single pass with a string-dispatched `if/elif` on
`route_type`. The clarification state is a complex Pydantic blob stored in
`session.metadata_json`, with lifecycle recomputation (`_clarification_lifecycle`)
happening on every access.

`chat_execution_service.py` handles synchronous capability execution (read-only
tools, memory, RAG) with a per-capability `if/elif` formatter in
`_format_chat_direct_result`. New capabilities require edits here or they fall
through to a raw JSON dump.

### Agent / Workflow

Workflows are pre-compiled at publish time into standard Job + Plan records.
At runtime, the workflow rides the same planner/worker/orchestrator pipeline
as any LLM-planned job. `WorkflowRun` is a tracking record, not an active
runtime. There is no mechanism for pause, resume, mid-run human input, or
adaptive re-planning on step failure.

---

## Proposed Changes

### 1. Break `handle_turn` into a typed pipeline

**Problem:** A single function classifying, acting, and responding makes each
concern hard to test, extend, or reason about. The `dict[str, Any]` turn plan
returned by the router loses type information immediately.

**Proposal:** Replace the string dispatch with a discriminated union of typed
plan objects and a corresponding executor per plan type.

```python
# Typed plans — one per route type
@dataclass(frozen=True)
class SubmitJobPlan:
    resolved_goal: str
    merged_context: dict[str, Any]
    assessment: dict[str, Any]

@dataclass(frozen=True)
class AskClarificationPlan:
    questions: list[str]
    pending_fields: list[str]
    resolved_goal: str

@dataclass(frozen=True)
class RespondPlan:
    assistant_content: str

@dataclass(frozen=True)
class RunWorkflowPlan: ...
@dataclass(frozen=True)
class ToolCallPlan: ...

TurnPlan = SubmitJobPlan | AskClarificationPlan | RespondPlan | RunWorkflowPlan | ToolCallPlan
```

Each plan type maps to a focused executor:

```python
class SubmitJobExecutor:
    def execute(self, plan: SubmitJobPlan, ctx: TurnContext) -> TurnResult: ...

class AskClarificationExecutor:
    def execute(self, plan: AskClarificationPlan, ctx: TurnContext) -> TurnResult: ...
```

`handle_turn` becomes ~30 lines:

```python
def handle_turn(db, session_id, request, *, runtime, user_id):
    ctx = _build_turn_context(db, session_id, request, runtime, user_id)
    plan: TurnPlan = runtime.route_turn(ctx)
    executor = _executor_for(plan)
    result: TurnResult = executor.execute(plan, ctx)
    _persist_turn(db, ctx, result)
    return _build_response(ctx, result)
```

**Benefit:** each executor is independently testable; adding a new route type
does not touch existing executors.

---

### 2. Replace the clarification state blob with an explicit state machine

**Problem:** `ClarificationState` stored as a JSON blob in `metadata_json`,
with lifecycle recomputed from scratch via `_clarification_lifecycle` on every
access. The lifecycle computation has subtle bugs (the `required_fields` filter
omission fixed in the review). The field-resolution logic spans
`_unresolved_clarification_fields`, `_ordered_clarification_fields`,
`_known_clarification_slot_values`, `_canonical_pending_state_payload`, and
`_merge_clarification_state_for_persistence`.

**Proposal:** A minimal state machine with three states and explicit transitions.

```python
class ClarificationPhase(str, Enum):
    idle       = "idle"
    collecting = "collecting"
    ready      = "ready"

@dataclass
class ClarificationSession:
    phase:     ClarificationPhase
    frame:     ExecutionFrame        # what we are collecting for
    collected: dict[str, Any]        # field → value, append-only
    queue:     list[SlotQuestion]    # ordered, shrinks as slots are filled
    goal:      str                   # original goal, immutable after set
```

Transitions are pure functions:

```python
def begin(goal: str, required_slots: list[SlotQuestion]) -> ClarificationSession:
    return ClarificationSession(
        phase=ClarificationPhase.collecting,
        frame=..., collected={}, queue=required_slots, goal=goal,
    )

def answer(session: ClarificationSession, field: str, value: Any) -> ClarificationSession:
    updated_collected = {**session.collected, field: value}
    updated_queue = [q for q in session.queue if q.field != field]
    phase = ClarificationPhase.ready if not updated_queue else ClarificationPhase.collecting
    return dataclasses.replace(session, collected=updated_collected, queue=updated_queue, phase=phase)

def is_complete(session: ClarificationSession) -> bool:
    return session.phase == ClarificationPhase.ready
```

`is_complete` is `len(session.queue) == 0` — no lifecycle recomputation, no
`known_slot_values` merge, no `required_fields` vs `pending_fields` asymmetry.

---

### 3. Separate session control state from message content

**Problem:** Routing state (`pending_clarification`, `active_job_id`,
`normalized_intent_envelope`, `_chat_session_id`) lives in `metadata_json`
alongside user-facing context. The optimistic-lock retry loop in
`_persist_chat_session_state` applies to the entire blob, causing conflicts when
concurrent turns race.

**Proposal:** Split into a dedicated `session_state` table.

```sql
session_state (
    session_id        TEXT PRIMARY KEY REFERENCES chat_sessions(id),
    phase             TEXT NOT NULL DEFAULT 'idle',
    active_job_id     TEXT,
    active_workflow_run_id TEXT,
    clarification     JSONB,          -- ClarificationSession struct
    intent_envelope   JSONB,
    updated_at        TIMESTAMP NOT NULL
)
```

The optimistic lock applies only to `session_state`, not to `metadata_json`.
`metadata_json` becomes append-friendly user-facing context with no
serialization conflicts.

**Benefit:** narrower lock scope, fewer conflicts; cleaner separation of
internal routing state from public session metadata.

---

### 4. Remove keyword heuristics from the chat layer

**Problem:** `_chat_thread_hints()` assembles token sets from every enabled
capability in the registry on each call (now cached, but still O(N·fields) on
cache miss). `_looks_like_pending_clarification_intent_change` and
`_looks_like_local_clarification_field_answer` duplicate logic from
`libs/core/chat_clarification_eval.py` and have diverged.

These heuristics exist because the LLM router's output did not carry enough
signal to answer: "is this conversation execution-oriented?" and "is this
message a slot answer?" With typed turn plans, both questions are answered
structurally by the router output itself.

**Proposal:**

- Drop the capability registry token loop from `_chat_thread_hints()`. Keep
  only the static bootstrap token sets (`_BOOTSTRAP_EXECUTION_ACTION_TOKENS`,
  `_BOOTSTRAP_EXECUTION_ARTIFACT_TOKENS`) as a lightweight fallback when the
  LLM is unavailable.
- Move `_looks_like_local_clarification_field_answer` and
  `_looks_like_pending_clarification_intent_change` entirely into
  `libs/core/chat_clarification_eval.py` as the single source of truth.
  Both files currently maintain diverged copies.
- Have the router return an explicit `answered_slot` field in
  `AskClarificationPlan` so slot detection does not require keyword matching
  in the service layer.

---

### 5. Separate ChatRuntime from AgentRuntime

**Problem:** `ChatServiceRuntime` bundles turn-scoped callables (`route_turn`,
`make_id`, `utcnow`) with job-scoped callables (`create_job`, `run_workflow`,
`inspect_workflow`). These belong to different concerns: chat owns a single
synchronous turn; the agent runtime owns a durable, async job lifecycle.

**Proposal:** Two runtime interfaces with an explicit event bridge.

```python
@dataclass(frozen=True)
class ChatRuntime:
    route_turn:   Callable[..., TurnPlan]
    respond:      Callable[..., str]          # LLM response generation
    utcnow:       Callable[[], datetime]
    make_id:      Callable[[], str]

@dataclass(frozen=True)
class AgentRuntime:
    submit_job:   Callable[..., Job]
    run_workflow: Callable[..., WorkflowRun]
    inspect_workflow: Callable[..., WorkflowInspection]
```

Chat creates a job and subscribes the session to its event stream. The agent
emits typed events (`job.completed`, `job.needs_input`, `job.failed`) that the
chat layer surfaces on the next turn. This removes the direct call from chat
into the job pipeline and makes the integration explicit.

**Tradeoff:** agents can no longer ask mid-run clarification questions via a
direct function call. They must emit a `needs_input` event and wait for the
next chat turn to pick it up. This is correct behavior (it forces a structured
handoff) but requires the event contract to be defined.

---

### 6. Capability-owned response formatting

**Problem:** `chat_execution_service._format_chat_direct_result` is a
per-capability `if/elif` chain. Adding a new capability to
`DEFAULT_CHAT_DIRECT_CAPABILITIES` requires a matching formatter here or it
falls through to raw JSON. The capability definition and its chat presentation
are in different files with no enforcement of the connection.

**Proposal:** Move response formatting into the capability spec.

```yaml
# capability_registry.yaml
- id: github.repo.list
  chat_response_template:
    mode: list
    items_field: items
    label_fields: [full_name, name]
    max_items: 10
    prefix: "Repositories:"
```

`ChatDirectExecutor` reads `spec.chat_response_template` and applies a generic
renderer. Capabilities with complex formatting provide a `format_response`
Python hook registered at startup. `_format_chat_direct_result` is deleted.

---

### 7. Workflow runtime: mid-run adaptivity

**Problem:** Workflows are compiled to a static task graph at publish time.
There is no mechanism for:
- Branching based on a step's runtime output (beyond pre-encoded `execution_gate` expressions)
- Pausing for human approval
- Injecting inputs mid-run
- Adaptive re-planning on step failure (unlike LLM-planned jobs which can re-plan)

**Proposal:** Three targeted additions, in order of priority.

**a) `needs_input` step type** — a workflow step that emits a `job.needs_input`
event and suspends until the chat layer provides a value. This enables
human-in-the-loop approval without changing the compilation model.

**b) Typed workflow inputs with pre-run validation** — enforce that all required
inputs are present before job creation, not discovered turn-by-turn via
`inspect_workflow`. Fail fast with a structured list of missing inputs rather
than discovering them one question at a time.

**c) Step-level retry policy** — today a step failure fails the job. Each step
should declare `max_retries` and `on_failure: skip | fail | retry`. This is
available in `StepSpec` but not fully wired through the executor.

---

## What Does Not Change

- The planner/worker/orchestrator pipeline for job execution. Workflows
  continue to compile to Jobs and ride the same pipeline.
- The `WorkflowRun` tracking model — it provides the right linking between
  workflow artifacts and execution.
- The Redis-based event stream. The chat/agent event bridge described above
  uses the same stream infrastructure.
- `libs/core/llm_provider*` — the provider abstraction is clean.

---

## Priority Order

| # | Change | Complexity | Value |
|---|---|---|---|
| 1 | Typed turn plans + per-type executors | Medium | High — testability, extensibility |
| 2 | Clarification state machine | Medium | High — eliminates class of lifecycle bugs |
| 3 | Capability-owned response formatting | Low | Medium — removes maintenance trap |
| 4 | Session state / message content split | High | Medium — reduces lock contention |
| 5 | ChatRuntime / AgentRuntime split | Medium | Medium — cleaner contracts |
| 6 | Remove keyword heuristics | Low | Low — cleanup, already cached |
| 7 | Workflow mid-run adaptivity | High | High — enables new use cases |

Items 1–3 are independent and can be done in any order. Items 4–5 depend on 1.
Item 7 is independent of all others.
