from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass, field, replace
from enum import Enum
from typing import Any, Dict, Iterator, List, Optional
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
import time


class Stability(Enum):
    """How stable a prompt block's content is across LLM calls."""
    STATIC = "static"    # never changes (rules, schema, full capability catalog)
    RUN = "run"          # stable within one job run (accumulated task summaries)
    DYNAMIC = "dynamic"  # changes every call (goal, payload, current task)


@dataclass
class PromptBlock:
    text: str
    stability: Stability = Stability.DYNAMIC


@dataclass
class CacheSessionRef:
    """Serializable reference to a provider-side cache session.

    For Anthropic/OpenAI: inline caching — handle is None, pinned_hash detects drift.
    For Gemini: handle holds the cachedContent resource name; must be closed at job end.
    """
    provider: str
    handle: Optional[str] = None        # Gemini: cachedContent name; others: None
    pinned_hash: Optional[str] = None   # sha256 of static blocks at session open
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class LLMResponse:
    content: str
    input_tokens: int = 0
    output_tokens: int = 0
    cached_input_tokens: int = 0       # tokens read from provider cache
    cache_creation_tokens: int = 0     # tokens written to provider cache (Anthropic)


@dataclass(frozen=True)
class LLMRequest:
    prompt: str
    system_prompt: Optional[str] = None
    temperature: Optional[float] = None
    max_output_tokens: Optional[int] = None
    metadata: Optional[Dict[str, Any]] = None
    # Structured blocks; if set, overrides prompt for providers that support them.
    prompt_blocks: Optional[List[PromptBlock]] = None
    # Per-turn reasoning budget: "none" | "low" | "high".
    # Providers map this to their native mechanism (Anthropic thinking budget,
    # OpenAI reasoning effort). None means provider default (no thinking).
    reasoning_effort: Optional[str] = None
    # When True, providers that support it will add response_format=json_object
    # to force structured JSON output. Used by generate_request_json_object.
    json_mode: bool = False


_JSON_OBJECT_RESPONSE_INSTRUCTION = (
    "Return exactly one top-level JSON object. Do not wrap it in markdown. "
    "Do not return an array, string, boolean, or explanation."
)


def _append_json_object_instruction(text: Optional[str]) -> str:
    existing = (text or "").strip()
    if _JSON_OBJECT_RESPONSE_INSTRUCTION in existing:
        return existing
    if not existing:
        return _JSON_OBJECT_RESPONSE_INSTRUCTION
    return f"{existing}\n\n{_JSON_OBJECT_RESPONSE_INSTRUCTION}"


def _with_json_object_contract(request: LLMRequest) -> LLMRequest:
    """Return a request that asks providers for a parseable top-level object."""
    prompt_blocks = request.prompt_blocks
    if prompt_blocks:
        if any(_JSON_OBJECT_RESPONSE_INSTRUCTION in block.text for block in prompt_blocks):
            return replace(request, json_mode=True)
        updated_blocks = list(prompt_blocks)
        static_index = next(
            (
                idx
                for idx, block in enumerate(updated_blocks)
                if block.stability == Stability.STATIC
            ),
            -1,
        )
        if static_index >= 0:
            block = updated_blocks[static_index]
            updated_blocks[static_index] = PromptBlock(
                text=_append_json_object_instruction(block.text),
                stability=block.stability,
            )
        else:
            updated_blocks.insert(
                0,
                PromptBlock(
                    text=_JSON_OBJECT_RESPONSE_INSTRUCTION,
                    stability=Stability.STATIC,
                ),
            )
        return replace(request, json_mode=True, prompt_blocks=updated_blocks)

    return replace(
        request,
        json_mode=True,
        system_prompt=_append_json_object_instruction(request.system_prompt),
    )


def _request_prompt_text(request: LLMRequest) -> str:
    if request.prompt_blocks:
        return "\n".join(block.text for block in request.prompt_blocks if block.text)
    return request.prompt


class LLMProviderError(Exception):
    pass


class LLMUnavailableError(LLMProviderError):
    """Raised when the LLM service is temporarily unavailable (quota, rate limit, network)."""
    pass


_RETRYABLE_HTTP_STATUS_CODES = {429, 500, 502, 503, 504}


