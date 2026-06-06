# Chat Latency Optimization Log

Running log of every latency issue diagnosed and fixed on the chat path, in order.
Each entry records the symptom, root cause, fix, and the commit(s) that shipped it.

---

## 1 — Sonnet on every chat turn (baseline problem)

**Symptom**  
All chat turns were routed through the Sonnet model. Observed end-to-end response times of 12–30 seconds.

**Root cause**  
`CHAT_RESPONSE_MODEL` was set to Sonnet. There was no fast path for simple conversational messages — every turn paid the full Sonnet generation cost.

**Fix**  
Switched `CHAT_RESPONSE_MODEL` to Haiku. Sonnet is now an opt-in escalation path controlled by `CHAT_SONNET_ESCALATION_ENABLED` and `CHAT_DEEP_RESPONSE_MODEL`. Added `requires_sonnet: bool` and `complexity: str` fields to `ChatBoundaryDecision` so the boundary model can signal when escalation is warranted.

**Files changed**  
- `services/api/app/main.py` — provider split, `_build_chat_deep_response_provider`, Sonnet escalation logic in `_generate_chat_response`
- `libs/core/chat_contracts.py` — `requires_sonnet`, `complexity` fields on `ChatBoundaryDecision`
- `.env.example` — `CHAT_DEEP_RESPONSE_MODEL`, `CHAT_DEEP_RESPONSE_MAX_OUTPUT_TOKENS`, `CHAT_SONNET_ESCALATION_ENABLED`

**Commit** `84ca192`

---

## 2 — Prompt cache always missing

**Symptom**  
Every chat turn paid full input-token cost. Cache hit rate was 0% even on warm sessions.

**Root cause**  
`CachingLLMProvider.generate_cached` was building the cache key from the wrong fields — the per-turn dynamic content was included in the stable (pinned) block, so the hash changed on every turn.

**Fix**  
Corrected the block partitioning: STATIC blocks contain only content stable across the session (system prompt, user profile, capability catalog). RUN blocks hold session-level context. DYNAMIC blocks hold the per-turn user message. Only STATIC + RUN content feeds the cache key.

**Files changed**  
- `services/api/app/main.py` — `_build_context_prompt_blocks` block stability assignments
- `libs/core/cache_session_store.py` — cache key derivation

**Commit** `2eac3bb`

---

## 3 — Chat history full-table scan on long sessions

**Symptom**  
Chat turns on sessions with many messages had unexpectedly high database latency. Every turn was loading the full message history.

**Root cause**  
`_load_chat_messages` had no LIMIT clause. On sessions with hundreds of messages it performed a full table scan and loaded all rows.

**Fix**  
Added `CHAT_HISTORY_CONTEXT_LIMIT` (default 50). Only the most recent N messages are loaded per turn.

**Files changed**  
- `services/api/app/main.py` — history query limit
- `.env.example` — `CHAT_HISTORY_CONTEXT_LIMIT=50`

**Commit** `a685196`

---

## 4 — RAG vector search on every conversational turn

**Symptom**  
Simple questions like "hi" or "what can you do?" had 1–3 seconds of added latency from a capability vector search that returned no useful results.

**Root cause**  
The capability and intent vector searches ran unconditionally before the boundary decision, including on purely conversational turns where no capability matching is needed.

**Fix**  
Added a pre-check using `_looks_like_conversational_turn()`: if the message is clearly conversational (no workflow tokens, no intent signals), skip both the intent vector search and the capability vector search entirely. Also fixed RAG retriever timeouts that were causing occasional 20-second stalls.

**Files changed**  
- `services/api/app/main.py` — conversational skip gate before vector searches
- `libs/core/rag_retriever.py` — timeout handling

**Commit** `5c2a0c9`

---

## 5 — SSE streaming endpoint added (sub-500 ms TTFT architecture)

**Symptom**  
All responses waited for full LLM completion before the user saw any text. Even fast Haiku responses felt slow because the full payload arrived as one block.

