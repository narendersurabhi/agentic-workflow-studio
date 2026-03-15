from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from sqlalchemy.orm import Session

from libs.core import workflow_contracts


@dataclass(frozen=True)
class IntentDecomposeConfig:
    enabled: bool
    mode: str
    capability_top_k: int
    memory_retrieval_enabled: bool
    memory_retrieval_limit: int


@dataclass(frozen=True)
class IntentDecomposeRuntime:
    provider: Any
    heuristic_decompose: Callable[[str], dict[str, Any]]
    capability_entries: Callable[[], list[dict[str, str]]]
    capability_ids: Callable[[], set[str]]
    normalize_user_id: Callable[[str | None], str]
    retrieve_workflow_hints: Callable[[Session | None, str, str, int], list[dict[str, Any]]]
    semantic_goal_capability_hints: Callable[[str, list[dict[str, str]], int], list[dict[str, Any]]]
    llm_decompose: Callable[..., dict[str, Any]]
    annotate_graph_summary_defaults: Callable[[dict[str, Any]], dict[str, Any]]
    apply_supported_fact_filter: Callable[[dict[str, Any], list[dict[str, Any]]], dict[str, Any]]
    record_metrics: Callable[[dict[str, Any], str, bool], None]
    on_llm_failure: Callable[[Exception], None]


def decompose_goal_intent(
    goal: str,
    *,
    db: Session | None = None,
    user_id: str | None = None,
    interaction_summaries: list[dict[str, Any]] | None = None,
    config: IntentDecomposeConfig,
    runtime: IntentDecomposeRuntime,
) -> workflow_contracts.IntentGraph:
    fallback_graph = runtime.heuristic_decompose(goal)
    if "source" not in fallback_graph:
        fallback_graph = {**fallback_graph, "source": "heuristic"}
    allowed_capability_catalog = runtime.capability_entries()
    allowed_capability_ids = {
        str(entry.get("id") or "").strip()
        for entry in allowed_capability_catalog
        if str(entry.get("id") or "").strip()
    }
    if not allowed_capability_ids:
        allowed_capability_ids = runtime.capability_ids()
    normalized_user_id = runtime.normalize_user_id(user_id)
    workflow_hints = runtime.retrieve_workflow_hints(
        db,
        goal,
        normalized_user_id,
        config.memory_retrieval_limit,
    )
    semantic_goal_capabilities = runtime.semantic_goal_capability_hints(
        goal,
        allowed_capability_catalog,
        max(4, config.capability_top_k * 2),
    )
    has_interaction_summaries = bool(interaction_summaries)
    result = "heuristic"
    graph = fallback_graph
    if not config.enabled:
        result = "disabled"
    elif config.mode == "heuristic":
        result = "heuristic"
    elif runtime.provider is None:
        result = "provider_unavailable"
    else:
        try:
            graph = runtime.llm_decompose(
                goal=goal,
                provider=runtime.provider,
                fallback_graph=fallback_graph,
                allowed_capability_ids=allowed_capability_ids,
                allowed_capability_catalog=allowed_capability_catalog,
                capability_top_k=config.capability_top_k,
                interaction_summaries=interaction_summaries,
                workflow_hints=workflow_hints,
                semantic_goal_capabilities=semantic_goal_capabilities,
            )
            result = "llm"
        except Exception as exc:  # noqa: BLE001
            runtime.on_llm_failure(exc)
            graph = fallback_graph
            result = "llm_failed_fallback"
    graph = runtime.annotate_graph_summary_defaults(graph)
    summary_raw = graph.get("summary")
    summary = dict(summary_raw) if isinstance(summary_raw, dict) else {}
    summary["memory_hints_used"] = len(workflow_hints)
    summary["memory_retrieval_enabled"] = bool(config.memory_retrieval_enabled)
    summary["semantic_capability_hints_used"] = len(semantic_goal_capabilities)
    graph = {**graph, "summary": summary}
    if interaction_summaries:
        graph = runtime.apply_supported_fact_filter(graph, interaction_summaries)
    runtime.record_metrics(graph, result, has_interaction_summaries)
    return workflow_contracts.IntentGraph.model_validate(graph)
