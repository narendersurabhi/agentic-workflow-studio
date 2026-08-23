# AGENTS.md — Agentic Workflow Studio

This file is the shared source of truth for any coding agent working in this repo — Claude Code, Codex CLI, or otherwise. It mirrors `CLAUDE.md`; the two should be kept in sync. If you're a human reading this: `CLAUDE.md` and this file cover the same ground, `CLAUDE.md` is Claude Code's default entry point and this one is everyone else's (and Claude Code's, when a task involves coordinating with another agent).

Full-stack platform for authoring and running AI-powered workflows through chat and a visual DAG editor. Users describe a goal in chat; the planner breaks it into a typed execution plan; the worker executes each step using tools; results stream back to the UI.

---

## Service Map

| Service | Path | Role |
|---|---|---|
| `api` | `services/api/` | Main REST + WebSocket API. Auth, jobs, chat, plans, events. FastAPI + SQLAlchemy + PostgreSQL. |
| `planner` | `services/planner/` | LLM-powered planner. Takes a user goal and produces a typed execution plan (JSON DAG). |
| `worker` | `services/worker/` | Executes plan steps. Calls tools via `ToolRegistry`. Reads/writes job state via API. |
| `coder` | `services/coder/` | Code generation agent. Called by worker via HTTP when a step requires coding tasks. |
| `critic` | `services/critic/` | Reviews/scores generated content. Called by worker for quality gating. |
| `policy` | `services/policy/` | Tool allow/deny decisions. Async event consumer; off by default (`POLICY_GATE_ENABLED=false`) — the always-on gate is `capability_runtime.evaluate_allowlist` in `services/worker/app/execution_service.py`. |
| `rag_retriever` | `services/rag_retriever/` (service name `rag-retriever-mcp` in compose/k8s) | RAG embedding and semantic search over Qdrant. |
| `ui` | `services/ui/` | Next.js 14 frontend (migrating to 16 — see Phase 5). App Router. Tailwind CSS. |

**Infrastructure:** PostgreSQL (jobs/plans/tasks/chat, migrating 15→18), Redis (pub/sub, job queue, migrating to Valkey), Qdrant (vector store, pinned `v1.19.0`).

---

## Library Map

| Library | Path | Role |
|---|---|---|
| `libs/core` | `libs/core/` | Shared business logic: tool registry, LLM provider, models, memory client, capability registry, governance, tracing. |
| `libs/tools` | `libs/tools/` | Tool implementations: file I/O, workspace, memory, HTTP, document rendering, GitHub, coding agent, LLM tools, agent harness (`agent_tools.py`). |
| `libs/framework` | `libs/framework/` | Tool runtime primitives: `Tool`, `ToolSpec`, `ToolRegistry`, execution, validation, timeouts. |

---

## Tool System

All tools live in `libs/tools/`. The registry is assembled in `libs/core/tool_registry.py`.

**Key types** (all in `libs/core/tool_registry.py`):
- `ToolCatalogHandlers` — dataclass of all handler callables (dependency injection)
- `register_default_tools()` — registers all tools into a `ToolRegistry`
- `build_tool_registry()` — register + plugins + governance
- `build_default_registry()` — convenience: wires real handlers then calls `build_tool_registry()`

**Tool spec pattern** (`libs/framework/tool_runtime.py`):
```python
Tool(
    spec=ToolSpec(name=..., description=..., input_schema={...}, output_schema={...}, ...),
    handler=some_callable,
)
```

**Adding a new tool:**
1. Add handler function in `libs/tools/` or `libs/core/tool_registry.py`
2. Add field to `CoreOpsHandlers` or `ToolCatalogHandlers` if it needs DI
3. Register via `registry.register(Tool(...))` inside the appropriate `register_*` function
4. Wire handler in `_build_core_ops_handlers()` or `_default_catalog_handlers()`

**Schemas:** Pydantic-generated JSON Schema (`model_json_schema()`) is the standard. New tools should use Pydantic `BaseModel` with `ConfigDict(extra="forbid")` and `Field(description=...)`.

---

## Database

- ORM: SQLAlchemy (models in `services/api/app/models.py`)
- Migrations: Alembic (`services/api/app/alembic/versions/`)
- `create_all()` runs at startup but does NOT add columns to existing tables
- Schema changes need an Alembic migration — do not add columns only in the ORM model
- Do not touch Alembic migration files without asking first

---

## Dev Workflow

```bash
make up             # start full Docker Compose stack
make lint            # ruff check (uv-managed, ephemeral venv — see UV_QUALITY_DEPS in Makefile)
make format-check    # ruff format --check
make typecheck       # mypy --strict on libs/core (see mypy.ini for scope/overrides)
make test            # pytest, full suite
```

UI: http://localhost:3002 | API: http://localhost:18000 | API docs: http://localhost:18000/docs

UI checks: `cd services/ui && npm run lint && npm run typecheck && npm test`

