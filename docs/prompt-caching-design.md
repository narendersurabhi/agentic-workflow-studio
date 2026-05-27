# Prompt Caching Design

## Overview

This document describes the design for implementing prompt caching across the LLM calls in
this platform. The core technique is **front-loading** — placing large, stable content at
the beginning of every prompt so it falls inside the cacheable prefix window, and keeping
volatile content (goal, job payload, intent graph) at the end where it varies per call.

---

## Background: How Provider Caching Works

### Anthropic (cache_control blocks)

Anthropic's API caches prompt prefixes explicitly. You mark the end of a static block with
`cache_control: {"type": "ephemeral"}`. Everything up to and including that block is cached
for 5 minutes (up to 1 hour with extended caching). Cache hits are billed at ~10% of the
normal input token cost.

Requirement: must use the Anthropic SDK or send raw requests to `api.anthropic.com` with
the `anthropic-beta: prompt-caching-2024-07-31` header.

### OpenAI (automatic prefix caching)

OpenAI caches the longest matching prefix automatically for prompts ≥ 1024 tokens. No
explicit markers needed. Cache hits appear in `usage.prompt_tokens_details.cached_tokens`.
Cache TTL is a few minutes; prompts must share an identical prefix byte-for-byte to hit.

### Gemini (context caching)

Gemini supports explicit context caching via the `cachedContent` API. Content ≥ 32 768
tokens can be cached for a configurable TTL (minimum 1 minute). The cached content is
referenced by name in subsequent requests.

---

## Current Prompt Structure (Problem)

The planner prompt today is assembled in this order in `planner_service.py`:

```
[system_prompt field]
  1. Static rules + JSON schema instructions   (~9 KB, static)

[user prompt field — single string]
  2. Goal text                                  (dynamic, small)
  3. Job payload JSON                           (dynamic, medium)
  4. Normalized intent envelope                 (dynamic, medium)
  5. Intent graph                               (dynamic, medium)
  6. Revision context                           (dynamic, on replan)
  7. Semantic capability hints                  (dynamic, per-goal)
  8. Capability catalog JSON                    (~10–50 KB, semi-static)
  9. Planner tool catalog                       (~1–5 KB, semi-static)
```

**Problems:**
- The capability catalog (largest block, 10–50 KB) sits at the end of the user prompt,
  after all the dynamic content. It changes on every call because the surrounding text
  changes, so caching never hits.
- OpenAI's automatic prefix caching requires a byte-for-byte identical prefix. Placing
  dynamic goal/payload before the catalog breaks the cache on every new job.
- There are no `cache_control` markers for Anthropic.
- The repair prompt (used on JSON parse failure) duplicates the full original prompt,
  doubling token cost on every repair attempt.

---

## Target Prompt Structure (Front-Loaded)

Move stable content to the front. The canonical order should be:

```
[system message]
  1. Role declaration + output format contract   (static, ~500 chars)

[user message — block 1, cache boundary here]
  2. Static planning rules (11 rules, schema)    (~8.5 KB, static)
  3. Planner tool catalog                        (~1–5 KB, static per service start)
  4. Capability catalog JSON                     (~10–50 KB, static per registry version)
  ── CACHE BOUNDARY (Anthropic cache_control / OpenAI prefix end) ──

[user message — block 2, per-call dynamic content]
  5. Normalized intent envelope                  (dynamic)
  6. Intent graph                                (dynamic)
  7. Semantic capability hints                   (dynamic)
  8. Revision context                            (dynamic, on replan)
  9. Goal text                                   (dynamic)
  10. Job payload JSON                           (dynamic)
```

For the chat service, the same principle applies:

```
[system message — cache boundary]
  1. Role + routing rules                        (static)
  2. Response schema                             (static)
  ── CACHE BOUNDARY ──

[user message]
  3. Route request JSON                          (dynamic)
  4. Direct capability candidates                (dynamic)
  5. Recent message history                      (dynamic)
```

---

## Implementation

