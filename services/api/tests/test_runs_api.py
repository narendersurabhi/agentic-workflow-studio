import json
import os
import uuid
from datetime import UTC, datetime

from fastapi.testclient import TestClient

os.environ["DATABASE_URL"] = "sqlite:///./test.db"
os.environ["ORCHESTRATOR_ENABLED"] = "false"
os.environ["JOB_RECOVERY_ENABLED"] = "false"
os.environ["POLICY_GATE_ENABLED"] = "false"
os.environ["CAPABILITY_MODE"] = "enabled"
os.environ["INTENT_VECTOR_SEARCH_ENABLED"] = "false"
os.environ["CHAT_INTENT_VECTOR_SEARCH_ENABLED"] = "false"

from libs.core import models  # noqa: E402
from services.api.app import main  # noqa: E402
from services.api.app import run_context_service  # noqa: E402
from services.api.app.database import Base, SessionLocal, engine  # noqa: E402
from services.api.app.models import (  # noqa: E402
    ExecutionRequestRecord,
    JobRecord,
    PlanRecord,
    RunRecord,
    RunStepRecord,
    StepAttemptRecord,
    StepCheckpointRecord,
    TaskRecord,
    WorkflowVersionRecord,
)


Base.metadata.drop_all(bind=engine)
Base.metadata.create_all(bind=engine)

client = TestClient(main.app)


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _create_job(goal: str | None = None) -> dict[str, str]:
    response = client.post(
        "/jobs",
        json={
            "goal": goal or f"run-shadow-{uuid.uuid4()}",
            "context_json": {},
            "priority": 1,
        },
    )
    assert response.status_code == 200
    return response.json()


def _create_plan(job_id: str) -> dict[str, str]:
    response = client.post(
        f"/plans?job_id={job_id}",
        json={
            "planner_version": "test",
            "tasks_summary": "List workspace files",
            "dag_edges": [],
            "tasks": [
                {
                    "name": "ListWorkspace",
                    "description": "List workspace files",
                    "instruction": "List the files in the workspace",
                    "acceptance_criteria": ["returns files"],
                    "expected_output_schema_ref": "schemas/workspace_listing",
                    "deps": [],
                    "tool_requests": ["filesystem.workspace.list"],
                    "tool_inputs": {"filesystem.workspace.list": {}},
                    "critic_required": False,
                }
            ],
        },
    )
    assert response.status_code == 200
    return response.json()


def _create_workflow_run() -> dict[str, dict]:
    create_response = client.post(
        "/workflows/definitions",
        json={
            "title": f"Workspace listing {uuid.uuid4()}",
            "goal": "List workspace files",
            "user_id": "narendersurabhi",
            "context_json": {"user_id": "narendersurabhi"},
            "draft": {
                "summary": "Workspace listing",
                "nodes": [
                    {
                        "id": "n1",
                        "taskName": "ListWorkspace",
                        "capabilityId": "filesystem.workspace.list",
                        "bindings": {},
                    }
                ],
                "edges": [],
            },
        },
    )
    assert create_response.status_code == 200
    definition = create_response.json()

    publish_response = client.post(f"/workflows/definitions/{definition['id']}/publish", json={})
    assert publish_response.status_code == 200
    version = publish_response.json()

    run_response = client.post(f"/workflows/versions/{version['id']}/run", json={"priority": 2})
    assert run_response.status_code == 200
    return run_response.json()


def test_create_job_surfaces_run_id_and_creates_shadow_run() -> None:
    job = _create_job()

    assert job["run_id"] == job["id"]

    with SessionLocal() as db:
        record = db.query(RunRecord).filter(RunRecord.id == job["run_id"]).first()
        assert record is not None
        assert record.job_id == job["id"]
        assert record.kind == models.RunKind.planner.value


def test_workflow_run_creates_shadow_run_with_workflow_run_id() -> None:
    run_body = _create_workflow_run()
    workflow_run = run_body["workflow_run"]
    job = run_body["job"]

    assert workflow_run["run_id"] == workflow_run["id"]
    assert job["run_id"] == workflow_run["id"]

    with SessionLocal() as db:
        record = db.query(RunRecord).filter(RunRecord.id == workflow_run["id"]).first()
        assert record is not None
        assert record.workflow_run_id == workflow_run["id"]
        assert record.job_id == job["id"]
        assert record.kind == models.RunKind.studio.value


def test_runs_list_and_get_return_shadow_run() -> None:
    job = _create_job()
    run_id = job["run_id"]

    list_response = client.get("/runs", params={"kind": models.RunKind.planner.value, "limit": 50})
    assert list_response.status_code == 200
    runs = list_response.json()
    matching = [run for run in runs if run["id"] == run_id]
    assert matching

    get_response = client.get(f"/runs/{run_id}")
    assert get_response.status_code == 200
    run = get_response.json()
    assert run["id"] == run_id
    assert run["job_id"] == job["id"]
    assert run["kind"] == models.RunKind.planner.value


def test_runs_steps_returns_shadow_steps_after_plan_creation() -> None:
    job = _create_job()
    _create_plan(job["id"])

    response = client.get(f"/runs/{job['run_id']}/steps")
    assert response.status_code == 200
    steps = response.json()

    assert len(steps) == 1
    assert steps[0]["run_id"] == job["run_id"]
    assert steps[0]["task_id"] == steps[0]["id"]
    assert steps[0]["spec_step_id"]
    assert steps[0]["capability_request_id"] == "filesystem.workspace.list"
    assert steps[0]["capability_id"] == "filesystem.workspace.list"


