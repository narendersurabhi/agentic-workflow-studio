from libs.core import intent_contract


def test_infer_task_intent_for_task_uses_goal_when_task_text_generic() -> None:
    inferred = intent_contract.infer_task_intent_for_task(
        explicit_intent=None,
        description="Step one",
        instruction="Handle this task.",
        acceptance_criteria=["Done"],
        goal_text="Validate the generated document against schema rules.",
    )
    assert inferred == "validate"


def test_infer_task_intent_for_payload_uses_nested_job_goal() -> None:
    inferred = intent_contract.infer_task_intent_for_payload(
        {
            "description": "Step one",
            "instruction": "Handle this task.",
            "acceptance_criteria": ["Done"],
            "job": {"goal": "Render a PDF from the approved document spec."},
        }
    )
    assert inferred == "render"


def test_infer_task_intent_explicit_value_wins_over_goal() -> None:
    inferred = intent_contract.infer_task_intent_for_task(
        explicit_intent="io",
        description="Generate report",
        instruction="Generate report",
        acceptance_criteria=["Done"],
        goal_text="Generate a report document.",
    )
    assert inferred == "io"


def test_infer_task_intent_with_metadata_reports_source_and_confidence() -> None:
    inference = intent_contract.infer_task_intent_for_task_with_metadata(
        explicit_intent=None,
        description="Step one",
        instruction="Handle this task.",
        acceptance_criteria=["Done"],
        goal_text="Render the final output as PDF.",
    )
    assert inference.intent == "render"
    assert inference.source == "goal_text"
    assert inference.confidence > 0