### Phase 1 — Add Anthropic as a native provider

The current `llm_provider.py` uses a custom `urllib`-based HTTP wrapper targeting the
OpenAI-compatible `/chat/completions` endpoint. Anthropic's prompt caching requires either:
- The `anthropic` Python SDK, or
- Raw HTTP to `api.anthropic.com/v1/messages` with the beta header and structured
  `content` blocks (list of typed content objects, not a plain string).

**New file:** `libs/core/llm_provider_anthropic.py`

```python
import anthropic

class AnthropicProvider(LLMProvider):
    def __init__(self, model: str, api_key: str, **kwargs):
        self.client = anthropic.Anthropic(api_key=api_key)
        self.model = model
        self.max_output_tokens = kwargs.get("max_output_tokens", 8192)

    def generate(self, request: LLMRequest) -> str:
        messages = _build_messages(request)
        response = self.client.messages.create(
            model=self.model,
            max_tokens=self.max_output_tokens,
            system=_build_system_blocks(request),
            messages=messages,
        )
        return response.content[0].text
```

**`LLMRequest` extension** (`libs/core/llm_provider.py`):

```python
@dataclass
class LLMRequest:
    prompt: str
    system_prompt: str | None = None
    temperature: float | None = None
    max_output_tokens: int | None = None
    metadata: dict | None = None
    # New: list of (content, is_cache_boundary) tuples for structured prompts
    prompt_blocks: list[PromptBlock] | None = None

@dataclass
class PromptBlock:
    text: str
    cache_boundary: bool = False   # If True, add cache_control after this block
```

When `prompt_blocks` is provided, the provider uses structured content objects.
When absent, it falls back to the existing `prompt` string (backward compatible).

**Provider registration** (`resolve_provider()`):

```python
if provider_name == "anthropic":
    return AnthropicProvider(
        model=os.getenv("ANTHROPIC_MODEL", "claude-opus-4-7"),
        api_key=os.getenv("ANTHROPIC_API_KEY", ""),
        max_output_tokens=int(os.getenv("OPENAI_MAX_OUTPUT_TOKENS", "8192")),
    )
```

**New env vars:**

```
ANTHROPIC_API_KEY=sk-ant-...
ANTHROPIC_MODEL=claude-opus-4-7
```

---

### Phase 2 — Refactor planner prompt into blocks

**File:** `services/planner/app/planner_service.py`

Replace `build_llm_prompt()` (which returns a single string) with
`build_llm_prompt_blocks()` (which returns `list[PromptBlock]`):

```python
def build_llm_prompt_blocks(request: PlanRequest, runtime: ...) -> list[PromptBlock]:
    # Block 1: static rules + schema — CACHE BOUNDARY
    static_block = PromptBlock(
        text=_build_static_instructions(),   # extracted from current lines 319–394
        cache_boundary=True,
    )
    # Block 2: capability catalog — CACHE BOUNDARY
    # This is semi-static: changes only when capability_registry.yaml is modified.
    # Keyed by registry mtime so cache invalidates when file changes.
    catalog_block = PromptBlock(
        text=_build_capability_catalog_section(runtime),
        cache_boundary=True,
    )
    # Block 3: dynamic per-call content — NO cache boundary
    dynamic_block = PromptBlock(
        text=_build_dynamic_section(request),
        cache_boundary=False,
    )
    return [static_block, catalog_block, dynamic_block]
```

**For OpenAI:** the blocks are concatenated into a single string in the provider (same
as today), but the order is now static-first, so the prefix is stable across calls for
the same registry version. OpenAI's automatic prefix cache will hit.

**For Anthropic:** each block becomes a `content` list entry with an optional
`cache_control` field:

```python
def _build_messages(request: LLMRequest) -> list[dict]:
    content = []
    for block in request.prompt_blocks:
        entry = {"type": "text", "text": block.text}
        if block.cache_boundary:
            entry["cache_control"] = {"type": "ephemeral"}
        content.append(entry)
    return [{"role": "user", "content": content}]
```