def test_run_debugger_includes_execution_requests() -> None:
    job = _create_job()
    _create_plan(job["id"])

    with SessionLocal() as db:
        task = db.query(TaskRecord).filter(TaskRecord.job_id == job["id"]).first()
        assert task is not None
        payload = main._task_payload_from_record(task, correlation_id=f"corr-{uuid.uuid4()}", context={})
        assert payload["task_id"] == task.id

    response = client.get(f"/runs/{job['run_id']}/debugger")
    assert response.status_code == 200
    debugger = response.json()

    assert debugger["run"]["id"] == job["run_id"]
    assert debugger["execution_requests"]
    assert debugger["steps"][0]["execution_requests"]
    assert debugger["execution_requests"][0]["run_id"] == job["run_id"]


def test_run_collaboration_context_indexes_blackboard_handoffs_and_artifacts() -> None:
    job = _create_job()
    _create_plan(job["id"])
    run_id = job["run_id"]

    blackboard_response = client.post(
        f"/runs/{run_id}/blackboard",
        json={
            "key": "finding:primary",
            "kind": "finding",
            "payload": {"summary": "Use the published workflow version."},
            "source_agent_id": "planner-agent",
            "visibility": "shared",
            "confidence": 0.9,
        },
    )
    assert blackboard_response.status_code == 200
    blackboard_entry = blackboard_response.json()
    assert blackboard_entry["run_id"] == run_id
    assert blackboard_entry["kind"] == "finding"

    handoff_response = client.post(
        f"/runs/{run_id}/handoffs",
        json={
            "from_agent_id": "planner-agent",
            "to_agent_id": "executor-agent",
            "objective": "Execute workspace listing",
            "summary": "Planner selected the filesystem listing capability.",
            "inputs": {"goal": job["goal"]},
            "outputs": {"next_step": "ListWorkspace"},
        },
    )
    assert handoff_response.status_code == 200
    handoff = handoff_response.json()
    assert handoff["run_id"] == run_id
    assert handoff["from_agent_id"] == "planner-agent"

    with SessionLocal() as db:
        task = db.query(TaskRecord).filter(TaskRecord.job_id == job["id"]).first()
        assert task is not None
        main._store_task_result(
            task.id,
            {
                "task_id": task.id,
                "run_id": run_id,
                "status": "completed",
                "outputs": {
                    "path": "artifacts/report.pdf",
                    "summary": "Generated report",
                },
                "artifacts": [{"type": "document", "path": "artifacts/report.pdf"}],
                "tool_calls": [],
            },
        )

    artifacts_response = client.get(f"/runs/{run_id}/artifacts")
    assert artifacts_response.status_code == 200
    artifacts = artifacts_response.json()
    assert [artifact for artifact in artifacts if artifact["path"] == "report.pdf"]

    context_response = client.get(f"/runs/{run_id}/context")
    assert context_response.status_code == 200
    context = context_response.json()
    assert context["state"]["run_id"] == run_id
    assert any(entry["kind"] == "finding" for entry in context["blackboard"])
    assert any(entry["kind"] == "task_snapshot" for entry in context["blackboard"])
    assert context["handoffs"][0]["to_agent_id"] == "executor-agent"
    assert any(artifact["path"] == "report.pdf" for artifact in context["artifacts"])

    debugger_response = client.get(f"/jobs/{job['id']}/debugger")
    assert debugger_response.status_code == 200
    debugger = debugger_response.json()
    assert debugger["run_state"]["run_id"] == run_id
    assert any(entry["kind"] == "finding" for entry in debugger["blackboard"])
    assert any(artifact["path"] == "report.pdf" for artifact in debugger["artifacts"])


def test_task_payload_includes_run_collaboration_context() -> None:
    job = _create_job()
    _create_plan(job["id"])
    run_id = job["run_id"]
    client.post(
        f"/runs/{run_id}/blackboard",
        json={
            "key": "decision:context",
            "kind": "decision",
            "payload": {"summary": "Share run context with worker payloads."},
        },
    )

    with SessionLocal() as db:
        task = db.query(TaskRecord).filter(TaskRecord.job_id == job["id"]).first()
        assert task is not None
        payload = main._task_payload_from_record(task, correlation_id=f"corr-{uuid.uuid4()}", context={})

    context = payload["context"]
    assert context["run_state"]["run_id"] == run_id
    assert any(entry["key"] == "decision:context" for entry in context["blackboard"])
    assert "handoffs" in context
    assert "artifacts" in context


