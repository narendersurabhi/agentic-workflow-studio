import os
import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi.testclient import TestClient

os.environ["DATABASE_URL"] = "sqlite:///./test.db"
os.environ["ORCHESTRATOR_ENABLED"] = "false"
os.environ["JOB_RECOVERY_ENABLED"] = "false"
os.environ["POLICY_GATE_ENABLED"] = "false"
os.environ["CAPABILITY_MODE"] = "enabled"

from services.api.app import main  # noqa: E402
from services.api.app.database import Base, SessionLocal, engine  # noqa: E402
from services.api.app.models import (  # noqa: E402
    ChatMessageRecord,
    ChatSessionRecord,
    JobRecord,
    PlanRecord,
    TaskRecord,
)


Base.metadata.create_all(bind=engine)

client = TestClient(main.app)


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _create_plan_for_job(job_id: str, *, planner_version: str = "test_feedback_v1") -> tuple[str, str]:
    plan_id = str(uuid.uuid4())
    task_id = str(uuid.uuid4())
    now = _utcnow()
    with SessionLocal() as db:
        plan = PlanRecord(
            id=plan_id,
            job_id=job_id,
            planner_version=planner_version,
            created_at=now,
            tasks_summary="Test feedback plan",
            dag_edges=[],
            policy_decision={},
        )
        task = TaskRecord(
            id=task_id,
            job_id=job_id,
            plan_id=plan_id,
            name="WriteSummary",
            description="Write a short summary.",
            instruction="Write a short summary.",
            acceptance_criteria=["Summary exists"],
            expected_output_schema_ref="TaskResult",
            status="pending",
            deps=[],
            attempts=0,
            max_attempts=3,
            rework_count=0,
            max_reworks=2,
            assigned_to=None,
            intent="transform",
            tool_requests=["text_summarize"],
            tool_inputs={},
            created_at=now,
            updated_at=now,
            critic_required=True,
        )
        db.add(plan)
        db.add(task)
        db.commit()
    return plan_id, task_id


def _update_job(job_id: str, *, metadata: dict[str, Any] | None = None, status: str | None = None) -> None:
    now = _utcnow()
    with SessionLocal() as db:
        job = db.query(JobRecord).filter(JobRecord.id == job_id).first()
        assert job is not None
        merged = dict(job.metadata_json or {})
        if metadata:
            merged.update(metadata)
        job.metadata_json = merged
        if status is not None:
            job.status = status
        job.updated_at = now
        db.commit()


def _update_task(task_id: str, *, status: str | None = None, rework_count: int | None = None) -> None:
    now = _utcnow()
    with SessionLocal() as db:
        task = db.query(TaskRecord).filter(TaskRecord.id == task_id).first()
        assert task is not None
        if status is not None:
            task.status = status
        if rework_count is not None:
            task.rework_count = rework_count
        task.updated_at = now
        db.commit()


def _attach_chat_session_to_job(
    job_id: str,
    *,
    clarification_questions: list[str] | None = None,
) -> str:
    session_id = str(uuid.uuid4())
    now = _utcnow()
    with SessionLocal() as db:
        session = ChatSessionRecord(
            id=session_id,
            title="Feedback summary session",
            metadata_json={},
            created_at=now,
            updated_at=now,
        )
        db.add(session)
        if clarification_questions:
            db.add(
                ChatMessageRecord(
                    id=str(uuid.uuid4()),
                    session_id=session_id,
                    role="assistant",
                    content="\n".join(clarification_questions),
                    metadata_json={},
                    action_json={
                        "type": "ask_clarification",
                        "clarification_questions": clarification_questions,
                    },
                    job_id=None,
                    created_at=now,
                )
            )
        db.add(
            ChatMessageRecord(
                id=str(uuid.uuid4()),
                session_id=session_id,
                role="assistant",
                content=f"Started job {job_id}",
                metadata_json={},
                action_json={"type": "submit_job"},
                job_id=job_id,
                created_at=now,
            )
        )
        db.commit()
    return session_id


