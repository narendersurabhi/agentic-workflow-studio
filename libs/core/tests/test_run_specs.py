from libs.core import execution_contracts, models, run_specs

# _document_capability_registry and test_plan_to_run_spec_accepts_capability_requests_without_tool_requests
# removed: depended on capability_registry, removed with the tools framework.


def test_plan_to_run_spec_roundtrips_execution_gate() -> None:
    plan = models.PlanCreate(
        planner_version="ui_chaining_composer_v2",
        tasks_summary="Round-trip studio plan",
        dag_edges=[["LoadData", "TransformData"]],
        tasks=[
            models.TaskCreate(
                name="LoadData",
                description="Load source data",
                instruction="Use capability filesystem.workspace.list.",
                acceptance_criteria=["Completed capability filesystem.workspace.list"],
                expected_output_schema_ref="schemas/json_object",
                intent=models.ToolIntent.io,
                deps=[],
                tool_requests=["filesystem.workspace.list"],
                tool_inputs={"filesystem.workspace.list": {"path": "."}},
                critic_required=False,
            ),
            models.TaskCreate(
                name="TransformData",
                description="Transform the source data",
                instruction="Use capability json_transform.",
                acceptance_criteria=["Completed capability json_transform"],
                expected_output_schema_ref="schemas/json_object",
                intent=models.ToolIntent.transform,
                deps=["LoadData"],
                tool_requests=["json_transform"],
                tool_inputs=execution_contracts.embed_execution_gate(
                    {
                        "json_transform": {
                            "source": {
                                "$from": [
                                    "dependencies_by_name",
                                    "LoadData",
                                    "filesystem.workspace.list",
                                    "items",
                                ]
                            }
                        }
                    },
                    {"expression": "context.approved == true"},
                    request_ids=["json_transform"],
                ),
                critic_required=False,
            ),
        ],
    )

    run_spec = run_specs.plan_to_run_spec(plan, kind=models.RunKind.studio)

    assert run_spec.kind == models.RunKind.studio
    assert [step.name for step in run_spec.steps] == ["LoadData", "TransformData"]
    assert run_spec.steps[1].depends_on == [run_spec.steps[0].step_id]
    assert run_spec.steps[1].execution_gate == {"expression": "context.approved == true"}
    assert run_spec.steps[1].input_bindings == {
        "source": {
            "$from": [
                "dependencies_by_name",
                "LoadData",
                "filesystem.workspace.list",
                "items",
            ]
        }
    }

    round_tripped = run_specs.run_spec_to_plan(run_spec)

    assert round_tripped.model_dump(mode="json") == plan.model_dump(mode="json")


def test_parse_legacy_run_spec_promotes_compiled_request_id_to_execution_request_id() -> None:
    run_spec = run_specs.parse_run_spec(
        {
            "kind": "planner",
            "steps": [
                {
                    "step_id": "generate",
                    "name": "GenerateDocumentSpec",
                    "description": "Generate a document spec",
                    "instruction": "Generate a document spec",
                    "capability_request": {
                        "request_id": "llm_generate_document_spec",
                        "capability_id": "document.spec.generate",
                    },
                }
            ],
        }
    )

    assert run_spec is not None
    assert run_spec.steps[0].capability_request.request_id == "document.spec.generate"
    assert run_spec.steps[0].capability_request.execution_request_id == (
        "llm_generate_document_spec"
    )
