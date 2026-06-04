# Model Usage Logging

## Problem

There is no way to answer "which model was used for which task, chat turn, step, or workflow run." `TimingLLMProvider` logs latency and token counts per LLM call, but omits:

1. **The model name** — you cannot tell from the log whether a call used `claude-3-5-haiku`, `gpt-4o-mini`, or a Bedrock model.
2. **Context IDs** — no `job_id`, `session_id`, `task_id`, or `step_id` on the log line, so you cannot correlate a call to the workflow or conversation that triggered it.

Without these, you cannot answer: "did the router really use the cheap model?", "which model handled task X that failed?", or "what is the per-model cost breakdown for this workflow run?"

---

## Current Architecture (as of 2026-06-04)

### Provider stack

Every LLM call flows through this wrapper chain:

```
TimingLLMProvider          ← logs latency/tokens (llm_provider_timing.py)
  └─ CachingLLMProvider    ← session-level cache (cache_session_store.py)
       └─ <raw provider>   ← Anthropic / OpenAI / Bedrock / Gemini / Mock
```

`TimingLLMProvider` is constructed once per component role in `services/api/app/main.py`. The component string (e.g. `chat_response`, `intent_assess`) is set at construction time but the model name is not.

### What is already logged (`llm_provider_timing.py:71`)

```
component, latency_ms, reasoning_effort,
input_tokens, cached_input_tokens, output_tokens,
cache_hit, cache_hit_ratio
```

### What is missing

| Field | Where it lives | Problem |
|---|---|---|
| `model` | Known at provider construction in `main.py` | Not passed to `TimingLLMProvider` |
| `provider` | Provider class name | Not surfaced in log |
| `job_id` | `LLMRequest.metadata` (exists, unused) | Never populated at call sites |
| `session_id` | Chat call sites | Never populated |
| `task_id` | Worker `execution_service.py` | Never populated |
| `step_id` | Worker `execution_service.py` | Never populated |

### Component-to-model mapping (today)

`main.py` builds these providers independently, each from its own env var:

| Component | Env var | Role |
|---|---|---|
| `chat_router` | `CHAT_ROUTER_MODEL` | cheap turn classification |
| `chat_response` | `CHAT_RESPONSE_MODEL` | user-facing response |
| `chat_pending_correction` | `CHAT_PENDING_CORRECTION_MODEL` | pending-job corrections |
| `intent_assess` | `INTENT_ASSESS_MODEL` | goal assessment |
| `intent_decompose` | `INTENT_DECOMPOSE_MODEL` | goal decomposition |
| `composer_recommender` | `COMPOSER_RECOMMENDER_MODEL` | capability suggestions |

All fall back to `LLM_MODEL_NAME` if their specific var is unset.

---

## Design: Two Changes

### Change 1 — Add `model` and `provider` to `TimingLLMProvider`

**File:** `libs/core/llm_provider_timing.py`

Extend the constructor to accept a `model` string. Each provider already knows its model at construction time; pass it through when wiring the stack in `main.py`.

```python
class TimingLLMProvider(LLMProvider):
    def __init__(self, inner: LLMProvider, component: str, model: str = "unknown") -> None:
        self._inner = inner
        self._component = component
        self._model = model
```

Add `model` to the `_log` extra dict:

```python
logger.info(
    "llm_call_latency",
    extra={
        "component": self._component,
        "model": self._model,
        # ... existing fields unchanged
    },
)
```

**File:** `services/api/app/main.py`

Pass the resolved model name when constructing each `TimingLLMProvider`. The model name is already in the env var read at that point:

```python
# example — repeat for each component
_chat_response_model = os.getenv("CHAT_RESPONSE_MODEL") or os.getenv("LLM_MODEL_NAME", "unknown")
_chat_response_provider = TimingLLMProvider(
    CachingLLMProvider(resolve_provider(..., model=_chat_response_model), ...),
    component="chat_response",
    model=_chat_response_model,
)
```

No changes to `LLMProvider` base class or any raw provider — `model` stays a presentation-layer concern of the timing wrapper.

---

### Change 2 — Populate `LLMRequest.metadata` with context IDs

`LLMRequest.metadata` (`llm_provider.py:55`) is a `Dict[str, Any]` that already travels through the entire call stack. Populate it at call sites and extract it in `TimingLLMProvider._log`.

#### Call sites