**Root cause**  
The only chat endpoint was `POST /chat/sessions/{id}/messages` (synchronous). There was no streaming path.

**Fix**  
Added `POST /chat/sessions/{id}/messages/stream` — an SSE endpoint that streams tokens as they arrive. Architecture:

1. A worker thread is created per request. It sets `_stream_callback_local.callback` (thread-local) then calls `handle_turn`.
2. `_generate_chat_response` checks the thread-local callback. When set, it iterates `provider.stream_request()` and calls the callback for each chunk.
3. Each chunk is put into a `queue.Queue` as a `("token", text)` tuple.
4. A synchronous generator in the main thread reads from the queue and yields `data: {"type":"token","text":"..."}` SSE events.
5. On completion the worker puts `("done", None)` which causes the generator to yield the final `ChatTurnResponse` payload as a `done` event.

Response headers: `Cache-Control: no-cache`, `X-Accel-Buffering: no`.

**Files changed**  
- `services/api/app/main.py` — `create_chat_message_stream`, `_stream_callback_local`, streaming branch in `_generate_chat_response`
- `services/ui/src/app/WorkspaceSurfaceContent.tsx` — SSE event reader, optimistic streaming bubble

**Commit** `bc0cb73`

---

## 6 — Parallel pre-fetch regression: 15-second stall on all chat turns

**Symptom**  
After adding speculative pre-fetching, ALL chat turns (including simple "hi") regressed to 15+ seconds. The pre-fetch was supposed to save time on execution turns only.

**Root cause**  
`_prefetch_thread.join()` (with no timeout) was called unconditionally after the boundary decision. For `chat_reply` turns the pre-fetch thread was running an intent normalization + capability search LLM call (~12–15 s) and the main thread blocked waiting for it to finish before returning.

**Fix**  
Moved the `.join()` inside the `execution_request` / `continue_pending` branch only. Added a 5-second timeout to prevent indefinite blocking even on those paths. The daemon thread finishes on its own for `chat_reply` turns.

**Files changed**  
- `services/api/app/main.py` — `_route_chat_turn`, pre-fetch join moved to execution branch

**Commit** `e17e07e`

---

## 7 — Factual questions routed to clarification ("What is the capital of Germany?" → "What output format do you need?")

**Symptom**  
WH-questions and simple factual queries were classified as `execution_request` by the boundary model, triggering the clarification flow instead of a direct answer.

**Root cause**  
`_looks_like_conversational_turn()` used a narrow set of casual phrases. WH-questions ("what is", "what are", "how does", etc.) were not recognised, so they bypassed the fast-exit path and went to the boundary LLM. The boundary model then saw high capability-search scores (vector similarity on common words) and classified them as execution requests.

Additionally, `conversation_mode_hint` was being fed into the boundary LLM prompt, but its value was pre-computed from the same heuristic — creating a feedback loop that poisoned the model's judgment on borderline messages.

**Fixes applied**

*a) Extended `_looks_like_conversational_turn`*  
Added prefixes: `why`, `what is`, `what's`, `whats`, `what are`, `what was`, `what were`, `how does`, `how do`, `how did`, `how many`, `how much`, `how long`, `how old`, `can you explain`, `explain`. Added a regex for `who`, `where`, `when`, `which` question openers.

*b) Removed `conversation_mode_hint` from boundary evidence payload*  
`_build_chat_boundary_decision_prompt` now excludes `conversation_mode_hint` from the serialised evidence dict (`exclude={"conversation_mode_hint"}`). The field is still computed locally for the fast-exit gate but is never shown to the boundary LLM.

*c) Simplified boundary postprocessor*  
Removed the `execution_signal_override` branch and the `conversation_mode_hint != "conversational"` checks from `_postprocess_chat_boundary_decision`. The model's decision is now trusted directly.

**Files changed**  
- `services/api/app/main.py` — `_looks_like_conversational_turn`, `_build_chat_boundary_decision_prompt`, `_postprocess_chat_boundary_decision`

**Commits** `073dee1`, `8fce2ff`

---

