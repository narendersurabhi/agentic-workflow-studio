from libs.core import models
from services.worker.app import main


def test_infer_task_intent_uses_payload_hint() -> None:
    payload = {
        "intent": "render",
        "description": "Generate something",
        "instruction": "Generate",
        "acceptance_criteria": ["done"],
    }
    assert main._infer_task_intent(payload) == "render"


def test_infer_task_intent_inference_exposes_source_and_confidence() -> None:
    payload = {
        "description": "Step one",
        "instruction": "Handle task",
        "acceptance_criteria": ["done"],
        "goal": "Validate this output against schema",
    }
    inference = main._infer_task_intent_inference(payload)
    assert inference.intent == "validate"
    assert inference.source == "goal_text"
    assert inference.confidence > 0


def test_intent_mismatch_rejects_generate_tool_for_io_task() -> None:
    mismatch = main._intent_mismatch("io", models.ToolIntent.generate, "llm_generate")
    assert mismatch == "tool_intent_mismatch:llm_generate:generate:io"