---

### Phase 3 — Capability catalog as a service-lifetime cache

The capability catalog JSON is the largest block (10–50 KB). It is already cached in
memory by `load_capability_registry()` (keyed by file mtime). Extend this to also cache
the serialised JSON string so `json.dumps()` is not called on every plan:

```python
# libs/core/capability_registry.py
_CATALOG_JSON_CACHE: dict[str, str] = {}   # mtime → json string

def load_capability_catalog_json(path=None) -> str:
    registry = load_capability_registry(path)
    key = str(_CAPABILITY_CACHE_KEY)
    if key not in _CATALOG_JSON_CACHE:
        _CATALOG_JSON_CACHE[key] = json.dumps(
            [spec_to_dict(s) for s in registry.capabilities.values()],
            ensure_ascii=False,
        )
    return _CATALOG_JSON_CACHE[key]
```

This means the catalog string is identical byte-for-byte across plan calls until the
registry file is modified — which is exactly what OpenAI's prefix cache requires.

---

### Phase 4 — Fix the repair prompt duplication

Currently, the repair prompt (`build_llm_repair_prompt()`) re-embeds the full original
prompt (lines 397–432 in `planner_service.py`). For a 40 KB planner prompt, a single
repair attempt doubles the token cost.

**Fix:** send the repair as an assistant + user continuation instead of a new request:

```python
# Instead of: one giant request containing original_prompt + malformed_output + repair_instructions
# Do:
messages = [
    {"role": "user",      "content": original_prompt_blocks},   # cached
    {"role": "assistant", "content": malformed_output},          # what the model returned
    {"role": "user",      "content": repair_instructions},       # small, dynamic
]
```

The `original_prompt_blocks` are already cached from the first call. The repair adds only
two small turns. This eliminates the duplication and keeps the cache hot.

For providers that don't support multi-turn (the current `OpenAIProvider` using the
`/completions` endpoint), fall back to the existing approach. Only `OpenAIChatCompletionsProvider`
and `AnthropicProvider` support multi-turn.

---

### Phase 5 — Chat service prompt stabilisation

**File:** `services/api/app/main.py`

The chat router, chat response, and boundary decision prompts each have static system
prompt text that is reconstructed as a Python string on every call. Extract these into
module-level constants so the string object is identical between calls:

```python
# Module level — built once at import time
_CHAT_ROUTER_SYSTEM_PROMPT = _build_chat_router_system_prompt()
_CHAT_RESPONSE_SYSTEM_PROMPT = _build_chat_response_system_prompt()
_CHAT_BOUNDARY_SYSTEM_PROMPT = _build_chat_boundary_system_prompt()
```

For Anthropic, mark the system prompt as a cache boundary. For OpenAI, the stable system
message prefix will be automatically cached for prompts sharing the same prefix.

---

## Cache Boundary Summary

| Call site | Cache boundary location | Cacheable size | Cache type |
|---|---|---|---|
| Planner (initial plan) | After capability catalog | ~20–60 KB | Anthropic block / OpenAI prefix |
| Planner (repair) | Reuse initial call messages | ~20–60 KB | Multi-turn continuation |
| Worker `llm_generate` | After system prompt | ~300 B | Anthropic block |
| Worker `llm_generate_document_spec` | After system prompt | ~500 B | Anthropic block |
| Chat router | After routing rules + schema | ~2 KB | Anthropic block / OpenAI prefix |
| Chat response | After system prompt | ~300 B | Anthropic block / OpenAI prefix |
| Chat boundary | After decision rules | ~1.5 KB | Anthropic block / OpenAI prefix |

---

## Observability

### Cache hit tracking

Extend `LLMProvider.generate()` to return a `LLMResponse` dataclass instead of a raw string:

