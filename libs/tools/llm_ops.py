"""Plain-text LLM generation tool handlers (llm_generate / llm_generate_with_context).

Moved out of libs/core/tool_registry.py (Phase 5 of the harness/MCP/tool-manager/
memory layering). Names are unchanged from their prior location; only the file
moved.
"""

from __future__ import annotations

import json
import math
import os
from typing import Any, Dict, Optional

from libs.core.llm_provider import LLMProvider, LLMRequest
from libs.framework.tool_runtime import ToolExecutionError


def _resolve_llm_timeout_s(provider: Optional[LLMProvider]) -> int:
    if provider is not None and hasattr(provider, "timeout_s"):
        try:
            return max(1, int(math.ceil(getattr(provider, "timeout_s"))))
        except (TypeError, ValueError):
            pass
    env_timeout = os.getenv("OPENAI_TIMEOUT_S")
    if env_timeout:
        try:
            return max(1, int(math.ceil(float(env_timeout))))
        except ValueError:
            return 30
    return 30


def _resolve_llm_iterative_tool_timeout_s(provider: Optional[LLMProvider]) -> int:
    base = _resolve_llm_timeout_s(provider)
    return min(900, max(60, base * 3))


def _llm_generate(payload: Dict[str, Any], provider: LLMProvider) -> Dict[str, Any]:
    prompt = payload.get("text") or payload.get("prompt") or ""
    meta: Dict[str, Any] = {
        "component": "tools",
        "tool": "llm_generate",
        "operation": "generate_text",
        "prompt_len": len(prompt),
    }
    job_id = payload.get("job_id")
    if job_id:
        meta["job_id"] = job_id
    response = provider.generate_request(LLMRequest(prompt=prompt, metadata=meta))
    return {
        "text": response.content,
        "usage": {
            "prompt_tokens": response.input_tokens,
            "completion_tokens": response.output_tokens,
            "cached_tokens": response.cached_input_tokens,
            "cache_write_tokens": response.cache_creation_tokens,
        },
    }


def _render_prompt_with_context(prompt: str, context_value: Any) -> str:
    if context_value is None:
        return prompt
    if isinstance(context_value, str):
        context_text = context_value.strip()
        if not context_text:
            return prompt
    elif isinstance(context_value, (dict, list)):
        if not context_value:
            return prompt
        try:
            context_text = json.dumps(context_value, indent=2, ensure_ascii=True)
        except (TypeError, ValueError):
            context_text = str(context_value)
    else:
        context_text = str(context_value).strip()
        if not context_text:
            return prompt
    return f"{prompt}\n\nContext:\n{context_text}"


def _llm_generate_with_context(payload: Dict[str, Any], provider: LLMProvider) -> Dict[str, Any]:
    prompt = str(payload.get("prompt") or "").strip()
    if not prompt:
        raise ToolExecutionError("missing_prompt")
    context_value = payload.get("context")
    prompt_with_context = _render_prompt_with_context(prompt, context_value)
    system_prompt = payload.get("system_prompt")
    if not isinstance(system_prompt, str) or not system_prompt.strip():
        system_prompt = None
    raw_temperature = payload.get("temperature")
    temperature = (
        raw_temperature
        if isinstance(raw_temperature, (int, float)) and not isinstance(raw_temperature, bool)
        else None
    )
    raw_max_tokens = payload.get("max_output_tokens")
    max_output_tokens = (
        raw_max_tokens
        if isinstance(raw_max_tokens, int) and not isinstance(raw_max_tokens, bool)
        else None
    )
    meta: Dict[str, Any] = {
        "component": "tools",
        "tool": "llm_generate_with_context",
        "operation": "generate_text_with_context",
        "prompt_len": len(prompt),
        "has_context": context_value is not None,
    }
    job_id = payload.get("job_id")
    if job_id:
        meta["job_id"] = job_id
    response = provider.generate_request(
        LLMRequest(
            prompt=prompt_with_context,
            system_prompt=system_prompt,
            temperature=float(temperature) if temperature is not None else None,
            max_output_tokens=max_output_tokens,
            metadata=meta,
        )
    )
    return {
        "text": response.content,
        "usage": {
            "prompt_tokens": response.input_tokens,
            "completion_tokens": response.output_tokens,
            "cached_tokens": response.cached_input_tokens,
            "cache_write_tokens": response.cache_creation_tokens,
        },
    }
