# Skills Design

## Background

Templates today are passive prompt artifacts — a `goal` string and `contextJson` with `{{variable}}` placeholders stored in `localStorage`. They fill a text box; they do not drive execution. They have no awareness of capabilities, no branching logic, and no ability to compose.

Skills replace Templates with an active, backend-persisted concept. A Skill knows *what to run*, not just *what to say*. It can wire specific capabilities into the workflow automatically and branch on `$ARGUMENTS`. The mental model shift: a Template is a filled-in prompt, a Skill is a reusable workflow program.

---

## Current State (Templates)

| Property | Value |
|---|---|
| Storage | `localStorage` keys `ape.templates.v1`, `ape.templates.order.v1`, `ape.template.defaults.v1` |
| Built-ins | Hardcoded as `BUILT_IN_TEMPLATES` in `WorkspaceSurfaceContent.tsx:1546` |
| Variables | `{{key}}` placeholders, per-run or saved-default scope |
| Execution | User fills variables → goal/context strings passed to the planner as-is |
| Capabilities | No awareness — user must reference capability IDs manually in the goal text |
| Composition | Not supported |
| Conditions | Not supported |

**Problems this creates:**
- Templates are lost when the user clears their browser or switches devices.
- Built-in templates require a code deploy to add or update.
- There is no way to guarantee a capability is available when a template references it.
- Complex multi-step workflows must be written as long freeform strings.

---

## Proposed: Skills

A Skill is a named, versioned, backend-persisted workflow program with:
1. **A capability chain** — the ordered list of capabilities the Skill wires in when invoked.
2. **`$ARGUMENTS`** — a single freeform string the user types after the Skill name, substituted wherever `$ARGUMENTS` appears in the goal or step inputs.
3. **Agent instructions** — natural language guidance prepended to the goal, shaping how the agent reasons and behaves throughout execution.
4. **Conditional steps** — steps that only execute when `$ARGUMENTS` satisfies a condition.

---

## Data Model

### `Skill`

```json
{
  "id": "string (uuid)",
  "name": "string",
  "description": "string",
  "version": "integer (monotonic, starts at 1)",
  "built_in": "boolean",
  "owner_id": "string | null (null = global/built-in)",
  "created_at": "datetime",
  "updated_at": "datetime",
  "instructions": "string | null",
  "steps": "SkillStep[]"
}
```

**`instructions`** is a natural language block that guides the agent on *how* to execute this Skill — independent of `$ARGUMENTS`. It is prepended to the goal as plain text at invocation time and stays constant across every run. Use it to express:

- Priorities and constraints ("prefer existing files over creating new ones")
- Output format or tone requirements ("respond in bullet points, no prose")
- Error handling guidance ("if the repository does not exist, stop — do not create one")
- Success criteria ("the task is complete when all steps produce a non-empty output")
- Background knowledge the agent needs to reason correctly

The `goal_template` on a step answers *what to do*. `instructions` answers *how to do it*.

**`$ARGUMENTS`** is the single freeform string the user provides when invoking a Skill — everything typed after the Skill name. It is substituted literally wherever `$ARGUMENTS` appears in `goal_template` or step `inputs`. The agent uses it to infer capability-specific inputs at runtime.

### `SkillStep`

```json
{
  "id": "string (step-local uuid)",
  "order": "integer",
  "type": "capability | goal_text",
  "capability_id": "string | null",
  "goal_template": "string | null",
  "inputs": "Record<string, string | number | boolean>",
  "condition": "SkillCondition | null"
}
```

- `type: capability` — wires a specific capability. `inputs` values may reference `$ARGUMENTS` or be fixed literals; the planner coerces types at runtime.
- `type: goal_text` — a freeform `goal_template` string; use `$ARGUMENTS` as a placeholder where the user's input should be interpolated.

### `SkillCondition`

```json
{
  "operator": "exists | not_exists | contains",
  "value": "string | null"
}
```

Conditions now operate on `$ARGUMENTS` only (there are no named variables). `exists` checks that `$ARGUMENTS` is non-empty. `not_exists` checks that it is empty. `contains` checks that `$ARGUMENTS` includes the given substring. A step whose condition fails is dropped from the chain.

---

## Capability Chain

When a Skill is invoked, its `steps` are resolved in order:

1. `$ARGUMENTS` is captured from the user's input (everything after the Skill name).
2. Each step's `condition` is evaluated against `$ARGUMENTS`; steps that fail are dropped.
3. Remaining steps are split by type: `capability` steps form the ordered capability chain; `goal_text` steps form the natural language goal.
4. `$ARGUMENTS` is substituted into all `goal_template` and `inputs` values.
5. The final goal string is assembled in this order:
   ```
   {instructions}

   {goal_text step 1}
   {goal_text step 2}
   ...
   ```
   If there are no `goal_text` steps, `instructions` alone forms the goal. If there are no `instructions`, the `goal_text` steps alone form the goal.
6. The assembled goal + capability chain are submitted to the planner via the existing job/run path.

