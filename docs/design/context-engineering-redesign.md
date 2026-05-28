# Context Engineering Redesign

## Background

The current context pipeline was designed when LLM context windows were small (~4K–16K tokens). The item-count budgets, lexical ranking, and seven stage-specific projection functions all exist to protect a scarce resource. With modern context windows at 200K tokens, the constraint shifts from *fitting content* to *minimising per-request cost* and *maximising cache hits*.

---

## Current Architecture

### Key classes and methods

| Symbol | File | Purpose |
|---|---|---|
| `ContextEnvelope` | `libs/core/workflow_contracts.py:300` | Core container — holds raw `context_json` plus derived fields: `user_scope`, `session_scope`, `workflow_scope`, `profile`, `interaction_summaries`, `capability_candidates`, `missing_inputs`, `dropped_inputs`, `trace` |
| `ContextEnvelopeTrace` | `workflow_contracts.py:291` | Diagnostic metadata: `sources_used`, `projection`, `profile_loaded` |
| `NormalizedIntentEnvelope` | `workflow_contracts.py:206` | Parsed intent: goal, graph segments, clarification state, candidate capabilities |
| `collect_context_sources()` | `context_service.py:97` | Assembles named source dicts, filters out Nones |
| `normalize_context_sources()` | `context_service.py:107` | Merges all sources; resolves `user_id` across them |
| `build_context_envelope()` | `context_service.py:133` | **Main builder** — merge → filter noise → rank → load profile → return `ContextEnvelope` |
| `build_chat_context_envelope()` | `context_service.py:213` | Chat wrapper: `session_context + turn_context → build_context_envelope()` |
| `drop_noisy_context_items()` | `context_service.py:414` | Filters `interaction_summaries` by noise tokens and goal relevance |
| `budget_context_for_stage()` | `context_service.py:455` | Trims context to per-stage item count limits |
| `update_chat_context_envelope()` | `context_service.py:482` | Immutable-style merge of new context into existing envelope |
| `_rank_interaction_summaries()` | `context_service.py:636` | Lexical score (goal token overlap × 4 + recency) |
| `_rank_capability_candidates()` | `context_service.py:655` | Score by goal token match against capability ID parts |
| `_merge_context_maps()` | `context_service.py:981` | Shallow merge with deep-merge for workflow keys |

### Pipeline flow

```
POST /chat/sessions/{id}/messages
  request.context_json (from UI)
         │
_prepare_turn_context()        sanitise / map pending workflow inputs
         │
_merge_chat_context()          session_context + turn_context → merged dict
         │
build_chat_context_envelope()  normalise + rank + enrich → ContextEnvelope
         │
chat_submit_context_view()     budget for submit stage (≤6 interaction summaries)
         │
_apply_pending_clarification_mapping()   resolve clarification slots if active
         │
_route_chat_turn()             planner_context_view() / execution_context_view()
         ▼
         Planner / Executor  (LLM call)
```

### Stage view functions (current)

| Function | Stage | Key differences |
|---|---|---|
| `chat_route_context_view` | routing | adds `user_profile`, `capability_candidates`, `missing_inputs` |
| `intent_context_view` | intent | adds `intent_slot_values`, `intent_slot_provenance` |
| `chat_submit_context_view` | pre-route | merges clarification slot ledger |
| `planner_context_view` | planning | removes `user_profile`, keeps candidates + missing |
| `execution_context_view` | execution | removes profile, candidates, missing inputs |
| `workflow_runtime_context_view` | workflow | pass-through budget |
| `preflight_context_view` | preflight | pass-through budget |

### Per-stage item caps (current)

```python
_INTERACTION_SUMMARY_STAGE_LIMITS = {
    "chat_submit": 6, "planner": 4, "intent": 6,
    "chat_route": 3, "execution": 6, ...
}
_CAPABILITY_CANDIDATE_STAGE_LIMITS = {
    "intent": 8, "chat_route": 8, "planner": 10,
}
```

---

## What's Good (Keep)

- **Structured envelope with namespaced scopes** — separating `context_json`, `user_scope`, `session_scope`, `workflow_scope` is correct and should stay.
- **Stage-gated projections** — each pipeline stage seeing only what it needs is the right pattern; the function count can shrink but the concept stays.
- **Noise filtering** — `_CONTEXT_NOISE_TOKENS`, `_interaction_summary_is_noisy` are valuable regardless of window size.
- **Provenance tracking** — `ContextEnvelopeTrace`, `intent_slot_provenance` are essential for debugging; keep and extend.
- **Canonical key resolution + aliases** — `_INTENT_SLOT_ALIASES`, `_context_has_required_input` prevent spurious clarification prompts.
- **Immutable-style updates** — `model_copy(update={...})` pattern is clean and safe.
- **Deep-merge for workflow keys** — `_merge_context_maps` correctly deep-merges `workflow_inputs`, `workflow_ref`, etc.

