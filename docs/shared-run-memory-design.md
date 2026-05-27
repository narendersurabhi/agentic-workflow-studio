# Shared Run Memory Design

## Overview

This document describes the design for a **shared run memory** — a mutable, structured scratchpad
scoped to a single workflow run (job) that every task in that run, every replanning iteration,
and every spawned agent can read from and write to.

The design builds on the existing `MemoryRecord` / `MemoryClient` infrastructure already in the
codebase. It introduces a new `RunMemory` abstraction on top of that foundation without replacing
or breaking existing task-output dependency resolution.

---

## Motivation

### Current limitations

| Mechanism | What it stores | Who can read | Durability |
|---|---|---|---|
| `task_output:{task_id}` Redis key | One task's raw outputs | Only downstream DAG deps | Evicted after TTL |
| `MemoryRecord` (PostgreSQL) | Named facts, tool memory | Any task with `memory_reads` spec | Permanent |
| `JobRecord.context_json` | User-provided job context | Planner at planning time only | Per-job |
| `PlanRevisionContext` | Failed-step info for replanning | Planner only, on revision | Per-revision |

**Gaps:**
1. A task can only read outputs from its direct ancestors. Sibling tasks are invisible.
2. The planner receives a narrow `context_json` snapshot at plan time; it cannot see
   what tasks discovered or observed during execution.
3. When replanning, the replanner knows only about the failed step, not the accumulated
   observations from all completed steps.
4. Spawning multiple agents in parallel requires each agent to have a shared space for
   coordination (status, intermediate results, locks).

### Goals

- **Cross-task visibility within a run**: any task can write a named observation; any later
  task can read it, regardless of DAG position.
- **Planner-accessible history**: when replanning, the planner sees the full run memory,
  not just the last failed step.
- **Multi-agent coordination**: agents share a single memory namespace keyed by job, so
  they can detect each other's outputs and avoid duplicate work.
- **Low latency for hot-path reads/writes**: Redis hash as the live store, flushed to
  PostgreSQL at checkpoints.

---

## Architecture

### Data model

```
RunMemory
├── job_id: str                         (primary key / scope)
├── revision: int                       (increments on each planner revision)
├── created_at: datetime
├── updated_at: datetime
│
├── facts: dict[str, FactEntry]         (open-ended observations & discovered values)
│   └── FactEntry
│       ├── key: str
│       ├── value: Any                  (JSON-serialisable)
│       ├── source_task: str | None     (task name that wrote this)
│       ├── source_agent: str | None    (agent id that wrote this)
│       ├── written_at: datetime
│       └── version: int                (monotonic counter per key)
│
├── task_snapshots: dict[str, Any]      (task-name → condensed output summary)
│   └── written by each task on completion; readable by planner & other agents
│
├── agent_registry: dict[str, AgentStatus]   (agent-id → status, for multi-agent)
│   └── AgentStatus
│       ├── agent_id: str
│       ├── role: str                   (e.g. "researcher", "writer", "critic")
│       ├── status: "idle"|"running"|"done"|"failed"
│       ├── assigned_task: str | None
│       └── last_heartbeat: datetime
│
└── planner_notes: list[PlannerNote]    (replanning rationale log)
    └── PlannerNote
        ├── revision: int
        ├── trigger: str                (e.g. "task_failed", "goal_drift", "agent_blocked")
        ├── strategy: str               (e.g. "replace_failed", "reorder", "split")
        ├── summary: str                (LLM-generated 1-sentence rationale)
        └── written_at: datetime
```

### Storage layers

```
Write path (task → memory):

  Worker task completes
       │
       ▼
  RunMemoryClient.write_fact(job_id, key, value, source_task=...)
       │
       ├── HSET run_memory:{job_id}:facts  key  <json>       ← Redis (hot)
       └── PUBLISH run_memory:{job_id}:updates  key          ← Redis pub/sub (agents subscribe)
       (async flush every 30 s or on checkpoint)
       └── MemoryRecord (scope=session, name="run_memory_facts", key=key)  ← PostgreSQL (durable)


Read path (task / planner / agent → memory):

  RunMemoryClient.read_facts(job_id, keys=[...] | None)
       │
       ├── HGETALL run_memory:{job_id}:facts                 ← Redis (< 1 ms)
       └── fallback: SELECT * FROM memory_records             ← PostgreSQL (if Redis miss)
            WHERE scope='session' AND job_id=? AND name='run_memory_facts'
```

### Redis key schema