def test_revision_context_includes_run_memory_snapshot() -> None:
    job = _create_job()
    _create_plan(job["id"])
    run_id = job["run_id"]

    client.post(
        f"/runs/{run_id}/blackboard",
        json={
            "key": "finding:api_rate_limit",
            "kind": "finding",
            "payload": {"summary": "Upstream API caps at 100 req/min."},
            "confidence": 0.8,
        },
    )
    client.post(
        f"/runs/{run_id}/handoffs",
        json={
            "from_agent_id": "researcher",
            "to_agent_id": "writer",
            "objective": "Draft the summary",
            "summary": "Findings gathered; writer to compose.",
            "assumptions": ["Rate limit respected"],
        },
    )

    with SessionLocal() as db:
        task = db.query(TaskRecord).filter(TaskRecord.job_id == job["id"]).first()
        assert task is not None
        # Storing a task result writes a task snapshot + indexes any artifacts.
        main._store_task_result(
            task.id,
            {
                "task_id": task.id,
                "run_id": run_id,
                "status": "completed",
                "outputs": {"path": "artifacts/findings.md", "summary": "Collected findings"},
                "artifacts": [{"type": "document", "path": "artifacts/findings.md"}],
                "tool_calls": [],
            },
        )

    with SessionLocal() as db:
        plan = (
            db.query(PlanRecord)
            .filter(PlanRecord.job_id == job["id"])
            .order_by(PlanRecord.created_at.desc())
            .first()
        )
        assert plan is not None
        revision = main._build_plan_revision_context(
            db,
            metadata={},
            active_plan=plan,
            reason="task_failed",
            context={},
        )

    snapshot = revision.run_memory_snapshot
    assert snapshot, "run_memory_snapshot should be populated from shared run memory"
    assert any(
        fact["key"] == "finding:api_rate_limit" for fact in snapshot.get("facts", [])
    )
    assert snapshot.get("task_snapshots"), "task snapshots should be present"
    assert snapshot.get("handoffs"), "handoffs should be present"
    assert snapshot["handoffs"][0]["to_agent_id"] == "writer"
    assert any(
        artifact["path"] == "findings.md" for artifact in snapshot.get("artifacts", [])
    )

    # The serialized revision context (what the planner prompt receives) carries it through.
    serialized = revision.model_dump(mode="json", exclude_none=True)
    assert "run_memory_snapshot" in serialized
    assert serialized["run_memory_snapshot"].get("facts")


def test_agent_registry_register_list_and_heartbeat() -> None:
    job = _create_job()
    _create_plan(job["id"])
    run_id = job["run_id"]

    register = client.post(
        f"/runs/{run_id}/agents",
        json={
            "agent_id": "researcher-1",
            "role": "researcher",
            "capabilities": ["memory.read", "filesystem.workspace.list"],
        },
    )
    assert register.status_code == 200
    agent = register.json()
    assert agent["agent_id"] == "researcher-1"
    assert agent["status"] == "idle"
    assert agent["last_heartbeat"] is not None
    first_heartbeat = agent["last_heartbeat"]

    # Re-register is idempotent (upsert) and refreshes heartbeat.
    client.post(
        f"/runs/{run_id}/agents",
        json={"agent_id": "writer-1", "role": "writer"},
    )
    listing = client.get(f"/runs/{run_id}/agents")
    assert listing.status_code == 200
    agents = listing.json()
    assert {a["agent_id"] for a in agents} == {"researcher-1", "writer-1"}

    # Status update + heartbeat.
    patch = client.patch(
        f"/runs/{run_id}/agents/researcher-1",
        json={"status": "running", "assigned_task_id": "ListWorkspace"},
    )
    assert patch.status_code == 200
    updated = patch.json()
    assert updated["status"] == "running"
    assert updated["assigned_task_id"] == "ListWorkspace"
    assert updated["last_heartbeat"] >= first_heartbeat

    missing = client.patch(f"/runs/{run_id}/agents/nope", json={"status": "done"})
    assert missing.status_code == 404


def test_agent_lock_acquire_conflict_release_and_steal() -> None:
    job = _create_job()
    _create_plan(job["id"])
    run_id = job["run_id"]

    acquire_a = client.post(
        f"/runs/{run_id}/locks",
        json={"resource": "shared-report", "agent_id": "agent-a", "ttl_seconds": 30},
    )
    assert acquire_a.status_code == 200
    assert acquire_a.json()["holder_agent_id"] == "agent-a"

    # A different agent cannot acquire the live lock.
    conflict = client.post(
        f"/runs/{run_id}/locks",
        json={"resource": "shared-report", "agent_id": "agent-b", "ttl_seconds": 30},
    )
    assert conflict.status_code == 409

    # The holder can refresh its own lock.
    refresh = client.post(
        f"/runs/{run_id}/locks",
        json={"resource": "shared-report", "agent_id": "agent-a", "ttl_seconds": 60},
    )
    assert refresh.status_code == 200

    locks = client.get(f"/runs/{run_id}/locks").json()
    assert [lock for lock in locks if lock["resource"] == "shared-report"]

    # Wrong agent cannot release.
    bad_release = client.delete(
        f"/runs/{run_id}/locks/shared-report", params={"agent_id": "agent-b"}
    )
    assert bad_release.status_code == 409

    # Holder releases; resource becomes free for another agent.
    release = client.delete(
        f"/runs/{run_id}/locks/shared-report", params={"agent_id": "agent-a"}
    )
    assert release.status_code == 200
    reacquire = client.post(
        f"/runs/{run_id}/locks",
        json={"resource": "shared-report", "agent_id": "agent-b", "ttl_seconds": 30},
    )
    assert reacquire.status_code == 200
    assert reacquire.json()["holder_agent_id"] == "agent-b"


def test_agent_lock_expired_lock_can_be_stolen() -> None:
    job = _create_job()
    _create_plan(job["id"])
    run_id = job["run_id"]

    # Acquire then force-expire the lock directly in the store.
    client.post(
        f"/runs/{run_id}/locks",
        json={"resource": "exclusive", "agent_id": "agent-a", "ttl_seconds": 30},
    )
    from services.api.app.models import AgentLockRecord

    with SessionLocal() as db:
        lock = (
            db.query(AgentLockRecord)
            .filter(AgentLockRecord.run_id == run_id, AgentLockRecord.resource == "exclusive")
            .first()
        )
        assert lock is not None
        lock.expires_at = datetime(2000, 1, 1, tzinfo=UTC)
        db.commit()

    # Expired lock is not listed as active and can be stolen by another agent.
    active = client.get(f"/runs/{run_id}/locks").json()
    assert not [lock for lock in active if lock["resource"] == "exclusive"]
    steal = client.post(
        f"/runs/{run_id}/locks",
        json={"resource": "exclusive", "agent_id": "agent-b", "ttl_seconds": 30},
    )
    assert steal.status_code == 200
    assert steal.json()["holder_agent_id"] == "agent-b"