## 8 — Speculative pre-fetch for execution turns

**Feature** (latency improvement, not a regression fix)

**Problem**  
On `execution_request` turns, the main path was: (1) boundary decision, (2) build route request (intent normalization + capability search), (3) router call. Steps 1 and 2 were sequential; step 2 added ~300–400 ms.

**Fix**  
Start building the route request (`_build_chat_route_request`) in a background thread as soon as the boundary call begins. If the boundary returns `execution_request` or `continue_pending`, the result is already ready. If it returns `chat_reply`, the background thread result is discarded.

**Files changed**  
- `services/api/app/main.py` — `_prefetch_thread` and `_prefetch_result` in `_route_chat_turn`

**Commit** `ed9285c`

---

## 9 — Streaming tokens never reached the browser (blank bubble until done)

**Symptom**  
The SSE endpoint was returning a `done` event but no `token` events. The assistant bubble stayed empty until the full response arrived, then showed all text at once.

**Root cause**  
The boundary model was returning a non-empty `assistant_response` for `chat_reply` decisions (its "one-call answer" optimisation). In `_route_chat_turn`, this response was passed to `_chat_response_turn_plan(assistant_content=boundary.assistant_response)`, which set `response_generated=True`. `_finalize_chat_turn_plan` saw `response_generated=True` and returned early, skipping `_generate_chat_response` entirely. No `provider.stream_request()` was ever called; no `token` events were placed in the queue. Only the `done` event was emitted.

**Fix**  
Added `_stream_active = getattr(_stream_callback_local, "callback", None) is not None` check at the top of the routing decision in `_route_chat_turn`. When streaming is active, `assistant_content` is forced to `""` regardless of the boundary's inline response, so `response_generated=False` and `_generate_chat_response` is always called. The non-streaming path (direct API call) still uses the boundary's inline response as before.

```python
_stream_active = getattr(_stream_callback_local, "callback", None) is not None
assistant_content = "" if _stream_active else (boundary.assistant_response or "")
```

**Files changed**  
- `services/api/app/main.py` — `_route_chat_turn`, `chat_reply` and `exit_pending_to_chat` branches

**Commit** `85251be`

---

## 10 — SSE buffered by Next.js proxy (all tokens arrive simultaneously)

**Symptom**  
Even after fix 9, no visual streaming was observed. The response still appeared all at once. Backend logs confirmed tokens were being streamed correctly by FastAPI/Bedrock.

**Root cause**  
The docker-compose default bakes `NEXT_PUBLIC_API_URL=/api` into the UI bundle at build time. All requests (including SSE) go through the Next.js catch-all proxy at `services/ui/src/app/api/[...path]/route.ts`. That proxy had three defects:

1. **No `export const dynamic = "force-dynamic"`** — Next.js treated the route handler as potentially static/cacheable, which prevented streaming.
2. **`transfer-encoding` header stripped** — `copyResponseHeaders()` deleted the `transfer-encoding` header. For HTTP/1.1 chunked SSE responses this removed the signal that tells Node.js to process chunks progressively.
3. **`upstream.body` passed directly to `new Response()`** — Next.js's response layer could buffer the `ReadableStream` before writing to the client TCP connection.

**Fix**  
- Added `export const dynamic = "force-dynamic"` at the top of `route.ts`.
- Removed `transfer-encoding` from the set of stripped headers.
- For `Content-Type: text/event-stream` responses, replaced the direct body pass-through with an explicit `ReadableStream` pipe:

```typescript
const passThrough = new ReadableStream({
    async start(controller) {
        const reader = upstreamBody.getReader();
        for (;;) {
            const { done, value } = await reader.read();
            if (done) { controller.close(); break; }
            controller.enqueue(value);  // flush each chunk immediately
        }
    },
});
return new Response(passThrough, { status, headers });
```

- Increased header-receipt timeout from 60 s to 120 s (the timeout is cancelled as soon as headers arrive; the body stream stays open indefinitely).

**Files changed**  
- `services/ui/src/app/api/[...path]/route.ts`

