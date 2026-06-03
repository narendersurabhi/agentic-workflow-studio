# Agent Designer Redesign

**Status:** In progress — Phase A implementing  
**Date:** 2026-05-28  
**Scope:** `StudioWorkbenchSurface.tsx` agent mode, `AgentDefinition` model

---

## Problem Statement

The current "Build Agent" form exposes the internal RunSpec construction to users. Users must understand "steps", "capability IDs", "step IDs", "instructions per step", "raw RunSpec JSON" — implementation concepts that have nothing to do with *defining an agent*.

The `instructions` field — the agent's system prompt that shapes its reasoning — is completely absent from the UI even though it exists in the backend model.

The result: a form that's useful for platform engineers debugging RunSpec structure, not for someone who wants to build and run a useful agent.

---

## What a user actually needs to define an agent

```
Name         — what to call this agent
Description  — what it's for (one sentence)
Instructions — the agent's system prompt:
               how it should reason, what style,
               what to avoid, what to prioritize
Goal         — what to achieve in this specific run
Tools        — the capabilities the agent can call
```

When run, the agent enters a loop:
1. LLM reasons about the goal given the instructions
2. Chooses a tool to call
3. Executes the tool via the capability runtime
4. Analyses the result
5. Repeats until goal is achieved or max steps reached

---

## Backend state (what already exists)

`AgentDefinition` already has all required fields:

| UI field | Backend field |
|---|---|
| Name | `name` |
| Description | `description` |
| Instructions | `instructions` ← **missing from current UI** |
| Goal (default) | `default_goal` |
| Tools | `allowed_capability_ids` |
| Loop engine | `agent_capability_id` (defaults to `codegen.autonomous`) |

The agentic loop itself is `codegen.autonomous`. It accepts a `goal`, uses `instructions` as its system prompt, and calls tools from `allowed_capability_ids` in a ReAct-style loop.

---

## Phase A — UI redesign (no backend changes)

**Target form layout:**

```
┌──────────────────────────────────────────────────────────┐
│ [Profile ▾ unsaved draft]  [v1 ▾]  [Save as] [Publish] [⋯]│
├──────────────────────────────────────────────────────────┤
│                                                          │
│  Name          [ Research Assistant                    ] │
│  Description   [ Finds and summarises web information  ] │
│                                                          │
│  Instructions                                            │
│  ┌────────────────────────────────────────────────────┐  │
│  │ You are a research agent. Think step by step.     │  │
│  │ Use search to gather information, then synthesise │  │
│  │ a clear summary. Cite your sources.               │  │
│  └────────────────────────────────────────────────────┘  │
│                                                          │
│  Goal                                                    │
│  ┌────────────────────────────────────────────────────┐  │
│  │ Find recent papers on AI safety alignment         │  │
│  │ published in 2025 and write a 3-paragraph summary │  │
│  └────────────────────────────────────────────────────┘  │
│                                                          │
│  Tools                                                   │
│  [web.search ✕] [llm.generate ✕] [+ Add from catalog]   │
│                                                          │
│  ▶ Advanced                                              │
│    Capability · Workspace path · Max steps              │
│    Constraints · Additional steps · Raw RunSpec         │
│                                                          │
│                    [ ▶  Run Agent ]                     │
└──────────────────────────────────────────────────────────┘
```

### What changes

| Before | After |
|---|---|
| Steps / RunSpec form is the primary UI | Name + Instructions + Goal + Tools are primary |
| `instructions` not visible anywhere | Prominent textarea, loaded/saved with profile |
| `agent_capability_id` required from user | Defaults to `codegen.autonomous`, hidden |
| Workspace path, max steps visible by default | Moved to Advanced |
| Additional steps visible by default | Moved to Advanced |
| Editor mode toggle visible by default | Moved to Advanced |
| Profile Name/Description inside profile subcard | Lifted into main identity form |
| Profile subcard with full fields | Compact row: select + version + actions |

### Profile header (compact)

```
[Unsaved draft ▾]  [—]  [Save as]  [Publish]  [⋯ New / Save / Delete]
```

- Profile select and version select stay visible
- Save as is primary CTA (creates a new named profile)
- Publish version is secondary CTA (snapshots the current saved profile)
- New, Save (update in-place), Delete move into a `⋯` overflow menu

### Instructions field

The `instructions` field becomes a top-level textarea, equal in prominence to Goal. It is:
- Pre-populated when a profile is loaded
- Saved into `AgentDefinition.instructions` on Save as / Save
- Used as the agent's system prompt by `codegen.autonomous`

Default placeholder: `"You are a helpful agent. Think step by step and use your tools to achieve the goal."`

### Advanced section

Contains everything that was primary before:
- Agent capability (default: `codegen.autonomous`)
- Workspace path (default: `workbench-agent`)
- Max steps (default: `6`)
- Constraints textarea
- Additional steps (+ Add Step)
- Structured Editor / Raw RunSpec toggle
- Context JSON, Title, User Id

---

## Phase B — Generic agentic loop capability (backend required)

`codegen.autonomous` is a coding-specialised agent. It assumes a file workspace and is optimised for code tasks. A general-purpose agent needs a different loop engine.

**New capability: `agent.run`**

Inputs:
- `goal: string`
- `instructions: string` (system prompt, optional)
- `max_steps: int` (default 12)

Behaviour:
- Loads `allowed_capability_ids` from the `AgentDefinition` snapshot attached to the run
- Converts each allowed capability into a Claude tool schema via the capability registry
- Runs a Claude `tool_use` message loop:
  1. Send system (instructions) + user (goal) + tool definitions
  2. If model returns `tool_use` block → execute capability → append result
  3. If model returns text-only block → check if goal achieved → stop or continue
  4. Repeat up to `max_steps`
- Emits step events for each tool call so the debugger panel can show the reasoning trace

This capability requires no file workspace. It works for any combination of tools: search + LLM, document processing, API calls, memory retrieval, etc.

**Frontend impact:** When `agent.run` is registered, the agent capability field in Advanced defaults to `agent.run` instead of `codegen.autonomous`. Workspace path becomes irrelevant and is hidden entirely.

---

## Migration

- Existing saved `AgentDefinition` records continue to work — they have `agent_capability_id = codegen.autonomous`
- The `instructions` field is already in the DB schema; agents created before this UI change have their instructions derived from step instruction text
- No RunSpec format changes; the new form generates the same RunSpec structure as before

---

## Open questions

1. Should the Instructions field show a character/token count hint? (The backend caps at 12,000 chars.)
2. Should Name be required before Run, or can an agent run without being saved?  
   → Current: name only required on Save as, not on Run.
3. For Phase B: should `agent.run` stream intermediate reasoning (chain-of-thought) to the output panel, or only emit tool call events?
