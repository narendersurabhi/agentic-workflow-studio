from __future__ import annotations

import hashlib
import mimetypes
import os
import re
import uuid
from collections.abc import Iterable, Mapping, Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from libs.core import models

from . import memory_store
from .models import (
    AgentHandoffRecord,
    AgentLockRecord,
    AgentRegistryRecord,
    ArtifactRecord,
    MemoryRecord,
    RunEventRecord,
    RunRecord,
    RunStepRecord,
    StepAttemptRecord,
    TaskResultRecord,
)


ARTIFACT_EXTENSIONS = {
    ".csv",
    ".docx",
    ".html",
    ".jpeg",
    ".jpg",
    ".json",
    ".md",
    ".pdf",
    ".png",
    ".pptx",
    ".svg",
    ".txt",
    ".xlsx",
    ".xml",
    ".yaml",
    ".yml",
    ".zip",
}
ARTIFACTS_DIR = os.getenv("ARTIFACTS_DIR", "/shared/artifacts")


def utcnow() -> datetime:
    return datetime.now(UTC)


def _as_aware(value: datetime | None) -> datetime | None:
    """Normalise a (possibly naive, e.g. SQLite-stored) datetime to UTC-aware."""
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value


def get_run_record(db: Session, run_id: str) -> RunRecord | None:
    return db.query(RunRecord).filter(RunRecord.id == run_id).first()


def get_run_state(db: Session, run_id: str) -> models.RunStateSnapshot:
    run_record = get_run_record(db, run_id)
    if run_record is None:
        raise KeyError("run_not_found")
    steps = db.query(RunStepRecord).filter(RunStepRecord.run_id == run_id).all()
    attempts = db.query(StepAttemptRecord).filter(StepAttemptRecord.run_id == run_id).all()
    latest_event = (
        db.query(RunEventRecord)
        .filter(RunEventRecord.run_id == run_id)
        .order_by(RunEventRecord.occurred_at.desc())
        .first()
    )
    latest_step = sorted(
        steps,
        key=lambda step: step.updated_at or step.created_at,
        reverse=True,
    )[0] if steps else None
    latest_error = _latest_error_for_run(db, run_record)
    return models.RunStateSnapshot(
        run_id=run_record.id,
        job_id=run_record.job_id,
        kind=run_record.kind,
        status=run_record.status,
        title=run_record.title,
        goal=run_record.goal,
        plan_id=run_record.plan_id,
        workflow_run_id=run_record.workflow_run_id,
        step_counts=_count_by_status(step.status for step in steps),
        attempt_counts=_count_by_status(attempt.status for attempt in attempts),
        latest_step_id=latest_step.id if latest_step is not None else None,
        latest_step_name=latest_step.name if latest_step is not None else None,
        latest_step_status=latest_step.status if latest_step is not None else None,
        latest_error=latest_error,
        latest_event_at=latest_event.occurred_at if latest_event is not None else None,
        metadata=run_record.metadata_json or {},
        created_at=run_record.created_at,
        updated_at=run_record.updated_at,
    )


def list_blackboard_entries(
    db: Session,
    run_id: str,
    *,
    kind: str | None = None,
    limit: int = 100,
    agent_id: str | None = None,
) -> list[models.BlackboardEntry]:
    run_record = _require_run(db, run_id)
    requester = _clean_optional(agent_id)
    entries: list[models.BlackboardEntry] = []
    for name in ("run_blackboard", "run_task_snapshots"):
        records = (
            db.query(MemoryRecord)
            .filter(
                MemoryRecord.name == name,
                MemoryRecord.scope == models.MemoryScope.session.value,
                MemoryRecord.job_id == run_record.job_id,
            )
            .order_by(MemoryRecord.updated_at.desc())
            .limit(max(1, min(limit, 500)))
            .all()
        )
        for record in records:
            entry = _blackboard_entry_from_memory(run_record, record)
            if kind and entry.kind != kind:
                continue
            if not _entry_visible_to(entry, requester):
                continue
            entries.append(entry)
    entries.sort(key=lambda entry: entry.updated_at, reverse=True)
    return entries[: max(1, min(limit, 500))]


def _entry_visible_to(entry: models.BlackboardEntry, requester: str | None) -> bool:
    """Private entries are only visible to their author; shared entries to all."""
    if str(entry.visibility or "shared").strip().lower() != "private":
        return True
    if requester is None:
        return False
    return entry.source_agent_id == requester


