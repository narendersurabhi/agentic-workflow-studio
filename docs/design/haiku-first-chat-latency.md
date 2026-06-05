# Haiku-First Chat Latency Design

## Problem

Current Bedrock chat latency is too high when Sonnet is used on the interactive path.

Observed timings:

- Haiku call: about 2 seconds
- Sonnet call: about 30 seconds
- Recent config tuning reduced the Sonnet-backed path to about 12 seconds, but this is still too slow for normal chat

The target is to make routine chat feel interactive while preserving a slower high-quality path for complex turns.

## Status of Prior Work

Several optimizations are already shipped and should not be re-implemented:

- **Streaming (SSE)** — `POST /chat/sessions/{id}/messages/stream` streams Bedrock and Anthropic responses token-by-token. First-token latency is under 500 ms on the chat-reply path. All latency targets in this doc are TTFT targets, not full-response targets.
- **One-Call Simple Path** — when the boundary returns `chat_reply`, `_route_chat_turn` uses `boundary.assistant_response` directly via `_chat_response_turn_plan(response_generated=True)` and skips the response LLM call entirely. This is Tier 1 as described below and is already live.
- **`response_generated` field** — already present in the boundary output schema since the typed-plan refactor. It is not a new field.
- **Parallel boundary + route-request pre-fetch** — `_build_chat_route_request` (intent normalization + capability search) runs concurrently with the boundary decision on execution-request turns, saving ~300–400 ms.
- **Prompt caching** — `CachingLLMProvider` routes per-session calls through `generate_cached` using a Redis-backed `CacheSessionStore` keyed by `session_id`. Cache hits reduce input-token billing and latency on warm sessions.

## Goals

- Keep simple chat TTFT under 500 ms where possible.
- Avoid Sonnet on the default chat path.
- Use Sonnet only when the user explicitly asks for deeper reasoning or the turn is complex enough to justify the latency.
- Allow an optional second Haiku call for medium-complexity review or repair.
- Preserve the existing rule that chat is unavailable when the LLM provider is unavailable.

## Non-Goals

- Guarantee a full Sonnet response under 2 seconds end-to-end (first-token can still be fast via streaming).
- Replace model quality with deterministic fallback responses.

## Decision

Use Haiku as the default chat model. Sonnet becomes an escalation model, not the primary response model.

Multiple Haiku calls are useful only when they replace a Sonnet call for medium-complexity work. They should not be used for every turn. If Haiku TTFT is about 500 ms with streaming, then two sequential Haiku calls are still under 2 seconds first-token, which is much faster than a Sonnet call. But adding a second call to every message would double latency for the common path.

Default policy:

| Tier | Path | Expected use | TTFT target |
|---|---|---|---|
| Tier 0 | Deterministic bypass | Safe local checks, pending correction heuristics | < 100 ms |
| Tier 1 | Single Haiku call | Normal chat, short explanations, routing with concise answer | < 500 ms |
| Tier 2 | Two Haiku calls | Medium complexity answer plus review or repair | < 1.5 s |
| Tier 3 | Sonnet escalation | Explicit deep reasoning, high complexity, high confidence requirement | < 2 s (streamed) |

All targets are time-to-first-token. Full-response completion time will be longer and is a secondary metric.

## Routing Policy

The front-door boundary/router call should use Haiku and return both the routing decision and latency metadata.

Recommended structured fields:

```json
{
  "route": "answer|handoff|clarify",
  "assistant_response": "string",
  "response_generated": true,
  "complexity": "simple|medium|high",
  "latency_tier": "single_haiku|review_haiku|sonnet",
  "confidence": "high|medium|low",
  "needs_review": false,
  "requires_sonnet": false,
  "reason_code": "short_machine_readable_reason"
}
```

### `reason_code` vocabulary

The following codes must be supported. Implementations must not invent codes outside this list without updating the doc.

