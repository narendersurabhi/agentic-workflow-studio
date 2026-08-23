# Engineering Challenges Solved

A running record of non-trivial engineering problems resolved in this codebase — what the problem was, why it mattered, and what was built to fix it.

---

## 1. Tool Registry Fragmentation

**Problem:** Tool assembly was spread across three files — `tool_registry.py`, `tool_catalog.py`, and `tool_bootstrap.py` — with overlapping responsibilities and duplicate factory functions (`default_registry()` vs `build_default_registry()`). New callers couldn't tell which entry point to use, and adding a tool required touching multiple files.

**Solution:** Merged `tool_catalog.py` and `tool_bootstrap.py` into `tool_registry.py`. Established a single assembly path: `build_default_registry()` is the canonical entry point; `default_registry()` was left as a deprecated alias with a doc comment. All tool registration, DI wiring, plugin loading, and governance now happen in one file.

**Files:** `libs/core/tool_registry.py`

---

## 2. Tool Input Schema Sprawl (Raw Dicts → Pydantic)

**Problem:** Most tool input and output schemas were defined as raw Python dicts with no type-checking, no IDE completion, and inconsistent field descriptions. Schema drift between what the dict declared and what the handler actually expected caused silent runtime failures that were hard to debug.

**Solution:** Migrated all schemas to Pydantic `BaseModel` with `ConfigDict(extra="forbid")` and `Field(description=...)`, then used `model.model_json_schema()` as the registered schema. This gives compile-time type safety, automatic JSON Schema generation, and strict input rejection. Six tools with complex `anyOf`/`not` top-level constraints were documented as intentional exceptions (they remain as raw dicts).

**Impact:** All new tools must use Pydantic schemas. The `CLAUDE.md` architectural issues section was updated to reflect this as resolved.

---

## 3. Agent Tool Naming Inconsistency (`agent_run` → `agent`)

**Problem:** The agentic loop tool was named `agent_run` — a verb-noun pattern that clashed with Claude Code's convention of using a simple noun (`agent`). This made the capability registry YAML, schema file references, and test fixtures inconsistent with the intended naming standard.