**Commit** `2b3c8e3`

---

## 11 — Next.js gzip compression batching SSE events (tokens still not progressive)

**Symptom**  
After fix 10, tokens were still arriving in large batches rather than one at a time. For long responses (>50 tokens) the observable TTFT was 2–16 seconds.

**Root cause**  
`next start` (production build) enables gzip compression by default (`compress: true` in `next.config.js`). The gzip compressor accumulates plaintext data internally until its sliding-window buffer fills before emitting a compressed block. Because SSE events are small (~30–100 bytes each), many events were buffered inside the compressor and released together, making streaming invisible to the browser.

**Fix**  
Set `compress: false` in `next.config.js`. Each SSE `data:` frame now flushes to the browser immediately. Static-asset compression should be handled by a reverse proxy (nginx) in front of the Next.js server rather than by Next.js itself.

```javascript
const nextConfig = {
  reactStrictMode: true,
  compress: false,
};
```

**Files changed**  
- `services/ui/next.config.js`

**Commit** `9ea1fbe`

---

## 12 — Boundary LLM called for all non-matching chat messages (long TTFT)

**Symptom**  
TTFT was 2–5+ seconds for any prompt that didn't match the narrow positive-match heuristic: "count from 1 to 10", "write a poem", "tell me a joke", etc. all paid the full boundary LLM round-trip before the first response token was sent. Prompts like "write a 500 word essay" were additionally failing with `chat_llm_unavailable` because the boundary model classified them as `execution_request`, sending them to the planner/executor which found no matching capability.

**Root cause**  
`_looks_like_conversational_turn()` required a *positive match* — the message had to start with a known casual phrase, end with `?`, or match a specific regex. Anything outside those patterns fell through to the boundary LLM call. The function was designed to catch conversational turns, but in practice far more message types needed the fast-exit than the narrow patterns covered.

**Fix**  
Inverted the logic: instead of "is this conversational?", check "does this contain unambiguous execution signals?". The function now returns `True` (skip boundary) for everything except messages containing highly specific system-execution tokens (`"deploy "`, `"run workflow"`, `"submit job"`, `"create workflow"`, `"write file"`, etc.). Broad verbs like `"create "`, `"build "`, `"generate "`, `"run "` were removed from the gate because they appear in conversational questions ("how do I run this?").

