from __future__ import annotations

import hashlib
import json
from typing import Any, Dict, List, Optional

try:
    import boto3 as _boto3
    _BOTO3_AVAILABLE = True
except ImportError:
    _boto3 = None  # type: ignore[assignment]
    _BOTO3_AVAILABLE = False

from libs.core.llm_provider import (
    CacheSessionRef,
    LLMUnavailableError,
    LLMProvider,
    LLMProviderError,
    LLMRequest,
    LLMResponse,
    PromptBlock,
    Stability,
    is_llm_unavailable_error,
)


class BedrockAnthropicProvider(LLMProvider):
    """LLM provider backed by AWS Bedrock bedrock-runtime using Anthropic models.

    Uses boto3 invoke_model (synchronous). Auth is handled by the boto3 credential
    chain (IAM role, AWS_PROFILE, env vars — no explicit API key needed).

    Prompt caching: Bedrock strips Anthropic cache_control markers, so
    cached_input_tokens will always be 0. Use AnthropicProvider (direct) for
    cache-sensitive paths.

    Extended thinking: supported via the same thinking param as Anthropic direct.
    Temperature must be omitted when thinking is enabled.

    Requires: ``pip install boto3``
    Env vars: BEDROCK_MODEL_ID, AWS_REGION (and standard boto3 credential vars)
    """

    # Maps reasoning_effort values to Anthropic thinking budget_tokens.
    _THINKING_BUDGETS: Dict[str, int] = {"low": 1024, "high": 10000}

    def __init__(
        self,
        model_id: str,
        region: str = "us-east-1",
        max_output_tokens: int = 8192,
        temperature: Optional[float] = None,
        timeout_s: float = 60.0,
    ) -> None:
        if not _BOTO3_AVAILABLE:
            raise LLMProviderError(
                "boto3 package is required for BedrockAnthropicProvider: pip install boto3"
            )
        self.model_id = model_id
        self.max_output_tokens = max_output_tokens
        self.temperature = temperature
        self.client = _boto3.client(
            "bedrock-runtime",
            region_name=region,
            config=_boto3.session.Config(  # type: ignore[attr-defined]
                connect_timeout=timeout_s,
                read_timeout=timeout_s,
            ),
        )

    def generate_request(self, request: LLMRequest) -> LLMResponse:
        blocks = request.prompt_blocks or [PromptBlock(text=request.prompt, stability=Stability.DYNAMIC)]
        session = CacheSessionRef(provider="bedrock-anthropic")
        return self.generate_cached(blocks, session, request)

    def generate_cached(
        self,
        blocks: List[PromptBlock],
        session: CacheSessionRef,
        request: LLMRequest,
    ) -> LLMResponse:
        """Invoke Bedrock with Anthropic Messages format.

        cache_control markers are intentionally omitted — Bedrock ignores them
        and including them adds noise to the wire payload.
        """
        content: List[Dict[str, Any]] = []
        for block in blocks:
            if not block.text:
                continue
            content.append({"type": "text", "text": block.text})

        if not content:
            raise LLMProviderError("BedrockAnthropicProvider: no non-empty prompt blocks")

        thinking_enabled = (
            request.reasoning_effort is not None
            and request.reasoning_effort != "none"
        )
        budget = self._THINKING_BUDGETS.get(request.reasoning_effort or "", 0)

        body: Dict[str, Any] = {
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens": request.max_output_tokens or self.max_output_tokens,
            "messages": [{"role": "user", "content": content}],
        }
        if thinking_enabled and budget:
            body["thinking"] = {"type": "enabled", "budget_tokens": budget}
        if request.system_prompt:
            body["system"] = request.system_prompt
        # Temperature must be omitted when extended thinking is enabled.
        if not thinking_enabled:
            temp = request.temperature if request.temperature is not None else self.temperature
            if temp is not None:
                body["temperature"] = temp

        try:
            raw = self.client.invoke_model(
                modelId=self.model_id,
                body=json.dumps(body),
                contentType="application/json",
                accept="application/json",
            )
            response_body = json.loads(raw["body"].read())
        except Exception as exc:
            if is_llm_unavailable_error(exc):
                raise LLMUnavailableError(f"Bedrock API unavailable: {exc}") from exc
            raise LLMProviderError(f"Bedrock API error: {exc}") from exc

        text = "".join(
            block.get("text", "")
            for block in response_body.get("content", [])
            if block.get("type") == "text"
        )
        if not text:
            raise LLMProviderError("Bedrock API returned empty output")

        usage = response_body.get("usage", {})
        return LLMResponse(
            content=text,
            input_tokens=usage.get("input_tokens", 0),
            output_tokens=usage.get("output_tokens", 0),
            # Bedrock does not return cache token counts for Anthropic models.
            cached_input_tokens=0,
            cache_creation_tokens=0,
        )

    def open_cache_session(
        self,
        job_id: str,
        static_blocks: List[PromptBlock],
    ) -> CacheSessionRef:
        # No server-side caching on Bedrock, but compute pinned_hash so the
        # CachingLLMProvider contract is satisfied.
        combined = "".join(b.text for b in static_blocks if b.stability == Stability.STATIC)
        pinned_hash = hashlib.sha256(combined.encode()).hexdigest() if combined else None
        return CacheSessionRef(provider="bedrock-anthropic", pinned_hash=pinned_hash)

    def close_cache_session(self, ref: CacheSessionRef) -> None:
        pass
