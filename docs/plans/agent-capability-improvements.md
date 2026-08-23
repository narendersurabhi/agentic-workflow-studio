# Agent Capability Improvements

Four features that bring the platform's `agent` tool to parity with Claude Code's Agent architecture. Listed in dependency order — each builds on the previous.

---

## Feature 1: Sub-agent-as-job (True Process Isolation)

**What it solves:** Today `_agent()` in `tool_registry.py:1207` recurses in-process. A context-length error or crash in the sub-agent propagates directly to the parent. This replaces that recursion with a real job dispatch — the sub-agent runs in a separate worker process with its own memory and LLM state.

### How it works

```
parent agent detects agent.run tool call
  → POST /internal/sub-agent  (new API endpoint)
      creates Job + Plan + Run records in DB
      enqueues to JOB_STREAM (Redis)
      returns {run_id}
  → poll GET /runs/{run_id} every 1s (with jitter, max timeout_s)
  → on completed: GET /runs/{run_id}/tasks → extract outputs["agent"]
  → on failed:    raise ToolExecutionError("sub-agent job failed: {error}")
```

The parent worker blocks on the poll but is not in the sub-agent's call stack. If the sub-agent worker process dies, the job goes to the DLQ and the parent gets `ToolExecutionError`.

### Files to change

| File | Change |
|---|---|
| `libs/core/sub_agent_dispatch.py` | **New.** `dispatch_sub_agent(payload, api_url, timeout_s) -> dict`. Builds run_spec, POSTs to API, polls completion, extracts result. |
| `libs/core/tool_registry.py:_agent()` | Replace `_agent(arguments, provider, _recursion_depth+1)` with `sub_agent_dispatch.dispatch_sub_agent(arguments, _API_URL)` when `_API_URL` is set; keep in-process as fallback for dev. |
| `services/api/app/main.py` | **New endpoint** `POST /internal/sub-agent`. Accepts `{goal, allowed_capability_ids, instructions, max_steps, agent_id, role}`. Builds a one-step RunSpec for `agent.run`, creates job, returns `{run_id, job_id}`. Auth: internal only (check `X-Internal-Token` header or bind to localhost). |
| `services/worker/docker-compose.yml` / env | Add `API_URL=http://api:8000` env var to worker service. |
| `libs/tools/agent_tools.py` | No loop changes needed — isolation comes from the dispatch layer. |

### New endpoint: `POST /internal/sub-agent`

```python
# Accepts:
{
  "goal": str,
  "allowed_capability_ids": list[str],
  "instructions": str | None,
  "max_steps": int | None,
  "agent_id": str | None,   # for registry attribution
  "role": str | None,
  "parent_run_id": str | None,  # for lineage tracking
}

# Returns:
{"run_id": str, "job_id": str}
```

Internally: build a `RunSpec` with one step — `capability_id: agent.run`, `input_bindings` = the payload fields — and call the existing `_workbench_launch_run()` helper. Tag `metadata.surface = "sub_agent"` and `metadata.parent_run_id`.

### Polling in `sub_agent_dispatch.py`

```python
# Pseudocode
def dispatch_sub_agent(payload, api_url, timeout_s=300.0):
    resp = httpx.post(f"{api_url}/internal/sub-agent", json=payload, timeout=30)
    run_id = resp.json()["run_id"]
    deadline = monotonic() + timeout_s
    interval = 0.5
    while monotonic() < deadline:
        run = httpx.get(f"{api_url}/runs/{run_id}", timeout=10).json()
        if run["status"] in ("completed", "done"):
            return _extract_agent_output(run_id, api_url)
        if run["status"] in ("failed", "error", "cancelled"):
            raise ToolExecutionError(f"sub-agent failed: {run.get('error', run['status'])}")
        time.sleep(min(interval, deadline - monotonic()))
        interval = min(interval * 1.5, 5.0)  # backoff, cap at 5s
    raise ToolExecutionError(f"sub-agent timed out after {timeout_s}s")

def _extract_agent_output(run_id, api_url):
    tasks = httpx.get(f"{api_url}/runs/{run_id}/tasks", timeout=10).json()
    for task in tasks:
        outputs = (task.get("outputs") or {})
        if "agent" in outputs:
            return outputs["agent"]
    return {"result": "completed", "steps_taken": 0, "tool_calls": [], "agents": []}
```

### Dev/test fallback

