# LLM Latency, Reasoning Balance & Bedrock Integration

## Problem

Chat latency and reasoning depth are traded once — at config time — by picking a model env var. There is no per-turn dial. Prompt caching infrastructure exists but is not verified to hit. Streaming is absent, so time-to-first-token is the full generation time. AWS Bedrock is not yet a supported provider.

---

## Current Architecture (as of 2026-06-03)

### Per-role model split

`services/api/app/main.py` builds five independent `LLMProvider` instances from env vars:

| Role | Env var | Notes |
|---|---|---|
| Turn router | `CHAT_ROUTER_MODEL` | cheap classification |
| Response generation | `CHAT_RESPONSE_MODEL` | user-facing |
| Pending correction | `CHAT_PENDING_CORRECTION_MODEL` | has `"heuristic"` bypass mode |
| Intent decompose | `INTENT_DECOMPOSE_MODEL` | |
| Composer recommender | `COMPOSER_RECOMMENDER_MODEL` | |

All roles fall back to `LLM_MODEL_NAME` if their specific var is unset.

### Provider abstraction

`libs/core/llm_provider.py`:
- `LLMProvider` base — `generate_request()`, `generate_cached()`, `open/close_cache_session()`
- `LLMRequest` — `prompt`, `system_prompt`, `temperature`, `max_output_tokens`, `metadata`, `prompt_blocks`
- `Stability` enum — `STATIC` / `RUN` / `DYNAMIC` — controls cache marker placement
- `LLMResponse` — includes `cached_input_tokens` and `cache_creation_tokens`

### Prompt caching

`libs/core/cache_session_store.py` — `CachingLLMProvider` wrapper routes every call through `generate_cached()`. `AnthropicProvider` applies `cache_control: {"type": "ephemeral"}` to `STATIC` and `RUN` blocks. `CacheSessionRef.pinned_hash` detects block drift.

---

## Design: Four Changes

### 1. Per-turn reasoning budget (`reasoning_effort`)

**What:** Add `reasoning_effort: Optional[str]` to `LLMRequest`.  
**Values:** `"none"` | `"low"` | `"high"` (provider maps to native budget tokens).  
**Why:** Reasoning depth should be a turn-level decision, not a model-level constant.  
**Mapping:**

| effort | Anthropic `budget_tokens` | OpenAI `reasoning.effort` |
|---|---|---|
| `"none"` | thinking disabled | `"low"` |
| `"low"` | 1 024 | `"medium"` |
| `"high"` | 10 000 | `"high"` |

`AnthropicProvider.generate_cached()` wraps the user content block in a `thinking` param when `reasoning_effort` is non-None and non-`"none"`. The `temperature` param must be omitted when thinking is enabled (Anthropic requirement).

### 2. Router-driven budget escalation

**What:** The router emits a complexity signal alongside the route. The service layer maps signal → `reasoning_effort` on the downstream `LLMRequest`.  
**Why:** The router call is already paid on every turn; make it gate reasoning cost.  
**Cheap turns** (acknowledgements, slot-fills, chat-only corrections) → `reasoning_effort="none"` or heuristic bypass (already proven by `CHAT_PENDING_CORRECTION_MODE`).

### 3. Streaming (future work — not in this phase)

`InvokeModelWithResponseStream` on Bedrock; `client.messages.stream()` on Anthropic SDK. Requires SSE propagation to the chat endpoint. Deferred — tracked separately.

### 4. Prompt cache hit verification

Log `cached_input_tokens / input_tokens` per role per turn. A ratio near 0 on the router (large STATIC catalog) signals block ordering drift or content churn. Fix: ensure STATIC blocks are emitted before RUN/DYNAMIC in every `generate_cached` call.

---

## Bedrock Provider

### Key differences from AnthropicProvider

| Concern | AnthropicProvider | BedrockAnthropicProvider |
|---|---|---|
| Auth | `ANTHROPIC_API_KEY` | IAM role / `AWS_PROFILE` |
| Client | `anthropic.Anthropic` SDK | `boto3.client("bedrock-runtime")` |
| Wire format | Anthropic Messages API | Same schema, wrapped in Bedrock body |
| Prompt caching | `cache_control` markers respected | **Ignored** — Bedrock strips them |
| `cached_input_tokens` | populated | always 0 |
| Extended thinking | `thinking` param | same param, same schema |
| Streaming | `client.messages.stream()` | `invoke_model_with_response_stream` |

### Env vars

```
LLM_PROVIDER=bedrock-anthropic
BEDROCK_MODEL_ID=anthropic.claude-3-5-haiku-20241022-v1:0
AWS_REGION=us-east-1
BEDROCK_MAX_OUTPUT_TOKENS=8192
```

Per-role override follows the same pattern: `CHAT_ROUTER_MODEL`, `CHAT_RESPONSE_MODEL`, etc. continue to work as model IDs passed to the Bedrock provider.

### Recommended role split when mixing providers

Keep Anthropic direct (`LLM_PROVIDER=anthropic`) for cache-heavy paths (response model, planner). Use Bedrock for roles where AWS IAM/billing integration matters and cache hits are rare (e.g. intent decompose).

---

## Implementation Plan

1. **`LLMRequest.reasoning_effort`** — add field to `libs/core/llm_provider.py`
2. **`AnthropicProvider`** — map `reasoning_effort` → `thinking` param in `generate_cached()`; omit `temperature` when thinking enabled
3. **`BedrockAnthropicProvider`** — new file `libs/core/llm_provider_bedrock.py`; boto3 `invoke_model`; no cache markers; same `LLMProvider` interface
4. **`resolve_provider`** — add `"bedrock-anthropic"` case in `libs/core/llm_provider.py`
5. **`main.py` env vars** — read `BEDROCK_MODEL_ID`, `AWS_REGION`, `BEDROCK_MAX_OUTPUT_TOKENS`

Streaming is deferred to a follow-up.
