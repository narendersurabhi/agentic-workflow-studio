from __future__ import annotations

import io
import json
import uuid
from urllib.error import HTTPError

from urllib.error import URLError

from libs.core.llm_provider import (
    CacheSessionRef,
    LLMProvider,
    LLMProviderError,
    LLMRequest,
    LLMResponse,
    LLMUnavailableError,
    OpenAIChatCompletionsProvider,
    OpenAIProvider,
    PromptBlock,
    Stability,
    parse_json_object,
)
from libs.core import llm_provider as llm_provider_module


class _FakeHTTPResponse:
    def __init__(self, payload: dict) -> None:
        self._raw = json.dumps(payload).encode("utf-8")

    def read(self) -> bytes:
        return self._raw

    def __enter__(self) -> "_FakeHTTPResponse":
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        return False


def _success_payload() -> dict:
    return {
        "output": [
            {
                "type": "message",
                "content": [{"type": "output_text", "text": '{"ok":true}'}],
            }
        ]
    }


def test_openai_provider_omits_temperature_for_gpt5(monkeypatch) -> None:
    captured_payloads: list[dict] = []

    def _fake_urlopen(request, timeout=0):  # type: ignore[no-untyped-def]
        body = json.loads(request.data.decode("utf-8"))
        captured_payloads.append(body)
        return _FakeHTTPResponse(_success_payload())

    monkeypatch.setattr(llm_provider_module, "urlopen", _fake_urlopen)

    provider = OpenAIProvider(
        api_key="test-key",
        model="gpt-5-mini",
        temperature=0.7,
    )
    response = provider.generate("hello")
    assert response.content == '{"ok":true}'
    assert len(captured_payloads) == 1
    assert "temperature" not in captured_payloads[0]


def test_openai_provider_retries_without_temperature_on_unsupported_error(monkeypatch) -> None:
    captured_payloads: list[dict] = []
    state = {"count": 0}

    def _fake_urlopen(request, timeout=0):  # type: ignore[no-untyped-def]
        body = json.loads(request.data.decode("utf-8"))
        captured_payloads.append(body)
        if state["count"] == 0:
            state["count"] += 1
            error_body = b'{"error":{"message":"Unsupported parameter: \'temperature\' is not supported with this model."}}'
            raise HTTPError(
                url="https://api.openai.com/v1/responses",
                code=400,
                msg="Bad Request",
                hdrs=None,
                fp=io.BytesIO(error_body),
            )
        return _FakeHTTPResponse(_success_payload())

    monkeypatch.setattr(llm_provider_module, "urlopen", _fake_urlopen)

    provider = OpenAIProvider(
        api_key="test-key",
        model="gpt-4.1-mini",
        temperature=0.2,
        max_retries=0,
    )
    response = provider.generate("hello")
    assert response.content == '{"ok":true}'
    assert len(captured_payloads) == 2
    assert captured_payloads[0]["temperature"] == 0.2
    assert "temperature" not in captured_payloads[1]


def test_openai_provider_builds_request_payload_from_llm_request() -> None:
    provider = OpenAIProvider(
        api_key="test-key",
        model="gpt-4.1-mini",
        temperature=0.4,
        max_output_tokens=256,
    )

    payload = provider._build_payload(  # type: ignore[attr-defined]
        LLMRequest(
            prompt="hello",
            system_prompt="system message",
            temperature=0.1,
            max_output_tokens=42,
            metadata={"component": "coder", "goal_len": 9},
        )
    )

    assert payload == {
        "model": "gpt-4.1-mini",
        "input": "hello",
        "instructions": "system message",
        "temperature": 0.1,
        "max_output_tokens": 42,
        "metadata": {"component": "coder", "goal_len": "9"},
    }


