# Chat → Tool / Agent Integration

Tracking document for the challenge of invoking registered tools and agents directly from the chat interface.

---

## Problem Statement

Chat is working well for conversational responses and document generation. The next challenge is letting users invoke **tools** (MCP tools, capability adapters) and **agents** (multi-step workflows, sub-agents) directly through natural-language chat — without requiring them to know capability IDs, field names, or workflow syntax.

Key questions to answer:
- How does the chat detect that the user wants a tool/agent, not just a chat reply?
- How does the system collect the required inputs for that tool/agent?
- How does the chat stream progress back to the user while the tool/agent runs?
- How does the result surface in the chat thread?

---

## Current State (baseline)

| Layer | What exists |
|---|---|
| Capability registry | `config/capability_registry.yaml` — all tools/agents registered with `id`, `description`, `tags`, `adapters`, `input_schema_ref` |
| Routing gate | `_looks_like_conversational_turn()` — level-1 hardcoded phrases + level-2 intent-verb × artifact-token check against `_chat_thread_hints()` |
| Boundary LLM | Haiku — decides `chat_reply` vs `execution_request` using capability vector search evidence |
| Router LLM | Picks a capability + collects slot values from conversation context |
| Clarification loop | `pending_clarification` state in session metadata — asks for missing required inputs one at a time |
| Execution | `handle_turn` → planner → executor → MCP tool call |
| Streaming | SSE token stream for chat replies; not yet wired for tool progress events |

---

## Existing Orchestration Architecture

`handle_turn` → `_classify_turn` → produces a `TurnPlan` → `_execute_turn` dispatches it.

| Plan type | What it does | Sync/Async | Gap |
|---|---|---|---|
| `AskClarificationPlan` | Asks user for missing fields | Sync | Works well |
| `ToolCallPlan` | Runs one capability directly via `run_direct_capability` | Sync | No streaming progress; one tool only |
| `SubmitJobPlan` | Submits to planner/executor as a background job | Async | Result never surfaces back in chat thread |
| `RunWorkflowPlan` | Triggers a workflow run | Async | Same — result not returned to chat |
| `RespondPlan` | Generates a chat reply | Sync (streamed) | N/A — works |

The planner/executor (`SubmitJobPlan`) handles multi-step tool chains but the result stays in the job/workflow system — it never comes back to the chat SSE stream.

---

## Challenges

### 1. Routing: detecting tool/agent intent from natural language

**Status**: Partially solved.

Level-1 (hardcoded phrases) catches explicit workflow commands.
Level-2 (intent-verb × artifact-token from registry) catches capability-aware natural language.

**Open**: False positives (questions like "how do I create a document?") still route to the boundary LLM unnecessarily, adding ~450–800ms. Question-detection guard not yet added.

**Files**: `services/api/app/main.py` — `_looks_like_conversational_turn()`

---

### 2. Input collection: clarification loop for required fields

**Status**: Exists but needs verification with tool invocations.

The clarification loop (`pending_clarification` state) already asks users for missing fields. The router fills slots from context; anything missing triggers a follow-up question.

**Open**:
- Does the clarification loop handle multi-step agents (agents that need inputs at different stages)?
- Can users provide all inputs in one message ("create a word document about visited places, for travel enthusiasts, in a practical tone")?

**Files**: `services/api/app/chat_service.py` — `clarification_lifecycle_from_metadata()`, `pending_clarification` state

---

### 3. Progress streaming: surfacing tool/agent execution status in chat

**Status**: Not yet implemented.

Currently the SSE stream delivers tokens for chat replies. When a tool/agent runs, the user sees nothing until the result is ready. For long-running tools (30s+ document generation, code generation) this is a poor UX.

**Open**:
- Wire tool execution events (`tool_started`, `tool_progress`, `tool_completed`) into the SSE queue as structured SSE events alongside `token` events.
- UI needs to render progress indicators for these event types.

**Files**:
- `services/api/app/main.py` — `_generate()`, SSE queue, `chunk_queue`
- `services/ui/src/app/WorkspaceSurfaceContent.tsx` — SSE event reader

---

### 4. Result rendering: surfacing tool output back in chat

**Status**: Partial. Tool output is persisted as a session artifact but not rendered inline in the chat thread.

**Open**:
- After tool execution completes, inject a structured result message into the chat history (e.g. "Generated document: [Download Word file]").
- For document capabilities: surface a download link or preview.
- For GitHub capabilities: surface PR link, commit SHA.

---

### 5. Agent chaining: multi-capability workflows from a single chat message

**Status**: Not started.

Some user requests map to a sequence of capabilities (e.g. "create a Word document about X" = `document.spec.generate` → `document.docx.render`). Currently each is triggered separately.

**Open**:
- Can the router plan a multi-step chain from a single message?
- How does the clarification loop handle inputs needed at different chain steps?

---

## Approach / Decision Log

### 2026-06-06 — Routing gate: level-2 capability-aware check added

