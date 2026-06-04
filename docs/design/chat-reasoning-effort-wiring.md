# Chat Reasoning Effort Wiring

## Problem

`reasoning_effort` was added to `LLMRequest` and both `AnthropicProvider` / `BedrockAnthropicProvider` read it, but no call site in the chat runtime actually sets it. Every `LLMRequest` in the chat path uses the default `None`, so extended thinking is never activated. The field is wired to the provider layer but dead from the top.

---

## Where the gap is

The call chain for a conversational turn:

```
_route_chat_turn()
  └─ _generate_chat_boundary_decision()     # classifies the turn, returns confidence
  └─ _route_chat_turn_with_router()         # chooses route, builds turn_plan dict
       └─ _finalize_chat_turn_plan()        # if route=="respond" and no pre-built response:
            └─ _generate_chat_response()    # ← LLMRequest built here, no reasoning_effort
```

`_finalize_chat_turn_plan` has the complete `turn_plan` dict in scope, which already contains
the signals needed to decide effort. `_generate_chat_response` just never receives them.

---

## Available signals in turn_plan

| Signal | Location in turn_plan | Meaning |
|---|---|---|
| `low_confidence` | `goal_intent_profile.low_confidence` | Router was below its calibrated threshold — ambiguous turn |
| `boundary_decision.confidence` | `boundary_decision.confidence` | Float confidence from the boundary model (0–1) |
| `routing_decision.fallback_used` | `routing_decision.fallback_used` | Router had to guess — extra reasoning helps |

The `low_confidence` boolean is the primary signal: it's already threshold-calibrated per intent/risk tier, so it's more reliable than the raw float.

---

## Design

### Rule: when to escalate to `"high"` effort

```
low_confidence == True in goal_intent_profile
  OR boundary_decision.confidence < THRESHOLD (default 0.70)
  OR routing_decision.fallback_used == True
→ reasoning_effort = "high"

otherwise → reasoning_effort = None  (provider default, no thinking)
```

The threshold is configurable via `CHAT_RESPONSE_REASONING_EFFORT_THRESHOLD` (float, 0.0–1.0).

### What does NOT get escalated

- Turns where `response_generated == True` — those already have a pre-built response from the boundary model; `_generate_chat_response` is never called.
- Non-`respond` route types (`ask_clarification`, `submit_job`, `run_workflow`) — `_finalize_chat_turn_plan` returns early before reaching `_generate_chat_response`.

So escalation only fires for conversational `respond` turns where the system was uncertain. This is the correct scope: complex or ambiguous questions get deeper thinking; routine conversation does not.

### `"none"` vs `None`

`None` is used (not `"none"`) to mean "no opinion — let the provider use its default". This preserves provider-level defaults and avoids explicitly disabling thinking on every non-escalated call.

---

## Implementation

### 1. New env var (`main.py`)
```python
CHAT_RESPONSE_REASONING_EFFORT_THRESHOLD = float(
    os.getenv("CHAT_RESPONSE_REASONING_EFFORT_THRESHOLD") or "0.70"
)
```

### 2. New helper (`main.py`)
```python
def _response_reasoning_effort(turn_plan: Mapping[str, Any]) -> str | None:
    profile = turn_plan.get("goal_intent_profile") or {}
    if isinstance(profile, Mapping) and profile.get("low_confidence"):
        return "high"
    boundary = turn_plan.get("boundary_decision") or {}
    if isinstance(boundary, Mapping):
        bd_conf = boundary.get("confidence")
        if isinstance(bd_conf, (int, float)) and bd_conf < CHAT_RESPONSE_REASONING_EFFORT_THRESHOLD:
            return "high"
    routing = turn_plan.get("routing_decision") or {}
    if isinstance(routing, Mapping) and routing.get("fallback_used"):
        return "high"
    return None
```

### 3. `_generate_chat_response` — add `reasoning_effort` param
Pass it straight to `LLMRequest(reasoning_effort=reasoning_effort)`.

### 4. `_finalize_chat_turn_plan` — call helper and thread it through
```python
finalized["assistant_content"] = _generate_chat_response(
    ...,
    reasoning_effort=_response_reasoning_effort(finalized),
)
```

---

## Tunability

| Env var | Default | Effect |
|---|---|---|
| `CHAT_RESPONSE_REASONING_EFFORT_THRESHOLD` | `0.70` | Boundary confidence below this → `"high"` effort |

Set to `0.0` to disable confidence-based escalation (only `low_confidence` and `fallback_used` trigger it).
Set to `1.0` to escalate on all turns that have a boundary decision.

---

## Relationship to earlier work

This is the final link in the chain started in `llm-latency-reasoning-bedrock.md`:

```
LLMRequest.reasoning_effort (contract) ✓
AnthropicProvider / BedrockAnthropicProvider (provider reads it) ✓
_response_reasoning_effort + _finalize_chat_turn_plan (runtime sets it) ← this doc
```