def test_openai_chat_completions_provider_builds_messages_payload() -> None:
    provider = OpenAIChatCompletionsProvider(
        api_key="test-key",
        model="gemini-2.5-flash",
        base_url="https://generativelanguage.googleapis.com/v1beta/openai",
        temperature=0.3,
        max_output_tokens=128,
        provider_label="Gemini",
    )

    payload = provider._build_payload(  # type: ignore[attr-defined]
        LLMRequest(
            prompt="hello",
            system_prompt="system message",
            temperature=0.1,
            max_output_tokens=42,
            metadata={"component": "planner"},
        )
    )

    assert payload == {
        "model": "gemini-2.5-flash",
        "messages": [
            {"role": "system", "content": "system message"},
            {"role": "user", "content": "hello"},
        ],
        "temperature": 0.1,
        "max_tokens": 42,
    }


def test_openai_chat_completions_provider_keeps_metadata_for_non_gemini_base_url() -> None:
    provider = OpenAIChatCompletionsProvider(
        api_key="test-key",
        model="gpt-4.1-mini",
        base_url="https://api.openai.com/v1",
        temperature=0.3,
        max_output_tokens=128,
    )

    payload = provider._build_payload(  # type: ignore[attr-defined]
        LLMRequest(
            prompt="hello",
            system_prompt="system message",
            temperature=0.1,
            max_output_tokens=42,
            metadata={"component": "planner"},
        )
    )

    assert payload == {
        "model": "gpt-4.1-mini",
        "messages": [
            {"role": "system", "content": "system message"},
            {"role": "user", "content": "hello"},
        ],
        "temperature": 0.1,
        "max_tokens": 42,
        "metadata": {"component": "planner"},
    }


def test_resolve_provider_supports_gemini_env(monkeypatch) -> None:
    monkeypatch.setenv("GEMINI_API_KEY", "gemini-key")
    monkeypatch.setenv("GEMINI_MODEL", "gemini-2.5-flash")
    monkeypatch.delenv("GEMINI_BASE_URL", raising=False)

    provider = llm_provider_module.resolve_provider(
        "gemini",
        api_key="openai-key",
        model="gpt-5-mini",
        base_url="https://api.openai.com",
    )

    assert isinstance(provider, OpenAIChatCompletionsProvider)
    assert provider.api_key == "gemini-key"
    assert provider.model == "gemini-2.5-flash"
    assert provider.base_url == "https://generativelanguage.googleapis.com/v1beta/openai"


def test_resolve_provider_bedrock_prefers_explicit_role_model(monkeypatch) -> None:
    from libs.core import llm_provider_bedrock

    verify_values: list[bool] = []

    def _fake_init(
        self,
        model_id,
        region="us-east-1",
        max_output_tokens=8192,
        temperature=None,
        timeout_s=60.0,
        verify_ssl=True,
    ):
        del region, max_output_tokens, temperature, timeout_s
        verify_values.append(verify_ssl)
        self.model_id = model_id

    monkeypatch.setenv("BEDROCK_MODEL_ID", "us.anthropic.claude-sonnet-4-6")
    monkeypatch.setenv("BEDROCK_VERIFY_SSL", "false")
    monkeypatch.setattr(
        llm_provider_bedrock.BedrockAnthropicProvider,
        "__init__",
        _fake_init,
    )

    provider = llm_provider_module.resolve_provider(
        "bedrock-anthropic",
        model="us.anthropic.claude-haiku-4-5-20251001-v1:0",
    )

    assert isinstance(provider, llm_provider_bedrock.BedrockAnthropicProvider)
    assert provider.model_id == "us.anthropic.claude-haiku-4-5-20251001-v1:0"

    alias_provider = llm_provider_module.resolve_provider(
        "bedrock",
        model="us.anthropic.claude-sonnet-4-6",
    )

    assert isinstance(alias_provider, llm_provider_bedrock.BedrockAnthropicProvider)
    assert alias_provider.model_id == "us.anthropic.claude-sonnet-4-6"
    assert verify_values == [False, False]


def test_resolve_provider_rejects_unknown_provider() -> None:
    try:
        llm_provider_module.resolve_provider("bedrok", model="test-model")
    except ValueError as exc:
        assert "Unsupported LLM provider" in str(exc)
        assert "bedrok" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("Expected ValueError")