def is_llm_unavailable_error(exc: BaseException) -> bool:
    if isinstance(exc, LLMUnavailableError):
        return True
    if isinstance(exc, HTTPError):
        return int(exc.code) in _RETRYABLE_HTTP_STATUS_CODES
    msg = str(exc).lower()
    return any(tok in msg for tok in (
        "429", "500", "502", "503", "504",
        "quota", "insufficient_quota", "rate_limit", "rate limit",
        "resource_exhausted", "too many requests",
        "service unavailable", "temporarily unavailable",
        "upstream unavailable", "overloaded", "over capacity",
        "timeout", "timed out", "deadline exceeded",
        "connection error", "connection refused", "connection reset",
        "network", "dns",
    ))


def _is_llm_unavailable_error(exc: BaseException) -> bool:
    return is_llm_unavailable_error(exc)


def _llm_unavailable(provider_label: str, detail: object) -> LLMUnavailableError:
    return LLMUnavailableError(f"{provider_label} unavailable: {detail}")


class LLMProvider:
    def generate(self, prompt: str) -> LLMResponse:  # pragma: no cover - interface
        return self.generate_request(LLMRequest(prompt=prompt))

    def generate_request(self, request: LLMRequest) -> LLMResponse:  # pragma: no cover - interface
        return self.generate(request.prompt)

    def generate_json_object(self, prompt: str) -> Dict[str, Any]:
        return self.generate_request_json_object(LLMRequest(prompt=prompt))

    def generate_request_json_object(self, request: LLMRequest) -> Dict[str, Any]:
        request = _with_json_object_contract(request)
        response = self.generate_request(request)
        return parse_json_object(response.content)

    def open_cache_session(
        self,
        job_id: str,
        static_blocks: List[PromptBlock],
    ) -> CacheSessionRef:
        """Start a cache session for a job run.

        Computes a pinned_hash over STATIC blocks so callers can detect content
        drift between session open and later generate_cached calls.
        """
        combined = "".join(b.text for b in static_blocks if b.stability == Stability.STATIC)
        pinned_hash = hashlib.sha256(combined.encode()).hexdigest() if combined else None
        return CacheSessionRef(provider=self.__class__.__name__, pinned_hash=pinned_hash)

    def close_cache_session(self, ref: CacheSessionRef) -> None:
        """Release any provider-side resources for this session.

        No-op for Anthropic/OpenAI (inline caching).
        Gemini overrides to delete the cachedContent resource.
        """

    def generate_cached(
        self,
        blocks: List[PromptBlock],
        session: CacheSessionRef,
        request: LLMRequest,
    ) -> LLMResponse:
        """Generate using structured prompt blocks.

        Default: concatenate all blocks and call generate_request.
        Provider subclasses override to use their native caching mechanism.
        """
        combined_text = "\n".join(b.text for b in blocks if b.text)
        merged = LLMRequest(
            prompt=combined_text,
            system_prompt=request.system_prompt,
            temperature=request.temperature,
            max_output_tokens=request.max_output_tokens,
            metadata=request.metadata,
            reasoning_effort=request.reasoning_effort,
            json_mode=request.json_mode,
        )
        return self.generate_request(merged)

    def stream_request(self, request: LLMRequest) -> Iterator[str]:
        """Stream response tokens. Default falls back to returning the full response as one chunk."""
        yield self.generate_request(request).content


class MockLLMProvider(LLMProvider):
    def generate_request(self, request: LLMRequest) -> LLMResponse:
        del request
        return LLMResponse(content="Mock response")