def test_blackboard_private_visibility_filtering() -> None:
    job = _create_job()
    _create_plan(job["id"])
    run_id = job["run_id"]

    client.post(
        f"/runs/{run_id}/blackboard",
        json={
            "key": "private:agent-a:scratch",
            "kind": "note",
            "payload": {"summary": "Agent A working notes."},
            "source_agent_id": "agent-a",
            "visibility": "private",
        },
    )
    client.post(
        f"/runs/{run_id}/blackboard",
        json={
            "key": "shared:finding",
            "kind": "finding",
            "payload": {"summary": "Everyone can see this."},
            "source_agent_id": "agent-a",
            "visibility": "shared",
        },
    )

    # Owner sees both; another agent sees only the shared entry; anonymous sees shared.
    owner_view = client.get(f"/runs/{run_id}/blackboard", params={"agent_id": "agent-a"}).json()
    owner_keys = {entry["key"] for entry in owner_view}
    assert "private:agent-a:scratch" in owner_keys
    assert "shared:finding" in owner_keys

    other_view = client.get(f"/runs/{run_id}/blackboard", params={"agent_id": "agent-b"}).json()
    other_keys = {entry["key"] for entry in other_view}
    assert "private:agent-a:scratch" not in other_keys
    assert "shared:finding" in other_keys

    anon_view = client.get(f"/runs/{run_id}/blackboard").json()
    anon_keys = {entry["key"] for entry in anon_view}
    assert "private:agent-a:scratch" not in anon_keys
    assert "shared:finding" in anon_keys


def test_run_context_bundle_includes_agents_and_locks() -> None:
    job = _create_job()
    _create_plan(job["id"])
    run_id = job["run_id"]

    client.post(f"/runs/{run_id}/agents", json={"agent_id": "critic-1", "role": "critic"})
    client.post(
        f"/runs/{run_id}/locks",
        json={"resource": "doc", "agent_id": "critic-1", "ttl_seconds": 30},
    )

    context = client.get(f"/runs/{run_id}/context").json()
    assert any(agent["agent_id"] == "critic-1" for agent in context["agents"])
    assert any(lock["resource"] == "doc" for lock in context["locks"])

    debugger = client.get(f"/jobs/{job['id']}/debugger").json()
    assert any(agent["agent_id"] == "critic-1" for agent in debugger["agents"])
    assert any(lock["resource"] == "doc" for lock in debugger["locks"])


def test_agent_roster_resolver_capability_matching() -> None:
    roster = run_context_service.normalize_agent_roster(
        [
            {"role": "Researcher", "capabilities": ["memory.read", "filesystem.*"]},
            {"role": "Writer", "capabilities": ["llm.text.generate", "document.*"]},
            {"role": "Generalist"},  # no capabilities → wildcard fallback
        ]
    )
    assert [agent["agent_id"] for agent in roster] == ["researcher", "writer", "generalist"]

    researcher = run_context_service.resolve_agent_for_capabilities(
        roster, ["filesystem.workspace.list"]
    )
    assert researcher is not None and researcher["agent_id"] == "researcher"

    writer = run_context_service.resolve_agent_for_capabilities(roster, ["document.spec.generate"])
    assert writer is not None and writer["agent_id"] == "writer"

    # Unowned capability falls back to the wildcard (no-capabilities) agent.
    fallback = run_context_service.resolve_agent_for_capabilities(roster, ["github.repo.list"])
    assert fallback is not None and fallback["agent_id"] == "generalist"

    # Duplicate roles get deduped ids.
    dup = run_context_service.normalize_agent_roster([{"role": "critic"}, {"role": "critic"}])
    assert [agent["agent_id"] for agent in dup] == ["critic", "critic-2"]


def test_multi_agent_job_preregisters_team_and_constrains_capabilities() -> None:
    response = client.post(
        "/jobs",
        json={
            "goal": f"multi-agent-{uuid.uuid4()}",
            "context_json": {},
            "priority": 1,
            "agents": [
                {"role": "researcher", "capabilities": ["filesystem.workspace.list", "memory.read"]},
                {"role": "writer", "capabilities": ["llm.text.generate"]},
            ],
        },
    )
    assert response.status_code == 200
    job = response.json()
    run_id = job["run_id"]

    # Agents are pre-registered in the run's registry.
    agents = client.get(f"/runs/{run_id}/agents").json()
    assert {agent["agent_id"] for agent in agents} == {"researcher", "writer"}
    assert all(agent["status"] == "idle" for agent in agents)

    # Roster + combined capability allow-list are recorded on the job.
    with SessionLocal() as db:
        record = db.query(JobRecord).filter(JobRecord.id == job["id"]).first()
        assert record is not None
        metadata = record.metadata_json or {}
        roster = metadata.get("agents")
        assert isinstance(roster, list) and len(roster) == 2
        allowed = metadata.get("allowed_capability_ids")
        assert "filesystem.workspace.list" in allowed
        assert "llm.text.generate" in allowed