def create_blackboard_entry(
    db: Session,
    run_id: str,
    request: models.BlackboardEntryCreate,
) -> models.BlackboardEntry:
    run_record = _require_run(db, run_id)
    key = request.key or f"{request.kind}:{uuid.uuid4()}"
    metadata = dict(request.metadata or {})
    metadata.update(
        {
            "run_id": run_record.id,
            "kind": request.kind,
            "source_agent_id": request.source_agent_id,
            "step_id": request.step_id,
            "task_id": request.task_id,
            "visibility": request.visibility,
        }
    )
    if request.confidence is not None:
        metadata["confidence"] = request.confidence
    entry = memory_store.write_memory(
        db,
        models.MemoryWrite(
            name="run_blackboard",
            job_id=run_record.job_id,
            key=key,
            payload={
                "kind": request.kind,
                "payload": request.payload,
                "source_agent_id": request.source_agent_id,
                "step_id": request.step_id,
                "task_id": request.task_id,
                "visibility": request.visibility,
                "confidence": request.confidence,
            },
            metadata=metadata,
            ttl_seconds=request.ttl_seconds,
        ),
    )
    return _blackboard_entry_from_memory_entry(run_record, entry)


def write_task_snapshot(
    db: Session,
    *,
    run_id: str,
    step_id: str,
    summary: Mapping[str, Any],
    task_id: str | None = None,
) -> models.BlackboardEntry | None:
    run_record = get_run_record(db, run_id)
    if run_record is None:
        return None
    key = f"task:{task_id or step_id}"
    entry = memory_store.write_memory(
        db,
        models.MemoryWrite(
            name="run_task_snapshots",
            job_id=run_record.job_id,
            key=key,
            payload={"kind": "task_snapshot", "payload": dict(summary)},
            metadata={
                "run_id": run_record.id,
                "kind": "task_snapshot",
                "step_id": step_id,
                "task_id": task_id or step_id,
                "visibility": "shared",
            },
        ),
    )
    return _blackboard_entry_from_memory_entry(run_record, entry)