class OpenAIProvider(LLMProvider):
    def __init__(
        self,
        api_key: str,
        model: str,
        base_url: str = "https://api.openai.com",
        temperature: Optional[float] = None,
        max_output_tokens: Optional[int] = None,
        timeout_s: float = 30.0,
        max_retries: int = 0,
    ) -> None:
        self.api_key = api_key
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.temperature = temperature
        self.max_output_tokens = max_output_tokens
        self.timeout_s = timeout_s
        self.max_retries = max_retries

    def generate(self, prompt: str) -> LLMResponse:
        return self.generate_request(
            LLMRequest(
                prompt=prompt,
                temperature=self.temperature,
                max_output_tokens=self.max_output_tokens,
            )
        )

    def generate_request(self, request: LLMRequest) -> LLMResponse:
        payload = self._build_payload(request)
        attempts = self.max_retries + 1
        retried_without_temperature = False
        attempt = 0
        while attempt < attempts:
            http_request = self._build_http_request(payload)
            try:
                response_data = self._send_request(http_request)
                text = _extract_output_text(response_data)
                if not text:
                    raise LLMProviderError("OpenAI API returned empty output")
                input_tokens, output_tokens, cached_tokens = _extract_usage_from_response(response_data)
                return LLMResponse(
                    content=text,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    cached_input_tokens=cached_tokens,
                )
            except HTTPError as exc:
                detail = exc.read().decode("utf-8") if exc.fp else str(exc)
                if (
                    "temperature" in payload
                    and not retried_without_temperature
                    and _is_unsupported_temperature_error(detail)
                ):
                    payload.pop("temperature", None)
                    retried_without_temperature = True
                    continue
                if _is_retryable_http_error(exc.code) and attempt < attempts - 1:
                    self._sleep_before_retry(attempt)
                    attempt += 1
                    continue
                if _is_retryable_http_error(exc.code) or is_llm_unavailable_error(exc) or is_llm_unavailable_error(Exception(detail)):
                    raise _llm_unavailable("OpenAI API", detail) from exc
                raise LLMProviderError(f"OpenAI API error: {detail}") from exc
            except (URLError, TimeoutError) as exc:
                if attempt < attempts - 1:
                    self._sleep_before_retry(attempt)
                    attempt += 1
                    continue
                raise _llm_unavailable("OpenAI API", exc) from exc
        raise LLMProviderError("OpenAI API request failed after retries")

    def _build_payload(self, request: LLMRequest) -> Dict[str, Any]:
        payload: Dict[str, Any] = {"model": self.model, "input": _request_prompt_text(request)}
        if request.system_prompt:
            payload["instructions"] = request.system_prompt
        if request.temperature is not None and _model_supports_temperature(self.model):
            payload["temperature"] = request.temperature
        if request.max_output_tokens is not None:
            payload["max_output_tokens"] = request.max_output_tokens
        if request.metadata:
            payload["metadata"] = {
                str(key): str(value) for key, value in request.metadata.items()
            }
        return payload

    def _build_http_request(self, payload: Dict[str, Any]) -> Request:
        return Request(
            f"{self.base_url}/v1/responses",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )

    def _send_request(self, request: Request) -> Dict[str, Any]:
        with urlopen(request, timeout=self.timeout_s) as response:
            body = response.read().decode("utf-8")
        return json.loads(body)

    def _sleep_before_retry(self, attempt: int) -> None:
        time.sleep(min(2**attempt, 8))