| Code | Meaning |
|---|---|
| `conversational` | Turn is chat-only; no capability or job routing needed |
| `short_factual` | Simple factual or product question; Haiku can answer directly |
| `medium_impl` | Implementation or configuration question; review pass may help |
| `high_complexity` | Architecture, code review, or large-context synthesis |
| `explicit_deep` | User phrase explicitly requested detailed or deep analysis |
| `low_confidence` | Haiku confidence is too low to answer without escalation |
| `pending_correction` | Turn is a correction to a prior pending clarification |
| `execution_request` | Turn requires job or workflow dispatch |

### Tier classification

**Important:** Haiku self-assessing its own output quality is unreliable. The `latency_tier` field returned by the boundary model is a hint, not a guarantee. A heuristic pre-classifier (turn length, question-type tokens, pending-clarification state) should gate the Tier 2 and Tier 3 paths independently of what Haiku returns, so a miscategorized turn does not silently use the wrong model. The boundary `latency_tier` is logged for calibration but should be validated against the heuristic before acting on it.

### Tier 1: Single Haiku

Use one Haiku call when:

- The user asks a simple product question.
- The turn is conversational or asks for a short explanation.
- The router can answer directly with high confidence.
- The response does not require long-context synthesis or careful tradeoff analysis.

This is the default route and is already implemented via the `chat_reply` boundary path.

### Tier 2: Two Haiku Calls

Use a second Haiku call only when:

- The first Haiku answer is useful but should be checked for completeness.
- The turn is medium complexity.
- The user asks for a more polished answer, but not deep reasoning.
- The answer includes steps, configuration, or implementation advice where a quick review can catch omissions.
- Router confidence is medium, but the problem does not require Sonnet.

The second call should be a bounded reviewer, not a second full reasoning pass. It should return the final answer only. The review prompt must be constrained:

- Do not expand unless necessary.
- Fix missing or incorrect points.
- Return the complete corrected answer, not a diff.
- Keep output under the configured review token cap (minimum 512 tokens; 256 is not sufficient for complete medium-complexity answers).

### Tier 3: Sonnet

Use Sonnet only when:

- The user explicitly asks for deep reasoning, careful analysis, architecture, or code review.
- The turn requires large-context synthesis.
- The answer is high impact and Haiku confidence is low.
- A Haiku review reports that the draft is incomplete or unsafe to answer.
- The user has opted into a slower high-quality response.

Sonnet responses must be streamed. Because streaming is already shipped, there is no synchronous fallback path to design. If `CHAT_SONNET_ESCALATION_ENABLED=false`, the turn falls back to Tier 2 (two-Haiku review) rather than erroring. This fallback must be logged with `reason_code=sonnet_disabled_fallback`.

## Architecture

### Provider Split

Keep separate provider instances for each chat role:

- `CHAT_ROUTER_MODEL`: cheap route classification
- `CHAT_BOUNDARY_MODEL`: cheap front-door route plus concise answer
- `CHAT_RESPONSE_MODEL`: normal user-facing response (switch from Sonnet to Haiku)
- `CHAT_REVIEW_MODEL`: optional review and repair pass (new)
- `CHAT_DEEP_RESPONSE_MODEL`: Sonnet escalation path (new)

The boundary and router models should be Haiku. **The normal response model should also be switched to Haiku.** Sonnet should be configured only as the deep response model. This is a breaking change for existing deployments — see the Migration section.

### One-Call Simple Path (already implemented)

For simple turns, the boundary call returns the final assistant response directly:

1. Build boundary prompt.
2. Call Haiku with low max output tokens.
3. Validate the JSON object.
4. If `response_generated=true` and `latency_tier=single_haiku`, persist and return `assistant_response`.

This avoids a router call followed by a separate response call for simple chat. It is live and no implementation work is needed.

### Two-Haiku Review Path

For medium turns:

1. Generate the draft with `CHAT_RESPONSE_MODEL` (Haiku).
2. Call `CHAT_REVIEW_MODEL` (Haiku) with the draft and the original user request.
3. Return the reviewed final answer.

