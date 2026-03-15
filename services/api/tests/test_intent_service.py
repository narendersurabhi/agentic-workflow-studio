from libs.core import workflow_contracts
from services.api.app import intent_service


def test_decompose_goal_intent_returns_llm_graph_with_summary_fields() -> None:
    failures: list[Exception] = []
    recorded: list[tuple[str, bool]] = []
    graph = intent_service.decompose_goal_intent(
        "Create a report",
        config=intent_service.IntentDecomposeConfig(
            enabled=True,
            mode="llm",
            capability_top_k=3,
            memory_retrieval_enabled=True,
            memory_retrieval_limit=2,
        ),
        runtime=intent_service.IntentDecomposeRuntime(
            provider=object(),
            heuristic_decompose=lambda goal: {"segments": [{"id": "fallback", "intent": "generate"}]},
            capability_entries=lambda: [{"id": "document.spec.generate", "description": "Generate doc"}],
            capability_ids=lambda: {"document.spec.generate"},
            normalize_user_id=lambda user_id: user_id or "default-user",
            retrieve_workflow_hints=lambda *_args: [{"key": "wf-1"}],
            semantic_goal_capability_hints=lambda *_args: [{"id": "document.spec.generate"}],
            llm_decompose=lambda **_kwargs: {
                "segments": [{"id": "s1", "intent": "generate", "objective": "Create report"}],
                "summary": {"segment_count": 1},
                "source": "llm",
            },
            annotate_graph_summary_defaults=lambda graph: {
                **graph,
                "summary": {
                    **(graph.get("summary") or {}),
                    "segment_count": 1,
                    "intent_order": ["generate"],
                },
            },
            apply_supported_fact_filter=lambda graph, _summaries: graph,
            record_metrics=lambda graph, result, has_summaries: recorded.append(
                (result, has_summaries)
            ),
            on_llm_failure=failures.append,
        ),
        interaction_summaries=[{"facts": ["Create report"], "action": "submit"}],
    )

    assert isinstance(graph, workflow_contracts.IntentGraph)
    assert graph.source == "llm"
    assert graph.summary.memory_hints_used == 1
    assert graph.summary.semantic_capability_hints_used == 1
    assert graph.summary.memory_retrieval_enabled is True
    assert recorded == [("llm", True)]
    assert failures == []


def test_decompose_goal_intent_falls_back_when_llm_fails() -> None:
    failures: list[Exception] = []
    graph = intent_service.decompose_goal_intent(
        "Create a report",
        config=intent_service.IntentDecomposeConfig(
            enabled=True,
            mode="llm",
            capability_top_k=3,
            memory_retrieval_enabled=False,
            memory_retrieval_limit=1,
        ),
        runtime=intent_service.IntentDecomposeRuntime(
            provider=object(),
            heuristic_decompose=lambda goal: {"segments": [{"id": "fallback", "intent": "generate"}]},
            capability_entries=lambda: [],
            capability_ids=lambda: set(),
            normalize_user_id=lambda user_id: user_id or "default-user",
            retrieve_workflow_hints=lambda *_args: [],
            semantic_goal_capability_hints=lambda *_args: [],
            llm_decompose=lambda **_kwargs: (_ for _ in ()).throw(ValueError("bad llm output")),
            annotate_graph_summary_defaults=lambda graph: {
                **graph,
                "summary": {"segment_count": len(graph.get("segments") or [])},
            },
            apply_supported_fact_filter=lambda graph, _summaries: graph,
            record_metrics=lambda *_args: None,
            on_llm_failure=failures.append,
        ),
    )

    assert graph.segments[0].id == "fallback"
    assert failures
