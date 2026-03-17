import json

from libs.core.llm_provider import LLMProvider, LLMRequest, LLMResponse
from libs.tools.document_spec_iterative import (
    _llm_generate_runbook_document_spec,
    _llm_improve_runbook_document_spec,
)


class _JsonProvider(LLMProvider):
    def __init__(self, output: dict[str, object]) -> None:
        self.output = output
        self.requests: list[LLMRequest] = []

    def generate_request(self, request: LLMRequest) -> LLMResponse:
        self.requests.append(request)
        return LLMResponse(content=json.dumps(self.output))


def test_llm_generate_runbook_document_spec_uses_request_json_object() -> None:
    provider = _JsonProvider({"title": "Runbook", "blocks": []})

    result = _llm_generate_runbook_document_spec(
        {"job": {"service": "api", "owner": "platform"}},
        provider,
        sanitize_document_spec=lambda spec: {**spec, "sanitized": True},
    )

    assert result["document_spec"]["title"] == "Runbook"
    assert result["document_spec"]["sanitized"] is True
    assert provider.requests
    assert provider.requests[0].metadata == {
        "component": "tools",
        "tool": "llm_iterative_improve_runbook_spec",
        "operation": "generate_runbook_document_spec",
        "job_keys": 2,
        "allowed_block_types": 7,
    }


def test_llm_improve_runbook_document_spec_uses_request_json_object() -> None:
    provider = _JsonProvider({"title": "Improved Runbook", "blocks": []})

    result = _llm_improve_runbook_document_spec(
        {
            "document_spec": {"title": "Draft"},
            "validation_report": {"errors": [{"message": "missing blocks"}]},
            "job": {"service": "api"},
            "allowed_block_types": ["heading", "paragraph"],
        },
        provider,
        sanitize_document_spec=lambda spec: {**spec, "sanitized": True},
    )

    assert result["document_spec"]["title"] == "Improved Runbook"
    assert result["document_spec"]["sanitized"] is True
    assert provider.requests
    assert provider.requests[0].metadata == {
        "component": "tools",
        "tool": "llm_iterative_improve_runbook_spec",
        "operation": "improve_runbook_document_spec",
        "document_spec_keys": 1,
        "validation_error_count": 1,
        "allowed_block_types": 2,
    }
