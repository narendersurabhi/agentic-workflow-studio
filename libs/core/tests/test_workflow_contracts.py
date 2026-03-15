from libs.core import workflow_contracts


def test_parse_intent_graph_accepts_minimal_segment_graph() -> None:
    graph = workflow_contracts.parse_intent_graph(
        {
            "segments": [{"id": "s1", "intent": "render"}],
            "summary": {"semantic_capability_hints_used": 2},
            "source": "heuristic",
        }
    )

    assert graph is not None
    assert graph.segments[0].id == "s1"
    assert graph.segments[0].objective == ""
    assert graph.summary.semantic_capability_hints_used == 2
    assert graph.source == "heuristic"


def test_dump_intent_graph_returns_json_mapping() -> None:
    dumped = workflow_contracts.dump_intent_graph(
        workflow_contracts.IntentGraph.model_validate(
            {
                "segments": [
                    {
                        "id": "s1",
                        "intent": "generate",
                        "slots": {"must_have_inputs": ["instruction"]},
                    }
                ],
                "summary": {"segment_count": 1},
            }
        )
    )

    assert dumped == {
        "segments": [
            {
                "id": "s1",
                "intent": "generate",
                "objective": "",
                "objective_facts": [],
                "depends_on": [],
                "required_inputs": [],
                "suggested_capabilities": [],
                "suggested_capability_rankings": [],
                "unsupported_facts": [],
                "slots": {"must_have_inputs": ["instruction"]},
            }
        ],
        "summary": {"segment_count": 1, "intent_order": []},
    }
