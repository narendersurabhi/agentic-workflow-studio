# LLM-Required Chat Availability

## Objective

Make chat an LLM-required surface.

If the configured chat LLM is missing, misconfigured, rate limited, quota exhausted,
timing out, or otherwise unavailable, chat must report unavailable instead of
answering from static fallback text or deterministic route heuristics.

The desired user-visible behavior is simple:

- The chat composer shows that chat is not available.
- Sending a chat message returns HTTP 503.
- No assistant message is persisted for the failed turn.
- The user's draft remains available in the UI so it can be retried.

## Design Principle

The LLM owns chat decisions and assistant prose. Deterministic code may still:

- build context
- validate and normalize model output
- enforce safety and capability policy
- execute a model-selected workflow or capability
- persist state

Deterministic code must not synthesize a successful chat answer when the LLM
role required for the turn is unavailable.

## Current Gap

The current stack has partial unavailable propagation:

- `LLMUnavailableError` exists in `libs/core/llm_provider.py`
- `_generate_chat_response()` can convert some quota/rate-limit failures into
  that exception
- `chat_service.handle_turn()` can convert it into `chat_llm_unavailable`
- the HTTP chat message endpoint can map that sentinel to 503

But several paths still violate the target contract:

- router failures can fall back to `_chat_router_failure_response()`
- boundary decision failures can fall back to `_chat_boundary_failure_response()`
- missing chat providers can return static fallback plans
- network failures are not consistently classified as LLM unavailable
- response normalization can insert `_fallback_chat_response()`
- the UI displays raw HTTP/JSON error text instead of a stable unavailable
  message

## Availability Contract

### Chat Provider Roles

There are two chat LLM roles:

| Role | Purpose | Required when |
|---|---|---|
| `chat_router` | classify the turn, choose route, select action | any turn that is not fully answered by the boundary model |
| `chat_response` | boundary decision and final assistant prose | every conversational answer, and every `answer_or_handoff` boundary decision |

In strict chat mode, a required role being `None` is an unavailable condition.
It is not a reason to use deterministic fallback text.

### Successful Turn Requirements

A successful chat message request must satisfy one of these:

1. An LLM-produced boundary decision returns a direct chat response.
2. An LLM-produced router decision returns a valid non-chat action such as
   `ask_clarification`, `submit_job`, `run_workflow`, or `tool_call`.
3. An LLM-produced router decision returns `respond`, and the response LLM
   produces the final assistant content.

If a model response is malformed, deterministic validation can repair safe,
structural details only when the model call itself succeeded. If repair would
require inventing user-facing assistant text, the response LLM must be called.

### Failure Requirements

The API must raise `LLMUnavailableError` when:

- a required chat provider role is missing
- provider initialization failed and left the role unavailable
- HTTP status is 429, 500, 502, 503, or 504 after retry budget is exhausted
- provider text indicates quota/rate/resource exhaustion
- network errors, DNS errors, connection refused, timeout, or upstream timeout
  occur after retry budget is exhausted
- the provider SDK raises an unavailable/resource/rate/timeout class

Malformed model output is different from unavailable. It should be treated as a
bad gateway or validation failure only if the provider successfully responded.
For the first implementation slice, malformed model output can use existing
router validation behavior, but it must not produce static chat prose.

## Backend Flow

### Provider Layer

Centralize unavailable classification in `libs/core/llm_provider.py`.

`LLMUnavailableError` should be raised by provider implementations, not only by
call sites. Call sites can still defensively wrap exceptions, but the provider
layer is the canonical source.

Recommended helpers:

```python
def is_llm_unavailable_error(exc: BaseException) -> bool: ...

def llm_unavailable_from_exception(exc: BaseException, *, provider: str) -> LLMUnavailableError: ...
```

Provider behavior:

- `HTTPError` with 429/500/502/503/504 after retries raises
  `LLMUnavailableError`