| Key | Type | Content |
|---|---|---|
| `run_memory:{job_id}:facts` | Hash | field → JSON(FactEntry) |
| `run_memory:{job_id}:snapshots` | Hash | task_name → JSON(task output summary) |
| `run_memory:{job_id}:agents` | Hash | agent_id → JSON(AgentStatus) |
| `run_memory:{job_id}:meta` | Hash | revision, created_at, updated_at |
| `run_memory:{job_id}:updates` | Pub/Sub channel | key name on each write |
| `run_memory:{job_id}:lock:{resource}` | String (SETNX) | agent_id holding lock, TTL 30 s |

---

## Implementation plan

### Phase 1 — RunMemoryClient

**New file:** `libs/core/run_memory_client.py`

```python
class RunMemoryClient:
    def __init__(self, redis_client, memory_client: MemoryClient):
        ...

    def write_fact(self, job_id, key, value, *, source_task=None, source_agent=None) -> None:
        """Atomic write; increments per-key version counter."""

    def read_fact(self, job_id, key) -> FactEntry | None:
        """Redis-first read, PostgreSQL fallback."""

    def read_all_facts(self, job_id) -> dict[str, FactEntry]:
        """Full snapshot for planner context."""

    def write_task_snapshot(self, job_id, task_name, summary: dict) -> None:
        """Called by worker on task completion with a condensed output."""

    def read_task_snapshots(self, job_id) -> dict[str, Any]:
        """Returns all task snapshots for the planner."""

    def register_agent(self, job_id, agent_id, role) -> None:
    def update_agent_status(self, job_id, agent_id, status, assigned_task=None) -> None:
    def list_agents(self, job_id) -> dict[str, AgentStatus]:

    def acquire_lock(self, job_id, resource, agent_id, ttl_s=30) -> bool:
        """SETNX-based optimistic lock for agent coordination."""
    def release_lock(self, job_id, resource, agent_id) -> None:

    def flush_to_store(self, job_id) -> None:
        """Persist hot Redis state to PostgreSQL MemoryRecord rows."""
```

**Where it lives:** `libs/core/run_memory_client.py` — shared library, imported by worker,
planner service, and API.

**Dependencies:** existing `RedisClient` and `MemoryClient` (already in `libs/core/memory_client.py`).

---

### Phase 2 — Worker integration

**File:** `services/worker/app/main.py`

Two new hooks around each task execution:

```python
# Before tool execution (after dependency context is built):
run_memory_snapshot = run_memory_client.read_all_facts(job_id)
context["run_memory"] = run_memory_snapshot   # injected into task context

# After task completes successfully:
run_memory_client.write_task_snapshot(
    job_id,
    task_name=task.name,
    summary=_summarize_task_output(task_result.outputs),
)
# Tool spec can declare memory_writes targeting run_memory:
if task_result.run_memory_writes:
    for key, value in task_result.run_memory_writes.items():
        run_memory_client.write_fact(job_id, key, value, source_task=task.name)
```

**Tool spec extension** (`libs/core/models.py` — `ToolSpec`):

```python
run_memory_reads: list[str] = []   # fact keys to inject into tool input
run_memory_writes: list[str] = []  # output keys to promote into run memory
```

This is opt-in per tool. Tools that don't declare these fields are unaffected.

---

### Phase 3 — Planner integration

**File:** `services/planner/app/main.py` and `libs/core/planner_contracts.py`

When the planner generates or revises a plan, inject `run_memory` into the planner context:

```python
# In project_planner_job_context() — planner_contracts.py
run_memory_facts = run_memory_client.read_all_facts(job_id)
task_snapshots  = run_memory_client.read_task_snapshots(job_id)

context["run_memory"] = {
    "facts": {k: v.value for k, v in run_memory_facts.items()},
    "completed_task_summaries": task_snapshots,
}
```

**LLM planner prompt addition:**

The planner prompt (in `services/planner/app/planner_service.py`) should include a section:

```
## Run Memory (accumulated context from completed tasks)
{run_memory_facts_formatted}

## Completed Task Summaries
{task_snapshots_formatted}
```

This gives the replanner everything it needs to avoid repeating failed approaches and to
understand what has already been learned.

---

### Phase 4 — Replanning via shared memory

Currently `PlanRevisionContext` captures:
- `completed_steps`: list of `CompletedStepContext`
- `failed_step`: `FailedStepContext`
- `remaining_goals`: str
- `constraints`: dict
- `budgets`: dict

**Extension:** add `run_memory_snapshot: dict[str, Any]` to `PlanRevisionContext`:

```python
@dataclass
class PlanRevisionContext:
    ...
    run_memory_snapshot: dict[str, Any] = field(default_factory=dict)
    # Keys: facts (all run_memory facts at time of replanning),
    #       task_snapshots (per-task output summaries)
```

