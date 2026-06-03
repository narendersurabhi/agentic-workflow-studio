# Sub-Agent Orchestration Analysis

Analysis date: 2026-06-03

Current branch: `framework-improvements`

Current HEAD: `d6a7763` - `Studio: surface the real save/publish/run error instead of "failed (400)"`

## Summary

The repository currently supports two related multi-agent orchestration patterns:

1. Static team assignment, where user-provided agents are registered against a run and workflow tasks are attributed to agents by capability.
2. Runtime recursive spawning, where an `agent.run` task can call `agent.run` again to create logical sub-agents during execution.

The most important distinction is that runtime-spawned sub-agents are not separate queued workflow tasks yet. They are recursive local tool invocations inside the parent `agent.run` worker execution. After the parent task completes, their descriptors are materialized into the durable run agent registry for visibility, attribution, and debugging.

## Recent Commit Trail

The last few commits show the feature evolving in layers:

- `758744a` - Added multi-agent coordination primitives, including agent handoffs, artifacts, agent registry records, and locks.
- `592a724` - Added capability-team creation, assignment, and attribution for multi-agent jobs.
- `eccf6c3` - Connected `agent.run` results to the run agent registry so runtime-spawned agents become visible.
- `dfa5703` - Added a spawn-agents workflow where one `agent.run` orchestrator delegates to sub-agents.
- `873aa86` - Fixed foreign key ordering for workflow-run shadow creation.
- `ea5b64f` - Fixed workflow-run shadow collisions and materialization of dynamic agents.
- `528905d` - Fixed `agent.run` schema resolution so spawned agents can recurse correctly.
- `3524556` - Added readiness checks for missing required capability inputs before run.
- `3a96ea3` and `d6a7763` - Improved Studio workflow run links and surfaced real save, publish, and run errors.

## Static Team Assignment

When a job is created with an agent roster, the API normalizes the roster and stores it in job metadata.

Relevant code:

- `services/api/app/main.py` around job creation stores normalized agents in metadata and constrains allowed capabilities to the team's capabilities.
- `services/api/app/run_context_service.py` provides `normalize_agent_roster`, `capability_matches`, and `resolve_agent_for_capabilities`.
- `services/api/app/main.py` enriches task context with `assigned_agent` based on the task's requested capabilities.

The flow is:

1. User submits a job with agents.
2. API normalizes each agent into an `agent_id`, `role`, `capabilities`, and `metadata`.
3. API stores the roster in job metadata.
4. API registers those agents in the run agent registry.
5. Each task gets an assigned agent by matching task capability requests against agent capability patterns.
6. Task results and artifacts are attributed to the assigned agent where possible.

This is assignment and attribution. It is not dynamic sub-agent spawning.

## Runtime Recursive Sub-Agent Spawning

Runtime spawning is implemented through the `agent.run` capability.

Relevant code:

- `config/capability_registry.yaml` defines `agent.run` as a local worker tool capability.
- `libs/tools/llm_tool_groups.py` registers the local `agent_run` tool.
- `libs/core/tool_registry.py` intercepts recursive `agent_run` and `agent__run` calls.
- `libs/tools/agent_tools.py` implements the ReAct-style agent loop and reports spawned agents.
- `scripts/create_spawn_agents_workflow.py` builds the current spawn-agents workflow example.

The current runtime flow is:

1. A workflow node or planner task requests the `agent.run` capability.
2. `agent.run` is mapped to the local worker tool `agent_run`.
3. The worker invokes `libs/core/tool_registry._agent_run`.
4. `agent_tools.agent_run` starts a ReAct-style loop.
5. The agent receives tools derived from `allowed_capability_ids`.
6. If `allowed_capability_ids` includes `agent.run`, the orchestrator can call `agent.run` as one of its tools.
7. The tool registry intercepts that recursive `agent_run` call and invokes `_agent_run(..., _recursion_depth + 1)`.
8. Each invocation returns its own agent descriptor.
9. Parent invocations accumulate child descriptors.
10. The final task result contains a flattened `agents` list.
11. The API indexes the result and materializes the reported agents into `agent_registry`.

The recursion depth is capped by `_MAX_RECURSION_DEPTH = 4` in `libs/tools/agent_tools.py`.

## Spawn-Agents Workflow

The clearest example is `scripts/create_spawn_agents_workflow.py`.

It creates a single orchestrator node:

- Capability: `agent.run`
- Role: `orchestrator`
- Allowed capabilities:
  - `agent.run`
  - `filesystem.workspace.list`
  - `llm.text.generate`
  - `memory.read`

The defining property is that the orchestrator's `allowed_capability_ids` includes `agent.run`. That gives the orchestrator permission to delegate by recursively creating sub-agents.

The workflow is not a graph of multiple predeclared sub-agent nodes. It is one orchestrator node that can dynamically call `agent.run` again during execution.

## Agent Materialization

`agent_tools.agent_run` returns an `agents` list where:

- The current invocation appears first.
- Recursively spawned sub-agents are appended after it.
- Each descriptor includes fields like `agent_id`, `role`, `depth`, `status`, `steps_taken`, and `goal`.

`services/api/app/run_context_service.py` then collects reported agents from:

- Top-level `result["agents"]`
- Nested per-tool outputs
- Nested tool call outputs

Those descriptors are upserted into `agent_registry` with metadata such as:

- `spawned_by: agent.run`
- `depth`
- `steps_taken`
- `goal`
- `origin_task_id`

This makes runtime-spawned agents visible in:

- `/runs/{run_id}/agents`
- `/runs/{run_id}/context`
- Studio debugger and run context panels

## Shared Run Memory And Coordination

The run context bundle now contains:

- Run state
- Blackboard entries
- Task snapshots
- Handoffs
- Artifacts
- Agents
- Locks

Relevant endpoints:

- `GET /runs/{run_id}/context`
- `GET /runs/{run_id}/blackboard`
- `POST /runs/{run_id}/blackboard`
- `GET /runs/{run_id}/handoffs`
- `POST /runs/{run_id}/handoffs`
- `GET /runs/{run_id}/artifacts`
- `POST /runs/{run_id}/artifacts`
- `GET /runs/{run_id}/agents`
- `POST /runs/{run_id}/agents`
- `GET /runs/{run_id}/locks`
- `POST /runs/{run_id}/locks`

Task results are indexed into this collaboration layer. During result storage, the API:

1. Registers any dynamic agents reported by `agent.run`.
2. Writes a task snapshot into run memory.
3. Attributes artifacts to the producing agent where possible.
4. Refreshes the producing agent assignment and heartbeat.

## Current Architectural Takeaway

Sub-agents are currently orchestrated depth-first inside a parent `agent.run` worker task.

They are logical runtime invocations, not independently scheduled workflow tasks. The repository has the durable registry, blackboard, handoff, artifact, and lock foundations needed for more advanced coordination, but the current spawning path does not yet provide independent task scheduling, concurrent execution, retries, leases, or lifecycle events per spawned sub-agent.

## Likely Next Step

If the platform should support true multi-agent execution, the next implementation step is to promote runtime-spawned sub-agents from recursive local calls into first-class run steps:

- Create a child task or step record for each spawned sub-agent.
- Schedule child tasks through the same worker queue as normal workflow tasks.
- Give each sub-agent its own lifecycle, retry policy, attempt record, and events.
- Preserve the existing `agent_registry` materialization as the durable observability layer.
- Use blackboard, handoffs, artifacts, and locks as the shared coordination substrate.

