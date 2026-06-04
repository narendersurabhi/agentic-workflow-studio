from __future__ import annotations

import time
from typing import List, Optional

import structlog

from libs.core.llm_provider import (
    CacheSessionRef,
    LLMProvider,
    LLMRequest,
    LLMResponse,
    PromptBlock,
)

logger = structlog.get_logger("llm.timing")


class TimingLLMProvider(LLMProvider):
    """Provider wrapper that logs latency and token counts for every LLM call.

    Sits outermost in the provider stack (outside CachingLLMProvider) so it
    measures the full round-trip including cache lookup overhead.

    Emits a structured log line per call:
        component, model, latency_ms, reasoning_effort,
        input_tokens, cached_input_tokens, output_tokens, cache_hit (bool),
        plus any of job_id/session_id/task_id/step_id present in request.metadata.

    Usage:
        provider = TimingLLMProvider(
            CachingLLMProvider(raw_provider, session_store),
            component="chat_response",
            model="claude-3-5-sonnet-20241022",
        )
    """

    def __init__(self, inner: LLMProvider, component: str, model: str = "unknown") -> None:
        self._inner = inner
        self._component = component
        self._model = model

    def generate_request(self, request: LLMRequest) -> LLMResponse:
        started = time.perf_counter()
        response = self._inner.generate_request(request)
        self._log(request, response, time.perf_counter() - started)
        return response

    def generate_cached(
        self,
        blocks: List[PromptBlock],
        session: CacheSessionRef,
        request: LLMRequest,
    ) -> LLMResponse:
        started = time.perf_counter()
        response = self._inner.generate_cached(blocks, session, request)
        self._log(request, response, time.perf_counter() - started)
        return response

    def open_cache_session(
        self, job_id: str, static_blocks: List[PromptBlock]
    ) -> CacheSessionRef:
        return self._inner.open_cache_session(job_id, static_blocks)

    def close_cache_session(self, ref: CacheSessionRef) -> None:
        self._inner.close_cache_session(ref)

    def _log(
        self,
        request: LLMRequest,
        response: LLMResponse,
        elapsed_s: float,
    ) -> None:
        meta = request.metadata or {}
        cache_hit = response.cached_input_tokens > 0
        fields: dict = {
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
            )
            if response.input_tokens
            else 0.0,
        }
        for key in ("job_id", "session_id", "task_id", "step_id"):
            if key in meta:
                fields[key] = meta[key]
        logger.info("llm_call_latency", **fields)