| File | Context available | Fields to add |
|---|---|---|
| `services/api/app/chat_service.py` | `session_id`, `job_id` | both |
| `services/api/app/main.py` (intent paths) | `job_id` | `job_id` |
| `services/worker/app/execution_service.py` | `job_id`, `task_id`, `step_id` | all three |
| `services/planner/app/planner_service.py` | `job_id` | `job_id` |

Pattern at each call site:

```python
request = LLMRequest(
    prompt=...,
    metadata={
        "job_id": job_id,
        "session_id": session_id,   # chat paths only
        "task_id": task_id,         # worker paths only
        "step_id": step_id,         # worker paths only
    },
)
```

If a context ID is not meaningful for a given call site, omit the key rather than passing `None`.

#### `TimingLLMProvider._log` extraction

```python
def _log(self, request: LLMRequest, response: LLMResponse, elapsed_s: float) -> None:
    meta = request.metadata or {}
    cache_hit = response.cached_input_tokens > 0
    extra = {
        "component": self._component,
        "model": self._model,
        "latency_ms": round(elapsed_s * 1000, 3),
        "reasoning_effort": request.reasoning_effort,
        "input_tokens": response.input_tokens,
        "cached_input_tokens": response.cached_input_tokens,
        "output_tokens": response.output_tokens,
        "cache_hit": cache_hit,
        "cache_hit_ratio": round(
            response.cached_input_tokens / response.input_tokens, 3
        ) if response.input_tokens else 0.0,
    }
    for key in ("job_id", "session_id", "task_id", "step_id"):
        if key in meta:
            extra[key] = meta[key]
    logger.info("llm_call_latency", extra=extra)
```

Only keys present in metadata are forwarded; the log line stays clean for call sites that have fewer IDs.

---

## Log output after both changes

### Chat turn
```json
{
  "event": "llm_call_latency",
  "component": "chat_response",
  "model": "claude-3-5-sonnet-20241022",
  "session_id": "sess_abc123",
  "job_id": "job_xyz789",
  "latency_ms": 1243.7,
  "input_tokens": 4200,
  "cached_input_tokens": 3100,
  "output_tokens": 312,
  "cache_hit": true,
  "cache_hit_ratio": 0.738
}
```

### Task execution (worker)
```json
{
  "event": "llm_call_latency",
  "component": "intent_assess",
  "model": "claude-3-5-haiku-20241022",
  "job_id": "job_xyz789",
  "task_id": "task_001",
  "step_id": "step_3",
  "latency_ms": 340.1,
  "input_tokens": 1800,
  "cached_input_tokens": 0,
  "output_tokens": 95,
  "cache_hit": false,
  "cache_hit_ratio": 0.0
}
```

---

## What you can answer after this

| Question | How |
|---|---|
| Which model handled a failed task? | Filter `llm_call_latency` by `task_id` |
| Did the router use the cheap model? | Filter by `component=chat_router`, check `model` |
| Per-model token cost for a workflow run? | Group by `job_id` + `model`, sum tokens |
| Which calls are cache-missing on Anthropic? | Filter `cache_hit=false` by `model` prefix |
| Full call trace for a session? | Filter by `session_id` |

---

## Out of scope

- **Streaming** — no change to streaming path; this only adds fields to the existing log line.
- **LLMResponse.model** — the raw provider response sometimes includes the model ID echoed back. Propagating that would be a separate, more invasive change and is not needed here since the model is already known at construction time.
- **Prometheus metrics** — `model` could be added as a Prometheus label but it increases cardinality; defer until there is a concrete dashboarding need.
- **Tracing** — `job_id`/`task_id` could also be added as OTEL span attributes in `tracing.py`. Defer; the log line is sufficient for initial observability.

---

## Files changed

| File | Change |
|---|---|
| `libs/core/llm_provider_timing.py` | Add `model` param to `__init__`, add `model` + context ID extraction to `_log` |
| `services/api/app/main.py` | Pass `model=` to every `TimingLLMProvider(...)` call |
| `services/api/app/chat_service.py` | Add `metadata` with `session_id` + `job_id` to `LLMRequest` |
| `services/api/app/main.py` (intent paths) | Add `metadata` with `job_id` to `LLMRequest` |
| `services/worker/app/execution_service.py` | Add `metadata` with `job_id`, `task_id`, `step_id` to `LLMRequest` |
| `services/planner/app/planner_service.py` | Add `metadata` with `job_id` to `LLMRequest` |