def test_multi_agent_task_assignment_and_attribution() -> None:
    response = client.post(
        "/jobs",
        json={
            "goal": f"multi-agent-assign-{uuid.uuid4()}",
            "context_json": {},
            "priority": 1,
            "agents": [
                {"role": "researcher", "capabilities": ["filesystem.workspace.list"]},
                {"role": "writer", "capabilities": ["llm.text.generate"]},
            ],
        },
    )
    assert response.status_code == 200
    job = response.json()
    run_id = job["run_id"]
    _create_plan(job["id"])  # task uses filesystem.workspace.list → owned by researcher

    # The task payload is stamped with the owning agent.
    with SessionLocal() as db:
        task = db.query(TaskRecord).filter(TaskRecord.job_id == job["id"]).first()
        assert task is not None
        payload = main._task_payload_from_record(task, correlation_id=f"corr-{uuid.uuid4()}", context={})
        assigned = payload["context"].get("assigned_agent")
        assert assigned is not None
        assert assigned["agent_id"] == "researcher"

        # Storing a result attributes artifacts to the producing agent.
        main._store_task_result(
            task.id,
            {
                "task_id": task.id,
                "run_id": run_id,
                "status": "completed",
                "outputs": {"path": "artifacts/listing.json"},
                "artifacts": [{"type": "document", "path": "artifacts/listing.json"}],
                "tool_calls": [],
            },
        )

    artifacts = client.get(f"/runs/{run_id}/artifacts").json()
    listing = [a for a in artifacts if a["path"] == "listing.json"]
    assert listing and listing[0]["producing_agent_id"] == "researcher"

    # The producing agent's registry row records the assignment.
    agents = client.get(f"/runs/{run_id}/agents").json()
    researcher = next(agent for agent in agents if agent["agent_id"] == "researcher")
    assert researcher["assigned_task_id"]


def test_agent_run_result_materializes_dynamic_agents_into_registry() -> None:
    job = _create_job()
    _create_plan(job["id"])
    run_id = job["run_id"]

    with SessionLocal() as db:
        task = db.query(TaskRecord).filter(TaskRecord.job_id == job["id"]).first()
        assert task is not None
        # Shape of an agent.run result: an 'agents' tree (self + spawned sub-agents).
        main._store_task_result(
            task.id,
            {
                "task_id": task.id,
                "run_id": run_id,
                "status": "completed",
                "result": "done",
                "agents": [
                    {"agent_id": "agent-run-d0-aaa", "role": "lead", "depth": 0, "status": "done", "steps_taken": 3},
                    {"agent_id": "agent-run-d1-bbb", "role": "agent", "depth": 1, "status": "done", "steps_taken": 2},
                ],
                "tool_calls": [],
            },
        )

    agents = client.get(f"/runs/{run_id}/agents").json()
    by_id = {agent["agent_id"]: agent for agent in agents}
    assert "agent-run-d0-aaa" in by_id
    assert "agent-run-d1-bbb" in by_id
    assert by_id["agent-run-d0-aaa"]["role"] == "lead"
    assert by_id["agent-run-d0-aaa"]["status"] == "done"
    # Spawn provenance is recorded in metadata.
    assert by_id["agent-run-d1-bbb"]["metadata"].get("spawned_by") == "agent.run"
    assert by_id["agent-run-d1-bbb"]["metadata"].get("depth") == 1

    # They surface in the run context bundle / debugger alongside static agents.
    context = client.get(f"/runs/{run_id}/context").json()
    assert {"agent-run-d0-aaa", "agent-run-d1-bbb"} <= {a["agent_id"] for a in context["agents"]}


def test_dynamic_agents_materialize_from_nested_agent_run_output() -> None:
    job = _create_job()
    _create_plan(job["id"])
    run_id = job["run_id"]

    with SessionLocal() as db:
        task = db.query(TaskRecord).filter(TaskRecord.job_id == job["id"]).first()
        assert task is not None
        # Real agent.run task-result shape: the agents tree is nested under the
        # per-tool outputs (and tool_calls), not at the result top level.
        main._store_task_result(
            task.id,
            {
                "task_id": task.id,
                "run_id": run_id,
                "status": "completed",
                "outputs": {
                    "agent_run": {
                        "result": "done",
                        "steps_taken": 2,
                        "agents": [
                            {"agent_id": "agent-run-d0-orch", "role": "orchestrator", "depth": 0, "status": "done"},
                            {"agent_id": "agent-run-d1-sub", "role": "agent", "depth": 1, "status": "done"},
                        ],
                    }
                },
                "tool_calls": [],
            },
        )

    agents = {a["agent_id"]: a for a in client.get(f"/runs/{run_id}/agents").json()}
    assert "agent-run-d0-orch" in agents
    assert "agent-run-d1-sub" in agents
    assert agents["agent-run-d0-orch"]["role"] == "orchestrator"
    assert agents["agent-run-d1-sub"]["metadata"].get("spawned_by") == "agent.run"