def test_bedrock_provider_error_includes_model_and_region(monkeypatch) -> None:
    from libs.core import llm_provider_bedrock

    class _FakeBedrockRuntime:
        def invoke_model(self, **kwargs):  # type: ignore[no-untyped-def]
            del kwargs
            raise RuntimeError("AccessDeniedException: model is marked as Legacy")

    class _FakeBoto3:
        class session:
            @staticmethod
            def Config(**kwargs):  # type: ignore[no-untyped-def]
                return kwargs

        @staticmethod
        def client(*args, **kwargs):  # type: ignore[no-untyped-def]
            del args, kwargs
            return _FakeBedrockRuntime()

    monkeypatch.setattr(llm_provider_bedrock, "_BOTO3_AVAILABLE", True)
    monkeypatch.setattr(llm_provider_bedrock, "_boto3", _FakeBoto3)

    provider = llm_provider_bedrock.BedrockAnthropicProvider(
        model_id="us.anthropic.claude-sonnet-4-6",
        region="us-east-1",
        verify_ssl=False,
    )

    try:
        provider.generate_request(LLMRequest(prompt="hello"))
    except LLMProviderError as exc:
        message = str(exc)
        assert "model_id=us.anthropic.claude-sonnet-4-6" in message
        assert "region=us-east-1" in message
        assert "verify_ssl=false" in message
        assert "Legacy" in message
    else:  # pragma: no cover
        raise AssertionError("Expected LLMProviderError")


def test_resolve_provider_supports_openai_compatible_endpoint() -> None:
    provider = llm_provider_module.resolve_provider(
        "openai_compatible",
        api_key="custom-key",
        model="fine-tuned-model",
        base_url="https://llm.example.test/v1",
    )

    assert isinstance(provider, OpenAIChatCompletionsProvider)
    assert provider.api_key == "custom-key"
    assert provider.model == "fine-tuned-model"
    assert provider.base_url == "https://llm.example.test/v1"


def test_openai_provider_retries_retryable_connection_error(monkeypatch) -> None:
    state = {"count": 0}
    sleeps: list[int] = []

    def _fake_urlopen(request, timeout=0):  # type: ignore[no-untyped-def]
        del request, timeout
        if state["count"] == 0:
            state["count"] += 1
            raise URLError("temporary network failure")
        return _FakeHTTPResponse(_success_payload())

    monkeypatch.setattr(llm_provider_module, "urlopen", _fake_urlopen)
    monkeypatch.setattr(llm_provider_module.time, "sleep", lambda seconds: sleeps.append(seconds))

    provider = OpenAIProvider(
        api_key="test-key",
        model="gpt-4.1-mini",
        max_retries=1,
    )

    response = provider.generate("hello")

    assert response.content == '{"ok":true}'
    assert sleeps == [1]


def test_openai_provider_maps_exhausted_retryable_http_error_to_unavailable(monkeypatch) -> None:
    def _fake_urlopen(request, timeout=0):  # type: ignore[no-untyped-def]
        del request, timeout
        raise HTTPError(
            url="https://api.openai.com/v1/responses",
            code=503,
            msg="Service Unavailable",
            hdrs=None,
            fp=io.BytesIO(b'{"error":{"message":"service unavailable"}}'),
        )

    monkeypatch.setattr(llm_provider_module, "urlopen", _fake_urlopen)

    provider = OpenAIProvider(api_key="test-key", model="gpt-4.1-mini")

    try:
        provider.generate("hello")
    except LLMUnavailableError as exc:
        assert "OpenAI API unavailable" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("Expected LLMUnavailableError")


def test_openai_provider_maps_exhausted_connection_error_to_unavailable(monkeypatch) -> None:
    def _fake_urlopen(request, timeout=0):  # type: ignore[no-untyped-def]
        del request, timeout
        raise URLError("connection refused")

    monkeypatch.setattr(llm_provider_module, "urlopen", _fake_urlopen)

    provider = OpenAIProvider(api_key="test-key", model="gpt-4.1-mini")

    try:
        provider.generate("hello")
    except LLMUnavailableError as exc:
        assert "OpenAI API unavailable" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("Expected LLMUnavailableError")


