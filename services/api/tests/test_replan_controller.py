from __future__ import annotations

from libs.core import models
from services.api.app import replan_controller


def test_decide_task_failure_recovery_returns_retry_same_step_when_retry_budget_remains() -> None:
    decision = replan_controller.decide_task_failure_recovery(
        planning_mode=models.PlanningMode.adaptive,
        has_pending_replan=False,
        replans_used=0,
        max_replans=2,
        error_message="service unavailable: upstream temporary 503",
        classification={
            "category": "transient",
            "retryable": True,
        },
        attempt_number=1,
        max_attempts=3,
    )

    assert decision.strategy == models.ReplanStrategy.retry_same_step
    assert decision.strategy_reason == "retry_budget_remaining"
    assert decision.should_replan is False


def test_decide_task_failure_recovery_returns_pause_for_human_for_missing_input() -> None:
    decision = replan_controller.decide_task_failure_recovery(
        planning_mode=models.PlanningMode.adaptive,
        has_pending_replan=False,
        replans_used=0,
        max_replans=2,
        error_message="missing_input:path",
        classification={
            "category": "contract",
            "retryable": False,
        },
        attempt_number=1,
        max_attempts=3,
    )

    assert decision.strategy == models.ReplanStrategy.pause_for_human
    assert decision.strategy_reason == "missing_or_ambiguous_user_input"
    assert decision.should_replan is False


def test_decide_manual_replan_returns_full_replan() -> None:
    decision = replan_controller.decide_manual_replan()

    assert decision.strategy == models.ReplanStrategy.full_replan
    assert decision.strategy_reason == "manual_replan_requested"
    assert decision.should_replan is True
    assert decision.replan_reason == "manual"