The Skill author controls three things: *what capabilities run* (the chain), *what the user provides* (`$ARGUMENTS`), and *how the agent should behave* (`instructions`). The planner's job is reduced to faithful execution rather than open-ended inference.

---

## Storage

### Backend DB schema

```sql
CREATE TABLE skills (
  id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  name        TEXT NOT NULL,
  description TEXT,
  version     INTEGER NOT NULL DEFAULT 1,
  built_in    BOOLEAN NOT NULL DEFAULT FALSE,
  owner_id    TEXT,
  created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  definition  JSONB NOT NULL  -- serialized { instructions, steps: SkillStep[] }
);

CREATE UNIQUE INDEX skills_name_owner_idx ON skills (LOWER(name), owner_id);
CREATE UNIQUE INDEX skills_name_builtin_idx ON skills (LOWER(name)) WHERE built_in = TRUE;
CREATE INDEX skills_owner_idx ON skills (owner_id);
CREATE INDEX skills_built_in_idx ON skills (built_in);
```

Skill names are unique per owner (case-insensitive). Built-in names are globally unique. This means `/skill-name` always resolves unambiguously. The UI pre-loads all visible Skills from `GET /skills` when the command palette is opened and resolves the name client-side — no additional lookup endpoint needed.

**Versioning:** Each save overwrites the current `definition` and increments `version`. No version history is kept — the version number is a staleness indicator for cache-busting, not a rollback mechanism.

**Visibility:** A user sees only their own Skills (`owner_id = caller`) and global built-ins (`owner_id IS NULL`). No cross-user sharing. The `GET /skills` query is `WHERE owner_id = $user_id OR owner_id IS NULL`.

**Built-in authoring:** Built-in Skills are defined in a YAML config file in the repo (e.g. `config/skills/built_ins.yaml`). A startup sync job compares the file against the DB and upserts any additions or changes — no migration needed per update, no deploy required beyond pushing the config file.

---

## API