After changing Python code in a service, rebuild its container:
```bash
docker compose build api && docker compose up -d api
```

All Python dependency installs — in Dockerfiles, in CI, and via the Makefile's `uv run --with ...` targets — go through `uv`, not raw `pip`. `ruff` and `mypy` versions are pinned (`ruff==0.16.4` in `Makefile`'s `UV_QUALITY_DEPS`) specifically because unpinned versions silently drift their default behavior (this broke CI for months — see issue #110 and the Phase 1 PR for the full story). Do not remove that pin without a reason.

---

## Key Conventions

- **Python:** `from __future__ import annotations` at top of every file. Type hints everywhere.
- **No comments** unless the WHY is non-obvious (hidden constraint, workaround, subtle invariant).
- **Tool handlers** return `Dict[str, Any]` and raise `ToolExecutionError` on failure — never return error dicts.
- **`libs/core/tool_registry.py`** is the single source of truth for tool assembly. `tool_catalog.py` and `tool_bootstrap.py` no longer exist (merged in).
- **Frontend** uses App Router (`services/ui/src/app/`). CSS custom properties for theming — use `text-text-hi/md/lo`, `bg-surface-1/2`, `border-subtle` tokens.
- **Secrets** live in `.env` — never commit that file.
- **Ruff:** every `pyproject.toml` with a `[tool.ruff]` block also declares `[tool.ruff.lint] select = ["E4", "E7", "E9", "F"]` explicitly. Do not delete this to "simplify" — it's what keeps the lint gate deterministic across ruff versions.

---

## Known Architectural Issues (fix before adding to these areas)

**`libs/core/tool_registry.py` is too large (~1300 lines)**
Concrete handler implementations belong in `libs/tools/`, not `libs/core/`. Do not add new handler implementations here.

**`libs/core/intent_contract.py` (~1900 lines) and `libs/core/models.py` (~1460 lines)** are similarly oversized and overdue for a split, same pattern as `tool_registry.py`.

**`_agent()`'s fallback path in `libs/core/tool_registry.py` calls `default_registry()`**, which is explicitly forbidden below, and rebuilds the entire tool registry on every single tool call inside an agent loop (up to 32x per run). Needs fixing: call `build_default_registry()` once, outside the loop.

**Sub-agent-as-job isolation is built but not activated**
`POST /internal/sub-agent`, the poll loop in `libs/core/sub_agent_dispatch.py`, and the dispatch hooks exist, but `API_URL` is never set in `docker-compose.yml` or `deploy/k8s/`, so every nested `agent.run` call silently falls back to in-process recursion. If this gets activated, note that `SubAgentDispatchRequest.depth` is captured into run metadata but never fed back into the new agent's recursion counter — fix that first, or recursive `agent.run` chains become unbounded across process boundaries.

**No Alembic baseline migration**
The oldest migration assumes `jobs`, `plans`, `tasks`, `chat_sessions`, `chat_messages` already exist. Fresh DB deployments work only because `create_all()` runs first. Undocumented and fragile.

**`default_registry()` and `build_default_registry()` are duplicates**
Do not add new call sites for `default_registry()` — use `build_default_registry()`.

**6 tool input schemas remain as raw dicts**
`llm_generate`, `llm_generate_document_spec`, `llm_generate_document_spec_from_markdown`, `llm_iterative_improve_document_spec`, `llm_iterative_improve_openapi_spec`, `docx_render` use `anyOf`/`not` at the top level that resists clean Pydantic discriminated unions. All other schemas are migrated. New tools must use Pydantic.

**Two parallel policy-enforcement mechanisms**
The dedicated `policy` service (event-driven, off by default) and the in-process `capability_runtime.evaluate_allowlist` (always on) both claim the "tool allow/deny" job. Not yet resolved which is authoritative.

**`agent_locks` table + API exist but nothing calls them**
`GET/POST /runs/{run_id}/locks` has a full schema and migration but no caller anywhere in `libs/tools`, `libs/core`, or `services/worker`.

---

## What NOT to Do

- Do not create Alembic migration files without asking
- Do not `git push --force` to main
- Do not add `time.sleep()` to tool handlers
- Do not add fallback/error-swallowing in tool handlers — let errors propagate so `ToolRegistry` can classify them
- Do not add new handler implementations in `libs/core/tool_registry.py` — put them in `libs/tools/`
- Do not add new raw dict `input_schema`/`output_schema` — use Pydantic models instead
- Do not call `default_registry()` — use `build_default_registry()` instead
- Do not leave `ruff`/`mypy` version floors unpinned in anything you add to `Makefile`/CI — see the Dev Workflow section above for why

---

## Multi-Agent Coordination Protocol

This repo is being migrated to a current tech stack (Python 3.13, Next.js 16/React 19/Tailwind 4, Postgres 18, Redis→Valkey — see the `migration` label on GitHub issues) with **multiple agents working in parallel** — different Claude Code sessions, subagents, and Codex CLI runs, potentially all active at once. This section is how you avoid stepping on each other.

### The task board is GitHub Issues, not this file

Repo: `narendersurabhi/agentic-workflow-studio` (the git remote may still say `planner-executer-agentic-platform` — GitHub redirects it, but prefer updating your remote if you're setting one up fresh).

```bash
gh issue list --repo narendersurabhi/agentic-workflow-studio --label migration --state open
```

Every migration issue has a checklist body describing its scope and a verification section. Do not start work that isn't tracked by an issue — if you find something that needs fixing that isn't already covered, **file a new issue with the `migration` label first**, referencing whatever issue or PR led you to it, then work it.

### Before you start an issue

1. Check the issue isn't already claimed: look for a comment saying "Claiming this" with no matching completion. If another agent claimed it more than a few hours ago with no activity, it's fair to ask (comment) before taking over — don't just silently start.
2. Comment on the issue: `Claiming this — starting work as <agent identifier, e.g. "Claude subagent" or "Codex CLI">.`
3. Create an isolated workspace — **do not work directly in another agent's checkout**:
   - Claude Code: use a git worktree (`Agent` tool with `isolation: "worktree"`, or manually `git worktree add ../awe-issue-NNN -b migration/issue-NNN-<slug>`)
   - Codex CLI / manual: `git worktree add ../awe-issue-NNN -b migration/issue-NNN-<slug>` from the repo root, then `cd` into it
   - Branch naming: `migration/issue-<number>-<short-slug>` (e.g. `migration/issue-106-valkey`)

### File-ownership map (who touches what, by phase)

Phases are scoped to be as disjoint as possible on purpose. Two agents on different phases should almost never conflict; if your issue's scope grows into another phase's files, stop and comment on both issues before proceeding.

| Issue | Phase | Primary files |
|---|---|---|
| #105 | 2 — Backend Python 3.13 | All 7 `services/*/Dockerfile`, `services/*/pyproject.toml`, `mypy.ini`/root `pyproject.toml` (`python_version`), `services/coder/app/main.py`, `services/rag_retriever/app/main.py`, `services/api/app/database.py` |
| #106 | 3 — Redis → Valkey | `docker-compose.yml` (redis service only), `deploy/k8s/redis.yaml` |
| #107 | 4 — Postgres 15→18 | `docker-compose.yml` (db service only), `deploy/k8s/postgres.yaml`, `.github/workflows/ci.yml` (postgres service block only) — **do not start until #105 is merged** (explicit dependency, not just convention) |
| #108 | 5 — Next.js 16/React 19/Tailwind 4 | Everything under `services/ui/` — fully isolated from the Python-side issues |
| #109 | 6 — CI/CD polish | `.github/workflows/*.yml` (actions version bumps, propagating the UI job) — **coordinate with whoever has #107 open**, you both touch `ci.yml` |
| #110 | mypy debt cleanup | `libs/core/chat_routing_feedback.py`, `feedback_eval.py`, `chat_routing_reranker.py`, `chat_routing_calibrator.py`, `intent_contract.py`, `intent_eval.py`, `planner_contracts.py`, `execution_contracts.py`, `run_specs.py`, plus removing the corresponding override block in `mypy.ini` as each file is cleared |

`docker-compose.yml` and `ci.yml` are the two files with more than one owner (#106/#107 both touch compose; #107/#109 both touch ci.yml). Whoever merges second should expect a trivial rebase, not a real conflict, since the touched lines don't overlap — but check before force-resolving.

### While working

- Run the actual verification commands from the issue before claiming done — usually some combination of `make lint`, `make format-check`, `make typecheck`, `make test`, `docker compose build <service>`, and for UI work `npm run lint && npm run typecheck && npm test && npm run build`.
- Tick checklist boxes in the issue body as you complete each sub-item (`gh issue edit <number> --body "..."` or via the GitHub UI) so other agents and the user can see live progress without reading your transcript.
- If you get blocked or the scope turns out bigger than expected, comment on the issue saying so — don't silently abandon it or silently expand scope.
- If you discover a new problem while working an issue (this happens constantly — Phase 0 and Phase 1 alone turned up a repo-wide CI outage, PII in tracked files, and a dead feature flag), **file a new issue immediately** with the `migration` label, cross-link it from where you found it, and either fix it inline if small and in-scope, or leave it for pickup.

### When done

1. Push your branch, open a PR against `framework-improvements` (the current integration branch — confirm this hasn't changed before opening).
2. Comment on the issue with a summary and link the PR.
3. Do not close the issue yourself unless asked — leave that for the user's review, or close it only once the PR is merged.
4. Remove your worktree once merged: `git worktree remove ../awe-issue-NNN`.

### Ground rules (apply on top of everything above)

- Never force-push a branch another agent might be building on.
- Never merge your own PR without the user's go-ahead unless explicitly told this session is fully autonomous.
- If your issue and another agent's issue turn out to genuinely conflict (not just adjacent lines in the same file), stop and surface it — don't silently pick a resolution for both.
