from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

from libs.core import models


@dataclass(frozen=True)
class RecoveryDecision:
    strategy: models.ReplanStrategy
    strategy_reason: str
    should_replan: bool = False
    replan_reason: str | None = None
    require_adaptive: bool = False
    context: dict[str, Any] = field(default_factory=dict)


def decide_manual_replan() -> RecoveryDecision:
    return RecoveryDecision(
        strategy=models.ReplanStrategy.full_replan,
        strategy_reason="manual_replan_requested",
        should_replan=True,
        replan_reason="manual",
        require_adaptive=False,
    )


def decide_task_failure_recovery(
    *,
    planning_mode: models.PlanningMode,
    has_pending_replan: bool,
    replans_used: int,
    max_replans: int,
    error_message: str | None,
    classification: Mapping[str, Any] | None,
    attempt_number: int,
    max_attempts: int,
    intent_mismatch_context: Mapping[str, Any] | None = None,
    retry_context: Mapping[str, Any] | None = None,
) -> RecoveryDecision:
    normalized_error = str(error_message or "").strip().lower()
    details = classification if isinstance(classification, Mapping) else {}
    category = str(details.get("category") or "").strip().lower()
    retryable = bool(details.get("retryable"))
    adaptive_enabled = planning_mode == models.PlanningMode.adaptive
    exhausted = max_attempts > 0 and attempt_number >= max_attempts

    if has_pending_replan:
        return RecoveryDecision(
            strategy=models.ReplanStrategy.no_replan,
            strategy_reason="pending_replan_already_requested",
        )

    if intent_mismatch_context:
        if not adaptive_enabled:
            return RecoveryDecision(
                strategy=models.ReplanStrategy.no_replan,
                strategy_reason="adaptive_mode_required_for_intent_mismatch_repair",
            )
        if replans_used >= max_replans:
            return RecoveryDecision(
                strategy=models.ReplanStrategy.no_replan,
                strategy_reason="max_replans_exhausted",
            )
        return RecoveryDecision(
            strategy=models.ReplanStrategy.switch_capability,
            strategy_reason="contract_or_intent_mismatch",
            should_replan=True,
            replan_reason="intent_mismatch_auto_repair",
            require_adaptive=True,
            context=dict(intent_mismatch_context),
        )

    if (
        "clarification" in normalized_error
        or "intent_clarification_required" in normalized_error
        or "missing input" in normalized_error
        or "missing_input" in normalized_error
        or "workflow_inputs_invalid" in normalized_error
    ):
        return RecoveryDecision(
            strategy=models.ReplanStrategy.pause_for_human,
            strategy_reason="missing_or_ambiguous_user_input",
        )

    if category == "policy":
        return RecoveryDecision(
            strategy=models.ReplanStrategy.no_replan,
            strategy_reason="policy_blocked",
        )

    if retryable and max_attempts > 0 and attempt_number < max_attempts:
        return RecoveryDecision(
            strategy=models.ReplanStrategy.retry_same_step,
            strategy_reason="retry_budget_remaining",
        )

    if retryable and exhausted:
        if not adaptive_enabled:
            return RecoveryDecision(
                strategy=models.ReplanStrategy.no_replan,
                strategy_reason="adaptive_mode_required_for_retry_exhausted_repair",
            )
        if replans_used >= max_replans:
            return RecoveryDecision(
                strategy=models.ReplanStrategy.no_replan,
                strategy_reason="max_replans_exhausted",
            )
        return RecoveryDecision(
            strategy=models.ReplanStrategy.patch_suffix,
            strategy_reason="retry_budget_exhausted_with_reusable_prefix",
            should_replan=True,
            replan_reason="retry_exhausted_auto_repair",
            require_adaptive=True,
            context=dict(retry_context or {}),
        )

    return RecoveryDecision(
        strategy=models.ReplanStrategy.no_replan,
        strategy_reason="no_applicable_recovery_strategy",
    )