**Solution:** Renamed the tool end-to-end: capability ID `agent.run` → kept (it's a namespace), tool name `agent_run` → `agent`, internal functions `_agent_run_*` → `_agent_*`, schema file `agent_run_capability_input.json` → `agent_capability_input.json`, all references in `config/capability_registry.yaml` and test fixtures updated.

**Files:** `libs/tools/agent_tools.py`, `libs/tools/llm_tool_groups.py`, `libs/core/tool_registry.py`, `config/capability_registry.yaml`, `schemas/`, tests

---

## 4. Agent Workbench: No Publish/Draft Lifecycle

**Problem:** The Agent Workbench allowed creating and editing agent definitions, but there was no concept of a "published" vs "in-progress" state. Any definition could be used for production runs regardless of whether it was stable, making it impossible to distinguish sandbox configurations from reviewed, released agents.

**Solution:** Added a `status` column (`draft` | `published`) to `agent_definitions`. Publish is atomic with version creation — `POST /agents/definitions/{id}/versions` sets `status = "published"` in the same transaction. Any change to a behavioral field (`instructions`, `allowed_capability_ids`, `llm_config`, `memory_policy`, `guardrail_policy`, `workspace_policy`, `agent_capability_id`) on a published definition automatically resets status to `draft`, forcing a re-review cycle. The `list_agent_definitions` endpoint accepts a `status` filter.

**Files:** `services/api/app/main.py`, `services/api/app/models.py`, `services/api/app/alembic/versions/20260608_add_agent_definition_status.py`

---

## 5. Sub-Agent Blast Radius (In-Process Recursion → Job Isolation)

**Problem:** When an agent called `agent.run` recursively, the child ran in the same worker process, sharing its memory, LLM context window, and error surface. A runaway child could exhaust the worker's resources, a crash in the child would kill the parent, and there was no way to observe or cancel a child independently.

**Solution:** When `API_URL` is configured, the `agent` tool handler intercepts recursive `agent` calls and dispatches them to `POST /internal/sub-agent` instead of calling `_agent()` in-process. The sub-agent runs as an independent job in a separate worker process. The parent polls `GET /runs/{run_id}` with exponential backoff (0.5s → 5s cap, 300s timeout) until the child completes, then extracts the output from its run steps. Falls back to in-process execution when `API_URL` is not set (dev/test).

**New files:** `libs/core/sub_agent_dispatch.py`
**Modified:** `libs/core/tool_registry.py`, `services/api/app/main.py` (added `/internal/sub-agent`)

---

## 6. No Background Agent Execution

**Problem:** Every `agent.run` call was synchronous — the caller blocked until the entire agentic loop completed. Long-running agents (multi-minute research loops, large codegen tasks) held open the caller's connection or consumed a worker slot for the full duration, with no way to fire-and-forget.

**Solution:** Added `background: bool` to `AgentRunInput`. When `background=True` and `API_URL` is set, the agent strips the `background` flag from the forwarded payload and dispatches via `sub_agent_dispatch.dispatch_sub_agent(..., background=True)`, which returns `{status: "running", run_id}` immediately after job creation without waiting for completion. The caller uses `GET /runs/{run_id}` to poll status independently.

**Files:** `libs/tools/agent_tools.py`, `libs/tools/llm_tool_groups.py`

---

## 7. No Workspace Isolation for File-Writing Agents

**Problem:** When an agent wrote files to a workspace, it operated directly on the repository's working tree. Multiple concurrent agents, or a single agent experimenting with code changes, could corrupt the main branch or interfere with each other. There was no safe sandbox for file operations.

**Solution:** Added `workspace_isolation: "none" | "worktree"` and `workspace_path` to `AgentRunInput`. When `workspace_isolation="worktree"`, the agent loop creates a dedicated git worktree branch (`agent-{id}-{uuid8}`) before the loop starts. Every tool call that accepts `workspace_path` has the argument rewritten to point at the isolated path. On failure, the worktree is force-removed; on success, it is left for the caller to inspect or merge.

**New files:** `libs/tools/workspace_git.py` (`create_worktree`, `remove_worktree`, `worktree_context`)
**Modified:** `libs/tools/agent_tools.py`, `libs/tools/llm_tool_groups.py`

---

## 8. No Human-in-the-Loop (Agent Resumability)

**Problem:** Agents ran to completion or failure with no ability to pause and ask a human a clarifying question mid-loop. Any task that required human confirmation, ambiguity resolution, or incremental input had to be broken into separate jobs manually, losing all intermediate context between them.

**Solution:** Implemented a checkpoint-based pause/resume system:

- **`wait_for_input` tool** is always injected into every agent's tool list. When called, it raises `AgentPauseSignal` which the loop catches, snapshots the full conversation state (`messages` list), and returns a `__paused__` marker up the call stack.
- **`agent()` handler** detects the pause, calls `POST /internal/agent-checkpoints` to persist the snapshot (messages, goal, instructions, capability list, step count, question) with a 24-hour TTL, and returns `{status: "paused", checkpoint_id, question}` as the task output.
- **`POST /agents/{run_id}/resume`** appends the user's reply to the saved messages, marks the checkpoint as `"resuming"`, creates a new `TaskRecord` in the same plan with `resume_from_checkpoint_id` in the tool inputs, and dispatches it via `_enqueue_ready_tasks`. The original `run_id` is unchanged — same run throughout.
- On resume, `agent()` detects `resume_from_checkpoint_id`, loads the checkpoint via `GET /internal/agent-checkpoints/{id}`, restores the conversation, and continues the loop from where it left off.

**Design constraints met:** same `run_id` (not linked runs), 24-hour TTL, always available (no opt-in flag).

**New files:** `services/api/app/alembic/versions/20260608_add_agent_checkpoints.py`
**Modified:** `services/api/app/models.py` (`AgentCheckpointRecord`), `libs/core/models.py` (`AgentCheckpoint`, `AgentCheckpointCreate`, `AgentResumeRequest`), `libs/tools/agent_tools.py`, `libs/tools/llm_tool_groups.py`, `services/api/app/main.py` (three new endpoints)

---

## Summary Table

| # | Challenge | Approach | Status |
|---|---|---|---|
| 1 | Tool registry split across 3 files | Merge into single `tool_registry.py` | Done |
| 2 | Raw-dict tool schemas, no type safety | Migrate to Pydantic `BaseModel` + `model_json_schema()` | Done |
| 3 | `agent_run` naming inconsistency | Rename to `agent` end-to-end | Done |
| 4 | No draft/published lifecycle for agents | `status` column + atomic publish + behavioral-field reset | Done |
| 5 | In-process sub-agent blast radius | Dispatch sub-agents as independent jobs via `/internal/sub-agent` | Done |
| 6 | No background agent execution | `background: bool` → immediate `run_id` return | Done |
| 7 | No workspace isolation for file-writing agents | Git worktree per agent run + `workspace_path` rewriting | Done |
| 8 | No human-in-the-loop / resumability | `wait_for_input` tool + checkpoint DB + resume endpoint | Done |