---

## Existing Caching Infrastructure

### What's built

| Symbol | File | Purpose |
|---|---|---|
| `Stability` enum | `libs/core/llm_provider.py:14` | `STATIC` / `RUN` / `DYNAMIC` — how stable a block is |
| `PromptBlock` | `llm_provider.py:22` | `(text, stability)` unit of prompt content |
| `CacheSessionRef` | `llm_provider.py:28` | Serialisable session handle + `pinned_hash` for drift detection |
| `LLMRequest.prompt_blocks` | `llm_provider.py:57` | Optional structured blocks; overrides flat `prompt` when set |
| `AnthropicProvider.generate_cached()` | `llm_provider_anthropic.py:60` | Applies `cache_control: {"type": "ephemeral"}` to STATIC + RUN blocks |
| `CacheSessionStore` | `cache_session_store.py:23` | Redis-backed store keyed by `job_id`, TTL 1hr |
| `CachingLLMProvider` | `cache_session_store.py:90` | Wrapper: intercepts `generate_request()`, looks up session by `metadata["job_id"]`, routes to `generate_cached()` |
| `_request_to_blocks()` | `cache_session_store.py:157` | Fallback: `system_prompt → STATIC`, `prompt → DYNAMIC` |

### What's wired today

- `CachingLLMProvider` is applied only in the **worker** (`worker/app/main.py:175`).
- `_cache_session_store` is initialised in the **API** but `open_cache_session()` is never called there — only `delete()` at job completion.
- All API-side LLM calls use `LLMRequest(prompt=..., system_prompt=...)` — no `prompt_blocks` ever supplied.
- The fallback `_request_to_blocks()` fires for everything: `system_prompt → STATIC` (one blob), `prompt → DYNAMIC` (one blob). No RUN blocks exist anywhere in the API path.

### Cache gaps

| What | Gap |
|---|---|
| Chat routing, intent, clarification LLM calls | No cache session; no `prompt_blocks`; fall through to coarse fallback |
| `interaction_summaries` in context | Baked into prompt string as DYNAMIC — should be RUN |
| User profile | Baked into prompt string — should be STATIC |
| Capability catalog | Baked into prompt string — should be STATIC |
| API `open_cache_session()` | Never called; sessions only opened by worker |

---

## Proposed Redesign

### 1. Replace item-count limits with token-aware budgeting

Remove `_INTERACTION_SUMMARY_STAGE_LIMITS` and `_CAPABILITY_CANDIDATE_STAGE_LIMITS` dicts. Replace with per-region token budgets:

```python
_TOKEN_BUDGETS: dict[str, int] = {
    "interaction_summaries": 4_000,
    "capability_candidates": 2_000,
    "user_profile":          1_500,
    "context_json":          8_000,
}

def _trim_to_token_budget(items: list[dict], budget: int) -> list[dict]:
    """Keep items in order until token budget is reached."""
    total = 0
    result = []
    for item in items:
        tokens = len(json.dumps(item)) // 4   # ~4 chars/token estimate
        if total + tokens > budget:
            break
        result.append(item)
        total += tokens
    return result
```

### 2. Split ContextEnvelope into stable vs. dynamic regions

Add a stability classification to the envelope builder. Each field has a natural stability level:

| Envelope field | Stability | Reasoning |
|---|---|---|
| System instructions + capability catalog text | `STATIC` | Never changes within a session |
| `profile` (user profile) | `STATIC` | Loaded once per session from memory |
| `capability_candidates` | `RUN` | Recomputed after intent, stable within a turn cycle |
| `interaction_summaries` | `RUN` | Grows per turn, stable after it's been written |
| `context_json` (user inputs) | `DYNAMIC` | Changes every turn |
| `goal`, `missing_inputs`, clarification state | `DYNAMIC` | Changes every turn |

New function in `context_service.py`:

```python
def envelope_to_prompt_blocks(
    envelope: ContextEnvelope,
    *,
    static_system: str,          # system instructions + capability catalog
    dynamic_goal: str,
    dynamic_turn_context: dict,
) -> list[PromptBlock]:
    """Convert a ContextEnvelope to PromptBlocks for generate_cached()."""
    run_parts: list[str] = []
    if envelope.profile:
        run_parts.append(f"<user_profile>{json.dumps(envelope.profile)}</user_profile>")
    if envelope.interaction_summaries:
        run_parts.append(f"<history>{json.dumps(envelope.interaction_summaries)}</history>")
    if envelope.capability_candidates:
        run_parts.append(f"<candidates>{json.dumps(envelope.capability_candidates)}</candidates>")

    blocks = [PromptBlock(text=static_system, stability=Stability.STATIC)]
    if run_parts:
        blocks.append(PromptBlock(text="\n".join(run_parts), stability=Stability.RUN))
    blocks.append(PromptBlock(
        text=f"Goal: {dynamic_goal}\nContext: {json.dumps(dynamic_turn_context)}",
        stability=Stability.DYNAMIC,
    ))
    return blocks
```

