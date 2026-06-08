# Agentic Workflow Studio — Claude Context

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
| `policy` | `services/policy/` | Tool allow/deny decisions. Worker consults this before executing high-risk tools. |
| `rag_retriever` | `services/rag_retriever/` | RAG embedding and semantic search over Qdrant. |
| `ui` | `services/ui/` | Next.js 14 frontend. App Router. Tailwind CSS. |

**Infrastructure:** PostgreSQL (jobs/plans/tasks/chat), Redis (pub/sub, job queue), Qdrant (vector store).

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
make up          # start full Docker Compose stack
make test        # run all tests
make lint        # ruff
make typecheck   # mypy
make format      # ruff format
```

UI: http://localhost:3002 | API: http://localhost:18000 | API docs: http://localhost:18000/docs

After changing Python code in a service, rebuild its container:
```bash
docker compose build api && docker compose up -d api
```

---

## Key Conventions

- **Python:** `from __future__ import annotations` at top of every file. Type hints everywhere.
- **No comments** unless the WHY is non-obvious (hidden constraint, workaround, subtle invariant).
- **Tool handlers** return `Dict[str, Any]` and raise `ToolExecutionError` on failure — never return error dicts.
- **`libs/core/tool_registry.py`** is the single source of truth for tool assembly. `tool_catalog.py` and `tool_bootstrap.py` no longer exist (merged in).
- **Frontend** uses App Router (`services/ui/src/app/`). CSS custom properties for theming — use `text-text-hi/md/lo`, `bg-surface-1/2`, `border-subtle` tokens.
- **Secrets** live in `.env` — never commit that file.

---

## Known Architectural Issues (fix before adding to these areas)

**`libs/core/tool_registry.py` is too large (~1400 lines)**
Concrete handler implementations (`_math_eval`, `_write_text_file`, `_http_fetch`, `_llm_generate`, etc.) belong in `libs/tools/`, not `libs/core/`. The file currently combines handler code, DI wiring, registration, and the public factory — these should be split. Do not add new handler implementations here; put them in `libs/tools/` instead.

**Alembic not wired into startup**
`_init_db()` in `services/api/app/main.py` runs `create_all()` but not `alembic upgrade head`. Adding a column to an ORM model without a migration silently breaks existing deployments (caused a production login failure with the `preferences` column). Every ORM model change needs an Alembic migration. Option to wire `alembic upgrade head` into startup is planned but not done yet — do not implement without asking.

**No Alembic baseline migration**
The oldest migration (`20260204_add_task_intent`, `down_revision = None`) assumes `jobs`, `plans`, `tasks`, `chat_sessions`, `chat_messages` already exist. Fresh DB deployments work only because `create_all()` runs first. This ordering is undocumented and fragile. A proper baseline migration is needed.

**`default_registry()` and `build_default_registry()` are duplicates**
Both produce identical results. Callers will pick one inconsistently. One should be removed — do not add new call sites for `default_registry()`, prefer `build_default_registry()`.

**6 tool input schemas remain as raw dicts**
These use `anyOf`/`not` at the top level that can't be expressed cleanly in Pydantic without discriminated unions: `llm_generate`, `llm_generate_document_spec`, `llm_generate_document_spec_from_markdown`, `llm_iterative_improve_document_spec`, `llm_iterative_improve_openapi_spec`, `docx_render`. All other schemas have been migrated. New tools must use Pydantic `BaseModel` with `ConfigDict(extra="forbid")` and `Field(description=...)`.

---

## What NOT to Do

- Do not run `alembic upgrade head` or create migration files without asking
- Do not `git push --force` to main
- Do not add `time.sleep()` to tool handlers
- Do not add fallback/error-swallowing in tool handlers — let errors propagate so `ToolRegistry` can classify them
- Do not add new handler implementations in `libs/core/tool_registry.py` — put them in `libs/tools/`
- Do not add new raw dict `input_schema`/`output_schema` — use Pydantic models instead (see Tool System section for pattern)
- Do not call `default_registry()` — use `build_default_registry()` instead