When `API_URL` is not set (unit tests, local dev without full stack), `tool_registry._agent()` falls back to the current in-process recursion. This keeps tests working unchanged.

---

## Feature 2: Background + Notification

**What it solves:** Today the `agent` tool always blocks — the caller waits for the entire loop to finish. `background: true` lets a step fire off a long-running agent and immediately continue to the next step. When the agent completes, the parent run is notified.

**Prerequisite:** Feature 1 (sub-agent-as-job). Once sub-agents are jobs, background is the same job dispatch without waiting for the result.

### How it works

```
agent tool receives payload with background: true
  → dispatch_sub_agent(payload, api_url) — same as Feature 1
  → return IMMEDIATELY with {status: "running", run_id: "...", background: true}
  (no polling)

When the background job completes:
  → the completion event is already published to TASK_STREAM
  → the parent task's "await_background" handler reads the run_id from task outputs
  → marks the parent step as complete and injects the result
```

### Files to change

| File | Change |
|---|---|
| `libs/tools/llm_tool_groups.py` | Add `background: bool = False` to `AgentRunInput`. Add `background: bool`, `run_id: str | None` to `AgentRunOutput`. |
| `libs/tools/agent_tools.py:agent()` | When `payload.get("background")` is True and `_recursion_depth == 0`: call `dispatch_sub_agent` (imported lazily) and return `{status: "running", run_id, background: True, ...}` without blocking. |
| `libs/core/sub_agent_dispatch.py` | Add `dispatch_sub_agent_background(payload, api_url) -> str` — same as `dispatch_sub_agent` but returns `run_id` immediately, no polling. |
| `services/worker/app/main.py` | **New:** `await_background_agent(run_id)` — called by the task executor when a step output has `background: true`. Polls completion (same logic as Feature 1). Adds result to task output when done. |

### Background completion notification

The sub-agent job completes and publishes to `TASK_STREAM` normally. The parent task's executor holds the `run_id` from the initial return value. On the next worker heartbeat cycle, it checks pending background run IDs and resolves them.

Simpler alternative (Phase 1): don't implement the auto-notification. Just return `{status: "running", run_id}` and let the planner/user poll. The full notification wiring can be Phase 2.

---

## Feature 3: Resumability (SendMessage equivalent)

**What it solves:** Today the agent loop runs until `final_answer` or `max_steps`. There's no way to pause, ask the user a question, and continue with their reply. This adds a `wait_for_input` mechanism — the agent can pause its loop, expose its current state, and resume when a message arrives.

**Prerequisite:** Feature 1 (sub-agent-as-job helps, but Feature 3 can be built independently using a DB checkpoint table).

### How it works

```
agent loop is running; model calls wait_for_input tool
  → serialize conversation state to agent_checkpoints table
  → return {status: "paused", checkpoint_id: "..."}

caller (UI / planner) sees paused status
  → displays the agent's question / current state to user
  → user replies

POST /agents/{run_id}/resume  {message: "user reply"}
  → loads checkpoint from DB
  → appends message to conversation history
  → creates a new job for the continued run (links back to original run_id)
  → returns {run_id: "new_continuation_run_id"}
```

### New DB table: `agent_checkpoints`

```sql
CREATE TABLE agent_checkpoints (
    id          VARCHAR PRIMARY KEY,
    run_id      VARCHAR NOT NULL INDEX,
    step_number INTEGER NOT NULL,
    messages_json JSON NOT NULL,        -- full conversation history
    goal        TEXT NOT NULL,
    instructions TEXT NOT NULL,
    allowed_capability_ids JSON NOT NULL,
    max_steps   INTEGER NOT NULL,
    status      VARCHAR NOT NULL DEFAULT 'paused',  -- paused | resumed | expired
    created_at  DATETIME NOT NULL,
    expires_at  DATETIME NOT NULL       -- TTL; gc old checkpoints
);
```

This needs an **Alembic migration** — ask before creating.

### Files to change

| File | Change |
|---|---|
| New migration | `agent_checkpoints` table. |
| `services/api/app/models.py` | `AgentCheckpointRecord` ORM model. |
| `libs/core/models.py` | `AgentCheckpoint` Pydantic model. |
| `libs/tools/agent_tools.py` | New `_wait_for_input_handler` tool. When called: serializes `messages` list to DB via API call, sets loop result to `{status: "paused", checkpoint_id}`. The loop exits cleanly — no exception. |
| `libs/tools/llm_tool_groups.py` | Register `wait_for_input` as a built-in tool always available to the agent. Input schema: `{question: str}`. |
| `services/api/app/main.py` | New endpoints: `GET /agents/{run_id}/checkpoint` (read state) and `POST /agents/{run_id}/resume` (inject message, create continuation job). |
| `libs/core/sub_agent_dispatch.py` | `resume_agent(checkpoint_id, message, api_url) -> str` — calls the resume endpoint, returns new `run_id`. |

