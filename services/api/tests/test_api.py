import os
import uuid
from datetime import datetime

import redis
from fastapi.testclient import TestClient

os.environ["DATABASE_URL"] = "sqlite:///./test.db"
os.environ["ORCHESTRATOR_ENABLED"] = "false"
os.environ["JOB_RECOVERY_ENABLED"] = "false"
os.environ["POLICY_GATE_ENABLED"] = "false"

from services.api.app import main  # noqa: E402
from services.api.app.database import Base, engine
from services.api.app.database import SessionLocal
from services.api.app.models import JobRecord, PlanRecord, TaskRecord
from libs.core import events, models
from libs.core import capability_registry as cap_registry


Base.metadata.create_all(bind=engine)

client = TestClient(main.app)


def test_create_job():
    response = client.post(
        "/jobs",
        json={"goal": "demo", "context_json": {}, "priority": 1},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["goal"] == "demo"


def test_event_stream():
    response = client.get("/events/stream?once=true")
    assert response.status_code == 200


def test_job_details():
    job_id = f"job-details-{uuid.uuid4()}"
    plan_id = f"plan-details-{uuid.uuid4()}"
    task_id = f"task-details-{uuid.uuid4()}"
    now = datetime.utcnow()
    with SessionLocal() as db:
        db.add(
            JobRecord(
                id=job_id,
                goal="details",
                context_json={},
                status=models.JobStatus.queued.value,
                created_at=now,
                updated_at=now,
                priority=0,
                metadata_json={},
            )
        )
        db.add(
            PlanRecord(
                id=plan_id,
                job_id=job_id,
                planner_version="test",
                created_at=now,
                tasks_summary="one task",
                dag_edges=[],
                policy_decision={},
            )
        )
        db.add(
            TaskRecord(
                id=task_id,
                job_id=job_id,
                plan_id=plan_id,
                name="t1",
                description="desc",
                instruction="do it",
                acceptance_criteria=[],
                expected_output_schema_ref="TaskResult",
                status=models.TaskStatus.pending.value,
                deps=[],
                attempts=0,
                max_attempts=1,
                rework_count=0,
                max_reworks=0,
                assigned_to=None,
                intent=None,
                tool_requests=[],
                tool_inputs={},
                created_at=now,
                updated_at=now,
                critic_required=1,
            )
        )
        db.commit()

    response = client.get(f"/jobs/{job_id}/details")
    assert response.status_code == 200
    data = response.json()
    assert data["job_id"] == job_id
    assert data["plan"]["id"] == plan_id
    assert len(data["tasks"]) == 1
    assert data["tasks"][0]["id"] == task_id
    assert task_id in data["task_results"]


def test_plan_created_enqueues_ready_tasks():
    job_id = f"job-test-plan-{uuid.uuid4()}"
    with SessionLocal() as db:
        db.add(
            JobRecord(
                id=job_id,
                goal="demo",
                context_json={},
                status=models.JobStatus.queued.value,
                created_at=datetime.utcnow(),
                updated_at=datetime.utcnow(),
                priority=0,
                metadata_json={},
            )
        )
        db.commit()
    plan = models.PlanCreate(
        planner_version="test",
        tasks_summary="t1 then t2",
        dag_edges=[["t1", "t2"]],
        tasks=[
            models.TaskCreate(
                name="t1",
                description="first",
                instruction="do first",
                acceptance_criteria=["ok"],
                expected_output_schema_ref="TaskResult",
                deps=[],
                tool_requests=[],
                critic_required=False,
            ),
            models.TaskCreate(
                name="t2",
                description="second",
                instruction="do second",
                acceptance_criteria=["ok"],
                expected_output_schema_ref="TaskResult",
                deps=["t1"],
                tool_requests=[],
                critic_required=False,
            ),
        ],
    )
    payload = plan.model_dump()
    payload["job_id"] = job_id
    envelope = {
        "type": "plan.created",
        "payload": payload,
        "job_id": job_id,
        "correlation_id": "corr",
    }
    events: list[tuple[str, dict]] = []
    original_emit = main._emit_event
    try:
        main._emit_event = lambda event_type, event_payload: events.append(
            (event_type, event_payload)
        )
        main._handle_plan_created(envelope)
    finally:
        main._emit_event = original_emit
    with SessionLocal() as db:
        tasks = db.query(TaskRecord).filter(TaskRecord.job_id == job_id).all()
        by_name = {task.name: task for task in tasks}
        assert by_name["t1"].status == models.TaskStatus.ready.value
        assert by_name["t2"].status == models.TaskStatus.pending.value
    assert any(event_type == "task.ready" for event_type, _ in events)


def test_handle_task_started_sets_task_running_and_job_running():
    job_id = f"job-task-started-{uuid.uuid4()}"
    plan_id = f"plan-task-started-{uuid.uuid4()}"
    task_id = f"task-task-started-{uuid.uuid4()}"
    now = datetime.utcnow()
    with SessionLocal() as db:
        db.add(
            JobRecord(
                id=job_id,
                goal="task started",
                context_json={},
                status=models.JobStatus.planning.value,
                created_at=now,
                updated_at=now,
                priority=0,
                metadata_json={},
            )
        )
        db.add(
            PlanRecord(
                id=plan_id,
                job_id=job_id,
                planner_version="test",
                created_at=now,
                tasks_summary="single task",
                dag_edges=[],
                policy_decision={},
            )
        )
        db.add(
            TaskRecord(
                id=task_id,
                job_id=job_id,
                plan_id=plan_id,
                name="only-task",
                description="desc",
                instruction="do",
                acceptance_criteria=[],
                expected_output_schema_ref="TaskResult",
                status=models.TaskStatus.ready.value,
                deps=[],
                attempts=1,
                max_attempts=3,
                rework_count=0,
                max_reworks=0,
                assigned_to=None,
                intent=None,
                tool_requests=[],
                tool_inputs={},
                created_at=now,
                updated_at=now,
                critic_required=0,
            )
        )
        db.commit()

    envelope = {
        "type": "task.started",
        "job_id": job_id,
        "task_id": task_id,
        "payload": {
            "task_id": task_id,
            "attempts": 1,
            "max_attempts": 3,
            "worker_consumer": "worker-a",
        },
    }
    main._handle_task_started(envelope)

    with SessionLocal() as db:
        job = db.query(JobRecord).filter(JobRecord.id == job_id).first()
        task = db.query(TaskRecord).filter(TaskRecord.id == task_id).first()
        assert job is not None
        assert task is not None
        assert job.status == models.JobStatus.running.value
        assert task.status == models.TaskStatus.running.value
        assert task.assigned_to == "worker-a"


def test_read_task_dlq_filters_by_job_and_respects_limit(monkeypatch):
    class _RedisStub:
        def xrevrange(self, stream, max_id, min_id, count=0):
            return [
                (
                    "11-0",
                    {
                        "data": '{"message_id":"m-1","job_id":"job-a","task_id":"t-1","error":"timed out","failed_at":"2026-02-14T00:00:00Z"}'
                    },
                ),
                (
                    "10-0",
                    {
                        "data": '{"message_id":"m-2","job_id":"job-b","task_id":"t-2","error":"hard failure"}'
                    },
                ),
                (
                    "9-0",
                    {
                        "data": '{"message_id":"m-3","job_id":"job-a","task_id":"t-3","error":"fatal"}'
                    },
                ),
            ]

    monkeypatch.setattr(main, "redis_client", _RedisStub())
    response = client.get("/jobs/job-a/tasks/dlq?limit=1")
    assert response.status_code == 200
    payload = response.json()
    assert len(payload) == 1
    assert payload[0]["job_id"] == "job-a"
    assert payload[0]["message_id"] == "m-1"


def test_read_task_dlq_returns_503_on_redis_error(monkeypatch):
    class _RedisStub:
        def xrevrange(self, stream, max_id, min_id, count=0):
            raise redis.RedisError("down")

    monkeypatch.setattr(main, "redis_client", _RedisStub())
    response = client.get("/jobs/job-a/tasks/dlq?limit=5")
    assert response.status_code == 503
    assert response.json()["detail"].startswith("redis_error:")


def test_list_capabilities_returns_required_inputs(monkeypatch):
    capability = cap_registry.CapabilitySpec(
        capability_id="github.repo.list",
        description="List repos",
        risk_tier="read_only",
        idempotency="read",
        group="github",
        subgroup="repositories",
        input_schema_ref="github_repo_list_capability_input",
        output_schema_ref=None,
        adapters=(
            cap_registry.CapabilityAdapterSpec(
                type="mcp",
                server_id="github_local",
                tool_name="search_repositories",
            ),
        ),
        tags=("github",),
        enabled=True,
    )
    registry = cap_registry.CapabilityRegistry(capabilities={"github.repo.list": capability})
    monkeypatch.setattr(main.capability_registry, "resolve_capability_mode", lambda: "enabled")
    monkeypatch.setattr(main.capability_registry, "load_capability_registry", lambda: registry)
    monkeypatch.setattr(
        main,
        "_load_schema_from_ref",
        lambda schema_ref: {
            "type": "object",
            "required": ["query"],
            "properties": {"query": {"type": "string"}},
        },
    )
    response = client.get("/capabilities")
    assert response.status_code == 200
    payload = response.json()
    assert payload["mode"] == "enabled"
    assert len(payload["items"]) == 1
    item = payload["items"][0]
    assert item["id"] == "github.repo.list"
    assert item["group"] == "github"
    assert item["subgroup"] == "repositories"
    assert item["required_inputs"] == ["query"]


def test_task_payload_from_record_flags_unresolved_reference_inputs() -> None:
    now = datetime.utcnow()
    record = TaskRecord(
        id=f"task-ref-{uuid.uuid4()}",
        job_id="job-ref",
        plan_id="plan-ref",
        name="RenderDocument",
        description="Render document",
        instruction="Render",
        acceptance_criteria=["docx created"],
        expected_output_schema_ref="schemas/docx_output",
        status=models.TaskStatus.ready.value,
        deps=["GenerateDocumentSpec"],
        attempts=0,
        max_attempts=3,
        rework_count=0,
        max_reworks=0,
        assigned_to=None,
        intent="render",
        tool_requests=["docx_generate_from_spec"],
        tool_inputs={
            "docx_generate_from_spec": {
                "path": "documents/out.docx",
                "document_spec": {
                    "$from": "dependencies_by_name.GenerateDocumentSpec.llm_generate_document_spec.document_spec"
                },
            }
        },
        created_at=now,
        updated_at=now,
        critic_required=0,
    )
    payload = main._task_payload_from_record(record, correlation_id="corr", context={})
    validation = payload.get("tool_inputs_validation", {})
    assert "docx_generate_from_spec" in validation
    assert "input reference resolution failed" in validation["docx_generate_from_spec"]


def test_plan_preflight_compiler_accepts_valid_dependency_chain() -> None:
    plan = models.PlanCreate(
        planner_version="test",
        tasks_summary="json chain",
        dag_edges=[["MakeJson", "ReuseJson"]],
        tasks=[
            models.TaskCreate(
                name="MakeJson",
                description="Build json",
                instruction="Build",
                acceptance_criteria=["done"],
                expected_output_schema_ref="schemas/json_object",
                deps=[],
                tool_requests=["json_transform"],
                tool_inputs={"json_transform": {"input": {"name": "demo"}}},
                critic_required=False,
            ),
            models.TaskCreate(
                name="ReuseJson",
                description="Reuse json",
                instruction="Reuse",
                acceptance_criteria=["done"],
                expected_output_schema_ref="schemas/json_object",
                deps=["MakeJson"],
                tool_requests=["json_transform"],
                tool_inputs={
                    "json_transform": {
                        "input": {"$from": "dependencies_by_name.MakeJson.json_transform.result"}
                    }
                },
                critic_required=False,
            ),
        ],
    )
    errors = main._compile_plan_preflight(plan, job_context={})
    assert errors == {}


def test_plan_preflight_compiler_flags_broken_reference_path() -> None:
    plan = models.PlanCreate(
        planner_version="test",
        tasks_summary="broken ref",
        dag_edges=[["MakeJson", "ReuseJson"]],
        tasks=[
            models.TaskCreate(
                name="MakeJson",
                description="Build json",
                instruction="Build",
                acceptance_criteria=["done"],
                expected_output_schema_ref="schemas/json_object",
                deps=[],
                tool_requests=["json_transform"],
                tool_inputs={"json_transform": {"input": {"name": "demo"}}},
                critic_required=False,
            ),
            models.TaskCreate(
                name="ReuseJson",
                description="Reuse json",
                instruction="Reuse",
                acceptance_criteria=["done"],
                expected_output_schema_ref="schemas/json_object",
                deps=["MakeJson"],
                tool_requests=["json_transform"],
                tool_inputs={
                    "json_transform": {
                        "input": {"$from": "dependencies_by_name.MakeJson.missing_tool.result"}
                    }
                },
                critic_required=False,
            ),
        ],
    )
    errors = main._compile_plan_preflight(plan, job_context={})
    assert "ReuseJson" in errors
    assert "input reference resolution failed" in errors["ReuseJson"]


def test_retry_task_from_dlq_resets_task_and_deletes_stream_entry(monkeypatch):
    job_id = f"job-retry-task-{uuid.uuid4()}"
    plan_id = f"plan-retry-task-{uuid.uuid4()}"
    task_id = f"task-retry-task-{uuid.uuid4()}"
    now = datetime.utcnow()
    with SessionLocal() as db:
        db.add(
            JobRecord(
                id=job_id,
                goal="retry one task",
                context_json={},
                status=models.JobStatus.failed.value,
                created_at=now,
                updated_at=now,
                priority=0,
                metadata_json={},
            )
        )
        db.add(
            PlanRecord(
                id=plan_id,
                job_id=job_id,
                planner_version="test",
                created_at=now,
                tasks_summary="single task",
                dag_edges=[],
                policy_decision={},
            )
        )
        db.add(
            TaskRecord(
                id=task_id,
                job_id=job_id,
                plan_id=plan_id,
                name="only-task",
                description="desc",
                instruction="do",
                acceptance_criteria=[],
                expected_output_schema_ref="TaskResult",
                status=models.TaskStatus.failed.value,
                deps=[],
                attempts=2,
                max_attempts=3,
                rework_count=1,
                max_reworks=2,
                assigned_to=None,
                intent=None,
                tool_requests=[],
                tool_inputs={},
                created_at=now,
                updated_at=now,
                critic_required=0,
            )
        )
        db.commit()

    class _RedisStub:
        def __init__(self):
            self.deleted = []

        def xdel(self, stream, stream_id):
            self.deleted.append((stream, stream_id))
            return 1

    redis_stub = _RedisStub()
    monkeypatch.setattr(main, "redis_client", redis_stub)
    captured = {"called": False}
    monkeypatch.setattr(
        main,
        "_enqueue_ready_tasks",
        lambda *args, **kwargs: captured.__setitem__("called", True),
    )

    response = client.post(
        f"/jobs/{job_id}/tasks/{task_id}/retry",
        json={"stream_id": "99-0"},
    )
    assert response.status_code == 200
    assert captured["called"] is True
    assert redis_stub.deleted == [(events.TASK_DLQ_STREAM, "99-0")]

    with SessionLocal() as db:
        refreshed = db.query(TaskRecord).filter(TaskRecord.id == task_id).first()
        assert refreshed is not None
        assert refreshed.status == models.TaskStatus.pending.value
        assert refreshed.attempts == 0
        assert refreshed.rework_count == 0


def test_retry_task_from_dlq_requires_failed_status():
    job_id = f"job-retry-task-state-{uuid.uuid4()}"
    plan_id = f"plan-retry-task-state-{uuid.uuid4()}"
    task_id = f"task-retry-task-state-{uuid.uuid4()}"
    now = datetime.utcnow()
    with SessionLocal() as db:
        db.add(
            JobRecord(
                id=job_id,
                goal="retry one task state",
                context_json={},
                status=models.JobStatus.running.value,
                created_at=now,
                updated_at=now,
                priority=0,
                metadata_json={},
            )
        )
        db.add(
            PlanRecord(
                id=plan_id,
                job_id=job_id,
                planner_version="test",
                created_at=now,
                tasks_summary="single task",
                dag_edges=[],
                policy_decision={},
            )
        )
        db.add(
            TaskRecord(
                id=task_id,
                job_id=job_id,
                plan_id=plan_id,
                name="only-task",
                description="desc",
                instruction="do",
                acceptance_criteria=[],
                expected_output_schema_ref="TaskResult",
                status=models.TaskStatus.completed.value,
                deps=[],
                attempts=1,
                max_attempts=3,
                rework_count=0,
                max_reworks=2,
                assigned_to=None,
                intent=None,
                tool_requests=[],
                tool_inputs={},
                created_at=now,
                updated_at=now,
                critic_required=0,
            )
        )
        db.commit()

    response = client.post(f"/jobs/{job_id}/tasks/{task_id}/retry", json={"stream_id": "100-0"})
    assert response.status_code == 400
    assert response.json()["detail"] == "Task is not failed"