- `URLError`, `TimeoutError`, and SDK timeout/connection exceptions after
  retries raise `LLMUnavailableError`
- known quota/rate/resource-exhausted messages raise `LLMUnavailableError`
- permanent request errors, schema errors, unsupported options, and empty output
  remain `LLMProviderError`

### API Chat Routing

`services/api/app/main.py` should treat all required LLM role failures as hard
failures:

- `_generate_chat_boundary_decision()` raises `LLMUnavailableError` when
  `chat_response` is required but missing or fails
- `_route_chat_turn_with_router()` raises `LLMUnavailableError` when
  `chat_router` is required but missing or fails
- `_route_chat_turn_legacy()` follows the same rule while it exists
- `_generate_chat_response()` raises `LLMUnavailableError` when
  `chat_response` is missing or fails
- `_finalize_chat_turn_plan()` does not insert fallback prose for `respond`
  routes

The previous fallback helpers can remain for non-chat operational messages only,
but they must not be reachable from `POST /chat/sessions/{id}/messages` as a
successful assistant response when the LLM is unavailable.

### Service Layer

`services/api/app/chat_service.py` should preserve current transaction shape:

1. Build the user message record.
2. Attempt classification/execution.
3. If `LLMUnavailableError` occurs, roll back the turn and raise
   `ValueError("chat_llm_unavailable")`.
4. Do not persist an assistant message.

The HTTP endpoint maps `chat_llm_unavailable` to:

```json
{
  "detail": "chat_llm_unavailable"
}
```

with status code `503`.

## UI Behavior

`services/ui/src/app/WorkspaceSurfaceContent.tsx` should parse chat send errors.

When the status is 503 and the response detail is `chat_llm_unavailable`, show:

```text
Chat is not available because the LLM provider is unavailable. Check the provider configuration or retry after quota/rate limits recover.
```

The UI should also:

- restore the user's draft message into the composer
- remove the optimistic message from the visible session
- stop the thinking/loading state
- avoid showing raw JSON like `{"detail":"chat_llm_unavailable"}`

The API proxy may still return `Upstream timeout` or `Upstream unavailable` when
the API service itself is unreachable. That is a separate UI message from
provider-side chat unavailability.

## Tests

### Backend API Tests

Add tests in `services/api/tests/test_chat_api.py`:

- missing router provider returns 503 in router-required mode
- missing response provider returns 503 for conversational response mode
- router provider raising quota/rate/timeout text returns 503
- response provider raising quota/rate/timeout text returns 503
- boundary provider failure in `answer_or_handoff` returns 503
- failed turn does not persist an assistant message

### Provider Tests

Add tests in `libs/core/tests/test_llm_provider.py`:

- retryable exhausted HTTP statuses map to `LLMUnavailableError`
- connection/timeout errors map to `LLMUnavailableError`
- non-retryable request errors remain `LLMProviderError`
- quota/rate/resource text is classified as unavailable

### UI Tests

Add or update frontend tests where available:

- `chat_llm_unavailable` detail is rendered as the friendly unavailable message
- raw JSON error text is not shown
- the draft message is restored after a 503

## Acceptance Criteria

- With chat provider roles unset or failed, `POST /chat/sessions/{id}/messages`
  returns 503.
- With provider quota exhausted, chat returns 503 instead of a static assistant
  answer.
- With provider network timeout after retries, chat returns 503.
- No successful chat response is generated from `_fallback_chat_response()` on
  the chat message endpoint.
- Existing workflow and capability execution can still run after an LLM-produced
  route selects them.
- UI displays a clear "chat is not available" message.

## Rollout Notes

This is intentionally a breaking behavior change for local/demo setups that
relied on static chat fallback. Tests should inject explicit fake LLM providers
when they expect successful chat turns.

For demo mode, use a mock provider that implements the chat LLM interface rather
than bypassing the LLM path. That keeps the product contract intact while still
allowing deterministic test fixtures.