### 3. Wire cache sessions into the API path

Open a cache session when a chat session is created, store it alongside the session metadata:

```python
# In create_chat_session() — api/app/main.py
session = ChatSessionRecord(...)
db.add(session)
db.commit()

static_blocks = [PromptBlock(text=build_static_system_prompt(), stability=Stability.STATIC)]
session_ref = llm_provider.open_cache_session(session.id, static_blocks)
_cache_session_store.save(session.id, session_ref)
```

Every subsequent LLM call in the chat path passes `metadata={"job_id": session.id}` on the `LLMRequest` so `CachingLLMProvider` can find the session and route to `generate_cached()`.

### 4. Replace flat `generate_request()` calls with `generate_cached()` + blocks

Current pattern (all API LLM calls):
```python
llm.generate_request_json_object(LLMRequest(
    prompt=some_big_string,
    system_prompt=system_string,
))
```

New pattern:
```python
blocks = envelope_to_prompt_blocks(
    envelope,
    static_system=system_string,
    dynamic_goal=candidate_goal,
    dynamic_turn_context=chat_submit_context_view(envelope),
)
llm.generate_cached(blocks, session_ref, LLMRequest(
    prompt="",    # unused when blocks are supplied
    metadata={"job_id": session_id},
))
```

### 5. Collapse 7 stage view functions → 3

With typed blocks, stage differentiation is about *which sections to include*, not *how many items to trim*. Reduce to:

```python
def chat_context_view(envelope: ContextEnvelope) -> dict:
    """For routing and intent — includes profile, candidates, clarification."""

def planner_context_view(envelope: ContextEnvelope) -> dict:
    """For plan generation — excludes profile, includes full inputs + missing."""

def execution_context_view(envelope: ContextEnvelope) -> dict:
    """For task execution — lean: just inputs and workflow scope."""
```

`chat_route_context_view`, `intent_context_view`, `chat_submit_context_view`, `preflight_context_view` are collapsed into `chat_context_view` with minor parameter flags if needed.

### 6. Add reserved-key guard at context ingestion

User-supplied `context_json` can shadow internal system fields today. Fix at ingestion:

```python
_SYSTEM_RESERVED_KEYS = frozenset({
    "capability_candidates", "missing_inputs", "user_profile",
    "interaction_summaries", "clarification_resolved_slots",
    "intent_slot_values", "workflow_scope",
})

def sanitize_user_context(context: dict[str, Any]) -> dict[str, Any]:
    shadowed = _SYSTEM_RESERVED_KEYS & context.keys()
    if shadowed:
        logger.warning("user_context_shadowed_system_keys: %s", shadowed)
    return {k: v for k, v in context.items() if k not in _SYSTEM_RESERVED_KEYS}
```

### 7. Surface `dropped_inputs` to the API response

The envelope already tracks what was dropped (`ContextEnvelopeTrace`, `dropped_inputs`) but callers never see it. Add to relevant API responses so callers can detect silent trimming.

---

## Known Weaknesses to Address Later

- **Lexical-only ranking** — `_rank_interaction_summaries` uses token overlap; does not find semantically related summaries with different vocabulary. Future: embed summaries and rank by cosine similarity against goal embedding.
- **`user_id` + `semantic_user_id` duplication** — `normalize_context_sources()` writes both keys with the same value (lines 126–127). Consolidate to one.
- **Capability scoring is hardcoded** — `_rank_capability_candidates` has hardcoded heuristics for `path`/render and `query`/search. Should derive from capability schema metadata.

---

## Implementation Priority

| Phase | Change | Files | Risk |
|---|---|---|---|
| 1 | Token-aware budgeting in `drop_noisy_context_items` and stage views | `context_service.py` | Low — behaviour improvement, no pipeline change |
| 2 | `sanitize_user_context()` reserved-key guard | `context_service.py`, call sites in `main.py` | Low |
| 3 | `envelope_to_prompt_blocks()` in `context_service.py` | `context_service.py` | Low — pure function, no callers yet |
| 4 | Open cache session at chat session creation; wire `metadata["job_id"]` to API LLM calls | `main.py` | Medium — touches session creation path |
| 5 | Collapse 7 view functions → 3 | `context_service.py`, all callers in `main.py`, `chat_service.py` | Medium — broad refactor, requires search for all call sites |
| 6 | Replace flat `generate_request()` → `generate_cached()` + blocks for chat, intent, clarification paths | `main.py`, `chat_service.py` | High — changes what the model sees; requires eval runs |
| 7 | Typed XML prompt sections | `main.py`, `chat_service.py`, prompt strings | High — requires prompt re-tuning and regression testing |