**Population** (in `_build_revision_context()` — `services/api/app/main.py`):

```python
revision_context.run_memory_snapshot = {
    "facts": run_memory_client.read_all_facts(job_id),
    "task_snapshots": run_memory_client.read_task_snapshots(job_id),
}
```

**Replanning prompt enrichment** (in the planner's LLM prompt):

```
## Why the plan failed
{failed_step.error}

## What was learned before failure (run memory)
{run_memory_snapshot.facts}

## What each completed task produced
{run_memory_snapshot.task_snapshots}

## Replanning strategy
Based on the above context, generate a revised plan that:
1. Avoids repeating the failed approach.
2. Builds on the facts already established.
3. Only re-runs tasks that are still needed.
```

---

### Phase 5 — Multi-agent coordination

When spawning multiple agents in parallel for a single job:

**Agent lifecycle:**

```
Job created (multi-agent flag set)
    │
    ├── Agent A spawned  → run_memory_client.register_agent(job_id, "agent-a", role="researcher")
    ├── Agent B spawned  → run_memory_client.register_agent(job_id, "agent-b", role="writer")
    └── Agent C spawned  → run_memory_client.register_agent(job_id, "agent-c", role="critic")

Each agent:
    ├── Reads run_memory to understand what others have done
    ├── Acquires a lock before writing to a shared resource
    ├── Writes its outputs to run_memory as facts
    └── Updates its AgentStatus on completion / failure
```

**Coordination patterns:**

| Pattern | Mechanism |
|---|---|
| Parallel independent tasks | Each agent writes to its own fact namespace (`agent-a:*`) |
| One produces, one consumes | Consumer subscribes to `run_memory:{job_id}:updates` channel |
| Avoiding duplicate work | Acquire `lock:{resource}` before starting; skip if already acquired |
| Agent failure recovery | Planner reads `agent_registry`, replans for failed agent's tasks |
| Critic reviewing writer | Critic reads `writer:output` fact; writes `critic:feedback` fact |

**API endpoint for multi-agent job creation:**

```
POST /jobs
{
  "goal": "...",
  "agents": [
    {"role": "researcher", "capabilities": ["memory.read", "filesystem.*"]},
    {"role": "writer",     "capabilities": ["llm.text.generate", "document.*"]},
    {"role": "critic",     "capabilities": ["document.spec.validate"]}
  ]
}
```

The API creates one `JobRecord` with a set of agent slots. Each agent is a worker consumer
in the same `tasks.events` stream group, but with its own consumer ID
(`agent-{role}-{job_id}`). They all share the same `run_memory:{job_id}` namespace.

---

## Concurrency and consistency

| Concern | Approach |
|---|---|
| Two tasks writing the same key | Last-write-wins by default; opt-in CAS via version check |
| Agent crashes without releasing lock | TTL on `lock:*` keys (30 s default, refreshed by heartbeat) |
| Redis restart loses in-flight memory | Flush to PostgreSQL on each task completion (async, < 100 ms) |
| Very large fact values | Cap at 64 KB per fact; large artifacts use `artifacts` path reference |
| Stale facts after replanning | Revision counter is stored; planner can filter facts by revision |

---

## What does NOT change

- The existing `task_output:{task_id}` / dependency resolution path is **unchanged**. Shared
  run memory is additive — it provides cross-task visibility, not a replacement for the DAG
  dependency mechanism.
- The `MemoryRecord` table and `MemoryClient` are **reused** as the durable store. No new
  PostgreSQL tables are required in Phase 1.
- Tools that do not declare `run_memory_reads` / `run_memory_writes` are **unaffected**.

---

## Open questions

1. **Token budget for planner context**: full `read_all_facts()` can be large. Should the
   planner receive a summarised / top-K view instead? Possible approach: use
   `memory.semantic.search` to retrieve only the most relevant facts given the failing task's
   instruction.

2. **Fact schema vs. free-form**: should facts be typed (e.g., a `discovered_file` has a
   required `path` field)? Typed facts allow schema validation but add authoring overhead.
   Recommendation: free-form JSON values for now, add optional schema refs later.

3. **Cross-job run memory**: for the multi-agent spawning case, should facts survive beyond
   a single job (e.g., agent learns something useful for a follow-on job)? If so, promote
   selected facts to `user`-scoped or `project`-scoped `MemoryRecord` rows at job completion.

4. **Visibility control**: should an agent in a multi-agent job be able to write private facts
   (visible only to itself)? Approach: namespace prefix `private:{agent_id}:{key}` plus a
   read filter in `RunMemoryClient`.
