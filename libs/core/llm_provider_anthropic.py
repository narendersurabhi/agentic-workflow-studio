from __future__ import annotations

import hashlib
from typing import Any, Dict, List, Optional

try:
    import anthropic as _anthropic_sdk
    _ANTHROPIC_AVAILABLE = True
except ImportError:
    _anthropic_sdk = None  # type: ignore[assignment]
    _ANTHROPIC_AVAILABLE = False

from libs.core.llm_provider import (
    CacheSessionRef,
    LLMProvider,
    LLMProviderError,
    LLMRequest,
    LLMResponse,
    PromptBlock,
    Stability,
)


class AnthropicProvider(LLMProvider):
    """LLM provider backed by the Anthropic Messages API with native prompt caching.

    Blocks with Stability.STATIC or Stability.RUN receive an inline
    ``cache_control: {"type": "ephemeral"}`` marker so Anthropic caches them
    for up to 5 minutes.  Cache hits are billed at ~10 % of normal input cost.

    Requires: ``pip install anthropic``
    Env vars: ANTHROPIC_API_KEY, ANTHROPIC_MODEL
    """

    def __init__(
        self,
        api_key: str,
        model: str,
        max_output_tokens: int = 8192,
        temperature: Optional[float] = None,
    ) -> None:
        if not _ANTHROPIC_AVAILABLE:
            raise LLMProviderError(
                "anthropic package is required for AnthropicProvider: pip install anthropic"
            )
        self.client = _anthropic_sdk.Anthropic(api_key=api_key)
        self.model = model
        self.max_output_tokens = max_output_tokens
        self.temperature = temperature

    # ------------------------------------------------------------------
    # Core interface
    # ------------------------------------------------------------------

    def generate_request(self, request: LLMRequest) -> LLMResponse:
        blocks = request.prompt_blocks or [PromptBlock(text=request.prompt, stability=Stability.DYNAMIC)]
        session = CacheSessionRef(provider="anthropic")
        return self.generate_cached(blocks, session, request)

    # Maps reasoning_effort values to Anthropic thinking budget_tokens.
    _THINKING_BUDGETS: Dict[str, int] = {"low": 1024, "high": 10000}

    def generate_cached(
        self,
        blocks: List[PromptBlock],
        session: CacheSessionRef,
        request: LLMRequest,
    ) -> LLMResponse:
        """Send blocks to Anthropic with cache_control markers on stable content.

        STATIC and RUN blocks get ``cache_control: {"type": "ephemeral"}``.
        Anthropic caches the longest matching prefix — the last cache-control marker
        in the message is the effective cache boundary.

        When request.reasoning_effort is "low" or "high", extended thinking is
        enabled with a mapped budget_tokens value. Temperature is omitted in that
        case (Anthropic requirement).
        """
        content: List[Dict[str, Any]] = []
        for block in blocks:
            if not block.text:
                continue
            entry: Dict[str, Any] = {"type": "text", "text": block.text}
            if block.stability in (Stability.STATIC, Stability.RUN):
                entry["cache_control"] = {"type": "ephemeral"}
            content.append(entry)

        if not content:
            raise LLMProviderError("AnthropicProvider: no non-empty prompt blocks")

        thinking_enabled = (
            request.reasoning_effort is not None
            and request.reasoning_effort != "none"
        )
        budget = self._THINKING_BUDGETS.get(request.reasoning_effort or "", 0)

        kwargs: Dict[str, Any] = {
            "model": self.model,
            "max_tokens": request.max_output_tokens or self.max_output_tokens,
            "messages": [{"role": "user", "content": content}],
        }
        if thinking_enabled and budget:
            kwargs["thinking"] = {"type": "enabled", "budget_tokens": budget}
        if request.system_prompt:
            kwargs["system"] = [
                {
                    "type": "text",
                    "text": request.system_prompt,
                    "cache_control": {"type": "ephemeral"},
                }
            ]
        # Temperature must be omitted when extended thinking is enabled.
        if not thinking_enabled:
            temp = request.temperature if request.temperature is not None else self.temperature
            if temp is not None:
                kwargs["temperature"] = temp

        try:
            response = self.client.messages.create(**kwargs)
        except Exception as exc:
            raise LLMProviderError(f"Anthropic API error: {exc}") from exc

        text = "".join(
            block.text for block in response.content if hasattr(block, "text")
        )
        if not text:
            raise LLMProviderError("Anthropic API returned empty output")

        usage = response.usage
        return LLMResponse(
            content=text,
            input_tokens=getattr(usage, "input_tokens", 0),
            output_tokens=getattr(usage, "output_tokens", 0),
            cached_input_tokens=getattr(usage, "cache_read_input_tokens", 0),
            cache_creation_tokens=getattr(usage, "cache_creation_input_tokens", 0),
        )

    # ------------------------------------------------------------------
    # Session lifecycle (inline caching — no separate resource to manage)
    # ------------------------------------------------------------------

    def open_cache_session(
        self,
        job_id: str,
        static_blocks: List[PromptBlock],
    ) -> CacheSessionRef:
        combined = "".join(b.text for b in static_blocks if b.stability == Stability.STATIC)
        pinned_hash = hashlib.sha256(combined.encode()).hexdigest() if combined else None
        return CacheSessionRef(provider="anthropic", pinned_hash=pinned_hash)

    def close_cache_session(self, ref: CacheSessionRef) -> None:
        # Anthropic caches are server-managed TTL; nothing to delete explicitly.
        pass