def test_openai_provider_keeps_non_retryable_http_error_as_provider_error(monkeypatch) -> None:
    def _fake_urlopen(request, timeout=0):  # type: ignore[no-untyped-def]
        del request, timeout
        raise HTTPError(
            url="https://api.openai.com/v1/responses",
            code=400,
            msg="Bad Request",
            hdrs=None,
            fp=io.BytesIO(b'{"error":{"message":"invalid request"}}'),
        )

    monkeypatch.setattr(llm_provider_module, "urlopen", _fake_urlopen)

    provider = OpenAIProvider(api_key="test-key", model="gpt-4.1-mini")

    try:
        provider.generate("hello")
    except LLMUnavailableError:  # pragma: no cover
        raise AssertionError("Expected non-retryable errors to remain LLMProviderError")
    except LLMProviderError as exc:
        assert "OpenAI API error" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("Expected LLMProviderError")


def test_unavailable_text_classifier_matches_quota_and_timeout() -> None:
    assert llm_provider_module.is_llm_unavailable_error(Exception("quota exceeded"))
    assert llm_provider_module.is_llm_unavailable_error(Exception("upstream timeout"))
    assert not llm_provider_module.is_llm_unavailable_error(
        Exception("SSL validation failed: unable to get local issuer certificate")
    )
    assert not llm_provider_module.is_llm_unavailable_error(Exception("invalid request"))


def test_openai_provider_raises_for_empty_output(monkeypatch) -> None:
    def _fake_urlopen(request, timeout=0):  # type: ignore[no-untyped-def]
        del request, timeout
        return _FakeHTTPResponse({"output": []})

    monkeypatch.setattr(llm_provider_module, "urlopen", _fake_urlopen)

    provider = OpenAIProvider(api_key="test-key", model="gpt-4.1-mini")

    try:
        provider.generate("hello")
    except LLMProviderError as exc:
        assert str(exc) == "OpenAI API returned empty output"
    else:  # pragma: no cover
        raise AssertionError("Expected LLMProviderError")


def test_parse_json_object_extracts_fenced_json_object() -> None:
    payload = parse_json_object('```json\n{"ok": true, "count": 2}\n```')

    assert payload == {"ok": True, "count": 2}


def test_parse_json_object_accepts_double_encoded_json_string() -> None:
    payload = parse_json_object('"{\\"ok\\": true, \\"count\\": 2}"')

    assert payload == {"ok": True, "count": 2}


def test_parse_json_object_accepts_singleton_list_with_object() -> None:
    payload = parse_json_object('[{"ok": true}]')

    assert payload == {"ok": True}


def test_generate_request_json_object_enforces_top_level_object_contract() -> None:
    captured: dict[str, LLMRequest] = {}

    class _Provider(LLMProvider):
        def generate_request(self, request: LLMRequest) -> LLMResponse:
            captured["request"] = request
            return LLMResponse(content='{"ok": true}')

    payload = _Provider().generate_request_json_object(
        LLMRequest(
            prompt="hello",
            system_prompt="Return JSON only.",
        )
    )

    assert payload == {"ok": True}
    assert captured["request"].json_mode is True
    assert captured["request"].prompt == "hello"
    assert "top-level JSON object" in (captured["request"].system_prompt or "")


def test_generate_request_json_object_enforces_contract_on_prompt_blocks() -> None:
    captured: dict[str, LLMRequest] = {}

    class _Provider(LLMProvider):
        def generate_request(self, request: LLMRequest) -> LLMResponse:
            captured["request"] = request
            return LLMResponse(content='{"ok": true}')

    _Provider().generate_request_json_object(
        LLMRequest(
            prompt="",
            prompt_blocks=[
                PromptBlock(text="Return JSON only.", stability=Stability.STATIC),
                PromptBlock(text='{"input": "hello"}', stability=Stability.DYNAMIC),
            ],
        )
    )

    request = captured["request"]
    assert request.json_mode is True
    assert request.prompt_blocks is not None
    assert "top-level JSON object" in request.prompt_blocks[0].text
    assert request.prompt_blocks[1].text == '{"input": "hello"}'