| Method | Path | Description |
|---|---|---|
| `GET` | `/skills` | List all Skills visible to the caller (built-ins + caller's own) |
| `GET` | `/skills/{id}` | Get a single Skill with full definition |
| `POST` | `/skills` | Create a new user Skill |
| `PUT` | `/skills/{id}` | Update a user Skill (increments `version`) |
| `DELETE` | `/skills/{id}` | Delete a user Skill (built-ins cannot be deleted) |

Invocation is not a separate API call. When the user submits `/skill-name arguments`, the UI resolves the name against the pre-loaded Skills list (already fetched for the command palette), substitutes `$ARGUMENTS` client-side, and submits the assembled goal + capability chain through the existing job/run path.

---

## UI: Skill Authoring

Skills are authored through a step builder that eliminates the need to know capability IDs. The author never types a capability ID manually.

### Capability Picker

Adding a step opens a searchable picker populated from the live `/capabilities` endpoint — the same data the Capability Catalog sidebar already fetches. Each row shows the capability ID, description, and required inputs.

```
┌─────────────────────────────────────────────────┐
│  Search capabilities...                          │
├─────────────────────────────────────────────────┤
│  coding_agent_autonomous                         │
│  Autonomously plan and implement code            │
│  required: goal, workspace_path                  │
│                                                  │
│  codegen.publish_pr                              │
│  Open a pull request from a workspace branch     │
│  required: owner, repo, branch, base             │
│                                                  │
│  github.repo.list                                │
│  Search GitHub repositories                      │
│  required: query                                 │
└─────────────────────────────────────────────────┘
```

Selecting a capability adds a `SkillStep` with `type: capability` and `capability_id` pre-filled. Required inputs are shown as editable fields, each defaulting to `$ARGUMENTS` so the author only overrides what needs a fixed value.

### Step Builder

Steps are displayed as an ordered list. The author can:
- **Add step** — opens the capability picker
- **Add goal text** — inserts a freeform `goal_template` step
- **Reorder** — drag steps up or down
- **Add condition** — attaches a `SkillCondition` to any step via a dropdown (`exists`, `not_exists`, `contains`)
- **Delete** — removes a step

```
┌─────────────────────────────────────────────────┐
│  Steps                              + Add step   │
├─────────────────────────────────────────────────┤
│  1  ⠿  capability: github.repo.list             │
│        query = $ARGUMENTS                        │
│                                                  │
│  2  ⠿  capability: coding_agent_autonomous      │
│        goal = $ARGUMENTS                         │
│        workspace_path = repos/demo               │
│                                                  │
│  3  ⠿  goal_text                                │
│        "Summarise the result for: $ARGUMENTS"    │
│        [condition: $ARGUMENTS contains "pr"]     │
└─────────────────────────────────────────────────┘
```

### Instructions Editor

A text area beneath the step list. Placeholder text suggests common patterns:
- "Stop if any step returns an error."
- "All file paths must be relative to the workspace root."
- "Do not create GitHub repositories."

---

## UI: Command Palette

Skills replace the Template Vault and Capability Catalog sidebars. Both are accessed via a unified command palette triggered by typing `/` inside the goal input box.

```
┌─────────────────────────────────────────────────┐
│  /  coder                              ⌘K        │
├─────────────────────────────────────────────────┤
│  SKILLS                                          │
│  ▸ Coder: Generate Workspace Code               │
│  ▸ GitHub: Generate Code & Open PR              │
│                                                  │
│  CAPABILITIES                                    │
│  ▸ coding_agent_autonomous                       │
│  ▸ codegen.publish_pr                            │
└─────────────────────────────────────────────────┘
```

- Typing `/` opens the palette; typing characters filters both sections simultaneously.
- Selecting a **Skill** places `/skill-name ` in the goal input with the cursor positioned after it — the user types `$ARGUMENTS` inline, exactly as in Claude Code.
- Selecting a **Capability** appends `capability_id` to the goal input (existing "Add to Goal" behaviour).
- The floating "Show templates" and "Show capabilities" buttons are removed.

The "Save as Skill" button appears near the goal input. Clicking it opens a small form:

```
┌─────────────────────────────────────────────────┐
│  Save as Skill                                   │
├─────────────────────────────────────────────────┤
│  Name        [____________________________]      │
│  Description [____________________________]      │
│                                                  │
│  The current goal text becomes a single          │
│  goal_text step. Steps and instructions can      │
│  be edited in the Skills manager.                │
│                                [Cancel] [Save]   │
└─────────────────────────────────────────────────┘
```

This is a quick capture — name + description only. The author refines steps and instructions in the Skills manager after saving.

---

## UI: Skills Management

Accessible via `/help` in the goal input or a dedicated **Skills** page in the nav. Typing `/help` in the goal input returns a formatted response in the chat listing all available Skills:

```
Available Skills:

/coder <goal>          Generate workspace code autonomously
/github-pr <goal>      Generate code and open a GitHub PR
/my-resume-workflow    Build and export a resume

Type /skill-name <arguments> to invoke. Visit Skills page to manage.
```

The page shows two sections: Built-in Skills (read-only) and My Skills (editable).

Each Skill row has **Edit** and **Delete** actions. Edit opens the full step builder described above. Delete is disabled for built-in Skills.

```
┌─────────────────────────────────────────────────┐
│  Skills                          + New Skill     │
├─────────────────────────────────────────────────┤
│  BUILT-IN                                        │
│  Coder: Generate Workspace Code       [View]     │
│  GitHub: Generate Code & Open PR      [View]     │
│                                                  │
│  MY SKILLS                                       │
│  My Resume Workflow         [Edit] [Delete]      │
│  Daily Standup Summary      [Edit] [Delete]      │
└─────────────────────────────────────────────────┘
```

---

## Migration from Templates

| Current | Becomes |
|---|---|
| `BUILT_IN_TEMPLATES` hardcoded in frontend | Defined in `config/skills/built_ins.yaml`, synced to DB on startup |
| User templates in `localStorage` | One-time import prompt on first load after deploy; exports to backend |
| Template variables (`{{key}}`) | Collapsed into `$ARGUMENTS` — multi-variable templates become a single freeform input |
| `goal` string | Single `goal_text` step with `$ARGUMENTS` in place of variable references |
| `contextJson` with a single variable | `inputs` value set to `$ARGUMENTS` |
| `contextJson` with multiple variables | Flagged for manual review — cannot be cleanly auto-migrated; shown in the import prompt with the raw JSON for the user to rework as a proper Skill |

Templates with no capability references and a single variable map cleanly to a `goal_text` step. Templates with multiple named variables are imported as a `goal_text` step containing the raw original goal string, marked with a "Needs review" badge in the Skills manager so the user knows to wire them up properly.

---

## Decisions Log

| Decision | Choice | Rationale |
|---|---|---|
| Visibility | Per-owner + built-ins only | No cross-user sharing complexity; single-user context is sufficient for now |
| Version history | Overwrite, no history | Version number used for cache-busting only; rollback not required |
| Built-in authoring | YAML config + startup sync | Avoids code deploys for content changes; config file is reviewable in PRs |
| Composition | Not supported — Skills are flat | Matches Claude Code; avoids cycle detection complexity; deferred until there is user demand |
| `instructions` injection | Prepended to goal as plain text | No `ContextEnvelope` changes required; simple and consistent with how the planner already reads the goal |
| Invocation | Client-side expansion, no `/invoke` endpoint | Matches Claude Code; the UI fetches the Skill definition and substitutes `$ARGUMENTS` before submitting |
| Skills management | Dedicated page + `/help` listing | DB-backed add/edit/delete; built-ins are read-only |
| Variable model | Single `$ARGUMENTS` string | Matches Claude Code; removes authoring friction; named variables deferred until there is user demand |
| Condition complexity | Operates on `$ARGUMENTS` only (`exists`, `not_exists`, `contains`) | No named variables to condition on; keeps authoring simple |
