# Agentic Workflow Studio — Claude Context

> This repo also has `AGENTS.md`, a tool-agnostic version of this file that Codex CLI (and any other agent) reads. The two are kept in sync — if you update one, update the other. `AGENTS.md` additionally has a **Multi-Agent Coordination Protocol** section for when multiple agents (Claude sessions, subagents, Codex runs) are working the migration issue backlog in parallel — read it before claiming a `migration`-labeled GitHub issue.

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
| `ui` | `services/ui/` | Next.js 14 frontend (migrating to 16 — see Phase 5 migration issue). App Router. Tailwind CSS. |

**Infrastructure:** PostgreSQL (jobs/plans/tasks/chat, migrating 15→18), Redis (pub/sub, job queue, migrating to Valkey), Qdrant (vector store, pinned `v1.19.0`).

---

## Library Map

| Library | Path | Role |
|---|---|---|
| `libs/core` | `libs/core/` | Shared business logic: tool registry, LLM provider, models, memory client, capability registry, governance, tracing. |
| `libs/tools` | `libs/tools/` | Tool implementations: file I/O, workspace, memory, HTTP, document rendering, GitHub, coding agent, LLM tools. |
| `libs/framework` | `libs/framework/` | Tool runtime primitives: `Tool`, `ToolSpec`, `ToolRegistry`, execution, validation, timeouts. |

---

## Tool System

All tools live in `libs/tools/`. The registry is assembled in `libs/core/tool_registry.py`.

**Key types** (all in `libs/core/tool_registry.py` after recent merge):
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

**Schemas:** Moving to Pydantic-generated JSON Schema (`model_json_schema()`). New tools should use Pydantic `BaseModel` with `ConfigDict(extra="forbid")` and `Field(description=...)`.

---

## Database

- ORM: SQLAlchemy (models in `services/api/app/models.py`)
- Migrations: Alembic (`services/api/app/alembic/versions/`, 18 migration files)
- `create_all()` runs at startup but does NOT add columns to existing tables
- Schema changes need an Alembic migration — do not add columns only in the ORM model
- Do not touch Alembic migration files without asking first

---

## Dev Workflow