def test_generate_cached_preserves_structured_request_fields() -> None:
    captured: dict[str, LLMRequest] = {}

    class _Provider(LLMProvider):
        def generate_request(self, request: LLMRequest) -> LLMResponse:
            captured["request"] = request
            return LLMResponse(content="ok")

    _Provider().generate_cached(
        [PromptBlock(text="hello", stability=Stability.DYNAMIC)],
        CacheSessionRef(provider="test"),
        LLMRequest(prompt="", json_mode=True, reasoning_effort="low"),
    )

    request = captured["request"]
    assert request.prompt == "hello"
    assert request.json_mode is True
    assert request.reasoning_effort == "low"


def test_openai_chat_cached_requests_preserve_json_mode() -> None:
    captured: dict[str, LLMRequest] = {}

    class _Provider(OpenAIChatCompletionsProvider):
        def generate_request(self, request: LLMRequest) -> LLMResponse:
            captured["request"] = request
            return LLMResponse(content="ok")

    _Provider(
        api_key="test-key", model="gpt-test", base_url="https://example.test"
    ).generate_cached(
        [PromptBlock(text="hello", stability=Stability.DYNAMIC)],
        CacheSessionRef(provider="test"),
        LLMRequest(prompt="", json_mode=True, reasoning_effort="low"),
    )

    request = captured["request"]
    assert request.prompt == "hello"
    assert request.json_mode is True
    assert request.reasoning_effort == "low"


def test_openai_chat_payload_uses_prompt_blocks_and_json_mode() -> None:
    provider = OpenAIChatCompletionsProvider(
        api_key="test-key",
        model="gpt-test",
        base_url="https://example.test",
    )

    payload = provider._build_payload(
        LLMRequest(
            prompt="",
            prompt_blocks=[
                PromptBlock(text="System rules", stability=Stability.STATIC),
                PromptBlock(text="User payload", stability=Stability.DYNAMIC),
            ],
            json_mode=True,
        )
    )

    assert payload["messages"][-1]["content"] == "System rules\nUser payload"
    assert payload["response_format"] == {"type": "json_object"}


def test_generate_json_object_uses_generate_compatibility_path() -> None:
    class _LegacyProvider(LLMProvider):
        def generate(self, prompt: str) -> LLMResponse:
            assert prompt == "hello"
            return LLMResponse(content='{"ok": true}')

    payload = _LegacyProvider().generate_json_object("hello")

    assert payload == {"ok": True}


def test_resolve_provider_cached_reuses_instance_for_same_key() -> None:
    key_model = f"mock-model-{uuid.uuid4()}"

    first = llm_provider_module.resolve_provider_cached("mock", key_model)
    second = llm_provider_module.resolve_provider_cached("mock", key_model)

    assert first is second


def test_resolve_provider_cached_builds_separate_instances_per_key() -> None:
    suffix = uuid.uuid4()

    first = llm_provider_module.resolve_provider_cached("mock", f"model-a-{suffix}")
    second = llm_provider_module.resolve_provider_cached("mock", f"model-b-{suffix}")

    assert first is not second


def test_resolve_provider_cached_sources_openai_credentials_from_env(monkeypatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "cached-openai-key")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://example.invalid/v1")
    unique_model = f"gpt-cached-{uuid.uuid4()}"

    provider = llm_provider_module.resolve_provider_cached("openai", unique_model)

    assert provider.api_key == "cached-openai-key"
    assert provider.model == unique_model
    assert provider.base_url == "https://example.invalid/v1"


def test_resolve_provider_cached_openai_falls_back_to_env_model_when_unset(monkeypatch) -> None:
    env_default_model = f"gpt-env-default-{uuid.uuid4()}"
    monkeypatch.setenv("OPENAI_API_KEY", "cached-openai-key")
    monkeypatch.setenv("OPENAI_MODEL", env_default_model)

    provider = llm_provider_module.resolve_provider_cached("openai")

    assert provider.model == env_default_model