### Continuation run

`POST /agents/{run_id}/resume` internally:
1. Loads checkpoint
2. Appends `{"role": "user", "content": message}` to the messages
3. Creates a new job with a special `resume_checkpoint_id` field in the run spec
4. The worker's `agent()` call detects `resume_checkpoint_id`, loads messages from DB instead of starting fresh

The resumed run links back to the original `run_id` via `metadata.parent_run_id`, forming a visible chain in the agents registry.

---

## Feature 4: Worktree Isolation

**What it solves:** Agents doing git operations (branch, commit, PR) work directly in the repo. A failing or abandoned agent can leave the working tree dirty. `workspace_isolation: "worktree"` wraps the agent in a `git worktree`, giving it a clean isolated branch that can be removed on failure or merged on success.

**Prerequisite:** None. This is purely at the tool/workspace layer and can be built independently.

### How it works

```
agent payload has workspace_isolation: "worktree", workspace_path: "/repo"

before loop:
  git worktree add /tmp/agent-{agent_id} -b agent/{agent_id} HEAD
  effective_workspace = /tmp/agent-{agent_id}

loop runs: all file/git tools see effective_workspace, not the original

on success:
  leave the worktree branch in place (user can merge/PR it)
  OR auto-commit + open PR if auto_publish_branch: true

on failure / ToolExecutionError:
  git worktree remove --force /tmp/agent-{agent_id}
  branch is deleted: no dirty state left behind
```

### Files to change

| File | Change |
|---|---|
| `libs/tools/workspace_git.py` | **New.** `create_worktree(repo_path, branch, base="HEAD") -> Path`. `remove_worktree(path, force=False)`. `@contextmanager worktree_context(repo_path, branch_prefix) -> Iterator[Path]` — create on enter, remove on exception, leave on success. Runs `git worktree add/remove` via `subprocess.run`. |
| `libs/tools/llm_tool_groups.py` | Add `workspace_isolation: Literal["none", "worktree"] = "none"` and `workspace_path: str | None` to `AgentRunInput`. |
| `libs/tools/agent_tools.py:agent()` | After parsing payload: if `workspace_isolation == "worktree"` and `workspace_path` is set, enter `worktree_context`. Pass `effective_workspace` through to the `invoke_capability` calls so tools receive the isolated path. |
| `config/capability_registry.yaml` | Update `agent.run` `input_schema_ref: agent_capability_input` (already renamed). Add `workspace_isolation` and `workspace_path` fields to `schemas/agent_capability_input.json`. |

### Passing `effective_workspace` to tools

The agent loop calls tools via `invoke_capability(cap_id, tool_input)`. For tools that accept `workspace_path`, the agent needs to inject the isolated path. Two options:

**Option A (simpler):** The agent rewrites `tool_input["workspace_path"]` to `effective_workspace` for any tool call when `workspace_isolation` is active. This is a shallow interception in `_execute_tool`.

**Option B (cleaner):** Tools that accept `workspace_path` honour a `AGENT_WORKSPACE_PATH` env var if no explicit path is given. The agent sets this env var before the loop and unsets it after. Avoids coupling the agent to individual tool schemas.

Option A is recommended — it's explicit and doesn't rely on env var side effects.

---

## Implementation order and dependencies

```
Feature 1 (sub-agent-as-job)
    ↓
Feature 2 (background)   Feature 4 (worktree) ← independent
    ↓
Feature 3 (resumability)
```

Features 1 and 4 can be started in parallel. Feature 2 requires Feature 1 (uses the same dispatch path). Feature 3 is the largest standalone piece; start after Feature 1 is stable.

## Open questions before starting Feature 3

1. Should resumed runs appear as separate runs in the UI, or as continuations of the same run?
2. What is the checkpoint TTL? (Suggested: 24h for interactive sessions, 7 days for async workflows.)
3. Should `wait_for_input` always be in the agent's tool list, or only when `resumable: true` is set in the payload?