def test_submit_chat_message_feedback_and_list_for_session() -> None:
    session = client.post("/chat/sessions", json={"title": "Feedback session"}).json()
    turn = client.post(
        f"/chat/sessions/{session['id']}/messages",
        json={"content": "help", "context_json": {}, "priority": 0},
    ).json()
    assistant_message = turn["assistant_message"]

    feedback_response = client.post(
        "/feedback",
        headers={"X-Feedback-Actor-Id": "tester-chat"},
        json={
            "target_type": "chat_message",
            "target_id": assistant_message["id"],
            "sentiment": "positive",
            "reason_codes": [],
            "comment": "Helpful answer.",
            "metadata": {"surface": "chat"},
        },
    )

    assert feedback_response.status_code == 200
    body = feedback_response.json()
    assert body["target_type"] == "chat_message"
    assert body["message_id"] == assistant_message["id"]
    assert body["session_id"] == session["id"]
    assert body["snapshot"]["content"] == assistant_message["content"]
    assert body["metadata"]["dimensions"]["target_type"] == "chat_message"
    assert body["metadata"]["dimensions"]["assistant_action_type"] == "respond"
    assert body["metadata"]["dimensions"]["has_comment"] is True
    assert body["metadata"]["dimensions"]["reason_count"] == 0

    list_response = client.get(f"/chat/sessions/{session['id']}/feedback")
    assert list_response.status_code == 200
    list_body = list_response.json()
    assert list_body["summary"]["total"] >= 1
    assert any(item["id"] == body["id"] for item in list_body["items"])


def test_submit_intent_and_plan_feedback_updates_same_actor_record() -> None:
    job_response = client.post(
        "/jobs",
        json={"goal": "Create a short document summary", "context_json": {}, "priority": 0},
    )
    assert job_response.status_code == 200
    job = job_response.json()
    plan_id, _task_id = _create_plan_for_job(job["id"])

    first = client.post(
        "/feedback",
        headers={"X-Feedback-Actor-Id": "tester-plan"},
        json={
            "target_type": "plan",
            "target_id": plan_id,
            "sentiment": "negative",
            "reason_codes": ["missing_step"],
            "comment": "Needs one more review step.",
        },
    )
    assert first.status_code == 200

    second = client.post(
        "/feedback",
        headers={"X-Feedback-Actor-Id": "tester-plan"},
        json={
            "target_type": "plan",
            "target_id": plan_id,
            "sentiment": "positive",
            "reason_codes": [],
            "comment": "Looks good now.",
        },
    )
    assert second.status_code == 200
    second_body = second.json()
    assert second_body["id"] == first.json()["id"]
    assert second_body["sentiment"] == "positive"
    assert second_body["snapshot"]["plan_id"] == plan_id
    assert second_body["snapshot"]["task_count"] == 1

    filtered = client.get(
        f"/feedback?target_type=plan&target_id={plan_id}&actor_key=tester-plan"
    )
    assert filtered.status_code == 200
    filtered_body = filtered.json()
    assert filtered_body["summary"]["total"] == 1
    assert filtered_body["items"][0]["comment"] == "Looks good now."


def test_job_feedback_endpoint_returns_intent_plan_and_outcome_feedback() -> None:
    job_response = client.post(
        "/jobs",
        json={"goal": "Plan a report", "context_json": {}, "priority": 0},
    )
    assert job_response.status_code == 200
    job = job_response.json()
    plan_id, _task_id = _create_plan_for_job(job["id"])

    intent_feedback = client.post(
        "/feedback",
        headers={"X-Feedback-Actor-Id": "tester-job"},
        json={
            "target_type": "intent_assessment",
            "target_id": job["id"],
            "sentiment": "negative",
            "reason_codes": ["wrong_scope"],
            "comment": "It missed the output constraints.",
        },
    )
    assert intent_feedback.status_code == 200
    assert intent_feedback.json()["snapshot"]["normalized_intent_envelope"]["goal"] == "Plan a report"

    plan_feedback = client.post(
        "/feedback",
        headers={"X-Feedback-Actor-Id": "tester-job"},
        json={
            "target_type": "plan",
            "target_id": plan_id,
            "sentiment": "positive",
            "reason_codes": [],
            "comment": "Plan structure is good.",
        },
    )
    assert plan_feedback.status_code == 200

    outcome_feedback = client.post(
        "/feedback",
        headers={"X-Feedback-Actor-Id": "tester-job"},
        json={
            "target_type": "job_outcome",
            "target_id": job["id"],
            "sentiment": "partial",
            "score": 3,
            "reason_codes": ["did_not_finish"],
            "comment": "Good direction, but incomplete.",
        },
    )
    assert outcome_feedback.status_code == 200
    assert outcome_feedback.json()["snapshot"]["job_id"] == job["id"]

    response = client.get(f"/jobs/{job['id']}/feedback")
    assert response.status_code == 200
    body = response.json()
    target_types = {item["target_type"] for item in body["items"]}
    assert "intent_assessment" in target_types
    assert "plan" in target_types
    assert "job_outcome" in target_types