def create_handoff(
    db: Session,
    run_id: str,
    request: models.AgentHandoffCreate,
) -> models.AgentHandoff:
    run_record = _require_run(db, run_id)
    now = utcnow()
    record = AgentHandoffRecord(
        id=str(uuid.uuid4()),
        run_id=run_record.id,
        job_id=run_record.job_id,
        from_agent_id=_clean_optional(request.from_agent_id),
        to_agent_id=_clean_optional(request.to_agent_id),
        step_id=_clean_optional(request.step_id),
        task_id=_clean_optional(request.task_id),
        objective=request.objective,
        summary=request.summary,
        inputs_json=dict(request.inputs or {}),
        outputs_json=dict(request.outputs or {}),
        assumptions_json=list(request.assumptions or []),
        risks_json=list(request.risks or []),
        artifact_ids_json=list(request.artifact_ids or []),
        metadata_json=dict(request.metadata or {}),
        created_at=now,
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    return handoff_from_record(record)


def list_handoffs(
    db: Session,
    run_id: str,
    *,
    limit: int = 100,
) -> list[models.AgentHandoff]:
    _require_run(db, run_id)
    rows = (
        db.query(AgentHandoffRecord)
        .filter(AgentHandoffRecord.run_id == run_id)
        .order_by(AgentHandoffRecord.created_at.asc())
        .limit(max(1, min(limit, 500)))
        .all()
    )
    return [handoff_from_record(row) for row in rows]


def create_artifact(
    db: Session,
    run_id: str,
    request: models.ArtifactCreate,
) -> models.Artifact:
    run_record = _require_run(db, run_id)
    record = upsert_artifact(
        db,
        run_record=run_record,
        artifact_type=request.artifact_type,
        path=request.path,
        step_id=request.step_id,
        task_id=request.task_id,
        producing_agent_id=request.producing_agent_id,
        storage_key=request.storage_key,
        mime_type=request.mime_type,
        size_bytes=request.size_bytes,
        sha256=request.sha256,
        metadata=request.metadata,
    )
    db.commit()
    db.refresh(record)
    return artifact_from_record(record)


def list_artifacts(
    db: Session,
    run_id: str,
    *,
    limit: int = 100,
) -> list[models.Artifact]:
    _require_run(db, run_id)
    rows = (
        db.query(ArtifactRecord)
        .filter(ArtifactRecord.run_id == run_id)
        .order_by(ArtifactRecord.created_at.asc())
        .limit(max(1, min(limit, 500)))
        .all()
    )
    return [artifact_from_record(row) for row in rows]


def get_artifact(db: Session, artifact_id: str) -> models.Artifact | None:
    record = db.query(ArtifactRecord).filter(ArtifactRecord.id == artifact_id).first()
    return artifact_from_record(record) if record is not None else None


# ── Agent registry ────────────────────────────────────────────────────────────


def register_agent(
    db: Session,
    run_id: str,
    request: models.AgentRegistration,
) -> models.AgentDescriptor:
    run_record = _require_run(db, run_id)
    agent_id = _clean_optional(request.agent_id)
    if agent_id is None:
        raise ValueError("agent_id_required")
    now = utcnow()
    record = (
        db.query(AgentRegistryRecord)
        .filter(
            AgentRegistryRecord.run_id == run_record.id,
            AgentRegistryRecord.agent_id == agent_id,
        )
        .first()
    )
    if record is None:
        record = AgentRegistryRecord(
            id=str(uuid.uuid4()),
            run_id=run_record.id,
            job_id=run_record.job_id,
            agent_id=agent_id,
            role=request.role or "",
            status=request.status or "idle",
            assigned_task_id=_clean_optional(request.assigned_task_id),
            capabilities_json=list(request.capabilities or []),
            metadata_json=dict(request.metadata or {}),
            last_heartbeat=now,
            created_at=now,
            updated_at=now,
        )
        db.add(record)
    else:
        record.role = request.role or record.role
        record.status = request.status or record.status
        if request.assigned_task_id is not None:
            record.assigned_task_id = _clean_optional(request.assigned_task_id)
        if request.capabilities:
            record.capabilities_json = list(request.capabilities)
        if request.metadata:
            record.metadata_json = {**dict(record.metadata_json or {}), **dict(request.metadata)}
        record.last_heartbeat = now
        record.updated_at = now
    db.commit()
    db.refresh(record)
    return agent_from_record(record)


def update_agent_status(
    db: Session,
    run_id: str,
    agent_id: str,
    request: models.AgentStatusUpdate,
) -> models.AgentDescriptor:
    run_record = _require_run(db, run_id)
    record = (
        db.query(AgentRegistryRecord)
        .filter(
            AgentRegistryRecord.run_id == run_record.id,
            AgentRegistryRecord.agent_id == agent_id,
        )
        .first()
    )
    if record is None:
        raise KeyError("agent_not_found")
    now = utcnow()
    if request.status is not None:
        record.status = request.status
    if request.role is not None:
        record.role = request.role
    if request.assigned_task_id is not None:
        record.assigned_task_id = _clean_optional(request.assigned_task_id)
    if request.metadata:
        record.metadata_json = {**dict(record.metadata_json or {}), **dict(request.metadata)}
    if request.heartbeat:
        record.last_heartbeat = now
    record.updated_at = now
    db.commit()
    db.refresh(record)
    return agent_from_record(record)


def list_agents(db: Session, run_id: str) -> list[models.AgentDescriptor]:
    run_record = _require_run(db, run_id)
    rows = (
        db.query(AgentRegistryRecord)
        .filter(AgentRegistryRecord.run_id == run_record.id)
        .order_by(AgentRegistryRecord.created_at.asc())
        .all()
    )
    return [agent_from_record(row) for row in rows]


def _collect_reported_agents(result: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Gather agent.run agent descriptors from a task result.

    agent.run returns ``agents`` in its own output, but the worker nests that
    under the task result's per-tool ``outputs`` and ``tool_calls`` rather than
    promoting it to the top level. Collect from all three locations and dedupe
    by agent_id (first occurrence wins).
    """
    collected: list[dict[str, Any]] = []
    seen: set[str] = set()

    def _take(candidate: Any) -> None:
        if not isinstance(candidate, Sequence) or isinstance(candidate, (str, bytes)):
            return
        for entry in candidate:
            if not isinstance(entry, Mapping):
                continue
            agent_id = _clean_optional(entry.get("agent_id"))
            if agent_id is None or agent_id in seen:
                continue
            seen.add(agent_id)
            collected.append(dict(entry))

    _take(result.get("agents"))
    outputs = result.get("outputs")
    if isinstance(outputs, Mapping):
        for value in outputs.values():
            if isinstance(value, Mapping):
                _take(value.get("agents"))
    tool_calls = result.get("tool_calls")
    if isinstance(tool_calls, Sequence) and not isinstance(tool_calls, (str, bytes)):
        for call in tool_calls:
            if isinstance(call, Mapping):
                output = call.get("output_or_error")
                if isinstance(output, Mapping):
                    _take(output.get("agents"))
    return collected


def materialize_dynamic_agents(
    db: Session,
    *,
    run_record: RunRecord,
    result: Mapping[str, Any],
    task_id: str | None = None,
) -> list[str]:
    """Register agents reported by an agent.run result into the durable registry.

    An agent.run result carries an ``agents`` list (this invocation + every
    recursively spawned sub-agent). Each is upserted into agent_registry so the
    orchestrator's runtime-spawned agents become first-class citizens — visible
    in the Agents panel and available for attribution. Best-effort.
    """
    if not isinstance(result, Mapping):
        return []
    reported = _collect_reported_agents(result)
    if not reported:
        return []
    registered: list[str] = []
    now = utcnow()
    for entry in reported:
        if not isinstance(entry, Mapping):
            continue
        agent_id = _clean_optional(entry.get("agent_id"))
        if agent_id is None:
            continue
        status = _clean_optional(entry.get("status")) or "done"
        role = _clean_optional(entry.get("role")) or "agent"
        metadata = {
            "spawned_by": "agent.run",
            "depth": entry.get("depth"),
            "steps_taken": entry.get("steps_taken"),
            "goal": entry.get("goal"),
            "origin_task_id": task_id,
        }
        existing = (
            db.query(AgentRegistryRecord)
            .filter(
                AgentRegistryRecord.run_id == run_record.id,
                AgentRegistryRecord.agent_id == agent_id,
            )
            .first()
        )
        if existing is None:
            db.add(
                AgentRegistryRecord(
                    id=str(uuid.uuid4()),
                    run_id=run_record.id,
                    job_id=run_record.job_id,
                    agent_id=agent_id,
                    role=role,
                    status=status,
                    assigned_task_id=task_id,
                    capabilities_json=[],
                    metadata_json={k: v for k, v in metadata.items() if v is not None},
                    last_heartbeat=now,
                    created_at=now,
                    updated_at=now,
                )
            )
        else:
            existing.status = status
            existing.role = existing.role or role
            if task_id:
                existing.assigned_task_id = task_id
            existing.metadata_json = {
                **dict(existing.metadata_json or {}),
                **{k: v for k, v in metadata.items() if v is not None},
            }
            existing.last_heartbeat = now
            existing.updated_at = now
        registered.append(agent_id)
    if registered:
        db.flush()
    return registered


def agent_from_record(record: AgentRegistryRecord) -> models.AgentDescriptor:
    return models.AgentDescriptor(
        id=record.id,
        run_id=record.run_id,
        job_id=record.job_id,
        agent_id=record.agent_id,
        role=record.role or "",
        status=record.status or "idle",
        assigned_task_id=record.assigned_task_id,
        capabilities=list(record.capabilities_json or []),
        metadata=dict(record.metadata_json or {}),
        last_heartbeat=record.last_heartbeat,
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


# ── Multi-agent roster (capability-team assignment) ────────────────────────────


def _slugify_agent_id(value: str) -> str:
    cleaned = re.sub(r"[^a-z0-9]+", "-", str(value or "").strip().lower()).strip("-")
    return cleaned or "agent"


def normalize_agent_roster(specs: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Normalise raw agent specs into a deterministic roster with unique ids."""
    roster: list[dict[str, Any]] = []
    used_ids: set[str] = set()
    for spec in specs:
        if not isinstance(spec, Mapping):
            continue
        role = str(spec.get("role") or "").strip()
        raw_id = str(spec.get("agent_id") or "").strip()
        base_id = _slugify_agent_id(raw_id or role or f"agent-{len(roster) + 1}")
        agent_id = base_id
        suffix = 2
        while agent_id in used_ids:
            agent_id = f"{base_id}-{suffix}"
            suffix += 1
        used_ids.add(agent_id)
        capabilities = [
            str(cap).strip()
            for cap in (spec.get("capabilities") or [])
            if isinstance(cap, str) and str(cap).strip()
        ]
        roster.append(
            {
                "agent_id": agent_id,
                "role": role or agent_id,
                "capabilities": capabilities,
                "metadata": dict(spec.get("metadata") or {}),
            }
        )
    return roster


def capability_matches(patterns: Sequence[str], capability_id: str) -> bool:
    """True if capability_id matches any pattern (exact, 'prefix.*', or '*')."""
    candidate = str(capability_id or "").strip()
    if not candidate:
        return False
    for raw_pattern in patterns:
        pattern = str(raw_pattern or "").strip()
        if not pattern or pattern == "*":
            return True
        if pattern == candidate:
            return True
        if pattern.endswith(".*") and candidate.startswith(pattern[:-1]):
            return True
        if pattern.endswith("*") and candidate.startswith(pattern[:-1]):
            return True
    return False


def resolve_agent_for_capabilities(
    roster: Sequence[Mapping[str, Any]],
    capability_ids: Sequence[str],
) -> dict[str, Any] | None:
    """Return the first roster agent whose capabilities cover any of the task's.

    Agents with no declared capabilities act as wildcard owners only when no
    capability-scoped agent matches.
    """
    wildcard: dict[str, Any] | None = None
    for agent in roster:
        if not isinstance(agent, Mapping):
            continue
        patterns = agent.get("capabilities") or []
        if not patterns:
            if wildcard is None:
                wildcard = dict(agent)
            continue
        for capability_id in capability_ids:
            if capability_matches(patterns, capability_id):
                return dict(agent)
    return wildcard


# ── Distributed locks (durable, TTL via expires_at) ────────────────────────────


def acquire_lock(
    db: Session,
    run_id: str,
    request: models.AgentLockRequest,
) -> models.AgentLock | None:
    """Acquire a named lock for an agent.

    Returns the lock when granted (newly acquired, re-acquired by the same
    holder, or stolen after the prior holder's TTL expired); returns None when
    the resource is currently held by a different live agent.
    """
    run_record = _require_run(db, run_id)
    resource = _clean_optional(request.resource)
    agent_id = _clean_optional(request.agent_id)
    if resource is None or agent_id is None:
        raise ValueError("resource_and_agent_id_required")
    now = utcnow()
    ttl = max(1, int(request.ttl_seconds or 30))
    expires_at = now + timedelta(seconds=ttl)
    existing = (
        db.query(AgentLockRecord)
        .filter(
            AgentLockRecord.run_id == run_record.id,
            AgentLockRecord.resource == resource,
        )
        .first()
    )
    if existing is not None:
        existing_expiry = _as_aware(existing.expires_at)
        live = existing_expiry is None or existing_expiry > now
        if live and existing.holder_agent_id != agent_id:
            return None  # held by another live agent
        # Same holder (refresh) or expired lock (steal).
        existing.holder_agent_id = agent_id
        existing.job_id = run_record.job_id
        existing.acquired_at = now
        existing.expires_at = expires_at
        if request.metadata:
            existing.metadata_json = {**dict(existing.metadata_json or {}), **dict(request.metadata)}
        db.commit()
        db.refresh(existing)
        return lock_from_record(existing)
    record = AgentLockRecord(
        id=str(uuid.uuid4()),
        run_id=run_record.id,
        job_id=run_record.job_id,
        resource=resource,
        holder_agent_id=agent_id,
        metadata_json=dict(request.metadata or {}),
        acquired_at=now,
        expires_at=expires_at,
    )
    db.add(record)
    try:
        db.commit()
    except IntegrityError:
        # Lost the race to another agent inserting the same (run_id, resource).
        db.rollback()
        contender = (
            db.query(AgentLockRecord)
            .filter(
                AgentLockRecord.run_id == run_record.id,
                AgentLockRecord.resource == resource,
            )
            .first()
        )
        if contender is not None and contender.holder_agent_id == agent_id:
            return lock_from_record(contender)
        return None
    db.refresh(record)
    return lock_from_record(record)


def release_lock(db: Session, run_id: str, resource: str, agent_id: str) -> bool:
    run_record = _require_run(db, run_id)
    normalized_resource = _clean_optional(resource)
    holder = _clean_optional(agent_id)
    if normalized_resource is None or holder is None:
        return False
    record = (
        db.query(AgentLockRecord)
        .filter(
            AgentLockRecord.run_id == run_record.id,
            AgentLockRecord.resource == normalized_resource,
        )
        .first()
    )
    if record is None or record.holder_agent_id != holder:
        return False
    db.delete(record)
    db.commit()
    return True


def list_locks(db: Session, run_id: str, *, include_expired: bool = False) -> list[models.AgentLock]:
    run_record = _require_run(db, run_id)
    now = utcnow()
    rows = (
        db.query(AgentLockRecord)
        .filter(AgentLockRecord.run_id == run_record.id)
        .order_by(AgentLockRecord.acquired_at.asc())
        .all()
    )
    locks: list[models.AgentLock] = []
    for row in rows:
        row_expiry = _as_aware(row.expires_at)
        if not include_expired and row_expiry is not None and row_expiry <= now:
            continue
        locks.append(lock_from_record(row))
    return locks


def lock_from_record(record: AgentLockRecord) -> models.AgentLock:
    return models.AgentLock(
        id=record.id,
        run_id=record.run_id,
        job_id=record.job_id,
        resource=record.resource,
        holder_agent_id=record.holder_agent_id,
        metadata=dict(record.metadata_json or {}),
        acquired_at=record.acquired_at,
        expires_at=record.expires_at,
    )


def get_run_context_bundle(
    db: Session,
    run_id: str,
    *,
    limit: int = 100,
    agent_id: str | None = None,
) -> models.RunContextBundle:
    return models.RunContextBundle(
        state=get_run_state(db, run_id),
        blackboard=list_blackboard_entries(db, run_id, limit=limit, agent_id=agent_id),
        handoffs=list_handoffs(db, run_id, limit=limit),
        artifacts=list_artifacts(db, run_id, limit=limit),
        agents=list_agents(db, run_id),
        locks=list_locks(db, run_id),
    )


def index_task_result_collaboration(
    db: Session,
    *,
    run_id: str,
    step_id: str,
    task_id: str,
    result: Mapping[str, Any],
    producing_agent_id: str | None = None,
) -> list[models.Artifact]:
    run_record = get_run_record(db, run_id)
    if run_record is None:
        return []
    producing_agent = _clean_optional(producing_agent_id)
    # Dynamic agents: an agent.run result reports the agent tree it spawned.
    # Register each in the durable registry so they become visible + attributed.
    materialize_dynamic_agents(
        db,
        run_record=run_record,
        result=result,
        task_id=task_id,
    )
    summary = task_result_summary(result)
    if producing_agent is not None:
        summary = {**summary, "producing_agent_id": producing_agent}
    write_task_snapshot(
        db,
        run_id=run_record.id,
        step_id=step_id,
        task_id=task_id,
        summary=summary,
    )
    if producing_agent is not None:
        _touch_agent_for_task(db, run_record=run_record, agent_id=producing_agent, task_id=task_id)
    created: list[models.Artifact] = []
    for candidate in artifact_candidates_from_result(result):
        path = str(candidate.get("path") or "").strip()
        if not path:
            continue
        record = upsert_artifact(
            db,
            run_record=run_record,
            artifact_type=str(candidate.get("artifact_type") or "file"),
            path=path,
            step_id=step_id,
            task_id=task_id,
            producing_agent_id=_clean_optional(candidate.get("producing_agent_id")) or producing_agent,
            storage_key=_clean_optional(candidate.get("storage_key")),
            mime_type=_clean_optional(candidate.get("mime_type")),
            size_bytes=_optional_int(candidate.get("size_bytes")),
            sha256=_clean_optional(candidate.get("sha256")),
            metadata=dict(candidate.get("metadata") or {}),
        )
        created.append(artifact_from_record(record))
    return created


def _touch_agent_for_task(
    db: Session,
    *,
    run_record: RunRecord,
    agent_id: str,
    task_id: str,
) -> None:
    """Record that an agent produced a task result: refresh heartbeat + assignment.

    Best-effort — never raises into the result-storage path.
    """
    try:
        record = (
            db.query(AgentRegistryRecord)
            .filter(
                AgentRegistryRecord.run_id == run_record.id,
                AgentRegistryRecord.agent_id == agent_id,
            )
            .first()
        )
        if record is None:
            return
        now = utcnow()
        record.assigned_task_id = task_id
        record.last_heartbeat = now
        record.updated_at = now
        db.flush()
    except Exception:  # noqa: BLE001
        return


def task_result_summary(result: Mapping[str, Any]) -> dict[str, Any]:
    outputs = result.get("outputs") if isinstance(result, Mapping) else None
    artifacts = result.get("artifacts") if isinstance(result, Mapping) else None
    tool_calls = result.get("tool_calls") if isinstance(result, Mapping) else None
    return {
        "status": str(result.get("status") or "") if isinstance(result, Mapping) else "",
        "output_keys": sorted(str(key) for key in outputs.keys()) if isinstance(outputs, Mapping) else [],
        "artifact_count": len(artifacts) if isinstance(artifacts, Sequence) and not isinstance(artifacts, (str, bytes)) else 0,
        "tool_call_count": len(tool_calls) if isinstance(tool_calls, Sequence) and not isinstance(tool_calls, (str, bytes)) else 0,
        "error": str(result.get("error") or "") if isinstance(result, Mapping) and result.get("error") else "",
    }


def artifact_candidates_from_result(result: Mapping[str, Any]) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    seen: set[str] = set()

    artifacts = result.get("artifacts") if isinstance(result, Mapping) else None
    if isinstance(artifacts, Sequence) and not isinstance(artifacts, (str, bytes)):
        for artifact in artifacts:
            if isinstance(artifact, Mapping):
                _append_artifact_candidate(candidates, seen, artifact, source="task_artifacts")

    outputs = result.get("outputs") if isinstance(result, Mapping) else None
    _collect_artifact_paths(outputs, candidates, seen, source="outputs")

    tool_calls = result.get("tool_calls") if isinstance(result, Mapping) else None
    if isinstance(tool_calls, Sequence) and not isinstance(tool_calls, (str, bytes)):
        for call in tool_calls:
            if not isinstance(call, Mapping):
                continue
            tool_name = str(call.get("tool_name") or "")
            output = call.get("output_or_error")
            _collect_artifact_paths(
                output,
                candidates,
                seen,
                source="tool_call",
                metadata={"tool_name": tool_name} if tool_name else {},
            )
    return candidates


def upsert_artifact(
    db: Session,
    *,
    run_record: RunRecord,
    artifact_type: str,
    path: str,
    step_id: str | None = None,
    task_id: str | None = None,
    producing_agent_id: str | None = None,
    storage_key: str | None = None,
    mime_type: str | None = None,
    size_bytes: int | None = None,
    sha256: str | None = None,
    metadata: Mapping[str, Any] | None = None,
) -> ArtifactRecord:
    normalized_path = normalize_artifact_path(path)
    if not normalized_path:
        raise ValueError("artifact_path_required")
    existing = (
        db.query(ArtifactRecord)
        .filter(
            ArtifactRecord.run_id == run_record.id,
            ArtifactRecord.step_id == step_id,
            ArtifactRecord.path == normalized_path,
        )
        .first()
    )
    stat = _artifact_file_stat(normalized_path)
    resolved_mime_type = mime_type or mimetypes.guess_type(normalized_path)[0]
    now = utcnow()
    if existing is None:
        existing = ArtifactRecord(
            id=str(uuid.uuid4()),
            run_id=run_record.id,
            job_id=run_record.job_id,
            step_id=step_id,
            task_id=task_id,
            producing_agent_id=producing_agent_id,
            artifact_type=artifact_type or "file",
            path=normalized_path,
            storage_key=storage_key,
            mime_type=resolved_mime_type,
            size_bytes=size_bytes if size_bytes is not None else stat.get("size_bytes"),
            sha256=sha256 or stat.get("sha256"),
            metadata_json=dict(metadata or {}),
            created_at=now,
        )
        db.add(existing)
        return existing
    existing.job_id = run_record.job_id
    existing.task_id = task_id or existing.task_id
    existing.producing_agent_id = producing_agent_id or existing.producing_agent_id
    existing.artifact_type = artifact_type or existing.artifact_type
    existing.storage_key = storage_key or existing.storage_key
    existing.mime_type = resolved_mime_type or existing.mime_type
    existing.size_bytes = size_bytes if size_bytes is not None else stat.get("size_bytes") or existing.size_bytes
    existing.sha256 = sha256 or stat.get("sha256") or existing.sha256
    existing.metadata_json = {**dict(existing.metadata_json or {}), **dict(metadata or {})}
    return existing


def handoff_from_record(record: AgentHandoffRecord) -> models.AgentHandoff:
    return models.AgentHandoff(
        id=record.id,
        run_id=record.run_id,
        job_id=record.job_id,
        from_agent_id=record.from_agent_id,
        to_agent_id=record.to_agent_id,
        step_id=record.step_id,
        task_id=record.task_id,
        objective=record.objective or "",
        summary=record.summary or "",
        inputs=record.inputs_json or {},
        outputs=record.outputs_json or {},
        assumptions=record.assumptions_json or [],
        risks=record.risks_json or [],
        artifact_ids=record.artifact_ids_json or [],
        metadata=record.metadata_json or {},
        created_at=record.created_at,
    )


def artifact_from_record(record: ArtifactRecord) -> models.Artifact:
    return models.Artifact(
        id=record.id,
        run_id=record.run_id,
        job_id=record.job_id,
        step_id=record.step_id,
        task_id=record.task_id,
        producing_agent_id=record.producing_agent_id,
        artifact_type=record.artifact_type,
        path=record.path,
        storage_key=record.storage_key,
        mime_type=record.mime_type,
        size_bytes=record.size_bytes,
        sha256=record.sha256,
        metadata=record.metadata_json or {},
        created_at=record.created_at,
    )


def normalize_artifact_path(value: str) -> str:
    trimmed = str(value or "").strip().replace("\\", "/")
    for prefix in ("/shared/artifacts/", "shared/artifacts/", "artifacts/"):
        if trimmed.startswith(prefix):
            trimmed = trimmed[len(prefix):]
            break
    if trimmed.startswith("/") or ".." in Path(trimmed).parts:
        return ""
    return trimmed


def _require_run(db: Session, run_id: str) -> RunRecord:
    run_record = get_run_record(db, run_id)
    if run_record is None:
        raise KeyError("run_not_found")
    return run_record


def _count_by_status(values: Iterable[str]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for value in values:
        key = str(value or "unknown")
        counts[key] = counts.get(key, 0) + 1
    return counts


def _latest_error_for_run(db: Session, run_record: RunRecord) -> str | None:
    result = (
        db.query(TaskResultRecord)
        .filter(TaskResultRecord.job_id == run_record.job_id)
        .order_by(TaskResultRecord.updated_at.desc())
        .first()
    )
    if result is None:
        return None
    return result.latest_error


def _blackboard_entry_from_memory(
    run_record: RunRecord,
    record: MemoryRecord,
) -> models.BlackboardEntry:
    payload = record.payload if isinstance(record.payload, Mapping) else {}
    metadata = record.metadata_json if isinstance(record.metadata_json, Mapping) else {}
    inner_payload = payload.get("payload") if isinstance(payload.get("payload"), Mapping) else payload
    kind = str(payload.get("kind") or metadata.get("kind") or "fact")
    confidence = payload.get("confidence", metadata.get("confidence"))
    return models.BlackboardEntry(
        id=record.id,
        run_id=str(metadata.get("run_id") or run_record.id),
        job_id=run_record.job_id,
        key=record.key,
        kind=kind,
        payload=dict(inner_payload),
        source_agent_id=_clean_optional(payload.get("source_agent_id") or metadata.get("source_agent_id")),
        step_id=_clean_optional(payload.get("step_id") or metadata.get("step_id")),
        task_id=_clean_optional(payload.get("task_id") or metadata.get("task_id")),
        visibility=str(payload.get("visibility") or metadata.get("visibility") or "shared"),
        confidence=float(confidence) if isinstance(confidence, (int, float)) else None,
        metadata=dict(metadata),
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


def _blackboard_entry_from_memory_entry(
    run_record: RunRecord,
    entry: models.MemoryEntry,
) -> models.BlackboardEntry:
    payload = entry.payload if isinstance(entry.payload, Mapping) else {}
    metadata = entry.metadata if isinstance(entry.metadata, Mapping) else {}
    inner_payload = payload.get("payload") if isinstance(payload.get("payload"), Mapping) else payload
    confidence = payload.get("confidence", metadata.get("confidence"))
    return models.BlackboardEntry(
        id=entry.id,
        run_id=str(metadata.get("run_id") or run_record.id),
        job_id=run_record.job_id,
        key=entry.key,
        kind=str(payload.get("kind") or metadata.get("kind") or "fact"),
        payload=dict(inner_payload),
        source_agent_id=_clean_optional(payload.get("source_agent_id") or metadata.get("source_agent_id")),
        step_id=_clean_optional(payload.get("step_id") or metadata.get("step_id")),
        task_id=_clean_optional(payload.get("task_id") or metadata.get("task_id")),
        visibility=str(payload.get("visibility") or metadata.get("visibility") or "shared"),
        confidence=float(confidence) if isinstance(confidence, (int, float)) else None,
        metadata=dict(metadata),
        created_at=entry.created_at,
        updated_at=entry.updated_at,
    )


def _append_artifact_candidate(
    candidates: list[dict[str, Any]],
    seen: set[str],
    artifact: Mapping[str, Any],
    *,
    source: str,
    metadata: Mapping[str, Any] | None = None,
) -> None:
    path = artifact.get("path") or artifact.get("output_path") or artifact.get("file_path")
    if not isinstance(path, str) or not _looks_like_artifact_path(path):
        return
    normalized = normalize_artifact_path(path)
    if not normalized or normalized in seen:
        return
    seen.add(normalized)
    merged_metadata = {"source": source}
    merged_metadata.update(dict(metadata or {}))
    merged_metadata.update({key: value for key, value in artifact.items() if key not in {"path"}})
    candidates.append(
        {
            "path": normalized,
            "artifact_type": str(artifact.get("type") or artifact.get("artifact_type") or "file"),
            "storage_key": artifact.get("storage_key") or artifact.get("s3_key"),
            "mime_type": artifact.get("mime_type"),
            "size_bytes": artifact.get("size_bytes"),
            "sha256": artifact.get("sha256"),
            "producing_agent_id": artifact.get("agent_id") or artifact.get("producing_agent_id"),
            "metadata": merged_metadata,
        }
    )


def _collect_artifact_paths(
    value: Any,
    candidates: list[dict[str, Any]],
    seen: set[str],
    *,
    source: str,
    path: str = "",
    metadata: Mapping[str, Any] | None = None,
) -> None:
    if isinstance(value, str):
        lower_path = path.lower()
        if ".tokens." in lower_path or lower_path.endswith(".result_path"):
            return
        _append_artifact_candidate(
            candidates,
            seen,
            {"path": value, "type": "file"},
            source=source,
            metadata=metadata,
        )
        return
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        for index, item in enumerate(value):
            _collect_artifact_paths(
                item,
                candidates,
                seen,
                source=source,
                path=f"{path}[{index}]",
                metadata=metadata,
            )
        return
    if isinstance(value, Mapping):
        _append_artifact_candidate(candidates, seen, value, source=source, metadata=metadata)
        for key, item in value.items():
            _collect_artifact_paths(
                item,
                candidates,
                seen,
                source=source,
                path=f"{path}.{key}" if path else str(key),
                metadata=metadata,
            )


def _looks_like_artifact_path(value: str) -> bool:
    normalized = normalize_artifact_path(value)
    if not normalized or normalized.startswith(("http://", "https://")):
        return False
    suffix = Path(normalized).suffix.lower()
    return suffix in ARTIFACT_EXTENSIONS


def _artifact_file_stat(path: str) -> dict[str, Any]:
    resolved = Path(ARTIFACTS_DIR) / path
    try:
        if not resolved.is_file():
            return {}
        size_bytes = resolved.stat().st_size
        stat: dict[str, Any] = {"size_bytes": size_bytes}
        if size_bytes <= 25 * 1024 * 1024:
            digest = hashlib.sha256()
            with resolved.open("rb") as file_obj:
                for chunk in iter(lambda: file_obj.read(1024 * 1024), b""):
                    digest.update(chunk)
            stat["sha256"] = digest.hexdigest()
        return stat
    except OSError:
        return {}


def _clean_optional(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    return stripped or None


def _optional_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed >= 0 else None