```python
@dataclass
class LLMResponse:
    text: str
    input_tokens: int = 0
    output_tokens: int = 0
    cached_input_tokens: int = 0   # from usage.prompt_tokens_details.cached_tokens (OpenAI)
                                   # or usage.cache_read_input_tokens (Anthropic)
    cache_creation_tokens: int = 0 # from usage.cache_creation_input_tokens (Anthropic)
```

Log these at the call site. Emit as OpenTelemetry spans (Jaeger is already configured) with
attributes `llm.cached_tokens` and `llm.cache_hit_ratio`. Surface in Grafana alongside
the existing latency dashboards.

### Expected savings

| Component | Prompt size | Cache hit rate | Est. token reduction |
|---|---|---|---|
| Planner (capability catalog) | 10–50 KB | ~80% (same registry version) | 70–85% of input tokens |
| Planner (static rules) | ~9 KB | ~95% | included above |
| Chat router | ~2 KB | ~90% | 60–70% of input tokens |
| Repair prompt | doubles current | 100% (continuation) | 50% vs. today |

---

## Rollout order

1. **Phase 2 + 3** (no new provider): Reorder planner prompt blocks and cache the catalog
   JSON string. Works with the existing OpenAI provider. Zero risk to production; validates
   that OpenAI prefix caching is hitting via `cached_tokens` in the response.

2. **Phase 5**: Extract chat system prompts to module-level constants. Zero risk.

3. **Phase 1**: Add `AnthropicProvider`. Introduce `LLMRequest.prompt_blocks` as optional.
   Test with a single service (planner) before rolling out to chat.

4. **Phase 4**: Fix repair prompt duplication. Requires multi-turn support to be working.

---

## Open items

**OI-1 — LLMProvider return type is a breaking change**
Today `generate()` returns `str`. Returning `LLMResponse` breaks every call site. Options:
add a separate `generate_with_usage()` method that returns `LLMResponse`, or introduce a
response wrapper and update all callers. The separate method is lower risk for rollout.

**OI-2 — OpenAI prefix cache TTL is undocumented / variable**
OpenAI does not publish a fixed TTL for automatic prefix caching. In practice it is a few
minutes. If the planner is called infrequently (e.g., once per minute), the cache may miss
between calls. Measure `cached_tokens` in production before claiming savings.

**OI-3 — Anthropic cache TTL vs. planning frequency**
Anthropic's default cache TTL is 5 minutes. If the same capability catalog is used across
many plan calls within 5 minutes (e.g., a high-throughput deployment), savings are large.
For low-throughput deployments, consider the 1-hour extended cache (available on certain
tiers) or accept that savings are smaller.

**OI-4 — Gemini context caching requires ≥ 32 768 tokens**
The minimum cacheable content for Gemini is 32 768 tokens (~25 KB). The planner prompt's
static block is ~20–60 KB, which may or may not meet the minimum depending on the registry
size. Verify token count before implementing Gemini caching.

**OI-5 — Capability catalog cache invalidation across multiple instances**
In a multi-instance deployment (multiple API pods), each instance has its own in-process
`_CATALOG_JSON_CACHE`. If the registry file changes, instances invalidate their cache
independently as they next call `load_capability_registry()`. This is fine for correctness
but means different instances may send different catalog strings during the transition
window, splitting the provider-side cache. Not a correctness issue; note it for observability.

**OI-6 — `PromptBlock` abstraction may not map cleanly to all providers**
OpenAI's `/chat/completions` treats the system message and user messages separately.
Anthropic uses a `content` list with typed blocks. Some OpenAI-compatible providers
(e.g., local models via llama.cpp) may not support structured content blocks at all.
The `PromptBlock` abstraction needs a clean fallback: if the provider does not support
structured content, concatenate blocks with a delimiter and send as a single string.

**OI-7 — Static block extraction needs careful testing**
The "static" planning rules in `build_llm_prompt()` currently reference format strings
that interpolate values like `{json_schema}`. Extracting them to module-level constants
requires verifying no dynamic interpolation is hidden in the "static" block. A mismatch
would silently break the cache boundary (different string each call) without causing a
correctness failure.