def test_submit_feedback_returns_not_found_for_unknown_target() -> None:
    response = client.post(
        "/feedback",
        headers={"X-Feedback-Actor-Id": "tester-missing"},
        json={
            "target_type": "chat_message",
            "target_id": "missing-message",
            "sentiment": "negative",
            "reason_codes": ["incorrect"],
        },
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "feedback_target_not_found"


def test_feedback_summary_filters_breaks_down_dimensions_and_correlates() -> None:
    suffix = uuid.uuid4().hex[:8]
    workflow_source = f"summary-source-{suffix}"
    llm_model = f"summary-model-{suffix}"
    planner_version = f"summary-planner-{suffix}"

    job_response = client.post(
        "/jobs",
        json={"goal": "Assemble an incident write-up", "context_json": {}, "priority": 0},
    )
    assert job_response.status_code == 200
    job = job_response.json()
    plan_id, task_id = _create_plan_for_job(job["id"], planner_version=planner_version)
    _update_job(
        job["id"],
        metadata={
            "workflow_source": workflow_source,
            "llm_provider": "openai",
            "llm_model": llm_model,
            "replan_count": 2,
            "plan_error": "planner_validation_failed",
        },
        status="failed",
    )
    _update_task(task_id, status="failed", rework_count=1)
    _attach_chat_session_to_job(
        job["id"],
        clarification_questions=["What level of detail should the write-up include?"],
    )

    intent_feedback = client.post(
        "/feedback",
        headers={"X-Feedback-Actor-Id": f"summary-intent-{suffix}"},
        json={
            "target_type": "intent_assessment",
            "target_id": job["id"],
            "sentiment": "negative",
            "reason_codes": ["wrong_scope"],
            "comment": "The request scope was too broad.",
        },
    )
    assert intent_feedback.status_code == 200
    assert intent_feedback.json()["metadata"]["dimensions"]["workflow_source"] == workflow_source
    assert intent_feedback.json()["metadata"]["dimensions"]["llm_model"] == llm_model
    assert intent_feedback.json()["metadata"]["dimensions"]["planner_version"] == planner_version
    assert intent_feedback.json()["metadata"]["dimensions"]["job_status_at_feedback"] == "failed"

    plan_feedback = client.post(
        "/feedback",
        headers={"X-Feedback-Actor-Id": f"summary-plan-{suffix}"},
        json={
            "target_type": "plan",
            "target_id": plan_id,
            "sentiment": "negative",
            "reason_codes": ["missing_step"],
            "comment": "The review step is missing.",
        },
    )
    assert plan_feedback.status_code == 200

    outcome_feedback = client.post(
        "/feedback",
        headers={"X-Feedback-Actor-Id": f"summary-outcome-{suffix}"},
        json={
            "target_type": "job_outcome",
            "target_id": job["id"],
            "sentiment": "partial",
            "score": 3,
            "reason_codes": ["did_not_finish"],
            "comment": "The draft never completed.",
        },
    )
    assert outcome_feedback.status_code == 200

    response = client.get(
        "/feedback/summary",
        params={
            "workflow_source": workflow_source,
            "llm_model": llm_model,
            "planner_version": planner_version,
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 3
    assert body["sentiment_counts"]["negative"] == 2
    assert body["sentiment_counts"]["partial"] == 1
    assert any(
        bucket["key"] == "intent_assessment" and bucket["total"] == 1
        for bucket in body["target_type_counts"]
    )
    assert any(bucket["key"] == workflow_source and bucket["total"] == 3 for bucket in body["workflow_sources"])
    assert any(bucket["key"] == llm_model and bucket["total"] == 3 for bucket in body["llm_models"])
    assert any(
        bucket["key"] == planner_version and bucket["total"] == 3
        for bucket in body["planner_versions"]
    )
    assert any(bucket["key"] == "failed" and bucket["total"] == 3 for bucket in body["job_statuses"])
    assert set(reason["reason_code"] for reason in body["negative_reasons"]) >= {
        "wrong_scope",
        "missing_step",
        "did_not_finish",
    }
    assert body["metrics"]["intent_agreement_rate"] == 0.0
    assert body["metrics"]["plan_approval_rate"] == 0.0
    assert body["metrics"]["job_outcome_positive_rate"] == 0.0
    assert body["correlates"]["job_count"] == 1
    assert body["correlates"]["replan_count"] == 2
    assert body["correlates"]["retry_count"] == 1
    assert body["correlates"]["failed_task_count"] == 1
    assert body["correlates"]["plan_failure_count"] == 1
    assert body["correlates"]["clarification_turn_count"] == 1
    assert any(
        bucket["key"] == "failed" and bucket["total"] == 1
        for bucket in body["correlates"]["terminal_statuses"]
    )

    plan_only = client.get(
        "/feedback/summary",
        params={
            "workflow_source": workflow_source,
            "target_type": "plan",
        },
    )
    assert plan_only.status_code == 200
    assert plan_only.json()["total"] == 1