### Sonnet Escalation Path

For high-complexity turns:

1. Route to `CHAT_DEEP_RESPONSE_MODEL` (Sonnet).
2. Use the streaming SSE endpoint — all Sonnet calls must stream.
3. Set `sonnet_used=true` and `escalation_reason` in `LLMRequest.metadata` so the timing log captures it.
4. If `CHAT_SONNET_ESCALATION_ENABLED=false`, fall back to two-Haiku path and log `sonnet_disabled_fallback`.

### Routing metadata in LLM calls

`latency_tier`, `complexity`, `review_used`, `sonnet_used`, and `escalation_reason` are routing-layer decisions. They must be threaded from the boundary JSON into `LLMRequest.metadata` before each downstream call so `TimingLLMProvider` can emit them in structured logs without changes to the provider interface. Example:

```python
LLMRequest(
    prompt="",
    prompt_blocks=prompt_blocks,
    metadata={
        "component": "chat_response",
        "session_id": chat_session_id,
        "latency_tier": tier,          # from boundary decision
        "complexity": complexity,       # from boundary decision
        "review_used": review_used,     # bool
        "sonnet_used": sonnet_used,     # bool
        "escalation_reason": reason,    # reason_code or ""
    },
)
```

`TimingLLMProvider._log()` already forwards arbitrary `metadata` keys that match a known set. Extend the known set to include the fields above.

## Configuration

Recommended POC configuration:

```dotenv
CHAT_ROUTER_MODEL=us.anthropic.claude-haiku-4-5-20251001-v1:0
CHAT_BOUNDARY_MODEL=us.anthropic.claude-haiku-4-5-20251001-v1:0
CHAT_RESPONSE_MODEL=us.anthropic.claude-haiku-4-5-20251001-v1:0
CHAT_REVIEW_MODEL=us.anthropic.claude-haiku-4-5-20251001-v1:0
CHAT_DEEP_RESPONSE_MODEL=us.anthropic.claude-sonnet-4-6

CHAT_ROUTER_MAX_OUTPUT_TOKENS=384
CHAT_BOUNDARY_MAX_OUTPUT_TOKENS=384
CHAT_RESPONSE_MAX_OUTPUT_TOKENS=768
CHAT_REVIEW_MAX_OUTPUT_TOKENS=512
CHAT_DEEP_RESPONSE_MAX_OUTPUT_TOKENS=2048

CHAT_PENDING_CORRECTION_MODE=heuristic
CHAT_CLARIFICATION_NORMALIZER_ENABLED=false
CHAT_SONNET_ESCALATION_ENABLED=true
```

Model IDs should remain configurable because Bedrock model availability and access vary by AWS account and region. The `us.` inference-profile prefix must be supported for Bedrock model IDs.

## Migration

Switching `CHAT_RESPONSE_MODEL` from Sonnet to Haiku is a **breaking behavioral change** for existing deployments. Existing users will receive shorter, faster responses on the default path and may notice a quality difference on medium-complexity questions.

Migration steps:

1. Set `CHAT_DEEP_RESPONSE_MODEL` to the current `CHAT_RESPONSE_MODEL` value before changing `CHAT_RESPONSE_MODEL`.
2. Deploy with `CHAT_SONNET_ESCALATION_ENABLED=false` first to validate Haiku quality before enabling escalation.
3. Monitor `sonnet_used` and `review_used` rates for one week before setting `CHAT_SONNET_ESCALATION_ENABLED=true`.
4. Communicate the change in release notes — users who relied on Sonnet for routine chat should know the default has changed and how to trigger escalation.

## Observability

Every LLM call should log:

- `component`
- `model`
- `latency_ms`
- `input_tokens`
- `output_tokens`
- `cached_input_tokens`
- `latency_tier`
- `complexity`
- `review_used`
- `sonnet_used`
- `escalation_reason`

These fields flow from the boundary JSON into `LLMRequest.metadata` and are forwarded by `TimingLLMProvider._log()` — no changes to the provider interface are needed beyond extending the forwarded key set.

