from __future__ import annotations

import json

from libs.core import models, planner_support_tools

# test_search_capabilities_support_returns_ranked_matches and
# test_finalize_run_spec_support_compiles_capability_first_plan removed:
# depended on capability_registry, removed with the tools framework.


def test_build_planner_support_tool_specs_exposes_metadata_only_surface() -> None:
    names = [tool.name for tool in planner_support_tools.build_planner_support_tool_specs()]

    assert names == [
        "search_capabilities",
        "get_capability_contract",
        "get_schema",
        "get_workflow_hints",
        "get_memory_hints",
        "finalize_run_spec",
    ]


def test_get_schema_support_summarizes_required_fields(tmp_path) -> None:
    schema_path = tmp_path / "example_schema.json"
    schema_path.write_text(
        json.dumps(
            {
                "type": "object",
                "properties": {"topic": {"type": "string"}, "audience": {"type": "string"}},
                "required": ["topic"],
            }
        ),
        encoding="utf-8",
    )

    result = planner_support_tools.get_schema_support(
        schema_ref="example_schema",
        schema_registry_path=str(tmp_path),
    )

    assert result["summary"]["required_fields"] == ["topic"]
    assert result["summary"]["property_count"] == 2