**Decision**: Extended `_looks_like_conversational_turn()` with a level-2 check: if the message contains an intent verb (`create`, `make`, `generate`, `write`, `export`, `save`, `build`, `run`, etc.) AND a capability artifact token from `_chat_thread_hints()`, route to the boundary LLM.

**Why**: Capabilities self-declare their routing triggers via `chat_thread_hints.artifact_tokens` in YAML — no need to hardcode phrases in `main.py` for each new tool.

**Tradeoff**: False positives (questions with intent verbs + artifact tokens) now pay ~450–800ms boundary LLM overhead. Mitigation (question-detection guard) not yet applied.

**Commit**: (pending push)

---

---

## Model 2 Design: Inline Tool Chain

### Goal
Run a sequence of capabilities synchronously inside a single chat turn, streaming step-by-step progress through the existing SSE queue so the user sees live status without a second round-trip.

### SSE Event Protocol Extension

New event types added alongside `token` and `done`:

```
data: {"type": "tool_intent",    "label": "Creating your Word document", "capability": "document.spec.generate"}
data: {"type": "tool_start",     "capability": "document.spec.generate", "label": "Generating document structure", "step": 1, "total_steps": 2}
data: {"type": "tool_done",      "capability": "document.spec.generate", "label": "Document structure ready",     "step": 1}
data: {"type": "tool_start",     "capability": "document.docx.render",   "label": "Rendering Word file",          "step": 2, "total_steps": 2}
data: {"type": "tool_done",      "capability": "document.docx.render",   "label": "Word file ready",              "step": 2,
                                  "result": {"url": "...", "filename": "...", "mime_type": "application/vnd.openxmlformats..."}}
data: {"type": "done", ...}
```

### Backend Architecture

**Thread-local progress callback** — mirrors `_stream_callback_local`:
```python
_tool_progress_callback_local: threading.local  # set in _run_turn, read in _execute_tool_call
```

**Emission points:**
| Event | Where emitted | Trigger |
|---|---|---|
| `tool_intent` | `_route_chat_turn` (main.py) | Immediately after boundary returns `execution_request` |
| `tool_start` | `_execute_tool_call` (chat_service.py) | Before `run_direct_capability()` |
| `tool_done` | `_execute_tool_call` (chat_service.py) | After `run_direct_capability()` succeeds |

**New plan type** (Model 2, implemented later):
```python
@dataclass(frozen=True)
class ToolChainPlan:
    steps: list[ToolCallPlan]   # ordered capability chain
    resolved_goal: str
    merged_context: dict
    assessment: dict
```
`_execute_turn` iterates steps, emitting `tool_start`/`tool_done` for each via the progress callback.

### UI Architecture

**State added to chat component:**
```typescript
type ToolStep = {
  capability: string;
  label: string;
  status: "running" | "done";
  step: number;
  result?: { url?: string; filename?: string; mime_type?: string };
};
```

**Streaming bubble transitions:**
```
[empty bubble]
  ↓ tool_intent
[spinner + "Creating your Word document…"]
  ↓ tool_start (step 1)
[● Generating document structure  ← spinner]
  ↓ tool_done (step 1)
[✓ Document structure ready]
[● Rendering Word file  ← spinner]
  ↓ tool_done (step 2, result)
[✓ Document structure ready]
[✓ Word file ready]
[📄 report.docx  Download ↓]
  ↓ done (token content fills in as normal chat text above/below)
```

### Files to change

| File | Change |
|---|---|
| `services/api/app/main.py` | `_tool_progress_callback_local`, emit `tool_intent` in `_route_chat_turn`, handle new kinds in `_generate()` |
| `services/api/app/chat_service.py` | `ChatServiceRuntime.progress_callback`, emit `tool_start/done` in `_execute_tool_call` |
| `services/ui/src/app/WorkspaceSurfaceContent.tsx` | New `SSEEvent` types, `toolSteps` state, `ToolProgressBubble` component |

---

## Implementation Status

| Feature | Status |
|---|---|
| Level-2 routing gate (capability-aware) | ✅ Done |
| `tool_intent` / `tool_start` / `tool_done` SSE events | ✅ Done |
| `ToolProgressCard` UI component | ✅ Done |
| `progress_callback` wired through runtime | ✅ Done |
| Capability offer hint for question turns | ✅ Done |
| `ToolChainPlan` + `_execute_tool_chain` | ✅ Done |
| `chains_to` in capability registry YAML | ✅ Done |
| Question-detection guard (false positive reduction) | ✅ Done |
| Result download card in UI | ✅ Done |
| End-to-end test: "create a word document" | Pending |

## Next Steps

1. **End-to-end test** — rebuild containers, test "create a word document about most visited places" through: routing → boundary → router → clarification → `ToolChainPlan` → `document.spec.generate` → `document.docx.render` → progress events in UI.

2. **Result download card** — when `tool_done` includes a `result.path`, render a download button in the `ToolProgressCard`.

3. **Question-detection guard** — if message is a question, skip the level-2 routing gate (stay on fast path) but still inject the capability offer hint via `_capability_offer_hint`.

4. **Extend `chains_to`** to other capabilities as needed.