class OpenAIChatCompletionsProvider(LLMProvider):
    def __init__(
        self,
        api_key: str,
        model: str,
        base_url: str,
        temperature: Optional[float] = None,
        max_output_tokens: Optional[int] = None,
        timeout_s: float = 30.0,
        max_retries: int = 0,
        provider_label: str = "OpenAI-compatible",
    ) -> None:
        self.api_key = api_key
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.temperature = temperature
        self.max_output_tokens = max_output_tokens
        self.timeout_s = timeout_s
        self.max_retries = max_retries
        self.provider_label = provider_label

    def generate(self, prompt: str) -> LLMResponse:
        return self.generate_request(
            LLMRequest(
                prompt=prompt,
                temperature=self.temperature,
                max_output_tokens=self.max_output_tokens,
            )
        )

    def generate_request(self, request: LLMRequest) -> LLMResponse:
        payload = self._build_payload(request)
        attempts = self.max_retries + 1
        attempt = 0
        while attempt < attempts:
            http_request = self._build_http_request(payload)
            try:
                response_data = self._send_request(http_request)
                text = _extract_chat_completion_text(response_data)
                if not text:
                    raise LLMProviderError(f"{self.provider_label} API returned empty output")
                input_tokens, output_tokens, cached_tokens = _extract_usage_from_chat_completion(response_data)
                return LLMResponse(
                    content=text,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    cached_input_tokens=cached_tokens,
                )
            except HTTPError as exc:
                detail = exc.read().decode("utf-8") if exc.fp else str(exc)
                if _is_retryable_http_error(exc.code) and attempt < attempts - 1:
                    self._sleep_before_retry(attempt)
                    attempt += 1
                    continue
                if _is_retryable_http_error(exc.code) or is_llm_unavailable_error(exc) or is_llm_unavailable_error(Exception(detail)):
                    raise _llm_unavailable(f"{self.provider_label} API", detail) from exc
                raise LLMProviderError(f"{self.provider_label} API error: {detail}") from exc
            except (URLError, TimeoutError) as exc:
                if attempt < attempts - 1:
                    self._sleep_before_retry(attempt)
                    attempt += 1
                    continue
                raise _llm_unavailable(f"{self.provider_label} API", exc) from exc
        raise LLMProviderError(f"{self.provider_label} API request failed after retries")

    def generate_cached(
        self,
        blocks: List[PromptBlock],
        session: CacheSessionRef,
        request: LLMRequest,
    ) -> LLMResponse:
        """Send blocks in stability order to maximise the stable byte prefix.

        OpenAI's automatic prefix cache requires a byte-for-byte identical prefix.
        Emitting STATIC blocks first, then RUN, then DYNAMIC ensures the longest
        possible stable prefix across calls that share the same registry version.
        """
        _order = {Stability.STATIC: 0, Stability.RUN: 1, Stability.DYNAMIC: 2}
        ordered = sorted(blocks, key=lambda b: _order[b.stability])
        combined_text = "\n".join(b.text for b in ordered if b.text)
        merged = LLMRequest(
            prompt=combined_text,
            system_prompt=request.system_prompt,
            temperature=request.temperature,
            max_output_tokens=request.max_output_tokens,
            metadata=request.metadata,
            reasoning_effort=request.reasoning_effort,
            json_mode=request.json_mode,
        )
        return self.generate_request(merged)

    def _build_payload(self, request: LLMRequest) -> Dict[str, Any]:
        messages: list[dict[str, str]] = []
        if request.system_prompt:
            messages.append({"role": "system", "content": request.system_prompt})
        messages.append({"role": "user", "content": _request_prompt_text(request)})
        payload: Dict[str, Any] = {"model": self.model, "messages": messages}
        if request.temperature is not None:
            payload["temperature"] = request.temperature
        if request.max_output_tokens is not None:
            payload["max_tokens"] = request.max_output_tokens
        if request.json_mode:
            payload["response_format"] = {"type": "json_object"}
        if request.metadata and "generativelanguage.googleapis.com" not in self.base_url:
            payload["metadata"] = {
                str(key): str(value) for key, value in request.metadata.items()
            }
        return payload

    def _build_http_request(self, payload: Dict[str, Any]) -> Request:
        return Request(
            f"{self.base_url}/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )

    def _send_request(self, request: Request) -> Dict[str, Any]:
        with urlopen(request, timeout=self.timeout_s) as response:
            body = response.read().decode("utf-8")
        return json.loads(body)

    def _sleep_before_retry(self, attempt: int) -> None:
        time.sleep(min(2**attempt, 8))


def resolve_provider(
    provider_name: str,
    *,
    api_key: Optional[str] = None,
    model: Optional[str] = None,
    base_url: Optional[str] = None,
    temperature: Optional[float] = None,
    max_output_tokens: Optional[int] = None,
    timeout_s: Optional[float] = None,
    max_retries: Optional[int] = None,
) -> LLMProvider:
    name = (provider_name or "mock").lower()
    if name == "mock":
        return MockLLMProvider()
    if name == "openai":
        if not api_key:
            raise ValueError("OPENAI_API_KEY is required when LLM_PROVIDER=openai")
        if not model:
            raise ValueError("OPENAI_MODEL is required when LLM_PROVIDER=openai")
        return OpenAIProvider(
            api_key=api_key,
            model=model,
            base_url=base_url or "https://api.openai.com",
            temperature=temperature,
            max_output_tokens=max_output_tokens,
            timeout_s=timeout_s or 30.0,
            max_retries=max_retries or 0,
        )
    if name == "anthropic":
        from libs.core.llm_provider_anthropic import AnthropicProvider  # lazy import
        anthropic_api_key = os.getenv("ANTHROPIC_API_KEY") or api_key
        anthropic_model = os.getenv("ANTHROPIC_MODEL") or model
        if not anthropic_api_key:
            raise ValueError("ANTHROPIC_API_KEY is required when LLM_PROVIDER=anthropic")
        if not anthropic_model:
            raise ValueError("ANTHROPIC_MODEL is required when LLM_PROVIDER=anthropic")
        return AnthropicProvider(
            api_key=anthropic_api_key,
            model=anthropic_model,
            max_output_tokens=int(max_output_tokens or 8192),
            temperature=temperature,
        )
    if name == "gemini":
        gemini_api_key = os.getenv("GEMINI_API_KEY") or api_key
        gemini_model = os.getenv("GEMINI_MODEL") or model
        gemini_base_url = os.getenv("GEMINI_BASE_URL")
        if not gemini_base_url and base_url and "api.openai.com" not in base_url:
            gemini_base_url = base_url
        if not gemini_api_key:
            raise ValueError("GEMINI_API_KEY is required when LLM_PROVIDER=gemini")
        if not gemini_model:
            raise ValueError("GEMINI_MODEL is required when LLM_PROVIDER=gemini")
        return OpenAIChatCompletionsProvider(
            api_key=gemini_api_key,
            model=gemini_model,
            base_url=gemini_base_url
            or "https://generativelanguage.googleapis.com/v1beta/openai",
            temperature=temperature,
            max_output_tokens=max_output_tokens,
            timeout_s=timeout_s or 30.0,
            max_retries=max_retries or 0,
            provider_label="Gemini",
        )
    if name in {"bedrock", "bedrock-anthropic", "bedrock_anthropic"}:
        from libs.core.llm_provider_bedrock import BedrockAnthropicProvider  # lazy import
        bedrock_model_id = model or os.getenv("BEDROCK_MODEL_ID")
        bedrock_region = os.getenv("AWS_REGION") or os.getenv("AWS_DEFAULT_REGION") or "us-east-1"
        bedrock_verify_ssl = os.getenv("BEDROCK_VERIFY_SSL", "false").strip().lower() not in {
            "0",
            "false",
            "no",
            "off",
        }
        if not bedrock_model_id:
            raise ValueError("BEDROCK_MODEL_ID is required when LLM_PROVIDER=bedrock-anthropic")
        return BedrockAnthropicProvider(
            model_id=bedrock_model_id,
            region=bedrock_region,
            max_output_tokens=int(max_output_tokens or os.getenv("BEDROCK_MAX_OUTPUT_TOKENS") or 8192),
            temperature=temperature,
            timeout_s=timeout_s or 60.0,
            verify_ssl=bedrock_verify_ssl,
        )
    if name in {"openai_compatible", "openai-chat", "chat_completions"}:
        if not api_key:
            raise ValueError("OPENAI_API_KEY is required when LLM_PROVIDER=openai_compatible")
        if not model:
            raise ValueError("OPENAI_MODEL is required when LLM_PROVIDER=openai_compatible")
        if not base_url:
            raise ValueError("OPENAI_BASE_URL is required when LLM_PROVIDER=openai_compatible")
        return OpenAIChatCompletionsProvider(
            api_key=api_key,
            model=model,
            base_url=base_url,
            temperature=temperature,
            max_output_tokens=max_output_tokens,
            timeout_s=timeout_s or 30.0,
            max_retries=max_retries or 0,
            provider_label="OpenAI-compatible",
        )
    raise ValueError(
        f"Unsupported LLM provider '{provider_name}'. "
        "Expected one of: mock, openai, openai_compatible, gemini, anthropic, bedrock-anthropic."
    )


def _extract_output_text(response: Dict[str, Any]) -> str:
    parts: list[str] = []
    for item in response.get("output", []):
        if item.get("type") != "message":
            continue
        for content in item.get("content", []):
            if content.get("type") == "output_text":
                parts.append(content.get("text", ""))
    return "".join(parts).strip()


def _extract_usage_from_response(response: Dict[str, Any]) -> tuple[int, int, int]:
    """Return (input_tokens, output_tokens, cached_tokens) from an OpenAI Responses API response."""
    usage = response.get("usage", {})
    if not isinstance(usage, dict):
        return 0, 0, 0
    input_tokens = int(usage.get("input_tokens", 0))
    output_tokens = int(usage.get("output_tokens", 0))
    details = usage.get("input_tokens_details", {})
    cached_tokens = int(details.get("cached_tokens", 0)) if isinstance(details, dict) else 0
    return input_tokens, output_tokens, cached_tokens


def _extract_chat_completion_text(response: Dict[str, Any]) -> str:
    parts: list[str] = []
    for choice in response.get("choices", []):
        if not isinstance(choice, dict):
            continue
        message = choice.get("message")
        if not isinstance(message, dict):
            continue
        content = message.get("content")
        if isinstance(content, str):
            parts.append(content)
        elif isinstance(content, list):
            for item in content:
                if isinstance(item, dict) and isinstance(item.get("text"), str):
                    parts.append(item["text"])
    return "".join(parts).strip()


def _extract_usage_from_chat_completion(response: Dict[str, Any]) -> tuple[int, int, int]:
    """Return (input_tokens, output_tokens, cached_tokens) from a chat/completions response."""
    usage = response.get("usage", {})
    if not isinstance(usage, dict):
        return 0, 0, 0
    input_tokens = int(usage.get("prompt_tokens", 0))
    output_tokens = int(usage.get("completion_tokens", 0))
    details = usage.get("prompt_tokens_details", {})
    cached_tokens = int(details.get("cached_tokens", 0)) if isinstance(details, dict) else 0
    return input_tokens, output_tokens, cached_tokens


def _model_supports_temperature(model: str) -> bool:
    normalized = (model or "").strip().lower()
    # GPT-5 responses currently reject temperature.
    return not normalized.startswith("gpt-5")


def _is_unsupported_temperature_error(detail: str) -> bool:
    lowered = (detail or "").lower()
    return "unsupported parameter" in lowered and "temperature" in lowered


def _is_retryable_http_error(status_code: int) -> bool:
    return status_code in _RETRYABLE_HTTP_STATUS_CODES


def extract_json_object_text(text: str) -> str:
    content = _strip_markdown_fence(text.strip())
    content = _unwrap_json_string(content)
    if content.startswith("{") and content.endswith("}"):
        return content
    start = content.find("{")
    end = content.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise LLMProviderError("No JSON object found in model response")
    return _unwrap_json_string(content[start : end + 1])


def parse_json_object(text: str) -> Dict[str, Any]:
    queue = [text]
    seen: set[str] = set()
    last_non_object = ""
    while queue:
        candidate = queue.pop(0).strip()
        if not candidate or candidate in seen:
            continue
        seen.add(candidate)
        normalized = _strip_markdown_fence(candidate)
        normalized = _unwrap_json_string(normalized)
        last_non_object = normalized
        try:
            parsed = json.loads(normalized)
        except json.JSONDecodeError:
            try:
                extracted = extract_json_object_text(normalized)
            except LLMProviderError:
                extracted = ""
            if extracted and extracted != normalized:
                queue.append(extracted)
            if '\\"' in normalized:
                queue.append(normalized.replace('\\"', '"'))
            continue
        if isinstance(parsed, dict):
            return parsed
        if isinstance(parsed, list) and len(parsed) == 1 and isinstance(parsed[0], dict):
            return parsed[0]
        if isinstance(parsed, str):
            queue.append(parsed)
    preview = (last_non_object or text or "").replace("\n", "\\n")[:300]
    raise LLMProviderError(
        f"Top-level structured output must be a JSON object: {preview}"
    )


def _strip_markdown_fence(text: str) -> str:
    if not text.startswith("```"):
        return text
    parts = text.split("```")
    if len(parts) <= 1:
        return text
    candidate = parts[1].lstrip()
    if candidate.startswith("json"):
        candidate = candidate[4:].lstrip()
    return candidate


def _unwrap_json_string(text: str) -> str:
    candidate = text.strip()
    for _ in range(2):
        if not (candidate.startswith('"') and candidate.endswith('"')):
            break
        try:
            decoded = json.loads(candidate)
        except json.JSONDecodeError:
            break
        if not isinstance(decoded, str):
            break
        candidate = decoded.strip()
    return candidate