**Impact**  
For the overwhelming majority of chat messages, TTFT drops from 2–5s to ~200–400ms (Bedrock Haiku's own first-token latency). Only messages with explicit workflow-execution tokens still pay the boundary LLM cost.

**Files changed**  
- `services/api/app/main.py` — `_looks_like_conversational_turn` rewritten

**Commit** `(pending)`

---

## 13 — DB connection pool overhead (first/stale request: +300–500 ms)

**Symptom**  
`total_build_ms` was 1188 ms on the first request and ~729 ms on the second. After the second request warmed up the pool, it dropped further.

**Root cause**  
`pool_pre_ping=True` (SQLAlchemy default) sends a `SELECT 1` on every connection checkout — one extra round-trip before every request. When a connection was stale (recycled after idle time), this triggered a full TCP+SSL+auth reconnect (300–500 ms). The pool was also undersized (`pool_size=5`), causing overflow connections on concurrent requests.

**Fix**  
- Set `pool_pre_ping=False`; replaced with `pool_recycle=1800` (proactively recycles after 30 min, preventing staleness without a per-request round-trip)
- `pool_size=20`, `max_overflow=20` (supports 40 concurrent connections), `pool_timeout=10`

**Files changed**  
- `services/api/app/database.py`

---

## 14 — Session record DB query on every turn (~40–100 ms per warm turn)

**Symptom**  
`session_ms ≈ 40–100 ms` on every turn — a SELECT on `chat_sessions` that returned the same data.

**Root cause**  
`_build_turn_context` queried the `chat_sessions` table on every request to load the session record, even though the record's metadata, title, and timestamps don't change between turns.

**Fix**  
Added in-process session cache (`_SESSION_CACHE` dict with `_CachedSession` dataclass). After each `_persist_turn`, the cache is populated. On the next turn, `_build_turn_context` serves the session record from the cache with `SimpleNamespace`, skipping the DB read entirely.

**Files changed**  
- `services/api/app/chat_service.py` — `_CachedSession`, `_SESSION_CACHE`, `_get/_put/_invalidate_cached_session`, warm-path in `_build_turn_context`

---

## 15 — User profile DB query on every turn (~30–80 ms per warm turn)

**Symptom**  
`envelope_ms ≈ 30–80 ms` — a SELECT on the memory table for the user profile on every turn.

**Root cause**  
`build_chat_context_envelope` → `load_user_profile` always queried the `memory` table. The user profile only changes when memory promotion fires (infrequently).

**Fix**  
Added in-process TTL cache in `memory_profile_service.py` (`_PROFILE_CACHE` dict, 60 s TTL). `write_user_profile` updates the cache on every write so hits are always fresh. Cold misses still query the DB.

**Files changed**  
- `services/api/app/memory_profile_service.py`

---

## 16 — `_looks_like_chat_only_correction` LLM call on every turn (~887 ms avg)

**Symptom**  
After fixes 13–15, `total_build_ms avg = 892 ms` across 5 requests, with `gap2_ms avg = 887 ms`. Session and envelope were near-zero. The bottleneck was entirely inside the `_message_from_record` loop + `_candidate_goal`.

**Root cause**  
`_execution_thread_candidate_goal` (called from `_candidate_goal` inside `_build_turn_context`) unconditionally called `is_chat_only_correction(current)` — which is `_looks_like_chat_only_correction`, an LLM call to the configured chat provider. This ran on every turn regardless of whether there was an active pending-clarification state to cancel. The LLM call (~887 ms) happened entirely before the main streaming LLM call, dominating TTFT.

**Fix**  
In `_candidate_goal`, only pass `is_chat_only_correction` to `_execution_thread_candidate_goal` when `pending_state is not None`. When there's no active clarification, the correction check is meaningless so the LLM call is skipped entirely.

Also added `convert_ms` and `goal_ms` sub-fields to `chat_build_context_timing` log to split `gap2_ms` into message-conversion time vs. goal-computation time for future diagnostics.

As a defensive secondary fix, added a 30-second TTL to `load_capability_registry` (via `_CAPABILITY_CACHE_CHECKED_AT`) so repeated calls within the same window skip the `stat()` on the YAML file.

**Files changed**  
- `services/api/app/chat_service.py` — gate `is_chat_only_correction` behind `pending_state is not None` in `_candidate_goal`; add `_tc3a`, `convert_ms`, `goal_ms` timing
- `libs/core/capability_registry.py` — `_CAPABILITY_CACHE_CHECKED_AT`, `_CAPABILITY_CACHE_TTL`, TTL fast-path in `load_capability_registry`

---

## Current state (after all fixes)

| Path | Expected TTFT | Notes |
|---|---|---|
| Conversational fast-exit (heuristic) | ~200–400 ms | No boundary LLM call; goes straight to Bedrock response |
| Execution turns (explicit tokens) | ~1–3 s TTFT | Boundary LLM → parallel pre-fetch → router → executor |
| Sonnet escalation (disabled by default) | ~1–2 s TTFT | `CHAT_SONNET_ESCALATION_ENABLED=true` required |

All TTFT figures are time-to-first-visible-token in the browser. Full response time is higher and depends on response length and model speed.

---

## Known remaining work

- Tier 2 (two-Haiku review pass) not yet wired — `CHAT_REVIEW_MODEL` env var exists in the design doc but provider is not instantiated.
- `latency_tier`, `review_used`, `escalation_reason` not yet threaded into `LLMRequest.metadata` for `TimingLLMProvider` logs.
- Tests for provider selection and tier decisions not yet written.
- Container must be rebuilt (`docker compose build ui`) after the `next.config.js` and proxy changes — these are baked into the production bundle.