```bash
make up             # start full Docker Compose stack
make lint            # ruff check (uv-managed ephemeral venv — see UV_QUALITY_DEPS in Makefile)
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

All Python dependency installs — Dockerfiles, CI, and the Makefile's `uv run --with ...` targets — go through `uv`, not raw `pip`. `ruff` and `mypy` versions are pinned (`ruff==0.16.4` in `UV_QUALITY_DEPS`) because unpinned versions silently drift their default rule set — this broke CI for months undetected (see issue #110). Don't remove that pin.

---

## Key Conventions

- **Python:** `from __future__ import annotations` at top of every file. Type hints everywhere.
- **No comments** unless the WHY is non-obvious (hidden constraint, workaround, subtle invariant).
- **Tool handlers** return `Dict[str, Any]` and raise `ToolExecutionError` on failure — never return error dicts.
- **`libs/core/tool_registry.py`** is the single source of truth for tool assembly. `tool_catalog.py` and `tool_bootstrap.py` no longer exist (merged in).
- **Frontend** uses App Router (`services/ui/src/app/`). CSS custom properties for theming — use `text-text-hi/md/lo`, `bg-surface-1/2`, `border-subtle` tokens.
- **Secrets** live in `.env` — never commit that file.
- **Ruff:** every `pyproject.toml` with a `[tool.ruff]` block also declares `[tool.ruff.lint] select = ["E4", "E7", "E9", "F"]` explicitly. Don't delete this — it's what keeps the lint gate deterministic across ruff versions instead of silently riding ruff's evolving defaults.

---

## Known Architectural Issues (fix before adding to these areas)

**`libs/core/tool_registry.py` is too large (~1300 lines)**
Concrete handler implementations (`_math_eval`, `_write_text_file`, `_http_fetch`, `_llm_generate`, etc.) belong in `libs/tools/`, not `libs/core/`. The file currently combines handler code, DI wiring, registration, and the public factory — these should be split. Do not add new handler implementations here; put them in `libs/tools/` instead.

**`libs/core/intent_contract.py` (~1900 lines) and `libs/core/models.py` (~1460 lines)** are similarly oversized and overdue for the same split treatment as `tool_registry.py`.

**Alembic wired into startup** ✓ resolved
`_init_db()` now calls `_run_migrations()` which runs `alembic upgrade head` before `create_all()`. Every deployment automatically applies pending migrations. Every ORM model change still needs an Alembic migration — `create_all()` is kept as a safety net for fresh databases but migrations are the authoritative schema source.

**No Alembic baseline migration**
The oldest migration (`20260204_add_task_intent`, `down_revision = None`) assumes `jobs`, `plans`, `tasks`, `chat_sessions`, `chat_messages` already exist. Fresh DB deployments work only because `create_all()` runs first. This ordering is undocumented and fragile. A proper baseline migration is needed.

**`default_registry()` and `build_default_registry()` are duplicates**
Both produce identical results. Callers will pick one inconsistently. One should be removed — do not add new call sites for `default_registry()`, prefer `build_default_registry()`. `_agent()`'s in-process fallback path in `tool_registry.py` currently violates this itself, and rebuilds the whole registry on every tool call inside an agent loop (up to 32x per run) as a side effect — needs fixing.

**6 tool input schemas remain as raw dicts**
These use `anyOf`/`not` at the top level that can't be expressed cleanly in Pydantic without discriminated unions: `llm_generate`, `llm_generate_document_spec`, `llm_generate_document_spec_from_markdown`, `llm_iterative_improve_document_spec`, `llm_iterative_improve_openapi_spec`, `docx_render`. All other schemas have been migrated. New tools must use Pydantic `BaseModel` with `ConfigDict(extra="forbid")` and `Field(description=...)`.

**Sub-agent-as-job isolation is built but not activated**
`POST /internal/sub-agent`, the poll loop in `libs/core/sub_agent_dispatch.py`, and the dispatch hooks all exist, but `API_URL` is never set in `docker-compose.yml` or `deploy/k8s/`, so every nested `agent.run` call silently falls back to in-process recursion instead. If this ever gets activated: `SubAgentDispatchRequest.depth` is captured into run metadata but never fed back into the new agent's recursion counter, so recursive `agent.run` chains would become unbounded across process boundaries — fix that first.

**Two parallel policy-enforcement mechanisms**
The dedicated `policy` service (event-driven, off by default) and the in-process `capability_runtime.evaluate_allowlist` (always on) both claim the "tool allow/deny" job. Not yet resolved which is authoritative — see the Service Map entry above.

**`agent_locks` table + API exist but nothing calls them**
`GET/POST /runs/{run_id}/locks` has a full schema and Alembic migration but no caller anywhere in `libs/tools`, `libs/core`, or `services/worker`.

---

## What NOT to Do

- Do not create Alembic migration files without asking
- Do not `git push --force` to main
- Do not add `time.sleep()` to tool handlers
- Do not add fallback/error-swallowing in tool handlers — let errors propagate so `ToolRegistry` can classify them
- Do not add new handler implementations in `libs/core/tool_registry.py` — put them in `libs/tools/`
- Do not add new raw dict `input_schema`/`output_schema` — use Pydantic models instead (see Tool System section for pattern)
- Do not call `default_registry()` — use `build_default_registry()` instead
- Do not leave `ruff`/`mypy` version floors unpinned in anything you add to `Makefile`/CI

---

## Multi-Agent Coordination

The migration to a current tech stack is tracked entirely via GitHub issues (`migration` label, repo `narendersurabhi/agentic-workflow-studio`) and worked by multiple agents in parallel — other Claude sessions/subagents, and potentially Codex CLI runs, all in their own git worktrees. Before claiming a `migration` issue or touching the same files another in-flight issue owns, read `AGENTS.md`'s **Multi-Agent Coordination Protocol** section — it has the claiming protocol, worktree/branch convention, and a file-ownership map by phase so parallel work doesn't collide.