This is required to prove the default path is actually using Haiku and to detect accidental Sonnet calls on routine chat.

## Success Metrics

All targets are TTFT (time-to-first-token) because streaming is live.

| Path | P50 TTFT | P95 TTFT |
|---|---|---|
| Simple chat (Tier 1) | ≤ 500 ms | ≤ 1.5 s |
| Medium review (Tier 2) | ≤ 1.5 s | ≤ 3 s |
| Sonnet escalation (Tier 3) | ≤ 2 s | ≤ 4 s |

Additional targets:

- Sonnet usage: less than 5–10% of normal chat turns
- LLM unavailable errors still return chat unavailable instead of static fallback text
- `review_used` rate: less than 20% of turns (review should not become the default path)

## Risks

- Haiku may miss nuance on complex turns. Mitigation: use review and explicit Sonnet escalation.
- Two Haiku calls double latency for medium turns. Mitigation: never enable review by default for simple turns; use heuristic pre-classifier to gate Tier 2.
- Haiku self-classifies its tier unreliably. Mitigation: treat `latency_tier` from Haiku as a hint; validate against an independent heuristic before routing.
- Router misclassification can send hard questions to Haiku. Mitigation: log confidence and `reason_code`; add escalation tests.
- Lower token caps can truncate answers. Mitigation: `CHAT_REVIEW_MAX_OUTPUT_TOKENS` is set to 512 minimum; tune caps using logged output token counts.
- Switching `CHAT_RESPONSE_MODEL` to Haiku degrades quality for users on existing deployments. Mitigation: follow migration steps above; keep `CHAT_SONNET_ESCALATION_ENABLED=false` during initial rollout.

## Implementation Plan

The following steps remain to be done. Items already shipped are noted above in the Status section.

1. Add `CHAT_REVIEW_MODEL`, `CHAT_DEEP_RESPONSE_MODEL`, and role-specific max output token env vars.
2. Extend boundary structured output with `latency_tier`, `complexity`, `confidence`, `needs_review`, `requires_sonnet`, and `reason_code`.
3. Thread routing metadata (`latency_tier`, `complexity`, `escalation_reason`, `review_used`, `sonnet_used`) into `LLMRequest.metadata` on each downstream call.
4. Extend `TimingLLMProvider._log()` to forward the new metadata keys.
5. Implement the two-Haiku review path behind `CHAT_REVIEW_MODEL` and routing policy.
6. Implement Sonnet escalation behind `CHAT_SONNET_ESCALATION_ENABLED` and the explicit criteria above, with fallback to two-Haiku when disabled.
7. Add heuristic pre-classifier to gate Tier 2 and Tier 3 independently of the Haiku `latency_tier` hint.
8. Add tests for provider selection, tier decisions, and LLM unavailable propagation.

## Testing Plan

Unit tests:

- Simple turns use exactly one Haiku provider call.
- Medium turns use exactly two Haiku provider calls when review is requested.
- Sonnet is used only when `requires_sonnet=true` or explicit deep-answer triggers match.
- When `CHAT_SONNET_ESCALATION_ENABLED=false`, a turn that would escalate falls back to two-Haiku and logs `sonnet_disabled_fallback`.
- LLM unavailable errors propagate as chat unavailable and are not converted to fallback text.
- Bedrock model IDs with `us.` prefixes pass through unchanged.
- `TimingLLMProvider` emits `latency_tier`, `complexity`, `review_used`, `sonnet_used`, `escalation_reason` in structured logs.

Integration tests:

- Fake providers with controlled delays validate tier TTFT behavior.
- Boundary JSON validation rejects non-object structured output.
- Logs include model, component, latency tier, and escalation reason.

Manual verification:

- Ask a simple chat question and confirm only one Haiku call appears in logs.
- Ask a medium implementation question and confirm the review path is used only when routed.
- Ask for deep architecture review and confirm Sonnet escalation is visible in logs and the response streams.