def test_spawn_agents_workflow_compiles_with_recursive_agent_run() -> None:
    from scripts.create_spawn_agents_workflow import build_spawn_agents_draft

    draft = build_spawn_agents_draft()
    response = client.post(
        "/composer/compile",
        json={"draft": draft, "goal": draft["summary"]},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["valid"], body["diagnostics"]

    plan = body["plan"]
    assert plan is not None
    agent_tasks = [
        task
        for task in plan["tasks"]
        if "agent.run" in (task.get("tool_requests") or [])
        or "agent.run" in (task.get("tool_inputs") or {})
    ]
    assert agent_tasks, "expected an agent.run task in the compiled plan"

    inputs = agent_tasks[0]["tool_inputs"]["agent.run"]
    assert inputs.get("goal"), "agent.run requires a goal"
    # The defining property of a spawn-agents workflow: the orchestrator may call
    # agent.run itself, i.e. it can delegate to recursively-spawned sub-agents.
    assert "agent.run" in inputs.get("allowed_capability_ids", [])


def test_compile_coerces_agent_run_allowed_capability_ids_scalar_literal() -> None:
    draft = {
        "summary": "Agent Orchestrator (spawns sub-agents)",
        "nodes": [
            {
                "id": "orchestrator",
                "taskName": "OrchestratorAgent",
                "capabilityId": "agent.run",
                "inputBindings": {
                    "goal": {
                        "kind": "literal",
                        "value": (
                            "Inspect the workspace, delegate research and drafting to "
                            "specialised sub-agents, then synthesise their results."
                        ),
                    },
                    "instructions": {"kind": "literal", "value": ""},
                    # Studio used to persist this scalar string for an array schema field,
                    # which later failed at dispatch with tool_inputs_invalid.
                    "allowed_capability_ids": {"kind": "literal", "value": "agent.run"},
                    "max_steps": {"kind": "literal", "value": "8"},
                },
            }
        ],
        "edges": [],
    }

    response = client.post(
        "/composer/compile",
        json={"draft": draft, "goal": draft["summary"]},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["valid"], body["diagnostics"]

    inputs = body["plan"]["tasks"][0]["tool_inputs"]["agent.run"]
    assert inputs["allowed_capability_ids"] == ["agent.run"]
    assert inputs["max_steps"] == 8


def test_workflow_version_plan_normalizes_stored_agent_run_inputs() -> None:
    run_spec = models.RunSpec(
        kind=models.RunKind.studio,
        planner_version="ui_chaining_composer_v2",
        tasks_summary="Agent Orchestrator (spawns sub-agents)",
        steps=[
            models.StepSpec(
                step_id="orchestratoragent",
                name="OrchestratorAgent",
                description="Run a general-purpose agentic loop.",
                instruction="Use capability agent.run.",
                capability_request=models.CapabilityRequestSpec(
                    request_id="agent.run",
                    capability_id="agent.run",
                    execution_request_id="agent_run",
                ),
                input_bindings={
                    "goal": "Inspect the workspace and delegate.",
                    "allowed_capability_ids": "agent.run",
                    "max_steps": "8",
                },
                acceptance_policy=models.StepAcceptancePolicy(
                    acceptance_criteria=["Completed capability agent.run"],
                    critic_required=False,
                ),
                routing_hints={
                    "tool_name": "agent_run",
                    "adapter_type": "tool",
                    "server_id": "local_worker",
                    "planner_request_field": "tool_requests",
                },
            )
        ],
        capability_requests=[
            models.CapabilityRequestSpec(
                request_id="agent.run",
                capability_id="agent.run",
                execution_request_id="agent_run",
            )
        ],
    )
    version = WorkflowVersionRecord(
        id=str(uuid.uuid4()),
        definition_id=str(uuid.uuid4()),
        version_number=1,
        title="Agent Orchestrator",
        goal="Inspect the workspace and delegate.",
        context_json={},
        draft_json={},
        compiled_plan_json={},
        user_id=None,
        metadata_json={"run_spec": run_spec.model_dump(mode="json")},
        created_at=_utcnow(),
    )

    plan = main._workflow_version_plan(version)

    assert plan is not None
    inputs = plan.tasks[0].tool_inputs["agent.run"]
    assert inputs["allowed_capability_ids"] == ["agent.run"]
    assert inputs["max_steps"] == 8


def test_compile_flags_agent_run_missing_required_goal() -> None:
    # A bare agent.run node (no inputs) must be flagged by the Readiness Check
    # before it can run and fail at dispatch with tool_inputs_invalid.
    bare = {
        "summary": "bare orchestrator",
        "nodes": [
            {
                "id": "orchestrator",
                "taskName": "OrchestratorAgent",
                "capabilityId": "agent.run",
                "bindings": {},
            }
        ],
        "edges": [],
    }
    response = client.post("/composer/compile", json={"draft": bare, "goal": "bare"})
    assert response.status_code == 200
    body = response.json()
    assert body["valid"] is False
    errors = body["diagnostics"]["errors"]
    missing = [e for e in errors if e.get("code") == "draft.required_input_missing"]
    assert any(e.get("field") == "goal" for e in missing), errors

    # Binding the required goal clears the error.
    bare["nodes"][0]["bindings"] = {"goal": {"kind": "literal", "value": "do the thing"}}
    ok = client.post("/composer/compile", json={"draft": bare, "goal": "bare"}).json()
    assert ok["valid"] is True, ok["diagnostics"]


def test_spawn_agents_workflow_definition_round_trips() -> None:
    from scripts.create_spawn_agents_workflow import build_definition_payload

    create = client.post(
        "/workflows/definitions",
        json=build_definition_payload(user_id="narendersurabhi"),
    )
    assert create.status_code == 200
    definition = create.json()
    assert definition["title"] == "Agent Orchestrator"

    fetched = client.get(f"/workflows/definitions/{definition['id']}").json()
    nodes = fetched["draft"]["nodes"]
    orchestrator = next(node for node in nodes if node["capabilityId"] == "agent.run")
    allowed = orchestrator["bindings"]["allowed_capability_ids"]["value"]
    assert "agent.run" in allowed
    # Note: publishing additionally requires a live worker whose agent_run tool
    # adapter is loaded (runtime conformance) — not available in this harness.


def test_execution_request_snapshot_captures_retry_policy_and_context_provenance() -> None:
    job = _create_job()
    _create_plan(job["id"])

    with SessionLocal() as db:
        task = db.query(TaskRecord).filter(TaskRecord.job_id == job["id"]).first()
        assert task is not None
        payload = main._task_payload_from_record(
            task,
            correlation_id=f"corr-{uuid.uuid4()}",
            context={
                "job_context": {"workspace_id": "demo"},
                "dependencies": {"dep-1": {"status": "completed"}},
                "dependencies_by_name": {"ListWorkspace": {"files": []}},
            },
        )
        assert payload["task_id"] == task.id
        record = (
            db.query(ExecutionRequestRecord)
            .filter(ExecutionRequestRecord.run_id == job["run_id"])
            .first()
        )
        assert record is not None
        assert record.request_id == "workspace_list_files"
        assert record.capability_id == "filesystem.workspace.list"
        assert record.retry_policy_json["max_attempts"] == 3
        assert record.retry_policy_json["max_reworks"] == 2
        assert record.policy_snapshot_json["critic_required"] is False
        assert "job_context_keys" in record.context_provenance_json
        assert record.context_provenance_json["job_context_keys"] == ["workspace_id"]


def test_task_started_and_heartbeat_update_attempt_leases_and_execution_request() -> None:
    job = _create_job()
    _create_plan(job["id"])
    correlation_id = f"corr-{uuid.uuid4()}"

    with SessionLocal() as db:
        task = db.query(TaskRecord).filter(TaskRecord.job_id == job["id"]).first()
        assert task is not None
        main._task_payload_from_record(task, correlation_id=correlation_id, context={})
        task_id = task.id

    started_at = _utcnow()
    main._handle_event(
        "tasks.events",
        {
            "data": json.dumps(
                {
                    "type": "task.started",
                    "job_id": job["id"],
                    "task_id": task_id,
                    "occurred_at": started_at.isoformat(),
                    "payload": {
                        "task_id": task_id,
                        "attempts": 1,
                        "max_attempts": 3,
                        "worker_consumer": "worker-phase2",
                    },
                    "correlation_id": correlation_id,
                }
            )
        },
    )

    heartbeat_at = _utcnow()
    main._handle_event(
        "tasks.events",
        {
            "data": json.dumps(
                {
                    "type": "task.heartbeat",
                    "job_id": job["id"],
                    "task_id": task_id,
                    "occurred_at": heartbeat_at.isoformat(),
                    "payload": {
                        "task_id": task_id,
                        "attempts": 1,
                        "status": "heartbeat",
                        "worker_consumer": "worker-phase2",
                    },
                    "correlation_id": correlation_id,
                }
            )
        },
    )

    with SessionLocal() as db:
        attempt = db.query(StepAttemptRecord).filter(StepAttemptRecord.step_id == task_id).first()
        request = (
            db.query(ExecutionRequestRecord)
            .filter(ExecutionRequestRecord.run_id == job["run_id"])
            .first()
        )
        assert attempt is not None
        assert request is not None
        assert attempt.lease_owner == "worker-phase2"
        assert attempt.last_heartbeat_at is not None
        assert attempt.lease_expires_at is not None
        assert attempt.heartbeat_count == 1
        assert request.status == "heartbeat"
        assert request.lease_owner == "worker-phase2"
        assert request.last_heartbeat_at is not None
        assert request.lease_expires_at is not None


def test_task_started_accepts_existing_naive_step_attempt_timestamp() -> None:
    job = _create_job()
    _create_plan(job["id"])
    correlation_id = f"corr-{uuid.uuid4()}"

    with SessionLocal() as db:
        task = db.query(TaskRecord).filter(TaskRecord.job_id == job["id"]).first()
        assert task is not None
        main._task_payload_from_record(task, correlation_id=correlation_id, context={})
        task_id = task.id

    started_at = _utcnow()
    main._handle_event(
        "tasks.events",
        {
            "data": json.dumps(
                {
                    "type": "task.started",
                    "job_id": job["id"],
                    "task_id": task_id,
                    "occurred_at": started_at.isoformat(),
                    "payload": {
                        "task_id": task_id,
                        "attempts": 1,
                        "worker_consumer": "worker-phase2",
                    },
                    "correlation_id": correlation_id,
                }
            )
        },
    )

    with SessionLocal() as db:
        attempt = db.query(StepAttemptRecord).filter(StepAttemptRecord.step_id == task_id).first()
        assert attempt is not None
        attempt.started_at = started_at.replace(tzinfo=None)
        db.commit()

    main._handle_event(
        "tasks.events",
        {
            "data": json.dumps(
                {
                    "type": "task.started",
                    "job_id": job["id"],
                    "task_id": task_id,
                    "occurred_at": started_at.isoformat(),
                    "payload": {
                        "task_id": task_id,
                        "attempts": 1,
                        "worker_consumer": "worker-phase2",
                    },
                    "correlation_id": correlation_id,
                }
            )
        },
    )

    with SessionLocal() as db:
        attempt = db.query(StepAttemptRecord).filter(StepAttemptRecord.step_id == task_id).first()
        assert attempt is not None
        assert attempt.status == models.TaskStatus.running.value


def test_task_completed_ignores_missing_step_attempt_on_execution_request(monkeypatch) -> None:
    job = _create_job()
    _create_plan(job["id"])
    correlation_id = f"corr-{uuid.uuid4()}"

    with SessionLocal() as db:
        task = db.query(TaskRecord).filter(TaskRecord.job_id == job["id"]).first()
        assert task is not None
        main._task_payload_from_record(task, correlation_id=correlation_id, context={})
        task_id = task.id

    def _fake_finished_attempt(*_args, **_kwargs) -> StepAttemptRecord:
        return StepAttemptRecord(
            id="missing-step-attempt-id",
            run_id=job["run_id"],
            job_id=job["id"],
            step_id=task_id,
            attempt_number=1,
            status=models.TaskStatus.completed.value,
            worker_id="worker-phase2",
            started_at=_utcnow(),
            finished_at=_utcnow(),
            error_code=None,
            error_message=None,
            retry_classification="succeeded",
            lease_owner="worker-phase2",
            lease_expires_at=_utcnow(),
            last_heartbeat_at=_utcnow(),
            heartbeat_count=0,
            result_summary_json={},
        )

    monkeypatch.setattr(main, "_upsert_step_attempt_finished", _fake_finished_attempt)

    main._handle_event(
        "tasks.events",
        {
            "data": json.dumps(
                {
                    "type": "task.completed",
                    "job_id": job["id"],
                    "task_id": task_id,
                    "occurred_at": _utcnow().isoformat(),
                    "payload": {
                        "task_id": task_id,
                        "attempts": 1,
                        "worker_consumer": "worker-phase2",
                        "outputs": {"ok": True},
                    },
                    "correlation_id": correlation_id,
                }
            )
        },
    )

    with SessionLocal() as db:
        request = (
            db.query(ExecutionRequestRecord)
            .filter(ExecutionRequestRecord.run_id == job["run_id"])
            .first()
        )
        assert request is not None
        assert request.status == models.TaskStatus.completed.value
        assert request.step_attempt_id is None


def test_run_control_endpoints_delegate_to_job_lifecycle(monkeypatch) -> None:
    monkeypatch.setattr(main, "_dispatch_ready_work_for_job", lambda *_args, **_kwargs: None)

    job = _create_job()
    _create_plan(job["id"])
    run_id = job["run_id"]

    cancel_response = client.post(f"/runs/{run_id}/cancel")
    assert cancel_response.status_code == 200
    assert cancel_response.json()["status"] == models.JobStatus.canceled.value

    with SessionLocal() as db:
        job_record = db.query(JobRecord).filter(JobRecord.id == job["id"]).first()
        assert job_record is not None
        assert job_record.status == models.JobStatus.canceled.value

    continue_response = client.post(f"/runs/{run_id}/continue")
    assert continue_response.status_code == 200
    assert continue_response.json()["status"] == models.JobStatus.planning.value

    with SessionLocal() as db:
        job_record = db.query(JobRecord).filter(JobRecord.id == job["id"]).first()
        task_record = db.query(TaskRecord).filter(TaskRecord.job_id == job["id"]).first()
        assert job_record is not None
        assert task_record is not None
        job_record.status = models.JobStatus.failed.value
        job_record.updated_at = _utcnow()
        task_record.status = models.TaskStatus.failed.value
        task_record.attempts = 2
        task_record.rework_count = 1
        task_record.updated_at = _utcnow()
        db.commit()

    retry_response = client.post(f"/runs/{run_id}/retry")
    assert retry_response.status_code == 200
    assert retry_response.json()["status"] == models.JobStatus.planning.value

    with SessionLocal() as db:
        job_record = db.query(JobRecord).filter(JobRecord.id == job["id"]).first()
        task_record = db.query(TaskRecord).filter(TaskRecord.job_id == job["id"]).first()
        assert job_record is not None
        assert task_record is not None
        assert job_record.status == models.JobStatus.planning.value
        assert task_record.status == models.TaskStatus.pending.value
        assert task_record.attempts == 0
        assert task_record.rework_count == 0


def test_clear_job_deletes_shadow_run_records() -> None:
    job = _create_job()
    _create_plan(job["id"])
    run_id = job["run_id"]

    with SessionLocal() as db:
        task = db.query(TaskRecord).filter(TaskRecord.job_id == job["id"]).first()
        assert task is not None
        main._task_payload_from_record(task, correlation_id=f"corr-{uuid.uuid4()}", context={})
        checkpoint = StepCheckpointRecord(
            id=f"checkpoint-{uuid.uuid4()}",
            run_id=run_id,
            job_id=job["id"],
            step_id=task.id,
            step_attempt_id=None,
            checkpoint_key="initial",
            payload_json={"stage": "prepared"},
            input_digest="digest",
            replay_count=0,
            source="test",
            outcome="pending",
            created_at=_utcnow(),
            updated_at=_utcnow(),
        )
        db.add(checkpoint)
        db.commit()

    response = client.post(f"/jobs/{job['id']}/clear")
    assert response.status_code == 200
    assert response.json()["status"] == "cleared"

    with SessionLocal() as db:
        assert db.query(RunRecord).filter(RunRecord.id == run_id).first() is None
        assert db.query(RunStepRecord).filter(RunStepRecord.run_id == run_id).first() is None
        assert (
            db.query(ExecutionRequestRecord)
            .filter(ExecutionRequestRecord.run_id == run_id)
            .first()
            is None
        )
        assert db.query(StepCheckpointRecord).filter(StepCheckpointRecord.run_id == run_id).first() is None
